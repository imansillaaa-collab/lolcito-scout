"""Publicador diario de estadísticas (lo corre GitHub Actions con la API key del dueño).

Para cada nivel de rango (bajo / medio / alto) escautea partidas nuevas, las acumula en una base
por nivel, borra parches viejos y escribe publicado/stats_<nivel>.json, que la app descarga.

Uso local:  RIOT_API_KEY=RGAPI-... python publicar.py [--solo medio] [--demo]
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lolscout import config, db
from lolscout.analyze import analyze
from lolscout.ddragon import DDragon
from lolscout.live.advisor import role_distribution
from lolscout.online import BRACKETS

OUT = Path(__file__).parent / "publicado"
ALL_ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def publish_bracket(name, tiers, dd, client, demo=False):
    config.TIERS = tiers
    config.ROLES = ALL_ROLES
    conn = db.connect(config.DATA_DIR / f"stats_{name}.db")
    if demo:
        from lolscout.demo import generate
        if not conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]:
            generate(conn, dd, n=1500, seed=hash(name) % 1000)
    else:
        from lolscout.collect import collect
        collect(client, conn, log=lambda m: print(f"[{name}] {m}", flush=True))
    db.prune(conn, keep_patches=2)
    result = analyze(conn, dd)
    dist = {str(c): dict(v) for c, v in role_distribution(conn).items()}
    conn.close()
    payload = {
        "format": 1, "bracket": name, "tiers": tiers, "platform": config.PLATFORM,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "patches": result.get("patches", []), "matches": result.get("matches", 0),
        "version": result.get("version"), "roles": result.get("roles", {}), "duos": result.get("duos", []),
        "champs": {str(c): v for c, v in (result.get("champs") or {}).items()},
        "dist": dist,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / f"stats_{name}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                           encoding="utf-8")
    print(f"[{name}] publicado: {payload['matches']} partidas, parche {', '.join(payload['patches'])}", flush=True)
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
    config.PLAYERS_PER_RUN = int(config.PLAYERS_PER_RUN)
    index = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "brackets": {}}
    t0 = time.time()
    for name, tiers in BRACKETS.items():
        if args.solo and name != args.solo:
            continue
        try:
            p = publish_bracket(name, tiers, dd, client, args.demo)
            index["brackets"][name] = {"matches": p["matches"], "patches": p["patches"]}
        except Exception as e:  # un nivel que falla no frena a los demás
            print(f"[{name}] ERROR: {e}", file=sys.stderr, flush=True)
    (OUT / "indice.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Listo en {int(time.time() - t0)} s")


if __name__ == "__main__":
    main()
