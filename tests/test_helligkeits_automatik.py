from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from helligkeits_automatik import helligkeits_automatik as ha
from helligkeits_automatik.helligkeits_automatik import HelligkeitsAutomatik, exposure_to_parameters, measure_image


def _img(tmp_path: Path, name: str, value: int) -> Path:
    path = tmp_path / name
    Image.new("RGB", (200, 150), (value, value, value)).save(path)
    return path


def _plugin(monkeypatch):
    backend = SimpleNamespace(still_parameter_overrides={})
    plugin = HelligkeitsAutomatik()
    monkeypatch.setattr(plugin, "_backend", lambda: backend)
    monkeypatch.setattr(plugin, "_base", lambda: (0, 0, None))  # iso 100, 1/4000 fixed, aperture not controlled
    return plugin, backend


def test_parameters_iso_first_then_shutter():
    iso, shutter = (0, 4), (0, 5)
    assert exposure_to_parameters(0, 0, 0, iso, shutter) == {}
    assert exposure_to_parameters(2, 0, 0, iso, shutter) == {"iso": "400"}
    assert exposure_to_parameters(6, 0, 0, iso, shutter) == {"iso": "1600", "shutterspeed": "1/1000"}
    assert exposure_to_parameters(20, 0, 0, iso, shutter) == {"iso": "1600", "shutterspeed": "1/125"}
    assert exposure_to_parameters(-2, 0, 0, iso, shutter) == {}  # cannot go darker than iso 100 and 1/4000


def test_uncontrolled_values_are_never_touched():
    # iso on auto -> only the shutter may change
    assert exposure_to_parameters(3, 0, 0, (0, 0), (0, 5)) == {"shutterspeed": "1/500"}
    # shutter on auto -> only iso may change
    assert exposure_to_parameters(3, 0, 0, (0, 4), (0, 0)) == {"iso": "800"}


def test_inactive_when_camera_is_on_auto(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    monkeypatch.setattr(plugin, "_base", lambda: (None, None, None))
    plugin.acq_still_check(_img(tmp_path, "d.jpg", 55), 0)
    assert backend.still_parameter_overrides == {} and plugin._auto_notice


def test_dark_photo_raises_exposure(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    assert plugin.acq_still_check(_img(tmp_path, "d.jpg", 55), 0) is None
    assert backend.still_parameter_overrides.get("iso") in ("200", "400")


def test_within_tolerance_changes_nothing(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    plugin.acq_still_check(_img(tmp_path, "ok.jpg", 110), 0)
    assert backend.still_parameter_overrides == {}


def test_black_photo_is_ignored_as_flash_failure(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    plugin.acq_still_check(_img(tmp_path, "b.jpg", 2), 0)
    assert backend.still_parameter_overrides == {}


def test_retry_in_progress_is_ignored(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    backend.still_parameter_overrides = {"iso": "Auto"}  # set by another plugin's retry
    plugin.acq_still_check(_img(tmp_path, "r.jpg", 55), 0)
    assert backend.still_parameter_overrides == {"iso": "Auto"}


def test_converges_up_and_down(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    for _ in range(4):
        plugin.acq_still_check(_img(tmp_path, "d.jpg", 40), 0)
    assert plugin._exposure > 1
    for _ in range(8):
        plugin.acq_still_check(_img(tmp_path, "w.jpg", 230), 0)
    assert plugin._exposure <= 0.5


def test_measure_uses_face_region_not_whole_image(tmp_path, monkeypatch):
    path = tmp_path / "f.jpg"
    img = Image.new("L", (400, 300), 230)  # bright background
    img.paste(60, (150, 100, 250, 200))  # dark face
    img.convert("RGB").save(path)
    monkeypatch.setattr(ha, "detect_faces", lambda grey: [(150 * grey.width // 400, 100 * grey.height // 300, 100 * grey.width // 400, 100 * grey.height // 300)])
    mean, faces = measure_image(path)
    assert faces == 1 and mean < 80


def test_measure_without_face_uses_center(tmp_path, monkeypatch):
    path = tmp_path / "c.jpg"
    img = Image.new("L", (400, 300), 230)
    img.paste(60, (100, 75, 300, 225))
    img.convert("RGB").save(path)
    monkeypatch.setattr(ha, "detect_faces", lambda grey: [])
    mean, faces = measure_image(path)
    assert faces == 0 and mean < 80


def test_retry_photo_is_ignored(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    plugin.acq_still_check(_img(tmp_path, "r.jpg", 55), retry_attempt=1)
    assert backend.still_parameter_overrides == {} and plugin._exposure == 0


def test_aperture_is_only_used_after_iso_and_shutter_are_exhausted():
    iso, shutter, ap = (0, 1), (0, 1), (0, 6)  # iso 100-200, shutter 1/4000-1/2000, aperture 4 - 8, base 5.6 (index 3)
    assert exposure_to_parameters(1, 0, 0, iso, shutter, 3, ap) == {"iso": "200"}
    assert exposure_to_parameters(2, 0, 0, iso, shutter, 3, ap) == {"iso": "200", "shutterspeed": "1/2000"}
    assert exposure_to_parameters(3, 0, 0, iso, shutter, 3, ap) == {"iso": "200", "shutterspeed": "1/2000", "aperture": "4"}
    assert exposure_to_parameters(9, 0, 0, iso, shutter, 3, ap)["aperture"] == "4"  # limited to the widest allowed aperture


def test_aperture_closes_when_too_bright_and_iso_shutter_at_minimum():
    iso, shutter, ap = (0, 1), (0, 1), (0, 6)
    assert exposure_to_parameters(-1, 0, 0, iso, shutter, 3, ap) == {"aperture": "8"}
    assert exposure_to_parameters(-5, 0, 0, iso, shutter, 3, ap) == {"aperture": "8"}  # 8 is the narrowest allowed
    assert exposure_to_parameters(-1, 0, 0, iso, shutter, 6, (0, 6)) == {}  # already at the narrowest allowed


def test_first_photos_are_corrected_at_full_strength(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    plugin.acq_still_check(_img(tmp_path, "w1.jpg", 40), 0)  # very dark first photo
    first = plugin._exposure
    assert first > 2.5  # full strength: 2.2 * log2(110/40) = 3.2 stops

    plugin2, _ = _plugin(monkeypatch)
    plugin2._config.limits.warmup_photos = 0  # no warmup: damped
    plugin2.acq_still_check(_img(tmp_path, "w2.jpg", 40), 0)
    assert plugin2._exposure < first


def test_warmup_switch_off(tmp_path, monkeypatch):
    plugin, _ = _plugin(monkeypatch)
    plugin._config.limits.warmup_enabled = False
    plugin.acq_still_check(_img(tmp_path, "o.jpg", 40), 0)
    assert plugin._exposure < 2.2


def test_after_warmup_damping_applies_again(tmp_path, monkeypatch):
    plugin, _ = _plugin(monkeypatch)
    plugin._measured = plugin._config.limits.warmup_photos
    plugin.acq_still_check(_img(tmp_path, "d.jpg", 40), 0)
    assert plugin._exposure < 2.2


def test_hook_signature_has_no_default_for_retry_attempt():
    # pluggy does not pass arguments with a default value, the retry photo would then not be recognized
    import inspect
    assert inspect.signature(HelligkeitsAutomatik.acq_still_check).parameters["retry_attempt"].default is inspect.Parameter.empty


def test_face_model_is_shipped_and_loadable():
    import cv2

    assert ha.MODEL_PATH.exists() and ha.MODEL_PATH.stat().st_size > 100_000
    if hasattr(cv2, "FaceDetectorYN"):
        ha._detector = None
        assert ha.detect_faces(Image.new("RGB", (320, 240), (128, 128, 128))) == []  # loads the model, no face in a grey image
        assert ha._detector is not None and ha._detector[0] == "yunet"
