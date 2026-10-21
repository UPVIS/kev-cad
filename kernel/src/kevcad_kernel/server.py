"""Kernel-Server von Kev CAD: startet die Laufzeit und bietet MCP über Streamable HTTP an (AP6, Entscheidung E9).

``serve(socket_path, port)`` ist der Einstieg aus ``kevcad-kernel serve``: Laufzeit über ``create_service`` starten,
MCP-Server „kevcad“ auf ``http://127.0.0.1:<port>/mcp`` betreiben, bei SIGTERM/SIGINT sauber beenden.

``build_server(service)`` und ``KevcadHTTPServer`` bauen denselben Server mit einem beliebigen ``KernelService``
(z. B. einer Attrappe in Tests).
"""

from __future__ import annotations

import logging
import signal
import socket
import sys
import threading
import time
from typing import Any

import anyio
import uvicorn
from mcp.server.mcpserver import MCPServer

import kevcad_kernel
from kevcad_kernel.mcp_tools import INSTRUCTIONS, SERVER_NAME, SERVER_TITLE, register_tools
from kevcad_kernel.mcp_tools.tracking import AgentTracker, SessionBoard
from kevcad_kernel.service import KernelService, create_service

log = logging.getLogger("kevcad_kernel.server")

HOST = "127.0.0.1"
MCP_PATH = "/mcp"


def build_server(service: KernelService, board: SessionBoard | None = None) -> MCPServer:
    """MCP-Server „kevcad“ mit allen Werkzeugen, gebunden an ``service`` (``board``: Claude-Sitzungen)."""
    mcp: MCPServer = MCPServer(
        SERVER_NAME,
        title=SERVER_TITLE,
        instructions=INSTRUCTIONS,
        version=kevcad_kernel.__version__,
        log_level="WARNING",
        subscriptions=False,
    )
    register_tools(mcp, service, board)
    return mcp


def bind_socket(host: str, port: int) -> socket.socket:
    """Bindet den TCP-Port vorab, damit ein belegter Port sofort und eindeutig auffällt (Port 0 = frei wählen)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


class KevcadHTTPServer:
    """MCP über Streamable HTTP mit uvicorn, dazu die Erkennung verbundener Agenten."""

    def __init__(self, service: KernelService, port: int = 0, host: str = HOST, *, sock: socket.socket | None = None,
                 log_level: str = "warning", tracker_options: dict[str, Any] | None = None) -> None:
        self.service = service
        self.host = host
        # Claude-Sitzungen (MIRROR.md): Werkzeuge melden Aufrufe, der Tracker meldet, welche noch verbunden sind
        self.board = SessionBoard(getattr(service, "set_agent_sessions", None))
        self.mcp = build_server(service, self.board)
        self.tracker = AgentTracker(service.set_agent_connected, path=MCP_PATH, board=self.board,
                                    **(tracker_options or {}))
        # JSON-Antworten statt SSE: Werkzeugergebnisse kommen als ein Stück. So stoßen große Bilder nicht an
        # Größengrenzen für SSE-Ereignisse in Clients (das Python-Paket erlaubt dort nur 1 MiB).
        app = self.mcp.streamable_http_app(host=host, streamable_http_path=MCP_PATH, json_response=True,
                                           session_idle_timeout=self.tracker.idle_s)
        self.app = self.tracker.wrap(app)
        self.sock = sock if sock is not None else bind_socket(host, port)
        self.port: int = self.sock.getsockname()[1]
        config = uvicorn.Config(self.app, host=host, port=self.port, log_level=log_level, log_config=None,
                                access_log=False, lifespan="on", timeout_graceful_shutdown=3)
        self.uvicorn = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{MCP_PATH}"

    @property
    def started(self) -> bool:
        return bool(self.uvicorn.started)

    async def serve(self) -> None:
        """Blockiert, bis ``stop()`` aufgerufen wird oder (im Hauptthread) SIGTERM/SIGINT kommt."""
        async with anyio.create_task_group() as tg:
            tg.start_soon(self.tracker.watch)
            try:
                await self.uvicorn.serve(sockets=[self.sock])
            finally:
                tg.cancel_scope.cancel()

    def stop(self) -> None:
        self.uvicorn.should_exit = True

    # Für Tests und Werkzeuge: Server in einem eigenen Thread mit eigener Ereignisschleife

    def start_in_thread(self, timeout: float = 15.0) -> KevcadHTTPServer:
        self._thread = threading.Thread(target=anyio.run, args=(self.serve,), name="kevcad-mcp-http", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self.started:
            if not self._thread.is_alive():
                raise RuntimeError("MCP-Server ist beim Start beendet worden")
            if time.monotonic() > deadline:
                raise TimeoutError("MCP-Server ist nicht rechtzeitig gestartet")
            time.sleep(0.02)
        return self

    def stop_thread(self, timeout: float = 10.0) -> None:
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout)


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "mcp.server.streamable_http", "mcp.server.streamable_http_manager"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _raise_exit(signum: int, frame: Any) -> None:
    raise SystemExit(0)


def _is_shutdown(exc: BaseException) -> bool:
    """SIGTERM/SIGINT kommen als SystemExit bzw. KeyboardInterrupt an, je nach Lage auch in einer Ausnahmegruppe."""
    if isinstance(exc, (SystemExit, KeyboardInterrupt)):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_shutdown(e) for e in exc.exceptions)
    return False


def serve(socket_path: str, port: int) -> int:
    """Startet Laufzeit und MCP-Server und blockiert bis SIGTERM/SIGINT. Rückgabe: Exit-Code."""
    _setup_logging()
    try:
        sock = bind_socket(HOST, port)
    except OSError as exc:
        log.error("Port %s auf %s ist nicht verfügbar (%s). Läuft Kev CAD schon?", port, HOST, exc)
        return 2

    # uvicorn fängt SIGTERM/SIGINT während des Betriebs selbst ab, fährt sauber herunter und löst das Signal danach
    # erneut aus. Dieser Handler macht daraus SystemExit, damit die Laufzeit unten in jedem Fall geschlossen wird,
    # auch wenn das Signal schon während des Starts kommt.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _raise_exit)
    service: KernelService | None = None
    code = 0
    try:
        service = create_service(socket_path, port)
        server = KevcadHTTPServer(service, port, sock=sock, log_level="info")
        log.info("MCP-Server startet auf %s", server.url)
        anyio.run(server.serve)
    except BaseException as exc:
        if not _is_shutdown(exc):
            log.exception("Kernel-Server abgebrochen")
            code = 1
    finally:
        sock.close()
        if service is not None:
            try:
                service.close()
            except Exception:
                log.exception("Laufzeit ließ sich nicht sauber schließen")
        log.info("Kernel-Server beendet")
    return code
