"""Publicador diario de estadísticas (lo corre GitHub Actions con la API key del dueño).

Para cada nivel de rango (bajo / medio / alto) escautea partidas nuevas, las acumula en una base
por nivel, borra parches viejos y escribe publicado/stats_<nivel>.json, que la app descarga.

Uso local:  RIOT_API_KEY=RGAPI-... python publicar.py [--solo medio] [--demo]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from lolscout import config, db
from lolscout.analyze import analyze
from lolscout.ddragon import DDragon
from lolscout.live.advisor import role_distribution
from lolscout.online import BRACKETS

OUT = Path(__file__).parent / "publicado"
ALL_ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
HISTORY_KEEP = 300  # ~3 semanas de tandas
# Orden y peso de cada nivel en cada tanda: Oro–Platino primero y con más jugadores, después Hierro–Plata,
# y Esmeralda–Maestro con menos (el tiempo de la API key se reparte según estos pesos)
PRIORIDAD = [("medio", 1.35), ("bajo", 1.0), ("alto", 0.55)]


def previous_history():
    """Historial de corridas anteriores: el indice.json de la tanda anterior de esta misma corrida
    o, si es la primera tanda, el que ya está publicado en la rama "datos"."""
    try:
        return json.loads((OUT / "indice.json").read_text(encoding="utf-8")).get("historial", [])
    except Exception:
        pass
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        try:
            url = f"https://raw.githubusercontent.com/{repo}/datos/indice.json"
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read()).get("historial", [])
        except Exception as e:
            print(f"No pude leer el historial anterior ({e}); empiezo uno nuevo.", flush=True)
            return []
    return []


def publish_bracket(name, tiers, dd, client, demo=False):
    config.TIERS = tiers
    config.ROLES = ALL_ROLES
    conn = db.connect(config.DATA_DIR / f"stats_{name}.db")
    t0 = time.time()
    before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    req0 = client.requests_made if client else 0
    new = 0
    if demo:
        from lolscout.demo import generate
        if not conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]:
            generate(conn, dd, n=1500, seed=hash(name) % 1000)
    else:
        from lolscout.collect import collect
        new = collect(client, conn, log=lambda m: print(f"[{name}] {m}", flush=True))
    before_prune = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    db.prune(conn, keep_patches=2)
    after_prune = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    result = analyze(conn, dd)
    dist = {str(c): dict(v) for c, v in role_distribution(conn).items()}
    conn.close()
    payload = {
        "format": 1, "bracket": name, "tiers": tiers, "platform": config.PLATFORM,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "patches": result.get("patches", []), "matches": result.get("matches", 0),
        "version": result.get("version"), "roles": result.get("roles", {}), "duos": result.get("duos", []),
        "dia": result.get("dia"),
        "champs": {str(c): v for c, v in (result.get("champs") or {}).items()},
        "dist": dist,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / f"stats_{name}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                           encoding="utf-8")
    print(f"[{name}] publicado: {payload['matches']} partidas, parche {', '.join(payload['patches'])}", flush=True)
    payload["_corrida"] = {"antes": before, "nuevas": new, "borradas": before_prune - after_prune,
                           "base": after_prune, "pedidos": (client.requests_made - req0) if client else 0,
                           "segundos": int(time.time() - t0)}
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", choices=list(BRACKETS))
    ap.add_argument("--demo", action="store_true", help="datos simulados, sin API key (para probar)")
    args = ap.parse_args()

    dd = DDragon()
    client = None
    if not args.demo:
        from lolscout.riot import RiotClient
        client = RiotClient()
    jugadores_base, partidas_base = int(config.PLAYERS_PER_RUN), int(config.MAX_NEW_MATCHES)
    index = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "brackets": {}}
    run = {"inicio": index["generated"], "evento": os.environ.get("GITHUB_EVENT_NAME", "local"), "niveles": {}}
    t0 = time.time()
    for name, peso in PRIORIDAD:
        tiers = BRACKETS[name]
        if args.solo and name != args.solo:
            continue
        config.PLAYERS_PER_RUN = max(20, int(jugadores_base * peso))
        config.MAX_NEW_MATCHES = max(100, int(partidas_base * peso))
        try:
            p = publish_bracket(name, tiers, dd, client, args.demo)
            index["brackets"][name] = {"matches": p["matches"], "patches": p["patches"]}
            run["niveles"][name] = {"partidas": p["matches"], "parches": p["patches"], **p["_corrida"]}
        except Exception as e:  # un nivel que falla no frena a los demás
            print(f"[{name}] ERROR: {e}", file=sys.stderr, flush=True)
            run["niveles"][name] = {"error": str(e)[:200]}
    run["minutos"] = round((time.time() - t0) / 60, 1)
    index["historial"] = (previous_history() + [run])[-HISTORY_KEEP:]
    (OUT / "indice.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Listo en {int(time.time() - t0)} s")


if __name__ == "__main__":
    main()
