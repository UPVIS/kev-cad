"""MCP-Werkzeuge der Druckvorschau (DRUCKVORSCHAU.md): ``druckvorschau``, ``druck_einstellen``, ``druck_export``.

Eigene Datei neben ``druck_tools.py`` (``druckpruefung``, unverändert): die Druckprüfung sagt, ob und wie ein Teil
druckbar ist, die Vorschau, was der Druck bedeutet (Filament, Zeit, Platten, Kosten, Einstellungen, Hinweise).
Beschreibungen englisch (für das Modell), Ergebnisse deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

DRUCKVORSCHAU_TOOL_NAMES: tuple[str, ...] = ("druckvorschau", "druck_einstellen", "druck_export")


def register_druckvorschau_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Registriert die drei Werkzeuge über den ``tool``-Dekorator aus ``register_tools``."""

    @tool("druckvorschau", "Druckvorschau",
          "Print preview of the last run for Kevin's Bambu Lab P1P (open frame): what the printed parts mean in "
          "practice. Groups of identical print parts (lager.druckteil) with count, material, purpose (zweck) and the "
          "recommended settings with reasons (layer height, walls, top/bottom layers, infill and pattern, supports, "
          "brim, orientation from the print check), filament per material in g, m and EUR, print time, plates with "
          "the parts arranged on each (identical parts together, one material per plate, front-left exclusion zone), "
          "total time incl. plate changes, cost incl. electricity and a risk surcharge, and practical hints (drying, "
          "warping on the open printer, brim, support removal, AMS purge, nozzle wear with CF, success risk). Values "
          "are a fast estimate right after each run and are replaced by Bambu Studio's slicer results in the "
          "background (stand: schaetzung | slicer | gemischt, slicer.zustand, abweichung = how far the estimate was "
          "off). Printability findings stay in druckpruefung. detail=true adds the plate outlines.",
          annotations["read_only"])
    async def druckvorschau(
        detail: Annotated[bool, Field(description="Include the convex outline of every part on its plate")] = False,
    ) -> CallToolResult:
        res = await t.work("liest die Druckvorschau", svc.druckvorschau, bool(detail))
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Druckvorschau nicht verfügbar: {err}", res)
        from kevcad_kernel.druck.vorschau_text import text

        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result(text(data), data)

    @tool("druck_einstellen", "Druck einstellen",
          "Fix print settings or the purpose of a print part group for the print preview and the 3MF export, stored "
          "in <project>/druck.json (survives runs, part of the versions). teil: a part name from show(), a group id "
          "like 'g3' or a group name; identical parts are always set together. einstellungen: any of schicht_mm "
          "(0.08-0.28), waende, decken, boeden, fuellung (0-1 or percent), muster (gyroid, grid, cubic, honeycomb, "
          "rectilinear, line, concentric, triangles, crosshatch, lightning), stuetzen (keine, baum, normal), brim "
          "(bool); a null value removes that fixed value. zweck: zier | funktion | tragend | bewegt | aussen "
          "(better: set zweck= in lager.druckteil in model.py). Only on Kevin's request or with a reason in your "
          "report. The orientation is set in model.py (druckteil(..., ausrichtung=...)), not here.",
          annotations["additive"])
    async def druck_einstellen(
        teil: Annotated[str, Field(description="Part name, group id ('g3') or group name")],
        einstellungen: Annotated[dict[str, Any] | None, Field(description="Settings to fix, e.g. "
                                                                          "{'waende': 4, 'fuellung': 0.3}")] = None,
        zweck: Annotated[Literal["zier", "funktion", "tragend", "bewegt", "aussen"] | None,
                         Field(description="Purpose of the part")] = None,
        zuruecksetzen: Annotated[bool, Field(description="Remove all fixed values of this group first")] = False,
    ) -> CallToolResult:
        res = await t.work("stellt den Druck ein", svc.druck_einstellen, teil, einstellungen, zweck, "agent",
                           bool(zuruecksetzen))
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Druckeinstellung nicht gespeichert: {err}", res)
        zeilen = [str(res.get("meldung") or "gespeichert")]
        g = res.get("gruppe")
        if isinstance(g, dict):
            from kevcad_kernel.druck.vorschau_text import dauer_text, einstellungen_text

            zeilen.append(f"Jetzt: {einstellungen_text(g.get('einstellungen') or {})}; "
                          f"{fmt.num(g.get('g'), 1)} g, {dauer_text(g.get('zeit_s'))} (Schätzung, Bambu Studio rechnet "
                          "nach).")
        return fmt.result("\n".join(zeilen), {k: v for k, v in res.items() if k != "ok"})

    @tool("druck_export", "Druckplatten als 3MF",
          "Write the arranged plates of the print preview as a 3MF project for Bambu Studio (Kevin's Bambu Lab P1P "
          "0.4 profile, filament per material, settings per part); with Bambu Studio installed the file is written "
          "by Bambu Studio and checked by loading it. Objects in the 3MF carry the part names from show() (shortened "
          "to about 60 characters, repeats numbered '(2)'), plates keep their numbers from druckvorschau. Does not "
          "print or send anything. ziel: path of the .3mf (default <project>/output/<project>-druck.3mf); platten: "
          "plate numbers from druckvorschau (default all). Select parts: teile = only these, ohne = all but these "
          "(both allowed, ohne wins); an entry is an exact part name, an assembly prefix ('Kugelschieber/Lenksperren' "
          "covers everything below it), a group id ('g3') or a group name from druckvorschau; unknown entries are an "
          "error with suggestions. The remaining parts stay where the preview put them (gaps are fine, Bambu Studio "
          "loads and slices that), empty plates are dropped, and the result lists what was left out (weggelassen). "
          "Parts marked lager.druckteil(..., spaeter=True) are never on a plate and always listed as left out; to "
          "print them, remove spaeter in model.py and run again. Use ohne for a one-off export (e.g. 'a plate without "
          "the Lenksperren'), spaeter=True when a part should stay out of the plates until Kevin says otherwise.",
          annotations["additive"])
    async def druck_export(
        ziel: Annotated[str | None, Field(description="Target .3mf path")] = None,
        platten: Annotated[list[int] | None, Field(description="Plate numbers, e.g. [1, 2]; omit for all")] = None,
        teile: Annotated[list[str] | None, Field(description="Only these parts: part names, assembly prefixes, "
                                                             "group ids or group names")] = None,
        ohne: Annotated[list[str] | None, Field(description="Leave these parts out (same kinds of entries as "
                                                            "teile; wins over teile)")] = None,
    ) -> CallToolResult:
        res = await t.work("schreibt die Druckplatten als 3MF", svc.druck_export, ziel, platten, teile, ohne)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"3MF nicht geschrieben: {err}", res)
        n = len(res.get("platten") or [])
        nummern = ", ".join(str(p) for p in res.get("platten") or [])
        text = (f"3MF mit {fmt.plural(n, 'Platte', 'Platten')} ({nummern}): {res.get('pfad')} "
                f"({fmt.ms_text(res.get('ms'))}).")
        for h in res.get("hinweise") or []:
            text += f"\n{h}"
        for d in res.get("dateien") or []:
            if d.get("objekte"):
                text += f"\nObjekte in {d.get('pfad')}: " + ", ".join(d["objekte"])
        return fmt.result(text, {k: v for k, v in res.items() if k != "ok"})
