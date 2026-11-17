from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import SettingsConfigDict

from photobooth import CONFIG_PATH
from photobooth.services.config.baseconfig import BaseConfig


class Common(BaseModel):
    model_config = ConfigDict(title="Allgemein")

    enabled: bool = Field(default=True, description="Helligkeit der Live-Vorschau messen und ISO/Belichtungszeit der Vorschau automatisch nachregeln.")
    target_mean: float = Field(default=100, ge=40, le=200, description="Ziel-Helligkeit der Vorschau (mittlerer Grauwert 0-255).")
    tolerance: float = Field(default=15, ge=3, le=60, description="Abweichung vom Ziel, ab der nachgeregelt wird (Grauwerte).")
    interval: float = Field(default=2.0, ge=0.5, le=10, description="Abstand der Messungen in Sekunden.")
    damping: float = Field(default=0.7, ge=0.1, le=1, description="Staerke der Nachregelung pro Messung (1 = voll, kleiner = ruhiger).")
    max_step_stops: float = Field(default=3, ge=0.5, le=6, description="Maximale Korrektur pro Messung in Blendenstufen.")


class Limits(BaseModel):
    model_config = ConfigDict(title="Grenzen")

    iso_base: int = Field(default=800, description="Start-ISO der Vorschau (wird beim Start fest gesetzt, wenn die Kamera in der Vorschau auf Auto steht).")
    iso_min: int = Field(default=100, description="Niedrigster ISO-Wert der Vorschau.")
    iso_max: int = Field(default=6400, description="Hoechster ISO-Wert der Vorschau.")
    shutter_base: str = Field(default="1/60", description="Start-Belichtungszeit der Vorschau.")
    shutter_slowest: str = Field(default="1/30", description="Laengste Belichtungszeit der Vorschau (langsamer = ruckelige Vorschau).")
    shutter_fastest: str = Field(default="1/1000", description="Kuerzeste Belichtungszeit der Vorschau.")


class VorschauAutomatikConfig(BaseConfig):
    model_config = SettingsConfigDict(
        title="Vorschau-Automatik Plugin Config",
        json_file=f"{CONFIG_PATH}plugin_vorschauautomatik.json",
        env_prefix="vorschauautomatik-",
    )

    common: Common = Common()
    limits: Limits = Limits()
