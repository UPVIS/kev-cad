"""MCP-Werkzeuge für den Bestand je Projekt (BESTAND.md): bestand_liste, bestand_eintragen, einkaufsliste,
gebaut_buchen, buchung_rueckgaengig. Beschreibungen englisch (für das Modell), Ergebnisse deutsch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from kevcad_kernel.service import KernelService

from . import format as fmt

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
ADDITIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

BESTAND_TOOL_NAMES: tuple[str, ...] = ("bestand_liste", "bestand_eintragen", "einkaufsliste", "gebaut_buchen",
                                       "buchung_rueckgaengig")


def _lines(res: dict[str, Any]) -> list[str]:
    return [f"- {line}" for line in res.get("aenderungen_text") or []]


def register_bestand_tools(tool: Callable[..., Any], t: Any, svc: KernelService) -> None:
    """Registriert die Bestandswerkzeuge mit dem ``tool``-Dekorator aus ``register_tools``."""

    @tool("bestand_liste", "Bestand",
          "Stock on hand for the OPEN PROJECT only (each project has its own bestand.json, nothing is shared between "
          "projects): whole bars or sheets, offcuts (Reste) with id (R-0001 bars, P-0001 sheets), length or size and "
          "location, piece goods (screws by length), settings (minimum offcut, saw kerf) and the latest bookings. "
          "id limits it to one stock item.", READ_ONLY)
    async def bestand_liste(
        id: Annotated[str | None, Field(description="Stock id from the catalog; omit for everything")] = None,
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
          "(screws, nuts, washers): count, or [{laenge, anzahl}] for screws per length (sets the count per length). "
          "mindestrest_mm: shorter offcuts count as waste for this item. grund: Kevin's statement. Every change is "
          "booked (undo with buchung_rueckgaengig) and listed in the answer; repeat that list to Kevin.", WRITES)
    async def bestand_eintragen(
        id: Annotated[str, Field(description="Stock id from the catalog")],
        grund: Annotated[str, Field(min_length=1, description="Kevin's statement this entry is based on")],
        ganze: Annotated[int | dict[str, float] | None, Field(description="Whole bars/sheets: count (sets it) or "
                                                                        "{anzahl, laenge} / {anzahl, b, h}")] = None,
        reste: Annotated[list[float | list[float] | dict[str, Any]] | None,
                         Field(description="Offcuts to add: lengths in mm, [b, h] for sheets, or objects with ort")]
        = None,
        reste_entfernen: Annotated[list[str] | None, Field(description="Offcut ids to remove, e.g. ['R-0003']")]
        = None,
        stueck: Annotated[int | list[dict[str, Any]] | None,
                          Field(description="Piece goods: count, or [{laenge, anzahl}] for screws")] = None,
        mindestrest_mm: Annotated[float | None, Field(description="Minimum useful offcut for this item (mm)")] = None,
        reste_ersetzen: Annotated[bool, Field(description="Replace all offcuts of this item by reste")] = False,
    ) -> CallToolResult:
        res = await t.work(f"trägt Bestand {id} ein", svc.bestand_eintragen, id, ganze, reste, reste_entfernen,
                           stueck, mindestrest_mm, reste_ersetzen, grund)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Bestand nicht eingetragen: {err}", res)
        b = res.get("buchung") or {}
        text = "\n".join([f"Bestand eingetragen ({b.get('id')}, {b.get('art')}):", *_lines(res),
                          "Zuschnitt und Einkaufsliste sind neu geplant. Kevin jede Änderung nennen; rückgängig mit "
                          f"buchung_rueckgaengig(\"{b.get('id')}\")."])
        return fmt.result(text, res)

    @tool("einkaufsliste", "Einkaufsliste",
          "Shopping list of the current project after the last run: what is missing after using offcuts first, then "
          "whole stock of this project, rounded up to purchase units (bar, sheet, piece), with guide price and date, "
          "supplier link, hints and the total; also writes <project>/output/<name>-einkaufsliste.csv. Mention the "
          "shopping list (or that nothing is missing) in your report to Kevin.", ADDITIVE)
    async def einkaufsliste() -> CallToolResult:
        res = await t.work("stellt die Einkaufsliste zusammen", svc.einkaufsliste)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        text = str(res.get("text") or "")
        if res.get("csv"):
            text += f"\nCSV: {res['csv']}"
        for w in res.get("warnings") or []:
            text += f"\nHinweis: {w}"
        return fmt.result(text, res)

    @tool("gebaut_buchen", "Gebaut buchen",
          "ONLY when Kevin explicitly says the project has been built (\"ist gebaut\", \"buch das ab\"). Books the "
          "current cut plan against this project's stock: planned offcuts and whole bars/sheets are removed, new "
          "offcuts (from the minimum length) are added with new ids, piece goods are deducted. Never call it on your "
          "own initiative. grund: Kevin's words. Reversible with buchung_rueckgaengig.", WRITES)
    async def gebaut_buchen(
        grund: Annotated[str, Field(min_length=1, description="Kevin's words that the project is built")],
    ) -> CallToolResult:
        res = await t.work("bucht das Gebaute ab", svc.gebaut_buchen, grund)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Nicht gebucht: {err}", res)
        b = res.get("buchung") or {}
        text = "\n".join([f"Gebaut gebucht ({b.get('id')}): {b.get('zusammenfassung')}", *_lines(res),
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
