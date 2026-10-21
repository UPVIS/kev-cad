"""Blatt als Bild: Nachricht DRAWING → SVG (Vektor, Blatt-mm) → PNG über ``rsvg-convert`` (auf dem Mac vorhanden).

Dient dem Agenten zur Prüfung seiner Zeichnungen (MCP ``zeichnung_bild``); Kevin sieht das Blatt in der App, die
dieselben Vektoren mit CoreGraphics zeichnet. Linienbreiten nach ISO 128-20 Liniengruppe 0,5 (breit 0,5 mm, schmal
0,25 mm), Strichlängen nach ISO 128-20 (Strich 12 d, Lücke 3 d, Punkt 0,5 d).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.zeichner import lies_nutzlast

STIL = {
    "sichtbar": 'stroke="#000" stroke-width="0.5"',
    "verdeckt": 'stroke="#000" stroke-width="0.25" stroke-dasharray="3,1"',
    "mitte": 'stroke="#000" stroke-width="0.25" stroke-dasharray="6,1,0.5,1"',
    "schnitt": 'stroke="#000" stroke-width="0.5" stroke-dasharray="6,1,0.5,1"',
    "schraffur": 'stroke="#000" stroke-width="0.18"',
    "duenn": 'stroke="#000" stroke-width="0.25"',
}
VERSAL = 0.72  # Versalhöhe / Schriftgröße bei Helvetica


def _pfad(pl: np.ndarray, H: float) -> str:
    pts = " ".join(f"{x:.3f},{H - y:.3f}" for x, y in pl)
    return f"M{pts.replace(' ', ' L', 1) if False else pts}"


def _polyline(pl: Any, H: float, stil: str, farbe: str | None = None) -> str:
    pts = " ".join(f"{float(x):.3f},{H - float(y):.3f}" for x, y in pl)
    if farbe:
        stil = stil.replace('stroke="#000"', f'stroke="{farbe}"')
    return f'<polyline points="{pts}" fill="none" {stil} stroke-linejoin="round" stroke-linecap="round"/>'


def _text(text: str, x: float, y: float, h: float, winkel: float, anker: str, H: float, farbe: str = "#000") -> str:
    a = {"links": "start", "mitte": "middle", "rechts": "end"}.get(anker, "middle")
    groesse = h / VERSAL
    return (f'<text transform="translate({x:.3f},{H - y:.3f}) rotate({-winkel:.3f})" font-family="Helvetica, Arial, '
            f'sans-serif" font-size="{groesse:.3f}" text-anchor="{a}" fill="{farbe}">{escape(str(text))}</text>')


def svg(kopf: dict[str, Any], nutzlast: bytes) -> str:
    W, H = kopf.get("blattgroesse") or [297, 210]
    gruppen = lies_nutzlast(kopf, nutzlast)
    teile = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">',
             f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fff"/>']
    for linien in gruppen:
        for art, ls in linien.items():
            stil = STIL.get(art, STIL["duenn"])
            for pl in ls:
                teile.append(_polyline(pl, H, stil))
    for poly in kopf.get("gefuellt") or []:
        pts = " ".join(f"{x:.3f},{H - y:.3f}" for x, y in poly)
        teile.append(f'<polygon points="{pts}" fill="#000"/>')
    for t in kopf.get("texte") or []:
        teile.append(_text(t["text"], t["lage"][0], t["lage"][1], t.get("hoehe", 3.5), t.get("winkel", 0.0),
                           t.get("anker", "links"), H))
    for m in kopf.get("masse") or []:
        farbe = "#d00" if m.get("verwaist") else ("#0a5" if m.get("quelle") in ("kevin", "agent") else "#000")
        for pl in m.get("linien") or []:
            teile.append(_polyline(pl, H, STIL["duenn"], farbe))
        for p in m.get("pfeile") or []:
            poly = p.get("polygon") or []
            if poly:
                pts = " ".join(f"{x:.3f},{H - y:.3f}" for x, y in poly)
                teile.append(f'<polygon points="{pts}" fill="{farbe}"/>')
        if m.get("text") and m.get("text_lage"):
            x, y = m["text_lage"]
            teile.append(_text(m["text"], x, y, m.get("text_hoehe", 3.5), m.get("text_winkel", 0.0), "mitte", H,
                               farbe))
        for t in m.get("texte") or []:
            teile.append(_text(t["text"], t["lage"][0], t["lage"][1], t.get("hoehe", 3.5), t.get("winkel", 0.0),
                               t.get("anker", "mitte"), H, farbe))
    teile.append("</svg>")
    return "\n".join(teile)


def png(kopf: dict[str, Any], nutzlast: bytes, breite: int = 1800) -> bytes:
    """PNG des Blatts; ``breite`` in Pixel."""
    prog = shutil.which("rsvg-convert") or ("/opt/homebrew/bin/rsvg-convert"
                                            if Path("/opt/homebrew/bin/rsvg-convert").exists() else None)
    if prog is None:
        raise RuntimeError("rsvg-convert fehlt (brew install librsvg)")
    with tempfile.TemporaryDirectory(prefix="kczb") as d:
        src = Path(d) / "blatt.svg"
        dst = Path(d) / "blatt.png"
        src.write_text(svg(kopf, nutzlast), encoding="utf-8")
        subprocess.run([prog, "-w", str(int(breite)), "-b", "white", "-o", str(dst), str(src)], check=True,
                       capture_output=True, timeout=60)
        return dst.read_bytes()
