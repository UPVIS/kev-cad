"""Hilfen für die MCP-Tests: Server mit Attrappe im Thread, Client-Aufrufe, Warten auf Bedingungen."""

from __future__ import annotations

import socket
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from fake_service import FakeService
from mcp import Client

from kevcad_kernel.server import KevcadHTTPServer

T = TypeVar("T")

TESTS = Path(__file__).resolve().parent
FAKE_KERNEL = TESTS / "fake_kernel.py"
BRIDGE_EXE = Path(sys.executable).parent / "kevcad-mcp"

EXPECTED_TOOLS = {
    "status", "project_open", "project_new", "run", "model_read", "model_write", "execute", "parts", "view", "focus",
    "visibility", "highlight", "section", "screenshot", "selection", "measure", "annotate", "clear_annotations",
    "export", "stock_search", "stock_get", "stock_define", "material_list", "material_define", "catalog_delete", "bom",
    "bestand_liste", "bestand_eintragen", "einkaufsliste", "gebaut_buchen", "buchung_rueckgaengig",
    "zukauf_anlegen", "zukauf_html", "cad_suchen", "cad_uebernehmen", "zukauf_liste",
    "bedingungen",
    # Phase 5: Animation
    "animation_liste", "animation_abspielen", "animation_springen", "animation_video", "kollision_pruefen",
}
# Phase 5: Kameras
EXPECTED_TOOLS |= {"kamera_liste", "kamera_info", "kamera_ansicht", "kamera_bild", "kamera_katalog",
                   "kamera_vorschlag_aus_ansicht"}


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


async def with_client(url: str, fn: Callable[[Client], Awaitable[T]], mode: str = "legacy") -> T:
    async with Client(url, mode=mode, cache=None) as client:
        return await fn(client)


def wait_for(cond: Callable[[], bool], timeout: float = 5.0, step: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(step)
    return cond()


def texts(result: Any) -> list[str]:
    return [b.text for b in result.content if getattr(b, "type", None) == "text"]
