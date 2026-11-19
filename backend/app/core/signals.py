"""Safe signal pre-emption for one intersection.

SignalController never jumps between states. Any change of green passes through
    green -> yellow (>= YELLOW_TIME) -> red on those links (>= ALL_RED_TIME) -> new green
and no green is cut before MIN_GREEN. SafetyMonitor checks this independently on
every state SUMO actually displays, so a controller bug shows up as a counted violation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from ..config import ALL_RED_TIME, MIN_GREEN, YELLOW_TIME
from .topology import GREEN, TlsInfo


class Mode(str, Enum):
    NORMAL = "normal"
    WAIT_MIN_GREEN = "holding_min_green"
    YELLOW = "yellow"
    ALL_RED = "all_red"
    SERVING = "serving"


@dataclass(frozen=True)
class ServePlan:
    state: str              # target signal string
    phase: int              # program phase it derives from


class SignalIO(Protocol):
    def set_state(self, tls: str, state: str) -> None: ...
    def resume_program(self, tls: str, program: str, phase: int) -> None: ...


def greens(state: str) -> frozenset[int]:
    return frozenset(i for i, c in enumerate(state) if c in GREEN)


def build_plan(info: TlsInfo, groups: list[tuple[int, ...]],
               foe_links: Callable[[int], set[int]]) -> ServePlan | None:
    """Best program phase serving every link group, or None if no phase can do so safely.

    The target is always a program phase with links only ever removed, so it cannot
    contain a combination the signal plan never allowed. A permissive `g` movement
    is promoted to protected `G` only after the links with right of way over it are
    held red; if that would stop another requested group, the groups are incompatible.
    """
    best: tuple[tuple[int, int], ServePlan] | None = None
    wanted = {lk for g in groups for lk in g}
    for pi in info.green_phases:
        state = list(info.phases[pi][0])
        if "y" in state or not all(any(state[lk] in GREEN for lk in g) for g in groups):
            continue
        ok = True
        for lk in sorted(wanted):
            if state[lk] == "g":
                foes = {f for f in foe_links(lk) if state[f] in GREEN}
                if foes & wanted:
                    ok = False
                    break
                for f in foes:
                    state[f] = "r"
                state[lk] = "G"
        # Each group needs one protected green; other lanes of it may be red in this phase.
        if not ok or not all(any(state[lk] == "G" for lk in g) for g in groups):
            continue
        rank = (sum(state[lk] == "G" for lk in wanted), sum(c in GREEN for c in state))
        if best is None or rank > best[0]:
            best = (rank, ServePlan("".join(state), pi))
    return best[1] if best else None


class SafetyMonitor:
    """Independent runtime check of every displayed state."""

    def __init__(self, info: TlsInfo) -> None:
        self.allowed = [greens(s) for s, _ in info.phases]
        ys = [d for s, d in info.phases if "y" in s]
        self.min_yellow = min([YELLOW_TIME, *ys])
        self.prev: str | None = None
        self.yellow_since: dict[int, float] = {}
        self.violations: list[str] = []

    def observe(self, now: float, state: str) -> None:
        g = greens(state)
        if g and not any(g <= a for a in self.allowed):
            self.violations.append(f"{now:.1f}s: green set {sorted(g)} is in no program phase")
        if self.prev is not None:
            for i, (a, b) in enumerate(zip(self.prev, state)):
                if a in GREEN and b in "rR":
                    self.violations.append(f"{now:.1f}s: link {i} went green to red without yellow")
                if a != "y" and b == "y":
                    self.yellow_since[i] = now
                if a == "y" and b != "y" and i in self.yellow_since:
                    held = now - self.yellow_since.pop(i)
                    if held < self.min_yellow - 1e-6:
                        self.violations.append(f"{now:.1f}s: link {i} yellow held only {held:.1f}s")
        self.prev = state


class SignalController:
    def __init__(self, info: TlsInfo, io: SignalIO, on_event: Callable[[str, str], None] | None = None) -> None:
        self.info = info
        self.io = io
        self.emit = on_event or (lambda kind, msg: None)
        self.mode = Mode.NORMAL
        self.target: ServePlan | None = None
        self.restoring = False
        self.taken = False                      # True once we have overridden the program
        self.resume_phase = 0
        self.state = info.phases[0][0]
        self.since: dict[int, float] = {}       # link -> when its current colour class began
        self.step_until = 0.0

    @property
    def active(self) -> bool:
        return self.mode != Mode.NORMAL

    def observe(self, now: float, state: str) -> None:
        """Update link timers from the state SUMO reports. Call before tick()."""
        for i, c in enumerate(state):
            prev = self.state[i]
            if i not in self.since or (c in GREEN) != (prev in GREEN) or (c == "y") != (prev == "y"):
                self.since[i] = now
        self.state = state

    def request(self, plan: ServePlan) -> None:
        """Begin (or redirect) a safe transition to `plan`."""
        self.target = plan
        self.restoring = False
        self.resume_phase = self.info.next_green_phase(plan.phase)
        if self.mode == Mode.SERVING and greens(plan.state) == greens(self.state):
            self._apply(plan.state)             # same greens, at most a g -> G promotion
            return
        if self.mode in (Mode.NORMAL, Mode.SERVING):
            self.mode = Mode.WAIT_MIN_GREEN

    def release(self) -> None:
        """No priority demand left: return to the program through the same safe sequence."""
        if not self.taken:                      # the program was never overridden
            self.mode, self.target = Mode.NORMAL, None
            return
        self.target = ServePlan(self.info.phases[self.resume_phase][0], self.resume_phase)
        self.restoring = True
        if self.mode == Mode.SERVING:
            self.mode = Mode.WAIT_MIN_GREEN

    def _apply(self, state: str) -> None:
        if state != self.state or not self.taken:
            self.io.set_state(self.info.id, state)
            self.state = state
            self.taken = True

    def tick(self, now: float) -> None:
        if self.mode in (Mode.NORMAL, Mode.SERVING) or self.target is None:
            return
        tg = greens(self.target.state)
        if self.mode == Mode.WAIT_MIN_GREEN:
            losing = greens(self.state) - tg
            if any(now - self.since.get(i, -1e9) < MIN_GREEN for i in losing):
                return
            if losing:
                self._apply("".join("y" if i in losing else c for i, c in enumerate(self.state)))
                self.emit("signal_transition", "Yellow on conflicting movements")
                self.mode, self.step_until = Mode.YELLOW, now + YELLOW_TIME
                return
            if "y" in self.state:               # a program yellow is running: freeze it and let it finish
                ages = [now - self.since.get(i, now) for i, c in enumerate(self.state) if c == "y"]
                self._apply(self.state)
                self.mode, self.step_until = Mode.YELLOW, now + max(0.0, YELLOW_TIME - min(ages))
                return
            if tg - greens(self.state):         # gaining greens: links that just went red must clear first
                reds = [now - self.since.get(i, -1e9) for i, c in enumerate(self.state) if c in "rR"]
                wait = ALL_RED_TIME - min(reds, default=1e9)
                if wait > 1e-9:
                    self._apply(self.state)
                    self.mode, self.step_until = Mode.ALL_RED, now + wait
                    return
            self._finish()
            return
        if now + 1e-9 < self.step_until:
            return
        if self.mode == Mode.YELLOW:
            self._apply("".join("r" if c == "y" else c for c in self.state))
            self.emit("signal_transition", "All-red clearance")
            self.mode, self.step_until = Mode.ALL_RED, now + ALL_RED_TIME
        elif self.mode == Mode.ALL_RED:
            # The target may have changed during clearance (an EV cleared, or a new plan
            # arrived), so judge it afresh: links it drops still need their own yellow.
            self.mode = Mode.WAIT_MIN_GREEN
            self.tick(now)

    def _finish(self) -> None:
        assert self.target is not None
        if self.restoring:
            self.io.resume_program(self.info.id, self.info.program_id, self.target.phase)
            self.state = self.target.state
            self.mode, self.target, self.restoring, self.taken = Mode.NORMAL, None, False, False
            self.emit("restored", "Normal signal program restored")
            return
        self._apply(self.target.state)
        self.mode = Mode.SERVING
        self.emit("priority_granted", "Priority green active")
