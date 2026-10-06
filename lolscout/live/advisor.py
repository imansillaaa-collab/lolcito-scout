"""La lógica del asistente en vivo: qué pickear en la selección y qué ítems considerar en partida.

Reglas de Riot para apps de terceros que respetamos acá:
- Solo se usa información visible en el cliente (picks, bans, marcador de Tab) + estadísticas generales.
- No se identifica a los rivales ni se mira su historial.
- Se muestran varias opciones con sus motivos; la decisión es siempre del jugador.
"""
from collections import defaultdict
from itertools import permutations

from ..analyze import adj_wr, tier_of
from .duos import COMBOS as DUO_COMBOS, _alias as _duo_alias, partner_picks, synergy as duo_synergy
from .sinergias import ally_synergy

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
    # lo que le falta a tu equipo se mira aparte (sinergias.team_needs), aunque el rival no haya pickeado
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


def ban_options(meta, my_role, pool, unavailable, dd, limit=8):
    """Qué conviene banear: lo que está fuerte en tu línea y lo que le gana a tus campeones.

    Se mira el rol que vas a jugar, porque el baneo que más te cambia la partida es el del
    campeón que te toca enfrente.
    """
    # tus campeones: los que más jugás, con cuánto peso tiene cada uno en tu pool
    mios = sorted(((cid, g, w) for cid, (g, w) in pool.items() if g >= 3), key=lambda x: -x[1])[:4]
    total_mias = sum(g for _, g, _ in mios) or 1
    # nunca proponer banear un campeón que jugás vos: te quedarías sin él
    propios = {cid for cid, _, _ in mios}
    rivales = [c for c in meta.get(my_role, []) if c["id"] not in unavailable and c["id"] not in propios
               and c.get("pick", 0) >= MIN_PICK]   # banear algo que casi nadie juega es un baneo perdido
    if not rivales:
        return []

    opciones = []
    for c in rivales:
        conf = min(c["games"] / CONF_PARTIDAS, 1.0)
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
# Para recomendar un campeón tiene que jugarse de verdad en ese rol: un campeón raro con pocas partidas puede
# tener 60% de victorias de pura casualidad (Aurelion Sol o Heimerdinger de ADC). Los tuyos entran siempre.
MIN_PICK = 0.008       # que aparezca en al menos el 0,8% de las partidas de tu rango en ese rol
MIN_ROL = 0.2          # y que ese rol sea de verdad uno de los suyos (al menos 1 de cada 5 de sus partidas)
CONF_PARTIDAS = 300    # recién con tantas partidas se le cree del todo su winrate


NICHO = 0.05          # se elige en menos del 5% de las partidas: lo juegan sobre todo sus mains


def piso(c):
    """Lo que como mínimo gana el campeón (con 95% de seguridad), en vez del winrate a secas: con pocas partidas
    el margen de error es grande y el piso baja. Encima, a los de nicho los juegan sobre todo sus mains (que los
    dominan), así que su winrate dice menos de lo que ganarías vos: se les descuenta hasta 2 puntos más."""
    n, p = max(c.get("games", 0), 1), c.get("wr", 0.5)
    lo = p - 1.96 * (p * (1 - p) / n) ** 0.5
    pk = c.get("pick", 0)
    if pk < NICHO:
        lo -= 0.02 * (1 - pk / NICHO)
    return lo


CRUCE_K = 150         # partidas de un cruce para creerle la mitad: con 38 partidas casi no pesa, con 600 bastante
CRUCE_MAX = 0.04      # un cruce de línea suma o resta como mucho 4 puntos (menos que saber jugar el campeón)
PESO_EQUIPO = 0.7     # lo que armó el rival (tanques, control, burst): reglas generales, lo que menos pesa
MIO_MAX = 0.06        # saber jugar el campeón suma hasta 6 puntos (lo que más pesa, junto con lo fuerte del parche)
CAMPO_MIN = 0.03      # a ciegas: los rivales posibles son los que se juegan en al menos el 3% de tu línea


def cruce(c, opp_meta, g, w):
    """Cuánto mejor (o peor) le va a este campeón contra ESE rival que contra cualquiera, ya achicado según
    cuántas partidas hay. Lo esperado sale del winrate de los dos: si Jinx gana 52,9% en general y Draven
    51,1%, contra Draven «lo normal» sería ~51,8%; si gana 59% le va 7 puntos mejor de lo normal."""
    esperado = c.get("wr", 0.5) + (0.5 - (opp_meta or {}).get("wr", 0.5))
    delta = (w - esperado) * g / (g + CRUCE_K)
    return max(-CRUCE_MAX, min(CRUCE_MAX, delta)), w - esperado


def jugable(c, role, dist, dd):
    return c.get("pick", 0) >= MIN_PICK and _role_prob(c["id"], role, dist, dd) >= MIN_ROL


def draft_advice(session: dict, meta: dict, duos: list, dist, dd, default_role="BOTTOM", pool=None, champs=None,
                 confianza=None) -> dict:
    """Orden de importancia: 1) lo que sabés jugar, cruzado con lo fuerte en el parche; 2) cómo le va contra tu
    rival de línea (si ya se sabe; si no, qué tan seguro es a ciegas); 3) lo que armó el rival y tus aliados."""
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
    # ¿qué tan seguro es que ese rival vaya a tu línea? Con los 5 elegidos, o si casi siempre juega ahí, seguro.
    lane_seguro = 0.0
    if lane_opp:
        lane_seguro = 1.0 if len(enemies) >= 5 else _role_prob(lane_opp, my_role, dist, dd)
        if lane_seguro >= 0.75:
            lane_seguro = 1.0
    modo = "counter" if lane_seguro >= 1.0 else ("probable" if lane_opp else "ciegas")
    conf = (confianza or {}).get(my_role) or {}

    def es_mio(cid):
        return conf.get(cid, {}).get("k", 0) >= 0.3 or pool.get(cid, [0])[0] >= 3
    enemy_partner = next((c for c, r in enemy_roles.items() if r == BOT_PARTNER.get(my_role)), None)
    partner = next((a for a in allies if a["role"] == BOT_PARTNER.get(my_role) and a["cid"]), None)
    ally_partner = partner["cid"] if partner else None

    duo_idx = {(d["adc"], d["sup"]): d for d in duos}
    shape = enemy_shape(dd, enemies)
    my_cids = [a["cid"] for a in allies if a["cid"]]

    opp_meta = next((x for x in meta.get(my_role, []) if x["id"] == lane_opp), None) if lane_opp else None
    # los rivales posibles en tu línea (para elegir a ciegas): los que más se juegan y siguen disponibles
    campo = [x for x in meta.get(my_role, []) if x.get("pick", 0) >= CAMPO_MIN and x["id"] not in unavailable]

    def evaluate(c):
        # 1) el meta del parche, mirando lo que como mínimo gana (ver piso): pocas partidas o de nicho bajan solos
        score = piso(c)
        nicho = c.get("pick", 0) < NICHO and c.get("games", 0) > 0
        why = [f"Meta: {c['wr']*100:.1f}% en {c['games']} partidas"
               + (" (de nicho: lo juegan sobre todo sus mains)" if nicho else "")]
        # 2) contra el campeón que te tocó en tu línea
        if lane_opp and str(lane_opp) in c["vs_all"]:
            g, w = c["vs_all"][str(lane_opp)]
            # se mira cuánto mejor le va contra ESE rival que contra cualquiera, y con pocas partidas casi no pesa
            suma, crudo = cruce(c, opp_meta, g, w)
            score += suma * lane_seguro
            why.append(("si va a tu línea, " if modo == "probable" else "")
                       + f"vs {dd.champ_name(lane_opp)}: {w*100:.0f}% en {g} partida{'s' if g != 1 else ''}"
                       + (f" ({abs(crudo)*100:.0f} punto{'' if round(abs(crudo)*100) == 1 else 's'} {'mejor' if crudo >= 0 else 'peor'} que contra cualquiera)"
                          if g >= 30 and abs(crudo) >= 0.01 else "")
                       + (" (pocas)" if g < 100 else ""))
        # 2b) a ciegas (o sin saber seguro tu rival): cómo le va contra lo que más se juega en tu línea
        if modo != "counter" and campo:
            acc = peso = 0.0
            peores = []
            for o in campo:
                vs = c.get("vs_all", {}).get(str(o["id"]))
                if not vs:
                    continue
                d, crudo = cruce(c, o, *vs)
                acc += o["pick"] * d
                peso += o["pick"]
                if crudo <= -0.06 and vs[0] >= 100 and o["pick"] >= 0.05:
                    peores.append((crudo, o["id"], vs))
            if peso:
                score += acc / peso * (1 - lane_seguro)
            peores.sort()
            if peores:
                nombres = [dd.champ_name(i) for _, i, _ in peores[:2]]
                why.append(f"Ojo a ciegas: {' y '.join(nombres)} le gana{'n' if len(nombres) > 1 else ''} "
                           f"y se juega{'n' if len(nombres) > 1 else ''} mucho en tu línea")
            elif peso and acc / peso >= 0.005:
                why.append("Seguro a ciegas: no pierde feo contra lo que más se juega en tu línea")
        # 3) contra el resto de lo que ya pickeó el rival
        fit, fit_why = team_fit(dd, c["id"], shape, my_cids)
        score += fit * PESO_EQUIPO
        why += fit_why
        # 3b) con el resto de tu equipo: combos entre líneas y lo que le falta al equipo
        #     (la dupla del bot no entra en los combos: la mira el punto 4)
        otros = [x for x in my_cids if not (my_role in BOT_PARTNER and x == ally_partner)]
        s_team, why_team, combo_team = ally_synergy(dd, c["id"], my_cids, otros)
        score += s_team
        why += why_team
        # 4) con tu compañero de línea (el que ya bloqueó o el que tiene marcado)
        if ally_partner:
            adc, sup = (c["id"], ally_partner) if my_role == "BOTTOM" else (ally_partner, c["id"])
            s_duo, why_duo, _ = duo_synergy(dd, adc, sup, duo_idx)
            score += s_duo
            why += [f"Con {dd.champ_name(ally_partner)}: {w[len('Juntos: '):]}" if w.startswith("Juntos: ") else w
                    for w in why_duo]
        # 5) tus campeones: lo que ya sabés jugar pesa más que un campeón fuerte que nunca tocaste,
        #    salvo que esté injugable (muy flojo en el parche o muy contrarrestado por tu rival de línea)
        cf = conf.get(c["id"])
        mine = [cf["g"], cf["w"]] if cf else pool.get(c["id"], [0, 0])
        if (cf and cf["k"] >= 0.15) or (not cf and mine[0] >= 2):
            g, w = mine
            k = cf["k"] if cf else min(g, 10) / 10
            comodidad = MIO_MAX * k                          # hasta +6 puntos por saber jugarlo
            # cómo te va a vos con él: pesa poco y recién con 5 partidas (10 partidas son muy pocas para juzgarte)
            propio = (adj_wr(w, g, 15) - 0.5) * 0.06 if g >= 5 else 0.0
            flojo = c.get("games", 0) >= 60 and c.get("adj", 0.5) < 0.47
            contra = False
            if lane_opp and str(lane_opp) in c.get("vs_all", {}):
                vg, vw = c["vs_all"][str(lane_opp)]
                contra = vg >= 15 and adj_wr(vw * vg, vg, 20) < 0.45
            texto = cf["texto"] if cf else f"Lo sabés jugar: {g} partidas tuyas"
            if g >= 3:
                texto += f" · {w / g * 100:.0f}% de victorias"
            if flojo or contra:
                comodidad *= 0.3
                why.append(texto + ", pero " + ("está muy flojo en este parche" if flojo
                                                 else f"{dd.champ_name(lane_opp)} le gana mucho"))
            else:
                why.insert(1, texto)
            score += comodidad + propio
        return score, why, bool(fit_why), es_mio(c["id"]), combo_team

    # tus campeones que casi no aparecen en el meta de tu rango para este rol (pocas partidas en la base):
    # los sumo igual si se juegan en este rol, con los datos generales del campeón
    candidatos = list(meta.get(my_role, []))
    en_meta = {c["id"] for c in candidatos}
    for cid in set(pool) | set(conf):
        if not es_mio(cid) or cid in en_meta or cid in unavailable:
            continue
        roles = dist.get(cid) or dist.get(str(cid)) or {}
        total = sum(roles.values())
        if not total or roles.get(my_role, 0) / total < 0.2:
            continue
        gen = (champs or {}).get(cid) or {}
        gg = gen.get("games", 0)
        a = adj_wr(gen.get("wr", 0.5) * gg, gg, 20)
        candidatos.append({"id": cid, "games": gg, "wr": gen.get("wr", 0.5), "adj": a, "tier": tier_of(a),
                           "pick": 0, "vs_all": {}, "items": gen.get("items", []), "boots": gen.get("boots", []),
                           "keystones": gen.get("keystones", [])})

    options = []
    for c in candidatos:
        if c["id"] in unavailable:
            continue
        if not es_mio(c["id"]) and not jugable(c, my_role, dist, dd):
            continue   # raro en este rol: no lo recomiendo (si es tuyo, sí)
        score, why, counters, mine, sinergia = evaluate(c)
        options.append({**_champ_card(dd, c["id"]), "tier": c["tier"], "score": score, "why": why,
                        "games": c["games"], "thin": c["games"] < 40, "counters": counters, "mine": mine,
                        "sinergia": sinergia,
                        # combo clásico con tu compañero de bot (el panel «Combina con…» ya no existe: va acá)
                        "combo": bool(ally_partner and my_role in BOT_PARTNER and (
                            (_duo_alias(dd, c["id"]), _duo_alias(dd, ally_partner)) if my_role == "BOTTOM"
                            else (_duo_alias(dd, ally_partner), _duo_alias(dd, c["id"]))) in DUO_COMBOS),
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

    if modo == "counter":
        situation = (f"Ya sabés tu rival: {dd.champ_name(lane_opp)}. Primero lo que sabés jugar y está fuerte, "
                     "y entre esos, lo que mejor le va contra él.")
    elif modo == "probable":
        situation = (f"Elegís casi a ciegas: {dd.champ_name(lane_opp)} probablemente vaya a tu línea, pero no es seguro. "
                     "Te muestro lo que sabés jugar y no pierde feo contra lo que más se juega.")
    else:
        situation = ("Elegís a ciegas: todavía no se sabe tu rival. Primero lo que sabés jugar y está fuerte, "
                     "y te aviso si algo pierde feo contra lo que más se juega en tu línea.")
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
    # para banear también se descartan los que tus aliados tienen marcados (todavía sin bloquear)
    bans_sug = ban_options(meta, my_role, pool, unavailable | {a["cid"] for a in allies if a["cid"]}, dd) \
        if paso == "ban" else []

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
        "phase": "draft", "modo": modo,
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
        "inicial": _inicial(dd, rune_cid, my_role, lane_opp),
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
        "options": options[:10],
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


def _inicial(dd, cid, role, rival):
    """Ítems iniciales del rol (menos support), el mejor contra tu rival primero."""
    from .inicial import iniciales
    try:
        return iniciales(dd, cid, role, rival)
    except Exception:  # noqa: BLE001  un dato raro no tiene que romper la pantalla
        return []


def _apoyo(dd, me, allies, enemies, fight, my_role):
    """Misión de Support: las cinco mejoras del ítem, la mejor para esta partida primero, y cuál elegiste."""
    if my_role != "UTILITY":
        return None
    from .apoyo import mejora_support
    r = mejora_support(dd, me, allies, enemies, ((fight or {}).get("compare") or {}).get("score", 0.0))
    for o in r["opciones"]:
        o.update(_item_card(dd, o["id"]))
    return r


def _niveles(inicio: str, prioridad: str) -> list:
    """Arma los 18 niveles: los primeros como se empieza, la R en 6, 11 y 16, y el resto subiendo primero la
    habilidad que se maxea antes (sin pasarse: a nivel N una habilidad puede tener como mucho (N+1)//2 puntos)."""
    pts, out = {"Q": 0, "W": 0, "E": 0, "R": 0}, []
    for lvl in range(1, 19):
        if lvl <= len(inicio):
            k = inicio[lvl - 1]
        elif lvl in (6, 11, 16) and pts["R"] < 3:
            k = "R"
        else:
            k = next((x for x in prioridad if pts[x] < 5 and pts[x] < (lvl + 1) // 2), None) \
                or next((x for x in "QWE" if pts[x] < 5), "R")
        pts[k] += 1
        out.append(k)
    return out


def _habilidades(dd, cid, role, champ_meta, meta):
    """Orden de habilidades que más se usa con este campeón (en tu rol o, si no hay, en cualquiera)."""
    h = (champ_meta or {}).get("habilidades") or {}
    if not h.get("maxeo"):
        h = next((c.get("habilidades") for r in (role, *POSITIONS) for c in meta.get(r, [])
                  if c["id"] == cid and (c.get("habilidades") or {}).get("maxeo")), None) or {}
    if not h.get("maxeo"):
        return None
    mx = h["maxeo"][0]
    inicio = (h.get("inicio") or [{}])[0].get("o") or mx["o"]
    sec = next((s["o"] for s in h.get("secuencias") or [] if s["share"] >= 0.15 and s["o"][:3] == inicio), None)
    niveles = list(sec) + _niveles(sec, mx["o"])[len(sec):] if sec else _niveles(inicio, mx["o"])
    nombre = dd.champ_name(cid)
    orden = " > ".join(mx["o"])
    return {"maxeo": list(mx["o"]), "niveles": niveles, "inicio": inicio,
            "img": {k: dd.skill_img(cid, i) for i, k in enumerate("QWER")},
            "why": f"El {mx['share'] * 100:.0f}% de los {nombre} sube {orden} ({mx['games']} partidas) y gana el "
                   f"{mx['wr'] * 100:.0f}%. La R siempre que puedas (niveles 6, 11 y 16)."}


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
    lane = next((p for p in enemies if enemy_roles.get(p["cid"]) == my_role or p["position"] == my_role), None)
    lane_cmp = None
    if lane:
        lane_cmp = {"gold": me["gold"] - lane["gold"], "level": me["level"] - lane["level"], "cs": me["cs"] - lane["cs"]}
    # lo que necesita el consejo «¿Qué conviene ahora?» para saber en qué momento de la partida estás
    rol_de = lambda p: p["position"] if p["position"] in POSITIONS else enemy_roles.get(p["cid"])  # noqa: E731
    ctx = {"role": my_role, "me": me, "lane": lane, "laneCmp": lane_cmp,
           "allies": {p["position"]: p for p in allies if p["position"] in POSITIONS},
           "enemies": {rol_de(p): p for p in enemies if rol_de(p)},
           "champName": lambda cid: dd.champ_name(cid)}
    fight = ob.situation(game, me["team"], dd, obj, (sum(p["gold"] for p in allies), sum(p["gold"] for p in enemies)),
                         me["cid"], max(dd.items.get(nxt["id"], {}).get("gold", 0) - gold_now, 0) if nxt else None,
                         dd.item_name(nxt["id"]) if nxt else None, ctx=ctx)
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
        "apoyo": _apoyo(dd, me, allies, enemies, fight, my_role),
        "inicial": _inicial(dd, me["cid"], my_role, lane["cid"] if lane else None) if t < 150 else None,
        "habilidades": _habilidades(dd, me["cid"], my_role, champ_meta, meta),
        "enemies": enemy_rows,
        "allies": sorted((row(p) for p in allies), key=by_role),
        "teamGold": [sum(p["gold"] for p in allies), sum(p["gold"] for p in enemies)],
        "teamKills": team_kills,
        "pants": pants(me, allies, enemies, lane_cmp, team_kills, t, my_role),
        "noMeta": not champ_meta,
    }
