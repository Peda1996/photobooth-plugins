from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import SettingsConfigDict

from photobooth import CONFIG_PATH
from photobooth.services.config.baseconfig import BaseConfig


class Common(BaseModel):
    model_config = ConfigDict(title="Allgemein")

    enabled: bool = Field(default=True, description="Helligkeit der Fotos messen und ISO/Belichtungszeit fuer die naechsten Fotos automatisch nachregeln.")
    use_faces: bool = Field(default=True, description="Helligkeit auf den erkannten Gesichtern messen (ohne Gesicht: Bildmitte). Aus = ganzes Bild.")
    target_mean: float = Field(default=110, ge=40, le=220, description="Ziel-Helligkeit (mittlerer Grauwert 0-255) der Gesichter, ca. 100-130 passt fuer Hauttoene.")
    tolerance: float = Field(default=12, ge=2, le=60, description="Abweichung vom Ziel, ab der nachgeregelt wird (Grauwerte).")
    ignore_below: float = Field(default=18, ge=0, le=100, description="Fotos darunter gelten als Blitzausfall und werden nicht zur Regelung verwendet.")


class Limits(BaseModel):
    model_config = ConfigDict(title="Grenzen")

    iso_max: int = Field(default=1600, ge=100, le=6400, description="Hoechster ISO-Wert, den die Automatik einstellen darf.")
    shutter_slowest: str = Field(default="1/125", description="Laengste Belichtungszeit, die die Automatik einstellen darf (z.B. 1/125). Gilt, wenn ISO ausgereizt ist.")
    damping: float = Field(default=0.6, ge=0.1, le=1, description="Staerke der Nachregelung pro Foto (1 = voll, kleiner = vorsichtiger).")
    max_step_stops: float = Field(default=2, ge=0.5, le=4, description="Maximale Korrektur pro Foto in Blendenstufen.")


class HelligkeitsAutomatikConfig(BaseConfig):
    model_config = SettingsConfigDict(
        title="Helligkeits-Automatik Plugin Config",
        json_file=f"{CONFIG_PATH}plugin_helligkeitsautomatik.json",
        env_prefix="helligkeitsautomatik-",
    )

    common: Common = Common()
    limits: Limits = Limits()
