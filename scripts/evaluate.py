"""Closed-loop evaluation: run each radius policy in SUMO on seeds never used for training.

Unlike the offline numbers in train_model.py, here the model drives the live controller,
at every signal on a route, with several EVs at once. Every policy sees identical seeds.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import SCENARIOS_FILE, TRAFFIC_LEVELS  # noqa: E402
from app.core.policy import FixedRadius, NoPriority, XGBoostRadius  # noqa: E402
from app.core.simcore import SimCore  # noqa: E402
from app.core.topology import get_network  # noqa: E402

OUT = ROOT / "data" / "model" / "evaluation.json"
WARMUP = 400.0
SEED_BASE = 500_000     # dataset seeds are 1000 + episode


def policy_of(name: str):
    if name == "none":
        return NoPriority()
    if name == "xgboost":
        return XGBoostRadius()
    return FixedRadius(float(name.split("_")[1]))


def run(task: tuple[str, str, int]) -> dict:
    policy, traffic, seed = task
    data = json.loads(SCENARIOS_FILE.read_text())
    scenario = next(s for s in data["scenarios"] if s["id"] == "five")
    net = get_network()
    core = SimCore(net, policy_of(policy), scale=TRAFFIC_LEVELS[traffic], seed=seed)
    core.start()
    try:
        while core.now < WARMUP:
            core.step()
        core.schedule_scenario(scenario["evs"], [f"EV{i}" for i in range(len(scenario["evs"]))], core.now + 5)
        end = core.now + 900
        while core.now < end and (core.evs or core.scheduled):
            core.step()
        settle = core.now + 60     # let the restored signals recover before reading civilian delay
        while core.now < settle:
            core.step()
        m = core.metrics.summary(core)
    finally:
        core.close()
    trips = core.finished_evs
    return {"policy": policy, "traffic": traffic, "seed": seed, "evs_finished": len(trips),
            "ev_time": float(np.mean([t["travel_time"] for t in trips])) if trips else None,
            "ev_loss": float(np.mean([t["time_loss"] for t in trips])) if trips else None,
            "civ_delay": m["avg_civilian_delay"], "run_queue": m["run_avg_queue"],
            "requests": m["requests_total"], "successful": m["requests_successful"],
            "expired": m["requests_expired"], "conflicts": m["conflicts_detected"],
            "violations": m["safety_violations"], "collisions": m["collisions"], "teleports": m["teleports"],
            "avg_radius": m["avg_radius_run"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--policies", default="none,fixed_130,fixed_190,fixed_340,xgboost")
    a = ap.parse_args()
    pols = a.policies.split(",")
    tasks = [(p, t, SEED_BASE + s) for t in TRAFFIC_LEVELS for s in range(a.seeds) for p in pols]
    t0 = time.time()
    results = []
    with mp.Pool(a.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(run, tasks), 1):
            results.append(r)
            if i % 10 == 0:
                print(f"{i}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)
    summary = {}
    for t in TRAFFIC_LEVELS:
        summary[t] = {}
        for p in pols:
            rs = [r for r in results if r["policy"] == p and r["traffic"] == t]
            agg = lambda k: round(float(np.mean([r[k] for r in rs if r[k] is not None])), 2)  # noqa: E731
            summary[t][p] = {k: agg(k) for k in ("ev_time", "ev_loss", "civ_delay", "run_queue", "requests")}
            summary[t][p] |= {k: int(sum(r[k] for r in rs)) for k in
                              ("expired", "conflicts", "violations", "collisions", "teleports")}
            if p != "none":
                summary[t][p]["avg_radius"] = agg("avg_radius")
    # Paired comparison against each fixed radius: same seed, same traffic.
    paired = {}
    for p in pols:
        if p in ("xgboost", "none"):
            continue
        d = []
        for r in results:
            if r["policy"] != "xgboost":
                continue
            o = next(x for x in results if x["policy"] == p and x["traffic"] == r["traffic"] and x["seed"] == r["seed"])
            if r["ev_time"] is not None and o["ev_time"] is not None:
                d.append(r["ev_time"] - o["ev_time"])
        rng = np.random.default_rng(0)
        boot = [rng.choice(d, len(d)).mean() for _ in range(4000)]
        paired[p] = {"mean_ev_time_diff_s": round(float(np.mean(d)), 2),
                     "ci95": [round(float(np.percentile(boot, 2.5)), 2), round(float(np.percentile(boot, 97.5)), 2)]}
    OUT.write_text(json.dumps({"seeds": a.seeds, "summary": summary, "xgboost_vs_fixed": paired, "runs": results}, indent=1))
    print(json.dumps({"summary": summary, "xgboost_vs_fixed": paired}, indent=1))


if __name__ == "__main__":
    main()
