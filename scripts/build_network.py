"""Convert the OSM extract to a left-hand-traffic SUMO network (two passes).

Pass 1 imports OSM using only the signals mapped in OSM.
Pass 2 adds signals at major unmapped crossroads, because OSM's signal coverage of
Ahmedabad is sparse (about 8 multi-approach signals in this area). Every signal is
recorded in tls_sources.json as "osm" or "inferred" and the UI shows the distinction.
"""
import json, math, os, pathlib, re, subprocess, sys
import sumo, sumolib

ROOT = pathlib.Path(__file__).resolve().parents[1]
NETDIR = ROOT / "data" / "net"
RAW, NET = NETDIR / "pass1.net.xml", NETDIR / "ahmedabad.net.xml"
NETCONVERT = os.path.join(sumo.SUMO_HOME, "bin", "netconvert")
MAX_INFERRED, MIN_SPACING_M = 26, 260.0
MAJOR = {"highway.primary", "highway.secondary"}
ROADS = MAJOR | {"highway.tertiary"}
COMMON = ["--lefthand", "true",                    # India drives on the left
          "--tls.default-type", "static", "--tls.cycle.time", "90",
          "--tls.yellow.time", "3", "--tls.allred.time", "2",
          "--no-turnarounds", "true", "--output.street-names", "true",
          "--ignore-errors", "true", "--no-warnings", "true"]


# Urban limits in m/s. SUMO's OSM defaults (27.8 m/s on primary roads) are far too fast for this area.
URBAN_SPEEDS = {"primary": 13.9, "primary_link": 11.1, "secondary": 12.5, "secondary_link": 11.1,
                "tertiary": 11.1, "tertiary_link": 8.3, "unclassified": 8.3, "residential": 8.3,
                "living_street": 5.6, "trunk": 16.7, "trunk_link": 13.9}


def write_type_file() -> pathlib.Path:
    src = pathlib.Path(sumo.SUMO_HOME, "data", "typemap", "osmNetconvert.typ.xml").read_text()
    for name, v in URBAN_SPEEDS.items():
        src = re.sub(rf'(<type id="highway\.{name}"[^>]*?speed=")[0-9.]+"', rf'\g<1>{v}"', src)
    out = NETDIR / "urban.typ.xml"
    out.write_text(src)
    return out


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-1500:])


def legs(node) -> tuple[int, int]:
    inc = [e for e in node.getIncoming() if e.getType() in ROADS]
    return len(inc), sum(e.getType() in MAJOR for e in inc)


def main() -> None:
    run([NETCONVERT, "--osm-files", str(ROOT / "data/osm/ahmedabad.osm.xml"), "--output-file", str(RAW),
         "--type-files", str(write_type_file()),
         "--geometry.remove", "true", "--roundabouts.guess", "true", "--ramps.guess", "true",
         "--junctions.join", "true", "--junctions.join-dist", "18", "--junctions.corner-detail", "5",
         "--tls.join", "true", "--tls.join-dist", "30",
         "--tls.guess-signals", "true", "--tls.guess-signals.dist", "30",
         "--keep-edges.in-geo-boundary", "72.540,23.005,72.590,23.050",
         "--keep-edges.by-vclass", "passenger", "--keep-edges.components", "1",
         "--default.lanewidth", "3.2", *COMMON])

    net = sumolib.net.readNet(str(RAW), withPrograms=True)
    osm_ids = [t.getID() for t in net.getTrafficLights()]
    taken = [n.getCoord() for n in net.getNodes() if n.getType().startswith("traffic_light")]
    cands = []
    for n in net.getNodes():
        if n.getType().startswith("traffic_light") or n.getType() == "dead_end":
            continue
        total, major = legs(n)
        names = {e.getName() for e in n.getIncoming() if e.getName()}
        if total >= 3 and major >= 2 and len(n.getOutgoing()) >= 3 and len(names) >= 2:
            cands.append((total * 2 + major, n))
    cands.sort(key=lambda c: (-c[0], c[1].getID()))
    chosen: list[str] = []
    for _, n in cands:
        x, y = n.getCoord()
        if all(math.hypot(x - a, y - b) >= MIN_SPACING_M for a, b in taken):
            chosen.append(n.getID())
            taken.append((x, y))
        if len(chosen) == MAX_INFERRED:
            break

    run([NETCONVERT, "--sumo-net-file", str(RAW), "--output-file", str(NET),
         "--tls.set", ",".join(chosen), *COMMON])
    RAW.unlink()

    final = sumolib.net.readNet(str(NET), withPrograms=True)
    sources = {}
    for t in final.getTrafficLights():
        tid = t.getID()
        sources[tid] = "osm" if tid in osm_ids else "inferred"
    (NETDIR / "tls_sources.json").write_text(json.dumps(sources, indent=1))
    print(f"edges={len(final.getEdges())} tls={len(sources)} "
          f"osm={sum(v == 'osm' for v in sources.values())} inferred={sum(v == 'inferred' for v in sources.values())}")


if __name__ == "__main__":
    main()
