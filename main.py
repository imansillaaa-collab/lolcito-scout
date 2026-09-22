"""Lolcito Scout — escauteo diario de partidas y mejores picks para ADC / Support.

Uso:
  python main.py diario      # escautea partidas nuevas + genera el reporte (lo que corre cada día)
  python main.py escautear   # solo baja partidas nuevas
  python main.py reporte     # solo regenera el reporte con lo que ya está guardado
  python main.py demo        # prueba con partidas simuladas, sin API key
  python main.py vivo        # asistente en vivo: selección de campeones + ítems en partida
Opciones del asistente en vivo:
  --simular draft|partida    # probarlo sin abrir el LoL
  --lan                      # para verlo en el celular (misma red WiFi)
Opciones:
  --parche 16.18             # analizar un parche específico
  --abrir                    # abrir el reporte en el navegador al terminar
"""
import argparse
import sys
import webbrowser

from lolscout import config, db
from lolscout.analyze import analyze
from lolscout.ddragon import DDragon
from lolscout.report import write_report


def build_report(conn, dd, patch=None, my_puuid=None, open_it=False):
    result = analyze(conn, dd, patch, my_puuid)
    if not result["matches"]:
        print("Todavía no hay partidas guardadas. Corré primero: python main.py diario")
        return
    html, _ = write_report(result, dd)
    print(f"Reporte listo: {html}")
    for role, champs in result["roles"].items():
        top = ", ".join(f"{c['name']} ({c['wr']*100:.1f}%)" for c in champs[:3])
        print(f"  Top {config.ROLE_NAMES.get(role, role)}: {top or 'sin datos suficientes'}")
    if open_it:
        webbrowser.open(html.resolve().as_uri())


def run_live(dd, args):
    from lolscout.live.clients import LCU, LiveClient
    from lolscout.live.server import App, Assistant

    assistant = Assistant(dd, LCU(), LiveClient())
    assistant.load_stats()
    app = App(dd, assistant, lan=args.lan)
    if args.simular:
        app.simulate(args.simular)
    if not args.no_abrir:
        import threading
        threading.Timer(0.8, webbrowser.open, [f"http://localhost:{args.puerto}"]).start()
    app.serve(args.puerto)


def main():
    ap = argparse.ArgumentParser(description="Lolcito Scout")
    ap.add_argument("comando", choices=["diario", "escautear", "reporte", "demo", "vivo"])
    ap.add_argument("--parche")
    ap.add_argument("--abrir", action="store_true")
    ap.add_argument("--simular", choices=["draft", "partida"])
    ap.add_argument("--lan", action="store_true")
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--no-abrir", action="store_true")
    args = ap.parse_args()

    dd = DDragon()
    print(f"Parche actual (Data Dragon): {dd.version}")

    if args.comando == "vivo":
        run_live(dd, args)
        return

    if args.comando == "demo":
        config.DB_PATH = config.DATA_DIR / "demo.db"
        if config.DB_PATH.exists():
            config.DB_PATH.unlink()
        conn = db.connect()
        from lolscout.demo import generate
        print("Generando 3000 partidas simuladas...")
        generate(conn, dd)
        build_report(conn, dd, args.parche, open_it=args.abrir)
        return

    conn = db.connect()
    my_puuid = None
    if args.comando in ("diario", "escautear"):
        from lolscout.collect import collect, collect_mine, my_puuid as get_puuid
        from lolscout.riot import RiotClient, RiotError
        try:
            client = RiotClient()
            collect(client, conn)
            my_puuid = get_puuid(client)
            if my_puuid:
                collect_mine(client, conn, my_puuid)
        except RiotError as e:
            print(f"ERROR: {e}")
            if args.comando == "escautear":
                sys.exit(1)
            print("Genero el reporte con las partidas que ya estaban guardadas.")
    if args.comando in ("diario", "reporte"):
        me_file = config.DATA_DIR / "mi_puuid.txt"
        if my_puuid:
            me_file.write_text(my_puuid)
        elif config.MY_RIOT_ID and me_file.exists():
            my_puuid = me_file.read_text().strip()
        build_report(conn, dd, args.parche, my_puuid, args.abrir)


if __name__ == "__main__":
    main()
