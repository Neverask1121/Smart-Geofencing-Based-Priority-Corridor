"""Radius policies. The controller only sees a policy, so the same code runs with the
trained model, a fixed radius baseline, or no priority at all."""
from __future__ import annotations

import json
import time
from typing import Protocol

import numpy as np

from ..config import MODEL_CARD, MODEL_FILE, RADIUS_MAX, RADIUS_MIN
from .features import MODEL_COLUMNS, model_rows


class RadiusPolicy(Protocol):
    name: str

    def radius(self, features: dict[str, float]) -> float | None:
        """Radius in metres, or None to never request priority."""


class NoPriority:
    name = "no_priority"

    def radius(self, features: dict[str, float]) -> None:
        return None


class FixedRadius:
    def __init__(self, r: float) -> None:
        self.r = r
        self.name = f"fixed_{r:.0f}"

    def radius(self, features: dict[str, float]) -> float:
        return self.r


CANDIDATES = np.array([80, 130, 190, 260, 340, 420, 480], dtype=float)   # the radii swept in the dataset
DEFAULT_TEMPERATURE = 1.0


def radius_from_costs(costs: np.ndarray, temperature: float) -> float:
    """Cost-weighted radius: a soft minimum over the predicted cost curve. When the curve is
    flat the candidates share the weight, so a tiny cost difference cannot swing the radius."""
    w = np.exp(-(costs - costs.min()) / temperature)
    return float((CANDIDATES * w).sum() / w.sum())


class ModelNotTrained(RuntimeError):
    pass


class XGBoostRadius:
    """Inference with the trained model, which predicts the decision cost of each candidate
    radius. There is deliberately no fallback value: if the model is missing the app says so
    rather than showing invented radii."""
    name = "xgboost"

    def __init__(self, path=MODEL_FILE) -> None:
        if not path.exists():
            raise ModelNotTrained(f"{path} not found. Run scripts/train_model.py first.")
        import xgboost as xgb
        self.booster = xgb.Booster()
        self.booster.load_model(str(path))
        names = self.booster.feature_names
        if names is not None and list(names) != MODEL_COLUMNS:
            raise ModelNotTrained("Model features do not match backend/app/core/features.py. Retrain the model.")
        self.card = json.loads(MODEL_CARD.read_text()) if MODEL_CARD.exists() else {}
        self.temperature = float(self.card.get("temperature", DEFAULT_TEMPERATURE))
        self.last_latency_ms = 0.0
        self.count = 0

    def radius(self, features: dict[str, float]) -> float:
        t0 = time.perf_counter()
        rows = np.array(model_rows(features, CANDIDATES), dtype=np.float32)
        y = radius_from_costs(np.asarray(self.booster.inplace_predict(rows), dtype=float), self.temperature)
        self.last_latency_ms = (time.perf_counter() - t0) * 1000
        self.count += 1
        return float(np.clip(y, RADIUS_MIN, RADIUS_MAX))
