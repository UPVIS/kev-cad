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
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anyio

log = logging.getLogger(__name__)

SESSION_HEADER = b"mcp-session-id"


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
                 on_session: Callable[[str], None] | None = None) -> None:
        self._notify = notify
        self._on_session = on_session  # Versionen: Sitzung, die gerade ein Werkzeug aufruft (für „Wer“)
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

    async def _push(self) -> None:
        if self._push_lock is None:
            self._push_lock = anyio.Lock()
        async with self._push_lock:
            self._expire()
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
        is_get = method == "GET"
        session = self._sessions.get(sid) if sid else None
        stateless = sid is None and method == "POST"

        if session is not None and not is_get and self._on_session is not None:
            try:
                self._on_session(sid)
            except Exception:  # Anzeige darf nie eine Anfrage scheitern lassen
                log.exception("Sitzung nicht gemeldet")
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
                log.info("MCP-Sitzung %s geöffnet", new_sid[:8])
            elif stateless and code is not None and code < 400:
                self._stateless_seen = now
            if sid is not None and (method == "DELETE" or code == 404):
                if self._sessions.pop(sid, None) is not None:
                    log.info("MCP-Sitzung %s beendet", sid[:8])
            with anyio.CancelScope(shield=True):
                await self._push()
