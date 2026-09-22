"""La lógica del asistente en vivo: qué pickear en la selección y qué ítems considerar en partida.

Reglas de Riot para apps de terceros que respetamos acá:
- Solo se usa información visible en el cliente (picks, bans, marcador de Tab) + estadísticas generales.
- No se identifica a los rivales ni se mira su historial.
- Se muestran varias opciones con sus motivos; la decisión es siempre del jugador.
"""
from collections import defaultdict
from itertools import permutations

from ..analyze import adj_wr

POSITIONS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
LCU_POS = {"top": "TOP", "jungle": "JUNGLE", "middle": "MIDDLE", "mid": "MIDDLE",
           "bottom": "BOTTOM", "utility": "UTILITY", "support": "UTILITY"}
BOT_PARTNER = {"BOTTOM": "UTILITY", "UTILITY": "BOTTOM"}
ROLE_ES = {"TOP": "Top", "JUNGLE": "Jungla", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}

# Campeones con mucha curación propia o para su equipo (alias de Data Dragon)
HEALERS = {"Soraka", "Yuumi", "Sona", "Nami", "Milio", "Seraphine", "Aatrox", "Vladimir", "Sylas",
           "DrMundo", "Warwick", "Swain", "Fiddlesticks", "Briar", "Illaoi", "Olaf", "Maokai",
           "Samira", "Belveth", "Volibear", "Trundle", "Zac", "Kayn", "Nasus", "Aphelios",
           "Senna", "Renekton", "Darius", "Gwen", "Irelia", "Viego", "Vayne"}
# Mucho control de masas (stuns, knock-ups, root, supresiones)
HARD_CC = {"Leona", "Nautilus", "Thresh", "Blitzcrank", "Morgana", "Lux", "Rell", "Alistar",
           "Rakan", "Pyke", "Maokai", "Amumu", "Sejuani", "Ashe", "Malphite", "Skarner", "Zac",
           "Annie", "Veigar", "Lissandra", "Braum", "Taric", "Neeko", "Warwick", "Vi", "Jax",
           "Poppy", "Sett", "Ornn", "Galio", "Twisted Fate", "Xerath", "Zyra", "Bard", "Swain"}


# ---------------------------------------------------------------- utilidades
def role_distribution(conn) -> dict:
    dist = defaultdict(lambda: defaultdict(int))
    for cid, pos, n in conn.execute(
        "SELECT champion_id, position, COUNT(*) FROM participants GROUP BY champion_id, position"
    ):
        if pos in POSITIONS:
            dist[cid][pos] = n
    return dist


def _role_prob(cid, role, dist, dd):
    counts = dist.get(cid, {})
    total = sum(counts.values())
    tags = dd.champions.get(cid, {}).get("tags", [])
    prior = {p: 1.0 for p in POSITIONS}  # sin datos: pista por el tipo de campeón
    if "Marksman" in tags: prior["BOTTOM"] += 6
    if "Support" in tags: prior["UTILITY"] += 5
    if "Mage" in tags: prior["MIDDLE"] += 3
    if "Assassin" in tags: prior["MIDDLE"] += 2; prior["JUNGLE"] += 1
    if "Fighter" in tags or "Tank" in tags: prior["TOP"] += 2; prior["JUNGLE"] += 2
    ps = sum(prior.values())
    return (counts.get(role, 0) + 3 * prior[role] / ps) / (total + 3)


def guess_roles(champ_ids, dist, dd, taken=()) -> dict:
    """Asigna a cada campeón rival el rol más probable (sin repetir roles)."""
    champ_ids = [c for c in champ_ids if c][:5]
    if not champ_ids:
        return {}
    free = [p for p in POSITIONS if p not in taken] if len(champ_ids) <= 5 - len(taken) else POSITIONS
    best, best_p = {}, -1.0
    for perm in permutations(free, len(champ_ids)):
        p = 1.0
        for cid, role in zip(champ_ids, perm):
            p *= _role_prob(cid, role, dist, dd)
        if p > best_p:
            best_p, best = p, dict(zip(champ_ids, perm))
    return best


def _champ_card(dd, cid):
    return {"id": cid, "name": dd.champ_name(cid), "img": dd.champ_img(cid)}


def _item_card(dd, iid):
    return {"id": iid, "name": dd.item_name(iid), "img": dd.item_img(iid), "gold": dd.items.get(iid, {}).get("gold", 0)}


def _ap_ratio(dd, cid):
    info = dd.champions.get(cid, {}).get("info", {})
    a, m = info.get("attack", 5), info.get("magic", 5)
    return m / (a + m) if a + m else 0.5


# ---------------------------------------------------------------- selección de campeones
def draft_advice(session: dict, meta: dict, duos: list, dist, dd, default_role="BOTTOM", pool=None) -> dict:
    pool = pool or {}
    local = session.get("localPlayerCellId")
    my_team = session.get("myTeam", [])
    their_team = session.get("theirTeam", [])
    me = next((p for p in my_team if p.get("cellId") == local), {})
    my_role = LCU_POS.get((me.get("assignedPosition") or "").lower(), default_role)
    my_champ = me.get("championId") or me.get("championPickIntent") or 0

    bans = set()
    for group in session.get("actions", []):
        for a in group:
            if a.get("type") == "ban" and a.get("completed") and a.get("championId"):
                bans.add(a["championId"])
    for key in ("myTeamBans", "theirTeamBans"):
        bans.update(c for c in session.get("bans", {}).get(key, []) if c)

    allies = []
    for p in my_team:
        if p.get("cellId") == local:
            continue
        cid = p.get("championId") or p.get("championPickIntent") or 0
        allies.append({"cid": cid, "locked": bool(p.get("championId")),
                       "role": LCU_POS.get((p.get("assignedPosition") or "").lower())})
    enemies = [p["championId"] for p in their_team if p.get("championId")]
    unavailable = bans | set(enemies) | {a["cid"] for a in allies if a["locked"]}

    enemy_roles = guess_roles(enemies, dist, dd)
    lane_opp = next((c for c, r in enemy_roles.items() if r == my_role), None)
    enemy_partner = next((c for c, r in enemy_roles.items() if r == BOT_PARTNER.get(my_role)), None)
    ally_partner = next((a["cid"] for a in allies if a["role"] == BOT_PARTNER.get(my_role) and a["cid"]), None)

    duo_idx = {(d["adc"], d["sup"]): d for d in duos}
    ally_ap = [_ap_ratio(dd, a["cid"]) for a in allies if a["cid"]]
    team_ap = sum(ally_ap) / len(ally_ap) if ally_ap else 0.5

    def evaluate(c):
        score, why = c["adj"], [f"Meta: {c['wr']*100:.1f}% en {c['games']} partidas"]
        if lane_opp and str(lane_opp) in c["vs_all"]:
            g, w = c["vs_all"][str(lane_opp)]
            a = adj_wr(w * g, g, 10)
            score += (a - 0.5) * 1.2
            why.append(f"vs {dd.champ_name(lane_opp)}: {w*100:.0f}% ({g} p.)")
        if ally_partner:
            key = (c["id"], ally_partner) if my_role == "BOTTOM" else (ally_partner, c["id"])
            d = duo_idx.get(key)
            if d:
                score += (d["adj"] - 0.5) * 0.8
                why.append(f"con {dd.champ_name(ally_partner)}: {d['wr']*100:.0f}% ({d['games']} p.)")
        if pool.get(c["id"], [0])[0] >= 3:
            g, w = pool[c["id"]]
            score += 0.012 * min(g, 10) / 10 + (w / g - 0.5) * 0.02
            why.append(f"Lo jugaste {g} veces ({w / g * 100:.0f}% de victorias)")
        if len(ally_ap) >= 3 and team_ap < 0.35 and _ap_ratio(dd, c["id"]) > 0.6:
            score += 0.01
            why.append("tu equipo necesita daño mágico")
        return score, why

    options = []
    for c in meta.get(my_role, []):
        if c["id"] in unavailable:
            continue
        score, why = evaluate(c)
        options.append({**_champ_card(dd, c["id"]), "tier": c["tier"], "score": score, "why": why,
                        "build": [_item_card(dd, i["id"]) for i in c["items"][:3]],
                        "boots": _item_card(dd, c["boots"][0]["id"]) if c["boots"] else None,
                        "keystone": {"name": dd.rune_name(c["keystones"][0]["id"]),
                                     "img": dd.rune_img(c["keystones"][0]["id"])} if c["keystones"] else None})
    options.sort(key=lambda o: o["score"], reverse=True)

    current = None
    if my_champ:
        current = next((o for o in options if o["id"] == my_champ), None)
        if not current:
            current = {**_champ_card(dd, my_champ), "tier": "?", "why": ["Pocas partidas en el meta de tu rango"],
                       "build": [], "boots": None, "keystone": None}

    return {
        "phase": "draft",
        "myRole": my_role, "myRoleEs": ROLE_ES.get(my_role, my_role),
        "current": current,
        "laneOpponent": _champ_card(dd, lane_opp) if lane_opp else None,
        "enemyPartner": _champ_card(dd, enemy_partner) if enemy_partner else None,
        "allyPartner": _champ_card(dd, ally_partner) if ally_partner else None,
        "enemies": [{**_champ_card(dd, c), "role": ROLE_ES.get(enemy_roles.get(c), "?")} for c in enemies],
        "enemySlots": max(len(their_team), 5),
        "team": [
            {**(_champ_card(dd, p.get("championId") or p.get("championPickIntent"))
                if (p.get("championId") or p.get("championPickIntent")) else {"id": 0, "name": "", "img": ""}),
             "role": ROLE_ES.get(LCU_POS.get((p.get("assignedPosition") or "").lower()), ""),
             "isMe": p.get("cellId") == local, "locked": bool(p.get("championId"))}
            for p in my_team
        ],
        "bans": [_champ_card(dd, b) for b in bans],
        "options": options[:5],
    }


# ---------------------------------------------------------------- partida en curso
def _player(dd, p):
    cid = dd.champ_from_live(p.get("rawChampionName", ""), p.get("championName", ""))
    items = [it["itemID"] for it in p.get("items", []) for _ in range(max(it.get("count", 1), 1))]
    sc = p.get("scores", {})
    return {
        "cid": cid, "team": p.get("team"), "position": (p.get("position") or "").upper(),
        "items": items, "level": p.get("level", 1), "dead": p.get("isDead", False), "respawn": p.get("respawnTimer", 0),
        "k": sc.get("kills", 0), "d": sc.get("deaths", 0), "a": sc.get("assists", 0), "cs": sc.get("creepScore", 0),
        "ids": {p.get("riotId"), p.get("summonerName"), p.get("riotIdGameName")} - {None, ""},
        "gold": sum(dd.items.get(i, {}).get("gold", 0) for i in items),
    }


def game_advice(game: dict, meta: dict, dist, dd, remembered_role=None, tracker=None) -> dict:
    from . import gameplan as gp
    from . import objectives as ob
    act = game.get("activePlayer", {})
    my_ids = {act.get("riotId"), act.get("summonerName"), act.get("riotIdGameName")} - {None, ""}
    players = [_player(dd, p) for p in game.get("allPlayers", [])]
    me = next((p for p in players if p["ids"] & my_ids), players[0] if players else None)
    if not me:
        return {"phase": "game", "error": "No encontré tu campeón en la partida."}
    allies = [p for p in players if p["team"] == me["team"]]
    enemies = [p for p in players if p["team"] != me["team"]]

    my_role = me["position"] if me["position"] in POSITIONS else remembered_role
    if my_role not in POSITIONS:
        my_role = max(POSITIONS, key=lambda r: _role_prob(me["cid"], r, dist, dd))
    if all(p["position"] in POSITIONS for p in enemies):
        enemy_roles = {p["cid"]: p["position"] for p in enemies}
    else:
        enemy_roles = guess_roles([p["cid"] for p in enemies], dist, dd)

    champ_meta = next((c for c in meta.get(my_role, []) if c["id"] == me["cid"]), None)
    prof = gp.champion_profile(dd, me["cid"], champ_meta)
    my_stats = act.get("championStats") or {}
    report = gp.enemy_report(enemies, dd, me, my_stats, prof["_damage"])
    gold_now = int(act.get("currentGold", 0))
    n_items = 6 if my_role == "BOTTOM" else 5  # misión de ADC: las botas pasan a su propio espacio
    build = gp.plan_build(dd, me, prof, champ_meta, report["needs"], gold_now, n_items)
    t = game.get("gameData", {}).get("gameTime", 0)
    events = []
    if tracker:
        tracker.update(t, enemies, report, dd)
        tracker.plan_changed(t, [p["id"] for p in build["plan"]] + ([build["boots"]["id"]] if build["boots"] else []),
                             {p["id"]: p.get("reasons", []) for p in build["plan"]}, dd, set(me["items"]))
        events = tracker.events[-10:][::-1]
    obj = ob.objectives(game, me["team"])
    nxt = build["next"][0] if build["next"] else None
    fight = ob.situation(game, me["team"], dd, obj, (sum(p["gold"] for p in allies), sum(p["gold"] for p in enemies)),
                         me["cid"], max(dd.items.get(nxt["id"], {}).get("gold", 0) - gold_now, 0) if nxt else None,
                         dd.item_name(nxt["id"]) if nxt else None)
    quest = ob.ROLE_QUEST.get(my_role)

    def card(iid, extra=None):
        c = _item_card(dd, iid)
        if extra:
            c.update(extra)
        return c

    next_opts = []
    for n, o in enumerate(build["next"]):
        c = card(o["id"])
        pop = next((x for x in (champ_meta or {}).get("items", []) + (champ_meta or {}).get("boots", []) if x["id"] == o["id"]), None)
        why = list(o.get("reasons", []))
        if pop and pop["share"] >= 0.1:
            why.append(f"lo arma el {pop['share']*100:.0f}% con tu campeón")
        elif not why:
            why.append("encaja con las estadísticas de tu campeón")
        c.update({"why": why, "affordable": gold_now >= c["gold"], "missing": max(c["gold"] - gold_now, 0),
                  "primary": n == 0, "situational": bool(o.get("reasons"))})
        next_opts.append(c)
    shop = build["shopping"]
    if shop:
        shop = {**shop, "buy": [card(i) for i in shop["buy"]]}

    def row(p):
        r = report["rows"].get(p["cid"], {}) if p["team"] != me["team"] else {}
        pos = p["position"] if p["position"] in POSITIONS else enemy_roles.get(p["cid"], "")
        return {**_champ_card(dd, p["cid"]), "level": p["level"], "k": p["k"], "d": p["d"], "a": p["a"],
                "cs": p["cs"], "gold": p["gold"], "dead": p["dead"], "role": ROLE_ES.get(pos, ""),
                "items": [_item_card(dd, i) for i in p["items"] if i not in (3340, 3363, 3364, 2055)],
                "dmg": r.get("dmg"), "armor": r.get("armor"), "mr": r.get("mr"), "flags": r.get("flags", []),
                "respawn": int(p.get("respawn", 0)) if p["dead"] else 0}

    order = {r: i for i, r in enumerate(ROLE_ES.values())}
    by_role = lambda r: order.get(r["role"], 9)  # noqa: E731  mismo orden que el marcador
    enemy_rows = sorted((row(p) for p in enemies), key=by_role)
    if enemy_rows:
        max(enemy_rows, key=lambda r: r["gold"])["threat"] = True
    lane = next((p for p in enemies if enemy_roles.get(p["cid"]) == my_role or p["position"] == my_role), None)
    lane_cmp = None
    if lane:
        lane_cmp = {"gold": me["gold"] - lane["gold"], "level": me["level"] - lane["level"], "cs": me["cs"] - lane["cs"]}

    return {
        "phase": "game",
        "time": int(t),
        "me": {**row(me), "gold_now": gold_now,
               "armor": round(my_stats.get("armor", 0)), "mr": round(my_stats.get("magicResist", 0)),
               "damage": "mágico" if prof["_damage"] == "magic" else "físico"},
        "myRole": my_role, "myRoleEs": ROLE_ES.get(my_role, my_role),
        "laneOpponent": row(lane) if lane else None, "laneCmp": lane_cmp,
        "alerts": report["alerts"],
        "needs": {k: round(v, 2) for k, v in report["needs"].items()},
        "apShare": round(report["ap_share"], 2),
        "plan": [card(p["id"], {"owned": p["owned"], "reasons": p.get("reasons", [])}) for p in build["plan"]],
        "boots": card(build["boots"]["id"], {"owned": build["boots"]["owned"], "reasons": build["boots"].get("reasons", [])})
        if build["boots"] else None,
        "standard": [card(i) for i in build["standard"]],
        "changes": [{"add": card(c["add"]), "remove": card(c["remove"]) if c["remove"] else None, "reasons": c["reasons"]}
                    for c in build["changes"]],
        "options": next_opts,
        "shopping": shop,
        "events": events,
        "objectives": {k: v for k, v in obj.items() if k != "soonest"},
        "fight": fight,
        "quest": quest, "nItems": n_items,
        "enemies": enemy_rows,
        "allies": sorted((row(p) for p in allies), key=by_role),
        "teamGold": [sum(p["gold"] for p in allies), sum(p["gold"] for p in enemies)],
        "teamKills": [sum(p["k"] for p in allies), sum(p["k"] for p in enemies)],
        "noMeta": not meta.get(my_role),
    }
