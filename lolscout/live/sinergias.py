"""Sinergias con el resto de tu equipo (no solo la dupla del bot).

Dos cosas:
  1) combos conocidos entre campeones de distintas líneas (Yasuo con los que levantan por el aire,
     Orianna con los que entran, las definitivas globales que se juntan, etc.);
  2) lo que le falta a tu equipo según lo que ya eligieron (o marcaron) tus aliados: alguien que
     arranque las peleas, una primera línea, o el tipo de daño que no tienen.
Se cuenta a los aliados que ya bloquearon y a los que solo lo tienen marcado.
"""

# Grupos de campeones (alias de Data Dragon en minúscula)
LEVANTAN = {"malphite", "alistar", "gragas", "rakan", "wukong", "jarvaniv", "nautilus", "rell", "sion", "chogath",
            "ornn", "zac", "vi", "leesin", "janna", "xinzhao", "yone", "yasuo", "gnar", "poppy", "reksai"}
ENTRAN = {"malphite", "jarvaniv", "wukong", "vi", "zac", "nocturne", "rakan", "hecarim", "amumu", "sejuani", "camille",
          "diana", "leona", "rell", "sion", "ornn", "galio", "kennen", "sett", "nautilus", "maokai"}
AREA_GRANDE = {"missfortune", "orianna", "kennen", "seraphine", "amumu", "malphite", "sona", "neeko", "fiddlesticks",
               "karthus", "yasuo", "wukong", "jarvaniv", "galio", "rumble", "brand", "zyra"}
GLOBALES = {"twistedfate", "nocturne", "shen", "pantheon", "taliyah", "galio", "karthus", "soraka", "ryze"}
PROTEGEN = {"lulu", "janna", "yuumi", "milio", "taric", "shen", "zilean", "soraka", "karma", "renata", "braum", "kayle"}
HIPER = {"masteryi", "kayle", "jax", "tryndamere", "twitch", "kogmaw", "jinx", "vayne", "aphelios", "zeri", "belveth",
         "kassadin", "smolder", "nilah", "irelia", "fiora", "gwen"}

# Combos: (grupo o alias A, grupo o alias B, explicación con {a} y {b})
COMBOS = [
    ({"yasuo", "yone"}, LEVANTAN - {"yasuo", "yone"},
     "{b} levanta por el aire a los rivales y {a} les tira la definitiva encima."),
    ({"orianna"}, ENTRAN - {"orianna"},
     "Orianna le pega la bola a {b}: cuando {b} entra, la definitiva de Orianna agarra a todos."),
    ({"missfortune"}, {"amumu", "malphite", "leona", "seraphine", "jarvaniv", "galio", "sona", "neeko", "rell", "wukong",
                       "sejuani", "maokai"},
     "{b} deja quieto al equipo rival y Miss Fortune tira la definitiva entera."),
    ({"galio"}, {"nocturne", "camille", "vi", "jarvaniv", "hecarim", "diana", "rengar", "khazix", "leesin", "wukong"},
     "Galio cae con su definitiva donde entra {b}: llegan juntos a la pelea."),
    (GLOBALES, GLOBALES,
     "{a} y {b} tienen definitiva global: aparecen juntos en cualquier línea y ganan esa pelea."),
    ({"jarvaniv"}, {"orianna", "missfortune", "galio", "kennen", "karthus", "brand", "zyra", "seraphine", "rumble"},
     "La definitiva de Jarvan encierra a los rivales y {b} les tira todo su daño en área."),
    ({"amumu"}, {"kennen", "orianna", "karthus", "brand", "zyra", "seraphine", "rumble", "fiddlesticks"},
     "Amumu inmoviliza a todos con su definitiva y {b} les tira el daño en área."),
    ({"taric"}, {"masteryi", "nilah", "irelia", "jax", "belveth", "tryndamere", "fiora", "camille"},
     "La definitiva de Taric deja a {b} invulnerable justo cuando entra a pelear."),
    ({"lulu"}, HIPER - {"lulu"},
     "Lulu agranda y acelera a {b}: se vuelve casi imposible de matar."),
    ({"kalista"}, {"sion", "alistar", "thresh", "nautilus", "rell", "leona", "malphite", "renata"},
     "La definitiva de Kalista lanza a {b} encima de los rivales."),
    ({"zilean"}, HIPER - {"zilean"},
     "La definitiva de Zilean revive a {b}: puede entrar a pelear sin miedo."),
    ({"kennen"}, {"jarvaniv", "amumu", "zac", "sejuani", "malphite", "rakan"},
     "{b} junta a los rivales y Kennen entra con su definitiva a aturdir a todos."),
]


def _names(dd, cid):
    """Todas las formas de nombrar al campeón (Wukong en los datos del juego se llama «MonkeyKing»)."""
    ch = dd.champions.get(cid, {})
    out = {(ch.get("alias") or "").lower(),
           (ch.get("name") or "").lower().replace(" ", "").replace("'", "").replace(".", "").replace("&", "")}
    img = dd.champ_img(cid) or ""
    out.add(img.rsplit("/", 1)[-1].replace(".png", "").lower())
    return out - {""}


def _alias(dd, cid):
    n = _names(dd, cid)
    return "wukong" if "wukong" in n else min(n, key=len) if n else ""


def _ap_ratio(dd, cid):
    info = dd.champions.get(cid, {}).get("info", {})
    ap, ad = info.get("magic", 5), info.get("attack", 5)
    return ap / max(ap + ad, 1)


def combos_with(dd, cid, ally_cids):
    """Combos conocidos entre este campeón y tus aliados: [(aliado, explicación)]."""
    me = _names(dd, cid)
    out = []
    for ally in ally_cids:
        other = _names(dd, ally)
        if not ally or ally == cid:
            continue
        for a, b, texto in COMBOS:
            if me & a and other & b:
                out.append((ally, texto.format(a=dd.champ_name(cid), b=dd.champ_name(ally))))
                break
            if other & a and me & b:
                out.append((ally, texto.format(a=dd.champ_name(ally), b=dd.champ_name(cid))))
                break
    return out


def team_needs(dd, cid, ally_cids):
    """Lo que le falta a tu equipo y este campeón le da. Devuelve (puntos, motivos)."""
    mine = [c for c in ally_cids if c]
    if len(mine) < 2:
        return 0.0, []
    ch = dd.champions.get(cid, {})
    tags = ch.get("tags", [])
    pts, why = 0.0, []
    tiene_tanque = any("Tank" in dd.champions.get(c, {}).get("tags", []) for c in mine)
    if not tiene_tanque and "Tank" in tags:
        pts += 0.008
        why.append("tu equipo todavía no tiene un tanque")
    tiene_engage = any(_names(dd, c) & ENTRAN for c in mine)
    if not tiene_engage and _names(dd, cid) & ENTRAN and len(mine) >= 3:
        pts += 0.007
        why.append("nadie de tu equipo arranca las peleas: vos podés")
    ap = [_ap_ratio(dd, c) for c in mine]
    prom = sum(ap) / len(ap)
    if prom < 0.35 and _ap_ratio(dd, cid) > 0.6:
        pts += 0.008
        why.append("tu equipo es casi todo daño físico: le suma daño mágico")
    elif prom > 0.65 and _ap_ratio(dd, cid) < 0.4:
        pts += 0.008
        why.append("tu equipo es casi todo daño mágico: le suma daño físico")
    return pts, why


def ally_synergy(dd, cid, ally_cids, combo_cids=None):
    """Sinergia con tus aliados (combos + lo que le falta al equipo). Devuelve (puntos, motivos, hay_combo).

    combo_cids: con quiénes buscar combos (por defecto, todos los aliados). La dupla del bot se deja
    afuera porque ya la mira duos.py.
    """
    combos = combos_with(dd, cid, ally_cids if combo_cids is None else combo_cids)
    pts, why = team_needs(dd, cid, ally_cids)
    for i, (_, texto) in enumerate(combos[:2]):
        pts += 0.02 if i == 0 else 0.01
        why.insert(i, texto)
    return pts, why, bool(combos)
