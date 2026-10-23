"""MCP-Werkzeuge des Bereichs „Simulation“ (PLAN-SIMULATION.md): ``simulation_liste``, ``simulation_aendern``,
``simulation_rechnen``.

Kevin legt Lastfälle, Kräfte und Lager per Klick in der App an (``<projekt>/simulation.json``); der Agent sieht und ändert
dieselben Daten. ``statik`` und ``szenario_rechnen`` sehen die Lastfälle der App ohnehin (sie gehören zu jedem Lauf).
Eigene Datei, damit parallele Stränge nicht in dieselben Zeilen von tools.py schreiben. Beschreibung englisch (für das
Modell), Ergebnis deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

SIMULATION_TOOL_NAMES: tuple[str, ...] = ("simulation_liste", "simulation_aendern", "simulation_rechnen")


def _kurztext(res: dict[str, Any]) -> str:
    lf = res.get("lastfaelle") or []
    teile = [f"{len(lf)} Lastfälle aus der App"]
    if res.get("lager"):
        teile.append(f"{len(res['lager'])} Lager")
    fehlen = sum(1 for l in lf for x in l.get("lasten") or [] if x.get("zustand") == "fehlt") + sum(
        1 for x in res.get("lager") or [] if x.get("zustand") == "fehlt")
    if fehlen:
        teile.append(f"{fehlen} nicht mehr zuordenbar")
    return ", ".join(teile)


def register_simulation_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:

    @tool("simulation_liste", "Simulation: Lastfälle der App",
          "List the load cases, forces and supports Kevin created in the app's 'Simulation' area (stored in "
          "<project>/simulation.json next to model.py) with their state in the current model: each force with part, "
          "face reference, point, direction (normal/axis/free), magnitude (N or kg), effective force vector and "
          "'zustand' (ok, neu = re-associated to another face after a model change, fehlt = no longer assignable). "
          "Also the scenarios from model.py (an app load case with the same name replaces the model.py one), "
          "supports from st.lager, derived supports (floor contact 'boden:<part>', carrying contacts "
          "'kontakt:<part>|<neighbour>', with 'aktiv'), topology settings per printed part and the running job. "
          "The app load cases are part of every run: 'statik', 'szenario_rechnen', 'festigkeit' and 'dynamik' see them "
          "under their names.", annotations["read_only"])
    async def simulation_liste() -> CallToolResult:
        res = await t.work("liest die Lastfälle der Simulation", svc.simulation_liste)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Simulation: {err}", res)
        return fmt.result(_kurztext(res), {k: v for k, v in res.items() if k != "ok"})

    @tool("simulation_aendern", "Simulation: Lastfälle ändern",
          "Change the app's load cases, forces and supports (simulation.json) exactly like Kevin does by clicking; "
          "the statics are recomputed with the last model right away (no new run) and the app updates. ops is a list "
          "of operations, applied all-or-nothing: "
          "{op:'lastfall_neu', name, art:'statisch'|'dynamisch', neigung:{grad, richtung:'+x'}, beschleunigung:[ax,ay,az] "
          "m/s², fahrt:{geschwindigkeit m/s, bremsen:'abrupt'|'anprall'|m/s², dauer s, animation, angriff:'boden'|mm, "
          "fahrtrichtung:'+x'}, stoss:factor, untergrund:'holz', ziel:{sicherheit, durchbiegung: 300 (= L/300)}}; "
          "{op:'lastfall_setzen', name, felder:{...same fields}}; {op:'lastfall_kopieren', von, name} (from an app "
          "load case or a model.py/standard scenario: 'als Kopie bearbeiten'); {op:'lastfall_umbenennen', name, neu}; "
          "{op:'lastfall_loeschen', name}; {op:'last_setzen', lastfall, last:{id?, teil, gegen? (force pair: the "
          "counter force acts on this part), ort:{flaeche: face number as in the viewer/selection, punkt:[x,y,z] mm, "
          "normale:[nx,ny,nz]}, richtung:{art:'normale'} (into the face; umkehren:true pulls) | {art:'achse', "
          "achse:'-z'} | {art:'frei', vektor:[x,y,z]} or {art:'frei', azimut, hoehe} degrees, betrag, einheit:'N'|'kg'}}"
          " (without id: new force, otherwise replace); {op:'last_loeschen', lastfall, id}; {op:'lager_setzen', "
          "lager:{id?, teil, art:'fest'|'gelenkig'|'gleitend', auf:'flaeche'|'punkt'|'teil', ort:{flaeche, punkt, "
          "normale}}} (supports apply to all load cases: bars get a support at the nearest axis point, other parts "
          "are grounded; the solid FEM and topology fix the face, 'gleitend' only normal to it); {op:'lager_loeschen', "
          "id}; {op:'abgeleitet', id:'boden:<part>'|'kontakt:<part>|<neighbour>', aktiv:false} (switch a derived "
          "support off/on); {op:'topologie', teil, einstellungen:{szenario, behalten, ueberhang, fein, steg, "
          "bohrungen, einsaetze, kontakt, bett, lager, schutz:[{art:'index', index}]}}. Face numbers come from "
          "'selection' or 'measure'. Only change what Kevin asked for; his clicks are his decisions.",
          annotations["additive"])
    async def simulation_aendern(
        ops: Annotated[list[dict[str, Any]], Field(description="Operations, see the tool description")],
        basis: Annotated[int | None, Field(description="Expected 'stand' from simulation_liste (rejects if changed)")]
        = None,
    ) -> CallToolResult:
        res = await t.work("ändert die Lastfälle der Simulation", svc.simulation_aendern, ops, basis, "agent")
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Nicht geändert: {err}", res)
        text = "; ".join(res.get("meldungen") or []) or "geändert"
        if res.get("warnung"):
            text += f" ({res['warnung']})"
        return fmt.result(text, {k: v for k, v in res.items() if k != "ok"})

    @tool("simulation_rechnen", "Simulation: rechnen",
          "Run what the buttons in the app's Simulation area run, for a load case (app or model.py): "
          "was='rechnen' (S0 and S1 now, all load cases), 'festigkeit' (solid FEM for the parts under load, optionally "
          "teil, fein), 'ablauf' (dynamic run with MuJoCo for a load case with fahrt), 'grenze' with "
          "grenze='last' (how much load: factor on the forces until the target safety, breaking, tipping, sliding), "
          "'neigung' (how steep the floor may get) or 'geschwindigkeit' (how fast: limit speed of the dynamic run). "
          "Waits for the result; the app shows progress and the result. Load and slope limits use S0 and S1 (not the "
          "solid FEM).", annotations["additive"])
    async def simulation_rechnen(
        was: Annotated[str, Field(description="rechnen | festigkeit | ablauf | grenze")],
        lastfall: Annotated[str | None, Field(description="Load case name (required for ablauf and grenze)")] = None,
        teil: Annotated[str | None, Field(description="festigkeit: only this part")] = None,
        fein: Annotated[bool, Field(description="festigkeit: finer mesh")] = False,
        grenze: Annotated[str | None, Field(description="grenze: last | neigung | geschwindigkeit")] = None,
    ) -> CallToolResult:
        res = await t.work("rechnet in der Simulation", svc.simulation_rechnen, was, lastfall, teil, fein, grenze,
                           True, "agent")
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Simulation: {err}", res)
        return fmt.result(str(res.get("text") or "gerechnet"), {k: v for k, v in res.items() if k != "ok"})
