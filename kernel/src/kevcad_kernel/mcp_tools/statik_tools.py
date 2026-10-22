"""MCP-Werkzeuge der Statik (PLAN-STATIK.md, Stufe 1): ``statik`` und ``szenario_rechnen``.

Eigene Datei, damit parallele Stränge nicht in dieselben Zeilen von tools.py schreiben. Beschreibung englisch (für das
Modell), Ergebnis deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

STATIK_TOOL_NAMES: tuple[str, ...] = ("statik", "szenario_rechnen")


def register_statik_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Registriert ``statik`` und ``szenario_rechnen`` über den ``tool``-Dekorator aus ``register_tools``."""

    @tool("statik", "Statik",
          "Statics of the last run (computed automatically after every run, nothing is recomputed): for every "
          "scenario a traffic light (gruen/gelb/rot) with safety factor against the target (static 2, dynamic 3, 3D "
          "printed parts x2), deflection, buckling load factor, tipping reserve per direction, sliding reserve (friction "
          "from the catalog), rough screw loads and the frame (bars from stock tubes/profiles via PyNite: stresses, "
          "deflection, support forces). Scenarios come from model.py (import kevcad.statik as st; st.szenario(...), "
          "st.last(teil, kraft=(fx, fy, fz) in N or kg=..., punkt=...)) plus defaults (Eigengewicht, Nutzlast from a "
          "param in kg, Bremsen on wheels). Also suggests lighter or stronger stock items ONLY from the inventory, and "
          "for printed parts loaded across the layers 'drehen oder verstärken'. Without szenario: all scenarios; with "
          "szenario: details (bars, supports, tipping per direction) and the viewer shows its utilization gradient. "
          "Results are simplified (linear-elastic beams, rigid connectors): always say so; no substitute for a "
          "structural engineer for safety-relevant things.", annotations["read_only"])
    async def statik(
        szenario: Annotated[str | None, Field(description="Scenario name for details, e.g. 'Eigengewicht' or "
                                                          "'Aufstützen 30 kg'; omit for the overview")] = None,
    ) -> CallToolResult:
        res = await t.work("liest die Statik", svc.statik, szenario)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Statik nicht verfügbar: {err}", res)
        from kevcad_kernel.statik.bericht import statik_text

        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result(statik_text(res), data)

    @tool("szenario_rechnen", "Szenario rechnen",
          "Compute one load scenario on the statics model of the last run, without a new run, in well under a second, "
          "and show it in the viewer (utilization gradient on parts and bars, exaggerated deflection as ghost). Use it "
          "for questions like 'does the frame hold if I lean on it with 30 kg?': lasten=[{teil: 'Name or group/', "
          "kg: 30}] or kraft=[fx, fy, fz] in N, optional punkt=[x, y, z] in mm (world). beschleunigung=[ax, ay, az] "
          "in m/s² of the whole object (braking in +X travel: [-3, 0, 0]), neigung in degrees with richtung ('+x', "
          "'-y'), stoss = impact factor on the loads (dynamic target 3). Answer with traffic light, safety factor, "
          "stress, deflection, tipping reserve and the stated simplifications. To keep a scenario, write it into "
          "model.py with kevcad.statik.", annotations["additive"])
    async def szenario_rechnen(
        name: Annotated[str, Field(description="Scenario name, e.g. 'Aufstützen 30 kg'")],
        lasten: Annotated[list[dict[str, Any]] | None, Field(
            description="Loads: [{'teil': 'Kugelschieber/Querstange vorn (Rohr 3)', 'kg': 30}] or "
                        "[{'teil': 'Halter', 'kraft': [0, 0, -50], 'punkt': [120, 0, 40]}]")] = None,
        beschleunigung: Annotated[list[float] | None, Field(description="[ax, ay, az] in m/s²")] = None,
        neigung: Annotated[float | None, Field(description="Floor tilt in degrees")] = None,
        richtung: Annotated[str | None, Field(description="Downhill direction for neigung: '+x', '-y', …")] = None,
        stoss: Annotated[float | None, Field(description="Impact factor on all loads, e.g. 2")] = None,
        ziel: Annotated[float | None, Field(description="Own target safety factor (default 2 static, 3 dynamic)")]
        = None,
        beschreibung: Annotated[str | None, Field(description="Short description in Kevin's words")] = None,
        zeigen: Annotated[bool, Field(description="Show the scenario in the viewer")] = True,
    ) -> CallToolResult:
        res = await t.work("rechnet ein Szenario", svc.szenario_rechnen, name, beschleunigung, neigung, richtung,
                           lasten, stoss, ziel, beschreibung, zeigen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Szenario nicht gerechnet: {err}", res)
        from kevcad_kernel.statik.bericht import szenario_text

        e = res.get("szenario") or {}
        text = szenario_text(e, detail=True)
        text += f"\n(gerechnet in {res.get('ms')} ms" + (", im Viewer gezeigt)" if res.get("gezeigt") else ")")
        if res.get("vereinfachungen"):
            text += "\nAnnahmen: " + "; ".join(res["vereinfachungen"][:6])
        if res.get("grenzen"):
            text += "\nGrenzen: " + " ".join(res["grenzen"])
        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result(text, data)
