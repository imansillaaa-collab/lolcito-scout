#!/usr/bin/env bash
# Publica dist/LolcitoScout.exe en la rama "descargas": de ahí se actualizan solas las apps de todos.
# Uso: herramientas/publicar_exe.sh "Qué cambió (se muestra en el cartel de versión nueva)"
# La rama se reescribe entera cada vez (así el repo no crece con cada .exe).
set -euo pipefail
cd "$(dirname "$0")/.."
NOTAS="${1:-}"
EXE=dist/LolcitoScout.exe
[ -f "$EXE" ] || { echo "Primero compilá: herramientas/construir_exe.sh"; exit 1; }
VERSION=$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('lolscout/version.py').read()).group(1))")
REMOTO=$(git remote get-url origin)

tmp=$(mktemp -d)
cp "$EXE" "$tmp/LolcitoScout.exe"
python3 - "$tmp" "$VERSION" "$NOTAS" <<'PY'
import hashlib, json, os, sys
d, version, notas = sys.argv[1], sys.argv[2], sys.argv[3]
b = open(os.path.join(d, "LolcitoScout.exe"), "rb").read()
json.dump({"version": version, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b), "notas": notas},
          open(os.path.join(d, "version.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY
cat > "$tmp/LEEME.md" <<TXT
# Lolcito Scout — descargas

Última versión: **$VERSION**

Descargá [LolcitoScout.exe](https://github.com/imansillaaa-collab/lolcito-scout/raw/descargas/LolcitoScout.exe).
Una vez abierto, se actualiza solo.
TXT
(
  cd "$tmp"
  git init -q -b descargas
  git config user.name "lolcito-bot"
  git config user.email "lolcito-bot@users.noreply.github.com"
  git add .
  git commit -qm "LolcitoScout.exe $VERSION"
  git push -qf "$REMOTO" descargas
)
echo "Publicado $VERSION en la rama descargas. Las apps abiertas lo ven en unos minutos."
