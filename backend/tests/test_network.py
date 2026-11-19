"""Checks against the real network and a real SUMO process."""
import json
import math

import pytest

from app.config import SCENARIOS_FILE
from app.core.policy import FixedRadius, ModelNotTrained, NoPriority, XGBoostRadius
from app.core.simcore import EvSpec, SimCore
from app.core.topology import bearing_label, get_network


@pytest.fixture(scope="module")
def net():
    return get_network()


@pytest.fixture(scope="module")
def scenarios():
    return {s["id"]: s for s in json.loads(SCENARIOS_FILE.read_text())["scenarios"]}


def test_network_is_left_hand_and_in_ahmedabad(net):
    assert "lefthand" in open(net_path(), encoding="utf8").read(4000)
    lon0, lat0, lon1, lat1 = net.bbox()
    assert 72.5 < lon0 < lon1 < 72.62 and 22.98 < lat0 < lat1 < 23.08


def net_path():
    from app.config import NET_FILE
    return NET_FILE


def test_bearing_labels():
    assert bearing_label(0) == "Northbound"
    assert bearing_label(90) == "Eastbound"
    assert bearing_label(359) == "Northbound"


def test_coordinates_match_sumo_own_conversion(net):
    core = SimCore(net, NoPriority(), scale=0.1)
    core.start()
    try:
        for e in list(net.net.getEdges())[::1500]:
            x, y = e.getShape()[0]
            lon, lat = core.conn.simulation.convertGeo(x, y)
            mine = net.lonlat(x, y)
            assert math.hypot(mine[0] - lon, mine[1] - lat) < 1e-6
    finally:
        core.close()


def test_every_link_appears_in_some_green_phase(net):
    for t in net.tls.values():
        for idx in t.links:
            assert any(s[idx] in "Gg" for s, _ in t.phases), (t.id, idx)


def test_every_scenario_route_is_connected(net, scenarios):
    for s in scenarios.values():
        for ev in s["evs"]:
            for a, b in zip(ev["edges"], ev["edges"][1:]):
                assert net.net.getEdge(b) in net.net.getEdge(a).getOutgoing(), (s["id"], a, b)


def test_perpendicular_scenario_really_conflicts_and_stays_safe(net, scenarios):
    core = SimCore(net, FixedRadius(250), scale=0.7, seed=5)
    core.start()
    try:
        while core.now < 60:
            core.step()
        evs = scenarios["perpendicular"]["evs"]
        core.schedule_scenario(evs, [f"EV{i}" for i in range(len(evs))], core.now)
        end = core.now + 400
        while core.now < end and (core.evs or core.scheduled):
            core.step()
        m = core.metrics.summary(core)
        assert m["conflicts_detected"] >= 1
        kinds = [e["kind"] for e in core.events]
        assert "arbitration" in kinds, "both vehicles must be scored, not first come first served"
        decided = next(e for e in core.events if e["kind"] == "arbitration")
        assert len(decided["detail"]["scores"]) == 2
        assert m["requests_successful"] >= 2
        assert m["requests_expired"] == 0
        assert m["safety_violations"] == 0
        assert len(core.finished_evs) == 2
    finally:
        core.close()


def test_single_ev_is_never_given_an_early_request(net, scenarios):
    core = SimCore(net, FixedRadius(200), scale=0.1, seed=7)
    core.start()
    try:
        e = scenarios["single"]["evs"][0]
        core.schedule(EvSpec("EV", e["type"], e["edges"], core.now))
        end = core.now + 300
        while core.now < end and (core.evs or core.scheduled):
            core.step()
        assert core.coord.requests and not any(r.early for r in core.coord.requests.values())
    finally:
        core.close()


def test_reroute_replaces_route_and_cancels_open_request(net, scenarios):
    core = SimCore(net, FixedRadius(480), scale=0.1, seed=8)
    core.start()
    try:
        e = scenarios["single"]["evs"][0]
        core.schedule(EvSpec("EV", e["type"], e["edges"], core.now))
        while not any(r.open for r in (core.coord.requests.values() if core.coord else [])):
            core.step()
            assert core.now < 300
        old = next(r for r in core.coord.requests.values() if r.open)
        ev = core.evs["EV"]
        while core.conn.vehicle.getRoadID("EV").startswith(":"):
            core.step()
        pool = json.loads(SCENARIOS_FILE.read_text())["pool"]
        dest = next(p["edges"][-1] for p in pool if p["edges"][-1] != e["edges"][-1]
                    and len(core.conn.simulation.findRoute(core.conn.vehicle.getRoadID("EV"), p["edges"][-1]).edges) > 3)
        assert core.reroute("EV", dest) == 2
        assert old.status.value == "cancelled"
        assert ev.edges[-1] == dest
        assert ev.route_coords and ev.route_cum[-1] > 0
        end = core.now + 400
        while core.now < end and core.evs:
            core.step()
        assert core.finished_evs and core.safety_violations == 0
    finally:
        core.close()


def test_geofence_activation_uses_radius(net, scenarios):
    core = SimCore(net, FixedRadius(120), scale=0.1, seed=6)
    core.start()
    try:
        e = scenarios["single"]["evs"][0]
        core.schedule(EvSpec("EV", e["type"], e["edges"], core.now))
        end = core.now + 300
        while core.now < end and (core.evs or core.scheduled):
            core.step()
        reqs = list(core.coord.requests.values())
        assert reqs and all(r.radius == 120 for r in reqs)
        assert all(r.dist <= 121 or r.accepted_at is not None for r in reqs)
    finally:
        core.close()


def test_missing_model_is_an_error_not_a_default(tmp_path):
    with pytest.raises(ModelNotTrained):
        XGBoostRadius(tmp_path / "nope.json")
