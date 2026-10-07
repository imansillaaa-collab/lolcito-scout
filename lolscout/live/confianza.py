"""Qué tan bien sabés jugar cada campeón («confianza»), para la selección de campeones.

Mezcla dos cosas, y las dos se van gastando con el tiempo:
- Tus partidas guardadas por Lolcito (el historial de cada cuenta, no solo las últimas 20): pesan más las
  recientes (valen la mitad cada 60 días) y las de ESTE rol (las de otro rol valen un 30%).
- La maestría del cliente (puntos de cada campeón), descontada según hace cuánto no lo jugás (la mitad cada 60
  días desde la última vez). Así 400.000 puntos con un campeón que no tocás hace un año pesan poco, y con uno
  que jugaste ayer pesan muchísimo. Más o menos 1.000 puntos = 1 partida, y la maestría vale un 30% de una
  partida guardada (no sabe en qué rol lo jugaste).

Resultado por campeón: k de 0 (nunca) a 1 (tu main): ~0,3 con 2 partidas recientes, ~0,6 con 5, ~0,8 con 10.
"""
import math
import time

ROL_ES = {"Top": "TOP", "Jungla": "JUNGLE", "Mid": "MIDDLE", "ADC": "BOTTOM", "Support": "UTILITY"}
VIDA_MEDIA = 60          # días en que una partida (o la maestría sin jugar) pasa a valer la mitad
OTRO_ROL = 0.3           # una partida de ese campeón en otro rol
PUNTOS_POR_PARTIDA = 1000
PESO_MAESTRIA = 0.1      # la maestría no sabe en qué rol ni en qué cola lo jugaste: pesa poco
MAESTRIA_MAX = 3.0       # y sola nunca vale más que 3 partidas recientes en este rol
ESCALA = 6.0             # k = 1 - e^(-total/ESCALA)


def _decae(dias):
    return 0.5 ** (max(dias, 0) / VIDA_MEDIA)


def calcular(partidas, maestria, ahora=None):
    """partidas: índice del historial (dicts con champ, role, result, created en ms, remake).
    maestria: lista del cliente (championId, championPoints, lastPlayTime en ms).
    Devuelve {rol: {championId: {k, g, w, texto}}} para los 5 roles."""
    ahora = ahora or time.time()
    out = {}
    m_eq, m_info = {}, {}
    for m in maestria or []:
        cid, pts = m.get("championId"), m.get("championPoints") or 0
        if not cid or pts <= 0:
            continue
        dias = (ahora - (m.get("lastPlayTime") or 0) / 1000) / 86400
        m_eq[cid] = min(pts / PUNTOS_POR_PARTIDA * _decae(dias) * PESO_MAESTRIA, MAESTRIA_MAX)
        m_info[cid] = (pts, dias)
    for rol in ROL_ES.values():
        eff, g, w, ultima = {}, {}, {}, {}
        for x in partidas or []:
            if x.get("remake") or not x.get("result") or not (x.get("champ") or {}).get("id"):
                continue
            cid = x["champ"]["id"]
            dias = (ahora - (x.get("created") or 0) / 1000) / 86400
            mismo = ROL_ES.get(x.get("role")) == rol
            eff[cid] = eff.get(cid, 0) + _decae(dias) * (1 if mismo else OTRO_ROL)
            if mismo and dias <= 120:     # tu winrate con él: solo en este rol y de los últimos 4 meses
                g[cid] = g.get(cid, 0) + 1
                w[cid] = w.get(cid, 0) + (x["result"] == "win")
            if mismo:
                ultima[cid] = min(ultima.get(cid, 1e9), dias)
        res = {}
        for cid in set(eff) | set(m_eq):
            total = eff.get(cid, 0) + m_eq.get(cid, 0)
            k = 1 - math.exp(-total / ESCALA)
            if k < 0.1:
                continue
            res[cid] = {"k": round(k, 3), "g": g.get(cid, 0), "w": w.get(cid, 0),
                        "texto": _texto(g.get(cid, 0), ultima.get(cid), m_info.get(cid), k)}
        out[rol] = res
    return out


def _texto(g, ultima, maestria, k):
    """La frase que aparece en la recomendación, para que se entienda por qué lo puso arriba."""
    pts, dias_m = maestria if maestria else (0, None)
    pts_txt = f"{pts / 1000:.0f} mil puntos de maestría" if pts >= 1000 else ""
    if g >= 3 and ultima is not None and ultima <= 30:
        return f"Lo jugás mucho últimamente ({g} partidas en este rol)" + (f", {pts_txt}" if pts_txt else "")
    if pts >= 50000 and dias_m is not None and dias_m <= 30:
        return f"Es de tus campeones: {pts_txt}"
    if pts >= 50000 and dias_m is not None:
        meses = max(1, round(dias_m / 30))
        return f"Lo jugabas mucho ({pts_txt}), pero hace {meses} mes{'es' if meses > 1 else ''} que no"
    if g >= 1:
        return f"Lo jugaste {g} {'vez' if g == 1 else 'veces'} en este rol" + (f" · {pts_txt}" if pts_txt else "")
    if pts_txt:
        return f"Lo jugaste en otros modos o roles: {pts_txt}"
    return "Lo jugaste algunas veces" if k >= 0.3 else "Lo probaste poco"
