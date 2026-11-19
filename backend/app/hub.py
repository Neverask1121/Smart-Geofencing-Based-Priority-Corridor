"""WebSocket fan-out.

Each client has its own bounded queue. When a client falls behind, its queue is dropped
and it gets one full snapshot instead, so a slow browser never holds up the simulation
and never sees a gap in the incremental stream.
"""
from __future__ import annotations

import asyncio

QUEUE_FRAMES = 12


class Client:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=QUEUE_FRAMES)
        self.need_full = True
        self.dropped = 0


class Hub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[Client] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def add(self) -> Client:
        c = Client()
        self.clients.add(c)
        return c

    def remove(self, c: Client) -> None:
        self.clients.discard(c)

    @property
    def needs_full(self) -> bool:
        return any(c.need_full for c in self.clients)

    def request_full(self) -> None:
        """Every client must replace its state, for example after a reset."""
        for c in list(self.clients):
            c.need_full = True

    def publish(self, frame: bytes | None, full: bytes | None) -> None:
        """Thread-safe. Called from the engine thread and never blocks it."""
        if self.loop is not None and self.clients:
            self.loop.call_soon_threadsafe(self._fan_out, frame, full)

    def _fan_out(self, frame: bytes | None, full: bytes | None) -> None:
        for c in self.clients:
            if c.need_full:
                if full is not None:
                    self._drain(c)
                    c.queue.put_nowait(full)
                    c.need_full = False
                continue
            if frame is None:
                continue
            try:
                c.queue.put_nowait(frame)
            except asyncio.QueueFull:
                self._drain(c)
                c.dropped += 1
                c.need_full = True

    @staticmethod
    def _drain(c: Client) -> None:
        while not c.queue.empty():
            c.queue.get_nowait()
