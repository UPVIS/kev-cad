"""Ergebnisse der MCP-Werkzeuge: kurze deutsche Zusammenfassung plus strukturierte Daten.

Jedes Werkzeug liefert ein ``CallToolResult`` mit
- einem Textblock (Zusammenfassung für Kevin und den Agenten),
- einem zweiten Textblock mit den Daten als kompaktem JSON (für Clients, die ``structuredContent`` nicht an das Modell
  weiterreichen),
- ``structured_content`` mit denselben Daten (immer ein JSON-Objekt, wie es die Protokollversionen bis 2025-11-25
  verlangen).
"""

from __future__ import annotations

import json
import math
from typing import Any

from mcp_types import CallToolResult, ContentBlock, ImageContent, TextContent


# ---------------------------------------------------------------------------------------------------------------------
# Zahlen


def num(value: Any, digits: int = 3) -> str:
    """Zahl im deutschen Format: Dezimalkomma, Tausendergruppen mit Leerzeichen ab 10 000, Nullen am Ende gekürzt."""
    if value is None:
        return "–"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    x = float(value)
    if math.isnan(x) or math.isinf(x):
        return str(x)
    text = f"{x:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    whole, _, frac = text.partition(".")
    if len(whole) > 4:
        groups = []
        while len(whole) > 3:
            groups.insert(0, whole[-3:])
            whole = whole[:-3]
        groups.insert(0, whole)
        whole = " ".join(groups)
    return sign + whole + ("," + frac if frac else "")


def vec(values: Any, digits: int = 2) -> str:
    """Vektor als ``(x; y; z)`` mit deutschen Zahlen."""
    if not isinstance(values, (list, tuple)):
        return str(values)
    return "(" + "; ".join(num(v, digits) for v in values) + ")"


def bbox_size(bbox: dict[str, Any] | None) -> list[float] | None:
    if not bbox:
        return None
    size = bbox.get("size")
    if isinstance(size, (list, tuple)) and len(size) == 3:
        return [float(v) for v in size]
    lo, hi = bbox.get("min"), bbox.get("max")
    if isinstance(lo, (list, tuple)) and isinstance(hi, (list, tuple)) and len(lo) == 3 and len(hi) == 3:
        return [float(b) - float(a) for a, b in zip(lo, hi)]
    return None


def size_text(bbox: dict[str, Any] | None) -> str:
    size = bbox_size(bbox)
    if size is None:
        return "Maße unbekannt"
    return " × ".join(num(v, 2) for v in size) + " mm"


def ms_text(ms: Any) -> str:
    if not isinstance(ms, (int, float)):
        return ""
    return f"{num(ms / 1000, 2)} s" if ms >= 1000 else f"{num(ms, 0)} ms"


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


# ---------------------------------------------------------------------------------------------------------------------
# Ergebnisse


def to_jsonable(value: Any) -> Any:
    """Macht Antworten der Laufzeit JSON-tauglich (Bytes fallen weg, Tupel werden Listen, NaN wird null)."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items() if not isinstance(v, (bytes, bytearray))}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def result(summary: str, data: dict[str, Any] | None = None, *, error: bool = False, json_block: bool = True,
           extra: list[ContentBlock] | None = None) -> CallToolResult:
    """Baut das Werkzeugergebnis: Zusammenfassung, optional Bild o. ä., Daten als JSON-Text und structuredContent."""
    content: list[ContentBlock] = list(extra or [])
    content.append(TextContent(type="text", text=summary.strip()))
    structured = None
    if data is not None:
        structured = to_jsonable(data)
        if json_block:
            content.append(TextContent(type="text", text=json.dumps(structured, ensure_ascii=False,
                                                                    separators=(",", ":"))))
    return CallToolResult(content=content, structured_content=structured, is_error=error)


def error_result(message: str, data: dict[str, Any] | None = None) -> CallToolResult:
    return result(message, data, error=True)


def image_block(png: bytes) -> ImageContent:
    import base64

    return ImageContent(type="image", data=base64.b64encode(png).decode("ascii"), mime_type="image/png")


def service_error(res: Any) -> str | None:
    """Fehlertext, wenn die Laufzeit ``{"ok": False, "error": ...}`` geliefert hat, sonst None."""
    if not isinstance(res, dict) or res.get("ok", True) is not False:
        return None
    err = res.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err) if err else "Unbekannter Fehler im Kernel"


# ---------------------------------------------------------------------------------------------------------------------
# Teile und Läufe


def part_line(part: dict[str, Any]) -> str:
    bits = [size_text(part.get("bbox"))]
    if isinstance(part.get("volume"), (int, float)):
        bits.append(f"{num(part['volume'], 1)} mm³")
    if isinstance(part.get("mass"), (int, float)):
        bits.append(f"{num(part['mass'], 1)} g")
    if part.get("material"):
        bits.append(str(part["material"]))
    stock = part.get("stock")
    if isinstance(stock, dict) and stock.get("id"):
        text = f"Lagerteil {stock['id']}"
        if isinstance(stock.get("laenge"), (int, float)):
            text += f" {num(stock['laenge'], 1)} mm"
        g = stock.get("gehrung") or []
        if any(isinstance(v, (int, float)) and v for v in g):
            text += f" Gehrung {num(g[0], 1)}°/{num(g[1], 1)}°"
        bits.append(text)
    druck = part.get("druckteil")
    if isinstance(druck, dict):
        bits.append("Druckteil" + (" (Harz)" if druck.get("verfahren") == "harzdruck" else ""))
    if part.get("inventar") == "fehlt":
        bits.append("NICHT AUS DEM INVENTAR")
    if part.get("visible") is False:
        bits.append("ausgeblendet")
    return f"- {part.get('name', '?')}: " + " · ".join(bits)


def part_data(part: dict[str, Any]) -> dict[str, Any]:
    """Kompakte Teildaten für Laufergebnisse (vollständige Daten liefert ``parts``)."""
    out: dict[str, Any] = {"name": part.get("name")}
    size = bbox_size(part.get("bbox"))
    if size is not None:
        out["size"] = [round(v, 4) for v in size]
    if part.get("bbox"):
        out["bbox"] = {k: part["bbox"][k] for k in ("min", "max") if k in part["bbox"]}
    for key in ("volume", "area", "mass", "material", "faces", "edges", "stock", "druckteil", "inventar"):
        if part.get(key) is not None:
            out[key] = part[key]
    return out


def parts_tree(parts: list[dict[str, Any]]) -> str:
    """Teileliste als Baum; Baugruppen ergeben sich aus ``/`` im Namen."""
    lines: list[str] = []
    shown_groups: set[str] = set()
    for part in sorted(parts, key=lambda p: str(p.get("name", ""))):
        name = str(part.get("name", "?"))
        segments = name.split("/")
        for depth in range(1, len(segments)):
            group = "/".join(segments[:depth])
            if group not in shown_groups:
                shown_groups.add(group)
                lines.append("  " * (depth - 1) + f"{segments[depth - 1]}/")
        line = part_line({**part, "name": segments[-1]})
        lines.append("  " * (len(segments) - 1) + line)
    return "\n".join(lines)


def run_summary(res: dict[str, Any]) -> tuple[str, dict[str, Any], bool]:
    """Zusammenfassung eines Laufs: (Text, Daten, Fehler?)."""
    run_no = res.get("run")
    label = f"Lauf {run_no}" if run_no is not None else "Lauf"
    if res.get("ok") is False:
        err = res.get("error")
        if not isinstance(err, dict):
            err = {"message": str(err) if err else "Unbekannter Fehler"}
        line = err.get("line")
        head = f"{label} fehlgeschlagen" + (f" in Zeile {line}" if line else "") + f": {err.get('message', '')}"
        parts = [head]
        if err.get("excerpt"):
            parts.append(str(err["excerpt"]).rstrip())
        if err.get("hint"):
            parts.append(f"Hinweis: {err['hint']}")
        parts.append("Die letzte gute Geometrie bleibt im Viewer stehen. model.py korrigieren und erneut run aufrufen.")
        data = {"ok": False, "run": run_no, "error": err}
        if res.get("steps"):
            data["steps"] = res["steps"]
        return "\n".join(parts), data, True

    parts = res.get("parts") or []
    warnings = res.get("warnings") or []
    steps = res.get("steps") or []
    head = f"{label} fertig"
    if res.get("duration_ms") is not None:
        head += f" in {ms_text(res['duration_ms'])}"
    head += f": {plural(len(parts), 'Teil', 'Teile')}"
    if steps:
        head += f", {plural(len(steps), 'Schritt', 'Schritte')}"
    if warnings:
        head += f", {plural(len(warnings), 'Warnung', 'Warnungen')}"
    head += "."
    lines = [head]
    if parts:
        lines.append(parts_tree(parts))
    else:
        lines.append("Keine Teile gezeigt: show(teil, \"Name\") in model.py aufrufen.")
    params = res.get("params") or {}
    if params:
        lines.append("Parameter: " + ", ".join(f"{k}={num(v)}" for k, v in params.items()))
    for w in warnings:
        lines.append(f"Warnung: {w}")
    bom = res.get("bom") if isinstance(res.get("bom"), dict) else None
    if bom:
        lines.append(f"Stückliste: {bom_totals_line(bom.get('totals') or {})} (Details mit bom)")
        for w in (bom.get("warnings") or [])[:5]:
            lines.append(f"Hinweis Stückliste: {w}")
    data = {
        "ok": True,
        "run": run_no,
        "duration_ms": res.get("duration_ms"),
        "parts": [part_data(p) for p in parts],
        "steps": steps,
        "warnings": warnings,
        "params": params,
    }
    if bom:
        data["bom"] = bom
    violations = list(res.get("inventar_verstoesse") or [])
    if "inventar_regel" in res:
        data["inventar_regel"] = bool(res["inventar_regel"])
        data["inventar_verstoesse"] = violations
    if violations:
        from kevcad_kernel.bom import inventory_text

        lines.insert(0, inventory_text(violations))
        lines.insert(1, "Die Geometrie ist im Viewer zu sehen; Export und Stückliste gelten erst, wenn alles aus dem "
                        "Inventar kommt.")
        return "\n".join(lines), data, True
    return "\n".join(lines), data, False


def measure_line(m: dict[str, Any]) -> str:
    """Eine Zeile zu einer Messung oder einem ausgewählten Element."""
    refs = m.get("refs") or []
    text = m.get("text")
    if not text:
        values = m.get("values") or {}
        text = ", ".join(f"{k} {num(v) if isinstance(v, (int, float)) else v}" for k, v in values.items()
                         if not isinstance(v, (dict, list)))
    who = " ↔ ".join(refs) if refs else "?"
    return f"{who}: {text}" if text else who


def camera_text(camera: dict[str, Any] | None) -> str:
    if not camera:
        return "Kamera unbekannt"
    bits = []
    for key, value in camera.items():
        if isinstance(value, (list, tuple)):
            bits.append(f"{key} {vec(value)}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            bits.append(f"{key} {num(value, 3)}")
        else:
            bits.append(f"{key} {value}")
    return "Kamera: " + ", ".join(bits)


# ---------------------------------------------------------------------------------------------------------------------
# Phase 2: Lagerteile, Materialien, Stückliste


def table(rows: list[list[str]], right: set[int] | None = None) -> str:
    """Ausgerichtete Texttabelle; erste Zeile ist der Kopf. ``right``: rechtsbündige Spalten."""
    right = right or set()
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for n, row in enumerate(rows):
        cells = [c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(row)]
        out.append("  ".join(cells).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def money(value: Any) -> str:
    from kevcad_kernel.bom import eur

    return eur(value if isinstance(value, (int, float)) else None)


def masse_short(item: dict[str, Any]) -> str:
    masse = item.get("masse") or {}
    return ", ".join(f"{k} {num(v, 2) if isinstance(v, (int, float)) else v}" for k, v in masse.items())


def status_text(entry: dict[str, Any]) -> str:
    return "wartet auf Freigabe" if entry.get("status") == "vorgeschlagen" else "frei"


def stock_table(items: list[dict[str, Any]]) -> str:
    rows = [["id", "Name", "Norm", "Material", "kg/m", "Preis", "Ebene", "Status"]]
    for it in items:
        calc = it.get("berechnet") or {}
        kgm = calc.get("kg_je_m", it.get("kg_je_m"))
        rows.append([str(it.get("id", "?")), str(it.get("name", "")), str(it.get("norm") or ""),
                     str(it.get("material", "")), num(kgm, 2) if isinstance(kgm, (int, float)) else "",
                     str(calc.get("preis_text") or ""), str(it.get("ebene", "")), status_text(it)])
    return table(rows, right={4})


def stock_detail(res: dict[str, Any]) -> str:
    it = res.get("item") or {}
    mat = res.get("material") or {}
    lines = [f"{it.get('name', '?')} ({it.get('id', '?')}), Ebene {it.get('ebene', '?')}"
             + (", vorgeschlagen – wartet auf Kevins Freigabe im Lagerkatalog" if it.get("status") == "vorgeschlagen"
                else "")]
    lines.append(f"Art {it.get('art', '?')}" + (f", Norm {it['norm']}" if it.get("norm") else "")
                 + f", Maße: {masse_short(it)}")
    lines.append(f"Material: {mat.get('name') or it.get('material', '?')}"
                 + (f" ({num(mat['dichte'], 3)} g/cm³)" if isinstance(mat.get("dichte"), (int, float)) else ""))
    bits = []
    if isinstance(res.get("querschnitt_mm2"), (int, float)):
        bits.append(f"Querschnitt {num(res['querschnitt_mm2'], 1)} mm²")
    if isinstance(res.get("kg_je_m"), (int, float)):
        source = "Tabelle" if it.get("kg_je_m") is not None else "berechnet"
        bits.append(f"{num(res['kg_je_m'], 3)} kg/m ({source})")
    if it.get("stangenlaenge"):
        bits.append(f"Stange {num(it['stangenlaenge'], 0)} mm")
    if it.get("platte"):
        bits.append("Format " + " × ".join(num(v, 0) for v in it["platte"]) + " mm")
    if bits:
        lines.append(", ".join(bits))
    preis = it.get("preis") or {}
    if res.get("preis_text"):
        src = ", ".join(str(preis[k]) for k in ("quelle", "stand") if preis.get(k))
        lines.append(f"Preis: {res['preis_text']}" + (f" ({src})" if src else ""))
    if it.get("tags"):
        lines.append("Tags: " + ", ".join(it["tags"]))
    if res.get("beispiel"):
        lines.append("In model.py:\n" + str(res["beispiel"]))
    return "\n".join(lines)


def material_table(mats: list[dict[str, Any]]) -> str:
    rows = [["id", "Name", "Gruppe", "g/cm³", "€/kg", "druckbar", "Aliase", "Ebene", "Status"]]
    for m in mats:
        pkg = m.get("preis_je_kg")
        rows.append([str(m.get("id", "?")), str(m.get("name", "")), str(m.get("gruppe", "")),
                     num(m.get("dichte"), 3), num(pkg, 2) if isinstance(pkg, (int, float)) else "",
                     "ja" if m.get("druckbar") is True else "", ", ".join(m.get("aliase") or []),
                     str(m.get("ebene", "")), status_text(m)])
    return table(rows, right={3, 4})


def bom_totals_line(totals: dict[str, Any]) -> str:
    from kevcad_kernel.bom import de_num, eur

    text = (f"{plural(int(totals.get('positionen', 0)), 'Position', 'Positionen')}, "
            f"{plural(int(totals.get('teile', 0)), 'Teil', 'Teile')}, {de_num(totals.get('kg') or 0, 2)} kg")
    if totals.get("preis") is not None:
        text += f", {eur(totals['preis'])}"
        if totals.get("preis_hinweis"):
            text += f" ({totals['preis_hinweis']})"
    return text


def bom_text(bom: dict[str, Any]) -> str:
    """Stückliste als ausgerichtete Tabelle, darunter Zuschnitt und Hinweise."""
    from kevcad_kernel.bom import cut_lines, de_fixed, de_num, gehrung_text

    lines_ = bom.get("lines") or []
    head = f"Stückliste (Lauf {bom.get('run', '?')}): {bom_totals_line(bom.get('totals') or {})}"
    if not lines_:
        out = [head, "Keine Positionen: Lagerteile mit lager.teil(...).verbauen(...) bauen oder Teile mit material= "
                     "zeigen."]
    else:
        rows = [["Pos", "Anz", "Benennung", "Maße", "Gehrung", "Material", "kg", "€"]]
        for ln in lines_:
            g = gehrung_text(ln.get("gehrung")) if not ln.get("eigenteil") else ""
            name = str(ln.get("benennung", "")) + (" (Eigenteil)" if ln.get("eigenteil") else "") + (
                " (Druckteil)" if ln.get("art") == "druckteil" else "")
            rows.append([str(ln.get("pos", "")), str(ln.get("anzahl", "")), name, str(ln.get("masse_text", "")), g,
                         str(ln.get("material") or ""),
                         de_num(ln["kg"], 2) if isinstance(ln.get("kg"), (int, float)) else "–",
                         de_fixed(ln["preis"]) if isinstance(ln.get("preis"), (int, float)) else "–"])
        out = [head, "", table(rows, right={0, 1, 6, 7})]
    cuts = bom.get("cuts") or []
    if cuts:
        out.append("")
        out.append(f"Zuschnitt (Sägeschnitt {de_num(cuts[0].get('saegeschnitt', 3))} mm):")
        for cut in cuts:
            n = len(cut.get("stangen") or [])
            line = (f"{cut.get('benennung')}: {plural(n, 'Stange', 'Stangen')} à {de_num(cut.get('stangenlaenge'))} "
                    f"mm, Verschnitt {de_num(cut.get('verschnitt_prozent'), 1)} %")
            if cut.get("preis_stangen") is not None:
                line += f", ganze Stangen {money(cut['preis_stangen'])}"
            out.append(line)
            out += [f"  {t}" for t in cut_lines(cut)]
    warnings = bom.get("warnings") or []
    if warnings:
        out.append("")
        out += [f"Hinweis: {w}" for w in warnings]
    return "\n".join(out)
