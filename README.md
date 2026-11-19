# Adaptive EV Priority: Ahmedabad ITS control centre

A smart-city traffic application for emergency vehicle (EV) signal priority. SUMO simulates
real Ahmedabad streets, an XGBoost model sets each EV's activation geofence, a coordinator
arbitrates between competing EVs, and a React control centre shows all of it live.

**SUMO is the simulation engine. FastAPI is the backend. React is the interface.** Every value
on screen comes from the running simulation.

## Run it

Windows, Python 3.14, Node 24. First time only:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
```

Then start everything and open <http://127.0.0.1:8000>:

```powershell
.\run.ps1
```

Pick a scenario in **Run setup** and press **Run scenario**. Press **D** for demo mode, Esc to leave.

The network, scenarios, dataset and trained model are already in `data/`, so nothing needs
rebuilding. For frontend development, run `npm run dev` in `frontend/` and open port 5173.

## Architecture

```text
React + MapLibre + deck.gl  <-- REST + /ws/simulation -->  FastAPI
                                                              |  commands in, immutable view out
                                                       Engine thread (only thread using TraCI)
                                                              |
             SimCore: EV tracking, features, radius policy, Coordinator, SignalController
                                                              |
                                                     SUMO (headless, TraCI)
```

| Path | Contents |
|---|---|
| `backend/app/core/simcore.py` | One SUMO run. Used by the live app, dataset generation and evaluation alike |
| `backend/app/core/signals.py` | Safe pre-emption, plus an independent runtime `SafetyMonitor` |
| `backend/app/core/coordination.py` | Request lifecycle, conflict detection, arbitration |
| `backend/app/core/features.py` | The single definition of the model's features |
| `backend/app/core/policy.py` | Radius policies: XGBoost, fixed radius, no priority |
| `backend/app/core/topology.py` | Geometry, coordinate conversion, signal structure |
| `backend/app/engine.py`, `hub.py`, `main.py` | Engine thread, WebSocket fan-out, API |
| `frontend/src/state/live.ts` | High-rate vehicle state, kept outside React |
| `frontend/src/components/map/` | Map and deck.gl layers |
| `scripts/` | Pipeline: `fetch_osm`, `build_network`, `build_demand`, `build_scenarios`, `generate_dataset`, `train_model`, `evaluate` |

### Technology choices

- **MapLibre GL JS** draws the basemap and the SUMO road network. **deck.gl** draws moving objects
  on top of it. It renders into MapLibre rather than competing with it, and it avoids pushing
  GeoJSON through a worker on every frame.
- **Tiles: OpenFreeMap.** Its site states no API key and no limits on map views or requests, with
  attribution handled by MapLibre. The OSM Foundation tile policy covers `tile.openstreetmap.org`
  raster tiles, which are not used here. OpenFreeMap offers no SLA, so if the style fails to load
  within 6 s the app falls back to a plain background. The road network comes from our own backend
  and still renders, though street labels do not.
- **Coordinates:** SUMO x,y minus `netOffset`, then inverse UTM 43N with pyproj. A test checks this
  against SUMO's own `convertGeo`.

## How priority works

1. Every 2 simulated seconds the policy predicts a radius for each EV and its next signal.
2. When the straight-line distance to that signal falls within the radius, a request opens. This
   is the same test the map draws, so "inside the circle" and "activated" always agree.
3. The coordinator scores open requests per signal (vehicle class, ETA, waiting time). If another EV
   on a conflicting movement is due within 15 s, its request opens at once (marked "opened early"),
   so both are scored rather than the first radius simply winning. Requests that one phase can
   carry run together. Others wait, and a request being served is never
   pre-empted, so priority cannot flip-flop.
4. The signal goes green, yellow (3 s), red clearance (2 s), new green. No green is cut before 6 s.
5. Once the EV clears, the signal returns to its program by the same sequence.

Movements and compatibility come from the network's `controlledLinks` and program phases. Nothing
assumes a four-way junction. A target state is always a program phase with links only removed. A
permissive movement becomes protected only after SUMO's right-of-way foes are held red. Browsers
have no way to set a signal: no endpoint exists, and a test enforces that.

## How the model was built

No labelled "optimal radius" exists, so the data comes from **counterfactual sweeps**. Each episode
replays one seed and traffic level once per radius (80 to 480 m) and once with no priority. Runs are
identical until a radius takes effect, so outcome differences are caused by the radius.

Decision cost is `J(r) = EV_time(r) + 0.02 × civilian_halted_vehicle_seconds(r)`. The weight is a
policy choice: one EV-second counts as much as 50 civilian halted seconds.

XGBoost learns the **cost curve** `J(state, radius)`, and the live radius is the soft minimum of the
predicted curve. Regressing the best radius directly failed: `R²` was 0.10 on partial data and it
gained nothing over a constant, because many crossings have flat cost curves and their "best"
radius is noise.

- 120 episodes of 8 runs each: 960 SUMO runs, 960 crossings. 8 episodes were dropped (see Limitations).
- 720 training and 176 test crossings, split by whole episode.
- Hyperparameters chosen by cross-validation on training episodes only.

## Results

**Read this before presenting.** Priority clearly works. The machine-learned radius does not clearly
beat a well-chosen fixed radius.

### Closed loop: five EVs, unseen seeds

8 seeds per traffic level, 120 runs, same seeds for every policy. Mean per EV trip.

| Traffic | Policy | EV time (s) | EV time lost (s) | Civilian delay (s) | Expired | Teleports |
|---|---|---|---|---|---|---|
| Low | No priority | 448.9 | 100.4 | 56.8 | 0 | 0 |
| Low | Fixed 190 m | 382.3 | 33.8 | 54.6 | 0 | 0 |
| Low | Fixed 340 m | 382.2 | 33.8 | 54.8 | 0 | 0 |
| Low | **XGBoost** | 383.3 | 34.8 | 54.8 | 0 | 0 |
| Medium | No priority | 477.2 | 128.6 | 64.8 | 0 | 0 |
| Medium | Fixed 190 m | 413.6 | 65.1 | 62.2 | 0 | 0 |
| Medium | Fixed 340 m | 412.7 | 64.2 | 61.8 | 3 | 0 |
| Medium | **XGBoost** | 413.5 | 65.0 | 62.1 | 0 | 0 |
| High | No priority | 505.3 | 156.8 | 74.6 | 0 | 4 |
| High | Fixed 190 m | 430.7 | 82.2 | 71.9 | 0 | 2 |
| High | Fixed 340 m | 427.5 | 79.0 | 71.6 | 4 | 18 |
| High | **XGBoost** | 433.1 | 84.6 | 72.0 | 0 | 0 |

Expired and teleport columns are totals over 8 runs. Fixed 130 m was also run and is left out of this
table for space; it is in the comparison below. `data/model/evaluation.json` has every run.

Paired difference in EV time, XGBoost minus fixed (negative favours XGBoost), with 95% CI:

| Against | Difference (s) | 95% CI | Reading |
|---|---|---|---|
| Fixed 130 m | −3.9 | −8.2 to +0.3 | Not significant |
| Fixed 190 m | +1.1 | −1.7 to +3.9 | Not significant |
| Fixed 340 m | +2.5 | −1.9 to +6.8 | Not significant |

### What can honestly be claimed

- **With the XGBoost radius, signal priority cuts EV trip time by 64 to 72 s (13 to 15 %)** and EV time
  lost by 46 to 65 %, compared with no priority. Civilian delay is also slightly lower.
- **The XGBoost radius performs on par with the best fixed radii.** It reached that level without
  hand-tuning, and it adapts per vehicle (mean near 200 m; live values seen from about 150 to 390 m).
- **It avoided the side effects of a large fixed radius**: 0 expired requests and 0 teleports across
  all levels, against 7 expired and 18 teleports for fixed 340 m. These are small counts from 24
  runs per policy, so treat this as an observation rather than a proven effect.
- **Do not claim** that ML makes EVs faster than a tuned fixed radius. The data does not show that.

### Offline, single signal (176 held-out crossings)

| Policy | Decision cost J |
|---|---|
| No priority | 126.11 |
| Best fixed (190 m) | 107.17 |
| **XGBoost** | **106.75** |
| Oracle (perfect per-crossing choice) | 103.95 |

Model minus fixed is −0.42, 95% CI −0.89 to −0.02, bootstrapped by episode. This small gain did
not carry over to a measurable closed-loop gain. Cost-curve test `R²` is 0.267. The oracle row shows
why: even perfect prediction could only save about 3 cost units over the best fixed radius, so this
network and signal plan leave little for an adaptive radius to win.

### Safety

- **0 signal safety violations in all 120 closed-loop runs.** The monitor checks every displayed
  state for green-to-red without yellow, short yellows, and green sets outside the program.
- SUMO reports vehicle collisions in every policy, including no priority (46 to 482 over 8 runs),
  at similar rates. Netconvert's warnings about intersecting turns on these OSM junctions suggest
  network geometry, but that cause has not been proven.

## Tests

```powershell
.venv\Scripts\python -m pytest backend/tests -q
cd frontend; npx vitest run
```

The backend suite includes a random request storm with a safety check at every step, real SUMO
scenario runs, coordinate checks and the WebSocket contract. The frontend suite checks that
geofence vertices sit at the true metre radius, and that interpolation never leaves the segment
between two simulated positions. `frontend/e2e/` holds headless Chrome checks; they need a running
backend.

## Limitations

- **Results predate conflict lookahead.** The closed-loop tables were measured before that change. It
  only affects EVs meeting at a signal, which was rare in those runs, but rerun `scripts/evaluate.py`
  before quoting them as final.
- **Performance depends on the machine.** On mains power, warm-up took seconds and heavy traffic ran at
  3 to 6x. In a later session on battery with little free RAM, the same work ran about 14x slower.
  Present with the laptop plugged in and other apps closed.
- **Signals:** OSM maps only about 8 multi-approach signals here, plus 5 small mid-block ones. Another
  13 are inferred at major crossroads. Each is labelled in `data/net/tls_sources.json` and in the UI.
- **Signal timing is not surveyed.** Programs are netconvert's generated fixed-time plans, and demand
  is synthetic (`randomTrips`), not calibrated to counts.
- **Driver behaviour:** civilians do not pull aside and EVs obey signals. Priority has to come from the
  controller, so results may understate real EV speeds. Indian lane-free traffic is not modelled.
- **Dataset:** 8 episodes ran before a controller bug was fixed (a target change during clearance could
  skip a yellow). They were excluded. The other episodes also ran on the pre-fix controller, but the
  bug only fires after an EV has cleared and the monitor recorded nothing in those episodes. All
  closed-loop results use the fixed controller.
- **Scenarios:** in paired scenarios the second EV dispatches when the first EV's live ETA matches its
  travel time. Conflicts then arise from real traffic, but usually not always (19 of 20 test runs, at fixed 130 m and 250 m radii).
- **Basemap needs internet.** Without it the app shows the road network on a plain background.

## Licences

Road data © OpenStreetMap contributors (ODbL). Basemap: OpenFreeMap, © OpenMapTiles.
