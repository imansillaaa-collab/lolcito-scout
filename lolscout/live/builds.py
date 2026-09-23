"""Qué arma cada campeón cuando todavía no hay estadísticas suficientes.

Las etiquetas de Riot (Data Dragon) no alcanzan para armar una build: a Malphite lo etiqueta
"Tanque + Mago" y a Teemo "Tirador", así que un plan B basado solo en eso termina recomendando
Sombrero de Rabadon a un tanque. Acá está, campeón por campeón, el tipo de build que arma de verdad.

Esto es solo el punto de partida: cuando las estadísticas tienen suficientes partidas de ese campeón,
mandan ellas (ver champion_profile en gameplan.py, que mezcla las dos según cuántas partidas hay).
"""

# Peso de cada estadística (0 a 1) según el tipo de build
ARCHETYPES = {
    # --- tanques
    "tanque":       {"hp": 1.0, "armor": .85, "mr": .85, "ah": .6, "ten": .4, "hregen": .25, "ad": .38, "ap": .34},
    "tanque_ap":    {"hp": 1.0, "armor": .8, "mr": .8, "ah": .65, "ap": .55, "mpen": .3, "ten": .35},
    "tanque_sup":   {"hp": 1.0, "armor": .8, "mr": .8, "ah": .7, "hsp": .45, "ten": .35, "ap": .35, "ad": .3},
    # --- peleadores
    "peleador":     {"ad": 1.0, "hp": .8, "ah": .7, "armor": .45, "mr": .45, "as": .5, "ls": .35},
    "peleador_ap":  {"ap": 1.0, "hp": .8, "ah": .7, "mpen": .5, "armor": .4, "mr": .4, "ov": .35},
    "coloso":       {"ad": 1.0, "hp": .9, "ah": .6, "armor": .45, "mr": .45, "ls": .4, "ten": .3},
    "duelista":     {"ad": 1.0, "crit": .9, "as": .8, "ah": .4, "ls": .4, "hp": .35},
    # --- magos
    "mago":         {"ap": 1.0, "mpen": .7, "ah": .75, "mana": .45, "hp": .3},
    "mago_burst":   {"ap": 1.0, "mpen": .8, "ah": .6, "mana": .3, "hp": .25},
    "mago_ataque":  {"ap": 1.0, "as": .85, "ah": .55, "mpen": .45, "hp": .3},
    # --- asesinos
    "asesino":      {"ad": 1.0, "leth": .9, "ah": .6, "crit": .35, "ms": .3},
    "asesino_ap":   {"ap": 1.0, "mpen": .8, "ah": .6, "ms": .3, "hp": .25},
    # --- tiradores
    "tirador":      {"ad": 1.0, "crit": .95, "as": .85, "arpen": .5, "ls": .4, "ms": .3},
    "tirador_golpe": {"as": 1.0, "ad": .9, "crit": .55, "ls": .45, "arpen": .4, "hp": .3},
    # --- supports
    "encantador":   {"ah": 1.0, "hsp": .95, "ap": .6, "mregen": .6, "ms": .5, "hp": .4, "mana": .4},
}

# Campeón (alias de Data Dragon) -> tipo de build
CHAMPS = {
    "Aatrox": "coloso", "Ahri": "mago_burst", "Akali": "asesino_ap", "Akshan": "tirador",
    "Alistar": "tanque_sup", "Ambessa": "peleador", "Amumu": "tanque_ap", "Anivia": "mago",
    "Annie": "mago_burst", "Aphelios": "tirador", "Ashe": "tirador", "AurelionSol": "mago",
    "Aurora": "mago_burst", "Azir": "mago", "Bard": "encantador", "Belveth": "tirador_golpe",
    "Blitzcrank": "tanque_sup", "Brand": "mago", "Braum": "tanque_sup", "Briar": "peleador",
    "Caitlyn": "tirador", "Camille": "peleador", "Cassiopeia": "mago", "Chogath": "tanque_ap",
    "Corki": "tirador", "Darius": "coloso", "Diana": "peleador_ap", "DrMundo": "tanque",
    "Draven": "tirador", "Ekko": "asesino_ap", "Elise": "peleador_ap", "Evelynn": "asesino_ap",
    "Ezreal": "tirador", "Fiddlesticks": "mago", "Fiora": "peleador", "Fizz": "asesino_ap",
    "Galio": "tanque_ap", "Gangplank": "duelista", "Garen": "coloso", "Gnar": "peleador",
    "Gragas": "peleador_ap", "Graves": "tirador", "Gwen": "peleador_ap", "Hecarim": "peleador",
    "Heimerdinger": "mago", "Hwei": "mago", "Illaoi": "coloso", "Irelia": "peleador",
    "Ivern": "encantador", "Janna": "encantador", "JarvanIV": "peleador", "Jax": "peleador",
    "Jayce": "peleador", "Jhin": "tirador", "Jinx": "tirador", "KSante": "tanque",
    "Kaisa": "tirador", "Kalista": "tirador", "Karma": "encantador", "Karthus": "mago",
    "Kassadin": "asesino_ap", "Katarina": "asesino_ap", "Kayle": "mago_ataque", "Kayn": "peleador",
    "Kennen": "mago", "Khazix": "asesino", "Kindred": "tirador", "Kled": "peleador",
    "KogMaw": "tirador_golpe", "Leblanc": "asesino_ap", "LeeSin": "peleador", "Leona": "tanque_sup",
    "Lillia": "peleador_ap", "Lissandra": "mago_burst", "Lucian": "tirador", "Lulu": "encantador",
    "Lux": "mago_burst", "Malphite": "tanque_ap", "Malzahar": "mago", "Maokai": "tanque_ap",
    "MasterYi": "duelista", "Milio": "encantador", "MissFortune": "tirador",
    "MonkeyKing": "peleador", "Mordekaiser": "peleador_ap", "Morgana": "mago", "Naafiri": "asesino",
    "Nami": "encantador", "Nasus": "coloso", "Nautilus": "tanque_sup", "Neeko": "mago_burst",
    "Nidalee": "mago_burst", "Nilah": "tirador", "Nocturne": "asesino", "Nunu": "tanque_ap",
    "Olaf": "peleador", "Orianna": "mago", "Ornn": "tanque", "Pantheon": "peleador",
    "Poppy": "tanque", "Pyke": "asesino", "Qiyana": "asesino", "Quinn": "tirador",
    "Rakan": "encantador", "Rammus": "tanque", "RekSai": "peleador", "Rell": "tanque_sup",
    "Renata": "encantador", "Renekton": "peleador", "Rengar": "asesino", "Riven": "peleador",
    "Rumble": "peleador_ap", "Ryze": "mago", "Samira": "tirador", "Sejuani": "tanque",
    "Senna": "tirador", "Seraphine": "encantador", "Sett": "coloso", "Shaco": "asesino",
    "Shen": "tanque", "Shyvana": "peleador", "Singed": "tanque_ap", "Sion": "tanque",
    "Sivir": "tirador", "Skarner": "tanque", "Smolder": "tirador", "Sona": "encantador",
    "Soraka": "encantador", "Swain": "peleador_ap", "Sylas": "peleador_ap", "Syndra": "mago_burst",
    "TahmKench": "tanque", "Taliyah": "mago", "Talon": "asesino", "Taric": "tanque_sup",
    "Teemo": "mago_ataque", "Thresh": "tanque_sup", "Tristana": "tirador", "Trundle": "coloso",
    "Tryndamere": "duelista", "TwistedFate": "mago", "Twitch": "tirador", "Udyr": "peleador",
    "Urgot": "coloso", "Varus": "tirador", "Vayne": "tirador_golpe", "Veigar": "mago",
    "Velkoz": "mago", "Vex": "mago_burst", "Vi": "peleador", "Viego": "peleador",
    "Viktor": "mago", "Vladimir": "peleador_ap", "Volibear": "coloso", "Warwick": "peleador",
    "Xayah": "tirador", "Xerath": "mago", "XinZhao": "peleador", "Yasuo": "duelista",
    "Yone": "duelista", "Yorick": "coloso", "Yuumi": "encantador", "Zac": "tanque_ap",
    "Zed": "asesino", "Zeri": "tirador", "Ziggs": "mago", "Zilean": "encantador",
    "Zoe": "mago_burst", "Zyra": "mago",
}

# Ítems típicos de cada tipo de build (los primeros que se compran). Solo se usan mientras no haya
# suficientes partidas de ese campeón en las estadísticas; sirven para que el primer ítem no sea
# siempre el más "eficiente en oro" (un Sombrero de Rabadon de primer ítem, por ejemplo).
CORE = {
    "tanque":       (3068, 3084, 3083, 3742, 3143, 3075, 6665, 8020, 3193),
    "tanque_ap":    (3068, 6662, 8020, 6653, 4633, 3116, 3084),
    "tanque_sup":   (3190, 3109, 3050, 2524, 3742, 8020, 6665, 3068),
    "peleador":     (3078, 3748, 6333, 3161, 6631, 6609, 3053, 3071),
    "peleador_ap":  (4633, 3152, 6653, 3116, 8010, 2510),
    "coloso":       (6609, 3748, 3161, 3053, 3074, 3071, 3181, 6333),
    "duelista":     (6673, 3153, 6675, 3046, 3085),
    "mago":         (6655, 3118, 4646, 4628, 3116, 6653, 3135),
    "mago_burst":   (6655, 4645, 3152, 4646, 3118),
    "mago_ataque":  (3115, 3124, 6653, 3135),
    "asesino":      (3142, 6692, 6699, 6676, 3814, 6698, 6694, 6695),
    "asesino_ap":   (3152, 4645, 6655, 4646),
    "tirador":      (6672, 6676, 3094, 3085, 3153, 6673, 3046),
    "tirador_golpe": (3153, 3124, 3302, 3091, 3085, 6672, 3046),
    "encantador":   (6617, 6620, 3222, 3107, 2065, 6616, 4005, 3504),
}

# Para un campeón nuevo que todavía no está en la lista: según sus etiquetas (la primera pesa más)
BY_TAG = {
    "Marksman": {"ad": 1, "as": .85, "crit": .9, "arpen": .5, "ls": .35},
    "Mage": {"ap": 1, "mpen": .7, "ah": .7, "mana": .4},
    "Assassin": {"ad": 1, "leth": .8, "ah": .5, "ms": .3},
    "Fighter": {"ad": 1, "hp": .75, "ah": .65, "armor": .35, "mr": .35, "as": .45},
    "Tank": {"hp": 1, "armor": .85, "mr": .85, "ah": .55, "ten": .35},
    "Support": {"ah": .9, "hsp": .85, "ap": .55, "mregen": .55, "hp": .4},
}
TAG_WEIGHT = (1.0, 0.5)


def archetype(dd, cid) -> str:
    return CHAMPS.get(dd.champions.get(cid, {}).get("alias", ""), "")


def core_items(dd, cid) -> set:
    """Ítems típicos del tipo de build de ese campeón (vacío si no lo tenemos en la lista)."""
    return set(CORE.get(archetype(dd, cid), ()))


def base_profile(dd, cid) -> dict:
    """Perfil de estadísticas del campeón sin mirar estadísticas de partidas."""
    name = archetype(dd, cid)
    if name:
        prof = dict(ARCHETYPES[name])
    else:
        prof = {}
        for i, t in enumerate(dd.champions.get(cid, {}).get("tags", [])[:2]):
            for k, v in BY_TAG.get(t, {}).items():
                prof[k] = max(prof.get(k, 0), v * TAG_WEIGHT[i])
    kit = dd.champions.get(cid, {}).get("kit", {})
    if kit.get("as_scaling") and prof.get("as"):
        prof["as"] = min(1.0, prof["as"] + 0.1)
    if kit.get("hp_scaling"):
        prof["hp"] = min(1.0, prof.get("hp", 0) + 0.25)
    return prof


def damage_type(dd, cid, prof, phys, mag) -> str:
    """Si la build no lo deja claro (tanques), lo decide el texto de las habilidades del campeón."""
    if abs(phys - mag) >= 0.3:
        return "magic" if mag > phys else "physical"
    kind = dd.champions.get(cid, {}).get("kit", {}).get("dmgtype")
    if kind:
        return kind
    return "magic" if mag > phys else "physical"
