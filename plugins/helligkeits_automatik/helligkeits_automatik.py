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
APERTURE_STEPS = ["4", "4.5", "5", "5.6", "6.3", "7.1", "8", "9", "10", "11", "13", "14", "16", "18", "20", "22", "25"]  # third stops as offered by canon, small number = open
GAMMA = 2.2  # jpeg mean grey value vs. light: stops = gamma * log2(target/mean)


_detector = None
_detector_failed = False
MODEL_PATH = Path(__file__).parent / "face_detection_yunet_2023mar.onnx"


def _load_detector(size: tuple[int, int]):
    """OpenCV 5 dropped the haar cascade, the YuNet model (ONNX, shipped next to this file) is used with FaceDetectorYN.
    older OpenCV (4.x) without FaceDetectorYN falls back to the haar cascade."""
    global _detector, _detector_failed
    import cv2

    if _detector is None:
        if hasattr(cv2, "FaceDetectorYN") and MODEL_PATH.exists():
            _detector = ("yunet", cv2.FaceDetectorYN.create(str(MODEL_PATH), "", size, 0.7, 0.3, 5000))
        elif hasattr(cv2, "CascadeClassifier"):
            _detector = ("haar", cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml"))
        else:
            raise RuntimeError("no face detector available in this OpenCV")
    return _detector


def detect_faces(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """returns face boxes (x, y, w, h) found in the image, empty list if none or detection is unavailable"""
    global _detector_failed
    if _detector_failed:
        return []
    try:
        import cv2
        import numpy as np

        rgb = np.asarray(img.convert("RGB"))
        kind, det = _load_detector((rgb.shape[1], rgb.shape[0]))
        if kind == "yunet":
            det.setInputSize((rgb.shape[1], rgb.shape[0]))
            _, faces = det.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            return [] if faces is None else [tuple(int(v) for v in f[:4]) for f in faces]
        grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        found = det.detectMultiScale(grey, scaleFactor=1.15, minNeighbors=5, minSize=(max(24, grey.shape[1] // 25),) * 2)
        return [tuple(int(v) for v in f) for f in found]
    except Exception as exc:
        _detector_failed = True  # do not retry on every photo
        logger.warning(f"face detection not available, measuring the image center instead: {exc}")
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
        small = img.convert("RGB")
        small.thumbnail((640, 640))
    grey = small.convert("L")

    faces = detect_faces(small) if use_faces else []
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


def exposure_to_parameters(
    stops: int,
    iso_base: int,
    shutter_base: int,
    iso_range: tuple[int, int],
    shutter_range: tuple[int, int],
    aperture_base: int = 0,
    aperture_range: tuple[int, int] = (0, 0),
) -> dict[str, str]:
    """distribute whole stops of exposure to iso first, then to the shutter and only as third to the aperture.
    a range with lo == hi == base means the value is not controlled. aperture moves in whole stops (3 entries of the third-stop list)."""
    iso_idx = max(iso_range[0], min(iso_range[1], iso_base + stops))
    remainder = stops - (iso_idx - iso_base)
    shutter_idx = max(shutter_range[0], min(shutter_range[1], shutter_base + remainder))
    remainder -= shutter_idx - shutter_base

    # positive remainder = more light needed = open the aperture (smaller index), negative = close it
    max_open_stops = (aperture_base - aperture_range[0]) // 3
    max_close_stops = (aperture_range[1] - aperture_base) // 3
    aperture_stops = max(-max_close_stops, min(max_open_stops, remainder))
    aperture_idx = aperture_base - 3 * aperture_stops

    params: dict[str, str] = {}
    if iso_idx != iso_base:
        params["iso"] = str(ISO_STEPS[iso_idx])
    if shutter_idx != shutter_base:
        params["shutterspeed"] = SHUTTER_STEPS[shutter_idx]
    if aperture_idx != aperture_base:
        params["aperture"] = APERTURE_STEPS[aperture_idx]
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
        self._auto_notice = False
        self._measured = 0  # photos used for the control since start, the first ones are corrected at full strength

    def _backend(self):
        from photobooth.container import container  # lazy: avoids circular import while the app config loads plugins

        return container.acquisition_service._stills_backend

    def _base(self) -> tuple[int | None, int | None, int | None]:
        """iso and shutter index of the configured still parameters. None if the value is not fixed (camera on Auto or not set), then it is not controlled."""
        iso_idx: int | None = None
        shutter_idx: int | None = None
        aperture_idx: int | None = None
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
                elif param.name == "aperture" and str(param.value) in APERTURE_STEPS:
                    aperture_idx = APERTURE_STEPS.index(str(param.value))
        except Exception as exc:
            logger.debug(f"could not read base still parameters: {exc}")
        return iso_idx, shutter_idx, aperture_idx

    def _ranges(self, iso_base: int | None, shutter_base: int | None, aperture_base: int | None):
        """returns the bases (0 if not controlled), the allowed index ranges and the allowed exposure range in stops"""
        lim = self._config.limits
        iso_b = iso_base if iso_base is not None else 0
        shutter_b = shutter_base if shutter_base is not None else 0
        aperture_b = aperture_base if aperture_base is not None else 0

        iso_range = (iso_b, iso_b)
        if iso_base is not None:
            iso_range = (0, max(iso_base, nearest_index(ISO_STEPS, lim.iso_max)))

        shutter_range = (shutter_b, shutter_b)
        if shutter_base is not None:
            slowest = SHUTTER_STEPS.index(lim.shutter_slowest) if lim.shutter_slowest in SHUTTER_STEPS else shutter_base
            shutter_range = (0, max(shutter_base, slowest))

        aperture_range = (aperture_b, aperture_b)
        if aperture_base is not None and lim.aperture_enabled:
            widest = APERTURE_STEPS.index(lim.aperture_widest) if lim.aperture_widest in APERTURE_STEPS else aperture_base
            narrowest = APERTURE_STEPS.index(lim.aperture_narrowest) if lim.aperture_narrowest in APERTURE_STEPS else aperture_base
            aperture_range = (min(aperture_base, widest), max(aperture_base, narrowest))

        min_e = (iso_range[0] - iso_b) + (shutter_range[0] - shutter_b) - (aperture_range[1] - aperture_b) // 3
        max_e = (iso_range[1] - iso_b) + (shutter_range[1] - shutter_b) + (aperture_b - aperture_range[0]) // 3
        return iso_b, shutter_b, aperture_b, iso_range, shutter_range, aperture_range, float(min_e), float(max_e)

    @hookimpl
    def acq_still_check(self, file: Path, retry_attempt: int) -> StillRetry | None:
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

        warmup = lim.warmup_enabled and self._measured < lim.warmup_photos
        self._measured += 1
        damping = 1.0 if warmup else lim.damping
        max_step = lim.warmup_max_step_stops if warmup else lim.max_step_stops
        delta = GAMMA * math.log2(common.target_mean / max(mean, 1.0)) * damping
        delta = max(-max_step, min(max_step, delta))

        iso_base, shutter_base, aperture_base = self._base()
        if iso_base is None and shutter_base is None and aperture_base is None:
            if not self._auto_notice:
                logger.warning("brightness automatic inactive: iso, shutterspeed and aperture of the still parameters are not fixed values (camera on Auto)")
                self._auto_notice = True
            return
        iso_b, shutter_b, aperture_b, iso_range, shutter_range, aperture_range, min_e, max_e = self._ranges(iso_base, shutter_base, aperture_base)
        self._exposure = max(min_e, min(max_e, self._exposure + delta))

        params = exposure_to_parameters(round(self._exposure), iso_b, shutter_b, iso_range, shutter_range, aperture_b, aperture_range)
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
        self._measured = 0

    @hookimpl
    def get_stats(self) -> GenericStats | None:
        return GenericStats(
            id="helligkeits_automatik",
            name="Helligkeits-Automatik",
            stats=[
                SubStats("Status", "inaktiv: Kamera steht auf Auto" if self._auto_notice else "aktiv"),
                SubStats("Letzte Helligkeit", self._last_mean, decimals=1),
                SubStats("Gesichter im letzten Foto", self._last_faces),
                SubStats("Korrektur (Blendenstufen)", round(self._exposure, 1)),
                SubStats("Aktive Werte", ", ".join(f"{k}={v}" for k, v in self._applied.items()) or "wie konfiguriert"),
                SubStats("Anpassungen gesamt", self._corrections),
            ],
        )
