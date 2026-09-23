"""Runas y hechizos de invocador para la partida que estás por jugar.

Arma 2 o 3 páginas completas (árbol principal + secundario + fragmentos) y explica por qué cada una:
- "Para este rival": la página base del campeón, retocada según lo que ya pickeó el equipo rival
  (mucho control, asesinos, tanques, un rival de línea a distancia que te castiga, etc.).
- "La de siempre": lo que arma habitualmente ese tipo de campeón, con la runa clave que más se usa
  en tu rango cuando las estadísticas tienen suficientes partidas suyas.
- "Alternativa": otra forma de jugarlo (más agresiva o más de escalado).

Todas las páginas se validan contra el árbol real del parche antes de mostrarlas, así nunca se manda
al cliente de LoL una combinación imposible.
"""
from . import builds

# --- árboles (los nombres salen de Data Dragon; acá van los números que usa el juego)
PRECISION, DOMINACION, BRUJERIA, VALOR, INSPIRACION = 8000, 8100, 8200, 8400, 8300

# Filas de fragmentos: ofensiva, flexible, defensiva
SHARD_ROWS = [(5008, 5005, 5007), (5008, 5010, 5001), (5011, 5013, 5001)]
ADAPTATIVO, AT_VEL, HASTE, MOV, VIDA_ESC, VIDA, TENACIDAD = 5008, 5005, 5007, 5010, 5001, 5011, 5013

# Runas clave
CONQUISTADOR, TEMPO_LETAL, GOLPE_OFENSIVO, PIE_LIGERO = 8010, 8008, 8005, 8021
ELECTROCUTAR, COSECHA, LLUVIA_ESPADAS = 8112, 8128, 9923
AERY, COMETA, CABALGATORMENTAS = 8214, 8229, 8230
AGARRE, REPLICA, GUARDIAN = 8437, 8439, 8465
AUMENTO_GLACIAL, PRIMER_GOLPE = 8351, 8369

# Runas menores que se usan en las variantes
TRIUNFO, ABSORBER, CONCENTRACION = 9111, 9101, 8009
LEY_CELERIDAD, LEY_ACELERACION, LEY_LINAJE = 9104, 9105, 9103
GOLPE_GRACIA, CORTE, ULTIMA_BATALLA = 8014, 8017, 8299
GOLPE_BAJO, SABOR_SANGRE, IMPACTO_SUBITO = 8126, 8139, 8143
SEXTO_SENTIDO, RECUERDOS, CENTINELA = 8137, 8140, 8141
CAZA_TESOROS, CAZA_IMPLACABLE, CAZA_DEFINITIVO = 8135, 8105, 8106
ARCANISTA, ANILLO_MANA, CAPA_NIMBO = 8224, 8226, 8275
TRASCENDENCIA, CELERIDAD, CONCENTRACION_ABS = 8210, 8234, 8233
QUEMADURA, CAMINATA, TORMENTA = 8237, 8232, 8236
DEMOLICION, FUENTE_VIDA, GOLPE_ESCUDO = 8446, 8463, 8401
ACONDICIONAMIENTO, SEGUNDO_AIRE, CORAZA_OSEA = 8429, 8444, 8473
CRECIMIENTO, REVITALIZAR, INQUEBRANTABLE = 8451, 8453, 8242
DESTELLO_HEXTECH, CALZADO, REEMBOLSO = 8306, 8304, 8321
TONICO_TRIPLE, TONICO_TIEMPO, GALLETAS = 8313, 8352, 8345
PERSPICACIA, APROXIMACION, COMODIN = 8347, 8410, 8316


def page(primary, keystone, p2, p3, p4, sub, s1, s2, shards):
    return {"primary": primary, "sub": sub, "perks": [keystone, p2, p3, p4, s1, s2], "shards": list(shards)}


# Página base y alternativa de cada tipo de campeón (ver builds.py para el tipo de cada uno)
PAGES = {
    "tanque": {
        "base": page(VALOR, AGARRE, DEMOLICION, SEGUNDO_AIRE, CRECIMIENTO,
                     INSPIRACION, CALZADO, PERSPICACIA, (HASTE, VIDA_ESC, VIDA)),
        "alt": page(VALOR, REPLICA, FUENTE_VIDA, CORAZA_OSEA, INQUEBRANTABLE,
                    PRECISION, TRIUNFO, LEY_ACELERACION, (HASTE, VIDA_ESC, VIDA)),
        "altName": "Para entrar primero",
        "altWhy": "Réplica te da resistencias justo cuando enganchás: es la de los tanques que abren la pelea.",
    },
    "tanque_ap": {
        "base": page(VALOR, REPLICA, FUENTE_VIDA, ACONDICIONAMIENTO, CRECIMIENTO,
                     BRUJERIA, ANILLO_MANA, TRASCENDENCIA, (ADAPTATIVO, VIDA_ESC, VIDA)),
        "alt": page(VALOR, AGARRE, DEMOLICION, SEGUNDO_AIRE, CRECIMIENTO,
                    BRUJERIA, ANILLO_MANA, TORMENTA, (ADAPTATIVO, VIDA_ESC, VIDA)),
        "altName": "Para aguantar la línea",
        "altWhy": "Agarre del Perpetuo te cura en cada intercambio y Demolición te da la torre.",
    },
    "tanque_sup": {
        "base": page(VALOR, REPLICA, FUENTE_VIDA, CORAZA_OSEA, INQUEBRANTABLE,
                     INSPIRACION, CALZADO, PERSPICACIA, (HASTE, VIDA_ESC, VIDA)),
        "alt": page(VALOR, GUARDIAN, FUENTE_VIDA, CORAZA_OSEA, REVITALIZAR,
                    INSPIRACION, GALLETAS, PERSPICACIA, (ADAPTATIVO, VIDA_ESC, VIDA)),
        "altName": "Para cuidar al ADC",
        "altWhy": "Guardián te deja tapar el enganche del rival en vez de empezarlo vos.",
    },
    "peleador": {
        "base": page(PRECISION, CONQUISTADOR, TRIUNFO, LEY_CELERIDAD, ULTIMA_BATALLA,
                     VALOR, CORAZA_OSEA, CRECIMIENTO, (AT_VEL, ADAPTATIVO, VIDA)),
        "alt": page(PRECISION, CONQUISTADOR, TRIUNFO, LEY_ACELERACION, GOLPE_GRACIA,
                    DOMINACION, SABOR_SANGRE, CAZA_TESOROS, (AT_VEL, ADAPTATIVO, VIDA)),
        "altName": "Para buscar kills",
        "altWhy": "Cazador de Tesoros te da oro extra por cada rival distinto que matás.",
    },
    "peleador_ap": {
        "base": page(PRECISION, CONQUISTADOR, CONCENTRACION, LEY_ACELERACION, ULTIMA_BATALLA,
                     BRUJERIA, TRASCENDENCIA, TORMENTA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "alt": page(BRUJERIA, COMETA, ANILLO_MANA, TRASCENDENCIA, TORMENTA,
                    INSPIRACION, GALLETAS, PERSPICACIA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "altName": "Para castigar de lejos",
        "altWhy": "Cometa Arcano te deja pegarle al rival cada vez que lo tocás con una habilidad.",
    },
    "coloso": {
        "base": page(PRECISION, CONQUISTADOR, TRIUNFO, LEY_CELERIDAD, ULTIMA_BATALLA,
                     VALOR, ACONDICIONAMIENTO, CRECIMIENTO, (AT_VEL, ADAPTATIVO, VIDA)),
        "alt": page(VALOR, AGARRE, DEMOLICION, SEGUNDO_AIRE, CRECIMIENTO,
                    PRECISION, TRIUNFO, LEY_ACELERACION, (HASTE, VIDA_ESC, VIDA)),
        "altName": "Para no perder la línea",
        "altWhy": "Agarre del Perpetuo te suma vida sola y aguanta mejor las líneas difíciles.",
    },
    "duelista": {
        "base": page(PRECISION, TEMPO_LETAL, TRIUNFO, LEY_CELERIDAD, GOLPE_GRACIA,
                     VALOR, CORAZA_OSEA, CRECIMIENTO, (AT_VEL, ADAPTATIVO, VIDA)),
        "alt": page(PRECISION, CONQUISTADOR, TRIUNFO, LEY_CELERIDAD, ULTIMA_BATALLA,
                    VALOR, CORAZA_OSEA, INQUEBRANTABLE, (AT_VEL, ADAPTATIVO, VIDA)),
        "altName": "Para peleas largas",
        "altWhy": "Conquistador rinde más si las peleas de tu equipo duran, en vez de ser un duelo corto.",
    },
    "mago": {
        "base": page(BRUJERIA, COMETA, ANILLO_MANA, TRASCENDENCIA, QUEMADURA,
                     INSPIRACION, GALLETAS, PERSPICACIA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "alt": page(BRUJERIA, COMETA, ANILLO_MANA, TRASCENDENCIA, TORMENTA,
                    PRECISION, CONCENTRACION, LEY_ACELERACION, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "altName": "Para escalar",
        "altWhy": "Tormenta Creciente te hace más fuerte solo con que la partida se alargue.",
    },
    "mago_burst": {
        "base": page(DOMINACION, ELECTROCUTAR, SABOR_SANGRE, RECUERDOS, CAZA_DEFINITIVO,
                     BRUJERIA, ANILLO_MANA, TRASCENDENCIA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "alt": page(BRUJERIA, COMETA, ANILLO_MANA, TRASCENDENCIA, QUEMADURA,
                    INSPIRACION, GALLETAS, PERSPICACIA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "altName": "Para castigar en línea",
        "altWhy": "Cometa y Quemadura te dan daño constante aunque no consigas matar.",
    },
    "mago_ataque": {
        "base": page(PRECISION, TEMPO_LETAL, TRIUNFO, LEY_CELERIDAD, GOLPE_GRACIA,
                     BRUJERIA, TRASCENDENCIA, TORMENTA, (AT_VEL, ADAPTATIVO, VIDA)),
        "alt": page(DOMINACION, COSECHA, SABOR_SANGRE, RECUERDOS, CAZA_DEFINITIVO,
                    BRUJERIA, ANILLO_MANA, TORMENTA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "altName": "Para escalar",
        "altWhy": "Cosecha Oscura se va acumulando toda la partida: rinde en las partidas largas.",
    },
    "asesino": {
        "base": page(DOMINACION, ELECTROCUTAR, IMPACTO_SUBITO, RECUERDOS, CAZA_IMPLACABLE,
                     PRECISION, TRIUNFO, GOLPE_GRACIA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "alt": page(DOMINACION, ELECTROCUTAR, IMPACTO_SUBITO, RECUERDOS, CAZA_DEFINITIVO,
                    PRECISION, CONCENTRACION, LEY_ACELERACION, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "altName": "Para usar más la definitiva",
        "altWhy": "Cazador Definitivo te baja el tiempo de tu definitiva con cada rival distinto que matás.",
    },
    "asesino_ap": {
        "base": page(DOMINACION, ELECTROCUTAR, IMPACTO_SUBITO, RECUERDOS, CAZA_DEFINITIVO,
                     BRUJERIA, TRASCENDENCIA, QUEMADURA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "alt": page(BRUJERIA, COMETA, ANILLO_MANA, TRASCENDENCIA, QUEMADURA,
                    DOMINACION, SABOR_SANGRE, CAZA_DEFINITIVO, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "altName": "Para castigar en línea",
        "altWhy": "Cometa Arcano te deja pelear la línea aunque no puedas matar todavía.",
    },
    "tirador": {
        "base": page(PRECISION, TEMPO_LETAL, TRIUNFO, LEY_CELERIDAD, GOLPE_GRACIA,
                     DOMINACION, SABOR_SANGRE, CAZA_TESOROS, (AT_VEL, ADAPTATIVO, VIDA)),
        "alt": page(PRECISION, GOLPE_OFENSIVO, TRIUNFO, LEY_CELERIDAD, GOLPE_GRACIA,
                    DOMINACION, SABOR_SANGRE, CAZA_TESOROS, (AT_VEL, ADAPTATIVO, VIDA)),
        "altName": "Para ganar los intercambios",
        "altWhy": "Estrategia Ofensiva pega fuerte cada tres golpes: bueno si querés pelear la línea desde temprano.",
    },
    "tirador_golpe": {
        "base": page(PRECISION, TEMPO_LETAL, TRIUNFO, LEY_CELERIDAD, GOLPE_GRACIA,
                     VALOR, CORAZA_OSEA, CRECIMIENTO, (AT_VEL, ADAPTATIVO, VIDA)),
        "alt": page(PRECISION, TEMPO_LETAL, ABSORBER, LEY_LINAJE, CORTE,
                    DOMINACION, SABOR_SANGRE, CAZA_TESOROS, (AT_VEL, ADAPTATIVO, VIDA)),
        "altName": "Contra mucha vida",
        "altWhy": "Corte y Leyenda: Linaje están pensados para bajar tanques.",
    },
    "encantador": {
        "base": page(BRUJERIA, AERY, ANILLO_MANA, TRASCENDENCIA, TORMENTA,
                     VALOR, FUENTE_VIDA, REVITALIZAR, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "alt": page(VALOR, GUARDIAN, FUENTE_VIDA, CORAZA_OSEA, REVITALIZAR,
                    BRUJERIA, ANILLO_MANA, TRASCENDENCIA, (ADAPTATIVO, ADAPTATIVO, VIDA)),
        "altName": "Para aguantar el enganche",
        "altWhy": "Guardián te deja tapar el enganche del rival, útil contra supports que te saltan encima.",
    },
}

# Si el campeón no está en la lista de arquetipos, se usa esta
DEFAULT = PAGES["peleador"]


# ---------------------------------------------------------------- hechizos de invocador
DESTELLO, CASTIGO, PRENDER, AGOTAR, BARRERA, CURAR, PURIFICAR, TELETRANSPORTE, FANTASMA = 4, 11, 14, 3, 21, 7, 1, 12, 6
SPELL_ES = {4: "Destello", 11: "Castigo", 14: "Prender", 3: "Agotar", 21: "Barrera", 7: "Curar",
            1: "Purificar", 12: "Teletransporte", 6: "Fantasma"}
ROLE_SPELL = {"TOP": TELETRANSPORTE, "JUNGLE": CASTIGO, "MIDDLE": TELETRANSPORTE,
              "BOTTOM": CURAR, "UTILITY": PRENDER}


def spells(role, shape, dd, cid):
    """Qué llevar además de Destello, y por qué. Devuelve (par recomendado, alternativas)."""
    segundo = ROLE_SPELL.get(role, PRENDER)
    why = {"TOP": "Teletransporte te devuelve a la línea sin perder súbditos y te deja aparecer en las peleas.",
           "JUNGLE": "Castigo es obligatorio para junglear y para pelear los objetivos.",
           "MIDDLE": "Teletransporte te deja volver rápido y sumarte a las peleas del mapa.",
           "BOTTOM": "Curar es lo estándar del ADC: te salva a vos y a tu support.",
           "UTILITY": "Prender corta curaciones y ayuda a cerrar las kills en la línea."}.get(role, "")
    alts = []
    if role != "JUNGLE":
        if len(shape["cc"]) >= 3:
            alts.append({"id": PURIFICAR, "name": SPELL_ES[PURIFICAR],
                         "why": f"El rival tiene mucho control ({', '.join(shape['cc'][:3])}): Purificar te saca el primer aturdimiento."})
        if len(shape["burst"]) >= 2:
            alts.append({"id": BARRERA, "name": SPELL_ES[BARRERA],
                         "why": f"Con {' y '.join(shape['burst'][:2])} enfrente, Barrera te aguanta el golpe que te mata."})
            alts.append({"id": AGOTAR, "name": SPELL_ES[AGOTAR],
                         "why": "Agotar apaga al asesino rival justo cuando salta."})
        if len(shape["heal"]) >= 2 and role in ("TOP", "MIDDLE", "UTILITY"):
            alts.append({"id": PRENDER, "name": SPELL_ES[PRENDER],
                         "why": f"El rival se cura mucho ({', '.join(shape['heal'][:2])}): Prender le corta la curación a la mitad."})
    vistos, limpio = set(), []
    for a in alts:
        if a["id"] != segundo and a["id"] not in vistos:
            vistos.add(a["id"])
            limpio.append(a)
    return {"par": [DESTELLO, segundo], "parNombres": [SPELL_ES[DESTELLO], SPELL_ES[segundo]],
            "why": why, "alts": limpio[:2]}


# ---------------------------------------------------------------- variantes según el rival
def _swap(pg, viejos, nuevo):
    """Cambia por `nuevo` la primera de `viejos` que esté en la página. Devuelve si cambió algo."""
    for v in (viejos if isinstance(viejos, (list, tuple)) else [viejos]):
        if v == nuevo:
            return False
        if v in pg["perks"]:
            pg["perks"][pg["perks"].index(v)] = nuevo
            return True
    return False


def _secundario(pg, estilo, r1, r2):
    pg["sub"] = estilo
    pg["perks"][4], pg["perks"][5] = r1, r2


# Runas que comparten ranura (para cambiar una por otra sin romper la página)
FILA_VALOR_2 = (ACONDICIONAMIENTO, SEGUNDO_AIRE, CORAZA_OSEA)
FILA_VALOR_3 = (CRECIMIENTO, REVITALIZAR, INQUEBRANTABLE)
FILA_PRECISION_3 = (GOLPE_GRACIA, CORTE, ULTIMA_BATALLA)


def adapt(base, shape, role, ranged, tanky, lane_ranged):
    """Retoca la página base según lo que pickeó el rival. Devuelve (página, motivos)."""
    pg = {"primary": base["primary"], "sub": base["sub"],
          "perks": list(base["perks"]), "shards": list(base["shards"])}
    why = []
    if len(shape["tanks"]) >= 2 and _swap(pg, FILA_PRECISION_3, CORTE):
        why.append(f"Corte en la última ranura: el rival tiene {len(shape['tanks'])} tanques "
                   f"({', '.join(shape['tanks'])}) y Corte pega según la vida que tengan.")
    if len(shape["cc"]) >= 3:
        if pg["shards"][2] != TENACIDAD:
            pg["shards"][2] = TENACIDAD
            why.append(f"Fragmento de tenacidad: con {len(shape['cc'])} campeones con control enfrente "
                       f"({', '.join(shape['cc'][:3])}), salís antes de los aturdimientos.")
        if not tanky and pg["sub"] == VALOR and _swap(pg, FILA_VALOR_3, INQUEBRANTABLE):
            why.append("Inquebrantable suma más tenacidad encima de eso.")
    if len(shape["burst"]) >= 2 and not tanky:
        if pg["sub"] != VALOR:
            _secundario(pg, VALOR, CORAZA_OSEA, CRECIMIENTO)
            why.append(f"Secundario en Valor (Coraza Ósea + Crecimiento Excesivo): con {' y '.join(shape['burst'][:2])} "
                       "enfrente, lo que te salva es no morir en el primer golpe.")
        elif _swap(pg, FILA_VALOR_3, CRECIMIENTO):
            why.append("Crecimiento Excesivo para aguantar el burst del rival.")
    poke = (lane_ranged or shape["ranged"] >= 3) and not ranged and role in ("TOP", "MIDDLE", "JUNGLE")
    if poke:
        motivo = ("tu rival de línea pega a distancia y te va a castigar"
                  if lane_ranged else f"el rival tiene {shape['ranged']} campeones a distancia")
        if pg["sub"] == VALOR:
            if _swap(pg, FILA_VALOR_2, SEGUNDO_AIRE):
                why.append(f"Segundo Aire: {motivo}; esta runa te cura ese daño constante.")
        else:
            _secundario(pg, VALOR, SEGUNDO_AIRE, CORAZA_OSEA)
            why.append(f"Secundario en Valor (Segundo Aire + Coraza Ósea): {motivo}, "
                       "y así aguantás la línea sin volver a base.")
    return pg, why


# ---------------------------------------------------------------- armado de las opciones
def _valid(dd, pg):
    """Que cada runa esté en la ranura que corresponde del árbol que dice la página."""
    slots_p = dd.rune_slots.get(pg["primary"])
    slots_s = dd.rune_slots.get(pg["sub"])
    if not slots_p or not slots_s or pg["primary"] == pg["sub"]:
        return False
    if any(pg["perks"][i] not in slots_p[i] for i in range(4)):
        return False
    filas = [i for i in range(1, 4) if pg["perks"][4] in slots_s[i]]
    filas2 = [i for i in range(1, 4) if pg["perks"][5] in slots_s[i]]
    if not filas or not filas2 or (len(filas) == 1 and filas == filas2):
        return False
    return all(pg["shards"][i] in SHARD_ROWS[i] for i in range(3))


def _view(dd, pg):
    """Lo que necesita la página web para dibujarla."""
    def r(i):
        return {"id": i, "name": dd.rune_name(i), "img": dd.rune_img(i)}
    return {**pg,
            "primaryName": dd.rune_name(pg["primary"]), "primaryImg": dd.rune_img(pg["primary"]),
            "subName": dd.rune_name(pg["sub"]), "subImg": dd.rune_img(pg["sub"]),
            "keystone": r(pg["perks"][0]),
            "primaryRunes": [r(i) for i in pg["perks"][:4]],
            "subRunes": [r(i) for i in pg["perks"][4:6]],
            "shardNames": [SHARD_ES.get(s, str(s)) for s in pg["shards"]]}


SHARD_ES = {5008: "Fuerza adaptable", 5005: "Velocidad de ataque", 5007: "Aceleración de habilidades",
            5010: "Velocidad de movimiento", 5001: "Vida (escala)", 5011: "Vida", 5013: "Tenacidad"}


def options(dd, cid, role, shape, champ_meta=None, lane_opp=None):
    """Las 2 o 3 páginas que se le muestran al jugador, ya validadas."""
    arq = builds.archetype(dd, cid) or "peleador"
    tabla = PAGES.get(arq, DEFAULT)
    ch = dd.champions.get(cid, {})
    ranged = bool(ch.get("ranged"))
    tanky = arq.startswith("tanque") or arq in ("coloso", "peleador")
    lane_ranged = bool(lane_opp and dd.champions.get(lane_opp, {}).get("ranged"))

    base = {k: (list(v) if isinstance(v, list) else v) for k, v in tabla["base"].items()}
    # si las estadísticas tienen suficientes partidas de este campeón, mandan ellas para la runa clave
    meta_key, meta_share, meta_games = None, 0, (champ_meta or {}).get("games", 0)
    for k in (champ_meta or {}).get("keystones", [])[:1]:
        if meta_games >= 25 and k.get("share", 0) >= 0.35:
            meta_key, meta_share = k["id"], k["share"]

    opciones = []
    adaptada, motivos = adapt(base, shape, role, ranged, tanky, lane_ranged)
    if motivos and _valid(dd, adaptada):
        opciones.append({"id": "rival", "title": "Para este rival", "why": motivos, **_view(dd, adaptada)})

    pg_meta = {**base, "perks": list(base["perks"]), "shards": list(base["shards"])}
    why_meta = []
    if meta_key and meta_key != pg_meta["perks"][0] and dd.rune_style.get(meta_key) == pg_meta["primary"]:
        pg_meta["perks"][0] = meta_key  # misma rama: la runa clave que más se usa entra directo
    if meta_key and meta_key == pg_meta["perks"][0]:
        why_meta.append(f"{dd.rune_name(meta_key)} la usa el {meta_share*100:.0f}% de los "
                        f"{dd.champ_name(cid)} en tu rango ({meta_games} partidas).")
    elif meta_key:
        why_meta.append(f"Ojo: en tu rango el {meta_share*100:.0f}% de los {dd.champ_name(cid)} "
                        f"usa {dd.rune_name(meta_key)}, de otra rama.")
    why_meta.append("Es la página que mejor le funciona a este campeón en general, sin mirar al rival.")
    if _valid(dd, pg_meta):
        opciones.append({"id": "meta", "title": "La de siempre", "why": why_meta, **_view(dd, pg_meta)})

    alt = tabla.get("alt")
    if alt and _valid(dd, alt) and all(alt["perks"][0] != o["perks"][0] or alt["primary"] != o["primary"]
                                       for o in opciones):
        opciones.append({"id": "alt", "title": tabla.get("altName", "Alternativa"),
                         "why": [tabla.get("altWhy", "Otra forma de jugar este campeón.")], **_view(dd, alt)})
    return opciones[:3]
