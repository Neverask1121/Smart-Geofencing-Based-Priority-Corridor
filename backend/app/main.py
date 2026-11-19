"""FastAPI application: REST control and query API plus the /ws/simulation stream."""
from __future__ import annotations

import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager

import orjson
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import schemas as S
from .config import ROOT
from .core.topology import get_network
from .engine import CommandError, SimulationEngine
from .hub import Hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
hub = Hub()
engine: SimulationEngine
network_cache: dict[str, bytes] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    hub.bind(asyncio.get_running_loop())
    net = await asyncio.to_thread(get_network)
    engine = SimulationEngine(net, hub)
    network_cache["roads"] = orjson.dumps(net.roads_geojson())
    network_cache["signals"] = orjson.dumps(signals_payload(net))
    engine.start_thread()
    yield
    await asyncio.to_thread(engine.stop_thread)


app = FastAPI(title="Adaptive EV Priority ITS", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def signals_payload(net) -> dict:
    out = []
    for t in net.tls.values():
        out.append({
            "id": t.id, "name": t.name, "source": t.source, "lon": t.lon, "lat": t.lat,
            "phases": [{"state": s, "duration": d} for s, d in t.phases],
            "approaches": [{"edge": a.edge, "name": a.name, "label": a.label, "bearing": round(a.bearing, 1),
                            "lanes": a.lanes, "lon": a.lon, "lat": a.lat, "links": a.links}
                           for a in t.approaches.values()],
            "links": [{"index": k.index, "in_edge": k.in_edge, "out_edge": k.out_edge, "turn": k.turn}
                      for k in sorted(t.links.values(), key=lambda v: v.index)],
        })
    return {"signals": out, "bbox": net.bbox()}


async def run_command(name: str, arg=None, timeout: float = 30.0) -> S.Ack:
    try:
        return S.Ack(ok=True, detail=await asyncio.to_thread(engine.submit, name, arg, timeout))
    except CommandError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.get("/health", response_model=S.Health)
def health() -> S.Health:
    return S.Health(status="ok", model_loaded=engine.model is not None, model_error=engine.model_error,
                    network_loaded=True, sim_status=engine.status)


@app.get("/api/v1/simulation/status", response_model=S.SimStatus)
def sim_status() -> dict:
    return engine.status_dict()


@app.post("/api/v1/simulation/start", response_model=S.Ack)
async def sim_start() -> S.Ack:
    return await run_command("start")


@app.post("/api/v1/simulation/pause", response_model=S.Ack)
async def sim_pause() -> S.Ack:
    return await run_command("pause")


@app.post("/api/v1/simulation/resume", response_model=S.Ack)
async def sim_resume() -> S.Ack:
    return await run_command("resume")


@app.post("/api/v1/simulation/reset", response_model=S.Ack)
async def sim_reset() -> S.Ack:
    return await run_command("reset")


@app.post("/api/v1/simulation/speed", response_model=S.Ack)
async def sim_speed(cmd: S.SpeedCommand) -> S.Ack:
    return await run_command("speed", cmd.speed)


@app.post("/api/v1/simulation/demand", response_model=S.Ack)
async def sim_demand(cmd: S.DemandCommand) -> S.Ack:
    return await run_command("demand", cmd.scale)


@app.get("/api/v1/vehicles", response_model=list[S.Vehicle])
def vehicles() -> list[dict]:
    return engine.vehicles()


@app.get("/api/v1/emergency-vehicles", response_model=list[S.EmergencyVehicle])
def emergency_vehicles() -> list[dict]:
    return engine.view["evs"]


@app.post("/api/v1/emergency-vehicles/dispatch", response_model=S.Ack)
async def dispatch(cmd: S.DispatchCommand) -> S.Ack:
    return await run_command("dispatch", cmd.type)


@app.post("/api/v1/emergency-vehicles/{ev_id}/reroute", response_model=S.Ack)
async def reroute(ev_id: str) -> S.Ack:
    return await run_command("reroute", ev_id)


@app.get("/api/v1/intersections", response_model=list[S.Intersection])
def intersections() -> list[dict]:
    return engine.view["intersections"]


@app.get("/api/v1/intersections/{tls_id}", response_model=S.Intersection)
def intersection(tls_id: str) -> dict:
    for i in engine.view["intersections"]:
        if i["id"] == tls_id:
            return i
    raise HTTPException(status_code=404, detail="Unknown intersection, or no simulation running")


@app.get("/api/v1/priority-requests", response_model=list[S.PriorityRequest])
def priority_requests() -> list[dict]:
    return engine.view["requests"]


@app.get("/api/v1/metrics")
def metrics() -> dict:
    return {"current": engine.view["metrics"], "history": engine.view["history"]}


@app.get("/api/v1/events")
def events() -> list[dict]:
    return engine.view["events"]


@app.get("/api/v1/scenarios", response_model=list[S.ScenarioInfo])
def scenarios() -> list[dict]:
    return [{**s, "ev_count": len(s["evs"])} for s in engine.scenarios.values()]


@app.post("/api/v1/scenarios/select", response_model=S.Ack)
async def scenario_select(cmd: S.ScenarioSelect) -> S.Ack:
    return await run_command("select", cmd.model_dump())


@app.get("/api/v1/model")
def model_info() -> dict:
    if engine.model is None:
        return {"loaded": False, "error": engine.model_error}
    return {"loaded": True, "predictions": engine.model.count, "last_latency_ms": round(engine.model.last_latency_ms, 3),
            **engine.model.card}


@app.get("/api/v1/network/roads")
def network_roads() -> Response:
    return Response(network_cache["roads"], media_type="application/json")


@app.get("/api/v1/network/signals")
def network_signals() -> Response:
    return Response(network_cache["signals"], media_type="application/json")


@app.websocket("/ws/simulation")
async def ws_simulation(ws: WebSocket) -> None:
    await ws.accept()
    client = hub.add()

    async def reader() -> None:
        while True:
            raw = await ws.receive_text()
            try:
                msg = S.ClientMessage.model_validate_json(raw)
            except ValidationError:
                await ws.send_text('{"type":"error","message":"Invalid client message"}')
                continue
            if msg.type == "resync":
                client.need_full = True
            else:
                await ws.send_text(orjson.dumps({"type": "pong", "nonce": msg.nonce}).decode())

    async def writer() -> None:
        while True:
            await ws.send_text((await client.queue.get()).decode())

    tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            t.result()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        hub.remove(client)


# Production build of the React app, so one process serves everything.
DIST = pathlib.Path(ROOT) / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
