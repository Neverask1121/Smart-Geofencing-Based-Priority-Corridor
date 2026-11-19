"""API and WebSocket contract, against a real engine and SUMO process."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core.signals import greens
from app.hub import QUEUE_FRAMES, Hub
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def wait_for(client, status, seconds=90):
    end = time.time() + seconds
    while time.time() < end:
        if client.get("/api/v1/simulation/status").json()["status"] == status:
            return
        time.sleep(0.2)
    raise AssertionError(f"never reached {status}")


def test_health(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["network_loaded"]


def test_static_network_endpoints(client):
    roads = client.get("/api/v1/network/roads").json()
    assert roads["type"] == "FeatureCollection" and len(roads["features"]) > 5000
    assert roads["features"][0]["geometry"]["coordinates"][0][0] == pytest.approx(72.56, abs=0.1)
    sig = client.get("/api/v1/network/signals").json()
    assert len(sig["signals"]) >= 20
    assert {s["source"] for s in sig["signals"]} == {"osm", "inferred"}


def test_scenarios_list_covers_the_required_set(client):
    ids = {s["id"] for s in client.get("/api/v1/scenarios").json()}
    assert {"single", "opposite", "perpendicular", "connected", "five", "low", "medium", "high", "conflict"} <= ids


def test_bad_commands_are_rejected(client):
    assert client.post("/api/v1/simulation/speed", json={"speed": 1000}).status_code == 422
    assert client.post("/api/v1/scenarios/select", json={"scenario": "x", "policy": "evil"}).status_code == 422
    assert client.post("/api/v1/scenarios/select", json={"scenario": "nope", "policy": "none"}).status_code == 409
    assert client.post("/api/v1/simulation/pause").status_code == 409


def test_no_endpoint_can_set_a_signal(client):
    paths = [r.path for r in app.routes]
    assert not any("signal" in p and "network" not in p for p in paths)


def test_websocket_rejects_unknown_messages(client):
    with client.websocket_connect("/ws/simulation") as ws:
        ws.send_text(json.dumps({"type": "set_signal", "state": "GGGG"}))
        for _ in range(50):
            m = json.loads(ws.receive_text())
            if m["type"] == "error":
                return
        raise AssertionError("no error reply")


def test_run_stream_control_and_reset(client):
    r = client.post("/api/v1/scenarios/select",
                    json={"scenario": "five", "policy": "fixed_300", "traffic": "low", "seed": 1})
    assert r.status_code == 200, r.text
    wait_for(client, "running")
    client.post("/api/v1/simulation/speed", json={"speed": 16})

    with client.websocket_connect("/ws/simulation") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "snapshot" and first["sim"]["status"] == "running"
        assert len(first["veh"]["pos"]) % 5 == 0 and first["veh"]["pos"]
        state = {k: None for k, _ in first["veh"]["add"]}
        seq = first["seq"]
        evs_seen = set()
        frames = 0
        while frames < 150 and len(evs_seen) < 5:
            m = json.loads(ws.receive_text())
            if m["type"] != "frame":
                continue
            frames += 1
            assert m["seq"] == seq + 1, "gap in the incremental stream"
            seq = m["seq"]
            for k, _ in m["veh"]["add"]:
                state[k] = None
            for k in m["veh"]["del"]:
                state.pop(k, None)
            pos = m["veh"]["pos"]
            assert all(int(pos[i]) in state for i in range(0, len(pos), 5)), "position for unknown vehicle"
            evs_seen |= {e["id"] for e in m["evs"]}
        assert len(evs_seen) == 5

    time.sleep(1.2)
    evs = client.get("/api/v1/emergency-vehicles").json()
    assert evs and all(72.5 < e["lon"] < 72.62 for e in evs if e["lon"])
    assert len(client.get("/api/v1/vehicles").json()) > 20
    assert len(client.get("/api/v1/intersections").json()) >= 20

    assert client.post("/api/v1/simulation/pause").status_code == 200
    t0 = client.get("/api/v1/simulation/status").json()["t"]
    time.sleep(0.6)
    assert client.get("/api/v1/simulation/status").json()["t"] == t0
    assert client.post("/api/v1/simulation/resume").status_code == 200
    assert client.post("/api/v1/emergency-vehicles/dispatch", json={"type": "police"}).status_code == 200
    assert client.post("/api/v1/simulation/demand", json={"scale": 0.5}).status_code == 200
    assert client.post("/api/v1/simulation/reset").status_code == 200
    assert client.get("/api/v1/simulation/status").json()["status"] == "idle"


def test_commands_work_during_warm_up(client):
    assert client.post("/api/v1/scenarios/select",
                       json={"scenario": "single", "policy": "none", "traffic": "low"}).status_code == 200
    assert client.get("/api/v1/simulation/status").json()["status"] == "warming"
    assert client.post("/api/v1/simulation/speed", json={"speed": 4}).status_code == 200
    # Changing scenario part way through a warm-up restarts cleanly.
    assert client.post("/api/v1/scenarios/select",
                       json={"scenario": "single", "policy": "fixed_150", "traffic": "low"}).status_code == 200
    wait_for(client, "running")
    assert client.get("/api/v1/simulation/status").json()["policy"] == "fixed_150"
    assert client.post("/api/v1/simulation/reset").status_code == 200


def test_slow_client_gets_a_resync_and_never_blocks():
    import asyncio

    async def run():
        hub = Hub()
        hub.bind(asyncio.get_running_loop())
        slow = hub.add()
        hub._fan_out(b"f", b"full")
        assert slow.queue.get_nowait() == b"full" and not slow.need_full
        for _ in range(QUEUE_FRAMES + 3):           # never drained
            hub._fan_out(b"frame", None)
        assert slow.need_full and slow.dropped >= 1
        hub._fan_out(b"frame", b"full2")
        assert slow.queue.get_nowait() == b"full2"

    asyncio.run(run())


def test_green_helper():
    assert greens("GrgyR") == {0, 2}
