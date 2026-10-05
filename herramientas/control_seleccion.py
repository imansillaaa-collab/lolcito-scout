"""Control automático de la selección de campeones: corre antes de cada publicación (herramientas/publicar_exe.sh).

Arma, con las estadísticas publicadas de verdad, lo que Lolcito recomendaría en los 5 roles y las 3 ligas, en
varias situaciones (sin rivales, con el equipo rival completo, con tu compañero de bot, en la fase de baneos), y
revisa que tenga sentido. Así nadie tiene que probar a mano cada rol y cada campeón.

ERROR (no se publica):
- se rompe algo (la selección o las runas tiran un error con algún campeón)
- recomienda un campeón raro en ese rol (casi no se juega ahí) que no es tuyo
- arma una página de runas que el juego no acepta
- recomienda menos de 5 campeones, o sugiere banear lo que marcó un aliado
OJO (se avisa pero se publica): un campeón con pocas partidas arriba de todo, o el mismo campeón primero en
muchos roles a la vez.

Uso: python herramientas/control_seleccion.py   (sale con código 1 si hay errores)
La tabla completa queda en control_seleccion.txt, al lado de la carpeta del proyecto.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from lolscout import ddragon, online  # noqa: E402
from lolscout.live import advisor, runes  # noqa: E402

ROLES = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "middle", "BOTTOM": "bottom", "UTILITY": "utility"}
LIGAS = {"bajo": "Baja", "medio": "Media", "alto": "Alta"}


def sesion(rol, enemigos=(), aliado=None, banear=False):
    """Una selección de campeones armada a mano, con el mismo formato que manda el cliente del LoL."""
    mi_equipo = [{"cellId": 0, "assignedPosition": ROLES[rol]}]
    if aliado:
        rol_aliado, cid, bloqueado = aliado
        mi_equipo.append({"cellId": 1, "assignedPosition": ROLES[rol_aliado],
                          ("championId" if bloqueado else "championPickIntent"): cid})
    acciones = [[{"actorCellId": 0, "type": "ban", "isInProgress": True, "completed": False, "id": 1}]] if banear else []
    return {"localPlayerCellId": 0, "myTeam": mi_equipo, "actions": acciones,
            "theirTeam": [{"cellId": 5 + i, "championId": c} for i, c in enumerate(enemigos)]}


def main():
    dd = ddragon.DDragon()
    errores, ojos, tabla = [], [], []
    for liga, liga_es in LIGAS.items():
        r, err = online.load(liga)
        if not r or not r.get("roles"):
            errores.append(f"{liga_es}: no pude bajar las estadísticas ({err})")
            continue
        meta = r["roles"]
        dist = {int(k): v for k, v in (r.get("dist") or {}).items()}
        champs = r.get("champs")
        duos = r.get("duos", [])
        # el campeón más jugado de cada rol: arma un equipo rival y un compañero de bot «típicos»
        tipico = {rol: max(meta[rol], key=lambda c: c["games"])["id"] for rol in ROLES if meta.get(rol)}
        primeros = {}
        for rol in ROLES:
            if not meta.get(rol):
                errores.append(f"{liga_es} {rol}: no hay estadísticas de ese rol")
                continue
            escenarios = {"sin rivales": sesion(rol),
                          "con el equipo rival": sesion(rol, [tipico[x] for x in ROLES if x in tipico])}
            if rol in advisor.BOT_PARTNER:
                comp = advisor.BOT_PARTNER[rol]
                escenarios["con tu compañero de bot"] = sesion(rol, aliado=(comp, tipico[comp], True))
            escenarios["baneos (aliado con campeón marcado)"] = sesion(rol, aliado=("TOP" if rol != "TOP" else "MIDDLE",
                                                                                tipico["TOP" if rol != "TOP" else "MIDDLE"],
                                                                                False), banear=True)
            for nombre, ses in escenarios.items():
                donde = f"{liga_es} · {advisor.ROLE_ES[rol]} · {nombre}"
                try:
                    st = advisor.draft_advice(ses, meta, duos, dist, dd, default_role=rol, champs=champs)
                except Exception:  # noqa: BLE001
                    errores.append(f"{donde}: la selección tiró un error:\n{traceback.format_exc(limit=3)}")
                    continue
                opciones = st.get("options") or []
                if len(opciones) < 5:
                    errores.append(f"{donde}: recomienda solo {len(opciones)} campeones")
                por_id = {c["id"]: c for c in meta[rol]}
                for o in opciones:
                    c = por_id.get(o["id"])
                    if c and not advisor.jugable(c, rol, dist, dd):
                        errores.append(f"{donde}: recomienda {o['name']}, que casi no se juega en ese rol")
                for o in opciones[:3]:
                    c = por_id.get(o["id"]) or {}
                    if c.get("games", 0) < 500:
                        ojos.append(f"{donde}: {o['name']} está entre los 3 primeros con solo {c.get('games', 0)} partidas")
                if nombre == "baneos (aliado con campeón marcado)":
                    marcado = ses["myTeam"][1].get("championPickIntent")
                    if any(b["id"] == marcado for b in st.get("banOptions") or []):
                        errores.append(f"{donde}: sugiere banear {dd.champ_name(marcado)}, que lo tiene marcado un aliado")
                # runas y hechizos de los 10 recomendados: que no se rompa y que el juego acepte las páginas
                shape = advisor.enemy_shape(dd, [p["championId"] for p in ses["theirTeam"]])
                for o in opciones:
                    try:
                        cm = por_id.get(o["id"]) or (champs or {}).get(o["id"])
                        for pg in runes.options(dd, o["id"], rol, shape, cm, None):
                            if not runes._valid(dd, pg):
                                errores.append(f"{donde}: página de runas inválida para {o['name']} ({pg.get('title')})")
                        runes.spells(rol, shape, dd, o["id"])
                    except Exception:  # noqa: BLE001
                        errores.append(f"{donde}: las runas de {o['name']} tiraron un error:\n"
                                       f"{traceback.format_exc(limit=3)}")
                if nombre == "sin rivales":
                    primeros[rol] = opciones[0]["name"] if opciones else "-"
                    tabla.append(f"{liga_es:5} | {advisor.ROLE_ES[rol]:7} | " + ", ".join(o["name"] for o in opciones))
        repetidos = {}
        for rol, n in primeros.items():
            repetidos.setdefault(n, []).append(advisor.ROLE_ES[rol])
        for n, rs in repetidos.items():
            if len(rs) >= 3:
                ojos.append(f"{liga_es}: {n} sale primero en {len(rs)} roles ({', '.join(rs)})")

    salida = ["RECOMENDACIONES SIN RIVALES (los 10 primeros de cada rol)", *tabla, ""]
    salida += [f"ERRORES: {len(errores)}", *[f"  ✗ {e}" for e in errores], ""]
    salida += [f"PARA MIRAR: {len(ojos)}", *[f"  · {o}" for o in ojos]]
    texto = "\n".join(salida)
    (Path(__file__).resolve().parent.parent.parent / "control_seleccion.txt").write_text(texto, encoding="utf-8")
    print(texto)
    print("\n" + ("✗ El control encontró errores: no publico." if errores else "✓ Control de la selección: todo bien."))
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
