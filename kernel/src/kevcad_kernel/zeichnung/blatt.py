"""Blatt: Formate (ISO 5457), Maßstäbe (ISO 5455), Rahmen, Schriftfeld (ISO 7200), Tabellen, Positionsnummern.

Alles in Blatt-mm, Ursprung links unten, y nach oben. Linien kommen als Polylinien je Linienart (``sichtbar`` = breit
0,5 mm für Rahmen und Tabellenrand, ``duenn`` = 0,25 mm für Unterteilungen), Texte als Wörterbücher
``{"text", "lage" [x, y], "hoehe" (Versalhöhe nach ISO 3098), "winkel", "anker" links|mitte|rechts, "art"}``;
``lage`` ist der Ankerpunkt auf der Grundlinie.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.geo2d import Rechteck, textbreite

# ISO 5457: beschnittene Formate (Breite × Höhe hochkant)
FORMATE = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A2": (420.0, 594.0), "A1": (594.0, 841.0),
           "A0": (841.0, 1189.0)}
RAND_LINKS = 20.0  # Heftrand
RAND = 10.0
# ISO 5455: empfohlene Maßstäbe
MASSSTAEBE = ("50:1", "20:1", "10:1", "5:1", "2:1", "1:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100", "1:200",
              "1:500", "1:1000")
SCHRIFTFELD_B = 180.0  # ISO 7200: höchstens 180 mm breit
SCHRIFTFELD_H = 40.0
TEXT_H = 3.5  # Versalhöhe Maßzahlen und Schriftfeldwerte (ISO 3098, Reihe 2,5 · 3,5 · 5 · 7)
TEXT_KLEIN = 2.5
TEXT_LABEL = 1.8
TEXT_TITEL = 5.0


def massstab_faktor(text: Any) -> float:
    """„1:2“ → 0.5, „2:1“ → 2.0, 0.5 → 0.5."""
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text or "1:1").replace(" ", "").replace("∶", ":")
    if ":" not in s:
        return float(s.replace(",", "."))
    a, b = s.split(":", 1)
    return float(a.replace(",", ".")) / float(b.replace(",", "."))


def massstab_text(f: float) -> str:
    """0.5 → „1:2“, 2 → „2:1“ (nächster Wert der Reihe, sonst als Bruch)."""
    for m in MASSSTAEBE:
        if abs(massstab_faktor(m) - f) < 1e-9:
            return m
    fr = Fraction(f).limit_denominator(1000)
    return f"{fr.numerator}:{fr.denominator}"


def blattgroesse(fmt: str, ausrichtung: str) -> tuple[float, float]:
    b, h = FORMATE.get(str(fmt).upper(), FORMATE["A4"])
    return (h, b) if ausrichtung == "quer" else (b, h)


@dataclass
class Grafik:
    """Linien je Art und Texte (Blatt-mm)."""

    linien: dict[str, list[np.ndarray]] = field(default_factory=lambda: {"sichtbar": [], "duenn": [], "mitte": []})
    texte: list[dict[str, Any]] = field(default_factory=list)
    flaechen: list[np.ndarray] = field(default_factory=list)  # gefüllte Polygone (Projektionssymbol nicht nötig)

    def linie(self, art: str, *punkte: Any) -> None:
        self.linien.setdefault(art, []).append(np.asarray(punkte, dtype=float).reshape(-1, 2))

    def rechteck(self, art: str, x0: float, y0: float, x1: float, y1: float) -> None:
        self.linie(art, (x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))

    def text(self, text: str, x: float, y: float, hoehe: float = TEXT_H, anker: str = "links", winkel: float = 0.0,
             art: str = "blatt") -> None:
        if text is None or text == "":
            return
        self.texte.append({"text": str(text), "lage": [round(x, 3), round(y, 3)], "hoehe": hoehe, "winkel": winkel,
                           "anker": anker, "art": art})

    def kreis(self, art: str, cx: float, cy: float, r: float, n: int = 48) -> None:
        t = np.linspace(0, 2 * math.pi, n + 1)
        self.linien.setdefault(art, []).append(np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], axis=1))

    def dazu(self, andere: Grafik) -> None:
        for k, v in andere.linien.items():
            self.linien.setdefault(k, []).extend(v)
        self.texte.extend(andere.texte)
        self.flaechen.extend(andere.flaechen)


def zeichenflaeche(breite: float, hoehe: float) -> Rechteck:
    """Innerhalb des Rahmens."""
    return Rechteck(RAND_LINKS, RAND, breite - RAND, hoehe - RAND)


def rahmen(breite: float, hoehe: float) -> Grafik:
    """Schneidekante (dünn), Zeichenflächenrahmen (breit), Mittenmarken (ISO 5457)."""
    g = Grafik()
    g.rechteck("duenn", 0, 0, breite, hoehe)
    z = zeichenflaeche(breite, hoehe)
    g.rechteck("sichtbar", z.x0, z.y0, z.x1, z.y1)
    mx, my = (z.x0 + z.x1) / 2, (z.y0 + z.y1) / 2
    for a, b in (((mx, 0), (mx, z.y0 + 5)), ((mx, hoehe), (mx, z.y1 - 5)), ((0, my), (z.x0 + 5, my)),
                 ((breite, my), (z.x1 - 5, my))):
        g.linie("sichtbar", a, b)
    return g


def schriftfeld_rechteck(breite: float, hoehe: float) -> Rechteck:
    z = zeichenflaeche(breite, hoehe)
    return Rechteck(z.x1 - SCHRIFTFELD_B, z.y0, z.x1, z.y0 + SCHRIFTFELD_H)


def _zelle(g: Grafik, x0: float, y0: float, x1: float, y1: float, label: str, wert: Any, hoehe: float = TEXT_H) -> None:
    g.text(label, x0 + 1.2, y1 - 1.2 - TEXT_LABEL, TEXT_LABEL, art="schriftfeld_label")
    if wert is None or wert == "":
        return
    text = str(wert)
    h = hoehe
    platz = x1 - x0 - 2.4
    while h > TEXT_LABEL and textbreite(text, h) > platz:
        h = round(h - 0.25, 2)
    g.text(text, x0 + 1.2, y0 + 1.6, h, art="schriftfeld")


def projektionssymbol(g: Grafik, cx: float, cy: float, h: float = 5.0) -> None:
    """Symbol der Projektionsmethode 1 (ISO 5456-2): Kegelstumpf von der Seite, rechts daneben die Ansicht von links
    (zwei konzentrische Kreise)."""
    d_gross, d_klein = h, h / 2
    laenge = 1.2 * h
    x0 = cx - laenge - 1.0
    g.linie("sichtbar", (x0, cy - d_klein / 2), (x0 + laenge, cy - d_gross / 2), (x0 + laenge, cy + d_gross / 2),
            (x0, cy + d_klein / 2), (x0, cy - d_klein / 2))
    g.linie("mitte", (x0 - 1, cy), (x0 + laenge + 1, cy))
    kx = cx + 1.0 + d_gross / 2
    g.kreis("sichtbar", kx, cy, d_gross / 2, 32)
    g.kreis("sichtbar", kx, cy, d_klein / 2, 24)
    g.linie("mitte", (kx - d_gross / 2 - 1, cy), (kx + d_gross / 2 + 1, cy))
    g.linie("mitte", (kx, cy - d_gross / 2 - 1), (kx, cy + d_gross / 2 + 1))


def schriftfeld(breite: float, hoehe: float, werte: dict[str, Any], massstab: str, fmt: str) -> Grafik:
    """Schriftfeld nach ISO 7200 rechts unten: Benennung, Zeichnungsnummer, Werkstoff, Halbzeug, Masse, Maßstab,
    Allgemeintoleranz, Projektionsmethode, Stückzahl, Format, Projekt, Version, Datum, gezeichnet, Blatt."""
    g = Grafik()
    r = schriftfeld_rechteck(breite, hoehe)
    x0, y0, x1 = r.x0, r.y0, r.x1
    zeilen = [12.0, 10.0, 9.0, 9.0]  # von oben
    ys = [y0 + SCHRIFTFELD_H]
    for h in zeilen:
        ys.append(ys[-1] - h)
    g.rechteck("sichtbar", x0, y0, x1, y0 + SCHRIFTFELD_H)
    for y in ys[1:-1]:
        g.linie("duenn", (x0, y), (x1, y))
    # Zeile 1: Benennung | Zeichnungsnummer
    sp = [x0, x0 + 120, x1]
    g.linie("duenn", (sp[1], ys[0]), (sp[1], ys[1]))
    _zelle(g, sp[0], ys[1], sp[1], ys[0], "Benennung", werte.get("benennung"), TEXT_TITEL)
    _zelle(g, sp[1], ys[1], sp[2], ys[0], "Zeichnungsnummer", werte.get("zeichnungsnummer"))
    # Zeile 2: Werkstoff | Halbzeug | Masse | Maßstab
    sp = [x0, x0 + 55, x0 + 110, x0 + 145, x1]
    for x in sp[1:-1]:
        g.linie("duenn", (x, ys[1]), (x, ys[2]))
    masse = werte.get("masse_g")
    masse_text = None
    if isinstance(masse, (int, float)):
        masse_text = (f"{masse / 1000:.3f} kg" if masse >= 1000 else f"{masse:.1f} g").replace(".", ",")
    _zelle(g, sp[0], ys[2], sp[1], ys[1], "Werkstoff", werte.get("werkstoff"))
    _zelle(g, sp[1], ys[2], sp[2], ys[1], "Halbzeug", werte.get("halbzeug"))
    _zelle(g, sp[2], ys[2], sp[3], ys[1], "Masse", masse_text)
    _zelle(g, sp[3], ys[2], sp[4], ys[1], "Maßstab", massstab)
    # Zeile 3: Allgemeintoleranz | Projektion | Stückzahl | Format
    for x in sp[1:-1]:
        g.linie("duenn", (x, ys[2]), (x, ys[3]))
    _zelle(g, sp[0], ys[3], sp[1], ys[2], "Allgemeintoleranz", werte.get("allgemeintoleranz"))
    g.text("Projektionsmethode 1", sp[1] + 1.2, ys[2] - 1.2 - TEXT_LABEL, TEXT_LABEL, art="schriftfeld_label")
    projektionssymbol(g, (sp[1] + sp[2]) / 2 + 6, ys[3] + 3.2, 4.0)
    _zelle(g, sp[2], ys[3], sp[3], ys[2], "Stückzahl", werte.get("stueckzahl"))
    _zelle(g, sp[3], ys[3], sp[4], ys[2], "Format", fmt)
    # Zeile 4: Projekt | Version | Datum | gezeichnet | Blatt
    sp = [x0, x0 + 55, x0 + 90, x0 + 118, x0 + 152, x1]
    for x in sp[1:-1]:
        g.linie("duenn", (x, ys[3]), (x, ys[4]))
    _zelle(g, sp[0], ys[4], sp[1], ys[3], "Projekt", werte.get("projekt"), TEXT_KLEIN)
    _zelle(g, sp[1], ys[4], sp[2], ys[3], "Version", werte.get("version"), TEXT_KLEIN)
    _zelle(g, sp[2], ys[4], sp[3], ys[3], "Datum", werte.get("datum"), TEXT_KLEIN)
    _zelle(g, sp[3], ys[4], sp[4], ys[3], "gezeichnet", werte.get("gezeichnet"), TEXT_KLEIN)
    _zelle(g, sp[4], ys[4], sp[5], ys[3], "Blatt", werte.get("blatt") or "1/1", TEXT_KLEIN)
    return g


def allgemeinangaben_rechteck(breite: float, hoehe: float, zeilen: list[str]) -> Rechteck | None:
    """Platz der allgemeinen Angaben: links neben dem Schriftfeld, wenn dort mindestens 70 mm frei sind (spart Höhe),
    sonst über dem Schriftfeld."""
    if not zeilen:
        return None
    z = zeichenflaeche(breite, hoehe)
    r = schriftfeld_rechteck(breite, hoehe)
    h = len(zeilen) * TEXT_KLEIN * 1.8 + 3.0
    w = max(textbreite(t, TEXT_KLEIN) for t in zeilen) + 4.0
    if r.x0 - z.x0 >= max(70.0, w + 6.0) and h <= SCHRIFTFELD_H:
        return Rechteck(r.x0 - w - 4.0, z.y0, r.x0, z.y0 + h + 1.0)
    return Rechteck(r.x0, r.y1, r.x1, r.y1 + h)


def allgemeinangaben(breite: float, hoehe: float, zeilen: list[str]) -> tuple[Grafik, Rechteck | None]:
    """Allgemeine Angaben (z. B. „Nicht bemaßte Radien R3“) nahe am Schriftfeld, linksbündig."""
    g = Grafik()
    r = allgemeinangaben_rechteck(breite, hoehe, zeilen)
    if r is None:
        return g, None
    y = r.y0 + 2.0
    for text in reversed(zeilen):
        g.text(text, r.x0 + 1.0, y, TEXT_KLEIN, art="allgemein")
        y += TEXT_KLEIN * 1.8
    return g, r


# ---------------------------------------------------------------------------------------------------------------------
# Tabellen
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Spalte:
    titel: str
    breite: float
    anker: str = "links"


def tabelle(x0: float, y0: float, spalten: list[Spalte], zeilen: list[list[Any]], titel: str | None = None,
            zeilenhoehe: float = 5.5, nach_oben: bool = True) -> tuple[Grafik, Rechteck]:
    """Tabelle mit Kopfzeile; ``nach_oben``: die Kopfzeile steht oben, die Tabelle wächst von (x0, y0) nach oben (wie
    eine Stückliste über dem Schriftfeld, ISO 7573)."""
    g = Grafik()
    breite = sum(s.breite for s in spalten)
    n = len(zeilen) + 1 + (1 if titel else 0)
    h = n * zeilenhoehe
    y1 = y0 + h
    g.rechteck("sichtbar", x0, y0, x0 + breite, y1)
    # Zeilen von oben: Titel, Kopf, Daten
    y = y1
    if titel:
        g.text(titel, x0 + 1.5, y - zeilenhoehe + 1.6, TEXT_KLEIN, art="tabelle_titel")
        y -= zeilenhoehe
        g.linie("duenn", (x0, y), (x0 + breite, y))
    x = x0
    for s in spalten:
        g.text(s.titel, x + 1.2 if s.anker == "links" else x + s.breite / 2, y - zeilenhoehe + 1.7, TEXT_LABEL + 0.2,
               "links" if s.anker == "links" else "mitte", art="tabelle_kopf")
        x += s.breite
    y -= zeilenhoehe
    g.linie("sichtbar", (x0, y), (x0 + breite, y))
    for zeile in zeilen:
        x = x0
        for s, wert in zip(spalten, zeile):
            text = "" if wert is None else str(wert)
            hh = TEXT_KLEIN
            while hh > 1.6 and textbreite(text, hh) > s.breite - 2.0:
                hh = round(hh - 0.2, 2)
            if s.anker == "rechts":
                g.text(text, x + s.breite - 1.2, y - zeilenhoehe + 1.6, hh, "rechts", art="tabelle")
            elif s.anker == "mitte":
                g.text(text, x + s.breite / 2, y - zeilenhoehe + 1.6, hh, "mitte", art="tabelle")
            else:
                g.text(text, x + 1.2, y - zeilenhoehe + 1.6, hh, art="tabelle")
            x += s.breite
        y -= zeilenhoehe
        if y > y0 + 1e-6:
            g.linie("duenn", (x0, y), (x0 + breite, y))
    x = x0
    for s in spalten[:-1]:
        x += s.breite
        g.linie("duenn", (x, y0), (x, y1 - (zeilenhoehe if titel else 0)))
    return g, Rechteck(x0, y0, x0 + breite, y1)


STUECKLISTE_SPALTEN = [Spalte("Pos.", 10, "mitte"), Spalte("Menge", 12, "mitte"), Spalte("Benennung", 62),
                       Spalte("Abmessung / Norm", 42), Spalte("Werkstoff", 34), Spalte("Masse", 20, "rechts")]


def stueckliste_zeilen(bom: dict[str, Any], positionen: list[int] | None = None) -> list[list[Any]]:
    """Zeilen der Stücklisten-Tabelle aus der Stückliste des Laufs (BOM.lines)."""
    out = []
    for ln in bom.get("lines") or []:
        if positionen is not None and ln.get("pos") not in positionen:
            continue
        kg = ln.get("kg")
        masse = "" if kg is None else (f"{kg:.3f} kg" if kg >= 1 else f"{kg * 1000:.0f} g").replace(".", ",")
        abm = ln.get("masse_text") or ""
        norm = ln.get("norm")
        if norm and norm not in abm:
            abm = f"{abm}, {norm}" if abm else norm
        out.append([ln.get("pos"), ln.get("anzahl"), ln.get("benennung") or "", abm, ln.get("material") or "",
                    masse])
    return out


BOHRUNGEN_SPALTEN = [Spalte("Zeichen", 14, "mitte"), Spalte("X", 16, "rechts"), Spalte("Y", 16, "rechts"),
                     Spalte("Bohrung", 64)]


def positionsnummer(g: Grafik, nummer: Any, mitte: tuple[float, float], spitze: tuple[float, float],
                    r: float = 4.0) -> None:
    """Positionsnummer (ISO 6433): Kreis mit Nummer, Hinweislinie mit Punkt auf dem Teil."""
    cx, cy = mitte
    sx, sy = spitze
    g.kreis("duenn", cx, cy, r, 40)
    d = np.array([sx - cx, sy - cy])
    n = float(np.linalg.norm(d))
    if n > r:
        start = np.array([cx, cy]) + d / n * r
        g.linie("duenn", tuple(start), (sx, sy))
    g.flaechen.append(_punkt(sx, sy, 0.6))
    g.text(str(nummer), cx, cy - TEXT_H / 2, TEXT_H, "mitte", art="position")


def _punkt(x: float, y: float, r: float) -> np.ndarray:
    t = np.linspace(0, 2 * math.pi, 13)
    return np.stack([x + r * np.cos(t), y + r * np.sin(t)], axis=1)
