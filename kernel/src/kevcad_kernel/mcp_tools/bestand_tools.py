"""MCP-Werkzeuge für den Bestand je Projekt (BESTAND.md): bestand_liste, bestand_eintragen (auch Filament),
einkaufsliste, gebaut_buchen, gedruckt_buchen, buchung_rueckgaengig. Beschreibungen englisch (für das Modell),
Ergebnisse deutsch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from kevcad_kernel.appformat import masse_g
from kevcad_kernel.service import KernelService

from . import format as fmt

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
ADDITIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

BESTAND_TOOL_NAMES: tuple[str, ...] = ("bestand_liste", "bestand_eintragen", "einkaufsliste", "gebaut_buchen",
                                       "gedruckt_buchen", "buchung_rueckgaengig")


def _lines(res: dict[str, Any]) -> list[str]:
    return [f"- {line}" for line in res.get("aenderungen_text") or []]


def register_bestand_tools(tool: Callable[..., Any], t: Any, svc: KernelService) -> None:
    """Registriert die Bestandswerkzeuge mit dem ``tool``-Dekorator aus ``register_tools``."""

    @tool("bestand_liste", "Bestand",
          "Stock on hand for the OPEN PROJECT only (each project has its own bestand.json, nothing is shared between "
          "projects): whole bars or sheets, offcuts (Reste) with id (R-0001 bars, P-0001 sheets), length or size and "
          "location, piece goods (screws by length, purchased parts), filament spools (S-0001: material, grams left, "
          "full spool, name, colour, location), settings (minimum offcut, saw kerf) and the latest bookings. id "
          "limits it to one stock item, a material id or a spool id.", READ_ONLY)
    async def bestand_liste(
        id: Annotated[str | None, Field(description="Stock id from the catalog, material id or spool id; omit for "
                                                    "everything")] = None,
    ) -> CallToolResult:
        res = await t.work("liest den Bestand", svc.bestand_liste, id)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Bestand nicht lesbar: {err}", res)
        return fmt.result(str(res.get("text") or ""), res)

    @tool("bestand_eintragen", "Bestand eintragen",
          "Record what Kevin says he has for THIS project, ONLY after Kevin stated it (never guess or invent stock). "
          "id: catalog stock id (stock_search). ganze: number of whole bars/sheets (sets the count; object {anzahl, "
          "laenge} or {anzahl, b, h} for a non-standard size). reste: offcuts to ADD, bars as lengths in mm (e.g. "
          "[430, 610, 180]) or {laenge, ort}, sheets as [b, h] or {b, h, ort}; each gets a new id. reste_entfernen: "
          "offcut ids to remove. reste_ersetzen=true replaces all offcuts of this item by reste. stueck: piece goods "
          "(screws, nuts, washers, and purchased parts: zukaufteil, kamera, objektiv, kamerazubehoer): count, or "
          "[{laenge, anzahl}] for screws per length (sets the count per length). "
          "mindestrest_mm: shorter offcuts count as waste for this item. "
          "FILAMENT (instead of id): material (printable material id or alias, e.g. 'petg') with gramm (grams left on "
          "the spool; default a full spool), spule (spool name as Kevin says it, e.g. 'Bambu PETG Basic schwarz'), "
          "gramm_voll (full spool, default spule_g of the material or 1000), farbe, hersteller, ort, anzahl (number "
          "of identical spools; anzahl=0 records that the project tracks filament but has none) adds spools with new "
          "ids S-0001…; kennung (e.g. 'S-0002') with gramm/ort/… updates one spool; spulen_entfernen removes spools. "
          "Once the project tracks filament, the shopping list adds whole spools for what the print preview needs "
          "beyond the stock. grund: Kevin's statement. Every change is "
          "booked (undo with buchung_rueckgaengig) and listed in the answer; repeat that list to Kevin.", WRITES)
    async def bestand_eintragen(
        grund: Annotated[str, Field(min_length=1, description="Kevin's statement this entry is based on")],
        id: Annotated[str | None, Field(description="Stock id from the catalog (not for filament)")] = None,
        ganze: Annotated[int | dict[str, float] | None, Field(description="Whole bars/sheets: count (sets it) or "
                                                                        "{anzahl, laenge} / {anzahl, b, h}")] = None,
        reste: Annotated[list[float | list[float] | dict[str, Any]] | None,
                         Field(description="Offcuts to add: lengths in mm, [b, h] for sheets, or objects with ort")]
        = None,
        reste_entfernen: Annotated[list[str] | None, Field(description="Offcut ids to remove, e.g. ['R-0003']")]
        = None,
        stueck: Annotated[int | list[dict[str, Any]] | None,
                          Field(description="Piece goods (also purchased parts, cameras, lenses): count, "
                                            "or [{laenge, anzahl}] for screws")] = None,
        mindestrest_mm: Annotated[float | None, Field(description="Minimum useful offcut for this item (mm)")] = None,
        reste_ersetzen: Annotated[bool, Field(description="Replace all offcuts of this item by reste")] = False,
        material: Annotated[str | None, Field(description="Filament: printable material id or alias, e.g. 'petg'")]
        = None,
        gramm: Annotated[float | None, Field(description="Filament: grams left on the spool")] = None,
        spule: Annotated[str | None, Field(description="Filament: spool name, e.g. 'Bambu PETG Basic schwarz'")]
        = None,
        gramm_voll: Annotated[float | None, Field(description="Filament: net grams of a full spool")] = None,
        farbe: Annotated[str | None, Field(description="Filament: colour")] = None,
        hersteller: Annotated[str | None, Field(description="Filament: manufacturer")] = None,
        ort: Annotated[str | None, Field(description="Filament: storage location")] = None,
        anzahl: Annotated[int | None, Field(description="Filament: number of identical new spools (0: none on hand)")]
        = None,
        kennung: Annotated[str | None, Field(description="Filament: spool id to update, e.g. 'S-0002'")] = None,
        spulen_entfernen: Annotated[list[str] | None, Field(description="Filament: spool ids to remove")] = None,
        filament: Annotated[str | None, Field(description="Filament: id from Kevin's filament list (filament_liste), "
                                                          "fills material, name, manufacturer, colour")] = None,
    ) -> CallToolResult:
        was = id or (f"Filament {material}" if material else f"Spule {kennung}" if kennung else "Filament")
        res = await t.work(f"trägt Bestand {was} ein", svc.bestand_eintragen, id, ganze, reste, reste_entfernen,
                           stueck, mindestrest_mm, reste_ersetzen, grund, material=material, gramm=gramm,
                           gramm_voll=gramm_voll, spule=spule, farbe=farbe, hersteller=hersteller, anzahl=anzahl,
                           kennung=kennung, ort=ort, spulen_entfernen=spulen_entfernen, filament=filament)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Bestand nicht eingetragen: {err}", res)
        b = res.get("buchung") or {}
        text = "\n".join([f"Bestand eingetragen ({b.get('id')}, {b.get('art')}):", *_lines(res),
                          "Zuschnitt und Einkaufsliste sind neu geplant. Kevin jede Änderung nennen; rückgängig mit "
                          f"buchung_rueckgaengig(\"{b.get('id')}\")."])
        return fmt.result(text, res)

    @tool("einkaufsliste", "Einkaufsliste",
          "Shopping list of the current project after the last run, exactly as Kevin sees and shares it in the app "
          "(Material, Einkaufsliste): Lagerware (what is missing after using offcuts first, then whole stock of "
          "this project, rounded up to purchase units, standard parts to buy included), Zukaufteile (bought parts "
          "with shop link and price from the catalog, minus what the project stock holds), the total of both, then Normteile abzählen (needed, from "
          "stock, to buy) and Filament für Druckteile (from the print preview of the same run, else volume x "
          "density). If the project tracks filament, Lagerware also lists whole spools for what the print preview "
          "needs beyond the spools on hand. Also writes <project>/output/<name>-einkaufsliste.csv (same bytes as the "
          "app's CSV). Mention the shopping list (or that nothing is missing) in your report to Kevin.", ADDITIVE)
    async def einkaufsliste() -> CallToolResult:
        res = await t.work("stellt die Einkaufsliste zusammen", svc.einkaufsliste)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        text = str(res.get("text") or "")
        aus = res.get("zukauf_aus_bestand") or []
        if aus:
            text += "\nZukaufteile aus dem Bestand: " + ", ".join(
                f"{z.get('benennung')} ({z.get('aus_bestand')} von {z.get('anzahl')})" for z in aus)
        fil = [f for f in res.get("filament_aus_bestand") or [] if f.get("reicht")]
        if fil:
            text += "\nFilament aus dem Bestand: " + ", ".join(
                f"{f.get('werkstoff')} ({masse_g(f.get('bedarf_g') or 0)} von {masse_g(f.get('bestand_g') or 0)})"
                for f in fil)
        if res.get("einkauf_hinweis"):
            text += f"\nPreise Lagerware: {res['einkauf_hinweis']}"
        if res.get("csv"):
            text += f"\nCSV: {res['csv']}"
        for w in res.get("warnings") or []:
            text += f"\nHinweis: {w}"
        return fmt.result(text, res)

    @tool("gebaut_buchen", "Gebaut buchen",
          "ONLY when Kevin explicitly says the project has been built (\"ist gebaut\", \"buch das ab\"). Books the "
          "current cut plan against this project's stock: planned offcuts and whole bars/sheets are removed, new "
          "offcuts (from the minimum length) are added with new ids, piece goods are deducted, and (if the project "
          "tracks filament) the filament of print plates not yet booked as printed. Never call it on your "
          "own initiative. grund: Kevin's words. Reversible with buchung_rueckgaengig.", WRITES)
    async def gebaut_buchen(
        grund: Annotated[str, Field(min_length=1, description="Kevin's words that the project is built")],
    ) -> CallToolResult:
        res = await t.work("bucht das Gebaute ab", svc.gebaut_buchen, grund)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Nicht gebucht: {err}", res)
        b = res.get("buchung") or {}
        fil = [f"Filament: {x}" for x in res.get("filament_text") or []]
        text = "\n".join([f"Gebaut gebucht ({b.get('id')}): {b.get('zusammenfassung')}", *_lines(res), *fil,
                          f"Rückgängig mit buchung_rueckgaengig(\"{b.get('id')}\")."])
        return fmt.result(text, res)

    @tool("gedruckt_buchen", "Gedruckt buchen",
          "ONLY when Kevin explicitly says he printed the parts (\"ist gedruckt\", \"Platte 1 ist fertig\"). Books the "
          "filament of the print preview of the current run off this project's spools: all plates not booked yet, "
          "or only platten (plate numbers). Partly used spools first (least filament first), or spule first if "
          "Kevin names the spool he used; whatever the stock does not cover counts as printed from bought spools, "
          "and the rest of the last bought spool becomes a new spool. Each plate is booked once per run; "
          "gebaut_buchen later skips booked plates. Needs filament in the project stock (bestand_eintragen with "
          "material). grund: Kevin's words. Reversible with buchung_rueckgaengig.", WRITES)
    async def gedruckt_buchen(
        grund: Annotated[str, Field(min_length=1, description="Kevin's words that the parts are printed")],
        platten: Annotated[list[int] | None, Field(description="Plate numbers of the print preview; omit for all "
                                                               "plates not booked yet")] = None,
        spule: Annotated[str | None, Field(description="Spool id Kevin used, e.g. 'S-0002' (used first)")] = None,
    ) -> CallToolResult:
        res = await t.work("bucht das Gedruckte ab", svc.gedruckt_buchen, grund, platten, spule)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Nicht gebucht: {err}", res)
        b = res.get("buchung") or {}
        text = "\n".join([f"Gedruckt gebucht ({b.get('id')}, Platten {', '.join(map(str, res.get('platten') or []))}"
                          f"): {b.get('zusammenfassung')}",
                          *[f"- {x}" for x in res.get("filament_text") or []], *_lines(res),
                          f"Rückgängig mit buchung_rueckgaengig(\"{b.get('id')}\")."])
        return fmt.result(text, res)

    @tool("buchung_rueckgaengig", "Buchung rückgängig",
          "Undo one stock booking of this project by its id (e.g. 'B-0004'), as a new reverse booking. Fails with a "
          "clear message if later bookings already used the same offcuts.", WRITES)
    async def buchung_rueckgaengig(
        id: Annotated[str, Field(description="Booking id, e.g. 'B-0004' (see bestand_liste)")],
    ) -> CallToolResult:
        res = await t.work(f"macht Buchung {id} rückgängig", svc.buchung_rueckgaengig, id)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Nicht rückgängig gemacht: {err}", res)
        b = res.get("buchung") or {}
        text = "\n".join([f"Buchung {id} rückgängig gemacht ({b.get('id')}): {b.get('zusammenfassung')}",
                          *_lines(res)])
        return fmt.result(text, res)
