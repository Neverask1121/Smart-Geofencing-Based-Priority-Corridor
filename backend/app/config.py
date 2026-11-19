"""Paths and tunable constants shared by the live app, dataset generation and evaluation."""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
NET_DIR = DATA / "net"
NET_FILE = NET_DIR / "ahmedabad.net.xml"
SUMO_CFG = NET_DIR / "sim.sumocfg"
TLS_SOURCES = NET_DIR / "tls_sources.json"
SCENARIOS_FILE = NET_DIR / "scenarios.json"
MODEL_DIR = DATA / "model"
MODEL_FILE = MODEL_DIR / "radius_xgb.json"
MODEL_CARD = MODEL_DIR / "model_card.json"


def sumo_binary() -> str:
    import sumo
    return os.path.join(sumo.SUMO_HOME, "bin", "sumo")


STEP_LENGTH = 0.5            # s, must match sim.sumocfg
PREDICT_EVERY = 2.0          # s of simulation between radius predictions

# Radius limits (m). The model's output is clipped to the range it was trained on.
RADIUS_MIN = 80.0
RADIUS_MAX = 480.0

# Signal safety timings (s).
MIN_GREEN = 6.0              # a green is never cut shorter than this
YELLOW_TIME = 3.0
ALL_RED_TIME = 2.0

# Coordination.
REQUEST_TTL = 120.0          # an unserved request expires after this
CONTENDER_LOOKAHEAD = 15.0   # s: a conflicting EV this much further away is arbitrated with the first
MAX_HOLD = 60.0              # a served request is released after this, so a stuck EV cannot starve the junction
EV_TYPE_WEIGHT = {"ambulance": 1.0, "fire_engine": 0.85, "police": 0.7}
SCORE_W_TYPE, SCORE_W_ETA, SCORE_W_WAIT = 0.5, 0.35, 0.15

TRAFFIC_LEVELS = {"low": 0.4, "medium": 0.7, "high": 1.0}
