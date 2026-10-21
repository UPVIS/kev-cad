"""MCP-Werkzeuge für technische Zeichnungen (Phase 6, Strang P6-Z; Vertrag DOKUMENTE.md): Blätter auflisten, anlegen,
bearbeiten und als Bild zur eigenen Prüfung holen. Beschreibungen englisch (für das Modell), Ergebnisse deutsch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

ZEICHNUNG_TOOL_NAMES: tuple[str, ...] = ("zeichnungen", "zeichnung_erstellen", "zeichnung_bearbeiten", "zeichnung_bild")


def _blatt_zeile(b: dict[str, Any]) -> str:
    if b.get("fehler") and not b.get("titel"):
        return f"- {b.get('id')}: nicht lesbar ({b['fehler']})"
    inhalt = b.get("inhalt") or {}
    art = {"teil": "Einzelteil", "baugruppe": "Baugruppe", "zusammenbau": "Zusammenbau"}.get(inhalt.get("art"), "")
    ansichten = b.get("ansichten") or []
    if ansichten and isinstance(ansichten[0], dict):
        ansichten = [a.get("art") for a in ansichten]
    masse = b.get("masse")
    n_masse = len(masse) if isinstance(masse, list) else masse
    verwaist = b.get("verwaist") if b.get("verwaist") is not None else b.get("verwaiste_masse")
    n_verwaist = len(verwaist) if isinstance(verwaist, list) else (verwaist or 0)
    teile = ", ".join(inhalt.get("teile") or []) or "alle Teile"
    fmt_text = b.get("format") if " " in str(b.get("format") or "") else f"{b.get('format')} {b.get('ausrichtung', '')}"
    zeile = (f"- {b.get('id')}: {b.get('titel')} ({art}: {teile}) · {fmt_text.strip()} · {b.get('massstab')} · Ansichten "
             f"{', '.join(str(a) for a in ansichten)} · {n_masse} Maße")
    if n_verwaist:
        zeile += f" · {n_verwaist} verwaist"
    return zeile


def _masse_text(masse: list[dict[str, Any]], limit: int = 40) -> list[str]:
    out = []
    for m in masse[:limit]:
        quelle = "" if m.get("quelle") == "auto" else f" [{m.get('quelle')}]"
        verwaist = " VERWAIST" if m.get("verwaist") else ""
        bez = ", ".join(str(x) for x in m.get("bezuege") or [] if x)
        out.append(f"  {m.get('id')} {m.get('art')} „{m.get('text')}“ in {m.get('ansicht')} ({bez}){quelle}{verwaist}")
    if len(masse) > limit:
        out.append(f"  … und {len(masse) - limit} weitere")
    return out


def _pruef_text(befunde: list[dict[str, Any]]) -> list[str]:
    return [f"  Prüfung ({b.get('schwere')}): {b.get('text')}" for b in befunde or []]


def register_zeichnung_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    READ_ONLY, ADDITIVE, WRITES = annotations["read_only"], annotations["additive"], annotations["writes"]

    @tool("zeichnungen", "Zeichnungen",
          "Technical drawing sheets of the open project (<project>/dokumente/zeichnungen/*.json): id, title, content "
          "(single part, sub-assembly, assembly), format, scale, views, number of dimensions, orphaned dimensions "
          "(their geometry changed: delete or re-attach them) and Kevin's/your own dimensions.", READ_ONLY)
    async def zeichnungen() -> CallToolResult:
        res = await t.work("schaut auf die Zeichnungen", svc.drawings)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Zeichnungen nicht lesbar: {err}", res)
        blaetter = res.get("blaetter") or []
        if not blaetter:
            return fmt.result("Noch keine Zeichnungen. zeichnung_erstellen legt Blätter für alle gefertigten Teile und "
                              "den Zusammenbau an.", res)
        lines = [f"{fmt.plural(len(blaetter), 'Blatt', 'Blätter')} in {res.get('ordner')}:"]
        lines += [_blatt_zeile(b) for b in blaetter]
        return fmt.result("\n".join(lines), res)

    @tool("zeichnung_erstellen", "Zeichnungen erstellen",
          "Create technical drawings (ISO 128/129-1, first-angle projection, title block ISO 7200) with automatic views "
          "and dimensions from the recognized features (holes with Ø/thread/counterbore, hole patterns, slots, "
          "pockets, chamfers, radii, bar length and miter, insert and nut pockets). Without teile: one sheet per bill "
          "of materials position of every manufactured part (bar stock, plates, 3D prints) plus the assembly sheet "
          "with item balloons and parts list. Existing sheets keep Kevin's edits and are recomputed. Check every sheet "
          "with zeichnung_bild afterwards and fix missing or wrong dimensions with zeichnung_bearbeiten.", ADDITIVE)
    async def zeichnung_erstellen(
        teile: Annotated[list[str] | None, Field(description="Part names or group prefixes; omit for all manufactured "
                                                            "parts plus the assembly")] = None,
        art: Annotated[Literal["teil", "baugruppe", "zusammenbau"], Field(
            description="teil: one sheet per part; baugruppe: one sheet for the given group(s); zusammenbau: "
                        "assembly sheet")] = "teil",
        format: Annotated[str | None, Field(description="Fixed sheet format, e.g. 'A4', 'A3 quer', 'A4 hoch'; omit "
                                                        "to choose automatically")] = None,  # noqa: A002
    ) -> CallToolResult:
        try:
            res = await t.work("erstellt Zeichnungen", svc.drawing_create, teile, art, format)
        except ValueError as exc:
            return fmt.error_result(f"Ungültige Eingabe: {exc}")
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Zeichnungen nicht erstellt: {err}", res)
        blaetter = res.get("blaetter") or []
        lines = [f"{fmt.plural(len(blaetter), 'Blatt', 'Blätter')} gerechnet ({res.get('ordner')}):"]
        for b in blaetter:
            if not b.get("ok"):
                lines.append(f"- {b.get('id')}: Fehler {b.get('fehler')}")
                continue
            lines.append(_blatt_zeile(b) + (" (neu)" if b.get("neu") else " (vorhanden, aktualisiert)"))
            lines += _masse_text(b.get("masse") or [], 25)
            for a in b.get("allgemein") or []:
                lines.append(f"  Angabe: {a}")
            lines += _pruef_text(b.get("pruefung") or [])
            for h in b.get("hinweise") or []:
                lines.append(f"  Hinweis: {h}")
        lines.append("Als Nächstes jedes Blatt mit zeichnung_bild prüfen (nicht an Kevin schicken).")
        return fmt.result("\n".join(lines), res)

    @tool("zeichnung_bearbeiten", "Zeichnung bearbeiten",
          "Edit a drawing sheet with the operations of DRAWING_EDIT (as Kevin does in the app). Ops: "
          "{op:'mass_neu', art:'linear'|'durchmesser'|'radius'|'winkel'|'bohrung'|'fase', ansicht:'v1', "
          "bezuege:[{merkmal:'seite:x-'}, {merkmal:'bohrung:2'}] or clicks [{ansicht, punkt:[x,y]} in sheet mm], "
          "richtung:'x'|'y'|'frei', versatz, text ('<>' = measured value), toleranz}; {op:'mass_verschieben', id, "
          "versatz | text_lage}; {op:'mass_loeschen', id} (auto dimensions are then suppressed); {op:'mass_aendern', "
          "id, text, toleranz}; {op:'ansicht_neu', art:'vorn'|'oben'|'links'|…|'iso'|'schnitt'|'einzelheit', lage, "
          "schnitt:{von, ebene:{punkt, normale}, name}, einzelheit:{von, mitte, radius, faktor}}; "
          "{op:'ansicht_verschieben', id, lage}; {op:'ansicht_loeschen', id}; {op:'massstab', wert:'1:2'}; "
          "{op:'format', wert:'A3', ausrichtung}; {op:'notiz', text, lage, zeiger}; {op:'notiz_loeschen', id}; "
          "{op:'schriftfeld', feld, wert}; {op:'auto', ansichten, masse, zuruecksetzen}; "
          "{op:'unterdrueckung_aufheben', index}. Feature ids (bohrung:1, lochbild:1, seite:x-, ende:a, tasche:1, "
          "fase:1, radius:1 …) are listed in the result of zeichnung_erstellen and zeichnungen.", WRITES)
    async def zeichnung_bearbeiten(
        blatt: Annotated[str, Field(description="Sheet id, e.g. 'seitenstange-links-rohr-1'")],
        ops: Annotated[list[dict[str, Any]], Field(description="Operations, applied in order")],
    ) -> CallToolResult:
        if not ops:
            return fmt.error_result("Ungültige Eingabe: ops ist leer")
        res = await t.work(f"bearbeitet Zeichnung {blatt}", svc.drawing_edit, blatt, ops, "agent")
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Zeichnung {blatt} nicht bearbeitet: {err}", res)
        ergebnisse = res.get("ergebnisse") or []
        fehler = [e for e in ergebnisse if not e.get("ok")]
        lines = [f"{len(ergebnisse) - len(fehler)} von {len(ergebnisse)} Operationen ausgeführt."]
        for e in ergebnisse:
            lines.append(f"- {e.get('op')}: " + ("ok" + (f" ({e.get('id')})" if e.get("id") else "") if e.get("ok")
                                                  else f"Fehler: {e.get('fehler')}"))
        b = res.get("blatt") or {}
        if b:
            lines.append(_blatt_zeile(b))
            lines += _masse_text(b.get("masse") or [], 40)
            lines += _pruef_text(b.get("pruefung") or [])
        if fehler:
            return fmt.error_result("\n".join(lines), res)
        return fmt.result("\n".join(lines), res)

    @tool("zeichnung_bild", "Zeichnung als Bild",
          "PNG of a drawing sheet, rendered in the kernel from the same vectors the app draws. For checking your own "
          "work only (layout, missing or doubled dimensions, overlaps): do not show it to Kevin, he sees the sheet in "
          "the app.", READ_ONLY)
    async def zeichnung_bild(
        blatt: Annotated[str, Field(description="Sheet id")],
        breite: Annotated[int, Field(ge=400, le=4000, description="Image width in px")] = 1800,
    ) -> CallToolResult:
        res = await t.work(f"prüft Zeichnung {blatt}", svc.drawing_image, blatt, breite)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Kein Bild von {blatt}: {err}")
        png = res.get("png") or b""
        b = res.get("blatt") or {}
        lines = [f"Blatt {blatt}: {res.get('breite')} × {res.get('hoehe')} px.", _blatt_zeile(b) if b else ""]
        lines += _pruef_text(b.get("pruefung") or [])
        data = {k: v for k, v in res.items() if k != "png"}
        return fmt.result("\n".join(x for x in lines if x), data, extra=[fmt.image_block(png)])
