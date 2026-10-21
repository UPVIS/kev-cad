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
    for key in ("volume", "area", "mass", "material", "faces", "edges"):
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
    data = {
        "ok": True,
        "run": run_no,
        "duration_ms": res.get("duration_ms"),
        "parts": [part_data(p) for p in parts],
        "steps": steps,
        "warnings": warnings,
        "params": params,
    }
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
