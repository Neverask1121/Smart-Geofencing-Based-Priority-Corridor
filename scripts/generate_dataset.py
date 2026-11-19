"""Generate training data by counterfactual radius sweeps in SUMO.

Each episode fixes a seed and traffic level, then replays the same run once per candidate
radius (plus once with no priority). The runs are identical until a radius first takes
effect, so differences in outcome are caused by the radius. Each EV requests priority at
exactly one target signal, which keeps every crossing a clean experiment.

Output: data/dataset/raw.jsonl, one line per crossing. Resumable: finished episodes are skipped.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pathlib
import random
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import SCENARIOS_FILE, STEP_LENGTH  # noqa: E402
from app.core.policy import FixedRadius, NoPriority  # noqa: E402
from app.core.simcore import EV_TYPES, EvSpec, SimCore  # noqa: E402
from app.core.topology import get_network  # noqa: E402

OUT = ROOT / "data" / "dataset" / "raw.jsonl"
RADII = [80, 130, 190, 260, 340, 420, 480]
WARMUP, SPACING, K, WINDOW = 400.0, 40.0, 8, 200.0
SNAPSHOT_DISTANCES = [600.0, 480.0, 360.0, 240.0, 140.0]


def plan_episode(ep: int, targets: dict) -> dict:
    rng = random.Random(10_000 + ep)
    scale = round(rng.uniform(0.3, 1.05), 3)
    tls_ids = sorted(t for t, r in targets.items() if r)
    rng.shuffle(tls_ids)
    specs = []
    for i, tls in enumerate(tls_ids[:K]):
        key = rng.choice(sorted(targets[tls]))
        specs.append({"id": f"EV{i}", "type": rng.choice(EV_TYPES), "tls": tls, "pair": key,
                      "edges": targets[tls][key], "depart": WARMUP + i * SPACING})
    return {"ep": ep, "seed": 1000 + ep, "scale": scale, "specs": specs}


def run_once(plan: dict, radius: int | None) -> dict:
    net = get_network()
    policy = NoPriority() if radius is None else FixedRadius(float(radius))
    core = SimCore(net, policy, scale=plan["scale"], seed=plan["seed"], track_civilians=False)
    core.start()
    specs = plan["specs"]
    for s in specs:
        core.schedule(EvSpec(s["id"], s["type"], s["edges"], s["depart"], target_in_edge=s["pair"].split("|")[0]))
    res = {s["id"]: {"t_cross": None, "civ_halt": 0.0, "snapshots": [], "level": 0} for s in specs}
    target_idx = {s["id"]: s["edges"].index(s["pair"].split("|")[0]) for s in specs}
    end = specs[-1]["depart"] + WINDOW
    try:
        while core.now < end:
            core.step()
            for s in specs:
                rec = res[s["id"]]
                if not s["depart"] <= core.now <= s["depart"] + WINDOW:
                    continue
                rec["civ_halt"] += STEP_LENGTH * sum(core.edge_stats.get(a, (0, 0, 0))[1]
                                                     for a in net.tls[s["tls"]].approaches)
                ev = core.evs.get(s["id"])
                if ev is None:
                    if rec["t_cross"] is None and s["id"] in {t["id"] for t in core.finished_evs}:
                        rec["t_cross"] = core.now
                    continue
                if ev.departed_at is None:
                    continue
                if rec["t_cross"] is None and ev.route_index > target_idx[s["id"]]:
                    rec["t_cross"] = core.now
                elif radius is None and ev.features and ev.crossing is not None and rec["t_cross"] is None:
                    pending = [d for d in SNAPSHOT_DISTANCES if d >= ev.geo_dist]
                    if len(pending) > rec["level"]:
                        rec["level"] = len(pending)
                        rec["snapshots"].append(dict(ev.features, geo_dist=ev.geo_dist))
        violations = core.safety_violations
    finally:
        core.close()
    return {"res": res, "violations": violations}


def run_episode(plan: dict) -> list[dict]:
    sweep = {str(r): run_once(plan, r) for r in [None, *RADII]}
    rows = []
    base = sweep["None"]["res"]
    for s in plan["specs"]:
        sid = s["id"]
        rows.append({
            "ep": plan["ep"], "scale": plan["scale"], "tls": s["tls"], "ev_type": s["type"], "pair": s["pair"],
            "depart": s["depart"], "snapshots": base[sid]["snapshots"],
            "outcomes": {k: {"t_cross": v["res"][sid]["t_cross"], "civ_halt": round(v["res"][sid]["civ_halt"], 1)}
                         for k, v in sweep.items()},
            "violations": sum(v["violations"] for v in sweep.values()),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=120)
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["ep"] for line in out.open()} if out.exists() else set()
    targets = json.loads(SCENARIOS_FILE.read_text())["targets"]
    plans = [plan_episode(e, targets) for e in range(a.episodes) if e not in done]
    print(f"{len(plans)} episodes to run, {len(done)} already done", flush=True)
    t0 = time.time()
    with mp.Pool(a.workers) as pool, out.open("a") as f:
        for i, rows in enumerate(pool.imap_unordered(run_episode, plans), 1):
            for r in rows:
                f.write(json.dumps(r) + "\n")
            f.flush()
            print(f"{i}/{len(plans)} episodes, {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
