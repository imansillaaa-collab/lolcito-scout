"""Estadísticas online: la app descarga las estadísticas ya calculadas (las publica un proceso diario
en GitHub con la key del dueño), así cada usuario no necesita su propia API key de Riot."""
import json
import time

import requests

from . import config

# Rangos agrupados en 3 niveles: cada nivel tiene su propia tier list
BRACKETS = {
    "bajo": ["IRON", "BRONZE", "SILVER"],
    "medio": ["GOLD", "PLATINUM"],
    "alto": ["EMERALD", "DIAMOND", "MASTER"],
}
BRACKET_NAMES = {"bajo": "Hierro – Plata", "medio": "Oro – Platino", "alto": "Esmeralda – Maestro"}
TIER_ES = {"IRON": "Hierro", "BRONZE": "Bronce", "SILVER": "Plata", "GOLD": "Oro", "PLATINUM": "Platino",
           "EMERALD": "Esmeralda", "DIAMOND": "Diamante", "MASTER": "Maestro", "GRANDMASTER": "Gran Maestro",
           "CHALLENGER": "Retador"}
MAX_AGE = 6 * 3600  # vuelve a descargar si el archivo tiene más de 6 horas


def bracket_for_tier(tier: str) -> str:
    tier = (tier or "").upper()
    for name, tiers in BRACKETS.items():
        if tier in tiers:
            return name
    if tier in ("GRANDMASTER", "CHALLENGER"):
        return "alto"
    return "medio"  # sin rango: el nivel del medio es el más representativo


def url(bracket: str, repo: str = None) -> str:
    repo = (repo or config.STATS_REPO or "").strip().strip("/")
    if repo.startswith("http"):  # también sirve cualquier otro hosting: https://.../carpeta
        return f"{repo}/stats_{bracket}.json"
    return f"https://raw.githubusercontent.com/{repo}/datos/stats_{bracket}.json"


def _cache(bracket):
    return config.DATA_DIR / f"online_{bracket}.json"


def load(bracket: str, force: bool = False):
    """Devuelve (resultado, error). Usa la copia guardada si no hay internet."""
    cache = _cache(bracket)
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE
    if not config.STATS_REPO:
        err = "Todavía no se configuró el servidor de estadísticas."
    elif fresh and not force:
        err = None
    else:
        err = None
        try:
            r = requests.get(url(bracket), timeout=20)
            if r.status_code == 200:
                data = r.json()
                if data.get("roles") is not None:
                    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            elif r.status_code == 404:
                err = "El servidor todavía no publicó estadísticas para este nivel."
            else:
                err = f"El servidor respondió {r.status_code}."
        except (requests.RequestException, ValueError) as e:
            err = f"Sin conexión con el servidor de estadísticas ({e.__class__.__name__})."
    if cache.exists():
        try:
            return normalizar(json.loads(cache.read_text(encoding="utf-8"))), err
        except ValueError:
            pass
    return None, err or "No hay estadísticas descargadas."


def normalizar(result: dict) -> dict:
    """Vuelve a calcular el puntaje y el tier de cada campeón con la regla actual (analyze.PRIOR) y reordena.
    Así lo que ya estaba publicado con la regla vieja se ve bien sin esperar a la próxima publicación."""
    from .analyze import adj_wr, tier_of
    listas = list((result.get("roles") or {}).values()) + list(((result.get("dia") or {}).get("roles") or {}).values())
    for champs in listas:
        for c in champs:
            if c.get("games"):
                c["adj"] = adj_wr(c["wr"] * c["games"], c["games"])
                c["tier"] = tier_of(c["adj"])
        champs.sort(key=lambda c: c.get("adj", 0.5), reverse=True)
    return result


# ---------- «Todas las ligas»: junta los tres niveles en uno (lo usa la pestaña Estadísticas)
TODAS = "todas"
TODAS_NOMBRE = "Todas las ligas"


def load_todas(force: bool = False):
    """Descarga los tres niveles y los suma como si fueran una sola tier list. Devuelve (resultado, error)."""
    partes, errores = [], []
    for b in BRACKETS:
        r, err = load(b, force=force)
        if r and r.get("roles"):
            partes.append(r)
        if err:
            errores.append(err)
    if not partes:
        return None, errores[0] if errores else "No hay estadísticas descargadas."
    return combinar(partes), (errores[0] if errores else None)


def _sumar_lista(listas, top, minimo=0.0, con_wr=True):
    """Suma listas de {id, share, wr} de varios niveles (share y wr se pasan a cantidades y se vuelven a dividir)."""
    cant, gan = {}, {}
    for lista, g in listas:
        for x in lista or []:
            n = x.get("share", 0) * g
            cant[x["id"]] = cant.get(x["id"], 0) + n
            gan[x["id"]] = gan.get(x["id"], 0) + n * x.get("wr", 0)
    total = sum(g for _, g in listas) or 1
    ids = sorted((i for i in cant if cant[i] / total >= minimo), key=lambda i: cant[i], reverse=True)[:top]
    return [{"id": i, "share": cant[i] / total, **({"wr": gan[i] / cant[i]} if con_wr and cant[i] else {})}
            for i in ids]


def combinar(partes: list) -> dict:
    """Suma las estadísticas publicadas de varios niveles de liga en una sola."""
    from .analyze import adj_wr, tier_of
    n_total = sum(p.get("matches", 0) for p in partes) or 1
    roles = {}
    for role in ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]:
        por_id = {}
        for p in partes:
            for c in p.get("roles", {}).get(role, []):
                por_id.setdefault(c["id"], []).append((c, p.get("matches", 0)))
        lista = []
        for cid, filas in por_id.items():
            g = sum(c["games"] for c, _ in filas)
            w = sum(c["wr"] * c["games"] for c, _ in filas)
            vs = {}
            for c, _ in filas:
                for eid, (vg, vw) in (c.get("vs_all") or {}).items():
                    a = vs.setdefault(eid, [0, 0.0])
                    a[0] += vg
                    a[1] += vg * vw
            matchups = sorted(({"id": int(e), "games": a[0], "wr": a[1] / a[0], "adj": adj_wr(a[1], a[0], 10)}
                               for e, a in vs.items() if a[0] >= 5), key=lambda m: m["adj"], reverse=True)
            con_g = [(c, c["games"]) for c, _ in filas]
            lista.append({
                "id": cid, "name": filas[0][0].get("name"), "games": g, "wr": w / g, "adj": adj_wr(w, g),
                "tier": tier_of(adj_wr(w, g)),
                "pick": sum(c.get("pick", 0) * n for c, n in filas) / n_total,
                "ban": sum(c.get("ban", 0) * n for c, n in filas) / n_total,
                "kda": sum(c.get("kda", 0) * c["games"] for c, _ in filas) / g,
                "items": _sumar_lista([(c.get("items"), gg) for c, gg in con_g], 15, 0.02),
                "boots": _sumar_lista([(c.get("boots"), gg) for c, gg in con_g], 4),
                "keystones": _sumar_lista([(c.get("keystones"), gg) for c, gg in con_g], 2),
                "spells": max(filas, key=lambda f: f[0]["games"])[0].get("spells", []),
                "good_vs": matchups[:5], "bad_vs": matchups[::-1][:5],
                "vs_all": {str(m["id"]): [m["games"], round(m["wr"], 4)] for m in matchups},
            })
        lista.sort(key=lambda c: c["adj"], reverse=True)
        roles[role] = lista

    duos = {}
    for p in partes:
        for d in p.get("duos", []):
            a = duos.setdefault((d["adc"], d["sup"]), [0, 0.0])
            a[0] += d["games"]
            a[1] += d["games"] * d["wr"]
    duos = sorted(({"adc": a, "sup": s, "games": g, "wr": w / g, "adj": adj_wr(w, g, 15)}
                   for (a, s), (g, w) in duos.items()), key=lambda d: d["adj"], reverse=True)

    champs = {}
    for p in partes:
        for k, c in (p.get("champs") or {}).items():
            champs.setdefault(k, []).append(c)
    champs = {k: {"id": cs[0]["id"], "games": sum(c["games"] for c in cs),
                  "wr": sum(c["wr"] * c["games"] for c in cs) / sum(c["games"] for c in cs),
                  "items": _sumar_lista([(c.get("items"), c["games"]) for c in cs], 12, 0.05),
                  "boots": _sumar_lista([(c.get("boots"), c["games"]) for c in cs], 3),
                  "keystones": _sumar_lista([(c.get("keystones"), c["games"]) for c in cs], 2, con_wr=False)}
              for k, cs in champs.items()}

    dist = {}
    for p in partes:
        for cid, d in (p.get("dist") or {}).items():
            t = dist.setdefault(cid, {})
            for r, n in d.items():
                t[r] = t.get(r, 0) + n

    dia = None
    dias = [p["dia"] for p in partes if p.get("dia")]
    if dias:
        dr = {}
        for role in ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]:
            s = {}
            for d in dias:
                for c in d.get("roles", {}).get(role, []):
                    a = s.setdefault(c["id"], [0, 0.0])
                    a[0] += c["games"]
                    a[1] += c["games"] * c["wr"]
            lst = [{"id": i, "games": g, "wr": w / g, "adj": adj_wr(w, g), "tier": tier_of(adj_wr(w, g))}
                   for i, (g, w) in s.items()]
            dr[role] = sorted(lst, key=lambda c: c["adj"], reverse=True)[:10]
        dia = {"horas": dias[0].get("horas", 24), "matches": sum(d.get("matches", 0) for d in dias), "roles": dr}

    parches = sorted({x for p in partes for x in p.get("patches", [])},
                     key=lambda v: tuple(int(n) for n in v.split(".")), reverse=True)
    return {
        "format": 1, "bracket": TODAS, "tiers": [t for p in partes for t in p.get("tiers", [])],
        "platform": partes[0].get("platform"), "generated": max(p.get("generated") or "" for p in partes),
        "patches": parches, "matches": sum(p.get("matches", 0) for p in partes),
        "version": max((p.get("version") or "" for p in partes)), "roles": roles, "duos": duos,
        "champs": champs, "dist": dist, "dia": dia,
    }
