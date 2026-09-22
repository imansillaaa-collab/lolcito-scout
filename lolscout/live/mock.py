"""Simulación de una selección de campeones y una partida, para probar el asistente sin abrir el LoL."""
import time

START = time.time()
MODE = "partida"
SPEED = 20        # 1 segundo real = 20 segundos de partida
T0 = 180          # la simulación arranca en el minuto 3
END = 1935        # la partida termina a los 32:15 (gana tu equipo)
LINGER = 4        # segundos reales que queda la pantalla de victoria antes de cerrarse


def restart(mode="partida"):
    global START, MODE, T0
    START = time.time()
    MODE = mode
    T0 = END - 20 if mode == "resumen" else 180


def game_time():
    return min((time.time() - START) * SPEED + T0, END)


def game_over():
    return (time.time() - START) * SPEED + T0 >= END + LINGER * SPEED

ALLIES = [("Garen", "top"), ("LeeSin", "jungle"), ("Ahri", "middle"), ("Jinx", "bottom"), ("Thresh", "utility")]
ENEMIES = ["Mordekaiser", "Evelynn", "Vladimir", "Kaisa", "Soraka"]


def _ids(dd, aliases):
    return [dd.champ_by_alias[a.lower()] for a in aliases]


class MockLCU:
    """Selección que avanza sola: cada 4 segundos se revela un pick más."""

    def __init__(self, dd):
        self.dd = dd

    def phase(self):
        if MODE == "draft":
            return "ChampSelect"
        if MODE == "inicio":
            return "Lobby"
        return "EndOfGame" if game_over() else "InProgress"

    def get(self, path):
        """Lo que devolvería el cliente de LoL: historial de partidas y, al terminar, la partida simulada."""
        if path.startswith("/lol-match-history/v1/products/lol/current-summoner/matches"):
            games = [{"gameId": g[0], "mapId": 11, "gameCreation": g[5]} for g in HISTORY_GAMES]
            if game_over() and MODE != "draft":
                games.insert(0, {"gameId": 777, "mapId": 11, "gameCreation": int(time.time() * 1000)})
            return {"games": {"games": games}}
        for prefix in ("/lol-match-history/v1/games/", "/lol-match-history/v1/game-timelines/"):
            if path.startswith(prefix):
                gid = int(path[len(prefix):])
                timeline = "timelines" in path
                if gid == 777:
                    if not game_over():
                        return None
                    return mock_timeline() if timeline else mock_match(self.dd)
                g = next((g for g in HISTORY_GAMES if g[0] == gid), None)
                if g:
                    mh, tl = gen_match(self.dd, *g, puuid="demo")
                    return tl if timeline else mh
                return None
        if not game_over():
            return None
        if path.startswith("/lol-gameflow/v1/session"):
            return {"gameData": {"gameId": 777}}
        if path.startswith("/lol-end-of-game"):
            return {"gameId": 777}
        return None


# ------------------------------------------------------------------ historial simulado
POOL = {"TOP": ["Garen", "Darius", "Mordekaiser", "Sett", "Malphite"],
        "JUNGLE": ["LeeSin", "Evelynn", "Vi", "Warwick", "Kayn"],
        "MIDDLE": ["Ahri", "Vladimir", "Syndra", "Yasuo", "Viktor"],
        "BOTTOM": ["Jinx", "Kaisa", "Caitlyn", "Ezreal", "Jhin", "MissFortune"],
        "UTILITY": ["Thresh", "Soraka", "Lulu", "Nautilus", "Leona"]}
ITEMS = {"BOTTOM": [6672, 3031, 3094, 3036, 3033, 3046, 3072, 6675, 3124, 3085],
         "MIDDLE": [6655, 3089, 3157, 4645, 3100, 3135],
         "TOP": [6675, 3047, 3111, 3065, 4633, 3053],
         "JUNGLE": [6675, 3047, 3111, 3065, 3100, 4645],
         "UTILITY": [3190, 3107, 6617, 3865, 3050]}
BOOTS = {"BOTTOM": 3006, "MIDDLE": 3020, "TOP": 3047, "JUNGLE": 3111, "UTILITY": 3158}
_NOW = int(time.time() * 1000)
H = 3600 * 1000
# gameId, tu campeón, tu rol, ganaste, minutos, cuándo
HISTORY_GAMES = [
    (1009, "Kaisa", "BOTTOM", False, 27, _NOW - 2 * H), (1008, "Jinx", "BOTTOM", True, 31, _NOW - 3 * H),
    (1007, "Thresh", "UTILITY", True, 24, _NOW - 26 * H), (1006, "Caitlyn", "BOTTOM", True, 29, _NOW - 27 * H),
    (1005, "Jinx", "BOTTOM", False, 35, _NOW - 28 * H), (1004, "Ezreal", "BOTTOM", True, 22, _NOW - 50 * H),
    (1003, "Kaisa", "BOTTOM", True, 33, _NOW - 51 * H), (1002, "Thresh", "UTILITY", False, 30, _NOW - 74 * H),
    (1001, "Jhin", "BOTTOM", False, 3, _NOW - 75 * H), (1000, "Jinx", "BOTTOM", True, 26, _NOW - 98 * H),
]
SMURF_GAMES = [
    (2003, "Lulu", "UTILITY", True, 28, _NOW - 30 * H), (2002, "Nautilus", "UTILITY", False, 25, _NOW - 54 * H),
    (2001, "MissFortune", "BOTTOM", True, 21, _NOW - 120 * H), (2000, "Leona", "UTILITY", True, 32, _NOW - 170 * H),
]


def gen_match(dd, gid, my_alias, my_role, win, minutes, created, puuid="demo"):
    """Una partida inventada con el mismo formato que el historial del cliente de LoL."""
    import random
    rnd = random.Random(gid)
    roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    used = {my_alias}
    team = {}
    for side in (100, 200):
        for r in roles:
            if side == 100 and r == my_role:
                team[(side, r)] = my_alias
                continue
            c = rnd.choice([a for a in POOL[r] if a not in used])
            used.add(c)
            team[(side, r)] = c
    dur = minutes * 60 + rnd.randint(0, 59)
    parts, idents, pid_of = [], [], {}
    for pid, (side, r) in enumerate([(s_, r) for s_ in (100, 200) for r in roles], start=1):
        alias = team[(side, r)]
        me = side == 100 and r == my_role
        won = win if side == 100 else not win
        pid_of[(side, r)] = pid
        k = rnd.randint(0, 4) + (3 if won else 0) + (2 if r in ("MIDDLE", "BOTTOM") else 0)
        if r == "UTILITY":
            k = rnd.randint(0, 3)
        d = rnd.randint(2, 6) + (0 if won else 2) + (1 if me and not win else 0)
        a = rnd.randint(3, 10) + (8 if r == "UTILITY" else 0) + (3 if won else 0)
        if side == 100:
            a = min(a, 22)
        if minutes < 5:  # remake
            k = d = a = 0
        rate = {"TOP": 6.4, "JUNGLE": 5.4, "MIDDLE": 7.0, "BOTTOM": 7.0, "UTILITY": 1.1}[r] + rnd.uniform(-1.2, 1.0)
        cs = int(rate * dur / 60)
        n = max(1, min(6, int(dur / 60 / 5.5)))
        items = rnd.sample(ITEMS[r], min(n, len(ITEMS[r]))) + [BOOTS[r]]
        dmg = int(dur / 60 * {"TOP": 650, "JUNGLE": 520, "MIDDLE": 800, "BOTTOM": 850, "UTILITY": 260}[r] * rnd.uniform(0.7, 1.3))
        vis = int(dur / 60 * (1.9 if r == "UTILITY" else 1.0 if r == "JUNGLE" else 0.6) * rnd.uniform(0.6, 1.3))
        jungle = r == "JUNGLE"
        parts.append({"participantId": pid, "teamId": side, "championId": dd.champ_by_alias[alias.lower()],
                      "timeline": {"lane": "BOTTOM" if r == "UTILITY" else r, "role": "SUPPORT" if r == "UTILITY" else "CARRY" if r == "BOTTOM" else "SOLO"},
                      "stats": {"kills": k, "deaths": d, "assists": a, "totalMinionsKilled": 10 if jungle else cs,
                                "neutralMinionsKilled": cs if jungle else rnd.randint(0, 12),
                                "goldEarned": int(dur / 60 * 360 + k * 300 + cs * 18), "totalDamageDealtToChampions": dmg,
                                "visionScore": vis, "visionWardsBoughtInGame": rnd.randint(0, 3 if r != "UTILITY" else 9),
                                "wardsPlaced": int(vis / 1.5), "champLevel": min(18, 6 + int(dur / 60 / 2.2)), "win": won,
                                **{f"item{i}": it for i, it in enumerate(items[:7])}}})
        idents.append({"participantId": pid, "player": {"gameName": "Vos" if me else f"{alias}{rnd.randint(10, 99)}",
                                                        "puuid": puuid if me else f"x{gid}-{pid}"}})
    # línea de tiempo: oro y súbditos cada minuto, tus muertes, objetivos y tu primer ítem
    my_pid = pid_of[(100, my_role)]
    frames = []
    events = []
    drakes = {100: 0, 200: 0}
    t = 300
    while t < dur - 60:
        side = 100 if rnd.random() < (0.6 if win else 0.4) else 200
        drakes[side] += 1
        events.append({"type": "ELITE_MONSTER_KILL", "monsterType": "DRAGON", "killerId": pid_of[(side, "JUNGLE")], "timestamp": t * 1000})
        t += 300 + rnd.randint(0, 120)
    my_deaths = sorted(rnd.randint(180, max(dur - 30, 200)) for _ in range(parts[my_pid - 1]["stats"]["deaths"]))
    if not win and events and my_deaths:  # en las derrotas, alguna muerte justo antes de un dragón rival
        rival = [e for e in events if e["killerId"] > 5]
        if rival:
            my_deaths[0] = rival[0]["timestamp"] // 1000 - 30
    events += [{"type": "CHAMPION_KILL", "victimId": my_pid, "killerId": 6, "timestamp": dt * 1000} for dt in my_deaths]
    events.append({"type": "ITEM_PURCHASED", "participantId": my_pid, "itemId": parts[my_pid - 1]["stats"]["item0"],
                   "timestamp": rnd.randint(10 * 60, 16 * 60) * 1000})
    lane_opp = pid_of[(200, my_role)]
    for m in range(0, dur // 60 + 1):
        pf = {}
        for p in parts:
            pid = p["participantId"]
            base = 395 if p["timeline"]["role"] == "CARRY" else 250 if p["timeline"]["role"] == "SUPPORT" else 380
            edge = (25 if win else -25) if pid == my_pid else 0
            pf[str(pid)] = {"participantId": pid, "totalGold": 500 + (base + edge + (gid % 7) * 3 * (1 if pid == lane_opp else 0)) * m,
                            "minionsKilled": int(p["stats"]["totalMinionsKilled"] * m / max(dur / 60, 1)),
                            "jungleMinionsKilled": int(p["stats"]["neutralMinionsKilled"] * m / max(dur / 60, 1)),
                            "level": min(18, 1 + int(m / 1.8))}
        frames.append({"timestamp": m * 60000, "participantFrames": pf,
                       "events": [e for e in events if m * 60000 <= e["timestamp"] < (m + 1) * 60000]})
    mh = {"gameId": gid, "gameCreation": created, "gameDuration": dur, "queueId": 420 if gid % 3 else 440, "mapId": 11,
          "participants": parts, "participantIdentities": idents,
          "teams": [{"teamId": s_, "win": "Win" if (win if s_ == 100 else not win) else "Fail", "dragonKills": drakes[s_],
                     "baronKills": int(dur > 1500 and (win if s_ == 100 else not win)), "riftHeraldKills": rnd.randint(0, 1),
                     "towerKills": rnd.randint(6, 10) if (win if s_ == 100 else not win) else rnd.randint(1, 5),
                     "inhibitorKills": 1 if (win if s_ == 100 else not win) else 0, "hordeKills": rnd.randint(0, 3)}
                    for s_ in (100, 200)]}
    return mh, {"frames": frames}


def _mock_account(self):
    return {"gameName": "Vos", "tagLine": "LAS", "puuid": "demo", "profileIconId": 29, "summonerLevel": 187}


def _mock_ranked(self):
    return {"tier": "PLATINUM", "division": "II", "lp": 47, "wins": 61, "losses": 55}


def _mock_games(self, count=60):
    import random
    rnd = random.Random(3)
    pool = _ids(self.dd, ["Jinx", "Jhin", "Kaisa", "Thresh", "Caitlyn", "Ezreal"])
    return [(rnd.choice(pool[:4] * 3 + pool), rnd.random() < 0.53, 420) for _ in range(count)]


MockLCU.summoner = _mock_account
MockLCU.ranked = _mock_ranked
MockLCU.my_games = _mock_games


MY_DEATHS = [470, 600, 1215, 1700]
KDA_MOD = {"Garen": (-2, 1, -1), "LeeSin": (-1, 2, 5), "Ahri": (3, -1, 2), "Thresh": (-5, 2, 11), "Jinx": (0, 0, 0),
           "Mordekaiser": (1, 1, -3), "Evelynn": (2, 0, 1), "Vladimir": (0, 1, -2), "Kaisa": (1, 0, -1), "Soraka": (-5, 1, 12)}
CS_RATE = {"Jinx": 6.7, "Kaisa": 7.3, "Ahri": 7.4, "Vladimir": 7.0, "Garen": 6.6, "Mordekaiser": 6.9,
           "LeeSin": 5.4, "Evelynn": 5.8, "Thresh": 1.1, "Soraka": 0.9}


def _final(dd):
    """Última lectura de la partida (la del final) para armar el historial simulado."""
    return MockLiveClient(dd)._snapshot(END)


def mock_match(dd):
    import random
    rnd = random.Random(7)
    g = _final(dd)
    names = [a for a, _ in ALLIES] + ENEMIES
    dmg = {"Garen": 17800, "LeeSin": 14100, "Ahri": 24600, "Jinx": 27300, "Thresh": 6900,
           "Mordekaiser": 23800, "Evelynn": 19500, "Vladimir": 26100, "Kaisa": 25200, "Soraka": 5800}
    parts, idents = [], []
    for pid, (alias, pl) in enumerate(zip(names, g["allPlayers"]), start=1):
        sc = pl["scores"]
        items = [i["itemID"] for i in pl["items"]][:6] + [3363]
        jungle = alias in ("LeeSin", "Evelynn")
        parts.append({"participantId": pid, "teamId": 100 if pid <= 5 else 200, "championId": dd.champ_by_alias[alias.lower()],
                      "timeline": {}, "stats": {
                          "kills": sc["kills"], "deaths": sc["deaths"], "assists": sc["assists"],
                          "totalMinionsKilled": 0 if jungle else sc["creepScore"], "neutralMinionsKilled": sc["creepScore"] if jungle else 8,
                          "goldEarned": 9000 + sc["kills"] * 300 + sc["creepScore"] * 18 + rnd.randint(0, 900),
                          "totalDamageDealtToChampions": dmg[alias], "visionScore": int(sc["wardScore"]),
                          "visionWardsBoughtInGame": 1 if alias == "Jinx" else rnd.randint(1, 7), "wardsPlaced": int(sc["wardScore"] / 1.4),
                          "champLevel": pl["level"], "win": pid <= 5,
                          **{f"item{i}": it for i, it in enumerate(items)}}})
        idents.append({"participantId": pid, "player": {"gameName": pl["riotIdGameName"], "puuid": "demo" if alias == "Jinx" else f"p{pid}"}})
    return {"gameId": 777, "gameDuration": END, "queueId": 420, "mapId": 11, "participants": parts,
            "participantIdentities": idents,
            "teams": [{"teamId": 100, "win": "Win", "dragonKills": 2, "baronKills": 0, "riftHeraldKills": 1, "towerKills": 8, "inhibitorKills": 1, "hordeKills": 0},
                      {"teamId": 200, "win": "Fail", "dragonKills": 1, "baronKills": 1, "riftHeraldKills": 0, "towerKills": 4, "inhibitorKills": 1, "hordeKills": 3}]}


def mock_timeline():
    names = [a for a, _ in ALLIES] + ENEMIES
    gold_rate = {"Jinx": 395, "Kaisa": 430, "Thresh": 250, "Soraka": 245}
    frames = []
    for m in range(0, END // 60 + 1):
        pf = {}
        for pid, alias in enumerate(names, start=1):
            pf[str(pid)] = {"participantId": pid, "totalGold": 500 + gold_rate.get(alias, 380) * m,
                            "minionsKilled": int(CS_RATE.get(alias, 6) * m), "jungleMinionsKilled": 0,
                            "level": min(18, 1 + int(m / 1.8))}
        events = []
        if m == 11:
            events.append({"type": "ITEM_PURCHASED", "participantId": 4, "itemId": 6672, "timestamp": 11 * 60000 + 20000})
        frames.append({"timestamp": m * 60000, "participantFrames": pf, "events": events})
    return {"frames": frames}


class MockLiveClient:
    """Partida que avanza rápido (1 segundo real = 20 segundos de juego) y los rivales van comprando."""

    TIMELINE = {  # minuto -> ítems
        "Mordekaiser": [(0, [1056]), (9, [4633]), (16, [3111]), (22, [6653]), (28, [3065])],
        "Evelynn": [(0, []), (8, [3100]), (14, [3020]), (20, [4645]), (27, [3089])],
        "Vladimir": [(0, [1056]), (10, [6655]), (15, [3020]), (21, [3089]), (27, [3157])],
        "Kaisa": [(0, [1055]), (10, [6672]), (15, [3006]), (21, [3115]), (28, [3124])],
        "Soraka": [(0, [3865]), (11, [6617]), (16, [3158]), (24, [3107])],
        "Garen": [(0, [1055]), (12, [6675]), (18, [3047])],
        "LeeSin": [(0, []), (11, [6675])],
        "Ahri": [(0, [1056]), (11, [6655]), (17, [3020])],
        "Jinx": [(0, [1055]), (4, [1001]), (11, [6672]), (15, [3006]), (19, [3031]), (26, [3094]), (31, [3036])],
        "Thresh": [(0, [3865]), (16, [3190])],
    }

    def __init__(self, dd):
        self.dd = dd

    def game(self):
        if game_over():
            return None
        return self._snapshot(game_time())

    def _snapshot(self, t):
        minute = t / 60

        def player(alias, team, pos):
            cid = self.dd.champ_by_alias[alias.lower()]
            items = []
            for m, its in self.TIMELINE.get(alias, []):
                if minute >= m:
                    items = [i for i in items if i not in (1055, 1056, 1001) or not its] + its
            dk, dd_, da = KDA_MOD.get(alias, (0, 0, 0))
            f = minute / 32
            k = int(minute / 6) + (2 if alias in ("Evelynn", "Kaisa") else 0) + int(dk * f)
            deaths = sum(1 for d in MY_DEATHS if d <= t) if alias == "Jinx" else max(int(minute / 8) + int(dd_ * f), 0)
            return {"championName": self.dd.champ_name(cid), "rawChampionName": f"game_character_displayname_{alias}",
                    "team": team, "position": pos, "level": min(18, 1 + int(minute / 1.8)), "isDead": False,
                    "riotId": "Vos#LAS" if alias == "Jinx" else f"Jugador{alias}#LAS",
                    "riotIdGameName": "Vos" if alias == "Jinx" else f"Jugador{alias}",
                    "scores": {"kills": k, "deaths": deaths, "assists": max(int(minute / 5) + int(da * f), 0), "creepScore": int(minute * CS_RATE.get(alias, 6)),
                               "wardScore": round(minute * (2.1 if alias in ("Thresh", "Soraka") else 0.6), 1)},
                    "items": [{"itemID": i, "count": 1} for i in items]}

        allies = [player(a, "ORDER", p.upper().replace("MIDDLE", "MIDDLE")) for a, p in ALLIES]
        enemies = [player(a, "CHAOS", p) for a, p in zip(ENEMIES, ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"])]
        # muertes que van rotando (se ven en el marcador con su tiempo de reaparición)
        cycle = int(t // 40) % 5
        for i, pl in enumerate(enemies):
            if i in (cycle, (cycle + 2) % 5) and int(t // 20) % 2 == 0:
                pl["isDead"], pl["respawnTimer"] = True, 12 + 2 * i
        # objetivos: mismos avisos que muestra el juego
        timeline = [(305, "DragonKill", "JugadorLeeSin", "Fire"), (492, "HordeKill", "JugadorEvelynn", None),
                    (620, "DragonKill", "JugadorEvelynn", "Water"), (910, "HeraldKill", "JugadorLeeSin", None),
                    (930, "DragonKill", "JugadorLeeSin", "Chemtech"), (1250, "BaronKill", "JugadorEvelynn", None),
                    (1300, "InhibKilled", "JugadorKaisa", None)]
        turrets = [(700, "Turret_T2_R_03_A"), (820, "Turret_T1_L_03_A"), (1010, "Turret_T2_R_02_A"), (1150, "Turret_T2_C_03_A")]
        evs = [{"EventName": n, "EventTime": et, "KillerName": k, **({"DragonType": dt} if dt else {})}
               for et, n, k, dt in timeline if et <= t]
        evs += [{"EventName": "ChampionKill", "EventTime": d, "VictimName": "Vos", "KillerName": "JugadorKaisa"}
                for d in MY_DEATHS if d <= t]
        if t >= END:
            evs.append({"EventName": "GameEnd", "EventTime": END, "Result": "Win"})
        evs += [{"EventName": "TurretKilled", "EventTime": et, "TurretKilled": tn, "KillerName": "JugadorJinx"}
                for et, tn in turrets if et <= t]
        lvl = min(18, 1 + int(minute / 1.8))
        return {"activePlayer": {"riotId": "Vos#LAS", "currentGold": int(t * 1.7) % 3600,
                                 "championStats": {"armor": 26 + 4.2 * lvl, "magicResist": 30 + 1.3 * lvl,
                                                   "attackDamage": 59 + 3 * lvl, "abilityPower": 0}},
                "allPlayers": allies + enemies, "gameData": {"gameTime": t}, "events": {"Events": evs}}
