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

DRUCKVORSCHAU_TOOL_NAMES: tuple[str, ...] = ("druckvorschau", "druck_einstellen", "druck_export", "filament_liste",
                                             "filament_define")


def register_druckvorschau_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Registriert die Werkzeuge über den ``tool``-Dekorator aus ``register_tools``."""

    @tool("druckvorschau", "Druckvorschau",
          "Print preview of the last run for Kevin's Bambu Lab P1P (open frame): what the printed parts mean in "
          "practice. The preview assumes a filament per material (last chosen for this project, a spool in stock or "
          "the first of Kevin's list) and says which (summe.material[].filament_detail); before printing or exporting "
          "always ask Kevin which filament. Shows groups of identical print parts (lager.druckteil) with count, material, purpose (zweck) and the "
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
          "(bool), and the per-object print-ready keys stuetzen_nur_platte (bool), stuetzen_abstand_mm, brim_mm, naht "
          "(hinten, ausgerichtet, nah, zufall), buegeln (bool), oberflaeche (monoton_linie, monoton, linie, "
          "konzentrisch), loch_kompensation_mm, kontur_kompensation_mm, elefantenfuss_mm; a null value removes that "
          "fixed value. Fixed values always win over the automatic settings. zweck: zier | funktion | tragend | "
          "bewegt | aussen "
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
          "0.4 profile, the chosen filament's preset per material, settings per part). ALWAYS ASK KEVIN WHICH "
          "FILAMENT before calling this (also when he only asks about printing): filament = one entry of his list "
          "per material, e.g. {'petg': 'polymaker-polylite-petg-gelb'} (filament_liste shows the list). Without "
          "filament nothing is written and the result is an error 'Frag Kevin nach dem Filament' with suggestions "
          "(last chosen for this project, spools in stock, all filaments of the material); the last chosen one is "
          "only a suggestion, never take it silently. The filament's preset (Bambu base profile plus documented "
          "deviations, named like 'Polymaker PolyLite PETG gelb (Kev CAD)') goes completely into the project; the "
          "result names filament, preset, base profile, deviations with source and the temperatures. Every export "
          "is completely print-ready per object (supports only where needed, brim width, seam, ironing, walls "
          "around holes and inserts, hole compensation 0, each with a reason in objekte_einstellungen); never tune "
          "settings by hand afterwards. Before writing, Bambu Studio slices the file: druckfertig=true only without "
          "warnings, otherwise the hints say what is missing. With Bambu Studio installed the file is written "
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
        filament: Annotated[dict[str, str] | list[str] | str | None,
                            Field(description="Kevin's answer: per material one filament id from filament_liste, "
                                              "e.g. {'petg': 'polymaker-polylite-petg-gelb'}; required")] = None,
    ) -> CallToolResult:
        if isinstance(filament, str) and filament.strip().lower() == "vorschau":
            filament = None  # nur intern (Phase 8): der Agent fragt Kevin
        res = await t.work("schreibt die Druckplatten als 3MF", svc.druck_export, ziel, platten, teile, ohne,
                           filament)
        err = fmt.service_error(res)
        if err:
            if res.get("filament_frage"):
                return fmt.error_result(str(err), res)
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
        if res.get("objekte_einstellungen"):
            from kevcad_kernel.druck.vorschau_text import einstellungen_text

            text += "\n" + ("Druckfertig voreingestellt" if res.get("druckfertig") else "Voreingestellt (noch nicht "
                                                                                     "druckfertig, siehe oben)") + ":"
            for o in res["objekte_einstellungen"]:
                text += f"\n- {o.get('name')}: {einstellungen_text(o.get('einstellungen') or {})}"
                for k, b in (o.get("begruendung_je") or {}).items():
                    if k in ("waende", "fuellung", "stuetzen", "brim_mm", "naht", "buegeln", "stuetzen_nur_platte") \
                            or b.startswith("fest"):
                        text += f"\n    {b}"
        return fmt.result(text, {k: v for k, v in res.items() if k != "ok"})

    @tool("filament_liste", "Filamente",
          "Kevin's filaments (his own list, not the stock catalog): manufacturer, product, material, colour, "
          "diameter and the Bambu Studio preset each one prints with (base profile such as 'PolyLite PETG @BBL P1P' "
          "plus documented deviations with source), the resolved temperatures, the filament last chosen for this "
          "project and the spools in stock with their filament. Use it to ask Kevin which filament before "
          "druck_export. material filters (e.g. 'petg').", annotations["read_only"])
    async def filament_liste(
        material: Annotated[str | None, Field(description="Material id, e.g. 'petg'; omit for all")] = None,
    ) -> CallToolResult:
        res = await t.work("liest die Filamentliste", svc.filament_liste, material)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Filamentliste nicht lesbar: {err}", res)
        from kevcad_kernel.druck.filamentwahl import temperaturen_text

        zeilen = [f"Kevins Filamente ({res.get('pfad')}):"]
        for f in res.get("filamente") or []:
            t_ = temperaturen_text(f.get("temperaturen"))
            zeilen.append(f"- {f.get('id')}: {f.get('anzeige')}, {str(f.get('material')).upper()}; Preset "
                          f"„{f.get('preset_name')}“ (Basis „{(f.get('preset') or {}).get('basis')}“; "
                          f"{f.get('abweichungen_text')})" + (f"; {t_}" if t_ else "")
                          + (f"; offen: {', '.join(f['offen'])}" if f.get("offen") else "")
                          + (f"; PROBLEM: {' '.join(f['probleme'])}" if f.get("probleme") else ""))
        if res.get("zuletzt"):
            zeilen.append("Zuletzt gewählt (dieses Projekt): " + ", ".join(f"{m}: {i}" for m, i in
                                                                          res["zuletzt"].items()))
        for s_ in res.get("spulen") or []:
            zeilen.append(f"Spule {s_.get('kennung')} {s_.get('name') or ''} ({s_.get('material')}, "
                          f"{s_.get('gramm')} g) → {s_.get('filament') or 'kein Filament der Liste'}")
        return fmt.result("\n".join(zeilen), {k: v for k, v in res.items() if k != "ok"})

    @tool("filament_define", "Filament anlegen",
          "Add (or with ersetzen=true change) a filament in Kevin's list, no catalog release needed: hersteller, "
          "produkt, material (printable catalog id like 'petg'), farbe, durchmesser_mm (1.75), basis = Bambu Studio "
          "profile it inherits from (omit: chosen from manufacturer and product among profiles for the P1P 0.4), "
          "abweichungen = list of {schluessel, wert, quelle} with schluessel duese, duese_erste_schicht, bett, "
          "bett_erste_schicht, luefter_min, luefter_max, max_volumen, fluss (or a Bambu key of the base profile). "
          "Every deviation needs a source: the manufacturer's official profile for the P1P or Kevin's tested value "
          "with date; datasheet ranges for other speeds are no reason to deviate. Only on Kevin's request.",
          annotations["additive"])
    async def filament_define(
        hersteller: Annotated[str, Field(description="Manufacturer, e.g. 'Polymaker'")],
        produkt: Annotated[str, Field(description="Product, e.g. 'PolyLite PETG'")],
        material: Annotated[str, Field(description="Material id from the catalog, e.g. 'petg'")],
        farbe: Annotated[str | None, Field(description="Colour as Kevin calls it, e.g. 'gelb'")] = None,
        durchmesser_mm: Annotated[float, Field(description="Filament diameter in mm")] = 1.75,
        basis: Annotated[str | None, Field(description="Bambu Studio base profile, e.g. "
                                                       "'PolyLite PETG @BBL P1P'")] = None,
        abweichungen: Annotated[list[dict[str, Any]] | None,
                                Field(description="[{schluessel, wert, quelle}]")] = None,
        farbe_hex: Annotated[str | None, Field(description="#RRGGBB for the colour in Bambu Studio")] = None,
        id: Annotated[str | None, Field(description="Own id (default from manufacturer, product, colour)")] = None,  # noqa: A002
        preset_name: Annotated[str | None, Field(description="Preset name (default '<Hersteller> <Produkt> "
                                                             "<Farbe> (Kev CAD)')")] = None,
        quelle: Annotated[str | None, Field(description="Where the data comes from")] = None,
        ersetzen: Annotated[bool, Field(description="Replace an existing entry with this id")] = False,
    ) -> CallToolResult:
        res = await t.work("legt ein Filament an", svc.filament_define, hersteller, produkt, material, farbe,
                           durchmesser_mm, basis, abweichungen, farbe_hex, id, preset_name, quelle, ersetzen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Filament nicht angelegt: {err}", res)
        f = res.get("filament") or {}
        text = (f"Filament {'angelegt' if res.get('neu') else 'geändert'}: {f.get('id')} = {f.get('anzeige')}, Preset "
                f"„{(f.get('preset') or {}).get('name')}“ (Basis „{(f.get('preset') or {}).get('basis')}“).")
        for h in res.get("hinweise") or []:
            text += f"\n{h}"
        return fmt.result(text, {k: v for k, v in res.items() if k != "ok"})
