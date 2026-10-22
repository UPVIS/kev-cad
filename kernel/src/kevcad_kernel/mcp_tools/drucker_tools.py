"""MCP-Werkzeuge ``drucker_status`` und ``drucken`` (Phase 8, DRUCKVORSCHAU.md „Drucken (Phase 8)“).

Eigene Datei, damit parallele Stränge nicht in dieselben Zeilen von tools.py schreiben. Beschreibung englisch (für das
Modell), Ergebnis deutsch (Kevin liest mit). ``drucken`` startet nie selbst etwas: es öffnet in der App den Dialog, und
erst Kevins Klick dort löst etwas aus.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from . import format as fmt

DRUCKER_TOOL_NAMES: tuple[str, ...] = ("drucker_status", "drucken")

ASKS_KEVIN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                             open_world_hint=True)


def register_drucker_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    @tool("drucker_status", "Druckerstatus",
          "Read-only status of Kevin's Bambu Lab P1P and of Kev CAD's print job: connection (read-only MQTT in the "
          "LAN, only if Kevin entered IP, serial and access code and switched on 'Status lesen'), printer mode "
          "(cloud/LAN, developer mode), which way is possible (A: Kev CAD slices the plates of the print preview with "
          "Bambu Studio and opens them in Bambu Studio, Kevin clicks print there – Kevin's choice; B: direct LAN "
          "printing, locked unless the printer is in LAN-only + developer mode), current print (state, progress, "
          "layer, remaining time, temperatures, HMS errors), printers heard in the LAN and the last job. Never "
          "contains serial number or access code. Sends nothing to the printer.", annotations["read_only"])
    async def drucker_status() -> CallToolResult:
        res = await t.work("liest den Druckerstatus", svc.drucker_status)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Druckerstatus nicht verfügbar: {err}", res)
        from kevcad_kernel.drucker.bericht import status_text

        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result(status_text(res), data)

    @tool("drucken", "Drucken (Dialog in Kev CAD)",
          "ONLY when Kevin explicitly asks to print now (e.g. 'druck das', 'schick die Platten an den Drucker'); never "
          "on your own initiative, never to test. Opens the dialog 'Drucken …' in Kev CAD with the plates of the print "
          "preview; NOTHING happens until Kevin confirms there with a click. Way 'a' (default, Kevin's choice): after "
          "his click Kev CAD slices the plates with Bambu Studio and opens the .gcode.3mf in Bambu Studio, where "
          "Kevin presses print. Way 'b' (direct) is locked unless Kevin switched the printer to LAN-only + developer "
          "mode and chose way B. platten: plate numbers of the print preview (druckvorschau), omit for all. grund: one "
          "short German sentence shown in the dialog (why you ask). Follow progress with drucker_status.",
          ASKS_KEVIN)
    async def drucken(
        platten: Annotated[list[int] | None, Field(description="Plate numbers from druckvorschau; omit for all")] = None,
        weg: Annotated[str, Field(description="'a' (open in Bambu Studio, default) or 'b' (direct, usually locked)")]
        = "a",
        grund: Annotated[str | None, Field(description="Short German reason shown to Kevin in the dialog")] = None,
    ) -> CallToolResult:
        res = await t.work("fragt Kevin, ob gedruckt werden soll", svc.drucken, platten, weg, grund)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Drucken: {err}", res)
        platten_text = ", ".join(str(p) for p in res.get("platten") or []) or "alle"
        text = (f"Auftrag {res.get('auftrag')} (Weg {str(res.get('weg')).upper()}, Platten {platten_text}): "
                f"{res.get('meldung')}")
        return fmt.result(text, {k: v for k, v in res.items() if k != "ok"})
