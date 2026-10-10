"""Highlights: graba la pantalla mientras jugás y guarda clips de tus mejores momentos.

Cómo funciona:
- ffmpeg (se baja una sola vez, ~190 MB, de las compilaciones oficiales de BtbN en GitHub, verificando la suma
  sha256) graba el monitor principal en 720p30 en tramos de 4 segundos. Solo se guardan los últimos ~100
  segundos: lo anterior se borra solo, así no se llena el disco.
- Con la placa de video (NVIDIA/AMD/Intel) casi no usa procesador; si no hay, usa x264 «ultrafast».
- Los eventos de la partida (Live Client Data API: kills, multikills, first blood, ace, robos de objetivos)
  marcan los momentos; los que valen la pena se cortan en un MP4 con su miniatura en highlights/clips.
- Se puede apagar desde la solapa Highlights o Configuración (config.HIGHLIGHTS).
Sonido: solo el del juego (audio_juego.py toma el sonido del proceso del LoL y nada más: ni Discord ni música).
Se graba APARTE de la imagen, en archivos de 30 s con la hora exacta de su primera muestra (buffer/a_<ms>.pcm), y se
junta con la imagen recién al cortar cada clip. Cuando ffmpeg recibía imagen y sonido juntos, la captura de pantalla
se frenaba (de 30 a ~18 cuadros por segundo) y los clips se veían trabados.
"""
import hashlib
import json
import os
import subprocess
import threading
import time
import zipfile
from collections import deque
from pathlib import Path

from .. import config

VERSION_FFMPEG = "ffmpeg-n8.1-latest-win64-gpl-8.1.zip"   # la 9.x pide drivers de NVIDIA 610+
URL_FFMPEG = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/{VERSION_FFMPEG}"
URL_SUMAS = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256"
TRAMO = 4                 # segundos por tramo grabado
GUARDAR = 100             # segundos de grabación que se conservan hacia atrás
ANTES, DESPUES = 12, 4    # segundos de clip antes y después de cada momento
MIN_PUNTOS = 45           # lo que tiene que valer un momento para guardarlo (una kill común no llega: 10)
POR_PARTIDA = 5           # como mucho los 5 mejores momentos de cada partida
JUNTAR = 25               # lo que pasa a menos de 25 s de lo anterior es la misma pelea: un solo clip
MAX_VENTANA = 60          # pero un clip no abarca más de 60 s de pelea (la grabación guarda 100 s hacia atrás)
SOBREVIVIR = 10           # «kill y sobreviviste»: no te mataron en los 10 s siguientes
MAX_CLIPS = 200           # más que esto: se borran los más viejos
SIN_VENTANA = 0x08000000

ENCODERS = {
    "h264_nvenc": (["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-b:v", "5M", "-g", "60"], "la placa NVIDIA"),
    "h264_amf": (["-c:v", "h264_amf", "-quality", "speed", "-b:v", "5M", "-g", "60"], "la placa AMD"),
    "h264_qsv": (["-c:v", "h264_qsv", "-preset", "veryfast", "-b:v", "5M", "-g", "60"], "el video de Intel"),
    "libx264": (["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "28", "-g", "60"],
                "el procesador"),
}
MULTI = {2: ("Doble kill", 40), 3: ("Triple kill", 70), 4: ("Cuádruple kill", 90), 5: ("PENTAKILL", 120)}
OBJ_ES = {"DragonKill": "el dragón", "BaronKill": "el Barón", "HeraldKill": "el Heraldo", "HordeKill": "las larvas"}


BAJA = 0x00004000   # BELOW_NORMAL_PRIORITY_CLASS: el grabador nunca le gana el procesador al juego
_JOB = None


def _partes(encoder):
    """«ddagrab|h264_amf» → (captura, codificador). Los encoder.txt viejos solo tienen el codificador."""
    captura, _, enc = (encoder or "").rpartition("|")
    return (captura or "ddagrab"), (enc if enc in ENCODERS else "libx264")


def _entrada(captura):
    """Cómo se captura la pantalla: por la placa de video (liviano) o la captura clásica de Windows."""
    if captura == "gdigrab":
        return ["-f", "gdigrab", "-framerate", "30", "-draw_mouse", "0", "-i", "desktop",
                "-vf", "scale=1280:-2:flags=fast_bilinear,format=nv12"]
    return ["-f", "lavfi", "-i",
            "ddagrab=output_idx=0:framerate=30,hwdownload,format=bgra,scale=1280:-2:flags=fast_bilinear,format=nv12"]


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
        self._limpiar_viejos_sin_cuenta()
        self.proc = None
        self.encoder = self._leer_encoder()
        self.estado = "listo" if self.bin.exists() and self.encoder else "falta"
        self.progreso, self.error = 0, ""
        self._offset = None          # reloj de pared - tiempo de partida
        self._hechos = set()         # momentos ya recortados (por su inicio)
        self._pendientes = []        # (desde_pared, hasta_pared, info)
        self._lock = threading.Lock()
        self._partida_t = None
        self._ultima = None          # clave de la última partida grabada (para anotarle los LP al final)
        self._ultima_res = None      # la misma, para anotarle el resultado y el KDA final
        self._vida = deque(maxlen=900)   # (tiempo de partida, vida en %) de tu campeón, para «kill con poca vida»
        self._ult = None             # lo último que se vio de la partida (para cortar lo pendiente al terminar)

    def _limpiar_viejos_sin_cuenta(self):
        """Una sola vez: borra los clips de antes de que se guardara la cuenta y la liga (arrancamos en limpio)."""
        marca = self.dir / "clips-con-cuenta.txt"
        if marca.exists():
            return
        for f in self.clips.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        marca.write_text("Desde acá cada clip guarda la cuenta y la liga.\n", encoding="utf-8")

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

    def _bajar(self, url, destino):
        """Baja un archivo. Primero con requests (trae sus propios certificados de seguridad); si la compu igual
        rechaza la conexión segura (antivirus que revisa HTTPS, Windows sin certificados al día...), con curl.exe,
        que viene en Windows 10/11 y usa los certificados de Windows."""
        import requests
        try:
            with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "LolcitoScout"}) as r, \
                    open(destino, "wb") as f:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                bajado = 0
                for trozo in r.iter_content(1 << 20):
                    f.write(trozo)
                    bajado += len(trozo)
                    if total and destino.suffix == ".zip":
                        self.progreso = int(bajado * 100 / total)
            return
        except Exception as e:  # noqa: BLE001
            print(f"[highlights] no pude bajar con requests ({e}); pruebo con curl.exe", flush=True)
        curl = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "curl.exe"
        if not curl.exists():
            raise RuntimeError("no pude conectarme de forma segura para bajar el grabador")
        r = subprocess.run([str(curl), "-L", "-f", "-s", "-S", "--retry", "3", "-o", str(destino), url],
                           capture_output=True, creationflags=SIN_VENTANA | BAJA, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError(f"no pude bajar el grabador: {r.stderr.decode('utf-8', 'replace').strip()[:150]}")

    def _preparar(self):
        try:
            if not self.bin.exists():
                self.estado, self.progreso, self.error = "bajando", 0, ""
                zpath, spath = self.dir / "ffmpeg.zip", self.dir / "sumas.txt"
                self._bajar(URL_FFMPEG, zpath)
                self._bajar(URL_SUMAS, spath)
                self.progreso = 100
                h = hashlib.sha256()
                with open(zpath, "rb") as f:
                    for trozo in iter(lambda: f.read(1 << 20), b""):
                        h.update(trozo)
                sumas = spath.read_text(encoding="utf-8", errors="replace")
                spath.unlink(missing_ok=True)
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

    def _probar(self, captura, enc, segundos=2):
        """Graba de verdad `segundos` de pantalla con esa captura y ese codificador. Devuelve (anda, error)."""
        cmd = [str(self.bin), "-hide_banner", "-loglevel", "error", *_entrada(captura), "-t", str(segundos),
               *ENCODERS[enc][0], "-f", "null", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, creationflags=SIN_VENTANA | BAJA, timeout=40)
        except subprocess.TimeoutExpired:
            return False, "tardó demasiado"
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        importantes = [x for x in err if "rror" in x or "not" in x.lower() or "fail" in x.lower()]
        return r.returncode == 0, ((importantes or err)[0] if err else "")[:200]

    def _elegir_encoder(self, excluir=()):
        """Prueba en serio (graba 2 s) cada forma de capturar y codificar, de la más liviana a la más compatible:
        captura por la placa de video (ddagrab) y, si no anda, la clásica de Windows (gdigrab)."""
        errores = []
        for captura in ("ddagrab", "gdigrab"):
            for enc in ENCODERS:
                if f"{captura}|{enc}" in excluir:
                    continue
                anda, err = self._probar(captura, enc)
                if anda:
                    return f"{captura}|{enc}"
                errores.append(f"{captura}+{enc}: {err}")
        self.error = "Ninguna forma de grabar anduvo. " + " / ".join(errores[-2:])
        raise RuntimeError(self.error)

    def probar_ahora(self):
        """Botón «Probar grabación»: vuelve a elegir la mejor forma de grabar en esta compu."""
        if self.estado in ("bajando", "probando") or not self.bin.exists():
            return self.vista()
        def correr():
            try:
                self.estado, self.error = "probando", ""
                self.encoder = self._elegir_encoder()
                (self.dir / "encoder.txt").write_text(self.encoder, encoding="utf-8")
                self.estado = "listo"
            except Exception as e:  # noqa: BLE001
                self.estado, self.error = "error", str(e)[:300]
        threading.Thread(target=correr, daemon=True).start()
        return self.vista()

    # ---------- grabar
    @property
    def grabando(self):
        return self.proc is not None and self.proc.poll() is None

    def _arrancar(self):
        for f in list(self.buffer.glob("*.ts")) + list(self.buffer.glob("a_*.pcm")) + list(self.buffer.glob("*.csv")):
            f.unlink(missing_ok=True)
        captura, enc = _partes(self.encoder)
        # la lista de tramos dice en qué segundo de la grabación empieza cada uno: con eso se ubica el sonido justo
        cmd = [str(self.bin), "-hide_banner", "-loglevel", "error", *_entrada(captura), *ENCODERS[enc][0],
               "-f", "segment", "-segment_time", str(TRAMO), "-reset_timestamps", "1", "-strftime", "1",
               "-segment_list", str(self.buffer / "tramos.csv"), "-segment_list_type", "csv",
               str(self.buffer / "t_%Y%m%d%H%M%S.ts")]
        self._log = open(self.dir / "ffmpeg.log", "w", encoding="utf-8", errors="replace")
        # prioridad normal: si el juego le saca el procesador a la captura, repite cuadros y el clip sale trabado
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._log,
                                     creationflags=SIN_VENTANA)
        self._arranque = time.time()
        _atar_a_lolcito(self.proc)
        self._hechos, self._pendientes, self._offset = set(), [], None
        self._partida_t = time.time()
        self._cap, self._archivo_son = None, None
        if config.HIGHLIGHTS_SONIDO:
            threading.Thread(target=self._grabar_sonido, daemon=True).start()
        print(f"[highlights] grabando con {self.encoder}" + (" y el sonido del juego" if config.HIGHLIGHTS_SONIDO else ""),
              flush=True)

    # ---------- sonido (aparte de la imagen)
    def _grabar_sonido(self):
        """Graba el sonido del juego en archivos de 30 s (a_<ms de la primera muestra>.pcm, 48 kHz estéreo 16 bits)."""
        from . import audio_juego as aj
        pid = aj.pid_del_juego()
        if not pid:
            print("[audio] no encontré el proceso del juego: los clips van sin sonido", flush=True)
            return
        try:   # este hilo con prioridad alta: si se atrasa, se pierde sonido (la imagen no se entera)
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.GetCurrentThread.restype = ctypes.c_void_p
            k32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            k32.SetThreadPriority(k32.GetCurrentThread(), 2)   # THREAD_PRIORITY_HIGHEST
        except Exception:  # noqa: BLE001
            pass
        self._son_inicio, self._son_escritos = time.time(), 0
        self._cap = aj.CapturaJuego(pid, self._escribir_sonido)
        self._cap._correr()            # en este mismo hilo, hasta que se para la grabación
        if self._cap.error:
            print(f"[audio] sin sonido del juego: {self._cap.error}", flush=True)
        self._cerrar_sonido()

    def _escribir_sonido(self, datos):
        from . import audio_juego as aj
        por_archivo = 30 * aj.TASA * aj.CUADRO
        if self._archivo_son is None or self._archivo_son.tell() >= por_archivo:
            self._cerrar_sonido()
            ms = int((self._son_inicio + self._son_escritos / (aj.TASA * aj.CUADRO)) * 1000)
            self._archivo_son = open(self.buffer / f"a_{ms}.pcm", "wb")
        self._archivo_son.write(datos)
        self._son_escritos += len(datos)

    def _cerrar_sonido(self):
        try:
            if self._archivo_son:
                self._archivo_son.close()
        except Exception:  # noqa: BLE001
            pass
        self._archivo_son = None

    def _sonido_entre(self, desde, segundos):
        """Los bytes de sonido de [desde, desde+segundos] (hora de pared), con silencio donde no hay. None si no hay nada."""
        from . import audio_juego as aj
        por_seg = aj.TASA * aj.CUADRO
        total = int(segundos * aj.TASA) * aj.CUADRO
        out, alguno = bytearray(total), False
        for f in self.buffer.glob("a_*.pcm"):
            try:
                ini = int(f.stem[2:]) / 1000
                datos = f.read_bytes()
            except (ValueError, OSError):
                continue
            a, b = max(desde, ini), min(desde + segundos, ini + len(datos) / por_seg)
            if b <= a:
                continue
            o = int((a - ini) * aj.TASA) * aj.CUADRO
            d = int((a - desde) * aj.TASA) * aj.CUADRO
            n = min(int((b - a) * aj.TASA) * aj.CUADRO, len(datos) - o, total - d)
            out[d:d + n] = datos[o:o + n]
            alguno = True
        return bytes(out) if alguno else None

    def _inicio_real(self, tramos):
        """En qué hora exacta empieza el primer tramo (para que el sonido coincida con la imagen). La lista de ffmpeg
        dice el segundo de la grabación en que empieza cada tramo; la hora en que se creó cada archivo dice dónde cae
        el segundo 0. Sin la lista, la hora del nombre del archivo (con un margen de hasta 1 s)."""
        try:
            filas = [x.split(",") for x in (self.buffer / "tramos.csv").read_text(encoding="utf-8").split()]
            inicios = {fila[0]: float(fila[1]) for fila in filas if len(fila) >= 3}
            ceros = [(self.buffer / n).stat().st_ctime - s for n, s in inicios.items() if (self.buffer / n).exists()]
            if ceros and tramos[0][1].name in inicios:
                ceros.sort()
                return ceros[len(ceros) // 2] + inicios[tramos[0][1].name]
        except (OSError, ValueError):
            pass
        return tramos[0][0]

    def _se_cayo(self):
        """ffmpeg se cerró solo en plena partida: se anota por qué y se pasa a la próxima forma de grabar."""
        try:
            self._log.close()
            ult = (self.dir / "ffmpeg.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()
        except Exception:  # noqa: BLE001
            ult = []
        importantes = [x for x in ult if "rror" in x or "not" in x.lower() or "fail" in x.lower()]
        motivo = ((importantes or ult)[0] if ult else f"código {self.proc.returncode}")[:200]
        malo = self.encoder
        self.proc = None
        self._malos = getattr(self, "_malos", set()) | {malo}
        print(f"[highlights] la grabación con {malo} se cortó: {motivo}", flush=True)
        self.estado, self.error = "probando", f"La grabación con {malo} se cortó ({motivo}). Probando otra forma…"
        def reelegir():
            try:
                self.encoder = self._elegir_encoder(excluir=self._malos)
                (self.dir / "encoder.txt").write_text(self.encoder, encoding="utf-8")
                self.estado = "listo"
            except Exception as e:  # noqa: BLE001
                self.estado, self.error = "error", str(e)[:300]
        threading.Thread(target=reelegir, daemon=True).start()

    def _parar(self):
        if not self.proc:
            return
        if getattr(self, "_cap", None):
            self._cap.parar()           # (el hilo del sonido cierra su archivo solo)
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
            self.proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            self.proc.kill()
        self.proc = None
        try:
            self._log.close()
        except Exception:  # noqa: BLE001
            pass

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
        for f in self.buffer.glob("a_*.pcm"):   # sonido: también se guardan solo los últimos ~100 s
            try:
                if int(f.stem[2:]) / 1000 + 30 < viejo - 30 and (not self._archivo_son or self._archivo_son.name != str(f)):
                    f.unlink()
            except (ValueError, OSError):
                pass

    # ---------- momentos
    def _vida_en(self, t):
        """Tu vida (0 a 1) en el segundo `t` de la partida, o None si no se sabe."""
        antes = [v for tt, v in self._vida if tt <= t + 0.5]
        return antes[-1] if antes else None

    def _kill(self, t, asist, victima, racha_victima, campeon, mas_fuerte, mis_muertes):
        """Cuánto vale una kill tuya y cómo se llama. Una kill común vale 10 (no llega sola a MIN_PUNTOS): suman
        hacerla solo, con poca vida, cortarle la racha al rival, que sea el que más oro tiene, y sobrevivir."""
        pts, vida = 10, ""
        solo = not asist
        if solo:
            pts += 25
        hp = self._vida_en(t)
        if hp is not None and hp < 0.15:
            pts, vida = pts + 35, " con muy poca vida"
        elif hp is not None and hp < 0.30:
            pts, vida = pts + 25, " con poca vida"
        shutdown = racha_victima >= 3
        if shutdown:
            pts += 20
        if victima and victima == mas_fuerte:
            pts += 15
        if any(t < m <= t + SOBREVIVIR for m in mis_muertes):
            pts -= 15                 # la cambiaste por tu vida: vale menos
        cv = campeon.get(victima, "")
        if shutdown:
            nombre = f"Shutdown a {cv}"
        elif solo:
            nombre = f"Solo kill a {cv}" if cv else "Solo kill"
        elif victima == mas_fuerte:
            nombre = f"Kill al más fuerte ({cv})"
        else:
            nombre = f"Kill a {cv}" if cv else "Kill"
        return pts, nombre + vida

    def _momentos(self, game, yo):
        """Tus mejores momentos, una ventana por pelea: [(desde, hasta, puntos, nombre, último evento)] en tiempo
        de partida. Cada pelea junta lo que pasa a menos de JUNTAR segundos (sin pasar de MAX_VENTANA)."""
        campeon, equipo, oro = {}, {}, {}
        for p in game.get("allPlayers") or []:
            for n in {_norm(p.get(k)) for k in ("riotIdGameName", "riotId", "summonerName")} - {""}:
                campeon[n] = p.get("championName") or ""
                equipo[n] = p.get("team")
                oro[n] = sum((i.get("price") or 0) * (i.get("count") or 1) for i in p.get("items") or [])
        mi_equipo = next((equipo[n] for n in yo if n in equipo), None)
        rivales = {n: g for n, g in oro.items() if equipo.get(n) != mi_equipo}
        mas_fuerte = max(rivales, key=rivales.get) if rivales else None
        eventos = sorted((game.get("events") or {}).get("Events", []), key=lambda e: e.get("EventTime", 0))
        mis_muertes = [e.get("EventTime", 0) for e in eventos
                       if e.get("EventName") == "ChampionKill" and _norm(e.get("VictimName")) in yo]
        racha, momentos = {}, []
        for e in eventos:
            n, t = e.get("EventName"), e.get("EventTime", 0)
            asist = {_norm(a) for a in e.get("Assisters") or []}
            if n == "ChampionKill":
                killer, victima = _norm(e.get("KillerName")), _norm(e.get("VictimName"))
                racha_victima = racha.get(victima, 0)
                racha[killer] = racha.get(killer, 0) + 1
                racha[victima] = 0
                if killer in yo:
                    pts, nombre = self._kill(t, asist, victima, racha_victima, campeon, mas_fuerte, mis_muertes)
                    momentos.append((t, pts, nombre, "kill"))
            elif n == "Multikill" and _norm(e.get("KillerName")) in yo:
                nombre, pts = MULTI.get(min(int(e.get("KillStreak") or 2), 5), MULTI[2])
                momentos.append((t, pts, nombre, "multi"))
            elif n == "FirstBlood" and _norm(e.get("Recipient")) in yo:
                momentos.append((t, 20, "First blood", "otro"))
            elif n == "Ace" and _norm(e.get("Acer")) in yo:
                momentos.append((t, 25, "Ace", "otro"))
            elif n in OBJ_ES and _norm(e.get("KillerName")) in yo:
                # solo si el golpe final fue tuyo: una asistencia al robo de tu jungla no es tu jugada
                if str(e.get("Stolen", "")).lower() == "true":
                    momentos.append((t, 70, f"Robaste {OBJ_ES[n]}", "otro"))
                elif n == "BaronKill":
                    momentos.append((t, 15, "Tomaste el Barón", "otro"))
        grupos = []
        for m in sorted(momentos):
            g = grupos[-1] if grupos else None
            if g and m[0] - g["ult"] <= JUNTAR and m[0] - g["ini"] <= MAX_VENTANA:
                g["lista"].append(m)
                g["ult"] = m[0]
            else:
                grupos.append({"ini": m[0], "ult": m[0], "lista": [m]})
        out = []
        for g in grupos:
            lista = sorted(g["lista"], key=lambda m: -m[1])
            puntos = lista[0][1] + 0.5 * sum(m[1] for m in lista[1:])
            kills = sum(1 for m in lista if m[3] == "kill")
            multi = next((m for m in lista if m[3] == "multi"), None)
            if multi:
                nombre = multi[2]
            elif kills >= 2 and lista[0][3] == "kill":
                nombre = f"{lista[0][2]} y {kills - 1} kill{'s' if kills > 2 else ''} más"
            else:
                nombre = lista[0][2]
            out.append((max(0, g["ini"] - ANTES), g["ult"] + DESPUES, round(puntos), nombre, g["ult"]))
        return out

    def en_partida(self, game, me, cuenta=None):
        """Se llama en cada vuelta mientras hay partida. cuenta: {puuid, nombre, liga} de la cuenta conectada."""
        if not config.HIGHLIGHTS or os.name != "nt":
            if self.grabando:
                self._parar()
            return
        if self.estado != "listo":
            self.preparar()
            return
        if self.proc is not None and self.proc.poll() is not None:   # la grabación se cayó
            self._se_cayo()
            return
        if not self.grabando:
            self._arrancar()
        t = game.get("gameData", {}).get("gameTime", 0)
        self._offset = time.time() - t
        st = (game.get("activePlayer") or {}).get("championStats") or {}
        if st.get("maxHealth"):
            self._vida.append((t, (st.get("currentHealth") or 0) / st["maxHealth"]))
        self._ult = (game, me, cuenta)
        self._evaluar(game, me, cuenta, t)
        self._procesar_pendientes()
        self._limpiar_buffer()

    def _evaluar(self, game, me, cuenta, t, forzar=False):
        """Agenda el corte de las peleas que ya terminaron (o todas, si `forzar`: terminó la partida)."""
        act = game.get("activePlayer", {})
        yo = {_norm(act.get(k)) for k in ("riotIdGameName", "riotId", "summonerName")} - {""}
        for d, h, puntos, texto, ultimo in self._momentos(game, yo):
            clave = round(d)
            if clave in self._hechos or puntos < MIN_PUNTOS:
                continue
            # se espera a que la pelea termine (y a saber si sobreviviste) antes de cortar
            if not forzar and t < ultimo + max(JUNTAR, SOBREVIVIR):
                continue
            self._hechos.add(clave)
            info = {"tipo": texto, "puntos": puntos, "minuto": f"{int(d + ANTES) // 60}:{int(d + ANTES) % 60:02d}",
                    "campeon": (me or {}).get("name"), "campeonImg": (me or {}).get("img"),
                    "kda": f"{(me or {}).get('k', 0)}/{(me or {}).get('d', 0)}/{(me or {}).get('a', 0)}",
                    "partida": int(self._partida_t * 1000)}
            if cuenta:
                info.update({"puuid": cuenta.get("puuid"), "cuenta": cuenta.get("nombre"), "liga": cuenta.get("liga")})
            self._ultima = self._ultima_res = info["partida"]
            self._pendientes.append((self._offset + d, self._offset + h, info))

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
            # el sonido de esos mismos segundos (grabado aparte), si hay
            sonido = self._sonido_entre(self._inicio_real(tramos), len(tramos) * TRAMO + 1)
            entrada_son = []
            if sonido:
                corte = self.buffer / "corte.pcm"
                corte.write_bytes(sonido)
                entrada_son = ["-f", "s16le", "-ar", "48000", "-ac", "2", "-i", str(corte),
                               "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k", "-shortest"]
            r = subprocess.run([str(self.bin), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                                "-i", str(lista), *entrada_son, "-c:v", "copy", "-movflags", "+faststart", str(mp4)],
                               capture_output=True, creationflags=SIN_VENTANA | BAJA, timeout=120)
            if r.returncode != 0 or not mp4.exists():
                print(f"[highlights] no pude cortar el clip: {r.stderr[-300:]!r}", flush=True)
                return
            medio = max(0.0, (desde + ANTES) - tramos[0][0])
            subprocess.run([str(self.bin), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{medio:.1f}", "-i",
                            str(mp4), "-frames:v", "1", "-vf", "scale=480:-2", str(jpg)],
                           capture_output=True, creationflags=SIN_VENTANA | BAJA, timeout=60)
            info = {**info, "id": nombre, "video": f"/hl/{mp4.name}", "miniatura": f"/hl/{jpg.name}" if jpg.exists() else None,
                    "fecha": int(tramos[0][0] * 1000), "segundos": round(len(tramos) * TRAMO)}
            (self.clips / f"{nombre}.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            print(f"[highlights] clip guardado: {info['tipo']} ({info['puntos']} puntos)", flush=True)
            self._limitar_partida(info["partida"])
            self._recortar_viejos()

    def _limitar_partida(self, partida):
        """Deja solo los POR_PARTIDA mejores momentos de esa partida."""
        de_esta = [c for c in self.listar() if c.get("partida") == partida]
        for c in sorted(de_esta, key=lambda c: (c.get("puntos", 0), c.get("fecha", 0)))[:-POR_PARTIDA]:
            self.borrar(c["id"])

    def _recortar_viejos(self):
        todos = sorted(self.clips.glob("*.json"))
        for f in todos[:-MAX_CLIPS]:
            self.borrar(f.stem)

    def fin_partida(self):
        """Terminó la partida: corta lo que quedó pendiente y deja de grabar."""
        if not self.grabando:
            return
        if self._ult:   # las peleas del final (no llegaron a «terminar»): se cortan igual
            game, me, cuenta = self._ult
            self._evaluar(game, me, cuenta, game.get("gameData", {}).get("gameTime", 0), forzar=True)
            self._ult = None

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

    def anotar_lp(self, texto):
        """Cuando Riot actualiza el rango después de la partida: le anota a sus clips los LP que ganaste o perdiste."""
        partida, self._ultima = self._ultima, None
        if partida and texto:
            self._anotar(partida, {"lp": texto})

    def cerrar_partida(self, resumen):
        """Con el resumen de la partida: le anota a sus clips si ganaste y tu KDA final (para la tarjeta)."""
        partida, self._ultima_res = self._ultima_res, None
        if partida and resumen:
            self._anotar(partida, {"resultado": resumen.get("result"),
                                   "kdaFinal": f"{resumen.get('k', 0)}/{resumen.get('d', 0)}/{resumen.get('a', 0)}"})

    def _anotar(self, partida, campos):
        def anotar():
            time.sleep(45)                       # que terminen de cortarse los últimos clips
            with self._lock:
                for f in self.clips.glob("*.json"):
                    try:
                        info = json.loads(f.read_text(encoding="utf-8"))
                        if info.get("partida") == partida:
                            info.update(campos)
                            f.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
                    except (OSError, ValueError):
                        pass
        threading.Thread(target=anotar, daemon=True).start()

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

    def vista(self, cuenta=None, cuentas=None):
        captura, e = _partes(self.encoder)
        enc = (ENCODERS[e][1] + (" (captura clásica de Windows)" if captura == "gdigrab" else "")) if self.encoder else None
        return {"on": bool(config.HIGHLIGHTS), "sonido": bool(config.HIGHLIGHTS_SONIDO), "estado": self.estado, "progreso": self.progreso, "error": self.error,
                "grabando": self.grabando, "con": enc, "clips": self.listar(),
                "cuenta": (cuenta or {}).get("puuid"), "cuentas": cuentas or []}

    def archivo(self, nombre):
        f = (self.clips / nombre).resolve()
        return f if self.clips.resolve() in f.parents and f.is_file() else None
