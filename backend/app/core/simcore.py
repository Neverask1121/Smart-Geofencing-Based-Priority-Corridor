"""SimCore: one SUMO run with EV tracking, radius prediction, coordination and signal control.

Dataset generation, evaluation and the live application all drive this class, so the
model is trained against exactly the controller that it runs with.
"""
from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import traci
import traci.constants as tc

from ..config import CONTENDER_LOOKAHEAD, PREDICT_EVERY, STEP_LENGTH, SUMO_CFG, sumo_binary
from .coordination import OPEN, Coordinator, Request, Status
from .features import extract
from .metrics import Metrics
from .policy import RadiusPolicy
from .signals import Mode, SafetyMonitor, SignalController, build_plan
from .topology import Crossing, NetworkModel

VEHICLE_VARS = [tc.VAR_POSITION, tc.VAR_SPEED, tc.VAR_ANGLE, tc.VAR_TIMELOSS]
EV_VARS = [tc.VAR_POSITION, tc.VAR_SPEED, tc.VAR_ANGLE, tc.VAR_ROAD_ID, tc.VAR_LANEPOSITION, tc.VAR_ROUTE_INDEX,
           tc.VAR_TIMELOSS]
SIM_VARS = [tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS,
            tc.VAR_COLLIDING_VEHICLES_NUMBER, tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER]
TLS_VARS = [tc.TL_RED_YELLOW_GREEN_STATE, tc.TL_CURRENT_PHASE, tc.TL_NEXT_SWITCH]
EDGE_VARS = [tc.LAST_STEP_VEHICLE_NUMBER, tc.LAST_STEP_VEHICLE_HALTING_NUMBER, tc.LAST_STEP_MEAN_SPEED]
CIVILIAN_CODES = {"car": 0, "motorcycle": 1, "bus": 2, "truck": 3}
EV_TYPES = ("ambulance", "fire_engine", "police")


@dataclass
class EvSpec:
    id: str
    type: str
    edges: list[str]
    depart: float = 0.0            # absolute simulation time
    target_in_edge: str | None = None  # dataset runs: request priority only on this approach
    sync_leader: str | None = None     # dispatch when this EV's live ETA falls to sync_travel_s,
    sync_travel_s: float = 0.0         # so both reach the shared signal together despite traffic


@dataclass
class EvState:
    spec: EvSpec
    id: str
    type: str
    edges: list[str]
    crossings: list[Crossing]
    color: int
    route_coords: list[list[float]]
    route_cum: list[float]
    edge_start: list[float]
    edge_cum: list[float]
    route_version: int = 1
    departed_at: float | None = None
    x: float = 0.0
    y: float = 0.0
    lon: float = 0.0
    lat: float = 0.0
    angle: float = 0.0
    speed: float = 0.0
    speed_ema: float = 8.0
    route_index: int = 0
    lane_pos: float = 0.0
    time_loss: float = 0.0
    next_i: int = 0
    route_dist: float = 0.0        # metres along the route to the stop line
    geo_dist: float = 0.0          # straight-line metres to the intersection: what the geofence tests
    eta: float = 0.0
    radius: float | None = None
    features: dict[str, float] = field(default_factory=dict)
    predicted_at: float = -1e9
    predictions: int = 0
    in_geofence: bool = False
    request: Request | None = None

    @property
    def crossing(self) -> Crossing | None:
        return self.crossings[self.next_i] if self.next_i < len(self.crossings) else None


def _r(v: float | None, n: int = 1) -> float | None:
    return None if v is None else round(v, n)


class SimCore:
    def __init__(self, net: NetworkModel, policy: RadiusPolicy, *, scale: float = 0.7, seed: int = 42,
                 track_civilians: bool = True, extra_args: Iterable[str] = ()) -> None:
        self.net = net
        self.policy = policy
        self.scale = scale
        self.seed = seed
        self.track_civilians = track_civilians
        self.extra_args = list(extra_args)
        self.label = f"sim-{uuid.uuid4().hex[:8]}"
        self.conn: Any = None
        self.now = 0.0
        self.ctrl: dict[str, SignalController] = {}
        self.monitor: dict[str, SafetyMonitor] = {}
        self.signal_state: dict[str, tuple[str, int, float]] = {}
        self.edge_stats: dict[str, tuple[int, int, float]] = {}
        self.foe_cache: dict[tuple[str, int], set[int]] = {}
        self.evs: dict[str, EvState] = {}
        self.scheduled: list[EvSpec] = []
        self.finished_evs: list[dict] = []
        self.events: deque[dict] = deque(maxlen=400)
        self.new_events: list[dict] = []
        self.event_seq = 0
        self.veh: dict[str, list] = {}        # id -> [key, type, x, y, angle, speed]
        self.veh_key = 0
        self.added: list[list] = []
        self.removed: list[int] = []
        self.changed_signals: set[str] = set()
        self.sent_pos: dict[int, tuple[float, float]] = {}
        self.metrics = Metrics()
        self.coord: Coordinator | None = None
        self.color_seq = 0

    # ---- lifecycle -----------------------------------------------------
    def start(self) -> None:
        cmd = [sumo_binary(), "-c", str(SUMO_CFG), "--step-length", str(STEP_LENGTH), "--scale", str(self.scale),
               "--seed", str(self.seed), "--no-step-log", "true", "--no-warnings", "true", *self.extra_args]
        traci.start(cmd, label=self.label, numRetries=60)
        self.conn = traci.getConnection(self.label)
        self.conn.simulation.subscribe(SIM_VARS)
        for tid, info in self.net.tls.items():
            self.conn.trafficlight.subscribe(tid, TLS_VARS)
            for e in info.approaches:
                self.conn.edge.subscribe(e, EDGE_VARS)
            self.ctrl[tid] = SignalController(info, self, self._signal_event(tid))
            self.monitor[tid] = SafetyMonitor(info)
        self.coord = Coordinator(self.net.tls, self.ctrl, self.foe_links, self.emit)
        self.now = self.conn.simulation.getTime()

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    # ---- SignalIO --------------------------------------------------------
    def set_state(self, tls: str, state: str) -> None:
        self.conn.trafficlight.setRedYellowGreenState(tls, state)

    def resume_program(self, tls: str, program: str, phase: int) -> None:
        self.conn.trafficlight.setProgram(tls, program)
        self.conn.trafficlight.setPhase(tls, phase)

    def foe_links(self, tls: str, link: int) -> set[int]:
        """Links with right of way over `link`, as reported by SUMO's junction logic."""
        key = (tls, link)
        if key not in self.foe_cache:
            info = self.net.tls[tls]
            lk = info.links[link]
            lanes = set(self.conn.lane.getFoes(lk.in_lane, lk.out_lane))
            self.foe_cache[key] = {o.index for o in info.links.values() if o.in_lane in lanes and o.index != link}
        return self.foe_cache[key]

    # ---- events ----------------------------------------------------------
    def emit(self, kind: str, now: float, *, tls: str | None = None, ev: str | None = None, req: str | None = None,
             message: str = "", detail: dict | None = None) -> None:
        self.event_seq += 1
        e = {"seq": self.event_seq, "t": round(now, 1), "kind": kind, "tls": tls, "ev": ev, "req": req,
             "message": message, "detail": detail}
        self.events.append(e)
        self.new_events.append(e)

    def _signal_event(self, tls: str):
        def on_event(kind: str, msg: str) -> None:
            self.emit(kind, self.now, tls=tls, message=f"{self.net.tls[tls].name}: {msg}")
        return on_event

    # ---- emergency vehicles ------------------------------------------------
    def schedule(self, spec: EvSpec) -> None:
        self.scheduled.append(spec)
        self.scheduled.sort(key=lambda s: s.depart)

    def _spawn(self, spec: EvSpec) -> None:
        rid = f"r_{spec.id}"
        self.conn.route.add(rid, spec.edges)
        self.conn.vehicle.add(spec.id, rid, typeID=spec.type, departLane="best", departSpeed="max")
        coords, cum, starts = self.net.route_polyline(spec.edges)
        lengths = np.cumsum([0.0] + [self.net.edge_length(e) for e in spec.edges])
        crossings = self.net.route_crossings(spec.edges)
        self.evs[spec.id] = EvState(spec, spec.id, spec.type, list(spec.edges), crossings, self.color_seq % 6,
                                    coords, cum, starts, [float(v) for v in lengths])
        self.color_seq += 1
        self.conn.vehicle.subscribe(spec.id, EV_VARS)
        self.emit("ev_dispatched", self.now, ev=spec.id, message=f"{spec.id} dispatched on a {cum[-1] / 1000:.1f} km route "
                                                                 f"through {len(crossings)} signals.")

    def _due(self, spec: EvSpec) -> bool:
        if spec.sync_leader is None:
            return spec.depart <= self.now
        leader = self.evs.get(spec.sync_leader)
        if leader is None or leader.crossing is None:       # leader finished or never appeared
            return spec.depart <= self.now
        if leader.departed_at is None or leader.route_dist <= 0:
            return False
        return leader.route_dist / max(leader.speed_ema, 6.0) <= spec.sync_travel_s

    def schedule_scenario(self, evs: list[dict], ids: list[str], start: float) -> None:
        """Queue a scenario's EVs. A vehicle with a `sync` entry waits for its leader's live ETA;
        `depart` is then only a fallback deadline."""
        for vid, e in zip(ids, evs):
            sync = e.get("sync")
            self.schedule(EvSpec(vid, e["type"], e["edges"], start + (240.0 if sync else e["delay"]),
                                 sync_leader=ids[sync["leader"]] if sync else None,
                                 sync_travel_s=sync["travel_s"] if sync else 0.0))

    def _check_route(self, ev: EvState) -> None:
        """Pick up route changes so the coordinator and the map stay truthful."""
        route = list(self.conn.vehicle.getRoute(ev.id))
        if route == ev.edges:
            return
        ev.edges = route
        ev.crossings = self.net.route_crossings(route)
        ev.next_i = 0
        ev.route_coords, ev.route_cum, ev.edge_start = self.net.route_polyline(route)
        ev.edge_cum = [float(v) for v in np.cumsum([0.0] + [self.net.edge_length(e) for e in route])]
        ev.route_version += 1
        # Request keys hold route positions, which no longer mean anything: start this EV afresh.
        for r in list(self.coord.requests.values()):
            if r.ev_id == ev.id and r.open:
                self.coord.close(self.now, r, Status.CANCELLED, f"{ev.id} changed route")
        self.coord.by_key = {k: v for k, v in self.coord.by_key.items() if k[0] != ev.id}
        ev.route_index = 0
        ev.request, ev.in_geofence, ev.radius, ev.features = None, False, None, {}
        ev.predicted_at = -1e9
        self.emit("ev_rerouted", self.now, ev=ev.id, message=f"{ev.id} route changed; now {len(ev.crossings)} signals.")

    def reroute(self, ev_id: str, destination: str) -> int:
        """Send an EV to a new destination. Returns the new route version."""
        ev = self.evs[ev_id]
        road = self.conn.vehicle.getRoadID(ev_id)
        if not road or road.startswith(":"):
            raise ValueError(f"{ev_id} is inside a junction; try again in a moment")
        edges = list(self.conn.simulation.findRoute(road, destination, vType=ev.type).edges)
        if len(edges) < 2:
            raise ValueError(f"No route from {ev_id}'s position to that destination")
        self.conn.vehicle.setRoute(ev_id, edges)
        self._check_route(ev)
        return ev.route_version

    def _open_contenders(self, r: Request, ev: EvState) -> None:
        """Arbitrate fairly between EVs that will meet. Without this, whichever vehicle's radius
        happens to fire first would win outright, however urgent the other one is. A conflicting
        EV arriving at about the same time gets its request now, so both are scored together."""
        coord = self.coord
        assert coord is not None
        if any(o.status in (Status.ACCEPTED, Status.SERVING) for o in coord.open_at(r.tls)):
            return
        info = self.net.tls[r.tls]
        for o in self.evs.values():
            c = o.crossing
            if (o is ev or c is None or c.tls != r.tls or o.departed_at is None or o.radius is None
                    or o.spec.target_in_edge is not None or (o.id, c.tls, c.route_index) in coord.by_key
                    or o.eta > ev.eta + CONTENDER_LOOKAHEAD):
                continue
            if build_plan(info, [r.crossing.links, c.links], lambda lk: self.foe_links(r.tls, lk)) is None:
                coord.open_request(self.now, o.id, o.type, c, o.radius, o.eta, o.geo_dist, early=True)

    def _update_ev(self, ev: EvState, res: dict) -> None:
        ev.x, ev.y = res[tc.VAR_POSITION]
        ev.speed = res[tc.VAR_SPEED]
        ev.angle = res[tc.VAR_ANGLE]
        ev.lane_pos = res[tc.VAR_LANEPOSITION]
        ev.route_index = res[tc.VAR_ROUTE_INDEX]
        ev.time_loss = res[tc.VAR_TIMELOSS]
        ev.lon, ev.lat = self.net.lonlat(ev.x, ev.y)
        ev.speed_ema += 0.1 * (ev.speed - ev.speed_ema)
        assert self.coord is not None

        while (c := ev.crossing) is not None and ev.route_index > c.route_index:
            r = self.coord.by_key.get((ev.id, c.tls, c.route_index))
            if r is not None and r.open:
                self.coord.close(self.now, r, Status.COMPLETED, f"{ev.id} cleared the intersection")
            ev.next_i += 1
            ev.request, ev.in_geofence, ev.radius, ev.features = None, False, None, {}
            ev.predicted_at = -1e9        # a new target signal gets a prediction straight away
        c = ev.crossing
        if c is None:
            ev.route_dist = ev.geo_dist = ev.eta = 0.0
            return
        on_edge = not res[tc.VAR_ROAD_ID].startswith(":")
        pos = ev.edge_cum[ev.route_index] + (ev.lane_pos if on_edge else self.net.edge_length(ev.edges[ev.route_index]))
        ev.route_dist = max(c.stop_m - pos, 0.0)
        info = self.net.tls[c.tls]
        ev.geo_dist = math.hypot(ev.x - info.x, ev.y - info.y)
        ev.eta = ev.route_dist / max(ev.speed_ema, 1.5)
        if ev.spec.target_in_edge is not None and c.in_edge != ev.spec.target_in_edge:
            return

        if self.now - ev.predicted_at >= PREDICT_EVERY:
            ev.predicted_at = self.now
            ev.features = extract(self, ev, c)
            ev.radius = self.policy.radius(ev.features)
            if ev.radius is not None:
                ev.predictions += 1
                self.metrics.radius_sum += ev.radius
                self.metrics.radius_n += 1

        if ev.radius is None:
            return
        ev.in_geofence = ev.geo_dist <= ev.radius
        r = self.coord.by_key.get((ev.id, c.tls, c.route_index))
        if r is None and ev.in_geofence:
            r = self.coord.open_request(self.now, ev.id, ev.type, c, ev.radius, ev.eta, ev.geo_dist)
            self._open_contenders(r, ev)
        if r is not None:
            ev.request = r
            r.eta, r.dist = ev.eta, ev.geo_dist

    # ---- step --------------------------------------------------------------
    def step(self) -> None:
        conn = self.conn
        for spec in [s for s in self.scheduled if self._due(s)]:
            self.scheduled.remove(spec)
            self._spawn(spec)
        conn.simulationStep()
        self.now = conn.simulation.getTime()
        sim = conn.simulation.getSubscriptionResults()
        for vid in sim[tc.VAR_DEPARTED_VEHICLES_IDS]:
            if vid in self.evs:
                self.evs[vid].departed_at = self.now
            elif self.track_civilians:
                conn.vehicle.subscribe(vid, VEHICLE_VARS)
                self.veh_key += 1
                code = CIVILIAN_CODES.get(conn.vehicle.getTypeID(vid), 0)
                self.veh[vid] = [self.veh_key, code, 0.0, 0.0, 0.0, 0.0, 0.0]
                self.added.append([self.veh_key, code])
        for vid in sim[tc.VAR_ARRIVED_VEHICLES_IDS]:
            if vid in self.evs:
                self._ev_arrived(self.evs.pop(vid))
            elif vid in self.veh:
                rec = self.veh.pop(vid)
                self.removed.append(rec[0])
                self.sent_pos.pop(rec[0], None)
                self.metrics.civilian_arrived(self.now, rec[6])
        self.metrics.collisions += sim[tc.VAR_COLLIDING_VEHICLES_NUMBER]
        self.metrics.teleports += sim[tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER]

        if self.track_civilians:
            for vid, res in conn.vehicle.getAllSubscriptionResults().items():
                rec = self.veh.get(vid)
                if rec is not None:
                    rec[2], rec[3] = res[tc.VAR_POSITION]
                    rec[4], rec[5], rec[6] = res[tc.VAR_ANGLE], res[tc.VAR_SPEED], res[tc.VAR_TIMELOSS]

        self.edge_stats = {e: (r[tc.LAST_STEP_VEHICLE_NUMBER], r[tc.LAST_STEP_VEHICLE_HALTING_NUMBER],
                               r[tc.LAST_STEP_MEAN_SPEED])
                           for e, r in conn.edge.getAllSubscriptionResults().items()}
        for tid, r in conn.trafficlight.getAllSubscriptionResults().items():
            state = r[tc.TL_RED_YELLOW_GREEN_STATE]
            old = self.signal_state.get(tid)
            if old is None or old[0] != state:
                self.changed_signals.add(tid)
            self.signal_state[tid] = (state, r[tc.TL_CURRENT_PHASE], r[tc.TL_NEXT_SWITCH])
            self.ctrl[tid].observe(self.now, state)
            self.monitor[tid].observe(self.now, state)

        assert self.coord is not None
        tick_route_check = int(self.now / STEP_LENGTH) % 10 == 0
        for ev in list(self.evs.values()):
            if ev.departed_at is None:
                continue
            res = conn.vehicle.getSubscriptionResults(ev.id)
            if not res:
                continue
            if tick_route_check:
                self._check_route(ev)
            self._update_ev(ev, res)
        self.coord.tick(self.now)
        for c in self.ctrl.values():
            c.tick(self.now)
        self.metrics.tick(self)

    def _ev_arrived(self, ev: EvState) -> None:
        assert self.coord is not None
        for r in self.coord.requests.values():
            if r.ev_id == ev.id and r.open:
                self.coord.close(self.now, r, Status.CANCELLED, f"{ev.id} left the network")
        trip = {"id": ev.id, "type": ev.type, "travel_time": round(self.now - (ev.departed_at or self.now), 1),
                "time_loss": round(ev.time_loss, 1), "distance_m": ev.route_cum[-1]}
        self.finished_evs.append(trip)
        self.metrics.ev_arrived(trip)
        self.emit("ev_arrived", self.now, ev=ev.id,
                  message=f"{ev.id} reached its destination in {trip['travel_time']:.0f} s.")

    # ---- serialisation -----------------------------------------------------
    def ev_status(self, ev: EvState) -> str:
        if ev.departed_at is None:
            return "dispatching"
        if ev.request is not None and ev.request.open:
            return ev.request.status.value
        if ev.crossing is None:
            return "final_leg"
        return "en_route"

    def ev_dict(self, ev: EvState, with_route: bool = False) -> dict:
        c = ev.crossing
        pos = 0.0
        i = min(ev.route_index, len(ev.edge_start) - 1)
        if i >= 0:
            frac = min(ev.lane_pos / max(self.net.edge_length(ev.edges[i]), 0.1), 1.0)
            nxt = ev.edge_start[i + 1] if i + 1 < len(ev.edge_start) else ev.route_cum[-1]
            pos = ev.edge_start[i] + frac * (nxt - ev.edge_start[i])
        upcoming = [x.tls for x in ev.crossings[ev.next_i:]]
        d = {
            "id": ev.id, "type": ev.type, "color": ev.color, "lon": round(ev.lon, 6), "lat": round(ev.lat, 6),
            "angle": round(ev.angle, 1), "speed": round(ev.speed, 1), "status": self.ev_status(ev),
            "next_tls": c.tls if c else None, "next_tls_name": self.net.tls[c.tls].name if c else None,
            "dist_to_tls": _r(ev.geo_dist) if c else None, "route_dist_to_tls": _r(ev.route_dist) if c else None,
            "eta": _r(ev.eta) if c else None, "radius": _r(ev.radius), "in_geofence": ev.in_geofence,
            "request_id": ev.request.id if ev.request else None,
            "request_status": ev.request.status.value if ev.request else None,
            "route_version": ev.route_version, "route_progress_m": round(pos, 1),
            "route_total_m": ev.route_cum[-1], "upcoming_tls": upcoming, "time_loss": round(ev.time_loss, 1),
            "travel_time": round(self.now - ev.departed_at, 1) if ev.departed_at is not None else 0.0,
            "predictions": ev.predictions,
            "features": {k: round(v, 2) for k, v in ev.features.items()},
        }
        if with_route:
            d["route"] = {"coords": ev.route_coords, "cum": ev.route_cum}
        return d

    def request_dict(self, r: Request) -> dict:
        return {
            "id": r.id, "ev_id": r.ev_id, "ev_type": r.ev_type, "tls": r.tls, "tls_name": self.net.tls[r.tls].name,
            "approach": r.approach, "movement": r.movement, "radius": r.radius, "eta": round(r.eta, 1),
            "dist": round(r.dist, 1), "status": r.status.value, "score": r.score, "score_parts": r.score_parts,
            "conflicts_with": r.conflicts_with, "arbitration": r.arbitration, "created_at": round(r.created_at, 1),
            "accepted_at": r.accepted_at, "served_at": r.served_at, "closed_at": r.closed_at, "early": r.early,
        }

    def intersection_dict(self, tid: str) -> dict:
        info = self.net.tls[tid]
        n = halted = 0
        speed_sum = km_lanes = 0.0
        for a in info.approaches.values():
            s = self.edge_stats.get(a.edge)
            if s:
                n += s[0]
                halted += s[1]
                speed_sum += s[2] * s[0]
            km_lanes += self.net.edge_length(a.edge) / 1000.0 * a.lanes
        ctrl = self.ctrl[tid]
        assert self.coord is not None
        reqs = self.coord.open_at(tid)
        state = self.signal_state.get(tid, ("", 0, 0.0))
        return {
            "id": tid, "state": state[0], "mode": "restoring" if ctrl.restoring else ctrl.mode.value,
            "target_state": ctrl.target.state if ctrl.target else None,
            "queue": halted, "vehicles": n, "density": round(n / km_lanes, 1) if km_lanes else 0.0,
            "avg_speed": round(speed_sum / n, 1) if n else None,
            "active_requests": [r.id for r in reqs if r.status in (Status.ACCEPTED, Status.SERVING)],
            "pending_requests": [r.id for r in reqs if r.status == Status.PENDING],
            "approaching_evs": [e.id for e in self.evs.values() if e.crossing and e.crossing.tls == tid],
            "safety_violations": len(self.monitor[tid].violations),
        }

    def recent_requests(self, limit: int = 60) -> list[Request]:
        assert self.coord is not None
        items = sorted(self.coord.requests.values(), key=lambda r: (r.status not in OPEN, -r.created_at))
        return items[:limit]

    def vehicle_delta(self) -> dict:
        """Vehicles added, removed or moved since the previous call, as compact arrays."""
        recs = list(self.veh.values())
        pos: list[float] = []
        if recs:
            ll = self.net.to_lonlat(np.array([[r[2], r[3]] for r in recs]))
            for r, (lon, lat) in zip(recs, ll):
                key = r[0]
                p = (r[2], r[3])
                old = self.sent_pos.get(key)
                if old is not None and abs(old[0] - p[0]) + abs(old[1] - p[1]) < 0.05:
                    continue
                self.sent_pos[key] = p
                pos += [key, round(float(lon), 6), round(float(lat), 6), round(r[4]), round(r[5], 1)]
        d = {"add": self.added, "del": self.removed, "pos": pos}
        self.added, self.removed = [], []
        return d

    def vehicle_full(self) -> dict:
        recs = list(self.veh.values())
        pos: list[float] = []
        if recs:
            ll = self.net.to_lonlat(np.array([[r[2], r[3]] for r in recs]))
            for r, (lon, lat) in zip(recs, ll):
                pos += [r[0], round(float(lon), 6), round(float(lat), 6), round(r[4]), round(r[5], 1)]
        return {"add": [[r[0], r[1]] for r in recs], "del": [], "pos": pos}

    @property
    def safety_violations(self) -> int:
        return sum(len(m.violations) for m in self.monitor.values())

    def controller_busy(self) -> bool:
        return any(c.mode != Mode.NORMAL for c in self.ctrl.values())
