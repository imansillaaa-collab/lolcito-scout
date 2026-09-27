"""Revisión del workflow «Estadísticas» de Lolcito Scout (la usa la alerta al celular).

En la nube (rutina de Claude, sin nada guardado entre corridas): python3 herramientas/revisar_workflow.py --horas 12

Lee la API pública de GitHub y el índice publicado en la rama «datos», compara con la foto anterior
(base.json, al lado de este archivo) y la actualiza. Imprime primero una línea «PUSH: ...» (lo que se
manda al teléfono) y después el detalle. Uso: py revisar.py            (compara y actualiza la foto)
                                          py revisar.py --sin-guardar (solo mira)
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "imansillaaa-collab/lolcito-scout"
BASE = Path(__file__).with_name("base.json")


def leer(url):
    req = urllib.request.Request(url, headers={"User-Agent": "lolcito-alerta", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fecha(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def miles(n):
    return f"{n:,}".replace(",", ".")


NTFY = Path(__file__).with_name("ntfy.txt")   # canal de ntfy.sh al que está suscripto el celular de Iñaki


def avisar_celular(texto, prioridad="default"):
    """Manda la notificación al celular por ntfy.sh (no depende de la app de Claude)."""
    if not NTFY.exists():
        return "sin canal configurado"
    canal = NTFY.read_text(encoding="utf-8").strip()
    req = urllib.request.Request(f"https://ntfy.sh/{canal}", data=texto.encode("utf-8"), method="POST",
                                 headers={"Title": "Lolcito Scout", "Priority": prioridad, "Tags": "video_game"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return "enviada" if r.status == 200 else f"respuesta {r.status}"
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def main():
    base = json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else {}
    desde = base.get("desde", "2026-09-26T19:29:00Z")
    total_antes = base.get("total", 27376)
    ultima_antes = base.get("ultima_tanda", "2026-09-26T18:51Z")
    if "--horas" in sys.argv:   # sin foto guardada: las últimas N horas
        horas = int(sys.argv[sys.argv.index("--horas") + 1])
        hace = datetime.now(timezone.utc) - timedelta(hours=horas)
        desde, ultima_antes, total_antes = hace.strftime("%Y-%m-%dT%H:%M:%SZ"), hace.strftime("%Y-%m-%dT%H:%MZ"), None

    runs = leer(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=30")["workflow_runs"]
    runs = sorted((r for r in runs if r["name"] == "Estadísticas" and r["created_at"] > desde),
                  key=lambda r: r["created_at"])
    ok = sum(1 for r in runs if r["conclusion"] == "success")
    mal = [r for r in runs if r["status"] == "completed" and r["conclusion"] not in ("success", "skipped")]
    corriendo = [r for r in runs if r["status"] != "completed"]
    huecos = []
    todas = sorted(leer(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=30")["workflow_runs"],
                   key=lambda r: r["created_at"])
    for a, b in zip(todas, todas[1:]):
        if b["created_at"] > desde and a["status"] == "completed" and b.get("run_started_at"):
            huecos.append(max(0, int((fecha(b["run_started_at"]) - fecha(a["updated_at"])).total_seconds() // 60)))

    indice = leer(f"https://raw.githubusercontent.com/{REPO}/datos/indice.json")
    tandas = [t for t in indice.get("historial", []) if t["inicio"] > ultima_antes]
    nuevas = {}
    for t in tandas:
        for k, v in t["niveles"].items():
            nuevas[k] = nuevas.get(k, 0) + (v.get("nuevas") or 0)
    ult = indice["historial"][-1]
    total = sum(v.get("partidas", 0) for v in ult["niveles"].values())
    if total_antes is None:
        total_antes = total - sum(nuevas.values())

    problemas = []
    for r in mal:
        problemas.append(f"la corrida {r['id']} terminó «{r['conclusion']}»")
    if not tandas:
        problemas.append("no hubo tandas nuevas")
    hueco_max = max(huecos) if huecos else 0
    if hueco_max > 90:
        problemas.append(f"hubo un hueco de {hueco_max} min entre corridas")

    partes = [f"{len(runs)} corridas ({ok} ok{', 1 corriendo' if corriendo else ''})", f"{len(tandas)} tandas",
              f"+{miles(sum(nuevas.values()))} partidas (total {miles(total)})"]
    if huecos:
        partes.append(f"hueco máx. entre corridas {hueco_max} min")
    push = "Lolcito: " + ("⚠ " + "; ".join(problemas) + ". " if problemas else "") + ", ".join(partes) + "."
    print("PUSH: " + push[:195])
    if "--sin-avisar" not in sys.argv:
        print("Notificación al celular (ntfy): " + avisar_celular(push, "high" if problemas else "default"))
    print()
    print(f"Desde {desde} (foto anterior: {miles(total_antes)} partidas).")
    for r in runs:
        print(f"- corrida {r['id']}: {r['status']} {r['conclusion'] or ''} (arrancó {r['run_started_at']})")
    print(f"Tandas nuevas: {len(tandas)} · partidas nuevas por nivel: "
          + ", ".join(f"{k} {miles(v)}" for k, v in nuevas.items()))
    print(f"Total ahora: {miles(total)} ({'+' if total >= total_antes else ''}{miles(total - total_antes)}) · "
          f"por nivel: " + ", ".join(f"{k} {miles(v.get('partidas', 0))}" for k, v in ult["niveles"].items()))
    if tandas:
        print(f"Promedio por tanda: {miles(round(sum(nuevas.values()) / len(tandas)))}")
    print(f"Huecos entre corridas (min): {huecos or 'ninguno para medir'}")

    if "--sin-guardar" not in sys.argv and "--horas" not in sys.argv:
        BASE.write_text(json.dumps({"desde": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "total": total, "ultima_tanda": ult["inicio"]}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    # la consola de Windows no siempre es UTF-8: sin esto, un «⚠» cortaba el programa
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    try:
        main()
    except Exception as e:  # noqa: BLE001  si GitHub no contesta, igual avisa
        msg = f"Lolcito: no pude revisar el workflow ({e.__class__.__name__})."
        print("PUSH: " + msg)
        if "--sin-avisar" not in sys.argv:
            print("Notificación al celular (ntfy): " + avisar_celular(msg, "high"))
