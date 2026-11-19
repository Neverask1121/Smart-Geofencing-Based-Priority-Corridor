from app.config import MAX_HOLD, REQUEST_TTL
from app.core.coordination import Coordinator, Status, score_request
from app.core.signals import Mode, SafetyMonitor, SignalController
from app.core.topology import Crossing
from conftest import FakeIO

STEP = 0.5
NS = Crossing(0, "J", "n", "s", (0,), 100.0)
SN = Crossing(0, "J", "s_in", "n_out", (1,), 100.0)
EW = Crossing(0, "J", "e", "w", (2,), 100.0)


class World:
    def __init__(self, tls):
        self.io = FakeIO(tls)
        self.events = []
        self.ctrl = SignalController(tls, self.io)
        self.mon = SafetyMonitor(tls)
        self.coord = Coordinator({"J": tls}, {"J": self.ctrl}, lambda t, lk: set(),
                                 lambda kind, now, **k: self.events.append((kind, k)))
        self.t = 0.0

    def run(self, seconds):
        end = self.t + seconds
        while self.t < end:
            self.t += STEP
            s = self.io.state(self.t)
            self.ctrl.observe(self.t, s)
            self.mon.observe(self.t, s)
            self.coord.tick(self.t)
            self.ctrl.tick(self.t)

    def kinds(self):
        return [k for k, _ in self.events]


def test_single_request_lifecycle(tls):
    w = World(tls)
    w.run(10)
    r = w.coord.open_request(w.t, "A", "ambulance", EW, 200, 20, 150)
    w.run(0.5)
    assert r.status == Status.ACCEPTED
    w.run(10)
    assert r.status == Status.SERVING
    w.coord.close(w.t, r, Status.COMPLETED, "cleared")
    w.run(20)
    assert w.ctrl.mode == Mode.NORMAL
    assert w.mon.violations == []


def test_conflict_is_arbitrated_and_loser_served_after(tls):
    w = World(tls)
    w.run(10)
    a = w.coord.open_request(w.t, "AMB", "ambulance", NS, 200, 15, 150)
    b = w.coord.open_request(w.t, "POL", "police", EW, 200, 15, 150)
    w.run(1)
    assert a.status in (Status.ACCEPTED, Status.SERVING) and b.status == Status.PENDING
    assert b.id in a.conflicts_with
    assert "conflict_detected" in w.kinds() and "arbitration" in w.kinds()
    assert "Held" in b.arbitration
    w.run(5)
    assert a.status == Status.SERVING
    w.coord.close(w.t, a, Status.COMPLETED, "cleared")
    w.run(15)
    assert b.status == Status.SERVING
    assert w.mon.violations == []


def test_closer_vehicle_can_beat_higher_class(tls):
    w = World(tls)
    w.run(10)
    far = w.coord.open_request(w.t, "AMB", "ambulance", NS, 400, 60, 400)
    near = w.coord.open_request(w.t, "FIRE", "fire_engine", EW, 200, 3, 30)
    w.run(1)
    assert near.status == Status.ACCEPTED and far.status == Status.PENDING


def test_compatible_requests_are_served_together(tls):
    w = World(tls)
    w.run(10)
    a = w.coord.open_request(w.t, "A", "ambulance", NS, 200, 15, 150)
    b = w.coord.open_request(w.t, "B", "fire_engine", SN, 200, 15, 150)
    w.run(2)
    assert a.status == b.status == Status.SERVING
    assert a.conflicts_with == [] and "conflict_detected" not in w.kinds()


def test_late_request_never_preempts_the_one_being_served(tls):
    w = World(tls)
    w.run(10)
    a = w.coord.open_request(w.t, "POL", "police", EW, 200, 15, 150)
    w.run(10)
    assert a.status == Status.SERVING
    b = w.coord.open_request(w.t, "AMB", "ambulance", NS, 200, 1, 10)
    w.run(5)
    assert a.status == Status.SERVING and b.status == Status.PENDING


def test_waiting_raises_score():
    from app.core.coordination import Request
    r = Request("x", "e", "police", "J", EW, "a", "through", 100, 0.0, 20, 100)
    assert score_request(r, 30.0)[0] > score_request(r, 0.0)[0]


def test_hold_limit_releases_a_stuck_ev(tls):
    w = World(tls)
    w.run(10)
    r = w.coord.open_request(w.t, "A", "ambulance", EW, 200, 20, 150)
    w.run(MAX_HOLD + 25)
    assert r.status == Status.EXPIRED
    assert w.ctrl.mode == Mode.NORMAL
    assert w.mon.violations == []


def test_unserved_request_expires(tls):
    w = World(tls)
    w.run(10)
    a = w.coord.open_request(w.t, "A", "ambulance", NS, 200, 5, 100)
    b = w.coord.open_request(w.t, "B", "police", EW, 200, 50, 100)
    # A never clears, so B waits. A's hold expires first, then B is served; B must not stay pending forever.
    w.run(REQUEST_TTL + 5)
    assert a.status == Status.EXPIRED
    assert b.status != Status.PENDING
