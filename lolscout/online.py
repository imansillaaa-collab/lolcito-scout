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
            return json.loads(cache.read_text(encoding="utf-8")), err
        except ValueError:
            pass
    return None, err or "No hay estadísticas descargadas."
