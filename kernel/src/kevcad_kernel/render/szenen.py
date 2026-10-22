"""Szenen, Größen, Ansichten und Hintergründe für Renderings (Phase 7, PLAN-PHASE7-RENDERINGS.md R8, R9).

Eine Szene beschreibt Licht und Hintergrund; App (RealityKit) und Blender setzen sie je auf ihre Art um:

- ``studio``: heller Hintergrund, weicher Schatten, eigene Softbox-Umgebung (im Code erzeugt).
- ``werkstatt``: Studiohalle mit Lampen (HDRI, CC0, Poly Haven über Blender), Hintergrund unscharf aus der Umgebung.
- ``draussen``: Garten bei Tageslicht (HDRI, CC0, Poly Haven über Blender).
- ``wohnraum``: Innenraum mit Fensterlicht (HDRI, CC0).
- ``freigestellt``: Studio-Licht, durchsichtiger Hintergrund, Schatten als halbdurchsichtiges Schwarz.

Eigene Umgebungen: ``umgebung`` als Pfad zu einer .hdr oder eine .hdr in ``<Datenordner>/umgebungen/``.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

UMGEBUNGEN_DIR = Path(__file__).resolve().parent / "umgebungen"

SZENEN: dict[str, dict[str, Any]] = {
    "studio": {"titel": "Studio", "umgebung": None, "licht": "studio", "hintergrund": "#F1F2F4", "boden": True,
               "staerke": 1.0, "drehung": 0.0,
               "text": "heller Hintergrund, weicher Schatten, Softboxen"},
    "werkstatt": {"titel": "Werkstatt", "umgebung": "halle.hdr", "licht": "umgebung", "hintergrund": "umgebung",
                  "boden": True, "staerke": 1.6, "drehung": 0.0,
                  "text": "Halle mit Lampen und grauem Boden (HDRI, CC0), Hintergrund unscharf"},
    "draussen": {"titel": "Draußen", "umgebung": "garten.hdr", "licht": "umgebung", "hintergrund": "umgebung",
                 "boden": True, "staerke": 1.0, "drehung": 0.0,
                 "text": "Garten bei Tageslicht (HDRI, CC0), Hintergrund unscharf"},
    "wohnraum": {"titel": "Wohnraum", "umgebung": "innenraum.hdr", "licht": "umgebung", "hintergrund": "umgebung",
                 "boden": True, "staerke": 1.0, "drehung": 0.0,
                 "text": "Innenraum mit Fensterlicht (HDRI, CC0), Hintergrund unscharf"},
    "freigestellt": {"titel": "Freigestellt", "umgebung": None, "licht": "studio", "hintergrund": "transparent",
                     "boden": True, "staerke": 1.0, "drehung": 0.0,
                     "text": "Studio-Licht, durchsichtiger Hintergrund mit Schatten (PNG mit Alpha)"},
}

# Breite × Höhe in Pixeln
GROESSEN: dict[str, tuple[int, int]] = {
    "vorschau": (960, 540),
    "hd": (1920, 1080),
    "4k": (3840, 2160),
    "quadrat": (2048, 2048),
    "hochkant": (1080, 1350),
    "story": (1080, 1920),
    "deckblatt": (2400, 1600),
    "a4": (3508, 2480),
}
GROESSEN_TEXT: dict[str, str] = {
    "vorschau": "Vorschau 960 × 540", "hd": "Full HD 1920 × 1080", "4k": "4K UHD 3840 × 2160",
    "quadrat": "Quadrat 2048 × 2048", "hochkant": "Instagram hochkant 1080 × 1350", "story": "Story 1080 × 1920",
    "deckblatt": "Deckblatt 2400 × 1600 (3:2)", "a4": "A4 quer 300 dpi 3508 × 2480",
}
MAX_KANTE = 8192

QUALITAETEN: dict[str, str] = {
    "schnell": "RealityKit in der App, ein bis wenige Sekunden",
    "foto": "Blender Cycles im Hintergrund, eine bis wenige Minuten",
}

# Kamera: aktuelle Ansicht, Produktansicht, Standardansichten des Viewers
ANSICHTEN: tuple[str, ...] = ("aktuell", "produkt", "iso", "iso_front_left", "iso_back_right", "iso_back_left",
                              "front", "back", "left", "right", "top")

HINTERGRUENDE: dict[str, str | None] = {
    "szene": None, "weiss": "#FFFFFF", "hell": "#F1F2F4", "grau": "#D9DBDE", "dunkel": "#2A2C30",
    "schwarz": "#000000", "transparent": "transparent", "umgebung": "umgebung",
}

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
_GROESSE = re.compile(r"^\s*(\d{2,5})\s*[x×*]\s*(\d{2,5})\s*$")


class RenderFehler(ValueError):
    """Eingabe für ein Rendering ist ungültig (Meldung für Agent und App)."""


def groesse(wert: Any) -> tuple[int, int]:
    """„hd“, „1920x1080“, [1920, 1080] oder {"breite", "hoehe"} → (Breite, Höhe)."""
    if wert is None or wert == "":
        return GROESSEN["hd"]
    if isinstance(wert, str):
        key = wert.strip().lower().replace(" ", "")
        if key in GROESSEN:
            return GROESSEN[key]
        m = _GROESSE.match(wert)
        if not m:
            raise RenderFehler(f"groesse {wert!r} unbekannt: {', '.join(GROESSEN)} oder „B x H“ (z. B. 2400x1600)")
        w, h = int(m.group(1)), int(m.group(2))
    elif isinstance(wert, (list, tuple)) and len(wert) == 2:
        w, h = int(wert[0]), int(wert[1])
    elif isinstance(wert, dict):
        w, h = int(wert.get("breite") or wert.get("width") or 0), int(wert.get("hoehe") or wert.get("height") or 0)
    else:
        raise RenderFehler(f"groesse {wert!r} unbekannt")
    if not (16 <= w <= MAX_KANTE and 16 <= h <= MAX_KANTE):
        raise RenderFehler(f"groesse {w} × {h} liegt außerhalb von 16 bis {MAX_KANTE} Pixeln je Kante")
    return w, h


def eigene_umgebungen(datenordner: Path | None) -> dict[str, Path]:
    """Eigene .hdr im Datenordner der App (Name ohne Endung → Pfad)."""
    if datenordner is None:
        return {}
    d = datenordner / "umgebungen"
    if not d.is_dir():
        return {}
    return {p.stem.lower(): p for p in sorted(d.glob("*.hdr"))}


def szene(name: Any, *, hintergrund: Any = None, umgebung: Any = None, datenordner: Path | None = None) -> dict[str, Any]:
    """Szene für einen Auftrag: Licht, Umgebung (absoluter Pfad oder None), Hintergrund (Hex, „umgebung“ oder
    „transparent“), Boden mit Schatten."""
    key = str(name or "studio").strip().lower().replace("ß", "ss")
    key = {"draußen": "draussen", "aussen": "draussen", "außen": "draussen", "outdoor": "draussen",
           "freisteller": "freigestellt", "transparent": "freigestellt", "innen": "werkstatt"}.get(key, key)
    eigene = eigene_umgebungen(datenordner)
    if key in SZENEN:
        s = dict(SZENEN[key])
    elif key in eigene:
        s = {"titel": key, "umgebung": str(eigene[key]), "licht": "umgebung", "hintergrund": "umgebung", "boden": True,
             "staerke": 1.0, "drehung": 0.0, "text": f"eigene Umgebung {eigene[key].name}"}
    else:
        namen = list(SZENEN) + list(eigene)
        raise RenderFehler(f"szene {name!r} unbekannt: {', '.join(namen)}")
    s["name"] = key
    if umgebung:
        p = Path(str(umgebung)).expanduser()
        if not p.is_absolute() and str(umgebung).lower() in eigene:
            p = eigene[str(umgebung).lower()]
        if not p.is_file():
            raise RenderFehler(f"umgebung {umgebung!r} nicht gefunden (Pfad zu einer .hdr)")
        if p.suffix.lower() != ".hdr":
            raise RenderFehler("umgebung muss eine Radiance-HDR (.hdr) sein; EXR liest macOS nicht immer")
        s["umgebung"] = str(p)
        s["licht"] = "umgebung"
        if s["hintergrund"] not in ("transparent",):
            s["hintergrund"] = "umgebung"
    elif s.get("umgebung") and not Path(s["umgebung"]).is_absolute():
        s["umgebung"] = str(UMGEBUNGEN_DIR / s["umgebung"])
    if hintergrund not in (None, "", "szene"):
        h = str(hintergrund).strip().lower()
        if h in HINTERGRUENDE:
            wert = HINTERGRUENDE[h]
        elif _HEX.match(h):
            wert = "#" + h.lstrip("#").upper()
        else:
            raise RenderFehler(f"hintergrund {hintergrund!r} unbekannt: {', '.join(HINTERGRUENDE)} oder Hex wie #F0F0F0")
        if wert == "umgebung" and not s.get("umgebung"):
            raise RenderFehler(f"Szene {key} hat keine Umgebung als Hintergrund")
        s["hintergrund"] = wert
    s["transparent"] = s["hintergrund"] == "transparent"
    return s


def ansicht(wert: Any) -> str:
    if wert is None or wert == "":
        return "aktuell"
    a = str(wert).strip().lower()
    a = {"current": "aktuell", "viewer": "aktuell", "product": "produkt", "vorne": "front", "hinten": "back",
         "links": "left", "rechts": "right", "oben": "top", "isometrisch": "iso"}.get(a, a)
    if a not in ANSICHTEN:
        raise RenderFehler(f"ansicht {wert!r} unbekannt: {', '.join(ANSICHTEN)}")
    return a


def qualitaet(wert: Any) -> str:
    q = str(wert or "schnell").strip().lower()
    q = {"fast": "schnell", "photo": "foto", "fotorealistisch": "foto", "cycles": "foto", "blender": "foto",
         "realitykit": "schnell"}.get(q, q)
    if q not in QUALITAETEN:
        raise RenderFehler(f"qualitaet {wert!r} unbekannt: schnell oder foto")
    return q


def sicherer_name(text: str) -> str:
    out = re.sub(r"[^\w.\-]+", "-", text, flags=re.UNICODE).strip("-.")
    return out or "render"


def zielpfad(output_dir: Path, projekt: str, s: dict[str, Any], q: str, *, kamera: str | None = None,
             ziel: Any = None, vorschau: bool = False) -> Path:
    """PNG unter ``<projekt>/output/renders/``; ``ziel`` relativ liegt dort, absolut wie angegeben."""
    renders = output_dir / "renders"
    if vorschau:
        return renders / ".vorschau" / f"vorschau-{q}.png"
    if ziel:
        p = Path(str(ziel)).expanduser()
        if not p.is_absolute():
            p = renders / p
        if p.suffix.lower() != ".png":
            p = p.with_suffix(".png")
        return p
    teile = [sicherer_name(projekt), s["name"]]
    if kamera:
        teile.append(sicherer_name(kamera.removeprefix("Kamera/")))
    teile += [q, time.strftime("%Y%m%d-%H%M%S")]
    p = renders / ("_".join(teile) + ".png")
    n = 2
    while p.exists():
        p = renders / ("_".join(teile) + f"-{n}.png")
        n += 1
    return p


def liste() -> dict[str, Any]:
    """Was es gibt (für MCP und Hilfe)."""
    return {"szenen": {k: v["text"] for k, v in SZENEN.items()}, "groessen": GROESSEN_TEXT,
            "qualitaeten": QUALITAETEN, "ansichten": list(ANSICHTEN),
            "hintergruende": [k for k in HINTERGRUENDE if k != "umgebung"] + ["#RRGGBB"]}
