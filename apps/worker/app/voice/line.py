"""One phone line for the whole Mini, with callers waiting their turn.

The Mini transcribes one answer at a time, so it takes `capacity` browser
calls at once (default 1) and queues everyone else first-in, first-out
across every tenant and script. In-memory on purpose: there is exactly one
worker process (`uvicorn --workers 1`), and a restart ends every call anyway.

A call frees the line when it finishes, when the caller hangs up or closes
the page, or when its page stops talking to us for `idle_seconds` (a closed
laptop). A waiting caller whose page stops polling loses their place.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Ticket:
    id: str
    link: str
    language: str | None
    joined: float
    seen: float


@dataclass
class CallLine:
    capacity: int = 1
    idle_seconds: float = 90.0
    wait_idle_seconds: float = 30.0
    clock: Callable[[], float] = time.monotonic
    active: dict[str, float] = field(default_factory=dict)  # call_id -> last activity
    waiting: "OrderedDict[str, Ticket]" = field(default_factory=OrderedDict)

    def _expire(self) -> None:
        now = self.clock()
        for call_id, seen in list(self.active.items()):
            if now - seen > self.idle_seconds:
                del self.active[call_id]
        for ticket_id, ticket in list(self.waiting.items()):
            if now - ticket.seen > self.wait_idle_seconds:
                del self.waiting[ticket_id]

    def free(self) -> bool:
        self._expire()
        return len(self.active) < self.capacity

    def can_start_now(self) -> bool:
        """A new caller connects only if nobody is ahead of them."""
        return self.free() and not self.waiting

    def join(self, link: str, language: str | None) -> Ticket:
        now = self.clock()
        ticket = Ticket("tk_" + secrets.token_urlsafe(12), link, language, now, now)
        self.waiting[ticket.id] = ticket
        return ticket

    def position(self, ticket_id: str) -> int | None:
        """1 = next in line. None = not waiting (expired, left, or unknown)."""
        self._expire()
        for index, key in enumerate(self.waiting):
            if key == ticket_id:
                self.waiting[key].seen = self.clock()
                return index + 1
        return None

    def take_turn(self, ticket_id: str) -> Ticket | None:
        """The head of the line gets the free slot; anyone else keeps waiting."""
        if self.position(ticket_id) != 1 or not self.free():
            return None
        return self.waiting.pop(ticket_id)

    def leave(self, ticket_id: str) -> None:
        self.waiting.pop(ticket_id, None)

    def started(self, call_id: str) -> None:
        self.active[call_id] = self.clock()

    def touch(self, call_id: str) -> None:
        if call_id in self.active:
            self.active[call_id] = self.clock()

    def ended(self, call_id: str) -> None:
        self.active.pop(call_id, None)

    def snapshot(self) -> dict[str, int]:
        self._expire()
        return {"capacity": self.capacity, "active": len(self.active), "waiting": len(self.waiting)}
