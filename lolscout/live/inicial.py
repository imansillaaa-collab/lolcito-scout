"""Ítem inicial: todos los que se suelen empezar en tu rol, ordenados por lo que más te conviene contra tu rival.

Riot no guarda en las partidas qué compraste al principio (los iniciales se venden), así que acá manda el
criterio de juego: si tu campeón es AD o AP, cuerpo a cuerpo o a distancia, tanque, asesino o tirador, y cómo
es tu rival de línea (si te pega de lejos, si es fuerte temprano). El support no aparece: ya empieza con el
ítem de su misión.
"""

POCION, POCION_R = 2003, 2031
ESCUDO, ESPADA, SORTIJA, SACRIFICAR = 1054, 1055, 1056, 1083
SELLO, LAGRIMA, ESPADA_LARGA = 1082, 3070, 1036
RASGAFUEGOS, TROTABRISAS, PISAMUSGO = 1101, 1102, 1103


def _tipo(dd, cid):
    ch = dd.champions.get(cid, {})
    info = ch.get("info", {})
    a, m = info.get("attack", 5), info.get("magic", 5)
    return {"tags": set(ch.get("tags", [])), "tag0": (ch.get("tags") or [""])[0], "ranged": bool(ch.get("ranged")), "ap": m / (a + m) if a + m else 0.5,
            "nombre": ch.get("name", "tu campeón")}


def iniciales(dd, cid, role, rival=None):
    """[{items, why, puntos, mejor}] para tu rol, el mejor primero. Vacío para support o sin campeón."""
    if not cid or role not in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM"):
        return []
    yo = _tipo(dd, cid)
    op = _tipo(dd, rival) if rival else None
    ap = yo["ap"] >= 0.6
    melee = not yo["ranged"]
    me_pegan_de_lejos = bool(op and op["ranged"] and melee)
    rival_nombre = op["nombre"] if op else "tu rival"
    ops = []

    def op_(items, puntos, why):
        ops.append({"items": items, "puntos": round(puntos, 2), "why": why})

    if role == "JUNGLE":
        tanque = "Tank" in yo["tags"]
        asesino = "Assassin" in yo["tags"]
        op_([RASGAFUEGOS, POCION], 0.45 + (0.25 if asesino else 0) + (0.15 if ap else 0) - (0.2 if tanque else 0),
            ["Más daño: limpia más rápido y mata más fácil en los ganks.",
             "Ideal para asesinos y campeones de daño." if not asesino else f"{yo['nombre']} vive de matar rápido."])
        op_([TROTABRISAS, POCION], 0.45 + (0.2 if "Fighter" in yo["tags"] and not tanque else 0),
            ["Velocidad para moverte y llegar antes a los ganks y a los objetivos.",
             "Buena para junglas que gankean mucho y pelean temprano."])
        op_([PISAMUSGO, POCION], 0.4 + (0.35 if tanque else 0),
            ["Escudos y resistencia: aguantás más en la jungla y en las peleas.",
             f"{yo['nombre']} es tanque: le saca más provecho." if tanque else "Para junglas que entran primero a pelear."])
    else:
        if role in ("TOP", "MIDDLE"):
            op_([ESCUDO, POCION], 0.35 + (0.4 if me_pegan_de_lejos else 0) + (0.15 if yo["tag0"] == "Tank" else 0)
                - (0.15 if ap else 0),
                [f"{rival_nombre} te pega de lejos: el Escudo te cura ese daño constante." if me_pegan_de_lejos
                 else "Aguante y curación para una línea difícil.",
                 "El inicial más seguro para no perder la línea."])
        if not ap:
            op_([ESPADA, POCION], 0.4 + (0.25 if role in ("TOP", "MIDDLE", "BOTTOM") and not me_pegan_de_lejos else 0)
                + (0.15 if role == "BOTTOM" else 0) - (0.25 if yo["tag0"] == "Tank" else 0),
                ["Daño y robo de vida: para pelear la línea desde el principio.",
                 "Lo estándar para campeones de ataque." if role != "BOTTOM" else "Lo estándar del ADC."])
        if ap or role == "MIDDLE" or (role == "TOP" and yo["ap"] >= 0.45):
            op_([SORTIJA, POCION, POCION], 0.4 + (0.35 if ap else -0.2),
                ["Poder de habilidad y maná: el inicial clásico de los magos.",
                 "Te deja castigar a tu rival con habilidades sin quedarte sin maná."])
        if role == "BOTTOM":
            op_([SACRIFICAR, POCION], 0.35 - (0.15 if op and "Assassin" in op["tags"] else 0),
                ["Oro extra por súbdito: si la línea es tranquila, llegás antes a tu primer ítem.",
                 "Mejor en líneas que no te van a presionar."])
        if ap and role in ("MIDDLE", "TOP"):
            op_([SELLO, POCION, POCION, POCION], 0.3 + (0.15 if op and op["ranged"] is False and role == "MIDDLE" else 0),
                ["Crece con cada kill y asistencia: para líneas en las que vas a ganar.",
                 "Si vas atrás, rinde menos: usalo si te sentís seguro."])
        if role in ("TOP", "MIDDLE") and "Mage" in yo["tags"] and "Tank" not in yo["tags"]:
            op_([LAGRIMA, POCION, POCION], 0.4,
                ["Maná que crece: para campeones que gastan mucho maná y escalan.",
                 "Pensado para jugar a largo plazo."])
        if not ap and role in ("TOP", "MIDDLE"):
            op_([ESPADA_LARGA, POCION, POCION, POCION], 0.3 + (0.1 if "Assassin" in yo["tags"] or "Fighter" in yo["tags"] else 0),
                ["Espada Larga + 3 pociones: más curación para intercambios largos.",
                 "Para ir a pelear mucho la línea."])

    ops.sort(key=lambda o: -o["puntos"])
    for i, o in enumerate(ops):
        o["mejor"] = i == 0
        o["items"] = [{"id": i_, "name": dd.item_name(i_), "img": dd.item_img(i_)} for i_ in o["items"]]
        o["name"] = o["items"][0]["name"]
        o["oro"] = sum(dd.items.get(i_["id"], {}).get("gold", 0) for i_ in o["items"])
    return ops
