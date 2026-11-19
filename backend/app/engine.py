"""Simulation engine thread: the only thread that talks to SUMO.

API handlers post commands to a queue and read an immutable view. Publishing is
rate-limited and non-blocking, so browser speed cannot affect simulation pacing.
"""
from __future__ import annotations

import json
import logging
import queue
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

import orjson

from .config import SCENARIOS_FILE, STEP_LENGTH, TRAFFIC_LEVELS
from .core.policy import FixedRadius, ModelNotTrained, NoPriority, RadiusPolicy, XGBoostRadius
from .core.simcore import EV_TYPES, EvSpec, SimCore
from .core.topology import NetworkModel
from .hub import Hub

log = logging.getLogger("engine")
PROTOCOL = 1
WARMUP_S = 400.0            # same as dataset generation
WARM_SLICE_S = 0.1          # wall time per warm-up slice
PUBLISH_MIN_INTERVAL = 0.2     # s of wall time
FULL_VIEW_INTERVAL = 1.0
INTERSECTION_EVERY = 1.0       # s of simulation
MAX_ACTIVE_EVS = 8
EV_PREFIX = {"ambulance": "AMB", "fire_engine": "FIRE", "police": "POL"}
VEHICLE_TYPES = ["car", "motorcycle", "bus", "truck"]


@dataclass
class RunConfig:
    scenario: str
    traffic: str
    policy: str
    seed: int


class CommandError(Exception):
    pass


class SimulationEngine:
    def __init__(self, net: NetworkModel, hub: Hub) -> None:
        self.net = net
        self.hub = hub
        data = json.loads(SCENARIOS_FILE.read_text())
        self.scenarios: dict[str, dict] = {s["id"]: s for s in data["scenarios"]}
        self.pool: list[dict] = data["pool"]
        self.model: XGBoostRadius | None = None
        self.model_error: str | None = None
        self.load_model()
        self.commands: queue.Queue[tuple[str, Any, queue.Queue]] = queue.Queue()
        self.core: SimCore | None = None
        self.cfg = RunConfig("perpendicular", self.scenarios["perpendicular"]["traffic"],
                             "xgboost" if self.model else "fixed_300", 42)
        self.status = "idle"
        self.message: str | None = None
        self.speed = 1.0
        self.achieved = 0.0
        self.warmup = 0.0
        self.run_id = 0
        self.seq = 0
        self.ev_counter = 0
        self.rng = random.Random(42)
        self.sent_routes: dict[str, int] = {}
        self.last_publish = 0.0
        self.last_view = 0.0
        self.last_intersections = -1e9
        self.last_metrics_t = -1e9
        self.view: dict = self._full_state()
        self.thread = threading.Thread(target=self._run, name="sim-engine", daemon=True)
        self.stopping = False

    # ---- public API (any thread) -----------------------------------------
    def load_model(self) -> None:
        try:
            self.model = XGBoostRadius()
            self.model_error = None
        except ModelNotTrained as e:
            self.model, self.model_error = None, str(e)

    def start_thread(self) -> None:
        self.thread.start()

    def stop_thread(self) -> None:
        self.stopping = True
        self.thread.join(timeout=5)

    def submit(self, name: str, arg: Any = None, timeout: float = 30.0) -> str:
        reply: queue.Queue = queue.Queue(maxsize=1)
        self.commands.put((name, arg, reply))
        try:
            ok, detail = reply.get(timeout=timeout)
        except queue.Empty:
            raise CommandError("Simulation engine did not respond") from None
        if not ok:
            raise CommandError(detail)
        return detail

    def status_dict(self) -> dict:
        s = self.scenarios.get(self.cfg.scenario, {})
        return {
            "run_id": self.run_id, "status": self.status, "t": round(self.core.now, 1) if self.core else 0.0,
            "speed": self.speed, "achieved_speed": round(self.achieved, 2), "scenario": self.cfg.scenario,
            "scenario_name": s.get("name"), "traffic": self.cfg.traffic,
            "scale": round(self.core.scale, 2) if self.core else None, "policy": self.cfg.policy,
            "message": self.message, "warmup_progress": round(self.warmup, 3), "clients": len(self.hub.clients),
        }

    # ---- thread ------------------------------------------------------------
    def _run(self) -> None:
        next_step = time.perf_counter()
        window_t, window_sim = time.perf_counter(), 0.0
        while not self.stopping:
            self._drain_commands()
            if self.status == "warming":
                self._warm_tick()
                self.achieved, window_sim = 0.0, 0.0
                next_step = window_t = time.perf_counter()
                continue
            if self.status != "running" or self.core is None:
                self._publish(force=self.status != "idle" or self.hub.needs_full)
                time.sleep(0.05)
                next_step = window_t = time.perf_counter()
                window_sim = 0.0
                continue
            now = time.perf_counter()
            if now < next_step:
                time.sleep(min(next_step - now, 0.01))
                continue
            try:
                self.core.step()
            except Exception as e:     # SUMO died or TraCI failed: stop and say so
                log.exception("simulation step failed")
                self._fail(f"Simulation stopped: {e}")
                continue
            window_sim += STEP_LENGTH
            next_step += STEP_LENGTH / self.speed
            behind = time.perf_counter() - next_step
            if behind > 0.25:      # drop lost time rather than sprint to catch up
                next_step = time.perf_counter()
            if time.perf_counter() - window_t >= 1.0:
                self.achieved = window_sim / (time.perf_counter() - window_t)
                window_t, window_sim = time.perf_counter(), 0.0
            if self.core.conn.simulation.getMinExpectedNumber() == 0:
                self.status, self.message = "finished", "All vehicles have left the network."
            self._publish()
        self._close_core()

    def _drain_commands(self) -> None:
        while True:
            try:
                name, arg, reply = self.commands.get_nowait()
            except queue.Empty:
                return
            try:
                reply.put((True, getattr(self, f"_cmd_{name}")(arg) or ""))
            except CommandError as e:
                reply.put((False, str(e)))
            except Exception as e:
                log.exception("command %s failed", name)
                reply.put((False, f"{name} failed: {e}"))

    def _fail(self, msg: str) -> None:
        self.status, self.message = "error", msg
        self._close_core()
        self.hub.request_full()

    def _close_core(self) -> None:
        if self.core is not None:
            self.core.close()
            self.core = None

    def _policy(self, name: str) -> RadiusPolicy:
        if name == "xgboost":
            if self.model is None:
                raise CommandError(self.model_error or "Model not available")
            return self.model
        if name == "none":
            return NoPriority()
        return FixedRadius(float(name.split("_")[1]))

    # ---- commands (engine thread) --------------------------------------------
    def _cmd_select(self, cmd: dict) -> str:
        s = self.scenarios.get(cmd["scenario"])
        if s is None:
            raise CommandError(f"Unknown scenario {cmd['scenario']!r}")
        self._policy(cmd["policy"])
        self.cfg = RunConfig(s["id"], cmd.get("traffic") or s["traffic"], cmd["policy"], cmd["seed"])
        if cmd.get("autostart"):
            return self._cmd_start(None)
        self._cmd_reset(None)
        return f"Selected {s['name']}"

    def _cmd_start(self, _: Any) -> str:
        self._policy(self.cfg.policy)          # refuse now, rather than failing part way through
        self._close_core()
        self.run_id += 1
        self.status, self.message, self.warmup = "warming", "Warming up traffic", 0.0
        self.sent_routes, self.ev_counter = {}, 0
        self.rng = random.Random(self.cfg.seed)
        self.hub.request_full()
        self._publish(force=True)
        return f"Starting {self.scenarios[self.cfg.scenario]['name']}"

    def _warm_tick(self) -> None:
        """Run a short slice of the warm-up, so that commands are never locked out while it runs."""
        try:
            if self.core is None:
                core = SimCore(self.net, self._policy(self.cfg.policy), scale=TRAFFIC_LEVELS[self.cfg.traffic],
                               seed=self.cfg.seed)
                self.core = core
                core.start()
            core = self.core
            end = time.perf_counter() + WARM_SLICE_S
            while core.now < WARMUP_S and time.perf_counter() < end:
                core.step()
        except Exception as e:
            log.exception("start failed")
            self._fail(f"Could not start SUMO: {e}")
            return
        self.warmup = core.now / WARMUP_S
        if core.now < WARMUP_S:
            self._publish(force=True)
            return
        core.vehicle_delta()
        core.new_events.clear()
        s = self.scenarios[self.cfg.scenario]
        ids = [self._next_id(e["type"]) for e in s["evs"]]
        core.schedule_scenario(s["evs"], ids, core.now + 5.0)
        self.status, self.message, self.warmup = "running", None, 1.0
        self.hub.request_full()
        self._publish(force=True)

    def _next_id(self, ev_type: str) -> str:
        self.ev_counter += 1
        return f"{EV_PREFIX[ev_type]}-{self.ev_counter}"

    def _cmd_pause(self, _: Any) -> str:
        if self.status != "running":
            raise CommandError(f"Cannot pause while {self.status}")
        self.status = "paused"
        return "Paused"

    def _cmd_resume(self, _: Any) -> str:
        if self.status != "paused":
            raise CommandError(f"Cannot resume while {self.status}")
        self.status = "running"
        return "Resumed"

    def _cmd_reset(self, _: Any) -> str:
        self._close_core()
        self.run_id += 1
        self.status, self.message, self.warmup = "idle", None, 0.0
        self.hub.request_full()
        self._publish(force=True)
        return "Reset"

    def _cmd_speed(self, speed: float) -> str:
        self.speed = speed
        return f"Speed {speed}x"

    def _cmd_demand(self, scale: float) -> str:
        if self.core is None:
            raise CommandError("No simulation running")
        self.core.conn.simulation.setScale(scale)
        self.core.scale = scale
        return f"Demand scale {scale}"

    def _cmd_dispatch(self, ev_type: str) -> str:
        if self.core is None or self.status not in ("running", "paused"):
            raise CommandError("No simulation running")
        if ev_type not in EV_TYPES:
            raise CommandError(f"Unknown vehicle type {ev_type}")
        if len(self.core.evs) + len(self.core.scheduled) >= MAX_ACTIVE_EVS:
            raise CommandError(f"Limit of {MAX_ACTIVE_EVS} active emergency vehicles reached")
        route = self.rng.choice(self.pool)
        vid = self._next_id(ev_type)
        self.core.schedule(EvSpec(vid, ev_type, route["edges"], self.core.now + 1.0))
        return vid

    def _cmd_reroute(self, ev_id: str) -> str:
        if self.core is None or ev_id not in self.core.evs:
            raise CommandError(f"{ev_id} is not active")
        current = self.core.evs[ev_id].edges[-1]
        options = [r["edges"][-1] for r in self.pool if r["edges"][-1] != current]
        for destination in self.rng.sample(options, min(6, len(options))):
            try:
                self.core.reroute(ev_id, destination)
                return f"{ev_id} rerouted"
            except ValueError as e:
                last = str(e)
            except Exception as e:     # TraCI reports an unreachable destination as an error
                last = str(e)
        raise CommandError(f"Could not reroute {ev_id}: {last}")

    # ---- publishing ------------------------------------------------------------
    def _sim_block(self) -> dict:
        return self.status_dict()

    def _full_state(self) -> dict:
        core = self.core
        base: dict = {"type": "snapshot", "v": PROTOCOL, "seq": self.seq, "run_id": self.run_id,
                      "t": round(core.now, 1) if core else 0.0, "sim": self._sim_block(),
                      "veh": {"add": [], "del": [], "pos": []}, "evs": [], "routes": {}, "signals": {},
                      "intersections": [], "requests": [], "events": [], "metrics": None, "history": []}
        if core is None or core.coord is None:
            return base
        base.update(
            veh=core.vehicle_full(),
            evs=[core.ev_dict(e) for e in core.evs.values()],
            routes={e.id: {"version": e.route_version, "coords": e.route_coords, "cum": e.route_cum}
                    for e in core.evs.values()},
            signals={t: s[0] for t, s in core.signal_state.items()},
            intersections=[core.intersection_dict(t) for t in self.net.tls],
            requests=[core.request_dict(r) for r in core.recent_requests()],
            events=list(core.events)[-120:],
            metrics=core.metrics.summary(core),
            history=list(core.metrics.history),
        )
        return base

    def _publish(self, force: bool = False) -> None:
        wall = time.perf_counter()
        if not force and wall - self.last_publish < PUBLISH_MIN_INTERVAL:
            return
        if force and wall - self.last_publish < 0.1 and not self.hub.needs_full:
            return
        self.last_publish = wall
        self.seq += 1
        core = self.core
        frame: bytes | None = None
        if core is not None and core.coord is not None and self.status in ("running", "paused"):
            frame = orjson.dumps(self._frame(core))
        elif self.status != "idle":
            frame = orjson.dumps({"type": "status", "v": PROTOCOL, "seq": self.seq, "sim": self._sim_block()})
        full = None
        if self.hub.needs_full or wall - self.last_view >= FULL_VIEW_INTERVAL:
            self.last_view = wall
            state = self._full_state()
            self.view = state
            if self.hub.needs_full:
                full = orjson.dumps(state)
        self.hub.publish(frame, full)

    def _frame(self, core: SimCore) -> dict:
        routes: dict[str, dict] = {}
        for e in core.evs.values():
            if self.sent_routes.get(e.id) != e.route_version:
                self.sent_routes[e.id] = e.route_version
                routes[e.id] = {"version": e.route_version, "coords": e.route_coords, "cum": e.route_cum}
        signals = {t: core.signal_state[t][0] for t in core.changed_signals}
        core.changed_signals.clear()
        d: dict = {"type": "frame", "v": PROTOCOL, "seq": self.seq, "run_id": self.run_id, "t": round(core.now, 1),
                   "sim": self._sim_block(), "veh": core.vehicle_delta(),
                   "evs": [core.ev_dict(e) for e in core.evs.values()], "routes": routes, "signals": signals,
                   "requests": [core.request_dict(r) for r in core.recent_requests()],
                   "events": core.new_events}
        core.new_events = []
        if core.now - self.last_intersections >= INTERSECTION_EVERY or signals:
            self.last_intersections = core.now
            d["intersections"] = [core.intersection_dict(t) for t in self.net.tls]
        if core.metrics.latest.get("t") != self.last_metrics_t:
            self.last_metrics_t = core.metrics.latest.get("t", 0.0)
            d["metrics"] = core.metrics.latest
            if core.metrics.history:
                d["history_point"] = core.metrics.history[-1]
        return d

    def vehicles(self) -> list[dict]:
        veh = self.view["veh"]
        types = {k: c for k, c in veh["add"]}
        p = veh["pos"]
        return [{"id": int(p[i]), "type": VEHICLE_TYPES[types.get(int(p[i]), 0)], "lon": p[i + 1], "lat": p[i + 2],
                 "angle": p[i + 3], "speed": p[i + 4]} for i in range(0, len(p), 5)]
