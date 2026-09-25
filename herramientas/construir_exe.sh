#!/usr/bin/env bash
# Compila LolcitoScout.exe en Linux con Wine (lo que usa Claude en la nube).
# Necesita encima del repo los archivos privados (lolcito-PRIVADO-no-subir.zip): fuentes, servidor.json,
# LolcitoScout.spec y lolscout.ico. Deja el .exe en dist/LolcitoScout.exe y le pone la versión (fecha UTC).
set -euo pipefail
cd "$(dirname "$0")/.."
export WINEPREFIX="${WINEPREFIX:-/root/.wine64}" WINEDEBUG=-all

for f in LolcitoScout.spec lolscout.ico lolscout/servidor.json lolscout/live/static/fonts/privadas/League.otf; do
  [ -f "$f" ] || { echo "Falta $f: descomprimí el zip privado encima del repo."; exit 1; }
done

# 1) Wine y el Python de Windows (solo la primera vez en cada máquina)
if ! command -v wine >/dev/null; then
  dpkg --add-architecture i386 && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wine64
fi
PY='C:\Py312\python.exe'
if [ ! -f "$WINEPREFIX/drive_c/Py312/python.exe" ]; then
  wineboot -i >/dev/null 2>&1 || true
  tmp=$(mktemp -d)
  curl -sSL -o "$tmp/py.nupkg" https://www.nuget.org/api/v2/package/python/3.12.8
  (cd "$tmp" && unzip -q py.nupkg 'tools/*')
  mkdir -p "$WINEPREFIX/drive_c/Py312" && cp -r "$tmp"/tools/* "$WINEPREFIX/drive_c/Py312/"
  # el Python de Windows necesita una terminal: script -qec se la da
  script -qec "wine '$PY' -m pip install -q pyinstaller requests psutil urllib3" /dev/null >/dev/null
fi

# 2) versión = fecha y hora UTC (la app compara este texto para saber si hay una más nueva)
VERSION=$(date -u +%Y.%m.%d-%H%M)
printf '"""Versión del .exe. La pone sola herramientas/construir_exe.sh al compilar (fecha y hora UTC)."""\nVERSION = "%s"\n' "$VERSION" > lolscout/version.py

# 3) compilar (en primer plano: si no, PyInstaller se cae)
rm -rf build dist
script -qec "wine '$PY' -m PyInstaller --noconfirm --clean LolcitoScout.spec" /dev/null > /tmp/construir_exe.log 2>&1 || true
[ -f dist/LolcitoScout.exe ] || { echo "No se generó el .exe. Mirá /tmp/construir_exe.log"; exit 1; }
echo "Listo: dist/LolcitoScout.exe versión $VERSION ($(du -h dist/LolcitoScout.exe | cut -f1))"
