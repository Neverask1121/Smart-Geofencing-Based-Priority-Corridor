import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core.topology import Approach, Link, TlsInfo  # noqa: E402


def make_tls(phases=None) -> TlsInfo:
    """A 4-arm junction. Links: 0,1 = N-S through; 2,3 = E-W through; 4 = N permissive turn across link 1."""
    phases = phases or [("GGrrg", 30.0), ("yyrry", 3.0), ("rrrrr", 2.0), ("rrGGr", 30.0), ("rryyr", 3.0), ("rrrrr", 2.0)]
    links = {
        0: Link(0, "n_0", "s_0", "n", "s", "s"),
        1: Link(1, "s_in_0", "n_out_0", "s_in", "n_out", "s"),
        2: Link(2, "e_0", "w_0", "e", "w", "s"),
        3: Link(3, "w_in_0", "e_out_0", "w_in", "e_out", "s"),
        4: Link(4, "n_1", "e_out_0", "n", "e_out", "r"),
    }
    approaches = {e: Approach(e, e, 0.0, f"{e}-bound", 1, 0.0, 0.0, []) for e in ("n", "s_in", "e", "w_in")}
    for lk in links.values():
        approaches[lk.in_edge].links.append(lk.index)
    pairs: dict = {}
    for lk in links.values():
        pairs.setdefault((lk.in_edge, lk.out_edge), []).append(lk.index)
    return TlsInfo("J", "Test junction", "osm", 0.0, 0.0, 0.0, 0.0, "0", phases, links, approaches, pairs, [])


class FakeIO:
    """Stands in for SUMO: the program advances on its own until overridden."""

    def __init__(self, info: TlsInfo) -> None:
        self.info = info
        self.override: str | None = None
        self.phase, self.phase_end = 0, info.phases[0][1]
        self.log: list[tuple[str, str]] = []

    def set_state(self, tls: str, state: str) -> None:
        self.override = state
        self.log.append(("set", state))

    def resume_program(self, tls: str, program: str, phase: int) -> None:
        self.override = None
        self.phase, self.phase_end = phase, None
        self.log.append(("resume", str(phase)))

    def state(self, now: float) -> str:
        if self.override is not None:
            return self.override
        if self.phase_end is None:
            self.phase_end = now + self.info.phases[self.phase][1]
        while now >= self.phase_end:
            self.phase = (self.phase + 1) % len(self.info.phases)
            self.phase_end += self.info.phases[self.phase][1]
        return self.info.phases[self.phase][0]


@pytest.fixture
def tls() -> TlsInfo:
    return make_tls()
