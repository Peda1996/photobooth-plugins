#!/usr/bin/env python3
"""Traegt die Texte der Plugin-Meldungen in die Uebersetzungen des Photobooth-Frontends ein (die Plugins koennen sonst nur bekannte Schluessel anzeigen).
Aufruf: python3 patch_frontend_texts.py [SITE_PACKAGES]   - idempotent, nach einem Update der Photobooth-App erneut ausfuehren, danach Browser neu laden."""
import glob
import re
import sys

site = sys.argv[1] if len(sys.argv) > 1 else "/home/fotobox/.local/share/pipx/venvs/photobooth-app/lib/python3.13/site-packages"
MARK = "blitz_wache:{failure:"
DE = "⚡ Blitzausfall? Bitte den Blitz prüfen!"
EN = "⚡ Flash failure? Please check the flash!"
anchor = "translatedFrontendNotifications:{"

files = glob.glob(f"{site}/web/frontend/assets/i18n-*.js")
if not files:
    sys.exit("keine i18n-Datei gefunden")
for f in files:
    s = open(f, encoding="utf-8").read()
    if MARK in s:
        print(f"schon gepatcht: {f}")
        continue
    out, pos, n = [], 0, 0
    for m in re.finditer(re.escape(anchor), s):
        end = m.end()
        text = DE if "Es läuft bereits ein Job" in s[end:end + 200] else EN
        out.append(s[pos:end])
        out.append(f"{MARK}`{text}`}},")
        pos = end
        n += 1
    out.append(s[pos:])
    open(f, "w", encoding="utf-8").write("".join(out))
    print(f"gepatcht: {f} ({n} Sprachen)")
