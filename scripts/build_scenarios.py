"""Derive EV routes and demonstration scenarios from the real network.

Routes are searched on the actual graph, so a "perpendicular" scenario is one where the
signal program really cannot serve both movements in one phase, not a label on a route.
Departure offsets are set so the vehicles reach the shared signal at about the same time.
"""
from __future__ import annotations

import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.config import SCENARIOS_FILE  # noqa: E402
from app.core.signals import build_plan  # noqa: E402
from app.core.topology import NetworkModel, TlsInfo  # noqa: E402

MAIN = {"highway.primary", "highway.secondary", "highway.tertiary"}
LEAD_M = 900.0     # route length before the signal: longer than the largest radius
TAIL_M = 500.0
EV_SPEED_FACTOR = 1.25


def backtrack(net: NetworkModel, edge: str, want: float, rng: random.Random) -> list[str]:
    """Walk upstream from `edge`, preferring major roads and straight continuation."""
    path, length, cur = [edge], 0.0, net.net.getEdge(edge)
    seen = {edge}
    while length < want:
        inc = [e for e in cur.getIncoming() if e.getID() not in seen and e.getFunction() != "internal"]
        if not inc:
            break
        inc.sort(key=lambda e: (e.getType() not in MAIN, -e.getLaneNumber(), rng.random()))
        cur = inc[0]
        seen.add(cur.getID())
        path.insert(0, cur.getID())
        length += cur.getLength()
    return path


def forward(net: NetworkModel, edge: str, want: float, rng: random.Random) -> list[str]:
    path, length, cur = [edge], 0.0, net.net.getEdge(edge)
    seen = {edge}
    while length < want:
        out = [e for e in cur.getOutgoing() if e.getID() not in seen and e.getFunction() != "internal"]
        if not out:
            break
        out.sort(key=lambda e: (e.getType() not in MAIN, -e.getLaneNumber(), rng.random()))
        cur = out[0]
        seen.add(cur.getID())
        path.append(cur.getID())
        length += cur.getLength()
    return path


def route_through(net: NetworkModel, in_edge: str, out_edge: str, rng: random.Random) -> list[str] | None:
    up = backtrack(net, in_edge, LEAD_M, rng)
    down = forward(net, out_edge, TAIL_M, rng)
    if sum(net.edge_length(e) for e in up[:-1]) < 600:
        return None
    r = up + down
    return r if len(set(r)) == len(r) else None


def free_time(net: NetworkModel, edges: list[str], until: str) -> float:
    t = 0.0
    for e in edges:
        ed = net.net.getEdge(e)
        t += ed.getLength() / ed.getSpeed()
        if e == until:
            break
    return t


def straight_pairs(info: TlsInfo) -> list[tuple[str, str]]:
    return [p for p, idx in info.pairs.items() if info.links[idx[0]].turn == "s"]


def compatible(info: TlsInfo, a: tuple[str, str], b: tuple[str, str]) -> bool:
    return build_plan(info, [tuple(info.pairs[a]), tuple(info.pairs[b])], lambda lk: set()) is not None


def angle_between(info: TlsInfo, a: str, b: str) -> float:
    d = abs(info.approaches[a].bearing - info.approaches[b].bearing) % 360
    return min(d, 360 - d)


def main() -> None:
    net = NetworkModel()
    rng = random.Random(7)
    big = [t for t in net.tls.values() if len(t.approaches) >= 3 and len(straight_pairs(t)) >= 2]

    routes: dict[str, dict[tuple[str, str], list[str]]] = {}
    for t in big:
        routes[t.id] = {}
        for p in t.pairs:
            r = route_through(net, p[0], p[1], rng)
            if r:
                routes[t.id][p] = r

    def pick_pair(perpendicular: bool):
        best = None
        for t in big:
            ps = [p for p in straight_pairs(t) if p in routes[t.id]]
            for i, a in enumerate(ps):
                for b in ps[i + 1:]:
                    ang = angle_between(t, a[0], b[0])
                    ok = (not compatible(t, a, b) and 60 < ang < 120) if perpendicular else \
                        (compatible(t, a, b) and ang > 150)
                    if ok:
                        lanes = t.approaches[a[0]].lanes + t.approaches[b[0]].lanes
                        rank = (t.source == "osm", lanes, -abs(ang - (90 if perpendicular else 180)))
                        if best is None or rank > best[0]:
                            best = (rank, t, a, b)
        return best

    perp, opp = pick_pair(True), pick_pair(False)
    if perp is None or opp is None:
        sys.exit("no suitable signal found for the conflict scenarios")

    def start_after_upstream_signal(route: list[str], in_edge: str) -> list[str]:
        """Drop the route before the last signal ahead of the target. An upstream red can delay a
        vehicle by a full cycle, which would decide by luck whether the two ever meet."""
        target = route.index(in_edge)
        before = [c for c in net.route_crossings(route) if c.route_index < target]
        if before:
            trimmed = route[before[-1].route_index + 1:]
            if sum(net.edge_length(e) for e in trimmed[:trimmed.index(in_edge) + 1]) >= 350:
                return trimmed
        return route

    def synced(t: TlsInfo, pairs, types):
        rs = [start_after_upstream_signal(routes[t.id][p], p[0]) for p in pairs]
        times = [free_time(net, r, p[0]) / EV_SPEED_FACTOR for r, p in zip(rs, pairs)]
        lead = times.index(max(times))
        out = []
        for i, (ty, r, tt) in enumerate(zip(types, rs, times)):
            e = {"type": ty, "edges": r, "delay": 0.0}
            if i != lead:
                e["sync"] = {"leader": lead, "travel_s": round(tt, 1)}
            out.append(e)
        return out

    # Longest routes in the pool cross the most signals: used for the corridor and the city-wide scenarios.
    pool: list[dict] = []
    edges = [e for e in net.net.getEdges() if e.getType() in MAIN]
    tries = 0
    while len(pool) < 80 and tries < 6000:
        tries += 1
        a, b = rng.choice(edges), rng.choice(edges)
        path = net.net.getShortestPath(a, b)[0]
        if not path:
            continue
        ids = [e.getID() for e in path]
        n = len({c.tls for c in net.route_crossings(ids)})
        length = sum(net.edge_length(e) for e in ids)
        if n >= 2 and 1800 < length < 6500:
            pool.append({"edges": ids, "signals": n, "length": round(length)})
    pool.sort(key=lambda p: -p["signals"])

    # Corridor: three routes sharing a chain of at least two consecutive signals.
    corridor = None
    for base in pool[:30]:
        seq = [c.tls for c in net.route_crossings(base["edges"])]
        mates = [p for p in pool if p is not base and len(set(seq) & {c.tls for c in net.route_crossings(p["edges"])}) >= 2]
        if len(mates) >= 2:
            corridor = [base, mates[0], mates[1]]
            break
    corridor = corridor or pool[:3]

    def spread(n: int) -> list[dict]:
        picked: list[dict] = []
        for p in pool:
            s = {c.tls for c in net.route_crossings(p["edges"])}
            if all(len(s & {c.tls for c in net.route_crossings(q["edges"])}) <= 1 for q in picked):
                picked.append(p)
            if len(picked) == n:
                break
        return picked or pool[:n]

    t_perp, a_p, b_p = perp[1], perp[2], perp[3]
    t_opp, a_o, b_o = opp[1], opp[2], opp[3]
    types5 = ["ambulance", "fire_engine", "police", "ambulance", "fire_engine"]
    five = [{"type": ty, "edges": p["edges"], "delay": i * 12.0} for i, (ty, p) in enumerate(zip(types5, spread(5)))]
    single = max(pool[:20], key=lambda p: p["signals"])
    one = [{"type": "ambulance", "edges": single["edges"], "delay": 0.0}]
    trio = [{"type": ty, "edges": p["edges"], "delay": i * 10.0}
            for i, (ty, p) in enumerate(zip(["ambulance", "fire_engine", "police"], corridor))]
    perp_evs = synced(t_perp, [a_p, b_p], ["ambulance", "ambulance"])
    perp_mixed = synced(t_perp, [a_p, b_p], ["ambulance", "police"])

    scenarios = [
        dict(id="single", name="Single emergency vehicle", traffic="medium", evs=one,
             description="One ambulance on a multi-signal route."),
        dict(id="opposite", name="Two EVs, opposite directions", traffic="medium", focus=t_opp.id,
             evs=synced(t_opp, [a_o, b_o], ["ambulance", "fire_engine"]),
             description=f"Head-on approaches at {t_opp.name}. One phase can serve both, so they run concurrently."),
        dict(id="perpendicular", name="Two EVs, perpendicular", traffic="medium", focus=t_perp.id, evs=perp_evs,
             description=f"Crossing approaches at {t_perp.name}. No phase can serve both, so the coordinator arbitrates."),
        dict(id="connected", name="Three EVs, connected signals", traffic="medium", evs=trio,
             description="Three vehicles through a shared chain of signals."),
        dict(id="five", name="Five EVs across the city", traffic="medium", evs=five,
             description="Five vehicles spread over the network."),
        dict(id="low", name="Low traffic", traffic="low", evs=one,
             description="One ambulance in light traffic: expect smaller radii."),
        dict(id="medium", name="Medium traffic", traffic="medium", evs=one,
             description="One ambulance in moderate traffic."),
        dict(id="high", name="High traffic", traffic="high", evs=one,
             description="One ambulance in heavy traffic: expect larger radii."),
        dict(id="conflict", name="Simultaneous conflict", traffic="high", focus=t_perp.id, evs=perp_mixed,
             description=f"Ambulance and police reach {t_perp.name} together in heavy traffic."),
    ]
    SCENARIOS_FILE.write_text(json.dumps({"scenarios": scenarios, "pool": pool,
                                          "targets": {t.id: {f"{p[0]}|{p[1]}": r for p, r in rs.items()}
                                                      for t, rs in ((net.tls[k], v) for k, v in routes.items())}}))
    print(f"pool={len(pool)} max signals={pool[0]['signals']} big tls={len(big)}")
    print(f"perpendicular @ {t_perp.name} ({t_perp.source}) angle {angle_between(t_perp, a_p[0], b_p[0]):.0f}")
    print(f"opposite @ {t_opp.name} ({t_opp.source}) angle {angle_between(t_opp, a_o[0], b_o[0]):.0f}")


if __name__ == "__main__":
    main()
