#!/usr/bin/env bash
# Una tanda del workflow «Estadísticas»: junta partidas nuevas, publica en la rama «datos» y le avisa al
# workflow que guarde las partidas acumuladas (así, si la corrida se corta, no se pierde lo ya juntado).
# Uso (lo llama .github/workflows/estadisticas.yml): herramientas/tanda.sh <número de tanda>
# Necesita FIN (hora de cierre, en segundos), RIOT_API_KEY y DESTINO en el entorno.
set -uo pipefail
cd "$(dirname "$0")/.."
tanda=$1

# otra tanda solo si queda tiempo para terminarla (cada una tarda ~30 minutos)
if [ "$tanda" -gt 1 ] && [ $(( FIN - $(date +%s) )) -lt $(( 45 * 60 )) ]; then
  echo "No queda tiempo para la tanda $tanda: termino acá."
  exit 0
fi

python publicar.py || echo "La tanda $tanda terminó con error: sigo con la próxima"
if [ -f publicado/indice.json ]; then
  (
    cd publicado
    rm -rf .git
    git init -q -b datos
    git config user.name "lolcito-bot"
    git config user.email "lolcito-bot@users.noreply.github.com"
    git add .
    git commit -qm "Estadísticas $(date -u '+%F %H:%M') (tanda $tanda)"
    git push -qf "$DESTINO" datos
  ) || echo "No pude publicar la tanda $tanda: se publica con la próxima"
fi
echo "guardar=si" >> "$GITHUB_OUTPUT"
