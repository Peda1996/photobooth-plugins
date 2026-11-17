# photobooth-plugins

Eigene Plugins fuer die [Photobooth-App](https://github.com/photobooth-app/photobooth-app) (v9).
Die Plugins liegen als Ordner `plugins/<name>/<name>.py` und werden von der App aus dem Ordner `./plugins/` unterhalb des Datenordners geladen (auf der Fotobox: `/home/fotobox/plugins/`).

## Plugins

### blitz_wache
Prueft jedes Foto per Histogramm auf Helligkeit:
- **zu dunkel** (Blitz nicht gezuendet): sofortige Neuaufnahme mit Umgebungslicht-Werten (Standard ISO Auto, 1/60)
- **ueberbelichtet**: Neuaufnahme mit ISO 100, 1/4000
- nach N dunklen Fotos in Folge (Standard 3) Meldung "BLITZAUSFALL?" im Log, in der Statusanzeige der Admin-Oberflaeche und als rote Meldung auf dem Bildschirm (einmalig `python3 patch_frontend_texts.py` ausfuehren, damit der Text im Frontend hinterlegt ist; nach einem App-Update wiederholen)
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

## Druck-Skript (DNP DS40)

`scripts/photobooth_print.sh` ist das Druck-Skript der Fotobox (Gutenprint/CUPS). Es legt keinen Auftrag an, solange der Drucker nicht am USB hängt (`1343:0003`) oder einen Fehler meldet (Klappe offen, Papier leer ...). So werden keine alten Aufträge nachgedruckt, wenn der Drucker wieder da ist. Exit-Code 5 = Drucker nicht bereit.

Einspielen auf der Box:

    sudo install -m 755 scripts/photobooth_print.sh /usr/local/bin/photobooth_print.sh

Share-Befehl in der App: `/usr/local/bin/photobooth_print.sh Dai_Nippon_Printing_DS40 "{filename}" --format 4x6`
