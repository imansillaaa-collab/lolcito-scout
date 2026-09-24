"""Servidor local de la app: asistente en vivo, estadísticas, configuración y actualización de datos.
La interfaz es una página web que se abre en una ventana propia (Edge en modo app)."""
import json
import mimetypes
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import config, db, online
from ..analyze import analyze
from .advisor import draft_advice, game_advice, role_distribution
from .gameplan import GameTracker
from . import postgame as pg
from .history import History, Importer

HERE = Path(__file__).parent
STATIC = HERE / "static"


class Assistant:
    """Consulta el cliente de LoL cada 2 segundos, detecta tu cuenta y guarda el estado para la página."""

    def __init__(self, dd, lcu, live):
        self.dd, self.lcu, self.live = dd, lcu, live
        self.meta, self.duos, self.dist, self.info = {}, [], {}, {}
        self.champs = {}
        self.result = None
        self.simulated = False
        self.db_path = None
        self.role_memory = None
        self.tracker = GameTracker()
        self.recorder = pg.GameRecorder()
        self.history = History(config.DATA_DIR / "cuentas")
        self.importer = Importer(self.history, dd, on_games=self.set_pool)
        self.postgame = None          # resumen de la última partida
        self.postgame_hidden = False  # el usuario lo cerró
        self._pg_fetch = None         # (gameId, hasta cuándo seguir buscando el detalle en el historial)
        self._pg_t = 0.0
        self.account, self.rank, self.pool = None, None, {}
        self.bracket = None
        self._acc_t = self._pool_t = self._stats_t = 0.0
        self.state = {"phase": "idle", "message": "Iniciando..."}
        self.lock = threading.Lock()

    # ---------- estadísticas
    def current_bracket(self):
        if config.BRACKET in online.BRACKETS:
            return config.BRACKET
        return online.bracket_for_tier(self.rank["tier"] if self.rank else "")

    def load_stats(self, db_path=None, force=False):
        db_path = db_path if db_path is not None else self.db_path
        err, source = None, "local"
        if not self.simulated and config.STATS_SOURCE == "online":
            source = "online"
            self.bracket = self.current_bracket()
            result, err = online.load(self.bracket, force=force)
            result = result or {"roles": {}, "duos": [], "dist": {}, "matches": 0, "patches": []}
            dist = {int(k): v for k, v in result.get("dist", {}).items()}
        else:
            conn = db.connect(db_path)
            result = analyze(conn, self.dd)
            dist = role_distribution(conn)
            conn.close()
        self.result = result
        self.meta, self.duos, self.dist = result.get("roles", {}), result.get("duos", []), dist
        # ítems por campeón juntando todos los roles (para la build en partida)
        self.champs = {int(k): v for k, v in (result.get("champs") or {}).items()}
        pg.ROLE_DIST.clear()
        for cid, d in (dist or {}).items():
            tot = sum(d.values()) or 1
            pg.ROLE_DIST[int(cid)] = {r: v / tot for r, v in d.items()}
        self.info = {"patch": ", ".join(result.get("patches", [])), "matches": result.get("matches", 0),
                     "simulated": self.simulated, "source": source, "error": err,
                     "bracket": self.bracket, "bracketName": online.BRACKET_NAMES.get(self.bracket or "", ""),
                     "generated": result.get("generated")}
        self._stats_t = time.time()

    def use_sources(self, lcu, live, simulated=False, db_path=None):
        self.lcu, self.live, self.simulated = lcu, live, simulated
        self.db_path = db_path
        self.account, self.rank, self.pool = None, None, {}
        self._acc_t = self._pool_t = 0.0
        self.recorder.reset()
        self.tracker.reset()
        self.postgame, self.postgame_hidden, self._pg_fetch = None, False, None
        if simulated:
            self.history = History(config.DATA_DIR / "simulacion" / "cuentas")
        else:
            self.history = History(config.DATA_DIR / "cuentas")
        self.importer = Importer(self.history, self.dd, on_games=self.set_pool)
        self.load_stats(db_path)

    # ---------- tu cuenta (sale del cliente de LoL, sin key)
    def refresh_account(self):
        now = time.time()
        if now - self._acc_t < 30:
            return
        self._acc_t = now
        s = self.lcu.summoner()
        if not s:
            return
        new_acc = {"name": s.get("gameName") or s.get("displayName") or "", "tag": s.get("tagLine", ""),
                   "puuid": s.get("puuid"), "level": s.get("summonerLevel"), "icon": s.get("profileIconId")}
        changed = not self.account or self.account.get("puuid") != new_acc["puuid"]
        self.account = new_acc
        old_bracket = self.current_bracket()
        self.rank = self.lcu.ranked()
        view = self.account_view()
        self.history.upsert_account({k: view.get(k) for k in ("puuid", "name", "tag", "iconUrl", "level", "rank")})
        self.importer.maybe_start(self.lcu, self.account, force=changed)
        if config.STATS_SOURCE == "online" and not self.simulated and self.current_bracket() != old_bracket:
            self.load_stats()

    def set_pool(self, puuid, games):
        """Tus campeones de las últimas partidas (sale de la misma lista que el historial)."""
        if puuid != (self.account or {}).get("puuid"):
            return
        pool = {}
        for g in games:
            p = (g.get("participants") or [{}])[0]
            cid = p.get("championId")
            if cid and g.get("mapId", 11) == 11:
                c = pool.setdefault(cid, [0, 0])
                c[0] += 1
                c[1] += int(bool((p.get("stats") or {}).get("win")))
        self.pool = pool

    def account_view(self):
        if not self.account:
            return None
        rank = None
        if self.rank:
            rank = f"{online.TIER_ES.get(self.rank['tier'], self.rank['tier'].title())} {self.rank['division']}".strip()
            rank += f" · {self.rank['lp']} LP"
        return {**self.account, "rank": rank or "Sin rango en Solo/Dúo",
                "iconUrl": f"https://ddragon.leagueoflegends.com/cdn/{self.dd.version}/img/profileicon/{self.account['icon']}.png"
                if self.account.get("icon") is not None else "",
                "bracket": self.current_bracket(), "bracketName": online.BRACKET_NAMES.get(self.current_bracket(), ""),
                "pool": self.pool_view()}

    def main_role(self, cid):
        d = self.dist.get(cid) or {}
        return max(d, key=d.get) if d else None

    def pool_view(self, limit=8):
        out = []
        for cid, (g, w) in sorted(self.pool.items(), key=lambda kv: -kv[1][0])[:limit]:
            role = self.main_role(cid)
            meta = next((c for c in self.meta.get(role, []) if c["id"] == cid), None) if role else None
            out.append({"id": cid, "name": self.dd.champ_name(cid), "img": self.dd.champ_img(cid),
                        "games": g, "wr": w / g, "role": config.ROLE_NAMES.get(role, ""),
                        "tier": meta["tier"] if meta else "?"})
        return out

    # ---------- ciclo
    def tick(self):
        game = self.live.game()
        st = None
        if game:
            ended = pg.game_ended(game)
            if ended and self.recorder.game is None and self.postgame:  # ya armé el resumen de esta partida
                st = self.show_postgame() if not self.postgame_hidden else {
                    "phase": "idle", "message": "Partida terminada", "detail": "GG."}
            else:
                st = game_advice(game, self.meta, self.dist, self.dd, self.role_memory, self.tracker,
                                 champs=self.champs)
                self.recorder.update(game, st, self.lcu)
                if ended:  # pantalla de victoria/derrota: ya muestro el resumen
                    self.finish_game()
                    st = self.show_postgame()
        else:
            if self.recorder.game is not None:  # se cerró la partida
                self.finish_game()
            phase = self.lcu.phase()
            if phase is not None:
                self.refresh_account()
            self.enrich_postgame()
            if phase == "ChampSelect":
                self.postgame_hidden = bool(self.postgame)
                st = draft_advice(self.lcu.champ_select() or {}, self.meta, self.duos, self.dist, self.dd,
                                  default_role=config.ROLES[0] if config.ROLES else "BOTTOM", pool=self.pool,
                                  champs=self.champs)
                self.role_memory = st["myRole"]
            elif self.postgame and not self.postgame_hidden and phase not in ("InProgress", "GameStart", "Reconnect"):
                st = self.show_postgame(phase)
            elif phase is None:
                st = {"phase": "idle", "message": "Esperando al cliente de League of Legends",
                      "detail": "Abrí el LoL e iniciá sesión: Lolcito Scout detecta tu cuenta solo."}
            else:
                msgs = {"Lobby": ("En el lobby", "Cuando entres a la selección de campeones te muestro qué pickear."),
                        "Matchmaking": ("Buscando partida", ""), "ReadyCheck": ("¡Partida encontrada!", "Aceptala."),
                        "InProgress": ("Cargando la partida", ""), "EndOfGame": ("Partida terminada", "GG."),
                        "None": ("Cliente abierto", "Cuando entres a la selección de campeones te muestro qué pickear.")}
                title, detail = msgs.get(phase, ("Cliente abierto", ""))
                st = {"phase": "idle", "message": title, "detail": detail}
            if st.get("phase") == "idle":
                st["lastGame"] = bool(self.postgame or (not self.simulated and pg.SAVE.exists()))
                st["hist"] = {"version": self.history.version, "importing": self.importer.status,
                              "current": (self.account or {}).get("puuid")}
        if time.time() - self._stats_t > online.MAX_AGE:
            self.load_stats()
        st["info"] = self.info
        st["account"] = self.account_view()
        with self.lock:
            self.state = st

    # ---------- fin de partida
    def finish_game(self):
        rec = self.recorder
        if rec.game is None:
            return
        puuid = (self.account or {}).get("puuid")
        summary = None
        try:
            summary = pg.summarize(self.dd, rec, puuid=puuid)
        except Exception:
            traceback.print_exc()
        if summary:
            summary["_live_t"] = rec.game.get("gameData", {}).get("gameTime")
            summary["_rec"] = rec  # para rehacerlo cuando llegue el historial
            self.postgame, self.postgame_hidden = summary, False
            if not self.simulated:
                pg.save({k: v for k, v in summary.items() if not k.startswith("_")})
            self.history.save((self.account or {}).get("puuid"), summary)
            self._pg_fetch = (rec.game_id, time.time() + 240)
        self.tracker.reset()
        new = pg.GameRecorder()
        self.recorder = new

    def enrich_postgame(self):
        """El historial del cliente tarda un poco en tener la partida: lo sigo buscando unos minutos."""
        if not self._pg_fetch or not self.postgame or time.time() - self._pg_t < 8 or getattr(self, "_pg_busy", False):
            return
        self._pg_t = time.time()
        self._pg_busy = True
        threading.Thread(target=self._enrich_run, daemon=True).start()

    def _enrich_run(self):
        try:
            self._enrich_once()
        finally:
            self._pg_busy = False
            self._pg_t = time.time()

    def _enrich_once(self):
        if not self._pg_fetch or not self.postgame:
            return
        gid, until = self._pg_fetch
        if time.time() > until:
            self._pg_fetch = None
            return
        mh, tl = pg.fetch_match(self.lcu, gid, (self.account or {}).get("puuid"))
        if not mh:
            return
        try:
            summary = pg.summarize(self.dd, self.postgame.get("_rec"), mh=mh, timeline=tl,
                                   puuid=(self.account or {}).get("puuid"))
        except Exception:
            traceback.print_exc()
            summary = None
        if summary:
            summary["_live_t"] = self.postgame.get("_live_t")
            summary["_rec"] = self.postgame.get("_rec")
            old_id, old_created = self.postgame.get("gameId"), self.postgame.get("created")
            self.postgame = summary
            puuid = (self.account or {}).get("puuid")
            if puuid and not old_id:  # la había guardado sin número de partida
                self.history.forget(puuid, f"t{old_created}")
            self.history.save(puuid, summary)
            if not self.simulated:
                pg.save({k: v for k, v in summary.items() if not k.startswith("_")})
        self._pg_fetch = None

    # ---------- banear / pickear desde Lolcito
    def draft_action(self, body):
        """Marca (o bloquea) un campeón en la selección. El bloqueo solo pasa si lo pedís explícito.

        El turno se lee del cliente en el momento del clic (no del estado de la pantalla, que puede
        tener un par de segundos): así no se pierde el turno por un dato viejo.
        """
        from .advisor import my_action, my_pending_pick
        cid = int(body.get("championId") or 0)
        lock = bool(body.get("lock"))
        if not cid:
            return {"ok": False, "error": "Falta el campeón."}
        nombre = self.dd.champ_name(cid)
        if self.simulated:
            st = self.get_state()
            if st.get("phase") != "draft":
                return {"ok": False, "error": "Ya no estás en la selección de campeones."}
            if not st.get("myTurn") and (lock or not st.get("canPrepick")):
                return {"ok": False, "error": "No es tu turno todavía: esperá a que te toque."}
            verbo = "banear" if st.get("step") == "ban" else "pickear"
            return {"ok": True, "simulated": True,
                    "msg": f"{'Bloqueado' if lock else 'Marcado'}: {nombre} ({verbo})"}
        if not hasattr(self.lcu, "draft_action"):
            return {"ok": False, "error": "No encuentro el cliente de League of Legends."}
        session = self.lcu.champ_select()
        if not session:
            return {"ok": False, "error": "Ya no estás en la selección de campeones."}
        local = session.get("localPlayerCellId")
        accion = my_action(session, local)
        if not accion:
            pre = my_pending_pick(session, local)
            if lock or not pre:
                return {"ok": False, "error": "No es tu turno todavía: esperá a que te toque."}
            ok, res = self.lcu.draft_action(pre["id"], cid, False)
            print(f"[draft] pre-pick {nombre} (acción {pre['id']}): {'ok' if ok else res}", flush=True)
            return ({"ok": True, "msg": f"{nombre} pre-pickeado: tus aliados ya lo ven"} if ok
                    else {"ok": False, "error": str(res)})
        ok, res = self.lcu.draft_action(accion["id"], cid, lock)
        print(f"[draft] {'bloquear' if lock else 'marcar'} {nombre} ({accion['type']}, acción {accion['id']}): "
              f"{'ok' if ok else res}", flush=True)
        if not ok:
            return {"ok": False, "error": str(res)}
        if lock and hasattr(self.lcu, "action_done") and not self.lcu.action_done(accion["id"], cid):
            # el cliente dijo que sí pero todavía no lo muestra: no es un error, solo aviso que lo mire
            return {"ok": True, "msg": f"{nombre}: el cliente lo aceptó, fijate que figure bloqueado"}
        es_ban = accion["type"] == "ban"
        if lock:
            return {"ok": True, "msg": f"{nombre} {'baneado' if es_ban else 'bloqueado'}"}
        return {"ok": True, "msg": f"{nombre} marcado en el cliente"}

    # ---------- runas al cliente de LoL
    def apply_runes(self, body):
        """Manda al LoL la página de runas que elegiste en Lolcito."""
        st = self.get_state()
        opciones = st.get("runes") or []
        elegida = next((o for o in opciones if o.get("id") == body.get("id")), None)
        if not elegida:
            return {"ok": False, "error": "Esa página ya no está disponible; volvé a la selección de campeones."}
        champ = (st.get("runeChamp") or {}).get("name") or "tu campeón"
        nombre = f"{self.lcu.PAGE_PREFIX}{champ}" if hasattr(self.lcu, "PAGE_PREFIX") else f"Lolcito runas para {champ}"
        if self.simulated:
            return {"ok": True, "name": nombre, "simulated": True}
        if not hasattr(self.lcu, "apply_runes"):
            return {"ok": False, "error": "No encuentro el cliente de League of Legends."}
        ok, res = self.lcu.apply_runes(nombre, elegida["primary"], elegida["sub"],
                                       elegida["perks"], elegida["shards"])
        if not ok:
            return {"ok": False, "error": str(res)}
        return {"ok": True, "name": nombre}

    def open_last_game(self):
        """Botón «Ver tu última partida»: la guardada, o la última del historial del cliente."""
        if not self.postgame and not self.simulated:
            saved = pg.load_saved()
            if saved:
                self.postgame = saved
            else:
                mh, tl = pg.fetch_match(self.lcu, None, (self.account or {}).get("puuid"))
                if mh:
                    self.postgame = pg.summarize(self.dd, None, mh=mh, timeline=tl, puuid=(self.account or {}).get("puuid"))
        self.postgame_hidden = False
        return bool(self.postgame)

    def show_postgame(self, phase=None):
        st = {k: v for k, v in self.postgame.items() if not k.startswith("_")}
        st["clientPhase"] = phase
        if self._pg_fetch and not st.get("complete"):
            st["loadingMore"] = True
        return st

    def loop(self):
        while True:
            try:
                self.tick()
            except Exception as e:
                traceback.print_exc()
                with self.lock:
                    self.state = {"phase": "idle", "message": "Error leyendo el juego", "detail": str(e),
                                  "info": self.info, "account": None}
            # en la selección de campeones los turnos duran 30 segundos: miro el cliente más seguido
            time.sleep(0.7 if self.state.get("phase") == "draft" else 2)

    def get_state(self):
        with self.lock:
            return self.state


class Updater:
    """Escaneo de partidas en segundo plano (el mismo que 'python main.py diario')."""

    STAMP = config.DATA_DIR / "ultima_actualizacion.txt"

    def __init__(self, on_done):
        self.on_done = on_done
        self.running = False
        self.lines = []

    def last(self):
        try:
            return float(self.STAMP.read_text())
        except (OSError, ValueError):
            return 0.0

    def status(self):
        last = self.last()
        return {"running": self.running, "log": self.lines[-14:],
                "last": datetime.fromtimestamp(last).strftime("%d/%m %H:%M") if last else None,
                "hasKey": bool(config.RIOT_API_KEY)}

    def log(self, msg):
        self.lines.append(str(msg))
        print(msg)

    def start(self):
        if self.running:
            return False
        self.running, self.lines = True, []
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self):
        from ..collect import collect, collect_mine, my_puuid
        from ..riot import RiotClient, RiotError
        try:
            conn = db.connect()
            client = RiotClient()
            collect(client, conn, log=self.log)
            puuid = my_puuid(client)
            if puuid:
                (config.DATA_DIR / "mi_puuid.txt").write_text(puuid)
                collect_mine(client, conn, puuid, log=self.log)
            conn.close()
            self.STAMP.write_text(str(time.time()))
            self.log("Listo. Estadísticas actualizadas.")
            self.on_done()
        except RiotError as e:
            self.log(f"ERROR: {e}")
        except Exception as e:
            traceback.print_exc()
            self.log(f"ERROR inesperado: {e}")
        finally:
            self.running = False


def build_report_html(dd, assistant) -> str:
    from ..report import TEMPLATE, _lookup
    result = assistant.result
    if not result or not result.get("matches"):
        return None
    result = {**result, "roles": {r: result["roles"][r] for r in ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
                                  if r in result.get("roles", {})}}
    me = []
    for p in assistant.pool_view(limit=20):
        role = next((k for k, v in config.ROLE_NAMES.items() if v == p["role"]), "")
        me.append({"role": role, "id": p["id"], "games": p["games"], "wr": p["wr"], "tier": p["tier"]})
    result["me"] = me or None
    tiers = online.BRACKETS.get(assistant.bracket or "", config.TIERS) if assistant.info.get("source") == "online" else config.TIERS
    tiers = [online.TIER_ES.get(t, t) for t in tiers]
    payload = {**result, "lookup": _lookup(result, dd), "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
               "tiers": tiers, "platform": config.PLATFORM.upper(), "roleNames": config.ROLE_NAMES}
    return TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class App:
    def __init__(self, dd, assistant: Assistant, lan=False, quit_when_closed=False):
        self.dd, self.assistant, self.lan = dd, assistant, lan
        self.updater = Updater(on_done=lambda: assistant.load_stats(assistant.db_path))
        self.quit_when_closed = quit_when_closed
        self.last_ping = None
        self.started = time.time()

    # ---- rutas
    def api(self, method, path, body):
        if path == "/api/ping":
            self.last_ping = time.time()
            return {"app": "lolscout"}
        if path == "/api/state":
            return self.assistant.get_state()
        if path == "/api/settings":
            if method == "POST":
                config.save_settings(body)
                self.assistant.load_stats(force=True)
            s = config.current_settings()
            s["TIERS"], s["ROLES"] = ",".join(s["TIERS"]), ",".join(s["ROLES"])
            s["dataDir"] = str(config.DATA_DIR)
            s["account"] = self.assistant.account_view()
            s["info"] = self.assistant.info
            s["lanUrl"] = f"http://{lan_ip()}:{self.port}" if self.lan else None
            return s
        if path == "/api/update":
            if method == "POST":
                self.updater.start()
            return self.updater.status()
        if path == "/api/stats" and method == "POST":
            self.assistant.load_stats(force=True)
            return self.assistant.info
        if path == "/api/simulate" and method == "POST":
            self.simulate(body.get("mode", "partida"))
            return {"ok": True}
        if path == "/api/cuentas":
            cur = (self.assistant.account or {}).get("puuid")
            accs = self.assistant.history.accounts()
            return {"accounts": [{**a, "current": a.get("puuid") == cur} for a in accs], "current": cur}
        if path == "/api/importar" and method == "POST":
            a = self.assistant
            a.importer.maybe_start(a.lcu, a.account, force=True)
            return {"ok": bool(a.account)}
        if path == "/api/historial":
            return self.assistant.history.games(body.get("puuid") or "")
        if path == "/api/partida":
            return self.assistant.history.get(body.get("puuid") or "", body.get("id") or "") or {"error": "No encontré esa partida."}
        if path == "/api/postgame" and method == "POST":
            if body.get("action") == "close":
                self.assistant.postgame_hidden = True
                return {"ok": True}
            return {"ok": self.assistant.open_last_game()}
        if path == "/api/draft" and method == "POST":
            return self.assistant.draft_action(body)
        if path == "/api/runas" and method == "POST":
            return self.assistant.apply_runes(body)
        if path == "/api/layout" and method == "POST":
            config.save_settings({"LAYOUT": body.get("layout") or {}})
            return {"ok": True}
        if path == "/api/real" and method == "POST":
            from .clients import LCU, LiveClient
            self.assistant.use_sources(LCU(), LiveClient(), simulated=False)
            return {"ok": True}
        return None

    def simulate(self, mode):
        from ..demo import generate
        from .mock import MockLCU, MockLiveClient, restart
        demo_db = config.DATA_DIR / "demo.db"
        conn = db.connect(demo_db)
        if not conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]:
            generate(conn, self.dd)
        conn.close()
        restart(mode)
        lcu, live = MockLCU(self.dd), MockLiveClient(self.dd)
        if mode in ("draft", "inicio"):
            live.game = lambda: None
        import shutil
        shutil.rmtree(config.DATA_DIR / "simulacion", ignore_errors=True)
        self.assistant.use_sources(lcu, live, simulated=True, db_path=demo_db)
        self.seed_simulated_history()

    def seed_simulated_history(self):
        """Una segunda cuenta inventada, para ver cómo se eligen las cuentas en el historial."""
        from .mock import SMURF_GAMES, gen_match
        h = self.assistant.history
        h.upsert_account({"puuid": "demo2", "name": "OtraCuenta", "tag": "LAS", "level": 64, "rank": "Oro I · 12 LP",
                          "iconUrl": f"https://ddragon.leagueoflegends.com/cdn/{self.dd.version}/img/profileicon/4568.png"})
        for g in SMURF_GAMES:
            mh, tl = gen_match(self.dd, *g, puuid="demo2")
            s = pg.summarize(self.dd, None, mh=mh, timeline=tl, puuid="demo2")
            h.save("demo2", s)

    def watchdog(self):
        """Cierra el programa cuando se cierra la ventana (la página deja de dar señales por 90 segundos)."""
        while True:
            time.sleep(5)
            if self.last_ping and time.time() - self.last_ping > 90:
                print("Ventana cerrada: salgo.")
                import os
                os._exit(0)

    def serve(self, port=8765):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, body, ctype):
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass  # la ventana canceló la carga (por ejemplo al recargar): no es un error

            def _route(self, method):
                app.last_ping = time.time()   # cualquier pedido significa que la ventana sigue abierta
                path, _, query = self.path.partition("?")
                from urllib.parse import parse_qs
                body = {k: v[-1] for k, v in parse_qs(query).items()}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    try:
                        body = json.loads(self.rfile.read(n) or b"{}")
                    except ValueError:
                        body = {}
                if path.startswith("/api/"):
                    try:
                        res = app.api(method, path, body)
                    except Exception as e:
                        traceback.print_exc()
                        res = {"error": str(e)}
                    if res is None:
                        return self._send(404, b"{}", "application/json")
                    return self._send(200, json.dumps(res, ensure_ascii=False, default=list).encode(),
                                      "application/json; charset=utf-8")
                if path == "/reporte":
                    html = build_report_html(app.dd, app.assistant)
                    if html is None:
                        html = ("<body style='background:#010a13;color:#a09b8c;font-family:sans-serif;"
                                "padding:40px'>Todavía no hay estadísticas descargadas. Revisá tu conexión a internet "
                                "y tocá «Descargar ahora» en Configuración.</body>")
                    return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                if path.startswith("/static/"):
                    f = (STATIC / path[len("/static/"):]).resolve()
                    if STATIC.resolve() in f.parents and f.is_file():
                        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                        ctype = {".ttf": "font/ttf", ".otf": "font/otf", ".png": "image/png"}.get(f.suffix, ctype)
                        return self._send(200, f.read_bytes(), ctype)
                    return self._send(404, b"", "text/plain")
                page = (HERE / "page.html").read_text(encoding="utf-8")
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def log_message(self, *args):
                pass

        host = "0.0.0.0" if self.lan else "127.0.0.1"
        httpd = ThreadingHTTPServer((host, port), Handler)
        self.port = port
        threading.Thread(target=self.assistant.loop, daemon=True).start()
        if self.quit_when_closed:
            threading.Thread(target=self.watchdog, daemon=True).start()
        if config.STATS_SOURCE == "local" and config.AUTO_UPDATE and config.RIOT_API_KEY and time.time() - self.updater.last() > 20 * 3600:
            self.updater.start()
        print(f"Lolcito Scout funcionando en http://localhost:{port}")
        if self.lan:
            print(f"Desde el celular (misma WiFi): http://{lan_ip()}:{port}")
        sys.stdout.flush()
        httpd.serve_forever()
