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

# strings that exist in the English frontend but are missing in the German translation (they would show up in English)
DE_EXTRA = {"Take one more!": "Noch ein Foto!"}

files = glob.glob(f"{site}/web/frontend/assets/i18n-*.js")
if not files:
    sys.exit("keine i18n-Datei gefunden")
for f in files:
    s = open(f, encoding="utf-8").read()
    if MARK in s and not any(f'"{k}":`{v}`' not in s for k, v in DE_EXTRA.items()):
        print(f"schon gepatcht: {f}")
        continue
    patched_de = False
    for m in re.finditer(r'[,{]"?de-DE"?:\{', s):
        extra = "".join(f'"{k}":`{v}`,' for k, v in DE_EXTRA.items() if f'"{k}":`{v}`' not in s[m.end():m.end() + 40000])
        if extra:
            s = s[: m.end()] + extra + s[m.end():]
            patched_de = True
        break

    out, pos, n = [], 0, 0
    for m in ([] if MARK in s else re.finditer(re.escape(anchor), s)):
        end = m.end()
        text = DE if "Es läuft bereits ein Job" in s[end:end + 200] else EN
        out.append(s[pos:end])
        out.append(f"{MARK}`{text}`}},")
        pos = end
        n += 1
    out.append(s[pos:])
    open(f, "w", encoding="utf-8").write("".join(out))
    print(f"gepatcht: {f} ({n} Sprachen)")
