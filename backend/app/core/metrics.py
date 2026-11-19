"""Run metrics, all measured from the simulation. Nothing here is estimated or seeded."""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .simcore import SimCore

HISTORY_EVERY = 5.0      # s of simulation between history samples
HISTORY_LEN = 360


class Metrics:
    def __init__(self) -> None:
        self.ev_trips: list[dict] = []
        self.civ_arrivals = 0
        self.civ_delay_sum = 0.0
        self.arrival_times: deque[float] = deque()
        self.collisions = 0
        self.teleports = 0
        self.radius_sum = 0.0
        self.radius_n = 0
        self.queue_sum = 0.0
        self.queue_n = 0
        self.current_queue = 0.0
        self.next_sample = 0.0
        self.history: deque[dict] = deque(maxlen=HISTORY_LEN)
        self.latest: dict = {}

    def civilian_arrived(self, now: float, time_loss: float) -> None:
        self.civ_arrivals += 1
        self.civ_delay_sum += time_loss
        self.arrival_times.append(now)

    def ev_arrived(self, trip: dict) -> None:
        self.ev_trips.append(trip)

    def tick(self, core: "SimCore") -> None:
        now = core.now
        while self.arrival_times and self.arrival_times[0] < now - 60.0:
            self.arrival_times.popleft()
        if now < self.next_sample:
            return
        self.next_sample = now + HISTORY_EVERY
        halted = [sum(core.edge_stats[a][1] for a in info.approaches if a in core.edge_stats)
                  for info in core.net.tls.values()]
        self.current_queue = sum(halted) / len(halted) if halted else 0.0
        self.queue_sum += self.current_queue
        self.queue_n += 1
        self.latest = self.summary(core)
        self.history.append({k: self.latest[k] for k in
                             ("t", "avg_queue", "avg_civilian_delay", "throughput_per_min", "vehicles",
                              "active_evs", "avg_radius_now")})

    def summary(self, core: "SimCore") -> dict:
        coord = core.coord
        reqs = list(coord.requests.values()) if coord else []
        by = lambda s: sum(r.status.value == s for r in reqs)   # noqa: E731
        trips = self.ev_trips
        radii = [e.radius for e in core.evs.values() if e.radius is not None]
        return {
            "t": round(core.now, 1),
            "vehicles": len(core.veh) + len(core.evs),
            "active_evs": len(core.evs),
            "evs_completed": len(trips),
            "avg_ev_travel_time": round(sum(t["travel_time"] for t in trips) / len(trips), 1) if trips else None,
            "avg_ev_time_loss": round(sum(t["time_loss"] for t in trips) / len(trips), 1) if trips else None,
            "avg_civilian_delay": round(self.civ_delay_sum / self.civ_arrivals, 1) if self.civ_arrivals else None,
            "civilian_trips": self.civ_arrivals,
            "avg_queue": round(self.current_queue, 1),
            "run_avg_queue": round(self.queue_sum / self.queue_n, 1) if self.queue_n else None,
            "throughput_per_min": len(self.arrival_times),
            "requests_total": len(reqs),
            "requests_successful": by("completed"),
            "requests_open": by("pending") + by("accepted") + by("serving"),
            "requests_expired": by("expired"),
            "requests_cancelled": by("cancelled"),
            "conflicts_detected": coord.conflicts_detected if coord else 0,
            "avg_radius_now": round(sum(radii) / len(radii), 1) if radii else None,
            "avg_radius_run": round(self.radius_sum / self.radius_n, 1) if self.radius_n else None,
            "predictions": self.radius_n,
            "safety_violations": core.safety_violations,
            "collisions": self.collisions,
            "teleports": self.teleports,
        }
