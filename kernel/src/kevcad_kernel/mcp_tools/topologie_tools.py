"""MCP-Werkzeuge der Topologieoptimierung (PLAN-TOPOLOGIE.md): ``topologie_optimieren``, ``topologie_ergebnis``,
``topologie_uebernehmen``.

Eigene Datei, damit parallele Stränge nicht in dieselben Zeilen von tools.py schreiben. Beschreibung englisch (für das
Modell), Ergebnis deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

TOPOLOGIE_TOOL_NAMES: tuple[str, ...] = ("topologie_optimieren", "topologie_ergebnis", "topologie_uebernehmen")


def register_topologie_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:

    @tool("topologie_optimieren", "Topologie optimieren",
          "Topology optimization of a 3D printed part (lager.druckteil) like implicit.build: keep a volume fraction "
          "(behalten, default 0.4) along the load paths and remove the rest. Supports and loads come from the "
          "statics model exactly like 'festigkeit' (contact faces to carrying neighbours, st.last on the part, force "
          "pairs, support forces of bars) for one scenario (szenario; default: the one with the highest utilization "
          "of the part). Protected zones automatically: holes with a wall ring, heat-set inserts with their minimum "
          "wall, load and clamping faces; plus schutz=[{art:'quader', min, max} | {art:'kugel', mitte, radius} "
          "(world, mm) | {art:'index', index: face number of the part}]. ueberhang=true: no new overhangs above 45 "
          "degrees in the print direction (Bambu P1P). steg: minimum member size in line widths of 0.42 mm "
          "(default 6 = 2.5 mm). lager='bohrungen': the bolts in the unloaded holes hold the part instead of the "
          "whole contact face (like 'Fix the bolts'; use it for brackets screwed onto a plate, otherwise the plate "
          "carries everything and the bosses end up as islands). fein=true: ~3x the voxels. Runs in the background in its own process (about a "
          "minute; the viewer shows the density live as translucent iterations); it returns at once unless "
          "warten=true. Afterwards the result is re-analysed with the solid FEM (safety vs target 4 for printed "
          "parts) and the print check, with key figures before and after (volume, mass, filament, print time, max "
          "stress, safety, deflection). abbrechen=true stops a running optimization. The result is stored in the "
          "project (topologie/<part>-<key>.brep); to use it, call topologie_uebernehmen (creates a variant) or write "
          "topologie.optimieren(part, ...) into model.py. Always say: approximation, not a structural verification.",
          annotations["additive"])
    async def topologie_optimieren(
        teil: Annotated[str | None, Field(description="Printed part, e.g. 'Halter'; omit if there is only one")] = None,
        szenario: Annotated[str | None, Field(description="Load scenario name; omit for the most utilized")] = None,
        behalten: Annotated[float | None, Field(description="Volume fraction to keep, 0.05-0.95 (default 0.4)")] = None,
        schutz: Annotated[list[dict[str, Any]] | None, Field(
            description="Extra protected zones: {art:'quader', min:[x,y,z], max:[x,y,z]}, {art:'kugel', "
                        "mitte:[x,y,z], radius:r} in world mm, or {art:'index', index:n} for a face of the part")] = None,
        ueberhang: Annotated[bool | None, Field(description="Overhang filter in print direction (45 degrees)")] = None,
        fein: Annotated[bool | None, Field(description="Finer voxel grid (about 3x the voxels, slower)")] = None,
        steg: Annotated[float | None, Field(description="Minimum member size in line widths (0.42 mm), default 6")]
        = None,
        lager: Annotated[str | None, Field(
            description="Supports while optimizing: 'kontakt' (contact faces, default, like statics) or 'bohrungen' "
                        "(bolts in the unloaded holes)")] = None,
        neu: Annotated[bool, Field(description="Recompute even if a stored result matches")] = False,
        warten: Annotated[bool, Field(description="Wait for the result (up to 10 minutes)")] = False,
        abbrechen: Annotated[bool, Field(description="Only stop a running optimization")] = False,
    ) -> CallToolResult:
        if abbrechen:
            res = await t.work("bricht die Topologieoptimierung ab", svc.topologie_abbrechen)
            return fmt.result("Topologieoptimierung abgebrochen." if res.get("abgebrochen")
                              else "Es lief keine Topologieoptimierung.", {k: v for k, v in res.items() if k != "ok"})
        res = await t.work("startet die Topologieoptimierung", svc.topologie_optimieren, teil, szenario, behalten,
                           schutz, ueberhang, fein, steg, None, neu, warten, lager)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Topologie nicht gestartet: {err}", res)
        return fmt.result(str(res.get("text") or res.get("stand")), {k: v for k, v in res.items() if k != "ok"})

    @tool("topologie_ergebnis", "Topologie: Ergebnis",
          "State and result of the last topology optimization: progress while running; when done the key figures "
          "before/after (volume, mass, filament g, print time, max von Mises stress, safety factor vs target with "
          "traffic light, deflection, thinnest member), protected zones, hints, limits and the stored file. "
          "warten_s waits up to that many seconds for the end.", annotations["read_only"])
    async def topologie_ergebnis(
        warten_s: Annotated[float, Field(description="Wait up to this many seconds for a running optimization")] = 0.0,
    ) -> CallToolResult:
        res = await t.work("liest das Topologie-Ergebnis", svc.topologie_ergebnis, warten_s)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Topologie: {err}", res)
        return fmt.result(str(res.get("text") or res.get("stand")), {k: v for k, v in res.items() if k != "ok"})

    @tool("topologie_uebernehmen", "Topologie übernehmen",
          "Adopt the last topology result as a new variant (versions): creates the variant, inserts "
          "'x = topologie.optimieren(x, szenario=..., behalten=...)' right after the part's lager.druckteil(...) "
          "line in model.py and runs it, so the optimized body replaces the part. Kevin decides which variant to "
          "keep. Only on Kevin's request.", annotations["additive"])
    async def topologie_uebernehmen(
        variante: Annotated[str | None, Field(description="Name of the new variant (default 'Topologie <part> 40 %')")]
        = None,
    ) -> CallToolResult:
        res = await t.work("übernimmt die Topologie als Variante", svc.topologie_uebernehmen, variante, True)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Nicht übernommen: {err}", res)
        return fmt.result(str(res.get("text") or "übernommen"), {k: v for k, v in res.items() if k != "ok"})
