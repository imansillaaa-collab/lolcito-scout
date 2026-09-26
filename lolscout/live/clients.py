"""Conexión con el cliente de LoL que corre en tu PC (no usa la API key ni internet).

- LCU (League Client): la selección de campeones. Puerto y clave salen del archivo "lockfile".
- Live Client Data API (puerto 2999): datos de la partida en curso, los mismos que ves en el marcador (Tab).
Ambas son APIs locales oficiales de Riot; solo leen, no tocan el juego.
"""
import base64
import time
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
        self.cred = None      # (puerto, clave, protocolo) con los que me conecté
        self._cred_t = 0.0

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
        self._cred_t = time.time()
        if not cred:
            self.base = None
            self.cred = None
            return False
        self.cred = cred
        port, password, proto = cred
        self.base = f"{proto}://127.0.0.1:{port}"
        token = base64.b64encode(f"riot:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}
        return True

    def get(self, path: str, timeout: float = 2):
        # si cerraste el LoL y entraste con otra cuenta, el cliente arranca con otra clave: la releo
        if self.base and time.time() - self._cred_t > 15:
            self._cred_t = time.time()
            cred = self._credentials()
            if cred and cred != self.cred:
                self.base = None
        if not self.base and not self.connect():
            return None
        try:
            r = requests.get(self.base + path, headers=self.headers, verify=False, timeout=timeout)
            if r.status_code in (401, 403):   # clave vieja: me reconecto en la próxima llamada
                self.base = None
                return None
            return r.json() if r.status_code == 200 else None
        except requests.Timeout:
            return None  # el cliente tardó (el historial lo pide a los servidores de Riot): se reintenta después
        except requests.RequestException:
            self.base = None  # el cliente se cerró o cambió de puerto
            return None

    def _send(self, method: str, path: str, body=None, timeout: float = 5):
        """POST/DELETE al cliente. Devuelve (ok, respuesta o mensaje de error)."""
        if not self.base and not self.connect():
            return False, "No encuentro el cliente de League of Legends."
        try:
            r = requests.request(method, self.base + path, headers=self.headers, json=body,
                                 verify=False, timeout=timeout)
            if r.status_code in (401, 403):
                self.base = None
                return False, "El cliente rechazó la conexión; probá de nuevo."
            if r.status_code >= 400:
                try:
                    msg = (r.json() or {}).get("message") or r.text[:200]
                except ValueError:
                    msg = r.text[:200]
                return False, f"El cliente respondió {r.status_code}: {msg}"
            try:
                return True, r.json()
            except ValueError:
                return True, None
        except requests.RequestException as e:
            self.base = None
            return False, f"No pude hablar con el cliente ({e.__class__.__name__})."

    # --- Selección de campeones: marcar y bloquear ---
    def draft_action(self, action_id, champion_id, lock=False):
        """Marca el campeón en tu casillero (reversible) y, si lock, lo confirma."""
        path = f"/lol-champ-select/v1/session/actions/{int(action_id)}"
        cid = int(champion_id)
        ok, res = self._send("PATCH", path, {"championId": cid})
        if not ok or not lock:
            return ok, res

        def accion_entera():
            """La acción tal como la tiene el cliente, con el campeón y «completed»: hay clientes que solo
            bloquean si el PATCH trae la acción completa (actorCellId, type, isAllyAction...)."""
            ses = self.champ_select() or {}
            a = next((a for g in ses.get("actions", []) for a in g if a.get("id") == int(action_id)), {})
            return {**a, "championId": cid, "completed": True}

        # El cliente a veces contesta «ok» y no bloquea: pruebo cada forma y verifico en la sesión
        intentos = [("POST", path + "/complete", lambda: {}),
                    ("PATCH", path, lambda: {"championId": cid, "completed": True}),
                    ("PATCH", path, accion_entera)]
        error = None
        for n, (metodo, p, cuerpo) in enumerate(intentos, 1):
            ok, res = self._send(metodo, p, cuerpo())
            print(f"[draft] bloqueo forma {n} ({metodo} {p.rsplit('/', 1)[-1]}): {'ok' if ok else res}", flush=True)
            if not ok:
                error = res
            if self.action_done(action_id, cid, wait=2.0 if ok else 0.6):
                return True, res
        return False, (f"El LoL no confirmó el bloqueo ({error}). Bloquealo a mano en el cliente." if error
                       else "El LoL no confirmó el bloqueo. Bloquealo a mano en el cliente.")

    def action_done(self, action_id, champion_id=None, wait: float = 4.0) -> bool:
        """¿El cliente ya tiene esa acción como bloqueada? Espera un poco a que se actualice.

        El cliente a veces tarda en marcar "completed": también cuenta como bloqueado si la acción
        ya no está en curso con tu campeón, si el campeón aparece en tu casillero o entre los baneos.
        """
        fin = time.time() + wait
        ultimo = None
        while True:
            ses = self.get("/lol-champ-select/v1/session", timeout=3)
            if ses is None:
                # sin respuesta: solo cuenta como bloqueado si de verdad ya no estamos en la selección
                # (antes un pedido lento se tomaba como «ya empezó la partida» y decía «ok» sin bloquear)
                fase = self.phase()
                if fase and fase != "ChampSelect":
                    return True
                ses = {"_sin_respuesta": True}
            local = ses.get("localPlayerCellId")
            for group in ses.get("actions", []):
                for a in group:
                    if a.get("id") == int(action_id):
                        ultimo = a
                        if a.get("completed"):
                            return True
                        if champion_id and a.get("championId") == int(champion_id) and not a.get("isInProgress"):
                            return True
            if champion_id:
                me = next((p for p in ses.get("myTeam", []) if p.get("cellId") == local), {})
                if me.get("championId") == int(champion_id):
                    return True
                bans = ses.get("bans") or {}
                if int(champion_id) in (bans.get("myTeamBans") or []) + (bans.get("theirTeamBans") or []):
                    return True
            if time.time() >= fin:
                print(f"[draft] sin confirmar la acción {action_id}: {ultimo}", flush=True)
                return False
            time.sleep(0.3)

    # --- Páginas de runas ---
    PAGE_PREFIX = "Lolcito runas para "

    def rune_pages(self):
        return self.get("/lol-perks/v1/pages") or []

    def rune_slots_free(self):
        """(páginas propias que se pueden borrar, cuántas entran en total)."""
        inv = self.get("/lol-perks/v1/inventory") or {}
        return inv.get("ownedPageCount")

    def apply_runes(self, name, primary, sub, perks, shards):
        """Crea (o reemplaza) la página de Lolcito en el cliente y la deja seleccionada."""
        pages = self.rune_pages()
        if not isinstance(pages, list):
            return False, "No pude leer tus páginas de runas."
        mias = [p for p in pages if str(p.get("name", "")).startswith(self.PAGE_PREFIX)]
        for p in mias:  # solo borro las que creó Lolcito, nunca las tuyas
            if p.get("isDeletable", True):
                self._send("DELETE", f"/lol-perks/v1/pages/{p['id']}")
        body = {"name": name, "primaryStyleId": int(primary), "subStyleId": int(sub),
                "selectedPerkIds": [int(x) for x in list(perks) + list(shards)], "current": True}
        ok, res = self._send("POST", "/lol-perks/v1/pages", body)
        if ok or "max" not in str(res).lower():
            return ok, res
        # No hay lugar: borro la página tuya que hace más tiempo que no tocás (nunca la que tenés elegida
        # ahora) y creo la de Lolcito en su lugar.
        editables = [p for p in pages if p.get("isDeletable", True) and p.get("isEditable", True)
                     and not str(p.get("name", "")).startswith(self.PAGE_PREFIX)]
        if not editables:
            return False, "No te queda lugar para otra página de runas y no hay ninguna que se pueda borrar."
        editables.sort(key=lambda p: (bool(p.get("current")), p.get("lastModified") or 0))
        vieja = editables[0]
        ok_b, res_b = self._send("DELETE", f"/lol-perks/v1/pages/{vieja['id']}")
        print(f"[runas] sin lugar: borro «{vieja.get('name')}» → {'ok' if ok_b else res_b}", flush=True)
        if not ok_b:
            return False, f"No te queda lugar para otra página de runas y no pude borrar una ({res_b})."
        ok, res = self._send("POST", "/lol-perks/v1/pages", body)
        if ok:
            self.pagina_borrada = vieja.get("name")
        return ok, res

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
