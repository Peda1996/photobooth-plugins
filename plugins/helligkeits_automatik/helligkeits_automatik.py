import logging
import math
from pathlib import Path

from PIL import Image

from photobooth.models.genericstats import GenericStats, SubStats
from photobooth.models.stillretry import StillRetry
from photobooth.plugins import hookimpl
from photobooth.plugins.base_plugin import BasePlugin

from .config import HelligkeitsAutomatikConfig

logger = logging.getLogger(__name__)

ISO_STEPS = [100, 200, 400, 800, 1600, 3200, 6400]
SHUTTER_STEPS = ["1/4000", "1/2000", "1/1000", "1/500", "1/250", "1/125", "1/60", "1/30"]  # fast -> slow
GAMMA = 2.2  # jpeg mean grey value vs. light: stops = gamma * log2(target/mean)


_cascade = None


def detect_faces(grey: Image.Image) -> list[tuple[int, int, int, int]]:
    """returns face boxes (x, y, w, h) found with the OpenCV haar cascade, empty list if none or opencv is unavailable"""
    global _cascade
    try:
        import cv2
        import numpy as np

        if _cascade is None:
            _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = _cascade.detectMultiScale(np.asarray(grey), scaleFactor=1.15, minNeighbors=5, minSize=(max(24, grey.width // 25), max(24, grey.width // 25)))
        return [tuple(int(v) for v in f) for f in faces]
    except Exception as exc:
        logger.debug(f"face detection not available: {exc}")
        return []


def region_mean(grey: Image.Image, box: tuple[int, int, int, int]) -> float:
    x, y, w, h = box
    hist = grey.crop((x, y, x + w, y + h)).histogram()
    total = sum(hist) or 1
    return sum(level * count for level, count in enumerate(hist)) / total


def measure_image(file: Path, use_faces: bool = True) -> tuple[float, int]:
    """returns (mean grey value 0-255, number of faces). the mean is measured on the faces (central part of each box, weighted by size);
    without a face the central half of the image is used, because people are usually in the middle."""
    with Image.open(file) as img:
        grey = img.convert("L")
        grey.thumbnail((640, 640))

    faces = detect_faces(grey) if use_faces else []
    if faces:
        total_area = sum(w * h for _, _, w, h in faces)
        mean = 0.0
        for x, y, w, h in faces:
            # central part of the box: skip hair, background and the edges
            inner = (x + w // 5, y + h // 5, w * 3 // 5, h * 3 // 5)
            mean += region_mean(grey, inner) * (w * h) / total_area
        return mean, len(faces)

    w, h = grey.size
    if not use_faces:
        return region_mean(grey, (0, 0, w, h)), 0
    return region_mean(grey, (w // 4, h // 4, w // 2, h // 2)), 0


def nearest_index(steps: list, value) -> int:
    return min(range(len(steps)), key=lambda i: abs(steps[i] - value))


def exposure_to_parameters(stops: int, iso_base: int, shutter_base: int, iso_max_idx: int, shutter_slowest_idx: int) -> dict[str, str]:
    """distribute whole stops of extra light to iso first and then to a slower shutter. negative stops go to iso first, then a faster shutter."""
    iso_idx = max(0, min(iso_max_idx, iso_base + stops))
    remainder = stops - (iso_idx - iso_base)
    shutter_idx = max(0, min(shutter_slowest_idx, shutter_base + remainder))

    params: dict[str, str] = {}
    if iso_idx != iso_base:
        params["iso"] = str(ISO_STEPS[iso_idx])
    if shutter_idx != shutter_base:
        params["shutterspeed"] = SHUTTER_STEPS[shutter_idx]
    return params


class HelligkeitsAutomatik(BasePlugin[HelligkeitsAutomatikConfig]):
    def __init__(self):
        super().__init__()
        self._config: HelligkeitsAutomatikConfig = HelligkeitsAutomatikConfig()
        self._exposure = 0.0  # stops relative to the configured still parameters
        self._applied: dict[str, str] = {}
        self._last_mean: float | None = None
        self._last_faces = 0
        self._corrections = 0

    def _backend(self):
        from photobooth.container import container  # lazy: avoids circular import while the app config loads plugins

        return container.acquisition_service._stills_backend

    def _base(self) -> tuple[int, int]:
        """iso and shutter index of the configured still parameters"""
        iso_idx, shutter_idx = 0, 0
        try:
            from photobooth.appconfig import appconfig  # lazy: avoids circular import while the app config loads plugins

            cfg = appconfig.cameras.group_backends[appconfig.cameras.index_backend_stills].backend_config
            for param in getattr(cfg, "parameterset_still", []):
                if not param.enabled:
                    continue
                if param.name == "iso" and str(param.value).isdigit():
                    iso_idx = nearest_index(ISO_STEPS, int(param.value))
                elif param.name == "shutterspeed" and param.value in SHUTTER_STEPS:
                    shutter_idx = SHUTTER_STEPS.index(param.value)
        except Exception as exc:
            logger.debug(f"could not read base still parameters: {exc}")
        return iso_idx, shutter_idx

    def _limits(self, iso_base: int, shutter_base: int) -> tuple[int, int, float, float]:
        lim = self._config.limits
        iso_max_idx = max(iso_base, nearest_index(ISO_STEPS, lim.iso_max))
        slowest_idx = shutter_base
        if lim.shutter_slowest in SHUTTER_STEPS:
            slowest_idx = max(shutter_base, SHUTTER_STEPS.index(lim.shutter_slowest))
        max_e = (iso_max_idx - iso_base) + (slowest_idx - shutter_base)
        min_e = -(iso_base + shutter_base)  # down to iso 100 and the fastest shutter
        return iso_max_idx, slowest_idx, float(min_e), float(max_e)

    @hookimpl
    def acq_still_check(self, file: Path, retry_attempt: int = 0) -> StillRetry | None:
        if not self._config.common.enabled or retry_attempt > 0:
            return None  # photos of a retry are shot with other parameters and must not influence the control

        try:
            backend = self._backend()
            # a retry of another plugin is running if the overrides differ from what this plugin applied; don't learn from it.
            if dict(backend.still_parameter_overrides) != self._applied:
                return None

            mean, faces = measure_image(file, self._config.common.use_faces)
            self._last_mean = mean
            self._last_faces = faces
            self._adjust(mean, backend)
        except Exception as exc:
            logger.warning(f"brightness automatic failed: {exc}")
        return None

    def _adjust(self, mean: float, backend) -> None:
        common, lim = self._config.common, self._config.limits

        if mean < common.ignore_below:
            logger.info(f"brightness automatic: mean={mean:.1f} ({self._last_faces} faces) below {common.ignore_below}, flash failure? not adjusting")
            return
        if abs(mean - common.target_mean) <= common.tolerance:
            logger.info(f"brightness automatic: mean={mean:.1f} ({self._last_faces} faces) within target {common.target_mean}+-{common.tolerance}")
            return

        delta = GAMMA * math.log2(common.target_mean / max(mean, 1.0)) * lim.damping
        delta = max(-lim.max_step_stops, min(lim.max_step_stops, delta))

        iso_base, shutter_base = self._base()
        iso_max_idx, slowest_idx, min_e, max_e = self._limits(iso_base, shutter_base)
        self._exposure = max(min_e, min(max_e, self._exposure + delta))

        params = exposure_to_parameters(round(self._exposure), iso_base, shutter_base, iso_max_idx, slowest_idx)
        if params != self._applied:
            self._corrections += 1
        self._applied = params
        backend.still_parameter_overrides = dict(params)
        logger.info(f"brightness automatic: mean={mean:.1f} ({self._last_faces} faces) target={common.target_mean} -> exposure {self._exposure:+.1f} stops, next still uses {params or 'configured values'}")

    @hookimpl
    def stop(self) -> None:
        try:
            if self._applied and dict(self._backend().still_parameter_overrides) == self._applied:
                self._backend().still_parameter_overrides = {}
        except Exception:
            pass
        self._applied = {}
        self._exposure = 0.0

    @hookimpl
    def get_stats(self) -> GenericStats | None:
        return GenericStats(
            id="helligkeits_automatik",
            name="Helligkeits-Automatik",
            stats=[
                SubStats("Letzte Helligkeit", self._last_mean, decimals=1),
                SubStats("Gesichter im letzten Foto", self._last_faces),
                SubStats("Korrektur (Blendenstufen)", round(self._exposure, 1)),
                SubStats("Aktive Werte", ", ".join(f"{k}={v}" for k, v in self._applied.items()) or "wie konfiguriert"),
                SubStats("Anpassungen gesamt", self._corrections),
            ],
        )
