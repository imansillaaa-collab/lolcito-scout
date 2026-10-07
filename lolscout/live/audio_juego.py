"""Sonido SOLO del juego para los highlights (sin Discord, música ni nada más de la compu).

Usa la captura de audio por programa de Windows («process loopback», Windows 10 versión 2004 o más nuevo):
se le pide a Windows el sonido del proceso «League of Legends.exe» (y sus hijos) y nada más. Está hecho con
ctypes, sin instalar nada ni sumar otro .exe.

El sonido sale como PCM de 16 bits, 48 kHz, estéreo, a ritmo de reloj: si el juego no suena (Windows no manda
nada), se rellena con silencio, así el audio nunca se atrasa respecto del video.
"""
import ctypes
import socket
import subprocess
import threading
import time
from ctypes import POINTER, byref, c_int, c_uint32, c_uint64, c_ulong, c_void_p, wintypes

TASA, CANALES, BYTES = 48000, 2, 2           # 48 kHz, estéreo, 16 bits
CUADRO = CANALES * BYTES
SIN_VENTANA = 0x08000000


class GUID(ctypes.Structure):
    _fields_ = [("a", c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def de(cls, s):
        import uuid
        return cls.from_buffer_copy(uuid.UUID(s).bytes_le)


IID_IUNKNOWN = GUID.de("00000000-0000-0000-C000-000000000046")
IID_HANDLER = GUID.de("41D949AB-9862-444A-80F6-C261334DA5EB")    # IActivateAudioInterfaceCompletionHandler
IID_AGILE = GUID.de("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")      # IAgileObject
IID_AUDIOCLIENT = GUID.de("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_CAPTURA = GUID.de("C8ADBD64-E71E-48A0-A4DE-185C395CD317")    # IAudioCaptureClient


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD)]


class PARAMS(ctypes.Structure):     # AUDIOCLIENT_ACTIVATION_PARAMS
    _fields_ = [("tipo", c_int), ("pid", wintypes.DWORD), ("modo", c_int)]


class BLOB(ctypes.Structure):
    _fields_ = [("cb", c_ulong), ("datos", c_void_p)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("blob", BLOB)]


def _metodo(obj, indice, restype, *argtypes):
    """Método número `indice` de la tabla de un objeto COM."""
    vtabla = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtabla[indice])


class _Avisador:
    """El objeto COM que Windows llama cuando terminó de preparar la captura (ActivateCompleted)."""
    QI = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
    REF = ctypes.WINFUNCTYPE(c_ulong, c_void_p)
    LISTO = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_void_p)

    def __init__(self):
        self.evento = threading.Event()
        self.op = None
        self._fns = [self.QI(self._qi), self.REF(lambda _: 1), self.REF(lambda _: 1), self.LISTO(self._listo)]
        self._tabla = (c_void_p * 4)(*[ctypes.cast(f, c_void_p) for f in self._fns])
        self._obj = (c_void_p * 1)(ctypes.addressof(self._tabla))
        self.ptr = ctypes.addressof(self._obj)

    def _qi(self, this, riid, ppv):
        if bytes(riid.contents) in (bytes(IID_IUNKNOWN), bytes(IID_HANDLER), bytes(IID_AGILE)):
            ppv[0] = this
            return 0
        ppv[0] = None
        return -2147467262   # E_NOINTERFACE

    def _listo(self, this, op):
        self.op = op
        self.evento.set()
        return 0


def pid_del_juego():
    """El proceso de la partida («League of Legends.exe»), o None."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq League of Legends.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, creationflags=SIN_VENTANA, timeout=10)
        for linea in r.stdout.splitlines():
            partes = [p.strip('"') for p in linea.split('","')]
            if len(partes) > 1 and partes[0].lower() == "league of legends.exe" and partes[1].isdigit():
                return int(partes[1])
    except Exception:  # noqa: BLE001
        pass
    return None


class CapturaJuego:
    """Toma el sonido de un proceso y lo manda a `destino(bytes)` a ritmo de reloj, en un hilo aparte."""

    def __init__(self, pid, destino):
        self.pid, self.destino = pid, destino
        self.error = None
        self._seguir = True
        self.hilo = threading.Thread(target=self._correr, daemon=True)

    def iniciar(self):
        self.hilo.start()

    def parar(self):
        self._seguir = False

    def _activar(self):
        ole = ctypes.windll.ole32
        ole.CoInitializeEx(None, 0)   # COINIT_MULTITHREADED
        params = PARAMS(1, self.pid, 0)   # PROCESS_LOOPBACK, este proceso y sus hijos
        pv = PROPVARIANT(65, 0, 0, 0, BLOB(ctypes.sizeof(params), ctypes.cast(byref(params), c_void_p)))   # VT_BLOB
        avisador = _Avisador()
        op = c_void_p()
        activar = ctypes.windll.mmdevapi.ActivateAudioInterfaceAsync
        activar.argtypes = [wintypes.LPCWSTR, POINTER(GUID), POINTER(PROPVARIANT), c_void_p, POINTER(c_void_p)]
        activar.restype = ctypes.HRESULT
        activar("VAD\\Process_Loopback", byref(IID_AUDIOCLIENT), byref(pv), avisador.ptr, byref(op))
        if not avisador.evento.wait(5):
            raise RuntimeError("Windows no respondió al pedir el sonido del juego")
        hr, cliente = ctypes.HRESULT(), c_void_p()
        _metodo(avisador.op or op, 3, ctypes.HRESULT, POINTER(ctypes.HRESULT), POINTER(c_void_p))(
            avisador.op or op, byref(hr), byref(cliente))
        if hr.value != 0 or not cliente:
            raise RuntimeError(f"Windows no dio el sonido del juego (código {hr.value & 0xFFFFFFFF:#x})")
        wf = WAVEFORMATEX(1, CANALES, TASA, TASA * CUADRO, CUADRO, BYTES * 8, 0)   # PCM 16 bits
        flags = 0x00020000 | 0x80000000 | 0x08000000   # LOOPBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY
        _metodo(cliente, 3, ctypes.HRESULT, c_int, wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong,
                POINTER(WAVEFORMATEX), c_void_p)(cliente, 0, flags, 2000000, 0, byref(wf), None)
        captura = c_void_p()
        _metodo(cliente, 14, ctypes.HRESULT, POINTER(GUID), POINTER(c_void_p))(cliente, byref(IID_CAPTURA),
                                                                                   byref(captura))
        _metodo(cliente, 10, ctypes.HRESULT)(cliente)   # Start
        return cliente, captura

    def _correr(self):
        try:
            cliente, captura = self._activar()
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            print(f"[audio] {e}", flush=True)
            return
        siguiente = _metodo(captura, 5, ctypes.HRESULT, POINTER(c_uint32))
        tomar = _metodo(captura, 3, ctypes.HRESULT, POINTER(c_void_p), POINTER(c_uint32), POINTER(wintypes.DWORD),
                        POINTER(c_uint64), POINTER(c_uint64))
        soltar = _metodo(captura, 4, ctypes.HRESULT, c_uint32)
        inicio, escritos = time.perf_counter(), 0
        try:
            while self._seguir:
                n = c_uint32()
                siguiente(captura, byref(n))
                while n.value:
                    datos, cuadros, flags = c_void_p(), c_uint32(), wintypes.DWORD()
                    tomar(captura, byref(datos), byref(cuadros), byref(flags), None, None)
                    k = cuadros.value
                    if flags.value & 0x2 or not datos:   # AUDCLNT_BUFFERFLAGS_SILENT
                        trozo = bytes(k * CUADRO)
                    else:
                        trozo = ctypes.string_at(datos, k * CUADRO)
                    soltar(captura, k)
                    self.destino(trozo)
                    escritos += k
                    siguiente(captura, byref(n))
                # si el juego no suena, Windows no manda nada: relleno con silencio para no atrasarme del reloj
                deberia = int((time.perf_counter() - inicio) * TASA)
                if deberia - escritos > TASA // 10:
                    faltan = deberia - escritos - TASA // 20
                    self.destino(bytes(faltan * CUADRO))
                    escritos += faltan
                time.sleep(0.01)
        except Exception as e:  # noqa: BLE001  (se cerró ffmpeg, etc.)
            self.error = self.error or str(e)
        finally:
            try:
                _metodo(cliente, 11, ctypes.HRESULT)(cliente)   # Stop
            except Exception:  # noqa: BLE001
                pass


def conectar(puerto, intentos=50):
    """Se conecta al ffmpeg que espera el sonido en 127.0.0.1:puerto."""
    for _ in range(intentos):
        try:
            return socket.create_connection(("127.0.0.1", puerto), timeout=2)
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("ffmpeg no abrió la entrada de sonido")
