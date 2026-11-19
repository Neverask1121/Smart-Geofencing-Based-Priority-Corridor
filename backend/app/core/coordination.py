"""Multi-EV coordination: request lifecycle, conflict detection and arbitration.

Runs per intersection each tick. A request being served is never pre-empted by a
new one, so priority cannot flip-flop. Requests that one phase can serve together
run concurrently; the rest wait, and their score grows with waiting time so
that a lower-class vehicle cannot be starved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from ..config import EV_TYPE_WEIGHT, MAX_HOLD, REQUEST_TTL, SCORE_W_ETA, SCORE_W_TYPE, SCORE_W_WAIT
from .signals import Mode, ServePlan, SignalController, build_plan
from .topology import TURNS, Crossing, TlsInfo


class Status(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    SERVING = "serving"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


OPEN = (Status.PENDING, Status.ACCEPTED, Status.SERVING)
CLOSE_EVENT = {Status.COMPLETED: "ev_cleared", Status.CANCELLED: "request_cancelled", Status.EXPIRED: "request_expired"}


@dataclass
class Request:
    id: str
    ev_id: str
    ev_type: str
    tls: str
    crossing: Crossing
    approach: str
    movement: str
    radius: float
    created_at: float
    eta: float
    dist: float
    status: Status = Status.PENDING
    score: float = 0.0
    score_parts: dict[str, float] = field(default_factory=dict)
    conflicts_with: list[str] = field(default_factory=list)
    arbitration: str = "Awaiting arbitration"
    accepted_at: float | None = None
    served_at: float | None = None
    closed_at: float | None = None
    early: bool = False      # opened by conflict lookahead, before the EV's own radius was reached

    @property
    def open(self) -> bool:
        return self.status in OPEN


def score_request(r: Request, now: float) -> tuple[float, dict[str, float]]:
    """Higher is more urgent. Vehicle class, closeness and waiting time all count."""
    type_part = EV_TYPE_WEIGHT.get(r.ev_type, 0.5)
    eta_part = 1.0 / (1.0 + max(r.eta, 0.0) / 20.0)
    wait_part = min(1.0, (now - r.created_at) / 30.0)
    total = SCORE_W_TYPE * type_part + SCORE_W_ETA * eta_part + SCORE_W_WAIT * wait_part
    return round(total, 3), {"type": round(type_part, 3), "eta": round(eta_part, 3), "wait": round(wait_part, 3)}


class Coordinator:
    def __init__(self, tls: dict[str, TlsInfo], controllers: dict[str, SignalController],
                 foe_links: Callable[[str, int], set[int]], emit: Callable[..., None]) -> None:
        self.tls = tls
        self.ctrl = controllers
        self.foe_links = foe_links
        self.emit = emit
        self.requests: dict[str, Request] = {}
        self.by_key: dict[tuple[str, str, int], Request] = {}
        self.seq = 0
        self.conflicts_detected = 0
        self._announced: set[frozenset[str]] = set()
        self._serve_start: dict[str, float] = {}

    # ---- lifecycle -----------------------------------------------------
    def open_request(self, now: float, ev_id: str, ev_type: str, c: Crossing, radius: float, eta: float,
                     dist: float, early: bool = False) -> Request:
        key = (ev_id, c.tls, c.route_index)
        if key in self.by_key:
            return self.by_key[key]
        self.seq += 1
        info = self.tls[c.tls]
        ap = info.approaches[c.in_edge]
        turn = TURNS.get(info.links[c.links[0]].turn, "through")
        r = Request(f"PR-{self.seq:04d}", ev_id, ev_type, c.tls, c, ap.label, turn, round(radius, 1), now, eta, dist,
                    early=early)
        self.requests[r.id] = r
        self.by_key[key] = r
        self.emit("request_created", now, tls=c.tls, ev=ev_id, req=r.id,
                  message=(f"{ev_id} arrives within the lookahead of a conflicting request (ETA {eta:.0f} s, "
                           f"{dist:.0f} m away). {r.id} opened early for arbitration ({ap.label} {turn})." if early else
                           f"{ev_id} entered its activation region: {dist:.0f} m ≤ radius {radius:.0f} m. "
                           f"{r.id} pending ({ap.label} {turn})."))
        return r

    def close(self, now: float, r: Request, status: Status, why: str) -> None:
        if not r.open:
            return
        r.status, r.closed_at, r.arbitration = status, now, why
        self.emit(CLOSE_EVENT[status], now, tls=r.tls, ev=r.ev_id, req=r.id, message=f"{r.id}: {why}")

    def open_at(self, tls: str) -> list[Request]:
        return [r for r in self.requests.values() if r.tls == tls and r.open]

    def _plan(self, tls: str, reqs: list[Request]) -> ServePlan | None:
        return build_plan(self.tls[tls], [r.crossing.links for r in reqs], lambda lk: self.foe_links(tls, lk))

    # ---- arbitration -----------------------------------------------------
    def tick(self, now: float) -> None:
        for r in list(self.requests.values()):
            if r.status == Status.PENDING and now - r.created_at > REQUEST_TTL:
                self.close(now, r, Status.EXPIRED, f"Not served within {REQUEST_TTL:.0f} s")
        busy = {r.tls for r in self.requests.values() if r.open}
        busy |= {t for t, c in self.ctrl.items() if c.active and not c.restoring}
        for tls in sorted(busy):
            self._tick_tls(now, tls)

    def _tick_tls(self, now: float, tls: str) -> None:
        ctrl = self.ctrl[tls]
        reqs = self.open_at(tls)
        for r in reqs:
            r.score, r.score_parts = score_request(r, now)
        active = [r for r in reqs if r.status in (Status.ACCEPTED, Status.SERVING)]
        pending = sorted((r for r in reqs if r.status == Status.PENDING), key=lambda r: (-r.score, r.id))

        # Hold limit: release a served request whose EV cannot reach the junction.
        start = self._serve_start.get(tls)
        if active and start is not None and now - start > MAX_HOLD:
            for r in active:
                self.close(now, r, Status.EXPIRED, f"Hold limit of {MAX_HOLD:.0f} s reached; released")
            active = []

        self._mark_conflicts(now, tls, pending, active)

        if active:
            # Late arrivals join when one phase can serve the whole group.
            for r in pending:
                plan = self._plan(tls, active + [r])
                if plan is not None:
                    ctrl.request(plan)
                    self._accept(now, r, f"Compatible with {', '.join(a.id for a in active)}: served concurrently")
                    active.append(r)
                else:
                    r.arbitration = f"Held: {active[0].id} is being served and conflicts with this movement"
            if ctrl.mode == Mode.SERVING:
                for r in active:
                    if r.status == Status.ACCEPTED:
                        self._serve(now, r)
            return

        if pending:
            self._start_next(now, tls, ctrl, pending)
            return

        if ctrl.active and not ctrl.restoring:
            self._serve_start.pop(tls, None)
            ctrl.release()
            if ctrl.active:
                self.emit("signal_transition", now, tls=tls, message="No priority demand left: restoring signal program")

    def _start_next(self, now: float, tls: str, ctrl: SignalController, pending: list[Request]) -> None:
        winner = pending[0]
        group = [winner]
        for r in pending[1:]:
            if self._plan(tls, group + [r]) is not None:
                group.append(r)
        plan = self._plan(tls, group)
        if plan is None:
            self.close(now, winner, Status.CANCELLED, "No signal phase can serve this movement")
            return
        ctrl.request(plan)
        self._serve_start[tls] = now
        held = [r for r in pending if r not in group]
        for r in group:
            if len(pending) == 1:
                why = "Only request at this intersection"
            elif len(group) > 1:
                why = "Selected: " + ", ".join(g.id for g in group) + " share a compatible phase"
            else:
                why = f"Selected: highest priority score ({r.score:.2f})"
            self._accept(now, r, why)
        for r in held:
            r.arbitration = (f"Held: lost to {winner.id} (score {r.score:.2f} vs {winner.score:.2f}, "
                             f"ETA {r.eta:.0f} s vs {winner.eta:.0f} s)")
        if held:
            self.emit("arbitration", now, tls=tls, ev=winner.ev_id, req=winner.id,
                      message=f"{winner.id} ({winner.ev_id}) selected: score {winner.score:.2f}, ETA {winner.eta:.0f} s. "
                              "Held: " + ", ".join(f"{r.id} ({r.ev_id}) score {r.score:.2f}, ETA {r.eta:.0f} s"
                                                   for r in held) + ".",
                      detail={"selected": winner.id, "scores": {r.id: r.score for r in pending}})
        if ctrl.mode == Mode.SERVING and ctrl.state == plan.state:
            for r in group:
                self._serve(now, r)

    def _accept(self, now: float, r: Request, why: str) -> None:
        r.status, r.accepted_at, r.arbitration = Status.ACCEPTED, now, why
        self.emit("request_accepted", now, tls=r.tls, ev=r.ev_id, req=r.id, message=f"{r.id} accepted. {why}.")

    def _serve(self, now: float, r: Request) -> None:
        r.status, r.served_at = Status.SERVING, now
        self.emit("request_serving", now, tls=r.tls, ev=r.ev_id, req=r.id,
                  message=f"{r.id}: green active for {r.ev_id} ({r.approach} {r.movement}).")

    def _mark_conflicts(self, now: float, tls: str, pending: list[Request], active: list[Request]) -> None:
        reqs = pending + active
        for r in reqs:
            r.conflicts_with = []
        for i, a in enumerate(reqs):
            for b in reqs[i + 1:]:
                if self._plan(tls, [a, b]) is not None:
                    continue
                a.conflicts_with.append(b.id)
                b.conflicts_with.append(a.id)
                pair = frozenset((a.id, b.id))
                if pair not in self._announced:
                    self._announced.add(pair)
                    self.conflicts_detected += 1
                    self.emit("conflict_detected", now, tls=tls, req=a.id,
                              message=f"Conflict: {a.id} ({a.ev_id}, {a.approach}) and {b.id} ({b.ev_id}, "
                                      f"{b.approach}) cannot share a signal phase.",
                              detail={"a": a.id, "b": b.id})
