"""Feature extraction for the radius model.

This is the only definition of the features. Dataset generation and live inference
both call extract(), so the model cannot see a different feature at run time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .topology import GREEN, Crossing

if TYPE_CHECKING:
    from .simcore import EvState, SimCore

FEATURES = [
    "ev_speed",            # m/s
    "ev_class",            # 0 ambulance, 1 fire engine, 2 police
    "dist_to_signal",      # m along the route to the stop line
    "approach_lanes",
    "speed_limit",         # m/s on the approach edge
    "queue_ahead",         # halted vehicles between the EV and the stop line
    "veh_ahead",
    "density_ahead",       # veh/km/lane
    "mean_speed_ahead",    # m/s
    "link_green",          # 1 if the EV movement is green now
    "time_to_green",       # s until green under the fixed program
    "green_remaining",     # s of green left under the fixed program
    "cross_queue",         # halted vehicles on the other approaches
    "cross_density",       # veh/km/lane on the other approaches
    "downstream_occupancy",  # % on the exit edge
]
EV_CLASS = {"ambulance": 0, "fire_engine": 1, "police": 2}

# Physically meaningful combinations, computed from the features above.
DERIVED = ["eta_free", "green_at_arrival", "wait_at_arrival", "green_slack", "queue_clear_s"]
# The model scores a (traffic state, candidate radius) pair.
MODEL_COLUMNS = FEATURES + DERIVED + ["radius", "radius_minus_dist"]


def derived(f: dict[str, float]) -> list[float]:
    eta = f["dist_to_signal"] / max(f["speed_limit"] * 1.25, 2.0)     # EVs run about 25 % over the limit
    green, left, ttg = f["link_green"], f["green_remaining"], f["time_to_green"]
    at_arrival = (green and left > eta) or (not green and ttg < eta)
    slack = left - eta if green else eta - ttg
    return [eta, float(at_arrival), max(ttg - eta, 0.0), slack, f["queue_ahead"] * 2.0 / max(f["approach_lanes"], 1.0)]


def model_rows(f: dict[str, float], candidates) -> list[list[float]]:
    """One model input row per candidate radius. Used by both training and live inference."""
    base = [f[k] for k in FEATURES] + derived(f)
    return [base + [float(r), float(r) - f["geo_dist"]] for r in candidates]


def extract(core: "SimCore", ev: "EvState", c: Crossing) -> dict[str, float]:
    conn, net = core.conn, core.net
    info = net.tls[c.tls]
    ahead = ev.edges[max(ev.route_index, 0):c.route_index + 1]
    n = halt = 0
    weighted_speed = km_lanes = 0.0
    for e in ahead:
        en = conn.edge.getLastStepVehicleNumber(e)
        n += en
        halt += conn.edge.getLastStepHaltingNumber(e)
        weighted_speed += conn.edge.getLastStepMeanSpeed(e) * en
        edge = net.net.getEdge(e)
        km_lanes += edge.getLength() / 1000.0 * edge.getLaneNumber()
    in_edge = net.net.getEdge(c.in_edge)
    limit = in_edge.getSpeed()

    state, phase, next_switch = core.signal_state[c.tls]
    link = c.links[0]
    green = state[link] in GREEN
    if core.ctrl[c.tls].active:        # another EV holds the junction: the program timings do not apply
        ttg, left = (0.0, 10.0) if green else (20.0, 0.0)
    else:
        ttg, left = info.time_until_green(link, phase, max(next_switch - core.now, 0.0))

    cross_q = cross_n = 0
    cross_km = 0.0
    for a in info.approaches.values():
        if a.edge == c.in_edge:
            continue
        s = core.edge_stats.get(a.edge)
        if s:
            cross_n += s[0]
            cross_q += s[1]
        cross_km += net.edge_length(a.edge) / 1000.0 * a.lanes

    return {
        "ev_speed": ev.speed,
        "ev_class": float(EV_CLASS[ev.type]),
        "dist_to_signal": ev.route_dist,
        "approach_lanes": float(in_edge.getLaneNumber()),
        "speed_limit": limit,
        "queue_ahead": float(halt),
        "veh_ahead": float(n),
        "density_ahead": n / km_lanes if km_lanes else 0.0,
        "mean_speed_ahead": weighted_speed / n if n else limit,
        "link_green": 1.0 if green else 0.0,
        "time_to_green": ttg,
        "green_remaining": left,
        "cross_queue": float(cross_q),
        "cross_density": cross_n / cross_km if cross_km else 0.0,
        "downstream_occupancy": conn.edge.getLastStepOccupancy(c.out_edge),
        "geo_dist": ev.geo_dist,       # not a model feature by itself; feeds radius_minus_dist
    }
