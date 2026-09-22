"""Historial de partidas por cuenta (todo guardado en tu PC).

Cada cuenta con la que abriste el LoL queda guardada en cuentas/cuentas.json, y cada partida en
cuentas/<cuenta>/<gameId>.json con el mismo resumen que ves al terminar (estadísticas y devoluciones).
Las partidas se importan del historial del cliente de LoL (solo el de la cuenta con la que estás logueado).
"""
import json
import re
import threading
import time
import traceback

from . import postgame as pg

KEEP = 200  # partidas guardadas por cuenta


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(s))[:80]


def compact(s):
    """Lo que se muestra en la lista del historial."""
    m = s.get("me", {})
    return {"v": s.get("v", 1), "gameId": s.get("gameId"), "created": s.get("created"), "result": s.get("result"),
            "resultText": s.get("resultText"), "remake": s.get("remake"), "queue": s.get("queue"),
            "durationText": s.get("durationText"), "grade": s.get("grade"), "score": s.get("score"),
            "champ": {"id": m.get("id"), "name": m.get("name"), "img": m.get("img")}, "role": m.get("roleEs"),
            "k": m.get("k"), "d": m.get("d"), "a": m.get("a"), "cs": m.get("cs"), "csMin": m.get("csMin"),
            "kp": m.get("kp"), "kda": m.get("kda"), "items": m.get("items", [])[:7],
            "tip": next((f["title"] for f in s.get("feedback", []) if f["tone"] == "bad"), None),
            "best": next((f["title"] for f in s.get("feedback", []) if f["tone"] == "good"), None)}


class History:
    def __init__(self, base):
        self.base = base
        self.lock = threading.Lock()
        self.version = 0  # sube cada vez que se guarda una partida (la página recarga la lista)

    # ---- cuentas
    def _acc_file(self):
        return self.base / "cuentas.json"

    def accounts(self):
        try:
            return json.loads(self._acc_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def upsert_account(self, acc):
        if not acc or not acc.get("puuid"):
            return
        with self.lock:
            self.base.mkdir(parents=True, exist_ok=True)
            accs = [a for a in self.accounts() if a.get("puuid") != acc["puuid"]]
            accs.insert(0, {**acc, "lastSeen": int(time.time())})
            self._acc_file().write_text(json.dumps(accs, ensure_ascii=False), encoding="utf-8")

    # ---- partidas
    def _dir(self, puuid):
        return self.base / _safe(puuid)

    def _index(self, puuid):
        try:
            return json.loads((self._dir(puuid) / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def has(self, puuid, gid):
        return (self._dir(puuid) / f"{_safe(gid)}.json").exists()

    def up_to_date(self, puuid, gid):
        """Guardada y evaluada con la versión actual (si no, se vuelve a importar)."""
        return any(str(x.get("gameId")) == str(gid) and x.get("v", 1) >= pg.VERSION for x in self._index(puuid))

    def save(self, puuid, summary):
        if not puuid or not summary:
            return
        gid = summary.get("gameId") or f"t{summary.get('created') or int(time.time() * 1000)}"
        summary = {k: v for k, v in summary.items() if not k.startswith("_")}
        summary["gameId"] = gid
        with self.lock:
            d = self._dir(puuid)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{_safe(gid)}.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
            idx = [x for x in self._index(puuid) if str(x.get("gameId")) != str(gid)]
            idx.append(compact(summary))
            idx.sort(key=lambda x: x.get("created") or 0, reverse=True)
            for old in idx[KEEP:]:
                try:
                    (d / f"{_safe(old['gameId'])}.json").unlink()
                except OSError:
                    pass
            (d / "index.json").write_text(json.dumps(idx[:KEEP], ensure_ascii=False), encoding="utf-8")
            self.version += 1

    def forget(self, puuid, gid):
        """Borra una partida guardada provisoriamente (sin gameId) cuando llega la versión completa."""
        with self.lock:
            d = self._dir(puuid)
            try:
                (d / f"{_safe(gid)}.json").unlink()
            except OSError:
                pass
            idx = [x for x in self._index(puuid) if str(x.get("gameId")) != str(gid)]
            if d.exists():
                (d / "index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")

    def games(self, puuid):
        idx = self._index(puuid)
        done = [x for x in idx if x.get("result") and not x.get("remake")]
        wins = sum(1 for x in done if x["result"] == "win")
        scores = [x["score"] for x in done if x.get("score") is not None]
        champs = {}
        for x in done:
            c = champs.setdefault(x["champ"]["id"], {**x["champ"], "games": 0, "wins": 0})
            c["games"] += 1
            c["wins"] += x["result"] == "win"
        return {"games": idx, "wins": wins, "losses": len(done) - wins,
                "avgScore": round(sum(scores) / len(scores)) if scores else None,
                "avgGrade": next((g for th, g in pg.GRADES if scores and sum(scores) / len(scores) / 100 >= th), None),
                "champs": sorted(champs.values(), key=lambda c: -c["games"])[:5]}

    def get(self, puuid, gid):
        try:
            return json.loads((self._dir(puuid) / f"{_safe(gid)}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


class Importer:
    """Trae del cliente de LoL las últimas partidas de la cuenta logueada que todavía no están guardadas."""

    def __init__(self, history, dd, on_games=None):
        self.history, self.dd, self.on_games = history, dd, on_games
        self.running = False
        self.last = {}  # puuid -> momento de la última importación
        self.ok = {}    # puuid -> si ya pudo traer la lista alguna vez
        self.status = ""

    def maybe_start(self, lcu, account, force=False):
        puuid = (account or {}).get("puuid")
        if not puuid or self.running:
            return
        wait = 600 if self.ok.get(puuid) else 45  # si no pudo traer nada, reintenta pronto
        if not force and time.time() - self.last.get(puuid, 0) < wait:
            return
        self.last[puuid] = time.time()
        self.running = True
        threading.Thread(target=self._run, args=(lcu, puuid), daemon=True).start()

    def _get(self, lcu, path):
        try:
            return lcu.get(path, timeout=20)
        except TypeError:  # clientes simulados
            return lcu.get(path)

    def _run(self, lcu, puuid, count=20):
        try:
            self.status = "Buscando tus partidas en el cliente de LoL…"
            if hasattr(lcu, "match_list"):
                games = lcu.match_list(count, puuid)
            else:
                data = lcu.get(f"/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex={count}") or {}
                games = ((data.get("games") or {}).get("games")) or []
            print(f"Historial: el cliente devolvió {len(games)} partidas")
            if not games:
                return
            self.ok[puuid] = True
            if self.on_games:
                self.on_games(puuid, games)
            new = [g for g in games if g.get("mapId", 11) == 11 and g.get("gameId") and not self.history.up_to_date(puuid, g["gameId"])]
            saved = 0
            for i, g in enumerate(new):
                self.status = f"Importando partidas {i + 1}/{len(new)}…"
                mh = self._get(lcu, f"/lol-match-history/v1/games/{g['gameId']}")
                if not mh or not mh.get("participants"):
                    mh = g if g.get("participants") and len(g["participants"]) >= 10 else None
                if not mh:
                    print(f"Historial: no pude leer la partida {g['gameId']}")
                    continue
                tl = self._get(lcu, f"/lol-match-history/v1/game-timelines/{g['gameId']}")
                try:
                    s = pg.summarize(self.dd, None, mh=mh, timeline=tl if tl and tl.get("frames") else None, puuid=puuid)
                except Exception:
                    traceback.print_exc()
                    s = None
                if s:
                    self.history.save(puuid, s)
                    saved += 1
            print(f"Historial: {saved} partidas nuevas guardadas")
        except Exception:
            traceback.print_exc()
        finally:
            self.status = ""
            self.running = False
