"""Actualización automática del .exe.

Cada tanto Lolcito mira la rama "descargas" del repo (la misma de siempre, en GitHub):
  version.json       {"version": "2026.09.24-2330", "sha256": "...", "bytes": 123, "notas": "..."}
  LolcitoScout.exe   el .exe nuevo
Si la versión publicada es más nueva que la propia, la pantalla muestra «Hay una versión nueva».
Al tocar «Actualizar»: baja el .exe, revisa que esté completo (sha256), y un PowerShell oculto espera a que
Lolcito se cierre, reemplaza el .exe y lo vuelve a abrir. La ventana abierta se recarga sola.

Solo funciona en el .exe de Windows; corriendo desde el código no hace nada.
"""
import base64
import hashlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from .. import config
from ..version import VERSION

RAMA = "descargas"
CADA = 3 * 3600          # cada cuánto vuelve a mirar si hay versión nueva


def _base():
    repo = (config.STATS_REPO or "").strip().strip("/")
    return f"https://raw.githubusercontent.com/{repo}/{RAMA}" if repo else None


class Actualizador:
    def __init__(self):
        self.nueva = None        # dict de version.json si hay una más nueva
        self.estado = "sin-revisar"   # sin-revisar | al-dia | hay | bajando | reiniciando | error
        self.error = ""
        self.progreso = 0
        self._t = 0.0

    def puede(self):
        return config.FROZEN and sys.platform == "win32" and bool(_base())

    def vista(self):
        return {"version": VERSION, "estado": self.estado, "error": self.error, "progreso": self.progreso,
                "nueva": {"version": self.nueva["version"], "notas": self.nueva.get("notas", "")} if self.nueva else None}

    # ---- revisar
    def revisar(self, forzar=False):
        if not self.puede() or self.estado in ("bajando", "reiniciando"):
            return self.vista()
        if not forzar and time.time() - self._t < CADA:
            return self.vista()
        self._t = time.time()
        try:
            r = requests.get(f"{_base()}/version.json", timeout=10, headers={"Cache-Control": "no-cache"})
            if r.status_code == 404:          # todavía no se publicó ninguna versión
                self.estado, self.nueva = "al-dia", None
                return self.vista()
            r.raise_for_status()
            info = r.json()
            if str(info.get("version", "")) > VERSION and info.get("sha256"):
                self.nueva, self.estado = info, "hay"
            else:
                self.nueva, self.estado = None, "al-dia"
        except Exception as e:  # sin internet, GitHub caído, etc.: se reintenta en la próxima vuelta
            print(f"[actualizar] no pude revisar: {e}", flush=True)
        return self.vista()

    def en_segundo_plano(self):
        def ciclo():
            time.sleep(20)       # que primero arranque todo lo demás
            while True:
                self.revisar()
                time.sleep(600)
        threading.Thread(target=ciclo, daemon=True).start()

    # ---- instalar
    def instalar(self):
        if not self.puede():
            return {"ok": False, "error": "La actualización automática solo funciona en el .exe de Windows."}
        if not self.nueva or self.estado != "hay":
            return {"ok": False, "error": "No hay ninguna versión nueva para instalar."}
        self.estado, self.error, self.progreso = "bajando", "", 0
        threading.Thread(target=self._instalar, daemon=True).start()
        return {"ok": True}

    def _instalar(self):
        try:
            carpeta = config.DATA_DIR / "actualizacion"
            carpeta.mkdir(exist_ok=True)
            nuevo = carpeta / "LolcitoScout-nuevo.exe"
            total = int(self.nueva.get("bytes") or 0)
            h, bajados = hashlib.sha256(), 0
            with requests.get(f"{_base()}/LolcitoScout.exe", stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(nuevo, "wb") as f:
                    for trozo in r.iter_content(1 << 16):
                        f.write(trozo)
                        h.update(trozo)
                        bajados += len(trozo)
                        if total:
                            self.progreso = min(99, int(bajados * 100 / total))
            if h.hexdigest().lower() != str(self.nueva["sha256"]).lower():
                nuevo.unlink(missing_ok=True)
                raise RuntimeError("El archivo bajó incompleto o dañado: probá de nuevo en un rato.")
            self.progreso = 100
            self._reemplazar_y_reiniciar(nuevo)
        except Exception as e:
            self.estado, self.error = "hay", str(e)
            print(f"[actualizar] falló: {e}", flush=True)

    def _reemplazar_y_reiniciar(self, nuevo: Path):
        exe = Path(sys.executable)
        # el .exe "de un solo archivo" corre en dos procesos: el que se abrió (dueño del archivo) y este
        pids = {os.getpid(), os.getppid()}
        q = lambda p: "'" + str(p).replace("'", "''") + "'"  # noqa: E731  (comillas de PowerShell)
        script = (
            f"foreach ($p in @({','.join(str(p) for p in pids)})) {{ Wait-Process -Id $p -Timeout 60 -ErrorAction SilentlyContinue }}\n"
            "Start-Sleep -Milliseconds 800\n"
            "for ($i = 0; $i -lt 30; $i++) {\n"
            f"  try {{ Move-Item -LiteralPath {q(nuevo)} -Destination {q(exe)} -Force -ErrorAction Stop; break }}\n"
            "  catch { Start-Sleep -Seconds 1 }\n"
            "}\n"
            f"Start-Process -FilePath {q(exe)} -ArgumentList '--actualizado'\n"
        )
        cod = base64.b64encode(script.encode("utf-16-le")).decode()   # así no importan la ñ ni los espacios
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
                          "-EncodedCommand", cod],
                         creationflags=0x00000008 | 0x00000200 | 0x08000000,  # desacoplado, grupo nuevo, sin consola
                         close_fds=True)
        self.estado = "reiniciando"
        print(f"[actualizar] instalando {self.nueva['version']}: cierro para reemplazar el .exe", flush=True)
        threading.Timer(1.5, lambda: os._exit(0)).start()   # tiempo para que la pantalla reciba la respuesta
