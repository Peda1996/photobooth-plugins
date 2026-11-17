# photobooth-plugins

Eigene Plugins fuer die [Photobooth-App](https://github.com/photobooth-app/photobooth-app) (v9).
Die Plugins liegen als Ordner `plugins/<name>/<name>.py` und werden von der App aus dem Ordner `./plugins/` unterhalb des Datenordners geladen (auf der Fotobox: `/home/fotobox/plugins/`).

## Plugins

### blitz_wache
Prueft jedes Foto per Histogramm auf Helligkeit:
- **zu dunkel** (Blitz nicht gezuendet): sofortige Neuaufnahme mit Umgebungslicht-Werten (Standard ISO Auto, 1/60)
- **ueberbelichtet**: Neuaufnahme mit ISO 100, 1/4000
- nach N dunklen Fotos in Folge (Standard 3) Meldung "BLITZAUSFALL?" im Log und in der Statusanzeige der Admin-Oberflaeche
- Einstellungen in der Admin-Oberflaeche in den Reitern "Allgemein" und "Wiederholung"

**Voraussetzung:** Die App braucht den Hook `acq_still_check` (Branch `feature/acq-still-check-hook` im Fork
[Peda1996/photobooth-app](https://github.com/Peda1996/photobooth-app/tree/feature/acq-still-check-hook), spaeter Pull Request ans Original).
Ohne den Hook laedt das Plugin zwar, tut aber nichts.

## Installation

```bash
./install.sh            # kopiert nach /home/fotobox/plugins
systemctl --user restart photobooth-app
```

## Tests

```bash
pip install pytest photobooth-app
pytest
```
