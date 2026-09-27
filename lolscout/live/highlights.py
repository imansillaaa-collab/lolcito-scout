"""Highlights: graba la pantalla mientras jugás y guarda clips de tus mejores momentos.

Cómo funciona:
- ffmpeg (se baja una sola vez, ~190 MB, de las compilaciones oficiales de BtbN en GitHub, verificando la suma
  sha256) graba el monitor principal en 720p30 en tramos de 4 segundos. Solo se guardan los últimos ~100
  segundos: lo anterior se borra solo, así no se llena el disco.
- Con la placa de video (NVIDIA/AMD/Intel) casi no usa procesador; si no hay, usa x264 «ultrafast».
- Los eventos de la partida (Live Client Data API: kills, multikills, first blood, ace, robos de objetivos)
  marcan los momentos; los que valen la pena se cortan en un MP4 con su miniatura en highlights/clips.
- Se puede apagar desde la solapa Highlights o Configuración (config.HIGHLIGHTS).
Sin audio por ahora (capturar el sonido de Windows con ffmpeg requiere un dispositivo extra).
"""
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .. import config

VERSION_FFMPEG = "ffmpeg-n8.1-latest-win64-gpl-8.1.zip"   # la 9.x pide drivers de NVIDIA 610+
URL_FFMPEG = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/{VERSION_FFMPEG}"
URL_SUMAS = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256"
TRAMO = 4                 # segundos por tramo grabado
GUARDAR = 100             # segundos de grabación que se conservan hacia atrás
ANTES, DESPUES = 12, 4    # segundos de clip antes y después de cada momento
MIN_PUNTOS = 20           # lo que tiene que valer un momento para guardarlo
MAX_CLIPS = 200           # más que esto: se borran los más viejos
SIN_VENTANA = 0x08000000

ENCODERS = {
    "h264_nvenc": (["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-b:v", "5M", "-g", "60"], "la placa NVIDIA"),
    "h264_amf": (["-c:v", "h264_amf", "-quality", "speed", "-b:v", "5M", "-g", "60"], "la placa AMD"),
    "h264_qsv": (["-c:v", "h264_qsv", "-preset", "veryfast", "-b:v", "5M", "-g", "60"], "el video de Intel"),
    "libx264": (["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "28", "-g", "60"],
                "el procesador"),
}
MULTI = {2: ("Doble kill", 40), 3: ("Triple kill", 60), 4: ("Cuádruple kill", 80), 5: ("PENTAKILL", 100)}
OBJ_ES = {"DragonKill": "el dragón", "BaronKill": "el Barón", "HeraldKill": "el Heraldo", "HordeKill": "las larvas"}


_JOB = None


def _atar_a_lolcito(proc):
    """Mete a ffmpeg en un «Job» de Windows que se cierra con Lolcito: si Lolcito se cierra de golpe (o se
    reinicia para actualizarse), Windows corta la grabación sola en vez de dejarla llenando el disco."""
    global _JOB
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        if _JOB is None:
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            job = k32.CreateJobObjectW(None, None)

            class LIM(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IOC(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("R", "W", "O", "RT", "WT", "OT")]

            class EXT(ctypes.Structure):
                _fields_ = [("Basic", LIM), ("Io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]
            info = EXT()
            info.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
            _JOB = job
        k32.AssignProcessToJobObject(wintypes.HANDLE(_JOB), wintypes.HANDLE(int(proc._handle)))
    except Exception as e:  # noqa: BLE001
        print(f"[highlights] no pude atar ffmpeg a Lolcito: {e}", flush=True)


def _norm(n):
    return (n or "").split("#")[0].strip().lower()


class Highlights:
    def __init__(self):
        self.dir = config.DATA_DIR / "highlights"
        self.clips = self.dir / "clips"
        self.buffer = self.dir / "buffer"
        self.bin = self.dir / "ffmpeg.exe"
        for d in (self.clips, self.buffer):
            d.mkdir(parents=True, exist_ok=True)
        self.proc = None
        self.encoder = self._leer_encoder()
        self.estado = "listo" if self.bin.exists() and self.encoder else "falta"
        self.progreso, self.error = 0, ""
        self._offset = None          # reloj de pared - tiempo de partida
        self._hechos = set()         # momentos ya recortados (por su inicio)
        self._pendientes = []        # (desde_pared, hasta_pared, info)
        self._lock = threading.Lock()
        self._partida_t = None

    # ---------- preparar ffmpeg
    def _leer_encoder(self):
        f = self.dir / "encoder.txt"
        return f.read_text(encoding="utf-8").strip() if f.exists() else None

    def preparar(self):
        """Si está prendido y falta ffmpeg, lo baja en segundo plano (una sola vez)."""
        if not config.HIGHLIGHTS or self.estado in ("bajando", "probando") or os.name != "nt":
            return
        if self.bin.exists() and self.encoder:
            self.estado = "listo"
            return
        threading.Thread(target=self._preparar, daemon=True).start()

    def _preparar(self):
        try:
            if not self.bin.exists():
                self.estado, self.progreso, self.error = "bajando", 0, ""
                zpath = self.dir / "ffmpeg.zip"
                req = urllib.request.Request(URL_FFMPEG, headers={"User-Agent": "LolcitoScout"})
                h = hashlib.sha256()
                with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    bajado = 0
                    while True:
                        trozo = r.read(1 << 20)
                        if not trozo:
                            break
                        f.write(trozo)
                        h.update(trozo)
                        bajado += len(trozo)
                        if total:
                            self.progreso = int(bajado * 100 / total)
                sumas = urllib.request.urlopen(urllib.request.Request(URL_SUMAS, headers={"User-Agent": "LolcitoScout"}),
                                               timeout=30).read().decode()
                esperado = next((ln.split()[0] for ln in sumas.splitlines() if ln.strip().endswith(VERSION_FFMPEG)), None)
                if not esperado or esperado.lower() != h.hexdigest():
                    zpath.unlink(missing_ok=True)
                    raise RuntimeError("el archivo bajado no coincide con el oficial")
                with zipfile.ZipFile(zpath) as z:
                    nombre = next(n for n in z.namelist() if n.endswith("/bin/ffmpeg.exe"))
                    with z.open(nombre) as src, open(self.bin, "wb") as dst:
                        dst.write(src.read())
                zpath.unlink(missing_ok=True)
            self.estado = "probando"
            self.encoder = self._elegir_encoder()
            (self.dir / "encoder.txt").write_text(self.encoder, encoding="utf-8")
            self.estado = "listo"
        except Exception as e:  # noqa: BLE001
            self.estado, self.error = "error", str(e)[:200]
            print(f"[highlights] no pude preparar ffmpeg: {e}", flush=True)

    def _elegir_encoder(self):
        for enc, (args, _) in ENCODERS.items():
            r = subprocess.run([str(self.bin), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "nullsrc=s=1280x720:d=0.3", "-pix_fmt", "nv12", *args, "-f", "null", "-"],
                               capture_output=True, creationflags=SIN_VENTANA, timeout=60)
            if r.returncode == 0:
                return enc
        return "libx264"

    # ---------- grabar
    @property
    def grabando(self):
        return self.proc is not None and self.proc.poll() is None

    def _arrancar(self):
        for f in self.buffer.glob("*.ts"):
            f.unlink(missing_ok=True)
        args = ENCODERS.get(self.encoder or "libx264", ENCODERS["libx264"])[0]
        cmd = [str(self.bin), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "ddagrab=output_idx=0:framerate=30,hwdownload,format=bgra,scale=1280:-2:flags=fast_bilinear,format=nv12",
               *args, "-f", "segment", "-segment_time", str(TRAMO), "-reset_timestamps", "1", "-strftime", "1",
               str(self.buffer / "t_%Y%m%d%H%M%S.ts")]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=SIN_VENTANA)
        _atar_a_lolcito(self.proc)
        self._hechos, self._pendientes, self._offset = set(), [], None
        self._partida_t = time.time()
        print(f"[highlights] grabando con {self.encoder}", flush=True)

    def _parar(self):
        if not self.proc:
            return
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
            self.proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            self.proc.kill()
        self.proc = None

    def _tramos(self):
        """[(inicio_pared, archivo)] de los tramos grabados, ordenados."""
        out = []
        for f in self.buffer.glob("t_*.ts"):
            try:
                out.append((time.mktime(time.strptime(f.stem[2:], "%Y%m%d%H%M%S")), f))
            except ValueError:
                pass
        return sorted(out)

    def _limpiar_buffer(self):
        viejo = time.time() - GUARDAR
        for t, f in self._tramos()[:-2]:
            if t < viejo:
                try:
                    f.unlink()
                except OSError:
                    pass

    # ---------- momentos
    def _momentos(self, game, yo):
        """Ventanas [desde, hasta] (en tiempo de partida) de tus mejores momentos, ya unidas."""
        ventanas = []
        for e in (game.get("events") or {}).get("Events", []):
            n, t = e.get("EventName"), e.get("EventTime", 0)
            puntos, texto, ini = 0, None, t - ANTES
            asist = {_norm(a) for a in e.get("Assisters") or []}
            if n == "ChampionKill":
                if _norm(e.get("KillerName")) in yo:
                    puntos, texto = 20, "Kill"
                elif yo & asist:
                    puntos, texto = 6, "Asistencia"
            elif n == "Multikill" and _norm(e.get("KillerName")) in yo:
                k = int(e.get("KillStreak") or 2)
                texto, puntos = MULTI.get(min(k, 5), MULTI[2])
                ini = t - ANTES - TRAMO * (k - 1)
            elif n == "FirstBlood" and _norm(e.get("Recipient")) in yo:
                puntos, texto = 25, "First blood"
            elif n == "Ace" and _norm(e.get("Acer")) in yo:
                puntos, texto = 30, "Ace"
            elif n in OBJ_ES and (_norm(e.get("KillerName")) in yo or yo & asist):
                robado = str(e.get("Stolen", "")).lower() == "true"
                puntos, texto = (70, f"Robaste {OBJ_ES[n]}") if robado else (15 if n == "BaronKill" else 0, f"Tomaste {OBJ_ES[n]}")
            if puntos:
                ventanas.append([max(0, ini), t + DESPUES, puntos, texto])
        ventanas.sort()
        unidas = []
        for v in ventanas:
            if unidas and v[0] <= unidas[-1][1] + 3:
                u = unidas[-1]
                u[1] = max(u[1], v[1])
                u[4].append((v[2], v[3]))
            else:
                unidas.append([v[0], v[1], v[2], v[3], [(v[2], v[3])]])
        out = []
        for d, h, _, _, lista in unidas:
            mejor = max(lista)
            puntos = mejor[0] + 0.3 * (sum(p for p, _ in lista) - mejor[0])
            kills = sum(1 for _, tx in lista if tx == "Kill")
            texto = mejor[1] if mejor[1] != "Kill" or kills < 2 else f"{kills} kills"
            out.append((d, h, round(puntos), texto))
        return out

    def en_partida(self, game, me):
        """Se llama en cada vuelta mientras hay partida."""
        if not config.HIGHLIGHTS or os.name != "nt":
            if self.grabando:
                self._parar()
            return
        if self.estado != "listo":
            self.preparar()
            return
        if not self.grabando:
            self._arrancar()
        t = game.get("gameData", {}).get("gameTime", 0)
        self._offset = time.time() - t
        act = game.get("activePlayer", {})
        yo = {_norm(act.get(k)) for k in ("riotIdGameName", "riotId", "summonerName")} - {""}
        for d, h, puntos, texto in self._momentos(game, yo):
            clave = round(d)
            if clave in self._hechos or puntos < MIN_PUNTOS or h > t - 1:
                continue
            self._hechos.add(clave)
            info = {"tipo": texto, "puntos": puntos, "minuto": f"{int(d + ANTES) // 60}:{int(d + ANTES) % 60:02d}",
                    "campeon": (me or {}).get("name"), "campeonImg": (me or {}).get("img"),
                    "kda": f"{(me or {}).get('k', 0)}/{(me or {}).get('d', 0)}/{(me or {}).get('a', 0)}",
                    "partida": int(self._partida_t * 1000)}
            self._pendientes.append((self._offset + d, self._offset + h, info))
        self._procesar_pendientes()
        self._limpiar_buffer()

    def _procesar_pendientes(self, forzar=False):
        listos = [p for p in self._pendientes if forzar or time.time() >= p[1] + TRAMO + 1]
        for p in listos:
            self._pendientes.remove(p)
            threading.Thread(target=self._recortar, args=p, daemon=True).start()

    def _recortar(self, desde, hasta, info):
        with self._lock:
            tramos = [(t, f) for t, f in self._tramos() if t + TRAMO > desde and t < hasta + 0.5]
            if not tramos:
                return
            nombre = time.strftime("%Y%m%d_%H%M%S", time.localtime(tramos[0][0]))
            lista = self.dir / "lista.txt"
            lista.write_text("".join(f"file '{f.as_posix()}'\n" for _, f in tramos), encoding="utf-8")
            mp4, jpg = self.clips / f"{nombre}.mp4", self.clips / f"{nombre}.jpg"
            r = subprocess.run([str(self.bin), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                                "-i", str(lista), "-c", "copy", "-movflags", "+faststart", str(mp4)],
                               capture_output=True, creationflags=SIN_VENTANA, timeout=120)
            if r.returncode != 0 or not mp4.exists():
                print(f"[highlights] no pude cortar el clip: {r.stderr[-300:]!r}", flush=True)
                return
            medio = max(0.0, (desde + ANTES) - tramos[0][0])
            subprocess.run([str(self.bin), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{medio:.1f}", "-i",
                            str(mp4), "-frames:v", "1", "-vf", "scale=480:-2", str(jpg)],
                           capture_output=True, creationflags=SIN_VENTANA, timeout=60)
            info = {**info, "id": nombre, "video": f"/hl/{mp4.name}", "miniatura": f"/hl/{jpg.name}" if jpg.exists() else None,
                    "fecha": int(tramos[0][0] * 1000), "segundos": round(len(tramos) * TRAMO)}
            (self.clips / f"{nombre}.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            print(f"[highlights] clip guardado: {info['tipo']} ({info['puntos']} puntos)", flush=True)
            self._recortar_viejos()

    def _recortar_viejos(self):
        todos = sorted(self.clips.glob("*.json"))
        for f in todos[:-MAX_CLIPS]:
            self.borrar(f.stem)

    def fin_partida(self):
        """Terminó la partida: corta lo que quedó pendiente y deja de grabar."""
        if not self.grabando:
            return
        def cerrar():
            time.sleep(TRAMO + 1)
            self._parar()
            self._procesar_pendientes(forzar=True)
            time.sleep(30)                       # que terminen de cortarse los últimos clips
            if not self.grabando:
                with self._lock:
                    for f in self.buffer.glob("*.ts"):
                        f.unlink(missing_ok=True)
        threading.Thread(target=cerrar, daemon=True).start()

    # ---------- solapa Highlights
    def listar(self):
        out = []
        for f in self.clips.glob("*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                pass
        return sorted(out, key=lambda c: c.get("fecha", 0), reverse=True)

    def borrar(self, cid):
        cid = "".join(ch for ch in str(cid) if ch.isalnum() or ch == "_")
        for ext in ("mp4", "jpg", "json"):
            try:
                (self.clips / f"{cid}.{ext}").unlink()
            except OSError:
                pass
        return {"ok": True}

    def vista(self):
        enc = ENCODERS.get(self.encoder or "", (None, None))[1]
        return {"on": bool(config.HIGHLIGHTS), "estado": self.estado, "progreso": self.progreso, "error": self.error,
                "grabando": self.grabando, "con": enc, "clips": self.listar()}

    def archivo(self, nombre):
        f = (self.clips / nombre).resolve()
        return f if self.clips.resolve() in f.parents and f.is_file() else None
