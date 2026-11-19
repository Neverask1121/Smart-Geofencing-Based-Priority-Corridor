"""Train the XGBoost radius model from the counterfactual sweeps.

Decision cost of a radius at a crossing:
    J(r) = EV_time(r) + LAMBDA * civilian_halted_vehicle_seconds(r)
LAMBDA is a policy choice: at 0.02, one EV-second is worth 50 civilian halted seconds.

Why the model learns the cost curve rather than the best radius directly: on many crossings
J is nearly flat, so the "best" radius is mostly noise, and a regressor on that label cannot
beat a constant. Learning J(state, radius) uses all seven outcomes of each sweep. The live
radius is the soft minimum of the predicted curve (backend/app/core/policy.py).

Whole episodes are held out, so no traffic state is on both sides of the split. Hyperparameters
and temperature are chosen by cross-validation on training episodes only; the test episodes are
scored once. Scoring is regret: the cost the model's radius really produced on held-out crossings.
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupKFold

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import MODEL_CARD, MODEL_DIR, MODEL_FILE, RADIUS_MAX, RADIUS_MIN  # noqa: E402
from app.core.features import MODEL_COLUMNS, model_rows  # noqa: E402
from app.core.policy import CANDIDATES, radius_from_costs  # noqa: E402

RAW = ROOT / "data" / "dataset" / "raw.jsonl"
LAMBDA = 0.02
NOT_CROSSED_PENALTY_S = 260.0
TEST_EVERY = 5          # every 5th episode is held out
GRID = [dict(max_depth=d, learning_rate=lr, n_estimators=n, min_child_weight=w)
        for d, lr, n, w in [(3, 0.05, 200, 20), (4, 0.03, 150, 50), (4, 0.05, 300, 20),
                            (5, 0.03, 200, 50), (6, 0.03, 300, 50), (6, 0.02, 200, 100)]]
TEMPERATURES = [0.5, 1.0, 2.0, 4.0]


def load() -> list[dict]:
    rows = [json.loads(line) for line in RAW.open()]
    dirty = {r["ep"] for r in rows if r["violations"]}     # episodes run before the clearance fix
    kept = [r for r in rows if r["ep"] not in dirty and r["snapshots"]]
    print(f"{len(rows)} crossings; dropped {len(rows) - len(kept)} "
          f"({len(dirty)} episodes hit the pre-fix controller bug, the rest had no snapshot)")
    for r in kept:
        o = r["outcomes"]

        def t(k: str) -> float:
            return (o[k]["t_cross"] or r["depart"] + NOT_CROSSED_PENALTY_S) - r["depart"]

        r["T"] = np.array([t(str(int(x))) for x in CANDIDATES])
        r["C"] = np.array([o[str(int(x))]["civ_halt"] for x in CANDIDATES])
        r["T0"], r["C0"] = t("None"), o["None"]["civ_halt"]
        r["J"] = r["T"] + LAMBDA * r["C"]
        # Light smoothing over neighbouring radii, so one lucky signal phase does not dominate.
        p = np.pad(r["J"], 1, mode="edge")
        r["Js"] = 0.25 * p[:-2] + 0.5 * p[1:-1] + 0.25 * p[2:]
        r["label"] = float(CANDIDATES[int(np.argmin(r["Js"]))])
    return kept


def design(rows: list[dict]) -> tuple[pd.DataFrame, np.ndarray]:
    X: list[list[float]] = []
    y: list[float] = []
    for r in rows:
        centred = r["Js"] - r["Js"].mean()
        for s in r["snapshots"]:
            X.extend(model_rows(s, CANDIDATES))
            y.extend(centred)
    return pd.DataFrame(X, columns=MODEL_COLUMNS), np.array(y)


def fit(params: dict, rows: list[dict]) -> xgb.XGBRegressor:
    X, y = design(rows)
    m = xgb.XGBRegressor(objective="reg:squarederror", subsample=0.8, colsample_bytree=0.8, reg_lambda=3.0,
                         tree_method="hist", random_state=42, n_jobs=6, **params)
    m.fit(X, y)
    return m


def fired_radius(model: xgb.XGBRegressor, r: dict, temperature: float) -> float:
    """Replay live behaviour: the prediction updates as the EV approaches, and the first one
    containing the EV's current distance is the radius that actually fires."""
    p = 0.0
    for s in sorted(r["snapshots"], key=lambda s: -s["geo_dist"]):
        X = pd.DataFrame(model_rows(s, CANDIDATES), columns=MODEL_COLUMNS)
        p = float(np.clip(radius_from_costs(model.predict(X).astype(float), temperature), RADIUS_MIN, RADIUS_MAX))
        if s["geo_dist"] <= p:
            break
    return p


def cost_at(r: dict, radius: float, field: str = "J") -> float:
    return float(np.interp(radius, CANDIDATES, r[field]))


def main() -> None:
    rows = load()
    test = [r for r in rows if r["ep"] % TEST_EVERY == 0]
    train = [r for r in rows if r["ep"] % TEST_EVERY != 0]
    print(f"train {len(train)} crossings, test {len(test)} crossings")

    groups = np.array([r["ep"] for r in train])
    folds = list(GroupKFold(5).split(groups, groups, groups))
    results = []
    for params in GRID:
        by_temp = {t: [] for t in TEMPERATURES}
        for a, b in folds:
            m = fit(params, [train[i] for i in a])
            for t in TEMPERATURES:
                by_temp[t] += [cost_at(train[i], fired_radius(m, train[i], t)) for i in b]
        for t, costs in by_temp.items():
            results.append((float(np.mean(costs)), t, params))
        print(params, {t: round(float(np.mean(c)), 2) for t, c in by_temp.items()}, flush=True)
    cv_cost, temperature, params = min(results, key=lambda x: x[0])
    print(f"selected by CV: cost {cv_cost:.2f}, temperature {temperature}, {params}")

    model = fit(params, train)

    # Held-out test, evaluated once.
    fixed_cost = {int(x): float(np.mean([cost_at(r, x) for r in train])) for x in CANDIDATES}
    best_fixed = min(fixed_cost, key=fixed_cost.get)
    fired = np.array([fired_radius(model, r, temperature) for r in test])
    J_model = np.array([cost_at(r, x) for r, x in zip(test, fired)])
    J_fixed = np.array([cost_at(r, best_fixed) for r in test])
    J_oracle = np.array([r["J"].min() for r in test])
    J_none = np.array([r["T0"] + LAMBDA * r["C0"] for r in test])
    T_model = np.array([cost_at(r, x, "T") for r, x in zip(test, fired)])
    T_fixed = np.array([cost_at(r, best_fixed, "T") for r in test])
    C_model = np.array([cost_at(r, x, "C") for r, x in zip(test, fired)])
    C_fixed = np.array([cost_at(r, best_fixed, "C") for r in test])
    labels = np.array([r["label"] for r in test])

    # Crossings in one episode share traffic, so resample whole episodes.
    eps = np.array([r["ep"] for r in test])
    uniq = np.unique(eps)
    rng = np.random.default_rng(0)
    diffs = J_model - J_fixed
    boot = [np.concatenate([diffs[eps == e] for e in rng.choice(uniq, len(uniq))]).mean() for _ in range(4000)]

    Xt, yt = design(test)
    yhat = model.predict(Xt)
    curve_r2 = float(1 - ((yt - yhat) ** 2).sum() / ((yt - yt.mean()) ** 2).sum())

    imp = model.get_booster().get_score(importance_type="gain")
    total = sum(imp.values()) or 1.0
    importance = sorted(((k, round(v / total, 3)) for k, v in imp.items()), key=lambda kv: -kv[1])

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    booster = model.get_booster()
    booster.feature_names = MODEL_COLUMNS
    booster.save_model(str(MODEL_FILE))
    card = {
        "model": "XGBoost regressor on decision cost J(state, radius); radius = soft minimum of the predicted curve",
        "features": MODEL_COLUMNS, "params": params, "temperature": temperature, "lambda": LAMBDA,
        "radii_swept_m": CANDIDATES.tolist(), "train_crossings": len(train), "test_crossings": len(test),
        "cost_curve_r2_test": round(curve_r2, 3),
        "test_mae_m": round(float(np.mean(np.abs(fired - labels))), 1),
        "test_mae_constant_baseline_m": round(float(np.mean(np.abs(best_fixed - labels))), 1),
        "fired_radius_m": {"mean": round(float(fired.mean()), 1), "p10": round(float(np.percentile(fired, 10)), 1),
                           "p90": round(float(np.percentile(fired, 90)), 1)},
        "best_fixed_radius_m": best_fixed,
        "decision_cost": {"no_priority": round(float(J_none.mean()), 2), "best_fixed": round(float(J_fixed.mean()), 2),
                          "model": round(float(J_model.mean()), 2), "oracle": round(float(J_oracle.mean()), 2)},
        "model_minus_fixed_ci95": [round(float(np.percentile(boot, 2.5)), 2), round(float(np.percentile(boot, 97.5)), 2)],
        "ev_time_s": {"model": round(float(T_model.mean()), 1), "best_fixed": round(float(T_fixed.mean()), 1)},
        "civilian_halt_s": {"model": round(float(C_model.mean()), 1), "best_fixed": round(float(C_fixed.mean()), 1)},
        "feature_importance_gain": importance,
    }
    MODEL_CARD.write_text(json.dumps(card, indent=2))
    print(json.dumps({k: v for k, v in card.items() if k not in ("features", "feature_importance_gain")}, indent=1))
    print("top features", importance[:6])


if __name__ == "__main__":
    main()
