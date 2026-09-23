"""Resumen al terminar la partida: resultado, estadísticas de los 10 jugadores, nota y devoluciones
según cómo jugaste.

Fuentes (todas locales, sin API key):
- Lo que fue leyendo el asistente durante la partida (Live Client Data API): marcador, eventos, ítems.
- El historial del cliente de LoL (LCU) cuando ya está disponible: daño a campeones, visión, oro
  ganado, guardianes de control y la línea de tiempo (oro y súbditos minuto a minuto).
"""
import json
import time

from .. import config
from .advisor import POSITIONS, ROLE_ES, _champ_card, _item_card, _player

LCU_LANE = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MIDDLE", "MID": "MIDDLE"}
QUEUES = {420: "Clasificatoria Solo/Dúo", 440: "Clasificatoria Flexible", 400: "Normal (reclutamiento)",
          430: "Normal (a ciegas)", 490: "Partida rápida", 450: "ARAM"}
SAVE = config.DATA_DIR / "ultima_partida.json"
HIDDEN_ITEMS = (3340, 3363, 3364, 2055, 2138, 2139, 2140)

# Referencias aproximadas para Platino–Esmeralda (lo que hace un jugador que sube en ese rol)
REF = {
    #           cs/min  kp    daño%  visión/min
    "TOP":     (6.8,   0.45, 0.23,  0.65),
    "JUNGLE":  (5.6,   0.60, 0.17,  1.00),
    "MIDDLE":  (7.2,   0.55, 0.27,  0.75),
    "BOTTOM":  (7.4,   0.55, 0.28,  0.65),
    "UTILITY": (0.0,   0.62, 0.10,  2.00),
}
# Cuánto pesa cada cosa en la nota, según el rol. La visión solo cuenta para el support: a un top
# o a un ADC no se le baja la nota por no poner guardianes, eso es tarea del support.
WEIGHTS = {  # cs, daño, kp, muertes, visión, línea
    "TOP":     (0.24, 0.20, 0.10, 0.20, 0.00, 0.26),
    "JUNGLE":  (0.14, 0.18, 0.32, 0.20, 0.00, 0.16),
    "MIDDLE":  (0.22, 0.24, 0.18, 0.20, 0.00, 0.16),
    "BOTTOM":  (0.24, 0.26, 0.14, 0.20, 0.00, 0.16),
    "UTILITY": (0.00, 0.12, 0.30, 0.20, 0.25, 0.13),
}
VERSION = 3  # sube cuando cambia cómo se evalúa una partida (las guardadas se vuelven a calcular)
GRADES = [(0.90, "S+"), (0.72, "S"), (0.54, "A"), (0.38, "B"), (0.24, "C"), (0.0, "D")]


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def mmss(t):
    t = int(t or 0)
    return f"{t // 60}:{t % 60:02d}"


# ------------------------------------------------------------------ durante la partida
class GameRecorder:
    """Guarda lo necesario de la partida en curso para armar el resumen al final."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.game = None          # última lectura de la Live Client Data API
        self.advice = None        # último estado que mostró el asistente
        self.lane = {}            # minuto -> comparación con tu rival de línea
        self.item_times = {}      # ítem terminado -> segundo de partida en que apareció
        self.needs = {}           # pico de cada necesidad (curación rival, armadura, etc.)
        self.game_id = None
        self._id_t = 0.0
        self.last_t = -1

    def update(self, game, advice, lcu=None):
        t = game.get("gameData", {}).get("gameTime", 0)
        if self.game is not None and t < self.last_t - 30:  # empezó otra partida
            self.reset()
        self.last_t = t
        self.game = game
        if advice.get("error"):
            return
        self.advice = advice
        for m in (10, 15):
            if m not in self.lane and m * 60 <= t < m * 60 + 120 and advice.get("laneCmp"):
                self.lane[m] = dict(advice["laneCmp"])
        for it in advice.get("me", {}).get("items", []):
            self.item_times.setdefault(it["id"], t)
        for k, v in (advice.get("needs") or {}).items():
            self.needs[k] = max(self.needs.get(k, 0), v)
        if lcu is not None and self.game_id is None and time.time() - self._id_t > 20:
            self._id_t = time.time()
            try:
                sess = lcu.get("/lol-gameflow/v1/session") or {}
                self.game_id = (sess.get("gameData") or {}).get("gameId") or None
            except Exception:
                pass


def game_result(game):
    for e in (game or {}).get("events", {}).get("Events", []):
        if e.get("EventName") == "GameEnd":
            return {"Win": True, "Lose": False}.get(e.get("Result"))
    return None


def game_ended(game):
    return any(e.get("EventName") == "GameEnd" for e in (game or {}).get("events", {}).get("Events", []))


# ------------------------------------------------------------------ historial del cliente
def fetch_match(lcu, game_id=None, puuid=None):
    """Detalle de la partida en el historial del cliente (y su línea de tiempo), o (None, None)."""
    if lcu is None:
        return None, None
    raw_get = lcu.get

    class _L:  # mismas llamadas, pero con más tiempo de espera (el cliente las pide a Riot)
        @staticmethod
        def get(path):
            try:
                return raw_get(path, timeout=15)
            except TypeError:
                return raw_get(path)
    lcu = _L
    try:
        if not game_id:
            block = lcu.get("/lol-end-of-game/v1/eog-stats-block") or {}
            game_id = block.get("gameId")
        if not game_id:
            data = lcu.get("/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=5") or {}
            games = ((data.get("games") or {}).get("games")) or []
            games = [g for g in games if g.get("mapId") == 11]
            if games:
                game_id = max(games, key=lambda g: g.get("gameCreation", 0)).get("gameId")
        if not game_id:
            return None, None
        mh = lcu.get(f"/lol-match-history/v1/games/{game_id}")
        if not mh or not mh.get("participants"):
            return None, None
        tl = lcu.get(f"/lol-match-history/v1/game-timelines/{game_id}")
        return mh, (tl if tl and tl.get("frames") else None)
    except Exception:
        return None, None


def _mh_role(p):
    tl = p.get("timeline") or {}
    lane, role = (tl.get("lane") or "").upper(), (tl.get("role") or "").upper()
    if lane in LCU_LANE:
        return LCU_LANE[lane]
    if lane in ("BOTTOM", "BOT"):
        return "UTILITY" if "SUPPORT" in role else "BOTTOM"
    return ""


SUPPORT_ITEMS = set(range(3850, 3878))
SMITE = 11
ROLE_DIST = {}  # championId -> {rol: probabilidad}, lo carga el asistente con las estadísticas del meta


def _role_score(dd, r, pos, mins):
    """Qué tan probable es que este jugador haya jugado en esa posición."""
    sc = 0.0
    smite = SMITE in r.get("spells", ())
    if pos == "JUNGLE":
        sc += 12 if smite else -6
    elif smite:
        sc -= 8
    sup_item = any(i in SUPPORT_ITEMS for i in r["items"])
    cspm = r["cs"] / max(mins, 1)
    if pos == "UTILITY":
        sc += (8 if sup_item else 0) + (3 if cspm < 2.5 else -3)
    elif sup_item:
        sc -= 6
    if r.get("hint") == pos:
        sc += 2
    tags = dd.champions.get(r["cid"], {}).get("tags", [])
    sc += {"BOTTOM": 2.5 * ("Marksman" in tags), "UTILITY": 1.5 * ("Support" in tags),
           "MIDDLE": 1.0 * ("Mage" in tags) + 0.5 * ("Assassin" in tags),
           "TOP": 1.0 * ("Fighter" in tags) + 0.8 * ("Tank" in tags), "JUNGLE": 0}[pos]
    sc += 5 * (ROLE_DIST.get(r["cid"]) or {}).get(pos, 0)
    return sc


def _assign_roles(dd, rows, duration):
    """El historial del cliente a veces marca mal las líneas: elijo la mejor asignación de las 5 posiciones
    por equipo usando Castigo, ítem de support, súbditos, el tipo de campeón y lo que marca el cliente."""
    from itertools import permutations
    mins = max(duration / 60, 1)
    for team in ("mine", "theirs"):
        rs = [r for r in rows if r["side"] == team]
        fixed = {r["pos"] for r in rs if r["pos"] in POSITIONS}
        free_rows = [r for r in rs if r["pos"] not in POSITIONS]
        free_pos = [p for p in POSITIONS if p not in fixed]
        if not free_rows or len(free_rows) > 5:
            continue
        best, best_sc = None, None
        for perm in permutations(free_pos, len(free_rows)):
            sc = sum(_role_score(dd, r, p, mins) for r, p in zip(free_rows, perm))
            if best_sc is None or sc > best_sc:
                best, best_sc = perm, sc
        for r, p in zip(free_rows, best or ()):
            r["pos"] = p


def _fill_roles(rows):
    """Completa roles que faltan (partidas sin rol asignado): el que quede libre en cada equipo."""
    for team in ("mine", "theirs"):
        rs = [r for r in rows if r["side"] == team]
        free = [p for p in POSITIONS if p not in {r["pos"] for r in rs}]
        for r in rs:
            if r["pos"] not in POSITIONS and free:
                r["pos"] = free.pop(0)


# ------------------------------------------------------------------ armado del resumen
def summarize(dd, rec=None, mh=None, timeline=None, puuid=None):
    game = rec.game if rec else None
    adv = rec.advice if rec else None
    live_players = [(_player(dd, p), p) for p in (game or {}).get("allPlayers", [])]
    my_cid = adv["me"]["id"] if adv else None
    my_team_live = next((lp["team"] for lp, _ in live_players if lp["cid"] == my_cid), None)
    live_pos = {lp["cid"]: lp["position"] for lp, _ in live_players}

    rows = []
    if mh:
        ident = {i.get("participantId"): (i.get("player") or {}) for i in mh.get("participantIdentities", [])}
        me_p = None
        for p in mh["participants"]:
            pl = ident.get(p.get("participantId"), {})
            if puuid and pl.get("puuid") == puuid:
                me_p = p
        if me_p is None and my_cid:
            me_p = next((p for p in mh["participants"] if p.get("championId") == my_cid), None)
        if me_p is None:
            me_p = mh["participants"][0]
        for p in mh["participants"]:
            st = p.get("stats") or {}
            pl = ident.get(p.get("participantId"), {})
            items = [st.get(f"item{i}") for i in range(7)]
            items = [i for i in items if i]
            cid = p.get("championId")
            rows.append({
                "pid": p.get("participantId"), "cid": cid,
                "side": "mine" if p.get("teamId") == me_p.get("teamId") else "theirs",
                "isMe": p is me_p, "player": pl.get("gameName") or pl.get("summonerName") or "",
                "pos": live_pos.get(cid) if live_pos.get(cid) in POSITIONS else "",
                "hint": _mh_role(p), "spells": {p.get("spell1Id"), p.get("spell2Id")},
                "level": st.get("champLevel", 0), "k": st.get("kills", 0), "d": st.get("deaths", 0),
                "a": st.get("assists", 0), "cs": st.get("totalMinionsKilled", 0) + st.get("neutralMinionsKilled", 0),
                "gold": st.get("goldEarned", 0), "dmg": st.get("totalDamageDealtToChampions"),
                "taken": st.get("totalDamageTaken"), "vision": st.get("visionScore"),
                "ctrl": st.get("visionWardsBoughtInGame"), "wards": st.get("wardsPlaced"),
                "items": items, "win": st.get("win"),
            })
        duration = mh.get("gameDuration") or (game or {}).get("gameData", {}).get("gameTime", 0)
        if duration > 20000:  # algunas versiones lo dan en milisegundos
            duration /= 1000
        win = next((r["win"] for r in rows if r["isMe"]), None)
        queue = QUEUES.get(mh.get("queueId"), "")
    else:
        if not live_players:
            return None
        for lp, raw in live_players:
            rows.append({
                "pid": None, "cid": lp["cid"], "side": "mine" if lp["team"] == my_team_live else "theirs",
                "isMe": lp["cid"] == my_cid, "player": raw.get("riotIdGameName") or (raw.get("riotId") or "").split("#")[0]
                or raw.get("summonerName", ""),
                "pos": lp["position"], "level": lp["level"], "k": lp["k"], "d": lp["d"], "a": lp["a"], "cs": lp["cs"],
                "gold": lp["gold"], "dmg": None, "taken": None, "vision": (raw.get("scores") or {}).get("wardScore"),
                "ctrl": None, "wards": None, "items": lp["items"], "win": None,
            })
        duration = game.get("gameData", {}).get("gameTime", 0)
        win = game_result(game)
        queue = ""
    if win is None and game:
        win = game_result(game)
    _assign_roles(dd, rows, duration)

    me = next((r for r in rows if r["isMe"]), None)
    if not me:
        return None
    role = (adv or {}).get("myRole") or me["pos"] or (config.ROLES[0] if config.ROLES else "BOTTOM")
    if role not in POSITIONS:
        role = "BOTTOM"
    mins = max(duration / 60, 1)
    mine = [r for r in rows if r["side"] == "mine"]
    theirs = [r for r in rows if r["side"] == "theirs"]
    team_kills = sum(r["k"] for r in mine)
    enemy_kills = sum(r["k"] for r in theirs)
    has_dmg = all(r["dmg"] is not None for r in rows)
    team_dmg = sum(r["dmg"] or 0 for r in mine)
    opp = next((r for r in theirs if r["pos"] == role), None)

    m = {
        "cs": me["cs"], "csMin": me["cs"] / mins,
        "kp": min((me["k"] + me["a"]) / team_kills, 1.0) if team_kills else 0.0,
        "deaths10": me["d"] / (mins / 10),
        "dmg": me["dmg"], "dmgShare": (me["dmg"] / team_dmg) if has_dmg and team_dmg else None,
        "vision": me["vision"], "visionMin": (me["vision"] / mins) if me["vision"] is not None and mh else None,
        "ctrl": me["ctrl"], "gold": me["gold"],
        "kda": (me["k"] + me["a"]) / max(me["d"], 1),
    }

    lane = _lane(rec, timeline, me, opp)
    first_item = _first_item(dd, rec, timeline, me)
    if game:
        deaths_before = _deaths_before_objectives(game, my_team_live)
    else:
        deaths_before = _deaths_before_timeline(timeline, me, rows) if timeline else []
    needs = rec.needs if rec and rec.needs else _needs_final(dd, rows, me)
    objs = _objectives(game, my_team_live, mh, me)

    remake = duration < 300
    score, grade = None, None
    if not remake:
        score = _score(role, m, lane)
        score = _clamp(score + (0.05 if win else 0))
        grade = next(g for th, g in GRADES if score >= th)

    fb = [] if remake else _feedback(dd, role, m, lane, first_item, deaths_before, needs, me, mins, win, opp)

    # Un solo MVP por partida: KDA, participación y daño dentro de su equipo; sale del equipo ganador
    def perf(r, team, won):
        tk = sum(x["k"] for x in team) or 1
        td = sum(x["dmg"] or 0 for x in team) or 1
        base = ((r["k"] + r["a"]) / max(r["d"], 1)) * 0.35 + (r["k"] + r["a"]) / tk + ((r["dmg"] or 0) / td) * 2
        return base * (1.2 if won else 1.0)
    if not remake and rows:
        cands = [(perf(r, mine, win is True), r) for r in mine] + [(perf(r, theirs, win is False), r) for r in theirs]
        if win is not None:  # como en el cliente de LoL: el MVP sale del equipo que ganó
            winners = mine if win else theirs
            cands = [c for c in cands if c[1] in winners]
        max(cands, key=lambda x: x[0])[1]["mvp"] = True

    max_dmg = max((r["dmg"] or 0) for r in rows) or 1
    order = {p: i for i, p in enumerate(POSITIONS)}

    def row_view(r):
        return {**_champ_card(dd, r["cid"]), "player": r["player"], "role": ROLE_ES.get(r["pos"], ""),
                "isMe": r["isMe"], "mvp": r.get("mvp", False), "level": r["level"], "k": r["k"], "d": r["d"], "a": r["a"],
                "cs": r["cs"], "csMin": round(r["cs"] / mins, 1), "gold": r["gold"], "dmg": r["dmg"],
                "dmgPct": round((r["dmg"] or 0) / max_dmg * 100), "vision": r["vision"],
                "items": [_item_card(dd, i) for i in r["items"] if i not in HIDDEN_ITEMS]}

    if win is True:
        result, rtext = "win", "Victoria"
    elif win is False:
        result, rtext = "loss", "Derrota"
    else:
        result, rtext = None, "Partida terminada"
    if remake:
        rtext = "Remake" if duration < 240 else rtext

    return {
        "phase": "postgame", "v": VERSION,
        "gameId": (mh or {}).get("gameId") or (rec.game_id if rec else None),
        "created": (mh or {}).get("gameCreation") or int(time.time() * 1000 - duration * 1000),
        "result": result, "resultText": rtext, "queue": queue, "duration": int(duration), "durationText": mmss(duration),
        "finishedAt": time.strftime("%d/%m %H:%M"),
        "complete": bool(mh), "remake": remake,
        "me": {**row_view(me), "roleEs": ROLE_ES.get(role, role), "role": role,
               "splash": f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{dd.champions.get(me['cid'], {}).get('alias', '')}_0.jpg",
               "kda": round(m["kda"], 2), "kp": round(m["kp"] * 100), "dmgShare": round(m["dmgShare"] * 100) if m["dmgShare"] is not None else None,
               "visionMin": round(m["visionMin"], 2) if m["visionMin"] is not None else None, "ctrl": m["ctrl"],
               "goldMin": round(me["gold"] / mins)},
        "grade": grade, "score": round(score * 100) if score is not None else None,
        "headline": _headline(win, grade, fb),
        "metrics": _metrics(role, m, lane, first_item),
        "feedback": fb,
        "lane": lane and {**lane, "opp": _champ_card(dd, opp["cid"]) if opp else None},
        "teams": {"mine": sorted((row_view(r) for r in mine), key=lambda r: order.get(_pos_of(r), 9)),
                  "theirs": sorted((row_view(r) for r in theirs), key=lambda r: order.get(_pos_of(r), 9))},
        "teamKills": [team_kills, enemy_kills],
        "teamGold": [sum(r["gold"] for r in mine), sum(r["gold"] for r in theirs)],
        "objectives": objs,
    }


def _pos_of(view_row):
    return next((p for p, es in ROLE_ES.items() if es == view_row["role"]), "")


def _lane(rec, timeline, me, opp):
    """Diferencia con tu rival de línea a los 10 y a los 15 minutos."""
    out = {}
    if timeline and me.get("pid") and opp and opp.get("pid"):
        frames = timeline.get("frames") or []
        for minute in (10, 15):
            f = next((fr for fr in frames if abs(fr.get("timestamp", 0) / 60000 - minute) < 0.6), None)
            if not f:
                continue
            pf = f.get("participantFrames") or {}
            a, b = pf.get(str(me["pid"])) or pf.get(me["pid"]), pf.get(str(opp["pid"])) or pf.get(opp["pid"])
            if a and b:
                cs = lambda x: x.get("minionsKilled", 0) + x.get("jungleMinionsKilled", 0)  # noqa: E731
                out[minute] = {"gold": a.get("totalGold", 0) - b.get("totalGold", 0), "cs": cs(a) - cs(b),
                               "level": a.get("level", 0) - b.get("level", 0), "kind": "oro"}
    if not out and rec:
        for minute, v in rec.lane.items():
            out[minute] = {**v, "kind": "oro en ítems"}
    return {"at10": out.get(10), "at15": out.get(15)} if out else None


def _first_item(dd, rec, timeline, me):
    def done(i):
        it = dd.items.get(i, {})
        return it.get("completed") and not it.get("boots")
    if timeline and me.get("pid"):
        for f in timeline.get("frames") or []:
            for e in f.get("events") or []:
                if (e.get("type") == "ITEM_PURCHASED" and e.get("participantId") == me["pid"] and done(e.get("itemId"))):
                    return {"id": e["itemId"], "t": e.get("timestamp", 0) / 1000}
    if rec and rec.item_times:
        cands = [(t, i) for i, t in rec.item_times.items() if done(i) and t > 60]
        if cands:
            t, i = min(cands)
            return {"id": i, "t": t}
    return None


def _names(p):
    return {(p.get(k) or "").split("#")[0].strip().lower() for k in ("riotIdGameName", "riotId", "summonerName")} - {""}


def _deaths_before_objectives(game, my_team):
    """Muertes tuyas en el minuto previo a un objetivo que se llevó el rival."""
    players = game.get("allPlayers", [])
    act = game.get("activePlayer", {})
    mine = {(act.get(k) or "").split("#")[0].strip().lower() for k in ("riotIdGameName", "riotId", "summonerName")} - {""}
    team_of = {}
    for p in players:
        for n in _names(p):
            team_of[n] = p.get("team")
    events = game.get("events", {}).get("Events", [])
    my_deaths = [e.get("EventTime", 0) for e in events
                 if e.get("EventName") == "ChampionKill" and (e.get("VictimName") or "").split("#")[0].strip().lower() in mine]
    names = {"DragonKill": "Dragón", "BaronKill": "Barón", "HeraldKill": "Heraldo", "HordeKill": "Larvas"}
    out = []
    for e in events:
        if e.get("EventName") not in names:
            continue
        killer_team = team_of.get((e.get("KillerName") or "").split("#")[0].strip().lower())
        if not killer_team or killer_team == my_team:
            continue
        et = e.get("EventTime", 0)
        if any(et - 75 <= d <= et for d in my_deaths):
            label = names[e["EventName"]]
            if e.get("DragonType") == "Elder":
                label = "Dragón Anciano"
            out.append(f"{label} ({mmss(et)})")
    return out


def _deaths_before_timeline(timeline, me, rows):
    """Lo mismo que arriba pero con la línea de tiempo del historial (partidas que no viste en vivo)."""
    if not me.get("pid"):
        return []
    side = {r["pid"]: r["side"] for r in rows}
    events = [e for f in timeline.get("frames") or [] for e in f.get("events") or []]
    my_deaths = [e.get("timestamp", 0) / 1000 for e in events if e.get("type") == "CHAMPION_KILL" and e.get("victimId") == me["pid"]]
    names = {"DRAGON": "Dragón", "BARON_NASHOR": "Barón", "RIFTHERALD": "Heraldo", "HORDE": "Larvas"}
    out = []
    for e in events:
        if e.get("type") != "ELITE_MONSTER_KILL" or e.get("monsterType") not in names:
            continue
        if side.get(e.get("killerId")) != "theirs":
            continue
        et = e.get("timestamp", 0) / 1000
        if any(et - 75 <= d <= et for d in my_deaths):
            label = "Dragón Anciano" if e.get("monsterSubType") == "ELDER_DRAGON" else names[e["monsterType"]]
            out.append(f"{label} ({mmss(et)})")
    return out


def _needs_final(dd, rows, me):
    """Qué pedía el equipo rival (curación, armadura, etc.) según cómo terminó armado."""
    from . import gameplan as gp
    try:
        enemies = [{"cid": r["cid"], "items": r["items"], "level": r["level"], "k": r["k"], "d": r["d"],
                    "gold": sum(dd.items.get(i, {}).get("gold", 0) for i in r["items"])}
                   for r in rows if r["side"] == "theirs"]
        dmg = gp.champion_profile(dd, me["cid"], None).get("_damage", "physical")
        return gp.enemy_report(enemies, dd, None, {}, dmg)["needs"]
    except Exception:
        return {}


def _objectives(game, my_team, mh, me):
    res = {"mine": {"drakes": 0, "barons": 0, "heralds": 0, "grubs": 0, "towers": 0, "inhibs": 0},
           "theirs": {"drakes": 0, "barons": 0, "heralds": 0, "grubs": 0, "towers": 0, "inhibs": 0}}
    if game:
        players = game.get("allPlayers", [])
        team_of = {}
        for p in players:
            for n in _names(p):
                team_of[n] = p.get("team")
        key = {"DragonKill": "drakes", "BaronKill": "barons", "HeraldKill": "heralds", "HordeKill": "grubs",
               "TurretKilled": "towers", "InhibKilled": "inhibs"}
        for e in game.get("events", {}).get("Events", []):
            k = key.get(e.get("EventName"))
            if not k:
                continue
            if k in ("towers", "inhibs"):
                # la torre/inhibidor que cayó dice de qué lado era: T1 = azul (ORDER), T2 = rojo (CHAOS)
                name = e.get("TurretKilled") or e.get("InhibKilled") or ""
                owner = "ORDER" if "_T1_" in name else "CHAOS" if "_T2_" in name else None
                team = ("CHAOS" if owner == "ORDER" else "ORDER") if owner else team_of.get((e.get("KillerName") or "").split("#")[0].lower())
            else:
                team = team_of.get((e.get("KillerName") or "").split("#")[0].strip().lower())
            if team:
                res["mine" if team == my_team else "theirs"][k] += 1
    if mh and mh.get("teams"):
        my_tid = next((p.get("teamId") for p in mh["participants"] if p.get("participantId") == me.get("pid")), None)
        for t in mh["teams"]:
            side = "mine" if t.get("teamId") == my_tid else "theirs"
            for k, src in (("drakes", "dragonKills"), ("barons", "baronKills"), ("heralds", "riftHeraldKills"),
                           ("towers", "towerKills"), ("inhibs", "inhibitorKills"), ("grubs", "hordeKills")):
                if t.get(src) is not None:
                    res[side][k] = t[src]
    return res


def _score(role, m, lane):
    """Nota de 0 a 1. La referencia es lo que hace un jugador que sube de rango: llegar a la
    referencia ya es una buena partida (nota A), no el mínimo para aprobar."""
    ref_cs, ref_kp, ref_dmg, ref_vis = REF[role]
    w = WEIGHTS[role]
    parts = []
    if ref_cs and w[0]:
        parts.append((w[0], _clamp((m["csMin"] / ref_cs - 0.55) / 0.75)))
    if m["dmgShare"] is not None and w[1]:
        parts.append((w[1], _clamp((m["dmgShare"] / ref_dmg - 0.5) / 0.8)))
    if w[2]:
        parts.append((w[2], _clamp((m["kp"] / ref_kp - 0.5) / 0.8)))
    if w[3]:
        parts.append((w[3], _clamp((3.8 - m["deaths10"]) / 3.4)))
    if m["visionMin"] is not None and w[4]:  # solo el support
        parts.append((w[4], _clamp((m["visionMin"] / ref_vis - 0.45) / 0.8)))
    at = lane and (lane.get("at15") or lane.get("at10"))
    if at and w[5]:
        parts.append((w[5], _clamp(0.5 + at["gold"] / 2600 + at["cs"] / 70)))
    tot = sum(x for x, _ in parts) or 1
    return sum(x * v for x, v in parts) / tot


def _metrics(role, m, lane, first_item):
    ref_cs, ref_kp, ref_dmg, ref_vis = REF[role]

    def tone(v, ref, higher=True):
        if v is None:
            return ""
        r = v / ref if higher else ref / max(v, 0.01)
        return "good" if r >= 0.95 else "bad" if r < 0.75 else "even"
    out = []
    if ref_cs:
        out.append({"label": "Súbditos por minuto", "value": f"{m['csMin']:.1f}", "ref": f"ref. {ref_cs:.1f}", "tone": tone(m["csMin"], ref_cs)})
    out.append({"label": "Participación en kills", "value": f"{m['kp']*100:.0f}%", "ref": f"ref. {ref_kp*100:.0f}%", "tone": tone(m["kp"], ref_kp)})
    if m["dmgShare"] is not None:
        out.append({"label": "Daño de tu equipo", "value": f"{m['dmgShare']*100:.0f}%", "ref": f"ref. {ref_dmg*100:.0f}%", "tone": tone(m["dmgShare"], ref_dmg)})
    out.append({"label": "Muertes cada 10 min", "value": f"{m['deaths10']:.1f}", "ref": "ref. 2.0", "tone": tone(m["deaths10"], 2.0, higher=False)})
    if m["visionMin"] is not None:
        if role == "UTILITY":
            out.append({"label": "Visión por minuto", "value": f"{m['visionMin']:.2f}", "ref": f"ref. {ref_vis:.2f}",
                        "tone": tone(m["visionMin"], ref_vis)})
        else:  # en el resto de los roles la visión no baja la nota: va solo como dato
            out.append({"label": "Visión por minuto", "value": f"{m['visionMin']:.2f}", "ref": "no cuenta para la nota",
                        "tone": ""})
    at = lane and lane.get("at15") or (lane or {}).get("at10")
    if at:
        minute = 15 if lane.get("at15") else 10
        out.append({"label": f"Contra tu rival a los {minute}", "value": f"{at['gold']:+d}", "ref": at["kind"],
                    "tone": "good" if at["gold"] > 250 else "bad" if at["gold"] < -250 else "even"})
    if first_item:
        out.append({"label": "Primer ítem", "value": mmss(first_item["t"]), "ref": "ref. 12:00",
                    "tone": "good" if first_item["t"] <= 12 * 60 else "bad" if first_item["t"] > 15 * 60 else "even"})
    return out


def _feedback(dd, role, m, lane, first_item, deaths_before, needs, me, mins, win, opp):
    ref_cs, ref_kp, ref_dmg, ref_vis = REF[role]
    good, bad, tips = [], [], []
    add = lambda lst, title, text, w=1.0: lst.append({"title": title, "text": text, "w": w})  # noqa: E731
    role_es = ROLE_ES.get(role, "")

    # Farmeo
    if ref_cs:
        r = m["csMin"] / ref_cs
        if r >= 0.92:
            add(good, "Buen farmeo", f"{m['csMin']:.1f} súbditos por minuto ({m['cs']} en total). En tu rango un {role_es} que sube ronda {ref_cs:.1f}.", r)
        elif r < 0.78:
            lost = int((ref_cs - m["csMin"]) * mins)
            add(bad, "Te faltó farmeo",
                f"{m['csMin']:.1f} súbditos por minuto: unos {lost} menos que la referencia (≈{lost * 20:,} de oro).".replace(",", ".")
                + (" Cuando no hay un objetivo cerca, andá a la línea que tenga más súbditos en vez de caminar con el equipo."
                   if mins > 20 else " En la línea, priorizá asegurar cada súbdito antes que tradear."), 1.4 - r)

    # Muertes
    d10 = m["deaths10"]
    if me["d"] <= 3 and mins >= 15:
        add(good, "Moriste poco", f"Solo {me['d']} muerte{'s' if me['d'] != 1 else ''} en {int(mins)} minutos: tu equipo pudo contar con vos casi siempre.", 1.2)
    elif d10 <= 1.9 and mins >= 15:
        add(good, "Pocas muertes", f"{me['d']} muertes en {int(mins)} minutos (una cada {mins / max(me['d'], 1):.0f} min).", 1.0)
    elif d10 >= 3.2:
        extra = {"BOTTOM": " Como ADC tu daño depende de estar vivo en las peleas: pegá desde atrás y no entres primero sin visión.",
                 "UTILITY": " Si vas a poner visión en zonas peligrosas, hacelo con tu equipo cerca o antes de que el rival llegue.",
                 "MIDDLE": " Antes de ir a un costado mirá dónde está el jungla rival en el mapa."}.get(role, " Revisá el mapa antes de avanzar sin visión.")
        add(bad, "Muchas muertes", f"{me['d']} muertes (una cada {mins / max(me['d'], 1):.1f} min).{extra}", d10 / 2.5)
    if deaths_before:
        add(bad, "Muertes que regalaron objetivos",
            f"Moriste justo antes de que el rival tomara: {', '.join(deaths_before)}. Cuando un objetivo está por aparecer, no te arriesgues solo en otra zona.",
            1.3 + 0.2 * len(deaths_before))

    # Participación
    rk = m["kp"] / ref_kp
    if rk >= 0.95:
        add(good, "Estuviste en las peleas", f"Participaste en el {m['kp']*100:.0f}% de las kills de tu equipo.", rk)
    elif rk < 0.68 and mins > 15:
        add(bad, "Poca participación", f"Estuviste en el {m['kp']*100:.0f}% de las kills de tu equipo (ref. {ref_kp*100:.0f}%). "
            "Cuando tu equipo pelea un objetivo, llegá antes: las peleas de dragón y Barón deciden la partida.", 1.3 - rk)

    # Daño
    if m["dmgShare"] is not None:
        rd = m["dmgShare"] / ref_dmg
        if rd >= 0.98:
            add(good, "Mucho daño", f"Hiciste el {m['dmgShare']*100:.0f}% del daño a campeones de tu equipo ({me['dmg']:,} de daño).".replace(",", "."), rd)
        elif rd < 0.65 and role != "UTILITY":
            add(bad, "Poco daño en las peleas", f"El {m['dmgShare']*100:.0f}% del daño de tu equipo (ref. {ref_dmg*100:.0f}%). "
                + ("Buscá pegarle al que tengas más cerca sin exponerte: un ADC que pega todo el tiempo gana más que uno que busca al carry." if role == "BOTTOM"
                   else "Intentá estar en rango de pegar durante toda la pelea, no solo al principio."), 1.3 - rd)

    # Visión
    if m["visionMin"] is not None:
        rv = m["visionMin"] / ref_vis
        if rv >= 1.1:
            add(good, "Buena visión", f"{m['visionMin']:.2f} de puntaje de visión por minuto.", rv * 0.9)
        elif rv < 0.7:
            add(bad, "Poca visión", f"{m['visionMin']:.2f} de visión por minuto (ref. {ref_vis:.2f}). "
                + ("Como support es tu tarea principal: usá la carga del ítem de support todo el tiempo y cambiá a la Lente de Oráculo."
                   if role == "UTILITY" else "Usá tu centinela cada vez que esté disponible, sobre todo antes de los objetivos."), 1.2 - rv)
    if m["ctrl"] == 0 and mins > 15:
        add(tips, "Ningún Centinela de Control", "No compraste ninguno. Cuesta 75 de oro y alrededor del dragón o del Barón te da la información que gana la pelea: sumá uno en cada vuelta a base.", 1.0)
    elif m["ctrl"] and m["ctrl"] >= 4:
        add(good, "Compraste Centinelas de Control", f"{m['ctrl']} en la partida.", 0.8)

    # Línea
    if lane:
        for minute in (15, 10):
            at = lane.get(f"at{minute}")
            if not at:
                continue
            who = dd.champ_name(opp["cid"]) if opp else "tu rival"
            if at["gold"] >= 400 or at["cs"] >= 12:
                add(good, "Ganaste la línea", f"A los {minute} min le sacabas {at['gold']:+d} de {at['kind']} y {at['cs']:+d} súbditos a {who}.", 1.1)
            elif at["gold"] <= -700 or at["cs"] <= -20:
                add(bad, "Perdiste la línea", f"A los {minute} min ibas {at['gold']:+d} de {at['kind']} y {at['cs']:+d} súbditos contra {who}. "
                    "Si la línea viene difícil, jugá para no perder súbditos bajo tu torre y pedí ayuda a tu jungla.", 1.1)
            break

    # Primer ítem
    if first_item and role != "UTILITY":
        t = first_item["t"]
        name = dd.item_name(first_item["id"])
        if t <= 12.5 * 60:
            add(good, "Primer ítem a tiempo", f"{name} a los {mmss(t)}.", 0.9)
        elif t > 16 * 60:
            add(bad, "Primer ítem tarde", f"{name} recién a los {mmss(t)} (lo ideal es cerca de las 12:00). "
                "Volvé a base cuando te alcance para una parte importante, no con oro de más.", 0.9)

    # Ítems situacionales
    if needs:
        owned = set(me["items"])
        tags = set()
        for i in owned:
            tags |= set(dd.items.get(i, {}).get("tags", ()))
        if needs.get("antiheal", 0) >= 0.5 and mins > 18:
            if "antiheal" in tags:
                add(good, "Cortaste la curación", "El rival se curaba mucho y armaste Heridas Graves: bien leído.", 1.0)
            else:
                add(bad, "Te faltó Heridas Graves", "El rival tenía mucha curación y no armaste un ítem que la corte. "
                    "Aunque sea el componente barato (800 de oro) cambia las peleas largas.", 1.2)
        if needs.get("vs_ad", 0) >= 0.7 and me["d"] >= 6 and not tags & {"vs_ad", "antiburst", "lifeline"} and role != "UTILITY":
            add(tips, "Nada defensivo contra tanto daño físico", "Con un equipo rival casi todo AD, un ítem con armadura o que te salve del burst (ej. Ángel Guardián) te habría dado más peleas vivo.", 0.9)
        if needs.get("vs_ap", 0) >= 0.7 and me["d"] >= 6 and not tags & {"vs_ap", "antiburst", "lifeline"} and role != "UTILITY":
            add(tips, "Nada defensivo contra tanto daño mágico", "Con un equipo rival casi todo AP, un ítem con resistencia mágica o un Fajín de Mercurio te habría dado más peleas vivo.", 0.9)

    good.sort(key=lambda x: -x["w"])
    bad.sort(key=lambda x: -x["w"])
    out = [{"tone": "good", **x} for x in good[:4]] + [{"tone": "bad", **x} for x in bad[:4]] + [{"tone": "tip", **x} for x in tips[:2]]
    for x in out:
        x.pop("w", None)
    return out


def _headline(win, grade, fb):
    goods = [f["title"].lower() for f in fb if f["tone"] == "good"][:2]
    bads = [f["title"].lower() for f in fb if f["tone"] == "bad"][:1]
    if not grade:
        return "La partida fue demasiado corta para evaluarla."
    good_grade = grade in ("S+", "S", "A")
    if win:
        s = f"Victoria con nota {grade}."
    else:
        s = f"Derrota, pero con nota {grade}." if good_grade else f"Derrota con nota {grade}."
    if goods:
        s += " Lo mejor: " + " y ".join(goods) + "."
    if bads:
        s += " Para mejorar: " + bads[0] + "."
    return s


# ------------------------------------------------------------------ guardado
def save(summary):
    try:
        SAVE.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def load_saved():
    try:
        return json.loads(SAVE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
