import io
from types import SimpleNamespace

from PIL import Image

from vorschau_automatik.vorschau_automatik import VorschauAutomatik, frame_mean, split_exposure


def _jpeg(value: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (value, value, value)).save(buf, "JPEG")
    return buf.getvalue()


def _plugin():
    backend = SimpleNamespace(video_parameter_overrides={}, live_parameter_request=None)
    plugin = VorschauAutomatik()
    return plugin, backend


def test_frame_mean():
    assert abs(frame_mean(_jpeg(60)) - 60) < 3


def test_split_iso_first_then_shutter():
    iso_r, sh_r = (0, 6), (0, 5)
    assert split_exposure(0, iso_r, sh_r, 3, 4) == (3, 4)
    assert split_exposure(2, iso_r, sh_r, 3, 4) == (5, 4)
    assert split_exposure(5, iso_r, sh_r, 3, 4) == (6, 5)  # iso exhausted -> shutter slower
    assert split_exposure(-4, iso_r, sh_r, 3, 4) == (0, 3)


def test_dark_preview_raises_exposure_and_requests_live_change():
    plugin, backend = _plugin()
    plugin._apply(backend, plugin._params())
    plugin._settle = 0
    plugin.adjust(23, backend)
    assert plugin._exposure > 1
    assert backend.live_parameter_request == backend.video_parameter_overrides
    assert backend.video_parameter_overrides["iso"] != "800" or backend.video_parameter_overrides["shutterspeed"] != "1/60"


def test_within_tolerance_changes_nothing():
    plugin, backend = _plugin()
    plugin._apply(backend, plugin._params())
    plugin._settle = 0
    plugin.adjust(100, backend)
    assert plugin._exposure == 0


def test_settle_skips_measurements_after_a_change():
    plugin, backend = _plugin()
    plugin._apply(backend, plugin._params())  # settle = 2
    plugin.adjust(23, backend)
    plugin.adjust(23, backend)
    assert plugin._exposure == 0
    plugin.adjust(23, backend)
    assert plugin._exposure > 0


def test_limits_are_respected():
    plugin, backend = _plugin()
    plugin._apply(backend, plugin._params())
    for _ in range(30):
        plugin._settle = 0
        plugin.adjust(5, backend)
    assert backend.video_parameter_overrides == {"iso": "6400", "shutterspeed": "1/30"}
    for _ in range(30):
        plugin._settle = 0
        plugin.adjust(250, backend)
    assert backend.video_parameter_overrides == {"iso": "100", "shutterspeed": "1/1000"}
