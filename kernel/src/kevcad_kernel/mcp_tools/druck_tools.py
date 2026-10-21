"""MCP-Werkzeug ``druckpruefung``: Ergebnis der Druckprüfung (Bambu Lab P1P) des letzten Laufs je Druckteil.

Eigene Datei, damit parallele Stränge nicht in dieselben Zeilen von tools.py schreiben. Beschreibung englisch (für das
Modell), Ergebnis deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

DRUCK_TOOL_NAMES: tuple[str, ...] = ("druckpruefung",)


def register_druck_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Registriert ``druckpruefung`` über den ``tool``-Dekorator aus ``register_tools``."""

    @tool("druckpruefung", "Druckprüfung",
          "3D print check of the last run for Kevin's Bambu Lab P1P (open frame, PLA/PETG), for every part made with "
          "lager.druckteil(...): chosen bed orientation (automatic or ausrichtung=... in druckteil) with its "
          "reasoning, the face lying on the bed, key figures (size on the bed, layers, support area, contact area, "
          "volume, build volume use) and ALL findings with face references (Part#f<n>), location and fix: overhangs, "
          "bridges, horizontal holes, thin walls, pins, elephant foot, warping, build volume, material. Also the "
          "material settings (nozzle/bed temperature, drying). The check runs after every run anyway (findings are "
          "in run as art druck_*); this tool only reads the result, nothing is recomputed. Without teil: all print "
          "parts; teil: one part name or an assembly prefix.", annotations["read_only"])
    async def druckpruefung(
        teil: Annotated[str | None, Field(description="Print part name or assembly prefix, e.g. "
                                                      "'Kugelschieber/Fangrolle (Druck)'; omit for all")] = None,
    ) -> CallToolResult:
        res = await t.work("liest die Druckprüfung", svc.druckpruefung, teil)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Druckprüfung nicht verfügbar: {err}", res)
        from kevcad_kernel.druck.bericht import druck_text

        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result(druck_text(res), data, error=int((res.get("zaehler") or {}).get("fehler") or 0) > 0)
