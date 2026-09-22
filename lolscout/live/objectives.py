"""Objetivos grandes y lectura de pelea, a partir de lo que el propio juego anuncia (eventos de la
Live Client Data API: el mismo aviso que ves en pantalla cuando alguien mata un dragón o al Barón).

Tiempos del parche 26.x:
- Dragón elemental: 5:00, reaparece 5:00 después de morir. Con 4 dragones de un equipo aparece el Anciano
  (6:00 después), que reaparece cada 6:00.
- Larvas del Vacío: 8:00, una sola vez; desaparecen a las 14:45.
- Heraldo de la Grieta: 15:00, una sola vez.
- Barón Nashor: 20:00, reaparece 6:00 después de morir. Su mejora dura 3:00; la del Anciano, 2:30.
- Inhibidores: vuelven 5:00 después de caer.
"""

DRAKE_ES = {"Fire": "Infernal", "Water": "Océano", "Earth": "Montaña", "Air": "Nube", "Chemtech": "Quimtech",
            "Hextech": "Hextech", "Elder": "Anciano"}
# Imágenes de los objetivos (sacadas de los archivos del juego, vía CommunityDragon)
DRAKE_IMG = {"Fire": "sru_dragon_fire", "Water": "sru_dragon_water", "Earth": "sru_dragon_earth",
             "Air": "sru_dragon_air", "Chemtech": "sru_dragon_chemtech", "Hextech": "sru_dragon_hextech",
             "Elder": "sru_dragon_elder"}
OBJ_IMG = {"drake": "sru_dragon", "elder": "sru_dragon_elder", "baron": "sru_baron", "herald": "sru_riftherald",
           "grubs": "sru_horde"}
DRAKE_COLOR = {"Fire": "#ff7b39", "Water": "#3fb6ff", "Earth": "#c89b5a", "Air": "#b8e3ff", "Chemtech": "#9be36a",
               "Hextech": "#43d7ff", "Elder": "#d6b3ff"}


def _norm(name):
    return (name or "").split("#")[0].strip().lower()


def _team_of(name, players):
    n = _norm(name)
    for p in players:
        for k in ("riotIdGameName", "riotId", "summonerName"):
            if _norm(p.get(k)) == n and n:
                return p.get("team")
    return None


def objectives(game, my_team):
    t = game.get("gameData", {}).get("gameTime", 0)
    players = game.get("allPlayers", [])
    events = (game.get("events") or {}).get("Events", [])
    other = "CHAOS" if my_team == "ORDER" else "ORDER"
    drakes = {my_team: [], other: []}
    last_drake = last_baron = last_elder = None
    baron_by = elder_by = None
    grubs = {my_team: 0, other: 0}
    herald_by = None
    inhibs = []
    for e in events:
        name, et = e.get("EventName"), e.get("EventTime", 0)
        team = _team_of(e.get("KillerName"), players)
        if name == "DragonKill":
            if e.get("DragonType") == "Elder":
                last_elder, elder_by = et, team
            else:
                last_drake = et
                if team in drakes:
                    drakes[team].append(e.get("DragonType"))
        elif name == "BaronKill":
            last_baron, baron_by = et, team
        elif name == "HeraldKill":
            herald_by = team
        elif name == "HordeKill":
            if team in grubs:
                grubs[team] += 1
        elif name == "InhibKilled":
            inhibs.append((et, e.get("InhibKilled", "")))

    def timer(key, label, spawn_at, available_until=None, taken=False, taken_by=None, extra="", img=None):
        img = f"/static/obj/{img or OBJ_IMG.get(key, 'sru_dragon')}.png"
        if taken:
            return {"key": key, "label": label, "state": "taken", "text": "tomado" + (f" por {taken_by}" if taken_by else ""),
                    "extra": extra, "img": img}
        if available_until is not None and t >= available_until:
            return {"key": key, "label": label, "state": "gone", "text": "ya no está", "extra": extra, "img": img}
        if t >= spawn_at:
            return {"key": key, "label": label, "state": "up", "text": "VIVO", "extra": extra, "img": img}
        left = int(spawn_at - t)
        return {"key": key, "label": label, "state": "soon" if left <= 60 else "wait",
                "text": f"{left // 60}:{left % 60:02d}", "at": f"{int(spawn_at // 60)}:{int(spawn_at % 60):02d}",
                "extra": extra, "img": img}

    who = lambda team: "tu equipo" if team == my_team else "el rival" if team else None  # noqa: E731
    soul = next((tm for tm, d in drakes.items() if len(d) >= 4), None)
    rows = []
    if soul:
        nxt = (last_elder or last_drake) + 360
        rows.append(timer("elder", "Dragón Anciano", nxt, extra=f"Alma para {who(soul)}"))
    else:
        nxt = 300 if last_drake is None else last_drake + 300
        # desde el 3er dragón el mapa queda de un elemento: los que siguen son todos de ese tipo
        all_drakes = [e.get("DragonType") for e in events if e.get("EventName") == "DragonKill"
                      and e.get("DragonType") != "Elder"]
        rift = all_drakes[2] if len(all_drakes) >= 3 else None
        label = f"Dragón {DRAKE_ES.get(rift, '')}".strip() if rift else "Dragón"
        rows.append(timer("drake", label, nxt, extra=f"Tu equipo {len(drakes[my_team])} · Rival {len(drakes[other])}",
                          img=DRAKE_IMG.get(rift)))
    gm, gt = grubs[my_team], grubs[other]
    grub_by = None
    if gm and gt:
        grub_by = f"tu equipo ({gm}) y el rival ({gt})"
    elif gm or gt:
        grub_by = "tu equipo" if gm else "el rival"
    rows.append(timer("grubs", "Larvas del Vacío", 480, available_until=885, taken=bool(gm or gt), taken_by=grub_by))
    rows.append(timer("herald", "Heraldo", 900, taken=herald_by is not None, taken_by=who(herald_by)))
    baron_next = 1200 if last_baron is None else last_baron + 360
    rows.append(timer("baron", "Barón Nashor", baron_next))

    buffs = []
    if last_baron is not None and t - last_baron < 180:
        left = int(180 - (t - last_baron))
        buffs.append({"text": f"Mejora del Barón: {who(baron_by)}", "left": f"{left // 60}:{left % 60:02d}",
                      "mine": baron_by == my_team})
    if last_elder is not None and t - last_elder < 150:
        left = int(150 - (t - last_elder))
        buffs.append({"text": f"Mejora del Anciano: {who(elder_by)}", "left": f"{left // 60}:{left % 60:02d}",
                      "mine": elder_by == my_team})
    inhib_rows = []
    for et, _name in inhibs:
        if t - et < 300:
            left = int(300 - (t - et))
            inhib_rows.append(f"Un inhibidor vuelve en {left // 60}:{left % 60:02d}")
    return {"rows": rows, "buffs": buffs, "inhibs": inhib_rows,
            "drakes": {"mine": [DRAKE_ES.get(d, d) for d in drakes[my_team]],
                       "theirs": [DRAKE_ES.get(d, d) for d in drakes[other]],
                       "mineColors": [DRAKE_COLOR.get(d, "#888") for d in drakes[my_team]],
                       "theirsColors": [DRAKE_COLOR.get(d, "#888") for d in drakes[other]],
                       "mineImgs": [f"/static/obj/{DRAKE_IMG.get(d, 'sru_dragon')}.png" for d in drakes[my_team]],
                       "theirsImgs": [f"/static/obj/{DRAKE_IMG.get(d, 'sru_dragon')}.png" for d in drakes[other]]},
            "baron_by": baron_by, "elder_by": elder_by, "soonest": min(
                (r for r in rows if r["state"] in ("soon", "up")), key=lambda r: 0 if r["state"] == "up" else 1, default=None)}


SPLITTERS = {"Fiora", "Jax", "Tryndamere", "Camille", "Yorick", "Nasus", "Trundle", "Shen", "Gwen", "Sion",
             "Udyr", "Kayle", "Illaoi", "Briar", "Jayce", "Quinn", "Garen", "Darius", "Riven", "Irelia", "Yone",
             "Yasuo", "Aatrox", "Gangplank", "Sett", "Olaf", "Kled", "Singed", "Teemo", "Volibear", "Warwick"}
LANE_ES = {"L": "arriba", "C": "medio", "R": "abajo"}


def towers(game, my_team):
    """Torres caídas por equipo y carril (del aviso 'TurretKilled': Turret_T1_L_03_A)."""
    lost = {"ORDER": {"L": 0, "C": 0, "R": 0}, "CHAOS": {"L": 0, "C": 0, "R": 0}}
    for e in (game.get("events") or {}).get("Events", []):
        if e.get("EventName") != "TurretKilled":
            continue
        parts = (e.get("TurretKilled") or "").split("_")
        if len(parts) >= 3 and parts[1] in ("T1", "T2") and parts[2] in ("L", "C", "R"):
            lost["ORDER" if parts[1] == "T1" else "CHAOS"][parts[2]] += 1
    other = "CHAOS" if my_team == "ORDER" else "ORDER"
    return {"mine_lost": lost[my_team], "theirs_lost": lost[other]}


def compare(players_raw, my_team, dd, obj, item_gold):
    """Compara la fuerza de los dos equipos AHORA (solo con lo que muestra el marcador)."""
    mine = [p for p in players_raw if p.get("team") == my_team]
    theirs = [p for p in players_raw if p.get("team") != my_team]
    alive_m = [p for p in mine if not p.get("isDead")]
    alive_t = [p for p in theirs if not p.get("isDead")]
    lvl = lambda ps: sum(p.get("level", 1) for p in ps) / max(len(ps), 1)  # noqa: E731
    gold_m, gold_t = item_gold
    factors, score = [], 0.0
    diff = len(alive_m) - len(alive_t)
    if diff:
        score += 0.28 * diff
        dead_t = sorted((p for p in theirs if p.get("isDead")), key=lambda p: -p.get("respawnTimer", 0))
        detail = ", ".join(f"{dd.champ_name(dd.champ_from_live(p.get('rawChampionName', ''), p.get('championName', '')))}"
                           f" ({int(p.get('respawnTimer', 0))} s)" for p in dead_t[:3])
        factors.append({"good": diff > 0, "text": f"{len(alive_m)} vivos contra {len(alive_t)}" +
                        (f" — muertos rivales: {detail}" if detail and diff > 0 else "")})
    lv = lvl(alive_m or mine) - lvl(alive_t or theirs)
    if abs(lv) >= 0.5:
        score += 0.25 * max(-2, min(2, lv))
        factors.append({"good": lv > 0, "text": f"Nivel promedio {'+' if lv > 0 else ''}{lv:.1f}"})
    gd = gold_m - gold_t
    if abs(gd) >= 1000:
        score += 0.35 * max(-2.5, min(2.5, gd / 3000))
        factors.append({"good": gd > 0, "text": f"{'+' if gd > 0 else ''}{gd / 1000:.1f}k de oro en ítems"})
    for bf in obj["buffs"]:
        score += 0.45 if bf["mine"] else -0.45
        factors.append({"good": bf["mine"], "text": f"{bf['text']} ({bf['left']})"})
    if not factors:
        factors.append({"good": None, "text": "Equipos muy parejos ahora mismo"})
    score = max(-1.5, min(1.5, score))
    if score >= 0.7:
        label, tone = "Ventaja clara para tu equipo", "good"
    elif score >= 0.25:
        label, tone = "Ventaja leve para tu equipo", "good"
    elif score > -0.25:
        label, tone = "Pelea pareja", "even"
    elif score > -0.7:
        label, tone = "Desventaja leve", "bad"
    else:
        label, tone = "Desventaja clara", "bad"
    return {"score": round(score, 2), "label": label, "tone": tone, "factors": factors,
            "alive_diff": diff, "alive": [len(alive_m), len(alive_t)]}


OBJ_PRIORITY = {"baron": 5, "elder": 5, "drake": 3, "herald": 2, "grubs": 2}
OBJ_SIDE = {"drake": "abajo", "elder": "abajo", "baron": "arriba", "herald": "arriba", "grubs": "arriba"}


def situation(game, my_team, dd, obj, item_gold, my_cid, next_missing=None, next_name=None):
    """Qué tiene sentido hacer ahora: si hay un objetivo en juego, la lectura de esa pelea;
    si no, opciones de macro (agruparse, split push, torres, farmear) ordenadas según la partida."""
    t = game.get("gameData", {}).get("gameTime", 0)
    cmp_ = compare(game.get("allPlayers", []), my_team, dd, obj, item_gold)
    adv, alive_diff = cmp_["score"], cmp_["alive_diff"]
    tw = towers(game, my_team)

    live = [r for r in obj["rows"] if r["state"] == "up" or r["state"] == "soon"]
    if live:
        r = max(live, key=lambda r: (r["state"] == "up", OBJ_PRIORITY.get(r["key"], 1)))
        stakes = []
        if r["key"] == "drake":
            mine_n, theirs_n = len(obj["drakes"]["mine"]), len(obj["drakes"]["theirs"])
            if mine_n == 3:
                stakes.append("Si lo toma tu equipo, consigue el ALMA del dragón")
            if theirs_n == 3:
                stakes.append("Si lo toma el rival, consigue el ALMA del dragón")
            if not stakes:
                stakes.append(f"Dragones: tu equipo {mine_n} · rival {theirs_n}")
        elif r["key"] == "baron":
            stakes.append("La mejora dura 3:00 y potencia a tus súbditos para tirar torres")
        elif r["key"] == "elder":
            stakes.append("La mejora del Anciano ejecuta a los rivales con poca vida (2:30)")
        elif r["key"] == "herald":
            stakes.append("El Heraldo sirve para tirar torres rápido")
        elif r["key"] == "grubs":
            stakes.append("Las Larvas dan más daño a estructuras")
        when = "está VIVO" if r["state"] == "up" else f"aparece en {r['text']}"
        if adv >= 0.25:
            reading, tone = "Buena ventana para disputarlo", "good"
            alts = ["Llegar primero y poner visión alrededor", "Si el rival no se presenta, tomarlo rápido"]
        elif adv > -0.25:
            reading, tone = "Disputa pareja: pesa quién llega primero y con visión", "even"
            alts = ["Pelearlo solo con visión y todos juntos", "Si llegan tarde, cambiarlo por torres del otro lado"]
        else:
            reading, tone = "Riesgoso: el rival está más fuerte ahora", "bad"
            opposite = "arriba" if OBJ_SIDE.get(r["key"]) == "abajo" else "abajo"
            alts = [f"Cambiarlo por torres o placas en el carril de {opposite}",
                    "Esperar a tu próximo ítem o a que muera algún rival antes de pelearlo"]
        return {"mode": "objective", "objective": {"key": r["key"], "label": r["label"], "when": when,
                                                   "state": r["state"], "img": r["img"]},
                "stakes": stakes, "reading": reading, "tone": tone, "compare": cmp_, "alts": alts}

    # ---- sin objetivos en juego: opciones de macro
    upcoming = [r for r in obj["rows"] if r["state"] == "wait"]
    secs = lambda r: int(r["text"].split(":")[0]) * 60 + int(r["text"].split(":")[1])  # noqa: E731
    nxt = min(upcoming, key=secs) if upcoming else None
    side = "arriba" if nxt and OBJ_SIDE.get(nxt["key"]) == "abajo" else "abajo"
    ch = dd.champions.get(my_cid, {})
    splitter = ch.get("alias") in SPLITTERS or ("Fighter" in ch.get("tags", []) and not ch.get("ranged"))
    theirs_lost = tw["theirs_lost"]
    open_lane = max(theirs_lost, key=theirs_lost.get)
    opts = []

    def opt(score, title, why):
        opts.append({"score": round(score, 2), "title": title, "why": why})

    why = []
    if alive_diff > 0:
        why.append(f"{cmp_['alive'][0]} vivos contra {cmp_['alive'][1]}")
    if adv >= 0.25:
        why.append("tu equipo está más fuerte ahora")
    opt(0.45 + adv * 0.6 + (0.25 if alive_diff > 0 else 0), "Agruparse y buscar pelea",
        why or ["los equipos están parejos: depende de quién enganche mejor"])
    sw = [f"el próximo objetivo ({nxt['label']}) aparece del otro lado" if nxt else "presionar un carril lateral"]
    if splitter:
        sw.append(f"{ch.get('name', 'tu campeón')} gana duelos de a uno")
    opt(0.3 + (0.35 if splitter else 0) + (0.1 if t >= 840 else -0.3) - (0.3 if adv <= -0.7 else 0),
        f"Split push por el carril de {side}", sw)
    tow = []
    if alive_diff >= 2:
        tow.append(f"hay {alive_diff} rivales menos en el mapa")
    if theirs_lost[open_lane]:
        tow.append(f"en el carril de {LANE_ES[open_lane]} ya cayeron {theirs_lost[open_lane]} torres rivales")
    opt(0.25 + 0.3 * max(0, alive_diff) + (0.2 if adv > 0.4 else 0), "Tirar torres y placas", tow or ["sumás oro para todo el equipo"])
    safe = []
    if adv <= -0.25:
        safe.append("el rival está más fuerte ahora")
    if next_missing is not None and 0 < next_missing <= 500:
        safe.append(f"te faltan {next_missing} de oro para {next_name}")
    opt(0.25 + (0.5 if adv <= -0.25 else 0) + (0.25 if safe and next_missing and next_missing <= 500 else 0),
        "Farmear seguro y esperar", safe or ["no hay nada urgente en el mapa"])
    if nxt:
        mins = nxt["text"]
        near = secs(nxt) <= 150
        opt(0.55 if near else 0.15, f"Preparar visión para el {nxt['label']}",
            [f"aparece en {mins} ({nxt.get('at', '')})"])
    opts.sort(key=lambda o: -o["score"])
    return {"mode": "macro", "compare": cmp_, "options": opts[:3],
            "towers": {"mine_lost": sum(tw["mine_lost"].values()), "theirs_lost": sum(theirs_lost.values())}}


ROLE_QUEST = {
    "TOP": {"name": "Misión de Top", "how": "Kills, súbditos en línea, placas y torres (1200 puntos).",
            "reward": "Nivel máximo 20, +11% de experiencia y Teletransporte mejorado."},
    "JUNGLE": {"name": "Misión de Jungla", "how": "Dale golosinas a tu mascota de jungla (35).",
               "reward": "Castigo Primordial, +10 de oro y experiencia por campamento y más velocidad en la jungla."},
    "MIDDLE": {"name": "Misión de Mid", "how": "Kills, súbditos, placas, torres y daño a campeones (1350 puntos).",
               "reward": "+8% de AD y AP, y tus botas nivel 2 pasan gratis a unas botas exclusivas nivel 3."},
    "BOTTOM": {"name": "Misión de ADC", "how": "Súbditos en línea, kills, placas y torres (1350 puntos).",
               "reward": "300 de oro, +2 de oro por súbdito, +40 por kill y las botas pasan a su propio espacio: "
                         "te queda lugar para 6 ítems más las botas."},
    "UTILITY": {"name": "Misión de Support", "how": "Oro de tu ítem de support y cargas de Riquezas Compartidas (800).",
                "reward": "Tu ítem de support mejora gratis (6 caminos a elegir) y el Centinela de Control cuesta 40."},
}
