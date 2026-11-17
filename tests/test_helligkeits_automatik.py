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
    monkeypatch.setattr(plugin, "_base", lambda: (0, 0))  # iso 100, 1/4000
    return plugin, backend


def test_parameters_iso_first_then_shutter():
    assert exposure_to_parameters(0, 0, 0, 4, 5) == {}
    assert exposure_to_parameters(2, 0, 0, 4, 5) == {"iso": "400"}
    assert exposure_to_parameters(6, 0, 0, 4, 5) == {"iso": "1600", "shutterspeed": "1/1000"}
    assert exposure_to_parameters(20, 0, 0, 4, 5) == {"iso": "1600", "shutterspeed": "1/125"}
    assert exposure_to_parameters(-2, 0, 0, 4, 5) == {}  # cannot go darker than iso 100 and 1/4000


def test_dark_photo_raises_exposure(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    assert plugin.acq_still_check(_img(tmp_path, "d.jpg", 55)) is None
    assert backend.still_parameter_overrides.get("iso") in ("200", "400")


def test_within_tolerance_changes_nothing(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    plugin.acq_still_check(_img(tmp_path, "ok.jpg", 110))
    assert backend.still_parameter_overrides == {}


def test_black_photo_is_ignored_as_flash_failure(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    plugin.acq_still_check(_img(tmp_path, "b.jpg", 2))
    assert backend.still_parameter_overrides == {}


def test_retry_in_progress_is_ignored(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    backend.still_parameter_overrides = {"iso": "Auto"}  # set by another plugin's retry
    plugin.acq_still_check(_img(tmp_path, "r.jpg", 55))
    assert backend.still_parameter_overrides == {"iso": "Auto"}


def test_converges_up_and_down(tmp_path, monkeypatch):
    plugin, backend = _plugin(monkeypatch)
    for _ in range(4):
        plugin.acq_still_check(_img(tmp_path, "d.jpg", 40))
    assert plugin._exposure > 1
    for _ in range(8):
        plugin.acq_still_check(_img(tmp_path, "w.jpg", 230))
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
