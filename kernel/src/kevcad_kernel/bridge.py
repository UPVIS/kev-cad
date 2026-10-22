"""stdio-Brücke ``kevcad-mcp``: MCP-Server für Claude Code, der an den Kernel-Server der App weiterleitet (AP6, E9).

Claude Code startet die Brücke über stdio. Sie leitet Werkzeugliste und Aufrufe unverändert (Texte, Bilder, Fehler,
``isError``) an ``http://127.0.0.1:<KEVCAD_PORT>/mcp`` weiter. Läuft Kev CAD beim Start nicht, startet sie die App im
Hintergrund (``open -g -b <KEVCAD_BUNDLE_ID>``) und wartet bis zu ``KEVCAD_START_TIMEOUT`` Sekunden. Fällt die App
später weg, verbindet sie sich beim nächsten Aufruf neu (und startet die App dafür erneut).

Umgebungsvariablen:

| Variable | Standard | Bedeutung |
|---|---|---|
| ``KEVCAD_PORT`` | 47823 | Port des Kernel-Servers |
| ``KEVCAD_BUNDLE_ID`` | de.upvis.kevcad | App, die bei Bedarf gestartet wird |
| ``KEVCAD_APP_PATH`` | ~/Applications/Tools/Kev CAD.app | App, die gestartet wird (nur bei der Standard-Bundle-ID; per Pfad, weil ``open -b`` sonst eine Build-Kopie erwischen kann) |
| ``KEVCAD_LAUNCH_CMD`` | – | eigener Startbefehl (Shell) statt ``open -g``; für Tests |
| ``KEVCAD_START_TIMEOUT`` | 45 | Sekunden, die auf den Kernel-Server gewartet wird |
| ``KEVCAD_LIST_WAIT`` | 10 | so lange wartet ``tools/list`` auf die App, danach kommt die eingebaute Liste |
| ``KEVCAD_LAUNCH_ON_START`` | 1 | 0 = App nicht schon beim Start der Brücke öffnen, erst beim ersten Werkzeugaufruf |
| ``KEVCAD_BRIDGE_DEBUG`` | – | 1 = ausführliches Protokoll auf stderr |
| ``CLAUDE_CODE_SESSION_ID`` | – | von Claude Code gesetzt; geht bei jeder Anfrage im Kopf ``x-claude-code-session-id`` an den Kernel (Sitzungen für den Spiegel, MIRROR.md) |
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

import anyio
import httpx2
from anyio.abc import TaskGroup
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import MCPError
from mcp_types import (
    CONNECTION_CLOSED,
    INVALID_REQUEST,
    CallToolRequestParams,
    CallToolResult,
    Implementation,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)

import kevcad_kernel
from kevcad_kernel.mcp_tools import INSTRUCTIONS, SERVER_NAME, SERVER_TITLE

log = logging.getLogger("kevcad_kernel.bridge")

DEFAULT_PORT = 47823
DEFAULT_BUNDLE_ID = "de.upvis.kevcad"
DEFAULT_APP_PATH = os.path.expanduser("~/Applications/Tools/Kev CAD.app")
HOST = "127.0.0.1"
MAX_EVENT_BYTES = 256 * 1024 * 1024
LESEZEIT_S = 960.0  # Sekunden; über der längsten Wartezeit eines Werkzeugs (900 s)
SESSION_HEADER = "x-claude-code-session-id"

T = TypeVar("T")


@dataclass(frozen=True)
class BridgeConfig:
    port: int = DEFAULT_PORT
    bundle_id: str = DEFAULT_BUNDLE_ID
    launch_cmd: str | None = None
    app_path: str | None = None
    start_timeout: float = 45.0
    list_wait: float = 10.0
    launch_on_start: bool = True
    host: str = HOST
    session_id: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BridgeConfig:
        env = os.environ if env is None else env

        def number(name: str, default: float) -> float:
            try:
                return float(env.get(name, "") or default)
            except ValueError:
                log.warning("%s=%r ist keine Zahl, nehme %s", name, env.get(name), default)
                return default

        return cls(
            port=int(number("KEVCAD_PORT", DEFAULT_PORT)),
            bundle_id=env.get("KEVCAD_BUNDLE_ID") or DEFAULT_BUNDLE_ID,
            launch_cmd=env.get("KEVCAD_LAUNCH_CMD") or None,
            app_path=env.get("KEVCAD_APP_PATH")
            or (DEFAULT_APP_PATH if (env.get("KEVCAD_BUNDLE_ID") or DEFAULT_BUNDLE_ID) == DEFAULT_BUNDLE_ID else None),
            start_timeout=number("KEVCAD_START_TIMEOUT", 45.0),
            list_wait=number("KEVCAD_LIST_WAIT", 10.0),
            launch_on_start=env.get("KEVCAD_LAUNCH_ON_START", "1").strip().lower() not in ("0", "false", "nein", "no"),
            session_id=(env.get("CLAUDE_CODE_SESSION_ID") or "").strip() or None,
        )

    @property
    def headers(self) -> dict[str, str]:
        """Kopfzeilen für jede Anfrage an den Kernel."""
        return {SESSION_HEADER: self.session_id} if self.session_id else {}

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"

    @property
    def launch_argv(self) -> list[str]:
        if self.launch_cmd:
            return ["/bin/sh", "-c", self.launch_cmd]
        if self.app_path and os.path.isdir(self.app_path):
            return ["open", "-g", self.app_path]
        return ["open", "-g", "-b", self.bundle_id]


class Unavailable(Exception):
    """Kev CAD ist nicht erreichbar (Text ist für den Agenten bestimmt)."""


class ConnectionLost(Exception):
    """Die Verbindung zum Kernel-Server ist während eines Aufrufs abgebrochen."""

    def __init__(self, safe_to_retry: bool) -> None:
        super().__init__("Verbindung zu Kev CAD abgebrochen")
        self.safe_to_retry = safe_to_retry


def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for e in exc.exceptions for leaf in _leaves(e)]
    return [exc]


def _never_sent(exc: BaseException | None) -> bool:
    """True, wenn der Abbruch daher kam, dass keine Verbindung zustande kam (Anfrage hat den Server nie erreicht)."""
    return exc is not None and any(isinstance(e, (httpx2.ConnectError, ConnectionRefusedError)) for e in _leaves(exc))


def _session_gone(exc: MCPError) -> bool:
    """404 auf eine alte Sitzung (Kernel neu gestartet): die Anfrage wurde nicht ausgeführt.

    Der Kernel-Server schickt dazu einen JSON-RPC-Fehler „Session not found“, den der Client unverändert weitergibt;
    „Session terminated“ setzt der Client nur ein, wenn die 404-Antwort keinen solchen Fehler enthält.
    """
    message = exc.message.lower()
    return exc.code == INVALID_REQUEST and ("session not found" in message or "session terminated" in message)


def error_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


@dataclass(eq=False)
class _Connection:
    """Eine offene MCP-Sitzung zum Kernel-Server; gehalten von einer eigenen Task."""

    client: Client | None = None
    error: BaseException | None = None
    ready: anyio.Event = field(default_factory=anyio.Event)
    dead: anyio.Event = field(default_factory=anyio.Event)
    close: anyio.Event = field(default_factory=anyio.Event)
    scopes: set[anyio.CancelScope] = field(default_factory=set)

    @property
    def alive(self) -> bool:
        # Eine verworfene Verbindung (close gesetzt) lebt noch, bis ihre Task endet; wiederverwenden darf sie niemand
        return self.client is not None and not self.dead.is_set() and not self.close.is_set()


@dataclass(eq=False)
class _Attempt:
    launch: bool = True
    done: anyio.Event = field(default_factory=anyio.Event)
    conn: _Connection | None = None
    error: Exception | None = None


class Upstream:
    """Verbindung zum Kernel-Server mit App-Start, Warten und Neuverbinden."""

    def __init__(self, cfg: BridgeConfig, tg: TaskGroup) -> None:
        self.cfg = cfg
        self._tg = tg
        self._conn: _Connection | None = None
        self._attempt: _Attempt | None = None

    # Verbindung -----------------------------------------------------------------------------------------------------

    async def get(self, wait_s: float, launch: bool = True) -> _Connection:
        """Offene Verbindung; baut sie bei Bedarf auf. ``launch``: App starten, wenn der Port zu ist."""
        deadline = time.monotonic() + wait_s
        while True:
            conn = self._conn
            if conn is not None and conn.alive:
                return conn
            attempt = self._attempt
            if attempt is None or (attempt.done.is_set() and not (attempt.conn and attempt.conn.alive)):
                attempt = self._attempt = _Attempt(launch=launch)
                self._tg.start_soon(self._run_attempt, attempt)
            with anyio.move_on_after(max(0.0, deadline - time.monotonic())):
                await attempt.done.wait()
            if not attempt.done.is_set():
                raise Unavailable("Kev CAD startet noch – bitte gleich noch einmal versuchen.")
            if attempt.error is not None:
                if launch and not attempt.launch and time.monotonic() < deadline:
                    continue  # lief ohne App-Start; jetzt mit
                raise attempt.error
            assert attempt.conn is not None
            return attempt.conn

    async def warm_up(self, launch: bool) -> None:
        """Beim Start der Brücke verbinden, mit ``launch`` auch die App starten (Fehler nur protokollieren)."""
        try:
            await self.get(self.cfg.start_timeout + 15, launch=launch)
            log.info("mit Kev CAD verbunden (%s)", self.cfg.url)
        except Exception as exc:
            log.log(logging.WARNING if launch else logging.INFO, "%s", exc)

    async def aclose(self, timeout: float = 3.0) -> None:
        conn = self._conn
        if conn is not None and not conn.dead.is_set():
            conn.close.set()
            with anyio.move_on_after(timeout):
                await conn.dead.wait()

    async def drop(self, conn: _Connection) -> None:
        if self._conn is conn:
            self._conn = None
        conn.close.set()

    async def _port_open(self) -> bool:
        try:
            with anyio.fail_after(1.0):
                stream = await anyio.connect_tcp(self.cfg.host, self.cfg.port)
        except (OSError, TimeoutError):
            return False
        await stream.aclose()
        return True

    async def _launch(self) -> None:
        argv = self.cfg.launch_argv
        log.info("Kev CAD läuft nicht, starte: %s", " ".join(argv))

        def run() -> tuple[int, str]:
            # stderr in eine Datei statt Pipe: ein im Hintergrund weiterlaufender Prozess hält sonst die Pipe offen
            with tempfile.TemporaryFile() as errf:
                proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errf,
                                      timeout=30, check=False)
                errf.seek(0)
                return proc.returncode, errf.read().decode("utf-8", "replace").strip()

        try:
            code, err = await anyio.to_thread.run_sync(run)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Unavailable(f"Kev CAD läuft nicht – bitte starten. Der automatische Start ging nicht: {exc}") from exc
        if code != 0:
            raise Unavailable(f"Kev CAD läuft nicht – bitte starten. Der automatische Start "
                              f"({' '.join(argv)}) ist fehlgeschlagen: {err or f'Exit-Code {code}'}")

    async def _run_attempt(self, attempt: _Attempt) -> None:
        try:
            deadline = time.monotonic() + self.cfg.start_timeout
            if not await self._port_open():
                if not attempt.launch:
                    raise Unavailable("Kev CAD läuft nicht – bitte starten.")
                await self._launch()
                while not await self._port_open():
                    if time.monotonic() > deadline:
                        raise Unavailable(f"Kev CAD läuft nicht – bitte starten. Nach dem Start kam binnen "
                                          f"{self.cfg.start_timeout:g} s keine Antwort auf Port {self.cfg.port}.")
                    await anyio.sleep(0.25)
            while True:
                try:
                    conn = await self._open_connection()
                    break
                except Exception as exc:
                    if time.monotonic() > deadline:
                        raise Unavailable(f"Kev CAD läuft nicht – bitte starten. Verbindung zu {self.cfg.url} "
                                          f"nicht möglich: {_describe(exc)}") from exc
                    log.info("Verbindung noch nicht möglich (%s), versuche erneut", _describe(exc))
                    await anyio.sleep(0.5)
            self._conn = conn
            attempt.conn = conn
        except Unavailable as exc:
            attempt.error = exc
        except Exception as exc:  # unerwartet: trotzdem als klare Meldung an den Agenten
            log.exception("Verbindungsaufbau fehlgeschlagen")
            attempt.error = Unavailable(f"Kev CAD läuft nicht – bitte starten ({_describe(exc)}).")
        finally:
            attempt.done.set()

    async def _open_connection(self) -> _Connection:
        conn = _Connection()
        self._tg.start_soon(self._hold, conn)
        await conn.ready.wait()
        if conn.client is None:
            raise conn.error or Unavailable("Verbindung zu Kev CAD nicht möglich")
        return conn

    async def _hold(self, conn: _Connection) -> None:
        """Hält eine MCP-Sitzung offen, bis ``close`` gesetzt wird oder die Verbindung abbricht."""
        try:
            # Bilder reisen als ein SSE-Ereignis; die Vorgabe des Pakets (1 MiB) wäre für große Screenshots zu knapp
            # Eigener HTTP-Client für die Kopfzeile mit der Sitzungskennung. Lesezeit über der längsten erlaubten
            # Wartezeit (run timeout_s, freigabe_anfragen warten_s: bis 900 s); die Vorgabe des Pakets (300 s) riss
            # lange Aufrufe ab (KevCup, 22.10.2026).
            http = create_mcp_http_client(headers=self.cfg.headers,
                                          timeout=httpx2.Timeout(30.0, read=LESEZEIT_S))
            async with http:
                transport = streamable_http_client(self.cfg.url, http_client=http, max_sse_event_size=MAX_EVENT_BYTES)
                client = Client(transport, mode="legacy", cache=None,
                                client_info=Implementation(name="kevcad-mcp", version=kevcad_kernel.__version__))
                async with client:
                    conn.client = client
                    conn.ready.set()
                    await conn.close.wait()
        except Exception as exc:
            conn.error = exc
            if conn.ready.is_set():
                log.warning("Verbindung zu Kev CAD abgebrochen: %s", _describe(exc))
        finally:
            conn.dead.set()
            conn.ready.set()
            for scope in list(conn.scopes):
                scope.cancel()
            if self._conn is conn:
                self._conn = None

    # Aufrufe ----------------------------------------------------------------------------------------------------------

    async def _guarded(self, conn: _Connection, fn: Callable[[Client], Awaitable[T]]) -> T:
        """Führt einen Aufruf aus und bricht ihn ab, sobald die Verbindung stirbt (statt ewig zu warten)."""
        assert conn.client is not None
        client = conn.client
        with anyio.CancelScope() as scope:
            conn.scopes.add(scope)
            try:
                if conn.dead.is_set():
                    scope.cancel()
                try:
                    return await fn(client)
                except MCPError as exc:
                    if exc.code != CONNECTION_CLOSED:
                        raise
                    with anyio.move_on_after(1.0):
                        await conn.dead.wait()
            finally:
                conn.scopes.discard(scope)
        raise ConnectionLost(safe_to_retry=_never_sent(conn.error))

    async def call(self, fn: Callable[[Client], Awaitable[T]], wait_s: float, launch: bool = True) -> T:
        """Aufruf mit höchstens einer Wiederholung, wenn er den Server sicher nicht erreicht hat."""
        for attempt in range(2):
            conn = await self.get(wait_s, launch=launch)
            try:
                return await self._guarded(conn, fn)
            except MCPError as exc:
                if attempt == 0 and _session_gone(exc):
                    log.info("alte Sitzung abgelaufen (Kernel neu gestartet), verbinde neu")
                    await self.drop(conn)
                    continue
                raise
            except ConnectionLost as lost:
                await self.drop(conn)
                if attempt == 0 and lost.safe_to_retry:
                    log.info("Kev CAD war nicht erreichbar, verbinde neu")
                    continue
                raise
        raise Unavailable("Kev CAD läuft nicht – bitte starten.")


def _describe(exc: BaseException) -> str:
    leaves = _leaves(exc)
    leaf = leaves[0] if leaves else exc
    return f"{type(leaf).__name__}: {leaf}" if str(leaf) else type(leaf).__name__


class _OfflineService:
    """Nur zum Bauen der eingebauten Werkzeugliste; wird nie aufgerufen."""

    def set_agent_activity(self, text: str | None) -> None:
        pass

    def set_agent_connected(self, connected: bool) -> None:
        pass

    def set_agent_sessions(self, sessions: list[dict[str, Any]]) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        raise Unavailable("Kev CAD läuft nicht – bitte starten.")


async def builtin_tools() -> ListToolsResult:
    """Werkzeugliste aus demselben Code wie der Kernel-Server, falls die App (noch) nicht erreichbar ist."""
    from kevcad_kernel.server import build_server

    mcp = build_server(_OfflineService())  # type: ignore[arg-type]
    return ListToolsResult(tools=await mcp.list_tools())


class Bridge:
    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg
        self.upstream: Upstream | None = None
        self._builtin: ListToolsResult | None = None

    def build_server(self) -> Server[Any]:
        return Server(
            SERVER_NAME,
            version=kevcad_kernel.__version__,
            title=SERVER_TITLE,
            instructions=INSTRUCTIONS,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    async def _list_tools(self, ctx: Any, params: PaginatedRequestParams | None) -> ListToolsResult:
        assert self.upstream is not None
        cursor = params.cursor if params is not None else None
        try:
            return await self.upstream.call(lambda c: c.list_tools(cursor=cursor), wait_s=self.cfg.list_wait,
                                            launch=self.cfg.launch_on_start)
        except (Unavailable, ConnectionLost) as exc:
            log.info("Werkzeugliste aus der Brücke (%s)", exc)
            if self._builtin is None:
                self._builtin = await builtin_tools()
            return self._builtin

    async def _call_tool(self, ctx: Any, params: CallToolRequestParams) -> CallToolResult:
        assert self.upstream is not None
        name, arguments = params.name, params.arguments or {}
        try:
            return await self.upstream.call(lambda c: c.call_tool(name, arguments),
                                            wait_s=self.cfg.start_timeout + 15)
        except Unavailable as exc:
            return error_result(str(exc))
        except ConnectionLost:
            return error_result("Die Verbindung zu Kev CAD ist während des Aufrufs abgebrochen, das Ergebnis ist "
                                "unbekannt. Beim nächsten Aufruf verbinde ich neu und starte die App, falls nötig.")

    async def run(self) -> None:
        async with anyio.create_task_group() as tg:
            self.upstream = Upstream(self.cfg, tg)
            server = self.build_server()
            async with stdio_server() as (read_stream, write_stream):
                tg.start_soon(self.upstream.warm_up, self.cfg.launch_on_start)
                await server.run(read_stream, write_stream, server.create_initialization_options())
            await self.upstream.aclose()
            tg.cancel_scope.cancel()


def main() -> int:
    debug = os.environ.get("KEVCAD_BRIDGE_DEBUG") == "1"
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, stream=sys.stderr,
                        format="kevcad-mcp %(levelname)s %(name)s: %(message)s")
    if debug:
        logging.getLogger("kevcad_kernel").setLevel(logging.DEBUG)
    else:
        # Abbrüche meldet die Brücke selbst verständlich; die Tracebacks des Pakets nur im Debug-Modus
        for noisy in ("httpx", "httpx2", "httpcore", "mcp"):
            logging.getLogger(noisy).setLevel(logging.CRITICAL)
    cfg = BridgeConfig.from_env()
    try:
        anyio.run(Bridge(cfg).run)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
