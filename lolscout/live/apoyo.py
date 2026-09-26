"""Misión de Support: qué mejora conviene elegir para el ítem de support en esta partida.

Parche 16.19: Brújula Rúnica → Recompensa Mundial (3867, al completar la misión) → se mejora gratis a una de
estas cinco. Se recomienda según tu campeón (si cura/escuda, cuánto control tiene, si es mago, tanque o
luchador), cómo viene el equipo rival y cómo va la partida. Cuando la elegís en el juego, se marca cuál.
"""
from .gameplan import HARD_CC

RECOMPENSA = 3867
MEJORAS = {
    3869: "Menos daño recibido de campeones y, al terminar, ralentiza a los que tenés cerca.",
    3870: "Tus curas y escudos le dan a tu aliado daño mágico extra en su próximo ataque y menos daño recibido.",
    3871: "Cuando pegás a un campeón con una habilidad, explota y hace daño mágico.",
    3876: "Ralentizar o inmovilizar a un rival cerca de tus aliados te cura y les da velocidad a vos y a un aliado.",
    3877: "Después de una habilidad, tu próximo ataque pega más y el rival recibe más daño por 4 segundos.",
}
ENCANTADORES = {"Janna", "Lulu", "Nami", "Soraka", "Sona", "Yuumi", "Milio", "Karma", "Seraphine", "Renata",
                "Taric", "Ivern", "Orianna", "Zilean", "Bard"}
PEGAN_CON_ATAQUES = {"Pantheon", "Braum", "Taric", "Leona", "Alistar", "Rell", "Senna", "Bard", "Thresh", "Pyke",
                     "Nautilus", "Sett", "Poppy"}


def mejora_support(dd, me, allies, enemies, ventaja=0.0):
    ch = dd.champions.get(me["cid"], {})
    alias, tags, kit = ch.get("alias", ""), ch.get("tags", []), ch.get("kit", {})
    cura = alias in ENCANTADORES or bool(kit.get("heal")) or bool(kit.get("shield"))
    control = alias in HARD_CC or kit.get("cc", 0) >= 2
    mago = "Mage" in tags
    tanque = "Tank" in tags
    ataques = alias in PEGAN_CON_ATAQUES or "Fighter" in tags
    nombre = ch.get("name", "tu campeón")
    buceadores = [dd.champ_name(p["cid"]) for p in enemies
                  if {"Assassin", "Fighter"} & set(dd.champions.get(p["cid"], {}).get("tags", []))]
    adc = next((p for p in allies if p["position"] == "BOTTOM"), None)
    adc_tira = adc and "Marksman" in dd.champions.get(adc["cid"], {}).get("tags", [])
    adc_nombre = dd.champ_name(adc["cid"]) if adc else "tu ADC"

    puntos, motivos = {}, {}

    def suma(item, p, motivo=None):
        puntos[item] = puntos.get(item, 0.25) + p
        if motivo:
            motivos.setdefault(item, []).append(motivo)

    for item in MEJORAS:
        suma(item, 0)
    # Oposición Celestial: aguantar
    if tanque:
        suma(3869, 0.35, f"{nombre} va adelante y recibe mucho daño")
    # (si no sos tanque, que se te tiren encima pesa menos: igual vas atrás de tu equipo)
    if len(buceadores) >= 2:
        suma(3869, 0.25 if tanque else 0.1, f"el rival tiene {len(buceadores)} que se tiran encima: {', '.join(buceadores[:3])}")
    if ventaja <= -0.25:
        suma(3869, 0.15 if tanque else 0.05, "tu equipo viene atrás: te conviene aguantar más")
    # Trineo del Solsticio: controles
    if control:
        suma(3876, 0.4, f"{nombre} tiene mucho control: cada ralentización o atontamiento te cura y te da velocidad")
    if tanque and control:
        suma(3876, 0.05)
    # Tejesueños: curas y escudos
    if cura:
        suma(3870, 0.45, f"{nombre} cura o escuda seguido: cada vez le das daño extra a tu aliado")
    if cura and adc_tira:
        suma(3870, 0.15, f"{adc_nombre} pega con ataques básicos: aprovecha el daño extra")
    # Espina de Zaz'Zak: daño con habilidades
    if mago:
        suma(3871, 0.45, f"{nombre} pega con habilidades: cada una explota con daño extra")
    if mago and ventaja >= 0.25:
        suma(3871, 0.1, "vienen adelante: más daño para cerrar la partida")
    # Canción de Sangre: ataques después de habilidades
    if ataques:
        suma(3877, 0.3, f"{nombre} combina habilidades con ataques básicos")
    if adc_tira and ataques:
        suma(3877, 0.1, f"el rival marcado recibe más daño de {adc_nombre} y del resto")
    if ventaja >= 0.25:
        suma(3877, 0.05)

    elegido = next((i for i in me["items"] if i in MEJORAS), None)
    if elegido:
        estado = "elegido"
    elif RECOMPENSA in me["items"]:
        estado = "elegir"
    else:
        estado = "juntando"
    orden = sorted(MEJORAS, key=lambda i: -puntos[i])
    return {"estado": estado, "elegido": elegido, "mejor": orden[0],
            "opciones": [{"id": i, "que": MEJORAS[i], "why": motivos.get(i, [])[:2],
                          "puntos": round(puntos[i], 2)} for i in orden]}
