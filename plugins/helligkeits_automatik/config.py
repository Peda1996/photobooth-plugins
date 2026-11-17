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
    aperture_widest: str = Field(default="4", description="Weiteste Blende (kleinste Zahl), die die Automatik einstellen darf. Die Blende wird erst angefasst, wenn ISO und Belichtungszeit ausgereizt sind, und nur wenn 'aperture' in den Still-Parametern der Kamera fest gesetzt ist.")
    aperture_narrowest: str = Field(default="16", description="Engste Blende (groesste Zahl), die die Automatik einstellen darf.")
    warmup_enabled: bool = Field(default=True, description="Schnellstart: bei den ersten Fotos nach dem Start mit voller Staerke regeln, damit die Werte schnell passen.")
    aperture_enabled: bool = Field(default=True, description="Blende als dritten Regler verwenden (erst wenn ISO und Belichtungszeit ausgereizt sind). Nur aktiv, wenn 'aperture' in den Still-Parametern der Kamera fest gesetzt ist.")
    warmup_photos: int = Field(default=3, ge=0, le=10, description="Anzahl der ersten Fotos nach dem Start, bei denen die Automatik mit voller Staerke regelt, damit die Werte schnell passen. 0 = aus.")
    warmup_max_step_stops: float = Field(default=4, ge=0.5, le=6, description="Maximale Korrektur pro Foto in Blendenstufen waehrend dieser ersten Fotos.")
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
