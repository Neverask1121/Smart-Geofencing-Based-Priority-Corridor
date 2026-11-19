"""Download the OSM road network for the study area (one-off, with exponential backoff).

Overpass public servers are shared infrastructure: the result is cached in
data/osm/ and re-used; pass --force to download again.
"""
import argparse, pathlib, sys, time, urllib.parse, urllib.request

BBOX = (23.005, 72.540, 23.050, 72.590)  # south, west, north, east: Navrangpura / CG Road / Ellisbridge / Paldi
MIRRORS = ["https://overpass.private.coffee/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass-api.de/api/interpreter"]
OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "osm" / "ahmedabad.osm.xml"
CLASSES = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if OUT.exists() and not a.force:
        print(f"cached: {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")
        return
    s, w, n, e = BBOX
    q = (f'[out:xml][timeout:120];(way["highway"~"^({CLASSES})$"]({s},{w},{n},{e});'
         f'node["highway"="traffic_signals"]({s},{w},{n},{e}););(._;>;);out body;')
    body = urllib.parse.urlencode({"data": q}).encode()
    delay = 10
    for attempt in range(9):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "its-academic-project/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if b"<osm" in data[:400] and b"<way" in data:
                OUT.write_bytes(data)
                print(f"ok from {url}: {len(data)/1e6:.1f} MB")
                return
            print(f"{url}: unexpected body {data[:120]!r}")
        except Exception as ex:
            print(f"{url}: {ex}")
        time.sleep(delay)
        delay = min(delay * 2, 120)
    sys.exit("failed to download OSM data")


if __name__ == "__main__":
    main()
