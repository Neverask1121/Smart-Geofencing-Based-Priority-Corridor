"""API schemas. frontend/src/types/simulation.ts mirrors these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvType = Literal["ambulance", "fire_engine", "police"]
SimStatusName = Literal["idle", "warming", "running", "paused", "finished", "error"]
RequestStatus = Literal["pending", "accepted", "serving", "completed", "cancelled", "expired"]
TrafficLevel = Literal["low", "medium", "high"]


class Health(BaseModel):
    status: Literal["ok"]
    model_loaded: bool
    model_error: str | None
    network_loaded: bool
    sim_status: SimStatusName


class SimStatus(BaseModel):
    run_id: int
    status: SimStatusName
    t: float
    speed: float
    achieved_speed: float
    scenario: str | None
    scenario_name: str | None
    traffic: str | None
    scale: float | None
    policy: str | None
    message: str | None
    warmup_progress: float
    clients: int


class Vehicle(BaseModel):
    id: int
    type: Literal["car", "motorcycle", "bus", "truck"]
    lon: float
    lat: float
    angle: float
    speed: float


class EmergencyVehicle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    type: EvType
    lon: float
    lat: float
    angle: float
    speed: float
    status: str
    next_tls: str | None
    next_tls_name: str | None
    dist_to_tls: float | None
    route_dist_to_tls: float | None
    eta: float | None
    radius: float | None
    in_geofence: bool
    request_id: str | None
    request_status: RequestStatus | None
    route_progress_m: float
    route_total_m: float
    upcoming_tls: list[str]
    time_loss: float
    travel_time: float


class PriorityRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    ev_id: str
    ev_type: EvType
    tls: str
    tls_name: str
    approach: str
    movement: str
    radius: float
    eta: float
    dist: float
    status: RequestStatus
    score: float
    score_parts: dict[str, float]
    conflicts_with: list[str]
    arbitration: str
    created_at: float
    accepted_at: float | None
    served_at: float | None
    closed_at: float | None
    early: bool


class Intersection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    state: str
    mode: str
    target_state: str | None
    queue: int
    vehicles: int
    density: float
    avg_speed: float | None
    active_requests: list[str]
    pending_requests: list[str]
    approaching_evs: list[str]
    safety_violations: int


class ScenarioInfo(BaseModel):
    id: str
    name: str
    description: str
    traffic: TrafficLevel
    ev_count: int
    focus: str | None = None


class ScenarioSelect(BaseModel):
    scenario: str
    traffic: TrafficLevel | None = None
    policy: str = Field(default="xgboost", pattern=r"^(xgboost|none|fixed_\d{2,3})$")
    seed: int = Field(default=42, ge=0, le=1_000_000)
    autostart: bool = True


class SpeedCommand(BaseModel):
    speed: float = Field(ge=0.5, le=20)


class DemandCommand(BaseModel):
    scale: float = Field(ge=0.1, le=1.2)


class DispatchCommand(BaseModel):
    type: EvType = "ambulance"


class Ack(BaseModel):
    ok: bool
    detail: str = ""


class ClientMessage(BaseModel):
    """The only messages a browser may send. Signals cannot be controlled from here."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["ping", "resync"]
    nonce: int | None = None
