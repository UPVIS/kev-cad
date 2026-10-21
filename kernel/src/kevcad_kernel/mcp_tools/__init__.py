"""MCP-Werkzeuge von Kev CAD (AP6): Werkzeuge, Ergebnisformat, Anweisungen, Verbindungs- und Tätigkeitsanzeige."""

from __future__ import annotations

from .instructions import INSTRUCTIONS, SERVER_NAME, SERVER_TITLE
from .tools import KevcadTools, register_tools

TOOL_NAMES: tuple[str, ...] = (
    "status",
    "project_open",
    "project_new",
    "run",
    "model_read",
    "model_write",
    "execute",
    "parts",
    "view",
    "focus",
    "visibility",
    "highlight",
    "section",
    "screenshot",
    "selection",
    "measure",
    "annotate",
    "clear_annotations",
    "export",
    "stock_search",
    "stock_get",
    "stock_define",
    "material_list",
    "material_define",
    "catalog_delete",
    "bom",
    "bedingungen",
)

__all__ = ["INSTRUCTIONS", "SERVER_NAME", "SERVER_TITLE", "TOOL_NAMES", "KevcadTools", "register_tools"]
