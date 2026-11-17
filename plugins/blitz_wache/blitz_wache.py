import logging
from pathlib import Path

from PIL import Image

from photobooth.models.genericstats import GenericStats, SubStats
from photobooth.models.stillretry import StillRetry
from photobooth.plugins import hookimpl
from photobooth.plugins.base_plugin import BasePlugin

from .config import BlitzWacheConfig

logger = logging.getLogger(__name__)


def image_brightness(file: Path) -> tuple[float, float]:
    """returns (mean brightness 0-255, share of near-black pixels 0-1) based on a downscaled greyscale histogram"""
    with Image.open(file) as img:
        grey = img.convert("L")
        grey.thumbnail((160, 160))
        hist = grey.histogram()
    total = sum(hist) or 1
    mean = sum(level * count for level, count in enumerate(hist)) / total
    dark_share = sum(hist[:10]) / total
    return mean, dark_share


def brighten_file(file: Path, target: float, max_gain_stops: float) -> float | None:
    """brightens a jpeg in place with a gamma curve so that its mean grey value gets close to target. returns the mean before, None if nothing was changed"""
    import math

    with Image.open(file) as img:
        img.load()
        grey = img.convert("L")
        grey.thumbnail((160, 160))
        hist = grey.histogram()
        mean = sum(level * count for level, count in enumerate(hist)) / (sum(hist) or 1)
        if mean >= target or mean < 1:
            return None
        gamma = math.log(target / 255) / math.log(max(mean, 1) / 255)  # < 1 brightens
        gamma = max(gamma, 2 ** (-max_gain_stops / 2.2))  # limit the gain, noise gets visible otherwise
        lut = [round(255 * (i / 255) ** gamma) for i in range(256)]
        exif = img.info.get("exif")
        out = img.convert("RGB").point(lut * 3)
        out.save(file, format="JPEG", quality=95, **({"exif": exif} if exif else {}))
    return mean


def notify_frontend(key: str) -> None:
    """show a notification in the frontend via sse. the key lives under translatedFrontendNotifications in the frontend translations"""
    from photobooth.services.sse import sse_service  # lazy: avoids circular import while the app config loads plugins
    from photobooth.services.sse.sse_ import SseEventTranslateableFrontendNotification

    sse_service.dispatch_event(SseEventTranslateableFrontendNotification(message_key=key, color="negative", icon="flash_off"))


class BlitzWache(BasePlugin[BlitzWacheConfig]):
    def __init__(self):
        super().__init__()
        self._config: BlitzWacheConfig = BlitzWacheConfig()
        self._dark_in_row = 0
        self._last_mean: float | None = None
        self._retries_total = 0
        self._failure = False

    @hookimpl
    def acq_still_check(self, file: Path, retry_attempt: int) -> StillRetry | None:  # no default: pluggy would not pass it
        if not self._config.common.enabled:
            return None

        try:
            mean, dark_share = image_brightness(file)
        except Exception as exc:
            logger.warning(f"could not analyze brightness of {file}: {exc}")
            return None

        self._last_mean = mean
        logger.info(f"brightness check: mean={mean:.1f}, dark pixels={dark_share:.0%}")

        if mean < self._config.common.dark_mean_below:
            self._dark_in_row += 1
            if self._dark_in_row >= self._config.common.failure_after_dark_in_row:
                if not self._failure:
                    self._failure = True
                    logger.error(f"BLITZAUSFALL? {self._dark_in_row} zu dunkle Fotos in Folge. Bitte Blitz pruefen!")
                if self._config.common.notify_in_ui:
                    try:
                        notify_frontend("blitz_wache.failure")  # at every further dark photo, so it stays visible until the flash works again
                    except Exception as exc:
                        logger.warning(f"could not send frontend notification: {exc}")
            if self._config.retry.retry_dark:
                self._retries_total += 1
                return StillRetry(
                    parameters={
                        "iso": self._config.retry.retry_dark_iso,
                        "shutterspeed": self._config.retry.retry_dark_shutterspeed,
                        **({"aperture": self._config.retry.retry_dark_aperture} if self._config.retry.retry_dark_aperture else {}),
                    },
                    reason=f"Foto zu dunkel (Helligkeit {mean:.1f}), Blitz evtl. ausgefallen",
                )
            return None

        if retry_attempt > 0 and self._config.retry.brighten_retry:
            try:
                before = brighten_file(file, self._config.retry.brighten_target, self._config.retry.brighten_max_gain_stops)
                if before is not None:
                    logger.info(f"photo after flash failure brightened by software, mean {before:.1f} -> ~{self._config.retry.brighten_target:.0f}")
            except Exception as exc:
                logger.warning(f"could not brighten {file}: {exc}")

        # photo is fine or only overexposed: dark streak ends, failure state resolved
        self._dark_in_row = 0
        self._failure = False

        if mean > self._config.common.bright_mean_above and self._config.retry.retry_bright:
            self._retries_total += 1
            return StillRetry(
                parameters={"iso": self._config.retry.retry_bright_iso, "shutterspeed": self._config.retry.retry_bright_shutterspeed},
                reason=f"Foto ueberbelichtet (Helligkeit {mean:.1f})",
            )
        return None

    @hookimpl
    def get_stats(self) -> GenericStats | None:
        return GenericStats(
            id="blitz_wache",
            name="Blitz-Wache",
            stats=[
                SubStats("Status", "BLITZAUSFALL?" if self._failure else "ok"),
                SubStats("Zu dunkle Fotos in Folge", self._dark_in_row),
                SubStats("Letzte Helligkeit", self._last_mean, decimals=1),
                SubStats("Wiederholungen gesamt", self._retries_total),
            ],
        )
