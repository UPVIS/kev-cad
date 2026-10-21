"""Zeigt in der App, ob ein Agent verbunden ist und was er gerade tut.

``ActivityTracker`` setzt vor jedem Werkzeug eine deutsche Kurzbeschreibung (``set_agent_activity``) und löscht sie
danach wieder. Laufen mehrere Werkzeuge gleichzeitig, bleibt die jüngste noch laufende Tätigkeit stehen.

``AgentTracker`` sitzt als ASGI-Hülle vor dem Streamable-HTTP-Endpunkt und leitet aus dem HTTP-Verkehr ab, ob ein
MCP-Client verbunden ist (``set_agent_connected``). Er nutzt nur das, was das Protokoll offenlegt:

- Sitzungen (Protokollversionen mit ``initialize``): Die Antwort auf ``initialize`` trägt die neue Sitzungskennung im
  Kopf ``mcp-session-id``; ``DELETE`` oder eine 404-Antwort beendet sie. Solange der Client seinen GET-Strom offen hält,
  lebt die Sitzung sicher. Endet der GET-Strom (Client beendet oder abgestürzt) und meldet sich der Client nicht
  binnen ``grace_s`` wieder, gilt die Sitzung als beendet. Sitzungen ganz ohne GET-Strom enden nach ``idle_s``.
- Zustandslose Anfragen (Protokoll 2026-07-28 ohne Sitzung): verbunden, solange die letzte Anfrage weniger als
  ``stateless_s`` zurückliegt.

``SessionBoard`` führt die Claude-Sitzungen, die Kev CAD bedienen (MIRROR.md, „Sitzungen“). Die Brücke ``kevcad-mcp``
schickt ihre ``CLAUDE_CODE_SESSION_ID`` bei jeder Anfrage im Kopf ``x-claude-code-session-id``; ``AgentTracker`` legt
sie für die Dauer der Anfrage in die Kontextvariable ``claude_session`` (die Werkzeuge laufen im Kontext der Anfrage)
und weiß, welche Sitzungen noch verbunden sind. Je Sitzung zählen der letzte verändernde Werkzeugaufruf (alles außer
nur lesenden Werkzeugen) und die Tätigkeit; aktiv ist genau die Sitzung mit dem letzten verändernden Aufruf der
letzten 10 Minuten.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import anyio

log = logging.getLogger(__name__)

SESSION_HEADER = b"mcp-session-id"
CLAUDE_SESSION_HEADER = b"x-claude-code-session-id"
ACTIVE_WINDOW_S = 10 * 60

# Claude-Sitzung der laufenden Anfrage (aus dem Kopf der Brücke), sonst None
claude_session: contextvars.ContextVar[str | None] = contextvars.ContextVar("kevcad_claude_session", default=None)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _ClaudeSession:
    first_seen: float  # Wanduhr
    last_mutation: float | None = None  # monotonic
    last_mutation_wall: float | None = None
    activity: str | None = None


class SessionBoard:
    """Claude-Sitzungen mit Tätigkeit und letztem verändernden Aufruf; meldet die Liste bei jeder Änderung.

    ``push`` bekommt die Liste wie ``agents`` in MIRROR.md: ``session_id``, ``aktiv``, ``seit``, ``taetigkeit`` und
    optional ``zuletzt``; die aktive Sitzung steht vorn. Threadsicher.
    """

    def __init__(self, push: Callable[[list[dict[str, Any]]], None] | None = None, *,
                 active_window_s: float = ACTIVE_WINDOW_S, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._push = push
        self.active_window_s = active_window_s
        self._clock = clock
        self._wall = wall
        self._lock = threading.RLock()
        self._sessions: dict[str, _ClaudeSession] = {}
        self._running: dict[int, tuple[str, str]] = {}  # Token → (Sitzung, Tätigkeit)
        self._next = 0
        self._pushed: list[dict[str, Any]] | None = None

    def seen(self, session: str) -> None:
        with self._lock:
            if session not in self._sessions:
                self._sessions[session] = _ClaudeSession(first_seen=self._wall())

    def tool_called(self, session: str | None, mutating: bool) -> None:
        """Vor jedem Werkzeugaufruf: Sitzung merken, verändernde Aufrufe zählen für ``aktiv``."""
        if not session:
            return
        with self._lock:
            self.seen(session)
            if mutating:
                s = self._sessions[session]
                s.last_mutation = self._clock()
                s.last_mutation_wall = self._wall()
        self.refresh()

    def activity_begin(self, session: str | None, text: str) -> int | None:
        if not session:
            return None
        with self._lock:
            self.seen(session)
            self._next += 1
            self._running[self._next] = (session, text)
            self._sessions[session].activity = text
            token = self._next
        self.refresh()
        return token

    def activity_end(self, token: int | None) -> None:
        """Die Tätigkeit bleibt als „zuletzt getan“ stehen, bis die Sitzung etwas Neues beginnt."""
        if token is None:
            return
        with self._lock:
            self._running.pop(token, None)

    def set_alive(self, alive: set[str]) -> None:
        """Vom Tracker: welche Sitzungen noch eine Verbindung haben; die anderen fallen aus der Liste."""
        with self._lock:
            for sid in [sid for sid in self._sessions if sid not in alive]:
                del self._sessions[sid]
        self.refresh()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            now = self._clock()
            recent = [(s.last_mutation, sid) for sid, s in self._sessions.items()
                      if s.last_mutation is not None and now - s.last_mutation < self.active_window_s]
            active = max(recent)[1] if recent else None
            out = []
            for sid, s in self._sessions.items():
                d: dict[str, Any] = {"session_id": sid, "aktiv": sid == active, "seit": _iso(s.first_seen),
                                     "taetigkeit": s.activity}
                if s.last_mutation_wall is not None:
                    d["zuletzt"] = _iso(s.last_mutation_wall)
                out.append(d)
            out.sort(key=lambda d: (not d["aktiv"], d["seit"], d["session_id"]))
            return out

    def refresh(self) -> None:
        """Liste neu bilden und nur bei einer Änderung melden (auch das Ende von „aktiv“ nach 10 Minuten)."""
        with self._lock:
            snap = self.snapshot()
            if snap == self._pushed:
                return
            self._pushed = snap
            push = self._push
        if push is not None:
            try:
                push(snap)
            except Exception:  # Anzeige darf nie ein Werkzeug scheitern lassen
                log.exception("set_agent_sessions fehlgeschlagen")


class ActivityTracker:
    """Verwaltet die Tätigkeitsanzeige über ``set_agent_activity``; threadsicher."""

    def __init__(self, setter: Callable[[str | None], None]) -> None:
        self._setter = setter
        self._lock = threading.Lock()
        self._active: dict[int, str] = {}
        self._next = 0

    def begin(self, text: str) -> int:
        with self._lock:
            self._next += 1
            token = self._next
            self._active[token] = text
            self._push(text)
            return token

    def end(self, token: int) -> None:
        with self._lock:
            self._active.pop(token, None)
            latest = self._active[max(self._active)] if self._active else None
            self._push(latest)

    def _push(self, text: str | None) -> None:
        try:
            self._setter(text)
        except Exception:  # Anzeige darf nie ein Werkzeug scheitern lassen
            log.exception("set_agent_activity fehlgeschlagen")


@dataclass
class _Session:
    open_requests: int = 0
    open_streams: int = 0  # offene GET-Ströme
    had_stream: bool = False
    last_seen: float = field(default_factory=time.monotonic)


class AgentTracker:
    """ASGI-Hülle, die Verbindungsaufbau und -ende von MCP-Clients erkennt und an die Laufzeit meldet."""

    def __init__(self, notify: Callable[[bool], None], *, path: str = "/mcp", grace_s: float = 5.0,
                 idle_s: float = 30 * 60, stateless_s: float = 10 * 60, poll_s: float = 1.0,
                 board: SessionBoard | None = None) -> None:
        self._notify = notify
        self.board = board
        self._claude_of: dict[str, str] = {}  # MCP-Sitzung → Claude-Sitzung
        self._claude_stateless: dict[str, float] = {}  # Claude-Sitzung ohne MCP-Sitzung → zuletzt gesehen
        self._path = path.rstrip("/") or "/"
        self.grace_s = grace_s
        self.idle_s = idle_s
        self.stateless_s = stateless_s
        self.poll_s = poll_s
        self._sessions: dict[str, _Session] = {}
        self._stateless_open = 0
        self._stateless_seen: float | None = None
        self._pushed = False  # die Laufzeit startet mit "kein Agent"; gemeldet werden nur Änderungen
        self._push_lock: anyio.Lock | None = None

    # Zustand ---------------------------------------------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        now = time.monotonic()
        for s in self._sessions.values():
            if self._alive(s, now):
                return True
        if self._stateless_open > 0:
            return True
        return self._stateless_seen is not None and now - self._stateless_seen < self.stateless_s

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def _alive(self, s: _Session, now: float) -> bool:
        if s.open_requests > 0 or s.open_streams > 0:
            return True
        limit = self.grace_s if s.had_stream else self.idle_s
        return now - s.last_seen < limit

    def _expire(self) -> None:
        now = time.monotonic()
        for sid in [sid for sid, s in self._sessions.items() if not self._alive(s, now)]:
            log.info("MCP-Sitzung %s beendet (keine Verbindung mehr)", sid[:8])
            del self._sessions[sid]
            self._claude_of.pop(sid, None)
        for cid in [cid for cid, seen in self._claude_stateless.items() if now - seen >= self.stateless_s]:
            del self._claude_stateless[cid]

    def alive_claude_sessions(self) -> set[str]:
        """Claude-Sitzungen, deren MCP-Sitzung (bzw. zustandslose Anfragen) noch leben."""
        alive = {cid for sid, cid in self._claude_of.items() if sid in self._sessions}
        return alive | set(self._claude_stateless)

    async def _push(self) -> None:
        if self._push_lock is None:
            self._push_lock = anyio.Lock()
        async with self._push_lock:
            self._expire()
            if self.board is not None:
                self.board.set_alive(self.alive_claude_sessions())
            value = self.connected
            if value == self._pushed:
                return
            self._pushed = value
            log.info("Agent %s", "verbunden" if value else "getrennt")
            try:
                await anyio.to_thread.run_sync(self._notify, value)
            except Exception:
                log.exception("set_agent_connected fehlgeschlagen")

    async def watch(self) -> None:
        """Prüft regelmäßig, ob Sitzungen abgelaufen sind. Läuft neben dem HTTP-Server."""
        while True:
            await anyio.sleep(self.poll_s)
            await self._push()

    # ASGI ------------------------------------------------------------------------------------------------------------

    def wrap(self, app: Any) -> Callable[..., Any]:
        async def asgi(scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
            if scope.get("type") != "http" or (scope.get("path", "").rstrip("/") or "/") != self._path:
                await app(scope, receive, send)
                return
            await self._handle(app, scope, receive, send)

        return asgi

    async def _handle(self, app: Any, scope: dict[str, Any], receive: Callable[..., Any],
                      send: Callable[..., Any]) -> None:
        method = scope.get("method", "")
        headers = dict(scope.get("headers") or [])
        sid_raw = headers.get(SESSION_HEADER)
        sid = sid_raw.decode("latin-1") if sid_raw else None
        claude_raw = headers.get(CLAUDE_SESSION_HEADER)
        claude = claude_raw.decode("latin-1").strip()[:128] if claude_raw else None
        token = claude_session.set(claude or None)
        if claude:
            if sid:
                self._claude_of[sid] = claude
            elif method == "POST":
                self._claude_stateless[claude] = time.monotonic()
        is_get = method == "GET"
        session = self._sessions.get(sid) if sid else None
        stateless = sid is None and method == "POST"

        if session is not None:
            session.last_seen = time.monotonic()
            if is_get:
                session.open_streams += 1
                session.had_stream = True
            else:
                session.open_requests += 1
        elif stateless:
            self._stateless_open += 1
        status: dict[str, Any] = {}

        async def watch_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status")
                for key, value in message.get("headers") or []:
                    if key.lower() == SESSION_HEADER:
                        status["new_sid"] = value.decode("latin-1")
            await send(message)

        try:
            await app(scope, receive, watch_send)
        finally:
            claude_session.reset(token)
            now = time.monotonic()
            if session is not None:
                session.last_seen = now
                if is_get:
                    session.open_streams = max(0, session.open_streams - 1)
                else:
                    session.open_requests = max(0, session.open_requests - 1)
            elif stateless:
                self._stateless_open = max(0, self._stateless_open - 1)
            code = status.get("code")
            new_sid = status.get("new_sid")
            if sid is None and new_sid and code is not None and code < 400 and new_sid not in self._sessions:
                # Antwort auf initialize: neue Sitzung
                self._sessions[new_sid] = _Session(last_seen=now)
                if claude:
                    self._claude_of[new_sid] = claude
                    self._claude_stateless.pop(claude, None)
                log.info("MCP-Sitzung %s geöffnet", new_sid[:8])
            elif stateless and code is not None and code < 400:
                self._stateless_seen = now
            if sid is not None and (method == "DELETE" or code == 404):
                self._claude_of.pop(sid, None)
                if self._sessions.pop(sid, None) is not None:
                    log.info("MCP-Sitzung %s beendet", sid[:8])
            with anyio.CancelScope(shield=True):
                await self._push()
