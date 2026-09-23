"""Duplas del carril inferior: qué ADC / support combina con el compañero que ya eligió (o marcó) tu aliado.

Mezcla dos cosas:
  1) los datos del parche (winrate de cada dupla en tu rango), cuando hay suficientes partidas;
  2) cómo encajan los estilos (un ADC de pelea corta quiere un support que enganche, un ADC que escala
     quiere uno que lo proteja, uno de rango quiere uno que pegue de lejos) y los combos conocidos.
Los datos de duplas todavía son pocos, así que el estilo pesa bastante hasta que crezca la base.
"""

# Estilo de cada ADC (alias de Data Dragon en minúscula)
ADC_STYLE = {
    "pelea": {"draven", "lucian", "samira", "kalista", "tristana", "nilah", "missfortune", "kaisa", "xayah"},
    "escala": {"jinx", "kogmaw", "twitch", "aphelios", "zeri", "vayne", "smolder", "yunara"},
    "rango": {"caitlyn", "ezreal", "varus", "jhin", "ashe", "sivir", "corki", "senna", "mel"},
}
# Estilo de cada support
SUP_STYLE = {
    "engage": {"leona", "nautilus", "rell", "alistar", "thresh", "rakan", "blitzcrank", "pyke", "amumu",
               "maokai", "poppy", "elise"},
    "protege": {"lulu", "janna", "nami", "milio", "soraka", "yuumi", "sona", "renata", "taric", "braum",
                "tahmkench", "karma", "seraphine"},
    "poke": {"lux", "xerath", "zyra", "brand", "velkoz", "morgana", "swain", "hwei", "neeko", "zilean",
             "karma", "seraphine", "bard"},
}
# Qué tan bien encaja cada estilo de ADC con cada estilo de support (0 a 1)
FIT = {
    ("pelea", "engage"): 1.0, ("pelea", "protege"): 0.5, ("pelea", "poke"): 0.3,
    ("escala", "protege"): 1.0, ("escala", "engage"): 0.5, ("escala", "poke"): 0.3,
    ("rango", "poke"): 1.0, ("rango", "protege"): 0.6, ("rango", "engage"): 0.4,
}
FIT_WHY = {
    ("pelea", "engage"): "{adc} quiere pelear corto y {sup} engancha: juntos ganan las peleas de nivel 2 y 3.",
    ("escala", "protege"): "{adc} necesita llegar vivo a los ítems y {sup} lo protege en la línea y en las peleas.",
    ("rango", "poke"): "Los dos pegan de lejos: bajan al rival antes de que pueda entrar.",
}

# Combos conocidos: (adc, support) -> por qué
COMBOS = {
    ("lucian", "nami"): "La E de Nami se aplica a los dos disparos de la pasiva de Lucian: mucho daño en poco tiempo.",
    ("lucian", "braum"): "Cada disparo doble de Lucian carga la pasiva de Braum y aturde rápido.",
    ("xayah", "rakan"): "Vuelven a base juntos y se potencian: Rakan entra y Xayah remata con sus plumas.",
    ("kalista", "thresh"): "La R de Kalista lanza a Thresh encima del rival y el farol lo saca si sale mal.",
    ("kalista", "renata"): "La R de Kalista lanza a Renata al medio de la pelea para tirar su definitiva.",
    ("kalista", "alistar"): "La R de Kalista lanza a Alistar y el combo de W+Q sale seguro.",
    ("kalista", "nautilus"): "La R de Kalista lanza a Nautilus al medio: engage casi imposible de esquivar.",
    ("samira", "nautilus"): "Cada control de Nautilus deja al rival quieto y Samira salta encima para rematar.",
    ("samira", "rell"): "Rell junta a todos y Samira entra con su definitiva al medio.",
    ("samira", "leona"): "Leona inmoviliza y Samira salta encima: combo de nivel 2 muy fuerte.",
    ("samira", "alistar"): "Alistar levanta a los rivales y Samira salta encima para rematar.",
    ("draven", "leona"): "Draven quiere pelear desde el minuto uno y Leona le arma las peleas.",
    ("draven", "nautilus"): "Nautilus engancha y Draven hace el daño con las hachas cargadas.",
    ("draven", "thresh"): "Thresh engancha con la Q y Draven castiga: dupla agresiva clásica.",
    ("tristana", "leona"): "Leona engancha y Tristana salta con la carga de la E.",
    ("tristana", "nautilus"): "Nautilus engancha y Tristana revienta con la E cargada.",
    ("missfortune", "leona"): "Leona deja al equipo rival quieto y Miss Fortune tira la definitiva entera.",
    ("missfortune", "amumu"): "Amumu inmoviliza a todos con su definitiva y Miss Fortune tira la suya.",
    ("missfortune", "seraphine"): "La definitiva de Seraphine deja a varios quietos: Miss Fortune tira la suya.",
    ("kaisa", "nautilus"): "Kai'Sa carga su pasiva sobre los rivales que Nautilus inmoviliza y entra con la R.",
    ("kaisa", "alistar"): "Alistar engancha y Kai'Sa entra con la R detrás.",
    ("kaisa", "rakan"): "Rakan engancha y Kai'Sa entra con la R detrás.",
    ("nilah", "taric"): "Nilah potencia las curas y escudos que recibe: con Taric es casi inmortal.",
    ("nilah", "soraka"): "Nilah potencia las curas que recibe: Soraka la mantiene viva en la pelea.",
    ("nilah", "milio"): "Nilah potencia los escudos y curas de Milio.",
    ("jinx", "thresh"): "Thresh engancha o la salva con el farol, y Jinx limpia la pelea.",
    ("jinx", "lulu"): "Lulu la protege y le da velocidad de ataque con la W.",
    ("jinx", "janna"): "Janna saca de encima a los que entran sobre Jinx.",
    ("kogmaw", "lulu"): "La dupla clásica: Lulu agranda y acelera a Kog'Maw y él derrite todo.",
    ("kogmaw", "braum"): "Braum se para delante y bloquea lo que le tiran a Kog'Maw.",
    ("twitch", "lulu"): "Lulu protege a Twitch y le da velocidad de ataque cuando sale del sigilo.",
    ("twitch", "yuumi"): "Yuumi viaja con Twitch invisible: aparecen juntos donde nadie espera.",
    ("zeri", "lulu"): "Lulu la escuda y acelera: Zeri se mueve y pega sin parar.",
    ("zeri", "yuumi"): "Yuumi la escuda mientras Zeri se mueve por toda la pelea.",
    ("zeri", "milio"): "Milio le da alcance y escudos: Zeri pega de más lejos.",
    ("aphelios", "thresh"): "Thresh engancha y Aphelios castiga con el arma que tenga cargada.",
    ("aphelios", "lulu"): "Lulu protege a Aphelios, que no tiene cómo escapar solo.",
    ("vayne", "lulu"): "Lulu protege a Vayne, que es muy débil al principio, hasta que escala.",
    ("vayne", "janna"): "Janna saca de encima a los que entran sobre Vayne.",
    ("smolder", "lulu"): "Lulu lo mantiene vivo mientras junta cargas.",
    ("smolder", "milio"): "Milio lo cura y le da alcance mientras junta cargas.",
    ("caitlyn", "lux"): "Caitlyn pone trampas debajo de los que Lux deja quietos: la línea es de ellos.",
    ("caitlyn", "morgana"): "Caitlyn pone trampas debajo de los que Morgana deja quietos.",
    ("caitlyn", "karma"): "Las dos pegan de lejos y Karma le da velocidad para acomodarse.",
    ("caitlyn", "xerath"): "Pegan de lejísimos: el rival no puede ni acercarse a la línea.",
    ("caitlyn", "zyra"): "Caitlyn pone trampas debajo de los que Zyra deja enraizados.",
    ("jhin", "zyra"): "La W de Jhin inmoviliza a los que Zyra acaba de golpear.",
    ("jhin", "morgana"): "Morgana deja quietos a los rivales y Jhin encadena su W.",
    ("jhin", "xerath"): "Pegan de lejísimos y Jhin encadena su W sobre los que golpea Xerath.",
    ("jhin", "lux"): "Lux deja quietos a los rivales y Jhin encadena su W.",
    ("ezreal", "karma"): "Los dos pegan de lejos y Karma le da velocidad para esquivar.",
    ("ezreal", "yuumi"): "Yuumi lo escuda y cura mientras Ezreal pega de lejos.",
    ("varus", "lux"): "Pegan de lejos y los controles se encadenan: la R de Varus sobre la Q de Lux.",
    ("varus", "karma"): "Pegan de lejos y Karma lo acelera para acomodarse.",
    ("ashe", "braum"): "Ashe ataca rápido y carga la pasiva de Braum: el aturdimiento sale enseguida.",
    ("ashe", "seraphine"): "Las definitivas de las dos encadenan controles de lejos.",
    ("sivir", "karma"): "Las dos aceleran al equipo: juntas eligen dónde pelear.",
    ("senna", "tahmkench"): "Tahm Kench se traga a Senna para salvarla cuando la agarran.",
    ("senna", "seraphine"): "Las dos pegan de lejos y curan al equipo.",
}


def _style(alias, table):
    return next((s for s, names in table.items() if alias in names), None)


def _alias(dd, cid):
    img = dd.champ_img(cid) or ""
    return img.rsplit("/", 1)[-1].replace(".png", "").lower()


def synergy(dd, adc_cid, sup_cid, duo_idx):
    """Qué tan bien combinan un ADC y un support. Devuelve (puntaje, motivos, datos)."""
    a, s = _alias(dd, adc_cid), _alias(dd, sup_cid)
    score, why = 0.0, []
    data = duo_idx.get((adc_cid, sup_cid))
    if data:
        peso = min(data["games"] / 25, 1.0)
        score += (data["adj"] - 0.5) * 0.8 * peso
        why.append(f"Juntos: {data['wr']*100:.0f}% en {data['games']} partidas de tu rango"
                   + (" (pocas)" if data["games"] < 15 else ""))
    combo = COMBOS.get((a, s))
    if combo:
        score += 0.025
        why.append(combo)
    sa, ss = _style(a, ADC_STYLE), _style(s, SUP_STYLE)
    if sa and ss:
        fit = FIT.get((sa, ss), 0.3)
        # Karma y Seraphine sirven como "protege" y como "poke": tomo el mejor encaje
        for other, names in SUP_STYLE.items():
            if s in names:
                fit = max(fit, FIT.get((sa, other), 0.3))
        score += (fit - 0.5) * 0.02
        if not combo and fit >= 1.0:
            ss_best = next(st for st, names in SUP_STYLE.items() if s in names and FIT.get((sa, st)) == 1.0)
            why.append(FIT_WHY[(sa, ss_best)].format(adc=dd.champ_name(adc_cid), sup=dd.champ_name(sup_cid)))
    return score, why, data


def partner_picks(dd, my_role, partner_cid, candidates, duo_idx, unavailable, limit=4):
    """Lista corta para tu rol (ADC o support) de lo que mejor combina con el compañero de tu aliado.

    candidates: las opciones del meta de tu rol (dicts con id, adj, games, tier).
    """
    out = []
    for c in candidates:
        cid = c["id"]
        if cid in unavailable:
            continue
        adc, sup = (cid, partner_cid) if my_role == "BOTTOM" else (partner_cid, cid)
        s, why, data = synergy(dd, adc, sup, duo_idx)
        if not why:
            continue
        # que también sea bueno en el parche: un combo perfecto con un campeón flojo no sirve
        meta = (c.get("adj", 0.5) - 0.5) * min(c.get("games", 0) / 60, 1.0)
        out.append({"id": cid, "name": dd.champ_name(cid), "img": dd.champ_img(cid), "tier": c.get("tier", "?"),
                    "score": s + meta * 0.5, "why": why, "combo": (_alias(dd, adc), _alias(dd, sup)) in COMBOS,
                    "duoWr": data["wr"] if data else None, "duoGames": data["games"] if data else 0})
    out.sort(key=lambda o: -o["score"])
    for o in out:
        o.pop("score")
    return out[:limit]
