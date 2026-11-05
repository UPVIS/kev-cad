"""Hilfen für die MCP-Tests: Server mit Attrappe im Thread, Client-Aufrufe, Warten auf Bedingungen."""

from __future__ import annotations

import socket
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from fake_service import FakeService
from kevcad_kernel.server import KevcadHTTPServer
from mcp import Client

T = TypeVar("T")

TESTS = Path(__file__).resolve().parent
FAKE_KERNEL = TESTS / "fake_kernel.py"
BRIDGE_EXE = Path(sys.executable).parent / "kevcad-mcp"

# V2-2: Kernsatz und je Fachbereich ein Werkzeug mit aktion (die 95 bisherigen Werkzeuge sind Griffe dahinter)
EXPECTED_TOOLS = {
    "status", "projekt", "modell", "run", "execute", "parts", "measure", "view", "pruefen", "ansichten", "katalog",
    "export", "feedback",
    "lager", "bestand", "druck", "statik", "topologie", "zeichnung", "bauplan", "referenz", "kamera", "animation",
    "versionen", "render",
}


class AltClient:
    """Client, der auch die bisherigen Werkzeugnamen versteht (Zuordnung aus kevcad_kernel.mcp_tools.zuordnung).
    Fachwerkzeuge bekommen dabei daten=true, damit das Ergebnis wie früher den JSON-Block trägt; neue Namen gehen
    unverändert durch. So prüfen die Tests der Fachlogik zugleich, dass jede alte Funktion erreichbar bleibt."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def call_tool(self, name: str, arguments: dict | None = None, *args: Any, **kwargs: Any) -> Any:
        from kevcad_kernel.mcp_tools.zuordnung import fach_eintraege, uebersetzen

        neu, argumente = uebersetzen(name, arguments or {})
        if name in fach_eintraege():
            argumente = {"daten": True, **argumente}
        return await self._client.call_tool(neu, argumente, *args, **kwargs)


def griff_werkzeuge(server: KevcadHTTPServer) -> dict[str, Any]:
    """Die bisherigen Werkzeuge (Griffe hinter Kernsatz und Fachwerkzeugen) mit Beschreibung und Schema, für Tests der
    Schemas: {name: Objekt mit description, input_schema}."""
    from types import SimpleNamespace

    griffe = server.mcp.kevcad_tools.griffe
    return {n: SimpleNamespace(name=n, description=griffe[n].beschreibung, input_schema=griffe[n].werkzeug.parameters,
                               annotations=griffe[n].annotations) for n in griffe.namen()}


def free_port() -> int:
    """Freier Port für Tests (nie 47823/47824)."""
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in (47823, 47824):
            return port


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def start_server(fake: FakeService | None = None, **tracker_options: Any) -> tuple[KevcadHTTPServer, FakeService]:
    fake = fake or FakeService()
    server = KevcadHTTPServer(fake, 0, tracker_options=tracker_options or None)
    server.start_in_thread()
    return server, fake


async def with_client(url: str, fn: Callable[[Client], Awaitable[T]], mode: str = "legacy", alt: bool = True) -> T:
    """Client gegen ``url``; mit ``alt`` (Vorgabe) versteht er auch die bisherigen Werkzeugnamen (AltClient)."""
    async with Client(url, mode=mode, cache=None) as client:
        return await fn(AltClient(client) if alt else client)


def wait_for(cond: Callable[[], bool], timeout: float = 5.0, step: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(step)
    return cond()


def texts(result: Any) -> list[str]:
    return [b.text for b in result.content if getattr(b, "type", None) == "text"]
