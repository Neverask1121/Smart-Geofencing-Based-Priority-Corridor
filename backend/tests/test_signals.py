import random

from app.config import ALL_RED_TIME, MIN_GREEN, YELLOW_TIME
from app.core.signals import Mode, SafetyMonitor, ServePlan, SignalController, build_plan, greens
from conftest import FakeIO

STEP = 0.5


def drive(ctrl, io, monitor, t0, t1):
    t = t0
    while t < t1:
        t += STEP
        s = io.state(t)
        ctrl.observe(t, s)
        monitor.observe(t, s)
        ctrl.tick(t)
    return t


def test_plan_uses_program_phase_for_through_movement(tls):
    plan = build_plan(tls, [(2,)], lambda lk: set())
    assert plan.state == "rrGGr"


def test_permissive_movement_is_protected_by_holding_its_foes(tls):
    plan = build_plan(tls, [(4,)], lambda lk: {1} if lk == 4 else set())
    assert plan.state[4] == "G"
    assert plan.state[1] == "r"


def test_groups_needing_a_foe_are_incompatible(tls):
    assert build_plan(tls, [(4,), (1,)], lambda lk: {1} if lk == 4 else set()) is None


def test_perpendicular_movements_have_no_shared_phase(tls):
    assert build_plan(tls, [(0,), (2,)], lambda lk: set()) is None


def test_opposite_movements_share_a_phase(tls):
    assert build_plan(tls, [(0,), (1,)], lambda lk: set()) is not None


def test_preemption_runs_yellow_then_all_red_then_green(tls):
    io = FakeIO(tls)
    ctrl, mon = SignalController(tls, io), SafetyMonitor(tls)
    t = drive(ctrl, io, mon, 0, 10)
    ctrl.request(ServePlan("rrGGr", 3))
    drive(ctrl, io, mon, t, t + 10)
    states = [s for kind, s in io.log if kind == "set"]
    assert states == ["yyrry", "rrrrr", "rrGGr"]
    assert ctrl.mode == Mode.SERVING
    assert mon.violations == []


def test_minimum_green_is_never_cut(tls):
    io = FakeIO(tls)
    ctrl, mon = SignalController(tls, io), SafetyMonitor(tls)
    t = drive(ctrl, io, mon, 0, 1)              # green has only just begun
    ctrl.request(ServePlan("rrGGr", 3))
    t = drive(ctrl, io, mon, t, MIN_GREEN - 2)
    assert io.log == []                          # still holding
    drive(ctrl, io, mon, t, MIN_GREEN + 1)
    assert io.log[0] == ("set", "yyrry")


def test_release_returns_to_program_through_clearance(tls):
    io = FakeIO(tls)
    ctrl, mon = SignalController(tls, io), SafetyMonitor(tls)
    t = drive(ctrl, io, mon, 0, 10)
    ctrl.request(ServePlan("rrGGr", 3))
    t = drive(ctrl, io, mon, t, t + 10)
    ctrl.release()
    t = drive(ctrl, io, mon, t, t + MIN_GREEN + YELLOW_TIME + ALL_RED_TIME + 3)
    assert ctrl.mode == Mode.NORMAL
    assert io.override is None
    assert io.log[-1][0] == "resume"
    drive(ctrl, io, mon, t, t + 200)             # the program keeps cycling safely afterwards
    assert mon.violations == []


def test_release_before_takeover_leaves_program_untouched(tls):
    io = FakeIO(tls)
    ctrl = SignalController(tls, io)
    ctrl.observe(1.0, io.state(1.0))
    ctrl.request(ServePlan("rrGGr", 3))
    ctrl.tick(1.0)
    ctrl.release()
    assert ctrl.mode == Mode.NORMAL and io.log == []


def test_target_change_during_clearance_still_yellows_dropped_links(tls):
    """Regression: an EV clears mid-transition, so release() changes the target while links
    the old target kept are still green. They must not go straight to red."""
    io = FakeIO(tls)
    ctrl, mon = SignalController(tls, io), SafetyMonitor(tls)
    t = drive(ctrl, io, mon, 0, 10)
    ctrl.request(ServePlan("GrrrG", 0))        # keeps links 0 and 4, drops link 1
    t = drive(ctrl, io, mon, t, t + 1)
    assert ctrl.mode == Mode.YELLOW
    ctrl.resume_phase = 3                      # the program resumes on the other green
    ctrl.release()
    drive(ctrl, io, mon, t, t + 30)
    assert mon.violations == []
    assert ctrl.mode == Mode.NORMAL


def test_monitor_catches_green_to_red(tls):
    mon = SafetyMonitor(tls)
    mon.observe(0, "GGrrg")
    mon.observe(0.5, "rrrrr")
    assert any("without yellow" in v for v in mon.violations)


def test_monitor_catches_conflicting_greens(tls):
    mon = SafetyMonitor(tls)
    mon.observe(0, "GrGrr")
    assert any("no program phase" in v for v in mon.violations)


def test_monitor_catches_short_yellow(tls):
    mon = SafetyMonitor(tls)
    for t, s in [(0, "GGrrg"), (0.5, "yyrry"), (1.0, "rrrrr")]:
        mon.observe(t, s)
    assert any("yellow held" in v for v in mon.violations)


def test_random_request_storm_stays_safe(tls):
    """Thousands of arbitrary requests and releases at arbitrary times: no safety violation."""
    plans = [ServePlan("GGrrr", 0), ServePlan("rrGGr", 3), ServePlan("GrrrG", 0)]
    for seed in range(30):
        rng = random.Random(seed)
        io = FakeIO(tls)
        ctrl, mon = SignalController(tls, io), SafetyMonitor(tls)
        t = 0.0
        for _ in range(1500):
            t += STEP
            s = io.state(t)
            ctrl.observe(t, s)
            mon.observe(t, s)
            ctrl.tick(t)
            roll = rng.random()
            if roll < 0.03:
                ctrl.request(rng.choice(plans))
            elif roll < 0.05 and ctrl.active and not ctrl.restoring:
                ctrl.release()
        assert mon.violations == [], (seed, mon.violations[:3])
        assert greens("GGrrr") <= greens("GGrrg")
