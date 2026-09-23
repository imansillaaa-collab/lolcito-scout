"""Análisis de la partida en curso y armado de una build pensada para ESTA partida.

1. Lee al equipo rival como en el marcador (campeones, niveles, ítems, KDA) y estima: tipo de daño,
   armadura/resistencia mágica, vida extra, curaciones, escudos, control, críticos, quién está adelantado.
2. Arma una build completa de 6 ítems: parte de lo que usa tu campeón (sus estadísticas), pero elige cada
   ítem por lo que necesita esta partida, con rendimientos decrecientes (una vez que tenés Heridas Graves,
   la segunda deja de sumar) y sin combinar ítems incompatibles (dos "Lifeline", dos de penetración %, etc.).
3. Compara contra la build "de siempre" y explica cada cambio. Todo son opciones: decidís vos.
"""
from collections import Counter

from . import builds

# Valor aproximado en oro de cada estadística (para comparar ítems de forma pareja)
GOLD_VALUE = {"ad": 35, "ap": 20, "as": 25, "crit": 40, "leth": 30, "arpen": 45, "mpen": 45, "hp": 2.67,
              "armor": 20, "mr": 18, "ah": 26.7, "ms": 39, "ls": 37.5, "ov": 40, "hsp": 45, "mana": 1.4,
              "ten": 15, "mregen": 5, "hregen": 3}
PHYSICAL = {"ad", "crit", "leth", "arpen", "as"}
MAGIC = {"ap", "mpen"}

HEALERS = {"Soraka", "Yuumi", "Sona", "Nami", "Milio", "Seraphine", "Aatrox", "Vladimir", "Sylas", "DrMundo",
           "Warwick", "Swain", "Fiddlesticks", "Briar", "Illaoi", "Olaf", "Maokai", "Samira", "Belveth",
           "Volibear", "Trundle", "Zac", "Kayn", "Nasus", "Aphelios", "Senna", "Renekton", "Darius", "Gwen",
           "Irelia", "Viego", "Vayne", "Taric", "Ivern", "Rakan", "Janna"}
SHIELDERS = {"Lulu", "Janna", "Karma", "Seraphine", "Sona", "Orianna", "Ivern", "Lux", "Milio", "Renata",
             "Rell", "Braum", "Taric", "Shen", "Yasuo", "Yone", "Sett", "Mordekaiser", "Riven", "Camille",
             "Rakan", "Nautilus", "Galio", "Skarner", "Poppy", "Diana", "Morgana"}
HARD_CC = {"Leona", "Nautilus", "Thresh", "Blitzcrank", "Morgana", "Lux", "Rell", "Alistar", "Rakan", "Pyke",
           "Maokai", "Amumu", "Sejuani", "Ashe", "Malphite", "Skarner", "Zac", "Annie", "Veigar", "Lissandra",
           "Braum", "Taric", "Neeko", "Warwick", "Vi", "Jax", "Poppy", "Sett", "Ornn", "Galio", "TwistedFate",
           "Xerath", "Zyra", "Bard", "Swain", "Nami", "Sona", "Cassiopeia", "Syndra", "Leblanc", "Nocturne",
           "Vex", "Sion", "Rammus", "Kennen", "Jarvan IV", "JarvanIV", "Chogath", "Tahm Kench", "TahmKench"}

TAG_TEXT = {
    "antiheal": "aplica Heridas Graves (cortan la curación)",
    "armorpen": "penetra armadura",
    "magicpen": "penetra resistencia mágica",
    "vs_tank": "daño por vida (bueno contra tanques)",
    "antishield": "rompe escudos",
    "vs_ap": "resistencia mágica",
    "vs_ad": "armadura",
    "antiburst": "te salva del burst",
    "anticc": "menos control sobre vos",
    "anticrit": "reduce el daño crítico",
    "antias": "baja la velocidad de ataque rival",
}
# Cuánto suma cada necesidad (0..1) a un ítem que la cubre. Pesan fuerte a propósito: la build tiene
# que responder a lo que arma el equipo rival, no ser siempre la misma.
TAG_WEIGHT = {"antiheal": 1.1, "armorpen": 0.7, "magicpen": 0.7, "vs_tank": 0.55, "antishield": 0.5,
              "vs_ap": 0.7, "vs_ad": 0.7, "antiburst": 0.55, "anticc": 0.45, "anticrit": 0.45, "antias": 0.35}
EXCLUSIVE = ("lifeline", "qss", "lastwhisper", "antiheal")  # a lo sumo uno de cada grupo


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def gold_vector(dd, iid):
    return {k: v * GOLD_VALUE.get(k, 0) for k, v in dd.items.get(iid, {}).get("full", {}).items()}


# ---------------------------------------------------------------- perfil de tu campeón
META_FULL = 80  # partidas a partir de las cuales las estadísticas mandan casi solas


def champion_profile(dd, cid, champ_meta):
    """Qué estadísticas aprovecha tu campeón (0..1 por estadística).

    Parte del tipo de build que arma de verdad ese campeón (builds.py) y, si las estadísticas tienen
    suficientes partidas suyas, se va acercando a lo que arma la gente en tu rango. Con pocas partidas
    casi no pesan: antes, un campeón sin datos se armaba según las etiquetas de Riot y salían disparates
    (Malphite está etiquetado "Tanque + Mago" y terminaba con build de mago).
    """
    base = builds.base_profile(dd, cid)
    w = Counter()
    for it in (champ_meta or {}).get("items", [])[:8]:
        for k, v in gold_vector(dd, it["id"]).items():
            w[k] += v * it["share"]
    if w:
        top = max(w.values())
        meta_prof = {k: v / top for k, v in w.items()}
        conf = min((champ_meta or {}).get("games", 0) / META_FULL, 1.0) * 0.8
        prof = {k: conf * meta_prof.get(k, 0) + (1 - conf) * base.get(k, 0)
                for k in set(meta_prof) | set(base)}
    else:
        prof = dict(base)
    top = max(prof.values()) if prof else 1
    prof = {k: v / top for k, v in prof.items() if v > 0}
    phys = sum(prof.get(k, 0) for k in PHYSICAL)
    mag = sum(prof.get(k, 0) for k in MAGIC)
    prof["_damage"] = builds.damage_type(dd, cid, prof, phys, mag)
    return prof


OFFENSE = PHYSICAL | MAGIC | {"ls", "ov"}


def offense_fit(dd, iid, prof):
    """Qué parte del daño que da el ítem aprovecha tu campeón (letalidad en un tirador de críticos = poco)."""
    gv = {k: v for k, v in gold_vector(dd, iid).items() if k in OFFENSE}
    total = sum(gv.values())
    if not total:
        return None
    return sum(v * min(1.0, prof.get(k, 0) * 1.5) for k, v in gv.items()) / total


def eligible(dd, iid, prof, popular):
    if iid in popular:
        return True
    f = fit(dd, iid, prof)
    of = offense_fit(dd, iid, prof)
    if of is None:  # ítem 100% defensivo: solo para campeones que ya arman vida/resistencias
        return f >= 0.5 and max(prof.get("hp", 0), prof.get("armor", 0), prof.get("mr", 0)) >= 0.5
    return of >= 0.55 and f >= 0.58


def fit(dd, iid, prof):
    gv = gold_vector(dd, iid)
    total = sum(gv.values())
    if not total:
        return 0.0
    return sum(v * prof.get(k, 0) for k, v in gv.items()) / total


# ---------------------------------------------------------------- lectura del equipo rival
def enemy_report(enemies, dd, me=None, my_stats=None, my_damage="physical"):
    rows, weights = [], []
    heal_src, shield_src, cc_src, crit_src, as_src, tanks, fed_burst = [], [], [], [], [], [], []
    invis_src, true_src, maxhp_src, heal_pts = [], [], [], 0.0
    avg_gold = sum(p["gold"] for p in enemies) / max(len(enemies), 1)
    for p in enemies:
        ch = dd.champions.get(p["cid"], {})
        alias, tags, st = ch.get("alias", ""), ch.get("tags", []), ch.get("stats", {})
        full = Counter()
        for i in p["items"]:
            full.update(dd.items.get(i, {}).get("full", {}))
        info = ch.get("info", {})
        a, m = info.get("attack", 5), info.get("magic", 5)
        ap = m / (a + m) if a + m else 0.5
        if full["ad"] + full["ap"] > 40:
            ap = 0.4 * ap + 0.6 * full["ap"] / (full["ad"] + full["ap"])
        lvl = p["level"]
        armor = st.get("armor", 30) + st.get("armorperlevel", 4) * (lvl - 1) + full["armor"]
        mr = st.get("spellblock", 30) + st.get("spellblockperlevel", 1.3) * (lvl - 1) + full["mr"]
        threat = (1 + p["gold"] / 3000) * (1 + max(p["k"] - p["d"], 0) * 0.12)
        weights.append(threat)
        name = ch.get("name", "?")
        item_heal = sum(1 for i in p["items"] if "heals" in dd.items.get(i, {}).get("tags", ())
                        and dd.items.get(i, {}).get("completed"))
        flags = []
        kit = ch.get("kit", {})
        # curación: la del kit (pasiva/habilidades) + la de sus ítems
        hp_pts = (1.0 if alias in HEALERS else 0.5 if kit.get("heal") else 0) + 0.5 * item_heal
        if hp_pts >= 0.5:
            heal_src.append(name); flags.append("cura"); heal_pts += hp_pts
        if alias in SHIELDERS or kit.get("shield") or full["hsp"]:
            shield_src.append(name); flags.append("escudos")
        if alias in HARD_CC or kit.get("cc", 0) >= 2:
            cc_src.append(name); flags.append("control")
        if kit.get("invis"):
            invis_src.append(name); flags.append("invisible")
        if kit.get("true"):
            true_src.append(name); flags.append("daño verdadero")
        if kit.get("maxhp"):
            maxhp_src.append(name); flags.append("% de vida")
        if full["crit"] >= 50:
            crit_src.append(name); flags.append("críticos")
        if "Marksman" in tags or full["as"] >= 50:
            as_src.append(name)
        if "Tank" in tags or full["hp"] >= 900:
            tanks.append((name, int(full["hp"]))); flags.append("tanque")
        burst = "Assassin" in tags or ("Mage" in tags and ap > 0.6)
        if burst and (p["gold"] > avg_gold * 1.15 or p["k"] - p["d"] >= 3):
            fed_burst.append(f"{name} {p['k']}/{p['d']}"); flags.append("peligroso")
        rows.append({"cid": p["cid"], "ap": ap, "armor": round(armor), "mr": round(mr), "bonus_hp": int(full["hp"]),
                     "dmg": "AP" if ap >= 0.6 else "AD" if ap <= 0.4 else "Mixto", "flags": flags, "threat": threat})

    wsum = sum(weights) or 1
    ap_share = sum(r["ap"] * w for r, w in zip(rows, weights)) / wsum
    avg_armor = sum(r["armor"] for r in rows) / max(len(rows), 1)
    avg_mr = sum(r["mr"] for r in rows) / max(len(rows), 1)
    max_armor = max(rows, key=lambda r: r["armor"]) if rows else None
    max_mr = max(rows, key=lambda r: r["mr"]) if rows else None
    heal_score = heal_pts + 0.5 * sum(1 for r in rows if "cura" in r["flags"] and r["threat"] > 1.6)
    true_share = len(true_src) / max(len(rows), 1)

    needs = {
        "antiheal": _clamp((heal_score - 0.5) / 2.5),
        "armorpen": _clamp((avg_armor - 55) / 70) if my_damage == "physical" else 0,
        "magicpen": _clamp((avg_mr - 45) / 55) if my_damage == "magic" else 0,
        "vs_tank": _clamp(len(tanks) / 2.5 + sum(h for _, h in tanks) / 4000),
        "antishield": _clamp((len(shield_src) - 1) / 2.5),
        # si varios hacen daño verdadero, la armadura/resistencia rinde un poco menos
        "vs_ap": _clamp((ap_share - 0.38) / 0.35) * (1 - 0.35 * true_share),
        "vs_ad": _clamp((0.62 - ap_share) / 0.35) * (1 - 0.35 * true_share),
        "avoid_hp": _clamp(len(maxhp_src) / 3),
        "antiburst": 0.85 if fed_burst else 0.15,
        "anticc": _clamp((len(cc_src) - 1) / 3),
        "anticrit": _clamp(len(crit_src) / 2),
        "antias": _clamp((len(as_src) - 1) / 2),
    }

    alerts = []
    def alert(level, key, text, detail=""):
        alerts.append({"level": level, "key": key, "text": text, "detail": detail})

    pct_ap = round(ap_share * 100)
    my_mr = round((my_stats or {}).get("magicResist", 0))
    my_armor = round((my_stats or {}).get("armor", 0))
    if ap_share >= 0.6:
        alert("alta", "dmg", f"Daño mayormente MÁGICO ({pct_ap}%)", f"Tu resistencia mágica: {my_mr}" if my_stats else "")
    elif ap_share <= 0.4:
        alert("alta", "dmg", f"Daño mayormente FÍSICO ({100 - pct_ap}%)", f"Tu armadura: {my_armor}" if my_stats else "")
    else:
        alert("info", "dmg", f"Daño MIXTO ({pct_ap}% mágico)", "Conviene repartir defensas")
    if needs["antiheal"] >= 0.5:
        alert("alta", "antiheal", "Mucha curación", ", ".join(heal_src))
    elif heal_src:
        alert("media", "antiheal", "Algo de curación", ", ".join(heal_src))
    if my_damage == "physical" and avg_armor >= 70:
        alert("alta" if avg_armor >= 100 else "media", "armor", f"Armadura alta: {round(avg_armor)} de promedio",
              f"{dd.champ_name(max_armor['cid'])} tiene ~{max_armor['armor']}")
    if my_damage == "magic" and avg_mr >= 55:
        alert("alta" if avg_mr >= 80 else "media", "mr", f"Resistencia mágica alta: {round(avg_mr)} de promedio",
              f"{dd.champ_name(max_mr['cid'])} tiene ~{max_mr['mr']}")
    if tanks:
        alert("media", "tank", "Tanques", ", ".join(f"{n} (+{h} vida)" for n, h in tanks))
    if fed_burst:
        alert("alta", "burst", "Asesino/burst adelantado", ", ".join(fed_burst))
    if len(cc_src) >= 3:
        alert("media", "cc", f"Mucho control ({len(cc_src)} campeones)", ", ".join(cc_src))
    if len(shield_src) >= 2:
        alert("media", "shield", "Varios escudos", ", ".join(shield_src))
    if crit_src:
        alert("media", "crit", "Críticos", ", ".join(crit_src))
    if invis_src:
        alert("media", "invis", "Tienen invisibilidad", ", ".join(invis_src) +
              " — un Centinela de Control o la Lente del Oráculo te dejan verlos")
    if len(maxhp_src) >= 2:
        alert("media", "maxhp", "Daño por % de vida", ", ".join(maxhp_src) +
              " — la vida extra rinde menos: mejor resistencias")
    if len(true_src) >= 2:
        alert("info", "true", "Daño verdadero", ", ".join(true_src) + " — ignora armadura y resistencia mágica")
    if len(as_src) >= 2:
        alert("info", "as", "Mucha velocidad de ataque", ", ".join(as_src))
    order = {"alta": 0, "media": 1, "info": 2}
    alerts.sort(key=lambda a: order[a["level"]])
    return {"rows": {r["cid"]: r for r in rows}, "needs": needs, "alerts": alerts, "ap_share": ap_share,
            "avg_armor": avg_armor, "avg_mr": avg_mr}


# ---------------------------------------------------------------- build para esta partida
def _groups(dd, iid):
    return {g for g in EXCLUSIVE if g in dd.items.get(iid, {}).get("tags", ())}


def _reasons(dd, iid, needs, prof):
    out = []
    for t in dd.items.get(iid, {}).get("tags", ()):
        if t in TAG_TEXT and needs.get(t, 0) >= 0.35:
            if t == "armorpen" and prof["_damage"] != "physical":
                continue
            if t == "magicpen" and prof["_damage"] != "magic":
                continue
            out.append(TAG_TEXT[t])
    return out


def _score(dd, iid, prof, pop, needs, first=False, core=(), core_w=0.0, pop_w=1.0):
    info = dd.items.get(iid, {})
    f = fit(dd, iid, prof)
    p = pop.get(iid, {})
    share, wr = p.get("share", 0) * pop_w, p.get("wr", 0.5)  # con pocas partidas, lo popular pesa menos
    is_core = core_w * (iid in core)
    need = 0.0
    for t in info.get("tags", ()):
        if t == "armorpen" and prof["_damage"] != "physical":
            continue
        if t == "magicpen" and prof["_damage"] != "magic":
            continue
        need += needs.get(t, 0) * TAG_WEIGHT.get(t, 0)
    if needs.get("avoid_hp"):  # rivales que pegan por % de vida: la vida extra rinde menos
        gv = gold_vector(dd, iid)
        need -= needs["avoid_hp"] * 0.3 * gv.get("hp", 0) / (sum(gv.values()) or 1)
    if first:  # el primer ítem: manda lo que funciona con tu campeón, pero el rival ya pesa
        return 1.6 * min(share, 0.8) + 0.5 * f + 0.9 * is_core + 0.3 * need
    wr_bonus = (wr - 0.5) * 0.6 if share >= 0.05 else 0
    return 0.55 * f + 0.45 * min(share, 0.6) + need + wr_bonus + 0.35 * is_core


def plan_build(dd, me, prof, champ_meta, needs, gold_now, n_items=5):
    owned = [i for i in me["items"] if dd.items.get(i, {}).get("completed")]
    owned_items = [i for i in owned if not dd.items[i]["boots"]]
    owned_boots = next((i for i in owned if dd.items[i]["boots"]), None)
    pop = {}
    for key in ("items", "boots"):
        for it in (champ_meta or {}).get(key, []):
            pop[it["id"]] = it
    # mientras las estadísticas de este campeón tengan pocas partidas, pesan sus ítems típicos
    core = builds.core_items(dd, me.get("cid"))
    core_w = 1 - min((champ_meta or {}).get("games", 0) / META_FULL, 1.0) * 0.8
    pop_w = min((champ_meta or {}).get("games", 0) / 40, 1.0) if champ_meta else 0.0

    # candidatos: lo que arma tu campeón + cualquier ítem que aproveche sus estadísticas
    names_seen, cands, boots_c = set(), [], []
    for iid, info in dd.items.items():
        if not info.get("completed") or not info.get("sr") or info["name"] in names_seen:
            continue
        if info["boots"]:
            if info.get("depth", 2) != 2:  # botas nivel 3: son una mejora aparte
                continue
        elif not eligible(dd, iid, prof, pop):
            continue
        names_seen.add(info["name"])
        (boots_c if info["boots"] else cands).append(iid)

    needs_left = dict(needs)
    used_groups = set()
    plan = []
    for i in owned_items:
        plan.append({"id": i, "owned": True})
        used_groups |= _groups(dd, i)
        for t in dd.items[i].get("tags", ()):
            if t in needs_left:
                needs_left[t] *= 0.3
    while len(plan) < n_items:
        first = not plan
        best, best_s = None, -9
        for iid in cands:
            if any(p["id"] == iid for p in plan) or _groups(dd, iid) & used_groups:
                continue
            s = _score(dd, iid, prof, pop, needs_left, first, core, core_w, pop_w)
            if s > best_s:
                best, best_s = iid, s
        if best is None:
            break
        plan.append({"id": best, "owned": False, "reasons": _reasons(dd, best, needs_left, prof)})
        used_groups |= _groups(dd, best)
        for t in dd.items[best].get("tags", ()):
            if t in needs_left:
                needs_left[t] *= 0.3

    # botas según la partida
    if owned_boots:
        boots = {"id": owned_boots, "owned": True}
    else:
        def bscore(b):
            info = dd.items[b]
            s = 0.8 * pop.get(b, {}).get("share", 0) * pop_w + 0.3 * fit(dd, b, prof)
            for t in info.get("tags", ()):
                s += needs.get(t, 0) * TAG_WEIGHT.get(t, 0) * 1.3
            return s
        bb = max(boots_c, key=bscore) if boots_c else None
        boots = {"id": bb, "owned": False, "reasons": _reasons(dd, bb, needs, prof)} if bb else None

    # la build "de siempre" (la más popular) para comparar
    standard = [it["id"] for it in (champ_meta or {}).get("items", [])[:5]]
    std_boot = ((champ_meta or {}).get("boots") or [{}])[0].get("id")
    plan_ids = [p["id"] for p in plan]
    removed = [i for i in standard if i not in plan_ids]
    changes = []
    for p in plan:
        if not p["owned"] and p["id"] not in standard and p.get("reasons"):
            changes.append({"add": p["id"], "remove": removed.pop(0) if removed else None, "reasons": p["reasons"]})
    if boots and not boots["owned"] and std_boot and boots["id"] != std_boot and boots.get("reasons"):
        changes.append({"add": boots["id"], "remove": std_boot, "reasons": boots["reasons"]})

    # próxima compra: el siguiente ítem del plan + 2 alternativas
    next_items = [p for p in plan if not p["owned"]]
    if boots and not boots["owned"] and len(owned_items) >= 1:
        next_items.insert(1, boots)
    primary = next_items[0] if next_items else None
    alts = []
    if primary:
        scored = sorted((c for c in cands if c != primary["id"] and c not in owned
                         and not (_groups(dd, c) & (used_groups - _groups(dd, primary["id"])))),
                        key=lambda c: -_score(dd, c, prof, pop, needs, False, core, core_w, pop_w))
        for c in scored[:2]:
            alts.append({"id": c, "owned": False, "reasons": _reasons(dd, c, needs, prof)})
    return {"plan": plan, "boots": boots, "standard": standard, "std_boot": std_boot, "changes": changes,
            "next": [primary] + alts if primary else [], "shopping": shopping(dd, primary["id"], me["items"], gold_now)
            if primary else None}


def shopping(dd, iid, inventory, gold):
    """Qué te conviene comprar ahora con el oro que tenés, camino al ítem."""
    inv = Counter(inventory)
    info = dd.items.get(iid, {})
    have = Counter()
    def owned_parts(i):
        for c in dd.items.get(i, {}).get("from", []):
            if inv[c] - have[c] > 0:
                have[c] += 1
            else:
                owned_parts(c)
    owned_parts(iid)
    discount = sum(dd.items.get(c, {}).get("gold", 0) * n for c, n in have.items())
    cost = info.get("gold", 0) - discount
    if gold >= cost:
        return {"complete": True, "cost": cost, "buy": [], "left": gold - cost}
    buy, g = [], gold
    used = Counter(have)
    def pick(i):
        nonlocal g
        for c in sorted(dd.items.get(i, {}).get("from", []), key=lambda c: -dd.items.get(c, {}).get("gold", 0)):
            if inv[c] - used[c] > 0:
                used[c] += 1
                continue
            cg = dd.items.get(c, {}).get("gold", 0)
            if cg and cg <= g:
                buy.append(c)
                g -= cg
            elif dd.items.get(c, {}).get("from"):
                pick(c)
    pick(iid)
    return {"complete": False, "cost": cost, "buy": buy, "left": g}


# ---------------------------------------------------------------- novedades durante la partida
class GameTracker:
    """Detecta cambios entre una lectura y la siguiente: ítems nuevos de los rivales, rachas, etc."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.prev_items, self.prev_kills, self.events, self.last_time = {}, {}, [], -1
        self.prev_alerts, self.announced = set(), set()
        self.prev_plan, self.last_cause = None, None

    def update(self, t, enemies, report, dd, lane=None, me=None):
        if t < self.last_time - 5:
            self.reset()
        first = self.last_time < 0
        self.last_time = t
        stamp = f"{int(t // 60)}:{int(t % 60):02d}"
        for p in enemies:
            name = dd.champ_name(p["cid"])
            done = [i for i in p["items"] if dd.items.get(i, {}).get("completed") and not dd.items[i]["boots"]]
            before = self.prev_items.get(p["cid"])
            if before is not None and not first:
                for i in done:
                    if i not in before:
                        extra = f" ({len(done)}° ítem)" if len(done) >= 2 else ""
                        self._add(stamp, "item", f"{name} completó {dd.item_name(i)}{extra}", i)
                        self.last_cause = f"{name} compró {dd.item_name(i)}"
                k0 = self.prev_kills.get(p["cid"], p["k"])
                if p["k"] - k0 >= 2:
                    self._add(stamp, "fed", f"{name} sumó {p['k'] - k0} kills: va {p['k']}/{p['d']}/{p['a']}")
                    self.prev_kills[p["cid"]] = p["k"]
            self.prev_items[p["cid"]] = done
            self.prev_kills.setdefault(p["cid"], p["k"])
        now = {a["key"] for a in report["alerts"] if a["level"] == "alta"}
        if not first:
            for a in report["alerts"]:
                if (a["level"] == "alta" and a["key"] not in self.prev_alerts and a["key"] != "dmg"
                        and a["key"] not in self.announced):
                    self.announced.add(a["key"])
                    self._add(stamp, "alert", f"Nuevo: {a['text'].lower()}" + (f" — {a['detail']}" if a["detail"] else ""))
        self.prev_alerts = now
        return self.events[-8:][::-1]

    def plan_changed(self, t, plan_ids, reasons_by_id, dd, owned=()):
        """Avisa cuando la build sugerida cambia por algo que pasó en la partida."""
        stamp = f"{int(t // 60)}:{int(t % 60):02d}"
        prev, self.prev_plan = self.prev_plan, list(plan_ids)
        if prev is None:
            return
        added = [i for i in plan_ids if i not in prev and i not in owned]
        removed = [i for i in prev if i not in plan_ids and i not in owned]
        if not added:
            return
        txt = "Tu build cambió: entra " + ", ".join(dd.item_name(i) for i in added)
        if removed:
            txt += " por " + ", ".join(dd.item_name(i) for i in removed)
        why = [r for i in added for r in reasons_by_id.get(i, [])]
        if self.last_cause:
            txt += f" (porque {self.last_cause})"
        elif why:
            txt += f" ({why[0]})"
        self._add(stamp, "plan", txt)

    def _add(self, stamp, kind, text, item=None):
        self.events.append({"t": stamp, "kind": kind, "text": text, "item": item})
