"""Conexión con el cliente de LoL que corre en tu PC (no usa la API key ni internet).

- LCU (League Client): la selección de campeones. Puerto y clave salen del archivo "lockfile".
- Live Client Data API (puerto 2999): datos de la partida en curso, los mismos que ves en el marcador (Tab).
Ambas son APIs locales oficiales de Riot; solo leen, no tocan el juego.
"""
import base64
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # certificados locales autofirmados

from .. import config

LOCKFILE_PATHS = [
    r"C:\Riot Games\League of Legends",
    r"D:\Riot Games\League of Legends",
    r"C:\Program Files\Riot Games\League of Legends",
    "/Applications/League of Legends.app/Contents/LoL",
]


class LCU:
    def __init__(self):
        self.base = None
        self.headers = {}

    def _credentials(self):
        for folder in filter(None, [config.LOL_PATH] + LOCKFILE_PATHS):
            f = Path(folder) / "lockfile"
            if f.exists():
                try:
                    _, _, port, password, proto = f.read_text().strip().split(":")
                    return port, password, proto
                except ValueError:
                    continue
        try:  # si el juego está instalado en otra carpeta, lo busco entre los procesos
            import psutil
            for p in psutil.process_iter(["name", "cmdline"]):
                if (p.info["name"] or "").lower().startswith("leagueclientux"):
                    args = dict(a[2:].split("=", 1) for a in p.info["cmdline"] or [] if a.startswith("--") and "=" in a)
                    if "app-port" in args:
                        return args["app-port"], args["remoting-auth-token"], "https"
        except Exception:
            pass
        return None

    def connect(self) -> bool:
        cred = self._credentials()
        if not cred:
            self.base = None
            return False
        port, password, proto = cred
        self.base = f"{proto}://127.0.0.1:{port}"
        token = base64.b64encode(f"riot:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}
        return True

    def get(self, path: str, timeout: float = 2):
        if not self.base and not self.connect():
            return None
        try:
            r = requests.get(self.base + path, headers=self.headers, verify=False, timeout=timeout)
            return r.json() if r.status_code == 200 else None
        except requests.Timeout:
            return None  # el cliente tardó (el historial lo pide a los servidores de Riot): se reintenta después
        except requests.RequestException:
            self.base = None  # el cliente se cerró o cambió de puerto
            return None

    def match_list(self, count: int = 20, puuid: str = None):
        """Últimas partidas de la cuenta logueada (el cliente las pide a Riot, puede tardar unos segundos)."""
        paths = [f"/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex={count}"]
        if puuid:
            paths.append(f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex={count}")
        for p in paths:
            data = self.get(p, timeout=20)
            games = ((data or {}).get("games") or {}).get("games") if isinstance(data, dict) else None
            if games:
                return games
        return []

    def phase(self):
        return self.get("/lol-gameflow/v1/gameflow-phase")

    def champ_select(self):
        return self.get("/lol-champ-select/v1/session")

    # --- Tu cuenta (la que está logueada en el cliente) ---
    def summoner(self):
        return self.get("/lol-summoner/v1/current-summoner")

    def ranked(self):
        """Rango en Solo/Dúo: {'tier': 'PLATINUM', 'division': 'II', 'lp': 45} o None."""
        data = self.get("/lol-ranked/v1/current-ranked-stats") or {}
        q = (data.get("queueMap") or {}).get("RANKED_SOLO_5x5")
        if not q:
            q = next((x for x in data.get("queues", []) if x.get("queueType") == "RANKED_SOLO_5x5"), None)
        if not q or not q.get("tier") or q.get("tier") in ("NONE", ""):
            return None
        return {"tier": q["tier"], "division": q.get("division", ""), "lp": q.get("leaguePoints", 0),
                "wins": q.get("wins", 0), "losses": q.get("losses", 0)}

    def my_games(self, count: int = 60):
        """Tus últimas partidas (Grieta del Invocador): lista de (championId, ganó, queueId)."""
        out = []
        for g in self.match_list(min(count, 20)):
            if g.get("mapId", 11) != 11:
                continue
            for p in g.get("participants", [])[:1]:
                out.append((p.get("championId"), bool((p.get("stats") or {}).get("win")), g.get("queueId")))
        return out


class LiveClient:
    URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"

    def game(self):
        try:
            r = requests.get(self.URL, verify=False, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                return data if data.get("allPlayers") else None
        except (requests.RequestException, ValueError):
            pass
        return None
