"""Materialien für Renderings (Phase 7, KATALOG.md „Material“, Feld ``render``).

Ein Teil bekommt eine PBR-Beschreibung (physikalisch basiert: Basisfarbe, metallisch, Rauheit) und eine Oberfläche, aus
der App (RealityKit) und Blender ihre Muster erzeugen. Reihenfolge der Quellen:

1. ``render`` des Katalogmaterials (mitgeliefert für alle Materialien des Normkatalogs),
2. sonst abgeleitet aus ``farbe``, ``metallisch``, ``rauheit`` und ``gruppe`` des Materials,
3. ohne Material: Teilfarbe, matt.

Die Farbe aus model.py hat Vorrang, wenn sie von der Katalogfarbe abweicht (farbiges PLA, schwarz eloxiert): dann ist
sie die Basisfarbe, Glanz und Metall bleiben vom Material.
"""

from __future__ import annotations

import re
from typing import Any

OBERFLAECHEN: dict[str, str] = {
    "glatt": "glatt, gleichmäßig",
    "gebuerstet": "Metall gebürstet (Schliff in einer Richtung)",
    "eloxiert": "Aluminium eloxiert (seidenmatt, leichte Klarschicht)",
    "verzinkt": "Stahl verzinkt (Zinkblumen, fleckiger Glanz)",
    "walzhaut": "Stahl roh (Walzhaut, dunkel, fleckig)",
    "pulver": "pulverbeschichtet oder lackiert (feine Orangenhaut)",
    "guss": "Guss (rau, körnig)",
    "schichten": "3D-Druck FDM (Schichtlinien quer zur Druckrichtung)",
    "harz": "Harzdruck (glatt, leicht glänzend)",
    "holz": "Holz (Maserung)",
    "gummi": "Gummi (matt, feine Struktur)",
    "schaum": "Schaumstoff (sehr matt, porig)",
    "glas": "durchsichtig (Acrylglas, Polycarbonat)",
    "beton": "Beton (rau, mineralisch)",
}

# Felder in ``render`` (KATALOG.md) mit Wertebereich
ZAHLEN = ("metallisch", "rauheit", "klarlack", "klarlack_rauheit", "anisotropie", "durchsichtig", "schichthoehe")

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")

# Rückfall je Gruppe, wenn ein Material kein ``render`` hat: Oberfläche, metallisch, Rauheit (angenommen nach den
# üblichen Werten für physikalisch basiertes Rendern; Metalle metallisch 1, Nichtmetalle 0).
_GRUPPE: dict[str, tuple[str, float, float]] = {
    "stahl": ("walzhaut", 0.85, 0.5),
    "edelstahl": ("gebuerstet", 1.0, 0.28),
    "aluminium": ("eloxiert", 1.0, 0.42),
    "buntmetall": ("glatt", 1.0, 0.3),
    "guss": ("guss", 0.7, 0.7),
    "holz": ("holz", 0.0, 0.62),
    "holzwerkstoff": ("holz", 0.0, 0.7),
    "kunststoff": ("glatt", 0.0, 0.45),
    "elastomer": ("gummi", 0.0, 0.85),
    "schaumstoff": ("schaum", 0.0, 0.95),
    "mineralisch": ("beton", 0.0, 0.9),
}


def hex_rgb(text: Any) -> list[float] | None:
    """„#8A9099“ → [0.541, 0.565, 0.6] (sRGB 0…1) oder None."""
    if not isinstance(text, str):
        return None
    m = _HEX.match(text.strip())
    if not m:
        return None
    h = m.group(1)
    return [round(int(h[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)]


def validate_render(spec: Any, who: str = "Material") -> list[str]:
    """Fehler im Feld ``render`` eines Materials (leer = gültig)."""
    if not isinstance(spec, dict):
        return [f"{who}: render muss ein Objekt sein"]
    errors: list[str] = []
    if "basisfarbe" in spec and spec["basisfarbe"] is not None and hex_rgb(spec["basisfarbe"]) is None:
        errors.append(f"{who}: render.basisfarbe ist kein sRGB-Hex wie \"#C8CCD0\"")
    for key in ZAHLEN:
        if key in spec and spec[key] is not None:
            v = spec[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errors.append(f"{who}: render.{key} muss eine Zahl sein")
            elif key == "schichthoehe":
                if not 0.02 <= float(v) <= 1.0:
                    errors.append(f"{who}: render.schichthoehe {v:g} mm ist unplausibel (0,02 bis 1)")
            elif not 0 <= float(v) <= 1:
                errors.append(f"{who}: render.{key} muss zwischen 0 und 1 liegen")
    o = spec.get("oberflaeche")
    if o is not None and o not in OBERFLAECHEN:
        errors.append(f"{who}: render.oberflaeche {o!r} unbekannt ({', '.join(OBERFLAECHEN)})")
    return errors


def _num(v: Any, default: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return float(v)


def _close(a: list[float] | None, b: list[float] | None, tol: float = 2.5 / 255) -> bool:
    if a is None or b is None:
        return False
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


def material_pbr(mat: dict[str, Any] | None) -> dict[str, Any]:
    """PBR-Beschreibung eines Katalogmaterials (ohne Teilfarbe)."""
    if not mat:
        return {"basisfarbe": [0.72, 0.75, 0.79], "metallisch": 0.0, "rauheit": 0.5, "oberflaeche": "glatt",
                "klarlack": 0.0, "klarlack_rauheit": 0.1, "anisotropie": 0.0, "durchsichtig": 0.0,
                "quelle": "ohne_material"}
    gruppe = str(mat.get("gruppe") or "").strip().lower()
    o_def, m_def, r_def = _GRUPPE.get(gruppe, ("glatt", 0.0, 0.5))
    if mat.get("druckbar"):
        o_def = "schichten"
    spec = mat.get("render") if isinstance(mat.get("render"), dict) else None
    farbe = hex_rgb(mat.get("farbe")) or [0.72, 0.75, 0.79]
    out: dict[str, Any] = {
        "basisfarbe": farbe,
        "metallisch": _num(mat.get("metallisch"), m_def),
        "rauheit": _num(mat.get("rauheit"), r_def),
        "oberflaeche": o_def,
        "klarlack": 0.0,
        "klarlack_rauheit": 0.1,
        "anisotropie": 0.0,
        "durchsichtig": 0.0,
        "quelle": "abgeleitet",
    }
    if spec is not None:
        out["quelle"] = "katalog"
        bf = hex_rgb(spec.get("basisfarbe"))
        if bf is not None:
            out["basisfarbe"] = bf
        for key in ZAHLEN:
            if key in spec and spec[key] is not None and not isinstance(spec[key], bool):
                out[key] = float(spec[key])
        if spec.get("oberflaeche") in OBERFLAECHEN:
            out["oberflaeche"] = spec["oberflaeche"]
    if out["oberflaeche"] == "schichten":
        out.setdefault("schichthoehe", 0.2)
    return out


def part_pbr(header: dict[str, Any], mat: dict[str, Any] | None) -> dict[str, Any]:
    """PBR-Beschreibung eines gezeigten Teils aus dem Kopf von PART_UPSERT und seinem Katalogmaterial."""
    out = material_pbr(mat)
    color = header.get("color")
    teilfarbe = [float(c) for c in color[:3]] if isinstance(color, list) and len(color) >= 3 else None
    katalogfarbe = hex_rgb(mat.get("farbe")) if mat else None
    if teilfarbe is not None and (mat is None or not _close(teilfarbe, katalogfarbe)):
        out["basisfarbe"] = [round(c, 4) for c in teilfarbe]
        if mat is not None:
            out["quelle"] = "teilfarbe"
    if isinstance(color, list) and len(color) >= 4 and float(color[3]) < 0.99:
        out["durchsichtig"] = max(out["durchsichtig"], round(1.0 - float(color[3]), 3))
    if header.get("druckteil") and out["oberflaeche"] not in ("harz",):
        out["oberflaeche"] = "schichten"
        out.setdefault("schichthoehe", 0.2)
    out["material"] = (mat or {}).get("id") or header.get("material")
    return out


def schluessel(pbr: dict[str, Any]) -> str:
    """Gleiche Darstellung, gleicher Schlüssel (Blender legt je Schlüssel ein Material an)."""
    farbe = ",".join(f"{c:.3f}" for c in pbr.get("basisfarbe", [0, 0, 0]))
    zahlen = ",".join(f"{float(pbr.get(k, 0) or 0):.3f}" for k in ZAHLEN)
    return f"{pbr.get('oberflaeche')}|{farbe}|{zahlen}"
