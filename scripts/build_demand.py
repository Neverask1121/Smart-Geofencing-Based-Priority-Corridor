"""Generate two hours of civilian trips. The scenario's traffic level scales this file at run time."""
import os, pathlib, re, subprocess, sys
import sumo

ROOT = pathlib.Path(__file__).resolve().parents[1]
NET = ROOT / "data" / "net"
PERIOD = sys.argv[1] if len(sys.argv) > 1 else "0.9"   # seconds between departures at scale 1.0


def main() -> None:
    env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)
    cmd = [sys.executable, os.path.join(sumo.SUMO_HOME, "tools", "randomTrips.py"),
           "-n", str(NET / "ahmedabad.net.xml"), "-r", str(NET / "civilian.rou.xml"),
           "-o", str(NET / "civilian.trips.xml"), "--additional-file", str(NET / "vtypes.add.xml"),
           "--trip-attributes", 'type="civilian" departLane="best" departSpeed="max"',
           "-b", "0", "-e", "7200", "-p", PERIOD, "--seed", "42",
           "--fringe-factor", "8", "--min-distance", "1500", "--speed-exponent", "2",
           "--random-depart", "--validate"]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    print(r.stdout[-400:], r.stderr[-800:])
    if r.returncode:
        sys.exit(r.returncode)
    # duarouter copies the used vTypes into its output; vtypes.add.xml stays the single definition.
    rou = NET / "civilian.rou.xml"
    text = re.sub(r"<vType\b[^>]*?/>\s*|<vType\b.*?</vType>\s*", "", rou.read_text(), flags=re.S)
    rou.write_text(text)


if __name__ == "__main__":
    main()
