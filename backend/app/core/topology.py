"""Static network model: geometry, coordinate conversion and signal structure.

Everything about a signal (movements, approaches, compatibility) comes from the
SUMO network and its signal programs. Nothing assumes a four-way, four-phase layout.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pyproj
import sumolib

from ..config import NET_FILE, TLS_SOURCES

GREEN = "Gg"
CARDINALS = ["Northbound", "North-eastbound", "Eastbound", "South-eastbound",
             "Southbound", "South-westbound", "Westbound", "North-westbound"]
TURNS = {"s": "through", "l": "left", "r": "right", "t": "U-turn", "L": "partial left", "R": "partial right"}


def bearing_label(deg: float) -> str:
    return CARDINALS[int(((deg % 360) + 22.5) // 45) % 8]


def bearing_of(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    """Compass heading from p0 to p1 in network coordinates (x east, y north)."""
    return math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1])) % 360


@dataclass(frozen=True)
class Link:
    index: int
    in_lane: str
    out_lane: str
    in_edge: str
    out_edge: str
    turn: str


@dataclass
class Approach:
    edge: str
    name: str
    bearing: float
    label: str
    lanes: int
    lon: float
    lat: float
    links: list[int] = field(default_factory=list)


@dataclass
class TlsInfo:
    id: str
    name: str
    source: str
    lon: float
    lat: float
    x: float
    y: float
    program_id: str
    phases: list[tuple[str, float]]
    links: dict[int, Link]
    approaches: dict[str, Approach]
    pairs: dict[tuple[str, str], list[int]]
    out_edges: list[str]

    @property
    def green_phases(self) -> list[int]:
        return [i for i, (s, _) in enumerate(self.phases) if any(c in GREEN for c in s)]

    def next_green_phase(self, after: int) -> int:
        """First pure green phase after `after` in cycle order, used to resume the program."""
        n = len(self.phases)
        for k in range(1, n + 1):
            i = (after + k) % n
            if any(c in GREEN for c in self.phases[i][0]) and "y" not in self.phases[i][0]:
                return i
        return after

    def time_until_green(self, link: int, phase: int, remaining: float) -> tuple[float, float]:
        """(seconds until `link` is next green, seconds of green left if it is green now),
        walking the fixed program from the current phase."""
        n = len(self.phases)
        if self.phases[phase][0][link] in GREEN:
            left, i = remaining, (phase + 1) % n
            for _ in range(n - 1):
                if self.phases[i][0][link] not in GREEN:
                    break
                left += self.phases[i][1]
                i = (i + 1) % n
            return 0.0, left
        wait, i = remaining, (phase + 1) % n
        for _ in range(n):
            if self.phases[i][0][link] in GREEN:
                return wait, 0.0
            wait += self.phases[i][1]
            i = (i + 1) % n
        return wait, 0.0


@dataclass(frozen=True)
class Crossing:
    """One passage of a route through a signal."""
    route_index: int           # index of in_edge in the route
    tls: str
    in_edge: str
    out_edge: str
    links: tuple[int, ...]
    stop_m: float              # distance from route start to the stop line


class NetworkModel:
    def __init__(self, path=NET_FILE) -> None:
        self.net = sumolib.net.readNet(str(path), withPrograms=True, withInternal=False)
        loc = self.net._location
        self.offset = tuple(float(v) for v in loc["netOffset"].split(","))
        self.proj = pyproj.Proj(loc["projParameter"])
        self.sources: dict[str, str] = json.loads(TLS_SOURCES.read_text()) if TLS_SOURCES.exists() else {}
        self.tls: dict[str, TlsInfo] = {}
        self.pair_to_tls: dict[tuple[str, str], tuple[str, tuple[int, ...]]] = {}
        for t in self.net.getTrafficLights():
            info = self._build_tls(t)
            self.tls[info.id] = info
            for pair, idx in info.pairs.items():
                self.pair_to_tls[pair] = (info.id, tuple(idx))
        seen: dict[str, int] = {}
        for info in sorted(self.tls.values(), key=lambda t: (t.lat, t.lon)):
            seen[info.name] = seen.get(info.name, 0) + 1
            if seen[info.name] > 1:
                info.name = f"{info.name} ({seen[info.name]})"

    # ---- coordinates -------------------------------------------------
    def to_lonlat(self, xy: np.ndarray) -> np.ndarray:
        """SUMO network x,y (n,2) -> lon,lat (n,2). Undoes netOffset, then inverts the UTM projection."""
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        lon, lat = self.proj(xy[:, 0] - self.offset[0], xy[:, 1] - self.offset[1], inverse=True)
        return np.column_stack([lon, lat])

    def lonlat(self, x: float, y: float) -> tuple[float, float]:
        p = self.to_lonlat(np.array([[x, y]]))[0]
        return float(p[0]), float(p[1])

    # ---- signals -----------------------------------------------------
    def _build_tls(self, t) -> TlsInfo:
        tid = t.getID()
        progs = t.getPrograms()
        pid = sorted(progs)[0]
        phases = [(p.state, float(p.duration)) for p in progs[pid].getPhases()]
        links: dict[int, Link] = {}
        pairs: dict[tuple[str, str], list[int]] = {}
        for in_lane, out_lane, idx in t.getConnections():
            ie, oe = in_lane.getEdge(), out_lane.getEdge()
            turn = "s"
            for c in ie.getConnections(oe):
                if c.getFromLane() == in_lane and c.getToLane() == out_lane:
                    turn = c.getDirection()
            links[idx] = Link(idx, in_lane.getID(), out_lane.getID(), ie.getID(), oe.getID(), turn)
            pairs.setdefault((ie.getID(), oe.getID()), []).append(idx)
        approaches: dict[str, Approach] = {}
        for lk in links.values():
            if lk.in_edge not in approaches:
                e = self.net.getEdge(lk.in_edge)
                shape = e.getShape()
                brg = bearing_of(shape[-2], shape[-1])
                lon, lat = self.lonlat(*shape[-1])
                approaches[lk.in_edge] = Approach(lk.in_edge, e.getName() or "", brg, bearing_label(brg),
                                                  e.getLaneNumber(), lon, lat)
            approaches[lk.in_edge].links.append(lk.index)
        ends = [self.net.getEdge(a).getShape()[-1] for a in approaches]
        x, y = float(np.mean([p[0] for p in ends])), float(np.mean([p[1] for p in ends]))
        lon, lat = self.lonlat(x, y)
        names = sorted({a.name for a in approaches.values() if a.name})
        name = " × ".join(names[:2]) if names else f"Signal {tid[:14]}"
        return TlsInfo(tid, name, self.sources.get(tid, "osm"), lon, lat, x, y, pid, phases, links, approaches,
                       pairs, sorted({lk.out_edge for lk in links.values()}))

    # ---- routes ------------------------------------------------------
    def edge_length(self, edge: str) -> float:
        return self.net.getEdge(edge).getLength()

    def route_crossings(self, edges: list[str]) -> list[Crossing]:
        out: list[Crossing] = []
        cum = 0.0
        for i, e in enumerate(edges):
            cum += self.edge_length(e)
            if i + 1 < len(edges) and (e, edges[i + 1]) in self.pair_to_tls:
                tls, links = self.pair_to_tls[(e, edges[i + 1])]
                out.append(Crossing(i, tls, e, edges[i + 1], links, cum))
        return out

    def route_polyline(self, edges: list[str]) -> tuple[list[list[float]], list[float], list[float]]:
        """Route as [[lon,lat],...], cumulative metres at each vertex, and the metres at which each edge starts."""
        pts: list[tuple[float, float]] = []
        starts: list[int] = []
        for e in edges:
            starts.append(len(pts))
            pts.extend(self.net.getEdge(e).getShape())
        arr = np.array(pts)
        ll = self.to_lonlat(arr)
        d = np.hypot(*np.diff(arr, axis=0).T)
        cum = np.concatenate([[0.0], np.cumsum(d)])
        return ([[round(float(a), 6), round(float(b), 6)] for a, b in ll],
                [round(float(c), 1) for c in cum], [float(cum[i]) for i in starts])

    # ---- GeoJSON for the map -----------------------------------------
    def roads_geojson(self) -> dict:
        feats = []
        for e in self.net.getEdges():
            if e.getFunction() == "internal":
                continue
            ll = self.to_lonlat(np.array(e.getShape()))
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [[round(float(a), 6), round(float(b), 6)] for a, b in ll]},
                "properties": {"id": e.getID(), "name": e.getName() or "",
                               "class": (e.getType() or "").replace("highway.", ""),
                               "lanes": e.getLaneNumber(), "speed": round(e.getSpeed(), 1)},
            })
        return {"type": "FeatureCollection", "features": feats}

    def bbox(self) -> list[float]:
        b = self.net.getBoundary()
        ll = self.to_lonlat(np.array([[b[0], b[1]], [b[2], b[3]]]))
        return [float(ll[0, 0]), float(ll[0, 1]), float(ll[1, 0]), float(ll[1, 1])]


@lru_cache(maxsize=1)
def get_network() -> NetworkModel:
    return NetworkModel()
