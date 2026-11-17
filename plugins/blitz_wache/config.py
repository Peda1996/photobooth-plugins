from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import SettingsConfigDict

from photobooth import CONFIG_PATH
from photobooth.services.config.baseconfig import BaseConfig


class Common(BaseModel):
    model_config = ConfigDict(title="Allgemein")

    enabled: bool = Field(default=True, description="Fotos nach der Aufnahme auf Helligkeit pruefen und bei Blitzausfall reagieren.")
    dark_mean_below: float = Field(default=18, ge=0, le=255, description="Mittlere Helligkeit (0-255) unter der ein Foto als zu dunkel gilt.")
    bright_mean_above: float = Field(default=240, ge=0, le=255, description="Mittlere Helligkeit (0-255) ueber der ein Foto als ueberbelichtet gilt.")
    notify_in_ui: bool = Field(default=True, description="Bei Blitzausfall eine rote Meldung auf dem Bildschirm einblenden (braucht patch_frontend_texts.py, sonst erscheint der Schluessel statt des Textes).")
    failure_after_dark_in_row: int = Field(default=3, ge=1, le=20, description="Anzahl zu dunkler Fotos in Folge, ab der ein Blitzausfall gemeldet wird.")


class Retry(BaseModel):
    model_config = ConfigDict(title="Wiederholung")

    retry_dark: bool = Field(default=True, description="Bei zu dunklem Foto sofort neu aufnehmen (Umgebungslicht-Werte).")
    retry_dark_iso: str = Field(default="Auto", description="ISO fuer den Wiederholungsversuch bei zu dunklem Foto.")
    retry_dark_shutterspeed: str = Field(default="1/30", description="Belichtungszeit fuer den Wiederholungsversuch bei zu dunklem Foto.")

    retry_dark_aperture: str = Field(default="min", description="Blende fuer den Wiederholungsversuch bei zu dunklem Foto. \"min\" = die weiteste Blende, die die Kamera gerade anbietet (je nach Zoom z.B. 3.5 oder 4), oder ein fester Wert wie 4. Leer = Blende nicht aendern.")
    brighten_retry: bool = Field(default=True, description="Das Foto der Wiederholung nachtraeglich per Software aufhellen, wenn es dunkler als die Zielhelligkeit ist (nur Fotos nach einem Blitzausfall).")
    brighten_target: float = Field(default=105, ge=60, le=180, description="Zielhelligkeit (0-255) fuer das Aufhellen.")
    brighten_max_gain_stops: float = Field(default=3, ge=0.5, le=5, description="Maximale Aufhellung in Blendenstufen (mehr = mehr Bildrauschen).")

    retry_bright: bool = Field(default=True, description="Bei ueberbelichtetem Foto sofort neu aufnehmen.")
    retry_bright_iso: str = Field(default="100", description="ISO fuer den Wiederholungsversuch bei ueberbelichtetem Foto.")
    retry_bright_shutterspeed: str = Field(default="1/4000", description="Belichtungszeit fuer den Wiederholungsversuch bei ueberbelichtetem Foto.")


class BlitzWacheConfig(BaseConfig):
    model_config = SettingsConfigDict(
        title="Blitz-Wache (Helligkeitskontrolle) Plugin Config",
        json_file=f"{CONFIG_PATH}plugin_blitzwache.json",
        env_prefix="blitzwache-",
    )

    common: Common = Common()
    retry: Retry = Retry()
