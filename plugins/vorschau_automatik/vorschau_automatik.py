import io
import logging
import math
import threading

from PIL import Image

from photobooth.models.genericstats import GenericStats, SubStats
from photobooth.plugins import hookimpl
from photobooth.plugins.base_plugin import BasePlugin

from .config import VorschauAutomatikConfig

logger = logging.getLogger(__name__)

ISO_STEPS = [100, 200, 400, 800, 1600, 3200, 6400]
SHUTTER_STEPS = ["1/1000", "1/500", "1/250", "1/125", "1/60", "1/30"]  # fast -> slow
GAMMA = 2.2  # jpeg mean grey value vs. light: stops = gamma * log2(target/mean)


def frame_mean(data: bytes) -> float:
    """mean grey value 0-255 of a jpeg frame"""
    with Image.open(io.BytesIO(data)) as img:
        grey = img.convert("L")
        grey.thumbnail((160, 160))
    hist = grey.histogram()
    total = sum(hist) or 1
    return sum(level * count for level, count in enumerate(hist)) / total


def nearest_index(steps: list, value) -> int:
    return min(range(len(steps)), key=lambda i: abs(steps[i] - value))


def split_exposure(total: int, iso_range: tuple[int, int], shutter_range: tuple[int, int], iso_base: int, shutter_base: int) -> tuple[int, int]:
    """distribute whole stops relative to the base to iso first, the remainder to the shutter. returns (iso index, shutter index)"""
    iso_idx = max(iso_range[0], min(iso_range[1], iso_base + total))
    remainder = total - (iso_idx - iso_base)
    shutter_idx = max(shutter_range[0], min(shutter_range[1], shutter_base + remainder))
    return iso_idx, shutter_idx


class VorschauAutomatik(BasePlugin[VorschauAutomatikConfig]):
    def __init__(self):
        super().__init__()
        self._config: VorschauAutomatikConfig = VorschauAutomatikConfig()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._exposure = 0.0  # stops relative to the base values
        self._applied: dict[str, str] = {}
        self._last_mean: float | None = None
        self._last_frame_id: int | None = None
        self._settle = 0  # measurements to skip after a change, so the new setting reached the frames
        self._corrections = 0

    def _backend(self):
        from photobooth.container import container  # lazy: avoids circular import while the app config loads plugins

        return container.acquisition_service._video_backend

    def _ranges(self):
        lim = self._config.limits
        iso_base = nearest_index(ISO_STEPS, lim.iso_base)
        shutter_base = SHUTTER_STEPS.index(lim.shutter_base) if lim.shutter_base in SHUTTER_STEPS else SHUTTER_STEPS.index("1/60")
        iso_range = (nearest_index(ISO_STEPS, lim.iso_min), nearest_index(ISO_STEPS, lim.iso_max))
        slowest = SHUTTER_STEPS.index(lim.shutter_slowest) if lim.shutter_slowest in SHUTTER_STEPS else len(SHUTTER_STEPS) - 1
        fastest = SHUTTER_STEPS.index(lim.shutter_fastest) if lim.shutter_fastest in SHUTTER_STEPS else 0
        shutter_range = (min(fastest, shutter_base), max(slowest, shutter_base))
        iso_range = (min(iso_range[0], iso_base), max(iso_range[1], iso_base))
        return iso_base, shutter_base, iso_range, shutter_range

    def _params(self) -> dict[str, str]:
        iso_base, shutter_base, iso_range, shutter_range = self._ranges()
        iso_idx, shutter_idx = split_exposure(round(self._exposure), iso_range, shutter_range, iso_base, shutter_base)
        return {"iso": str(ISO_STEPS[iso_idx]), "shutterspeed": SHUTTER_STEPS[shutter_idx]}

    def _limits_in_stops(self) -> tuple[float, float]:
        iso_base, shutter_base, iso_range, shutter_range = self._ranges()
        return (
            float((iso_range[0] - iso_base) + (shutter_range[0] - shutter_base)),
            float((iso_range[1] - iso_base) + (shutter_range[1] - shutter_base)),
        )

    def _apply(self, backend, params: dict[str, str]) -> None:
        self._applied = params
        backend.video_parameter_overrides = dict(params)  # also used after every later switch to video mode
        backend.live_parameter_request = dict(params)  # applied now by the backend thread while the live view runs
        self._settle = 2

    def adjust(self, mean: float, backend) -> None:
        """one control step based on the mean of a preview frame"""
        common = self._config.common
        if self._settle > 0:
            self._settle -= 1
            return
        if abs(mean - common.target_mean) <= common.tolerance:
            return
        delta = GAMMA * math.log2(common.target_mean / max(mean, 1.0)) * common.damping
        delta = max(-common.max_step_stops, min(common.max_step_stops, delta))
        min_e, max_e = self._limits_in_stops()
        self._exposure = max(min_e, min(max_e, self._exposure + delta))
        params = self._params()
        if params != self._applied:
            self._corrections += 1
            logger.info(f"preview automatic: mean={mean:.1f} target={common.target_mean} -> {params}")
            self._apply(backend, params)

    def _tick(self) -> None:
        backend = self._backend()
        machine = getattr(backend, "_mode_machine", None)
        if machine is None or machine.active_mode != "video":
            return  # live view not running; never wake the camera up just for measuring
        frame = backend._lores_data[0]
        data = frame.data
        if not data or id(data) == self._last_frame_id:
            return
        self._last_frame_id = id(data)

        if not self._applied:
            # first run: set explicit base values once, camera "Auto" in the preview is not controllable
            self._apply(backend, self._params())
            return
        mean = frame_mean(data)
        self._last_mean = mean
        self.adjust(mean, backend)

    def _run(self) -> None:
        while not self._stop.wait(self._config.common.interval):
            if not self._config.common.enabled:
                continue
            try:
                self._tick()
            except Exception as exc:
                logger.warning(f"preview automatic failed: {exc}")

    @hookimpl
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vorschau_automatik", daemon=True)
        self._thread.start()

    @hookimpl
    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        try:
            backend = self._backend()
            if self._applied and dict(backend.video_parameter_overrides) == self._applied:
                backend.video_parameter_overrides = {}
        except Exception:
            pass
        self._applied = {}
        self._exposure = 0.0
        self._settle = 0
        self._last_frame_id = None

    @hookimpl
    def get_stats(self) -> GenericStats | None:
        return GenericStats(
            id="vorschau_automatik",
            name="Vorschau-Automatik",
            stats=[
                SubStats("Letzte Helligkeit", self._last_mean, decimals=1),
                SubStats("Korrektur (Blendenstufen)", round(self._exposure, 1)),
                SubStats("Aktive Werte", ", ".join(f"{k}={v}" for k, v in self._applied.items()) or "noch nicht gesetzt"),
                SubStats("Anpassungen gesamt", self._corrections),
            ],
        )
