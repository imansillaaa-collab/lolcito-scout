"""Cliente mínimo de la API de Riot con control de rate limit y reintentos."""
import time
from collections import deque
from urllib.parse import quote

import requests

from . import config


class RiotError(Exception):
    pass


class RateLimiter:
    """Ventanas deslizantes: nunca supera N pedidos cada T segundos."""

    def __init__(self, limits):
        self.set_limits(limits)

    def set_limits(self, limits):
        self.windows = [(n, t, deque()) for n, t in limits]

    def wait(self):
        while True:
            now = time.monotonic()
            sleep_for = 0.0
            for n, t, calls in self.windows:
                while calls and now - calls[0] >= t:
                    calls.popleft()
                if len(calls) >= n:
                    sleep_for = max(sleep_for, t - (now - calls[0]) + 0.05)
            if sleep_for <= 0:
                for _, _, calls in self.windows:
                    calls.append(now)
                return
            time.sleep(sleep_for)


class RiotClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.RIOT_API_KEY
        if not self.api_key:
            raise RiotError(
                "Falta la API key: cargala en la pestaña Configuración."
            )
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = self.api_key
        self.limiter = RateLimiter(config.RATE_LIMITS)
        self.requests_made = 0
        self._limits_read = False

    def _read_limits(self, r):
        """Riot manda en cada respuesta los límites reales de la key (X-App-Rate-Limit: 20:1,100:120).
        Una key personal permite bastante más que una de desarrollo: así se aprovecha sin adivinar."""
        self._limits_read = True
        raw = r.headers.get("X-App-Rate-Limit", "")
        limits = []
        for part in raw.split(","):
            n, _, t = part.partition(":")
            try:
                limits.append((int(n), float(t)))
            except ValueError:
                return
        if limits:
            self.limiter.set_limits(limits)
            print("Límites de tu API key: " + ", ".join(f"{n} pedidos cada {int(t)} s" for n, t in limits))

    def _get(self, host: str, path: str, params=None, retries: int = 5):
        url = f"https://{host}.api.riotgames.com{path}"
        for attempt in range(retries):
            self.limiter.wait()
            try:
                r = self.session.get(url, params=params, timeout=15)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            self.requests_made += 1
            if not self._limits_read and r.status_code in (200, 404):
                self._read_limits(r)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "10"))
                print(f"  [rate limit] esperando {wait}s...")
                time.sleep(wait + 1)
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                return None
            if r.status_code in (401, 403):
                raise RiotError(
                    f"La API rechazó la key ({r.status_code}). Si es una key de desarrollo, "
                    "vence cada 24 h: generá una nueva en developer.riotgames.com y pegala en Configuración."
                )
            raise RiotError(f"Error {r.status_code} en {path}: {r.text[:200]}")
        raise RiotError(f"No se pudo completar {path} tras {retries} intentos")

    # --- Endpoints ---
    def league_entries(self, tier: str, division: str, page: int = 1):
        return self._get(
            config.PLATFORM,
            f"/lol/league-exp/v4/entries/RANKED_SOLO_5x5/{tier}/{division}",
            {"page": page},
        ) or []

    def match_ids(self, puuid: str, count: int = 20, start_time: int = None):
        params = {"queue": config.RANKED_SOLO_QUEUE, "type": "ranked", "count": count}
        if start_time:
            params["startTime"] = start_time
        return self._get(config.REGION, f"/lol/match/v5/matches/by-puuid/{puuid}/ids", params) or []

    def match(self, match_id: str):
        return self._get(config.REGION, f"/lol/match/v5/matches/{match_id}")

    def account_by_riot_id(self, game_name: str, tag_line: str):
        return self._get(
            config.REGION,
            f"/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}",
        )
