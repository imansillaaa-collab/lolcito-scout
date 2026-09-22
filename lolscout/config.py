"""Configuración. En la app (.exe) se edita desde la pestaña Configuración y se guarda en
%LOCALAPPDATA%\\LolcitoScout\\ajustes.json. En modo desarrollo también acepta un archivo .env."""
import json
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(__file__).resolve().parent.parent
if FROZEN:
    _base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    DATA_DIR = _base / "LolcitoScout"
    if not DATA_DIR.exists() and (_base / "LoLScout").exists():  # conserva datos de la versión anterior
        try:
            (_base / "LoLScout").rename(DATA_DIR)
        except OSError:
            DATA_DIR = _base / "LoLScout"
else:
    DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = DATA_DIR / "reportes" if FROZEN else ROOT / "reportes"
DB_PATH = DATA_DIR / "lolscout.db"
SETTINGS_PATH = DATA_DIR / "ajustes.json"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _list(name: str, default: str):
    return [x.strip().upper() for x in os.environ.get(name, default).split(",") if x.strip()]


RIOT_API_KEY = os.environ.get("RIOT_API_KEY", "")
MY_RIOT_ID = os.environ.get("MY_RIOT_ID", "")          # ej: "Iñaki#LAS"
PLATFORM = os.environ.get("PLATFORM", "la2")           # LAS
REGION = os.environ.get("REGION", "americas")          # región de match-v5 para LAS
TIERS = _list("TIERS", "PLATINUM,EMERALD")
DIVISIONS = ["I", "II", "III", "IV"]
ROLES = _list("ROLES", "BOTTOM,UTILITY")                # BOTTOM = ADC, UTILITY = Support
AUTO_UPDATE = os.environ.get("AUTO_UPDATE", "1") == "1"  # escanear solo al abrir la app si pasó un día
LOL_PATH = os.environ.get("LOL_PATH", "")
# Estadísticas: "online" (las descarga ya calculadas, sin key) o "local" (las calcula con tu propia key)
STATS_SOURCE = os.environ.get("STATS_SOURCE", "online")
BRACKET = os.environ.get("BRACKET", "auto")               # auto = según el rango de tu cuenta

PLAYERS_PER_RUN = _int("PLAYERS_PER_RUN", 80)
MATCHES_PER_PLAYER = _int("MATCHES_PER_PLAYER", 10)
MAX_NEW_MATCHES = _int("MAX_NEW_MATCHES", 500)
DAYS_BACK = _int("DAYS_BACK", 3)
MIN_GAMES = _int("MIN_GAMES", 20)
LANGUAGE = os.environ.get("LANGUAGE", "es_AR")

RATE_LIMITS = [(20, 1.0), (100, 120.0)]
RANKED_SOLO_QUEUE = 420
ROLE_NAMES = {"TOP": "Top", "JUNGLE": "Jungla", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}

EDITABLE = ["RIOT_API_KEY", "MY_RIOT_ID", "PLATFORM", "REGION", "TIERS", "ROLES", "AUTO_UPDATE", "LOL_PATH",
            "PLAYERS_PER_RUN", "MAX_NEW_MATCHES", "MIN_GAMES", "STATS_SOURCE", "STATS_REPO", "BRACKET", "LAYOUT"]
LAYOUT = {}  # orden de los paneles en la vista de partida (lo acomoda cada usuario)


def _bundled_repo() -> str:
    """Repositorio de GitHub de donde bajar las estadísticas. Lo escribe el compilador del .exe."""
    for base in (Path(getattr(sys, "_MEIPASS", ROOT)), ROOT):
        f = base / "lolscout" / "servidor.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8")).get("repo", "")
            except ValueError:
                pass
    return ""


STATS_REPO = os.environ.get("STATS_REPO", "") or _bundled_repo()


def current_settings() -> dict:
    g = globals()
    return {k: g[k] for k in EDITABLE}


def apply_settings(data: dict) -> None:
    g = globals()
    for k, v in data.items():
        if k not in EDITABLE:
            continue
        if k in ("TIERS", "ROLES") and isinstance(v, str):
            v = [x.strip().upper() for x in v.split(",") if x.strip()]
        if k in ("PLAYERS_PER_RUN", "MAX_NEW_MATCHES", "MIN_GAMES"):
            v = int(v)
        if k == "LAYOUT" and not isinstance(v, dict):
            continue
        if k == "AUTO_UPDATE":
            v = bool(v)
        if k in ("RIOT_API_KEY", "MY_RIOT_ID", "LOL_PATH", "STATS_REPO", "STATS_SOURCE", "BRACKET") and isinstance(v, str):
            v = v.strip()
        g[k] = v


def save_settings(data: dict) -> None:
    apply_settings(data)
    SETTINGS_PATH.write_text(json.dumps(current_settings(), ensure_ascii=False, indent=1), encoding="utf-8")


if SETTINGS_PATH.exists():
    try:
        apply_settings(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        pass
