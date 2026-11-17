#!/bin/bash
# Installiert alle Plugins dieses Repos in den Plugin-Ordner der Photobooth-App (Standard: /home/fotobox/plugins).
# Aufruf: ./install.sh [ZIELORDNER]   danach: systemctl --user restart photobooth-app
set -e
DEST="${1:-/home/fotobox/plugins}"
mkdir -p "${DEST:?}"
for p in "$(dirname "$0")"/plugins/*/; do
  name=$(basename "$p")
  rm -rf "${DEST:?}/${name:?}"
  cp -r "$p" "${DEST:?}/${name:?}"
  echo "installiert: $name -> $DEST/$name"
done
