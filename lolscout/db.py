"""Base de datos local (SQLite). Guarda solo lo necesario de cada partida."""
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id   TEXT PRIMARY KEY,
    patch      TEXT NOT NULL,
    game_start INTEGER NOT NULL,
    duration   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS participants (
    match_id    TEXT NOT NULL,
    puuid       TEXT,
    team_id     INTEGER NOT NULL,
    position    TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    win         INTEGER NOT NULL,
    kills INTEGER, deaths INTEGER, assists INTEGER,
    items       TEXT,          -- ids separados por coma (item0..item5)
    keystone    INTEGER,
    primary_style INTEGER,
    sub_style   INTEGER,
    spell1 INTEGER, spell2 INTEGER,
    PRIMARY KEY (match_id, puuid)
);
CREATE TABLE IF NOT EXISTS bans (
    match_id    TEXT NOT NULL,
    team_id     INTEGER NOT NULL,
    champion_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_ids (       -- partidas ya descartadas (otra cola, remake...)
    match_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS paginas (        -- la página de runas completa de cada jugador
    match_id    TEXT NOT NULL,
    position    TEXT,
    champion_id INTEGER,
    win         INTEGER,
    pagina      TEXT        -- "8000:8010,9111,9104,8014|8400:8444,8451|5008,5008,5011"
);
CREATE TABLE IF NOT EXISTS habilidades (    -- en qué orden subió las habilidades (sale de la línea de tiempo)
    match_id    TEXT NOT NULL,
    position    TEXT,
    champion_id INTEGER,
    win         INTEGER,
    orden       TEXT        -- "QWEQQRQEQQREEWWRWW" (una letra por nivel, hasta el 18)
);
CREATE INDEX IF NOT EXISTS idx_pag ON paginas(champion_id, position);
CREATE INDEX IF NOT EXISTS idx_hab ON habilidades(champion_id, position);
CREATE INDEX IF NOT EXISTS idx_part_pos ON participants(position, champion_id);
CREATE INDEX IF NOT EXISTS idx_match_patch ON matches(patch);
"""


def connect(path=None) -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def known_match(conn, match_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM matches WHERE match_id=? UNION SELECT 1 FROM seen_ids WHERE match_id=?",
        (match_id, match_id),
    ).fetchone() is not None


def mark_seen(conn, match_id: str):
    conn.execute("INSERT OR IGNORE INTO seen_ids VALUES (?)", (match_id,))


def texto_pagina(perks: dict) -> str:
    """La página de runas de match-v5 en un texto corto: "8000:8010,9111,9104,8014|8400:8444,8451|5008,5008,5011"."""
    try:
        s1, s2 = perks["styles"][0], perks["styles"][1]
        st = perks["statPerks"]
        a = ",".join(str(x["perk"]) for x in s1["selections"])
        b = ",".join(str(x["perk"]) for x in s2["selections"])
        if len(s1["selections"]) != 4 or len(s2["selections"]) != 2:
            return ""
        return f"{s1['style']}:{a}|{s2['style']}:{b}|{st['offense']},{st['flex']},{st['defense']}"
    except (KeyError, IndexError, TypeError):
        return ""


def pagina_de_texto(t: str) -> dict:
    p1, p2, f = t.split("|")
    a, ra = p1.split(":")
    b, rb = p2.split(":")
    return {"primary": int(a), "sub": int(b), "perks": [int(x) for x in ra.split(",")] + [int(x) for x in rb.split(",")],
            "shards": [int(x) for x in f.split(",")]}


def save_match(conn, match: dict) -> bool:
    """Guarda una partida de match-v5. Devuelve False si se descarta."""
    meta, info = match["metadata"], match["info"]
    mid = meta["matchId"]
    if info.get("queueId") != config.RANKED_SOLO_QUEUE or info.get("gameDuration", 0) < 15 * 60:
        mark_seen(conn, mid)          # remakes y partidas muy cortas ensucian los datos
        return False
    patch = ".".join(info["gameVersion"].split(".")[:2])
    conn.execute(
        "INSERT OR IGNORE INTO matches VALUES (?,?,?,?)",
        (mid, patch, info["gameStartTimestamp"] // 1000, info["gameDuration"]),
    )
    for p in info["participants"]:
        styles = p.get("perks", {}).get("styles", [{}, {}])
        keystone = styles[0].get("selections", [{}])[0].get("perk") if styles else None
        items = ",".join(str(p.get(f"item{i}", 0)) for i in range(6))
        conn.execute(
            "INSERT OR IGNORE INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid, p.get("puuid"), p["teamId"], p.get("teamPosition") or "NONE",
                p["championId"], int(p["win"]), p.get("kills"), p.get("deaths"), p.get("assists"),
                items, keystone,
                styles[0].get("style") if styles else None,
                styles[1].get("style") if len(styles) > 1 else None,
                p.get("summoner1Id"), p.get("summoner2Id"),
            ),
        )
        pagina = texto_pagina(p.get("perks") or {})
        if pagina:
            conn.execute("INSERT INTO paginas VALUES (?,?,?,?,?)",
                         (mid, p.get("teamPosition") or "NONE", p["championId"], int(p["win"]), pagina))
    for team in info.get("teams", []):
        for b in team.get("bans", []):
            if b.get("championId", -1) > 0:
                conn.execute("INSERT INTO bans VALUES (?,?,?)", (mid, team["teamId"], b["championId"]))
    return True


TECLAS = {1: "Q", 2: "W", 3: "E", 4: "R"}


def save_habilidades(conn, match: dict, timeline: dict) -> int:
    """Guarda en qué orden subió cada jugador sus habilidades (eventos SKILL_LEVEL_UP de la línea de tiempo)."""
    info, mid = match["info"], match["metadata"]["matchId"]
    por_id = {p.get("participantId"): p for p in info["participants"]}
    orden = {}
    for fr in ((timeline or {}).get("info") or {}).get("frames") or []:
        for ev in fr.get("events") or []:
            if ev.get("type") == "SKILL_LEVEL_UP" and ev.get("levelUpType", "NORMAL") == "NORMAL":
                tecla = TECLAS.get(ev.get("skillSlot"))
                if tecla:
                    orden.setdefault(ev.get("participantId"), []).append(tecla)
    n = 0
    for pid, seq in orden.items():
        p = por_id.get(pid)
        if p and len(seq) >= 6:
            conn.execute("INSERT INTO habilidades VALUES (?,?,?,?,?)",
                         (mid, p.get("teamPosition") or "NONE", p["championId"], int(p["win"]), "".join(seq[:18])))
            n += 1
    return n


def prune(conn, keep_patches: int = 2) -> None:
    """Borra partidas de parches viejos para que la base no crezca sin fin."""
    patches = [r[0] for r in conn.execute("SELECT DISTINCT patch FROM matches")]
    patches.sort(key=lambda p: tuple(int(x) for x in p.split(".") if x.isdigit()), reverse=True)
    old = patches[keep_patches:]
    for p in old:
        ids = [r[0] for r in conn.execute("SELECT match_id FROM matches WHERE patch=?", (p,))]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for table in ("participants", "bans", "paginas", "habilidades", "matches"):
                conn.execute(f"DELETE FROM {table} WHERE match_id IN ({ph})", chunk)
    if old:
        conn.commit()
        conn.execute("VACUUM")
