from pathlib import Path

import pytest
from PIL import Image

from photobooth.models.stillretry import StillRetry
from blitz_wache.blitz_wache import BlitzWache, image_brightness


def _img(tmp_path: Path, name: str, value: int) -> Path:
    path = tmp_path / name
    Image.new("RGB", (200, 150), (value, value, value)).save(path)
    return path


def test_image_brightness(tmp_path):
    mean, dark_share = image_brightness(_img(tmp_path, "black.jpg", 0))
    assert mean < 5
    assert dark_share > 0.9

    mean, dark_share = image_brightness(_img(tmp_path, "mid.jpg", 120))
    assert 110 < mean < 130
    assert dark_share < 0.1


def test_normal_image_no_retry(tmp_path):
    plugin = BlitzWache()
    assert plugin.acq_still_check(_img(tmp_path, "n.jpg", 120), 0) is None


def test_black_image_requests_retry_with_ambient_values(tmp_path):
    plugin = BlitzWache()
    retry = plugin.acq_still_check(_img(tmp_path, "b.jpg", 2), 0)
    assert isinstance(retry, StillRetry)
    assert retry.parameters == {"iso": "Auto", "shutterspeed": "1/60", "aperture": "4"}


def test_overexposed_image_requests_retry(tmp_path):
    plugin = BlitzWache()
    retry = plugin.acq_still_check(_img(tmp_path, "w.jpg", 252), 0)
    assert isinstance(retry, StillRetry)
    assert retry.parameters["iso"] == "100"


def test_failure_reported_after_dark_streak_and_resolved(tmp_path):
    plugin = BlitzWache()
    black = _img(tmp_path, "b.jpg", 2)
    for _ in range(plugin._config.common.failure_after_dark_in_row):
        plugin.acq_still_check(black, 0)
    assert plugin._failure is True
    assert plugin.get_stats().stats[0].val == "BLITZAUSFALL?"

    plugin.acq_still_check(_img(tmp_path, "n.jpg", 120), 0)
    assert plugin._failure is False


def test_disabled_plugin_does_nothing(tmp_path):
    plugin = BlitzWache()
    plugin._config.common.enabled = False
    assert plugin.acq_still_check(_img(tmp_path, "b.jpg", 0), 0) is None


def test_failure_sends_frontend_notification(tmp_path, monkeypatch):
    from blitz_wache import blitz_wache as bw

    sent = []
    monkeypatch.setattr(bw, "notify_frontend", sent.append)
    plugin = BlitzWache()
    black = _img(tmp_path, "b.jpg", 2)
    for _ in range(plugin._config.common.failure_after_dark_in_row + 1):
        plugin.acq_still_check(black, 0)
    assert sent == ["blitz_wache.failure"] * 2  # from the threshold on, at every dark photo

    sent.clear()
    plugin._config.common.notify_in_ui = False
    plugin.acq_still_check(black, 0)
    assert sent == []


def test_retry_photo_is_brightened_but_normal_photo_is_not(tmp_path):
    from blitz_wache.blitz_wache import image_brightness

    plugin = BlitzWache()
    dark = _img(tmp_path, "d.jpg", 50)
    plugin.acq_still_check(dark, 1)
    assert image_brightness(dark)[0] > 90

    normal = _img(tmp_path, "n.jpg", 50)
    plugin.acq_still_check(normal, 0)
    assert image_brightness(normal)[0] < 60
