"""La lógica del asistente en vivo: qué pickear en la selección y qué ítems considerar en partida.

Reglas de Riot para apps de terceros que respetamos acá:
- Solo se usa información visible en el cliente (picks, bans, marcador de Tab) + estadísticas generales.
- No se identifica a los rivales ni se mira su historial.
- Se muestran varias opciones con sus motivos; la decisión es siempre del jugador.
"""
from collections import defaultdict
from itertools import permutations

from ..analyze import adj_wr
from .duos import partner_picks, synergy as duo_synergy

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


# ---------------------------------------------------------------- cómo viene el equipo rival en el draft
def enemy_shape(dd, enemy_cids):
    """Qué tiene enfrente el equipo rival, con lo poco que se sabe en la selección: los campeones."""
    shape = {"tanks": [], "cc": [], "burst": [], "heal": [], "ranged": 0, "ap": 0.0, "n": 0}
    for cid in enemy_cids:
        ch = dd.champions.get(cid, {})
        tags, alias, kit = ch.get("tags", []), ch.get("alias", ""), ch.get("kit", {})
        name = ch.get("name", "?")
        shape["n"] += 1
        shape["ap"] += _ap_ratio(dd, cid)
        if "Tank" in tags:
            shape["tanks"].append(name)
        if alias in HARD_CC or kit.get("cc", 0) >= 2:
            shape["cc"].append(name)
        if "Assassin" in tags or ("Mage" in tags and _ap_ratio(dd, cid) > 0.6):
            shape["burst"].append(name)
        if alias in HEALERS or kit.get("heal"):
            shape["heal"].append(name)
        if ch.get("ranged"):
            shape["ranged"] += 1
    shape["apShare"] = shape["ap"] / shape["n"] if shape["n"] else 0.5
    return shape


def team_fit(dd, cid, shape, my_team_cids):
    """Cuánto le sirve este campeón a ESTA partida, mirando lo que ya pickeó el rival (y tu equipo).

    En puntos de winrate (0.01 = 1%), para que se pueda sumar al winrate del meta.
    """
    if not shape["n"]:
        return 0.0, []
    ch = dd.champions.get(cid, {})
    tags, kit = ch.get("tags", []), ch.get("kit", {})
    tanky = "Tank" in tags or "Fighter" in tags
    escapes = kit.get("dash") or kit.get("invis") or kit.get("untargetable")
    pts, why = 0.0, []
    if len(shape["tanks"]) >= 2 and (kit.get("maxhp") or kit.get("true")):
        pts += 0.012
        why.append(f"le pega bien a los tanques del rival ({', '.join(shape['tanks'])})")
    elif len(shape["tanks"]) >= 2 and "Assassin" in tags:
        pts -= 0.010
        why.append(f"cuesta matar tanques ({', '.join(shape['tanks'])}) con un asesino")
    if len(shape["cc"]) >= 3:
        if tanky or escapes:
            pts += 0.007
            why.append(f"aguanta el control del rival ({len(shape['cc'])} campeones con control)")
        elif ch.get("ranged"):
            pts -= 0.010
            why.append(f"el rival tiene mucho control ({len(shape['cc'])} campeones) y no tenés escape")
    if len(shape["burst"]) >= 2:
        if tanky:
            pts += 0.008
            why.append(f"resiste el burst de {', '.join(shape['burst'][:2])}")
        elif not escapes and ch.get("ranged"):
            pts -= 0.008
            why.append(f"te revientan rápido {', '.join(shape['burst'][:2])}")
    if len(shape["heal"]) >= 2 and not ch.get("ranged"):
        why.append("el rival cura mucho: acordate de un ítem de Heridas Graves")
    # lo que le falta a tu equipo
    mine = [c for c in my_team_cids if c]
    if len(mine) >= 2:
        if not any("Tank" in dd.champions.get(c, {}).get("tags", []) for c in mine) and "Tank" in tags:
            pts += 0.008
            why.append("tu equipo todavía no tiene un tanque")
        ap_mine = [_ap_ratio(dd, c) for c in mine]
        if len(ap_mine) >= 2 and sum(ap_mine) / len(ap_mine) < 0.35 and _ap_ratio(dd, cid) > 0.6:
            pts += 0.008
            why.append("tu equipo necesita daño mágico")
    return pts, why


# ---------------------------------------------------------------- fase de baneos
def _ban_phase(session):
    """Todavía se están baneando (hay baneos sin completar)."""
    for group in session.get("actions", []):
        for a in group:
            if a.get("type") == "ban" and not a.get("completed"):
                return True
    return False


def my_action(session, local):
    """La acción que te toca a vos ahora mismo (banear o pickear), si es tu turno."""
    for group in session.get("actions", []):
        for a in group:
            if a.get("actorCellId") == local and a.get("isInProgress") and not a.get("completed"):
                return {"id": a.get("id"), "type": a.get("type"), "championId": a.get("championId") or 0}
    return None


def my_pending_pick(session, local):
    """Tu pick que todavía no llegó: sirve para pre-pickear (marcar la intención) antes de tu turno."""
    for group in session.get("actions", []):
        for a in group:
            if a.get("actorCellId") == local and a.get("type") == "pick" and not a.get("completed"):
                return {"id": a.get("id"), "type": "pick", "championId": a.get("championId") or 0}
    return None


def ban_options(meta, my_role, pool, unavailable, dd, limit=4):
    """Qué conviene banear: lo que está fuerte en tu línea y lo que le gana a tus campeones.

    Se mira el rol que vas a jugar, porque el baneo que más te cambia la partida es el del
    campeón que te toca enfrente.
    """
    # tus campeones: los que más jugás, con cuánto peso tiene cada uno en tu pool
    mios = sorted(((cid, g, w) for cid, (g, w) in pool.items() if g >= 3), key=lambda x: -x[1])[:4]
    total_mias = sum(g for _, g, _ in mios) or 1
    # nunca proponer banear un campeón que jugás vos: te quedarías sin él
    propios = {cid for cid, _, _ in mios}
    rivales = [c for c in meta.get(my_role, []) if c["id"] not in unavailable and c["id"] not in propios]
    if not rivales:
        return []

    opciones = []
    for c in rivales:
        conf = min(c["games"] / 60, 1.0)
        fuerza = (c["adj"] - 0.5) * conf            # qué tan fuerte está en el parche
        pick = min(c.get("pick", 0) / 0.06, 1.0)    # y qué tan seguido te lo vas a cruzar
        peligro = fuerza * 4 + pick * 0.012
        why, contra = [], []
        for cid, g, w in mios:
            m = c["vs_all"].get(str(cid))
            if not m:
                continue
            mg, mw = m
            if mg >= 6 and mw >= 0.55:
                peso = g / total_mias
                peligro += (mw - 0.5) * 1.6 * peso * min(mg / 20, 1.0)
                contra.append((mw, mg, cid))
        if fuerza > 0:
            why.append(f"Está fuerte en {ROLE_ES.get(my_role, my_role)}: {c['wr']*100:.1f}% en {c['games']} partidas"
                       + ("" if conf >= 1 else " (pocas todavía)"))
        if pick >= 0.5:
            why.append(f"Lo vas a cruzar seguido: lo juega el {c.get('pick', 0)*100:.1f}% de las partidas de tu rango.")
        contra.sort(reverse=True)
        for mw, mg, cid in contra[:2]:
            why.append(f"Le gana a tu {dd.champ_name(cid)}: {mw*100:.0f}% en {mg} partidas"
                       + (" (pocas)" if mg < 15 else ""))
        if c.get("ban", 0) >= 0.05:
            why.append(f"En tu rango ya lo banea el {c['ban']*100:.0f}% de las partidas.")
        if why:
            opciones.append({**_champ_card(dd, c["id"]), "tier": c["tier"], "danger": peligro, "why": why,
                             "counters": bool(contra)})
    opciones.sort(key=lambda o: -o["danger"])
    # que al menos uno de los primeros sea "te contra a vos" si existe
    contras = [o for o in opciones if o["counters"]]
    elegidas = opciones[:limit]
    if contras and not any(o["counters"] for o in elegidas):
        elegidas = elegidas[:limit - 1] + [contras[0]]
    for o in elegidas:
        o.pop("danger", None)
    return elegidas


# ---------------------------------------------------------------- selección de campeones
def draft_advice(session: dict, meta: dict, duos: list, dist, dd, default_role="BOTTOM", pool=None, champs=None) -> dict:
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
    partner = next((a for a in allies if a["role"] == BOT_PARTNER.get(my_role) and a["cid"]), None)
    ally_partner = partner["cid"] if partner else None

    duo_idx = {(d["adc"], d["sup"]): d for d in duos}
    shape = enemy_shape(dd, enemies)
    my_cids = [a["cid"] for a in allies if a["cid"]]

    def evaluate(c):
        # 1) el meta del parche, pero creyéndole menos a los campeones con pocas partidas
        conf = min(c["games"] / 60, 1.0)
        score = 0.5 + (c["adj"] - 0.5) * conf
        score += 0.012 * min(c.get("pick", 0) / 0.05, 1.0)  # lo que de verdad se juega en tu rango
        why = [f"Meta: {c['wr']*100:.1f}% en {c['games']} partidas" + ("" if conf >= 1 else " (pocas partidas todavía)")]
        # 2) contra el campeón que te tocó en tu línea
        if lane_opp and str(lane_opp) in c["vs_all"]:
            g, w = c["vs_all"][str(lane_opp)]
            # con 6 partidas de un cruce no se puede decir "le gana": el dato pesa según cuántas hay
            a = adj_wr(w * g, g, 20)
            score += (a - 0.5) * 1.2 * min(g / 25, 1.0)
            why.append(f"vs {dd.champ_name(lane_opp)}: {w*100:.0f}% en {g} partida{'s' if g != 1 else ''}"
                       + (" (pocas)" if g < 15 else ""))
        # 3) contra el resto de lo que ya pickeó el rival
        fit, fit_why = team_fit(dd, c["id"], shape, my_cids)
        score += fit
        why += fit_why
        # 4) con tu compañero de línea (el que ya bloqueó o el que tiene marcado)
        if ally_partner:
            adc, sup = (c["id"], ally_partner) if my_role == "BOTTOM" else (ally_partner, c["id"])
            s_duo, why_duo, _ = duo_synergy(dd, adc, sup, duo_idx)
            score += s_duo
            why += [f"Con {dd.champ_name(ally_partner)}: {w[len('Juntos: '):]}" if w.startswith("Juntos: ") else w
                    for w in why_duo]
        # 5) tus campeones: los que jugás seguido y te salen bien
        mine = pool.get(c["id"], [0, 0])
        if mine[0] >= 3:
            g, w = mine
            score += 0.02 * min(g, 8) / 8 + (w / g - 0.5) * 0.03
            why.append(f"lo jugaste {g} veces ({w / g * 100:.0f}% de victorias)")
        return score, why, bool(fit_why), mine[0] >= 3

    options = []
    for c in meta.get(my_role, []):
        if c["id"] in unavailable:
            continue
        score, why, counters, mine = evaluate(c)
        options.append({**_champ_card(dd, c["id"]), "tier": c["tier"], "score": score, "why": why,
                        "games": c["games"], "thin": c["games"] < 40, "counters": counters, "mine": mine,
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

    if lane_opp:
        situation = (f"Enfrente tenés a {dd.champ_name(lane_opp)}: primero miro a quién le va bien contra ese campeón, "
                     "después cómo le va contra el resto del equipo rival y qué anda en el parche.")
    elif enemies:
        situation = (f"El rival ya pickeó {len(enemies)} campeón{'es' if len(enemies) > 1 else ''}: te muestro lo que "
                     "mejor funciona contra lo que armaron, más lo que anda en el parche.")
    else:
        situation = ("Todavía no pickeó nadie del rival, así que te muestro lo mejor del parche en tu rango "
                     "y los campeones que más jugás.")
    my_champs = [{**_champ_card(dd, cid), "games": g, "wr": w / g}
                 for cid, (g, w) in sorted(pool.items(), key=lambda kv: -kv[1][0])[:5]
                 if cid not in unavailable and g >= 3]

    # ¿te toca a vos ahora? ¿banear o pickear?
    accion = my_action(session, local)
    paso = accion["type"] if accion else ("ban" if _ban_phase(session) else "pick")
    # pre-pick: todavía no es tu turno pero ya podés marcar a quién querés (tus aliados lo ven)
    prepick = None if accion or me.get("championId") else my_pending_pick(session, local)

    duo_list = []
    if ally_partner and my_role in BOT_PARTNER:
        duo_list = partner_picks(dd, my_role, ally_partner, meta.get(my_role, []), duo_idx, unavailable)
        for o in duo_list:
            o["counters"] = any(x["id"] == o["id"] and x["counters"] for x in options)
    bans_sug = ban_options(meta, my_role, pool, unavailable, dd) if paso == "ban" else []

    # Runas y hechizos: para el campeón que ya elegiste, o para la primera opción mientras no elijas
    from . import runes as ru
    rune_cid = my_champ or (options[0]["id"] if options else 0)
    rune_meta = next((c for c in meta.get(my_role, []) if c["id"] == rune_cid), None) or (champs or {}).get(rune_cid)
    rune_opts = ru.options(dd, rune_cid, my_role, shape, rune_meta, lane_opp) if rune_cid else []
    spell_info = ru.spells(my_role, shape, dd, rune_cid) if rune_cid else None
    if spell_info:
        spell_info["par"] = [{"id": i, "name": ru.SPELL_ES.get(i, dd.spell_name(i)), "img": dd.spell_img(i)}
                             for i in spell_info["par"]]
        for alt in spell_info["alts"]:
            alt["img"] = dd.spell_img(alt["id"])

    return {
        "phase": "draft",
        "myRole": my_role, "myRoleEs": ROLE_ES.get(my_role, my_role),
        "situation": situation, "myChamps": my_champs,
        "step": paso, "myTurn": bool(accion), "actionId": (accion or {}).get("id"),
        "canPrepick": bool(prepick), "partnerPicks": duo_list,
        "partnerLocked": bool(partner and partner["locked"]),
        "hovering": (accion or {}).get("championId") or 0,
        "banOptions": bans_sug,
        "runes": rune_opts, "spells": spell_info,
        "runeChamp": _champ_card(dd, rune_cid) if rune_cid else None,
        "runeChampLocked": bool(my_champ),
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


PANTS_TIPS = {
    "TOP": "Presioná un carril lateral: si te mandan dos, tu equipo hace el objetivo del otro lado.",
    "JUNGLE": "Armá vos las peleas: invadí la jungla rival y hacé los objetivos con tu equipo.",
    "MIDDLE": "Limpiá rápido tu línea y aparecé en todos lados: con esta ventaja las rotaciones las ganás vos.",
    "BOTTOM": "No pelees solo, pero tampoco esperes: con esta ventaja peleás para adelante con tu support al lado.",
    "UTILITY": "Sos el que más ventaja tiene: enganchá vos las peleas y no esperes a que las empiece otro.",
}


def pants(me, allies, enemies, lane_cmp, team_kills, t, role):
    """El clásico «ponete el pantalón»: cuando estás claramente por encima del resto de la partida."""
    if t < 8 * 60:
        return None
    pts, why = 0, []
    kd = me["k"] - me["d"]
    if kd >= 5:
        pts += 1
        why.append(f"vas {me['k']}/{me['d']}/{me['a']}")
    if me["d"] <= 1 and t >= 15 * 60:
        pts += 1
        why.append("casi no moriste" if me["d"] else "todavía no moriste")
    avg_enemy = sum(p["gold"] for p in enemies) / max(len(enemies), 1)
    if me["gold"] - avg_enemy >= 2500:
        pts += 1
        why.append(f"tenés {int((me['gold'] - avg_enemy) / 100) * 100} de oro en ítems más que el rival promedio")
    if me["gold"] >= max(p["gold"] for p in allies + enemies):
        pts += 1
        why.append("sos el que más ítems tiene de los 10")
    kp = (me["k"] + me["a"]) / max(team_kills[0], 1)
    if kp >= 0.6 and team_kills[0] >= 8:
        pts += 1
        why.append(f"estuviste en el {kp*100:.0f}% de las kills de tu equipo")
    if lane_cmp and lane_cmp["gold"] >= 2000:
        pts += 1
        why.append("le sacaste la línea a tu rival")
    if pts < 3:
        return None
    return {"level": 2 if pts >= 5 else 1,
            "title": "Ponete el pantalón largo" if pts >= 5 else "Ponete el pantalón",
            "why": why[:3], "tip": PANTS_TIPS.get(role, "Hacete cargo de la partida: llevala vos.")}


def game_advice(game: dict, meta: dict, dist, dd, remembered_role=None, tracker=None, champs=None) -> dict:
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
    if not champ_meta:  # sin partidas suficientes en tu rol, valen las de ese campeón en cualquier rol
        champ_meta = (champs or {}).get(me["cid"])
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
    team_kills = [sum(p["k"] for p in allies), sum(p["k"] for p in enemies)]

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
        "teamKills": team_kills,
        "pants": pants(me, allies, enemies, lane_cmp, team_kills, t, my_role),
        "noMeta": not champ_meta,
    }
