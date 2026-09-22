"""Genera partidas simuladas para probar la app sin API key (python main.py demo)."""
import random
import time

from . import db

POSITIONS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


ROLE_ITEMS = {  # ítems realistas por rol, para que la demo tenga sentido
    "BOTTOM": [3031, 6672, 3094, 3046, 3036, 3033, 3072, 3026, 3139, 6673, 6675, 3085, 3124, 3153, 3087, 3508, 6676],
    "UTILITY": [3190, 3107, 6617, 3050, 3109, 2065, 3504, 6616, 3222, 6620, 4005, 3011, 3075, 3143],
    "TOP": [3153, 3075, 3143, 3065, 4633, 6653, 3302, 3179, 6694, 3142],
    "JUNGLE": [3142, 3179, 6694, 3814, 3100, 4645, 3089, 3157, 6676],
    "MIDDLE": [6655, 3089, 3157, 4633, 3100, 4645, 3003, 6653, 3165],
}
ROLE_BOOTS = {"BOTTOM": [3006, 3006, 3009, 3111, 3047], "UTILITY": [3158, 3111, 3047, 3009],
              "TOP": [3047, 3111], "JUNGLE": [3047, 3111, 3020], "MIDDLE": [3020, 3158]}
FIXED = {"TOP": ["Mordekaiser", "Garen", "Darius", "Malphite"], "JUNGLE": ["Evelynn", "LeeSin", "Vi", "Amumu"],
         "MIDDLE": ["Vladimir", "Ahri", "Syndra", "Zed"], "BOTTOM": ["Jinx", "Kaisa", "Caitlyn", "Ezreal"],
         "UTILITY": ["Soraka", "Thresh", "Nautilus", "Morgana", "Lulu"]}


def fake_match(i: int, dd, strength: dict, pools: dict) -> dict:
    keystones = [8005, 8008, 8021, 8214, 8229, 8465, 8439, 8351]
    teams = {100: {}, 200: {}}
    for pos in POSITIONS:
        picks = random.sample(pools[pos], 2)
        teams[100][pos], teams[200][pos] = picks
    power = {t: sum(strength.get(c, 0) for c in teams[t].values()) for t in teams}
    p100 = 0.5 + (power[100] - power[200])
    win100 = random.random() < p100
    parts = []
    for tid, team in teams.items():
        for pos, cid in team.items():
            rnd = random.Random(cid)
            core = rnd.sample(ROLE_ITEMS[pos], 6)
            extra = [i for i in ROLE_ITEMS[pos] if i not in core]
            its = random.sample(core, 3) + [random.choice(extra) if random.random() < 0.3 else 0]
            its += [random.choice(ROLE_BOOTS[pos]) if random.random() < 0.3 else rnd.choice(ROLE_BOOTS[pos]), 0]
            parts.append({
                "puuid": f"p{i}-{tid}-{pos}", "teamId": tid, "teamPosition": pos, "championId": cid,
                "win": (tid == 100) == win100, "kills": random.randint(0, 12),
                "deaths": random.randint(1, 10), "assists": random.randint(0, 15),
                **{f"item{k}": its[k] for k in range(6)},
                "perks": {"styles": [{"style": 8000, "selections": [{"perk": rnd.choice(keystones)}]}, {"style": 8300}]},
                "summoner1Id": 4, "summoner2Id": rnd.choice([7, 14, 3]),
            })
    return {
        "metadata": {"matchId": f"LA2_DEMO{i}"},
        "info": {
            "queueId": 420, "gameVersion": f"{dd.patch}.123.4567", "gameDuration": random.randint(1200, 2200),
            "gameStartTimestamp": int(time.time() * 1000) - i * 60000, "participants": parts,
            "teams": [{"teamId": t, "bans": [{"championId": random.choice(pools["MIDDLE"])} for _ in range(5)]}
                      for t in (100, 200)],
        },
    }


def generate(conn, dd, n: int = 3000, seed: int = 7) -> None:
    random.seed(seed)
    ids = list(dd.champions)
    pools = {pos: [dd.champ_by_alias[a.lower()] for a in names] for pos, names in FIXED.items()}
    used = {c for v in pools.values() for c in v}
    first_tag = {"BOTTOM": "Marksman", "UTILITY": "Support", "TOP": "Tank", "JUNGLE": "Fighter", "MIDDLE": "Mage"}
    for pos, tag in first_tag.items():
        extra = [c for c in ids if dd.champions[c]["tags"][0] == tag and c not in used][:18]
        pools[pos] += extra
        used.update(extra)
    strength = {c: random.gauss(0, 0.012) for c in ids}
    for i in range(n):
        db.save_match(conn, fake_match(i, dd, strength, pools))
    conn.commit()
