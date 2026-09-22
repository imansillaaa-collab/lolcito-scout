"""Escauteo diario: toma jugadores al azar del rango elegido y baja sus últimas rankeds."""
import random
import time

from . import config, db
from .riot import RiotClient


def collect(client: RiotClient = None, conn=None, log=print) -> int:
    client = client or RiotClient()
    conn = conn or db.connect()

    # 1) Jugadores semilla del rango elegido (Platino y Esmeralda, divisiones I a IV)
    log(f"Buscando jugadores en {', '.join(config.TIERS)} ({config.PLATFORM})...")
    players = []
    for tier in config.TIERS:
        for div in config.DIVISIONS:
            entries = client.league_entries(tier, div, page=random.randint(1, 3))
            if not entries:
                entries = client.league_entries(tier, div, page=1)
            players += [e["puuid"] for e in entries if e.get("puuid")]
    random.shuffle(players)
    players = players[: config.PLAYERS_PER_RUN]
    log(f"  {len(players)} jugadores seleccionados")

    # 2) IDs de sus últimas partidas rankeds
    since = int(time.time()) - config.DAYS_BACK * 86400
    ids = []
    for i, puuid in enumerate(players, 1):
        for mid in client.match_ids(puuid, config.MATCHES_PER_PLAYER, since):
            if mid not in ids and not db.known_match(conn, mid):
                ids.append(mid)
        if i % 20 == 0:
            log(f"  {i}/{len(players)} jugadores revisados, {len(ids)} partidas nuevas")
    ids = ids[: config.MAX_NEW_MATCHES]

    # 3) Detalle de cada partida
    log(f"Descargando {len(ids)} partidas (tarda unos minutos por los límites de la API)...")
    saved = 0
    for i, mid in enumerate(ids, 1):
        match = client.match(mid)
        if match and db.save_match(conn, match):
            saved += 1
        elif not match:
            db.mark_seen(conn, mid)
        if i % 25 == 0:
            conn.commit()
            log(f"  {i}/{len(ids)}")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    log(f"Listo: {saved} partidas nuevas guardadas ({total} en total). Pedidos a la API: {client.requests_made}")
    return saved


def my_puuid(client: RiotClient) -> str | None:
    if not config.MY_RIOT_ID or "#" not in config.MY_RIOT_ID:
        return None
    name, tag = config.MY_RIOT_ID.rsplit("#", 1)
    acc = client.account_by_riot_id(name, tag)
    return acc["puuid"] if acc else None


def collect_mine(client: RiotClient, conn, puuid: str, count: int = 30, log=print) -> int:
    """Baja tus propias rankeds recientes para las recomendaciones personales."""
    saved = 0
    for mid in client.match_ids(puuid, count):
        if db.known_match(conn, mid):
            continue
        match = client.match(mid)
        if match and db.save_match(conn, match):
            saved += 1
    conn.commit()
    log(f"Tus partidas: {saved} nuevas")
    return saved
