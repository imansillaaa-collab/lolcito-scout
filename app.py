"""Lolcito Scout — app de escritorio (esto es lo que se compila como LolcitoScout.exe)."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser

from lolscout import config

# Sin consola (.exe con ventana): todo lo que se imprime va a un archivo de registro
if sys.stdout is None or config.FROZEN:
    _log = open(config.DATA_DIR / "registro.txt", "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log


def message_box(text, title="Lolcito Scout"):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:
        print(text)


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.loads(r.read()).get("app") == "lolscout"
    except Exception:
        return False


def find_app_browser():
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def open_window(url):
    """Abre la interfaz en una ventana propia, sin barra de direcciones (Edge/Chrome en modo app)."""
    exe = find_app_browser()
    if exe:
        try:
            subprocess.Popen([exe, f"--app={url}", "--window-size=1360,900", "--no-first-run",
                              "--no-default-browser-check", f"--user-data-dir={config.DATA_DIR / 'ventana'}"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser(description="Lolcito Scout")
    ap.add_argument("--simular", choices=["draft", "partida", "resumen", "inicio"], help="probar sin abrir el LoL")
    ap.add_argument("--lan", action="store_true", help="permitir abrirlo desde el celular")
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--sin-ventana", action="store_true")
    ap.add_argument("--actualizado", action="store_true", help="lo abre la actualización: la ventana ya está abierta")
    args = ap.parse_args()
    url = f"http://localhost:{args.puerto}"

    if already_running(args.puerto):  # ya estaba abierto: solo muestro la ventana
        open_window(url)
        return

    from lolscout.ddragon import DDragon
    from lolscout.live.clients import LCU, LiveClient
    from lolscout.live.server import App, Assistant

    try:
        dd = DDragon()
    except Exception as e:
        message_box("No pude descargar los datos del parche (Data Dragon).\n"
                    "La primera vez Lolcito Scout necesita internet.\n\n" + str(e))
        return

    assistant = Assistant(dd, LCU(), LiveClient())
    assistant.load_stats()
    app = App(dd, assistant, lan=args.lan, quit_when_closed=not args.sin_ventana)
    if args.simular:
        app.simulate(args.simular)
    if not args.sin_ventana and not args.actualizado:   # tras actualizar, la ventana que ya estaba se recarga sola
        threading.Timer(0.8, open_window, [url]).start()
    try:
        app.serve(args.puerto)
    except OSError as e:
        message_box(f"No pude abrir el puerto {args.puerto}: {e}")


if __name__ == "__main__":
    main()
