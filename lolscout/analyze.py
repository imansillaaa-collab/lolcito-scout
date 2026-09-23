"""Convierte las partidas guardadas en estadísticas: tier list, builds, counters y sinergias."""
from collections import Counter, defaultdict

from . import config

PRIOR = 30  # "partidas fantasma" al 50%: evita que un campeón con 5 partidas y 5 victorias salga primero


def adj_wr(wins: float, games: int, prior: int = PRIOR) -> float:
    return (wins + 0.5 * prior) / (games + prior) if games + prior else 0.5


def tier_of(adj: float) -> str:
    pct = adj * 100
    if pct >= 52.5: return "S"
    if pct >= 51.0: return "A"
    if pct >= 49.5: return "B"
    if pct >= 48.0: return "C"
    return "D"


def pick_patches(conn, patch: str = None, min_matches: int = 300):
    """Usa el parche pedido; si no, el más nuevo (sumando el anterior si todavía hay pocas partidas)."""
    rows = conn.execute("SELECT patch, COUNT(*) n FROM matches GROUP BY patch").fetchall()
    if not rows:
        return [], 0
    counts = {r["patch"]: r["n"] for r in rows}
    if patch:
        return [patch], counts.get(patch, 0)
    ordered = sorted(counts, key=lambda p: tuple(int(x) for x in p.split(".")), reverse=True)
    chosen = [ordered[0]]
    if counts[ordered[0]] < min_matches and len(ordered) > 1:
        chosen.append(ordered[1])
    return chosen, sum(counts[p] for p in chosen)


def analyze(conn, dd, patch: str = None, my_puuid: str = None) -> dict:
    patches, n_matches = pick_patches(conn, patch)
    if not n_matches:
        return {"patches": [], "matches": 0, "roles": {}}
    ph = ",".join("?" * len(patches))

    rows = conn.execute(
        f"""SELECT p.* FROM participants p JOIN matches m USING(match_id)
            WHERE m.patch IN ({ph})""",
        patches,
    ).fetchall()
    bans = Counter(
        r[0] for r in conn.execute(
            f"SELECT b.champion_id FROM bans b JOIN matches m USING(match_id) WHERE m.patch IN ({ph})",
            patches,
        )
    )

    # Índice: partida -> equipo -> posición -> fila
    by_match = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        by_match[r["match_id"]][r["team_id"]][r["position"]] = r

    result = {
        "patches": patches,
        "matches": n_matches,
        "version": dd.version,
        "roles": {},
        "duos": [],
        "me": None,
    }

    for role in config.ROLES:
        stats = defaultdict(lambda: {"games": 0, "wins": 0, "k": 0, "d": 0, "a": 0,
                                     "items": Counter(), "item_wins": Counter(),
                                     "boots": Counter(), "boot_wins": Counter(),
                                     "keystones": Counter(), "keystone_wins": Counter(),
                                     "spells": Counter(), "vs": defaultdict(lambda: [0, 0])})
        for teams in by_match.values():
            if len(teams) != 2:
                continue
            t1, t2 = teams.keys()
            for mine, theirs in ((t1, t2), (t2, t1)):
                r = teams[mine].get(role)
                if not r:
                    continue
                s = stats[r["champion_id"]]
                w = r["win"]
                s["games"] += 1
                s["wins"] += w
                s["k"] += r["kills"] or 0
                s["d"] += r["deaths"] or 0
                s["a"] += r["assists"] or 0
                for iid in {int(x) for x in (r["items"] or "").split(",") if x and x != "0"}:
                    info = dd.items.get(iid)
                    if not info or not info["completed"]:
                        continue
                    if info["boots"]:
                        s["boots"][iid] += 1
                        s["boot_wins"][iid] += w
                    else:
                        s["items"][iid] += 1
                        s["item_wins"][iid] += w
                if r["keystone"]:
                    s["keystones"][r["keystone"]] += 1
                    s["keystone_wins"][r["keystone"]] += w
                if r["spell1"] and r["spell2"]:
                    s["spells"][tuple(sorted((r["spell1"], r["spell2"])))] += 1
                enemy = teams[theirs].get(role)
                if enemy:
                    s["vs"][enemy["champion_id"]][0] += 1
                    s["vs"][enemy["champion_id"]][1] += w

        champs = []
        for cid, s in stats.items():
            g = s["games"]
            if g < config.MIN_GAMES:
                continue
            a = adj_wr(s["wins"], g)
            items = [i for i in sorted(s["items"], key=lambda i: s["items"][i], reverse=True)
                     if s["items"][i] / g >= 0.02][:15]
            matchups = [
                {"id": eid, "games": v[0], "wr": v[1] / v[0], "adj": adj_wr(v[1], v[0], 10)}
                for eid, v in s["vs"].items() if v[0] >= 5
            ]
            matchups.sort(key=lambda m: m["adj"], reverse=True)
            champs.append({
                "id": cid,
                "name": dd.champ_name(cid),
                "games": g,
                "wr": s["wins"] / g,
                "adj": a,
                "tier": tier_of(a),
                "pick": g / n_matches,
                "ban": bans.get(cid, 0) / n_matches,
                "kda": (s["k"] + s["a"]) / max(s["d"], 1),
                "items": [{"id": i, "share": s["items"][i] / g,
                           "wr": s["item_wins"][i] / s["items"][i]} for i in items],
                "boots": [{"id": b, "share": s["boots"][b] / g, "wr": s["boot_wins"][b] / s["boots"][b]}
                          for b, _ in s["boots"].most_common(4)],
                "keystones": [{"id": k, "share": n / g, "wr": s["keystone_wins"][k] / n}
                              for k, n in s["keystones"].most_common(2)],
                "spells": [list(p) for p, _ in s["spells"].most_common(1)],
                "good_vs": matchups[:5],
                "bad_vs": matchups[::-1][:5],
                "vs_all": {str(m["id"]): [m["games"], round(m["wr"], 4)] for m in matchups},
            })
        champs.sort(key=lambda c: c["adj"], reverse=True)
        result["roles"][role] = champs

    # Ítems de cada campeón juntando todos los roles: sirve para la build en partida, que necesita
    # saber qué arma ESE campeón aunque no llegue a las partidas que pide la tier list de su rol.
    pool = defaultdict(lambda: {"games": 0, "wins": 0, "items": Counter(), "item_wins": Counter(),
                                "boots": Counter(), "boot_wins": Counter(), "keystones": Counter()})
    for r in rows:
        s = pool[r["champion_id"]]
        w = r["win"]
        s["games"] += 1
        s["wins"] += w
        for iid in {int(x) for x in (r["items"] or "").split(",") if x and x != "0"}:
            info = dd.items.get(iid)
            if not info or not info["completed"]:
                continue
            if info["boots"]:
                s["boots"][iid] += 1
                s["boot_wins"][iid] += w
            else:
                s["items"][iid] += 1
                s["item_wins"][iid] += w
        if r["keystone"]:
            s["keystones"][r["keystone"]] += 1
    champs = {}
    for cid, s in pool.items():
        g = s["games"]
        if g < 10:
            continue
        items = [i for i in sorted(s["items"], key=lambda i: s["items"][i], reverse=True)
                 if s["items"][i] / g >= 0.05][:12]
        champs[cid] = {
            "id": cid, "games": g, "wr": s["wins"] / g,
            "items": [{"id": i, "share": s["items"][i] / g, "wr": s["item_wins"][i] / s["items"][i]} for i in items],
            "boots": [{"id": b, "share": n / g, "wr": s["boot_wins"][b] / n} for b, n in s["boots"].most_common(3)],
            "keystones": [{"id": k, "share": n / g} for k, n in s["keystones"].most_common(2)],
        }
    result["champs"] = champs

    # Sinergias ADC + Support
    if "BOTTOM" in config.ROLES and "UTILITY" in config.ROLES:
        duos = defaultdict(lambda: [0, 0])
        for teams in by_match.values():
            for team in teams.values():
                adc, sup = team.get("BOTTOM"), team.get("UTILITY")
                if adc and sup:
                    d = duos[(adc["champion_id"], sup["champion_id"])]
                    d[0] += 1
                    d[1] += adc["win"]
        result["duos"] = sorted(
            ({"adc": a, "sup": s, "games": g, "wr": w / g, "adj": adj_wr(w, g, 15)}
             for (a, s), (g, w) in duos.items() if g >= 8),
            key=lambda d: d["adj"], reverse=True,
        )

    # Recomendaciones personales
    if my_puuid:
        mine = conn.execute(
            "SELECT position, champion_id, win FROM participants WHERE puuid=?", (my_puuid,)
        ).fetchall()
        pool = defaultdict(lambda: [0, 0])
        for r in mine:
            if r["position"] in config.ROLES:
                pool[(r["position"], r["champion_id"])][0] += 1
                pool[(r["position"], r["champion_id"])][1] += r["win"]
        meta = {(role, c["id"]): c for role, cs in result["roles"].items() for c in cs}
        result["me"] = sorted(
            ({"role": role, "id": cid, "games": g, "wr": w / g,
              "tier": meta.get((role, cid), {}).get("tier", "?")}
             for (role, cid), (g, w) in pool.items()),
            key=lambda x: x["games"], reverse=True,
        )
    return result
