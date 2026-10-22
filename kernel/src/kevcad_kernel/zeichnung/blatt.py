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
SCHRIFTFELD_H = 39.0
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


def lage_umrechnen(lage: Any, von: tuple[str, str], nach: tuple[str, str]) -> list[float]:
    """Lage (Blatt-mm) beim Formatwechsel proportional mitnehmen: gleicher Anteil der Zeichenfläche."""
    a = zeichenflaeche(*blattgroesse(*von))
    b = zeichenflaeche(*blattgroesse(*nach))
    x, y = float(lage[0]), float(lage[1])
    u = (x - a.x0) / a.breite if a.breite else 0.5
    v = (y - a.y0) / a.hoehe if a.hoehe else 0.5
    return [round(b.x0 + u * b.breite, 2), round(b.y0 + v * b.hoehe, 2)]


def rahmen(breite: float, hoehe: float) -> Grafik:
    """Schneidekante (dünn), Zeichenflächenrahmen (breit), Mittenmarken (ISO 5457)."""
    g = Grafik()
    g.rechteck("duenn", 0, 0, breite, hoehe)
    z = zeichenflaeche(breite, hoehe)
    g.rechteck("sichtbar", z.x0, z.y0, z.x1, z.y1)
    mx, my = (z.x0 + z.x1) / 2, (z.y0 + z.y1) / 2
    sf = schriftfeld_rechteck(breite, hoehe)
    unten = z.y0 if sf.x0 <= mx <= sf.x1 else z.y0 + 5  # nicht ins Schriftfeld
    for a, b in (((mx, 0), (mx, unten)), ((mx, hoehe), (mx, z.y1 - 5)), ((0, my), (z.x0 + 5, my)),
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
    """Schriftfeld nach ISO 7200 (180 mm breit, unten rechts) mit den acht Pflichtfeldern Eigentümer, Sachnummer
    (Zeichnungsnummer), Ausgabedatum, Blattnummer, Titel (Benennung), Freigebender, Ersteller, Dokumentart; dazu
    Werkstoff, Halbzeug, Masse, Maßstab mit dem Symbol der Projektionsmethode 1 daneben, Allgemeintoleranz, Stückzahl,
    Format, Projekt und Version bzw. Meilenstein."""
    g = Grafik()
    r = schriftfeld_rechteck(breite, hoehe)
    x0, y0, x1 = r.x0, r.y0, r.x1
    zeilen = [12.0, 9.0, 9.0, 9.0]  # von oben
    ys = [y0 + SCHRIFTFELD_H]
    for h in zeilen:
        ys.append(ys[-1] - h)
    g.rechteck("sichtbar", x0, y0, x1, y0 + SCHRIFTFELD_H)
    for y in ys[1:-1]:
        g.linie("duenn", (x0, y), (x1, y))

    def zeile(i: int, breiten: list[float], zellen: list[tuple[str, Any, float]]) -> list[float]:
        xs = [x0]
        for w in breiten:
            xs.append(xs[-1] + w)
        for x in xs[1:-1]:
            g.linie("duenn", (x, ys[i]), (x, ys[i + 1]))
        for (label, wert, h), a, b in zip(zellen, xs[:-1], xs[1:]):
            if label:
                _zelle(g, a, ys[i + 1], b, ys[i], label, wert, h)
        return xs

    blatt_text = f"{werte.get('blatt_nr') or 1}/{werte.get('blatt_anzahl') or 1}"
    zeile(0, [100, 50, 30], [("Benennung", werte.get("benennung"), TEXT_TITEL),
                             ("Sachnummer", werte.get("zeichnungsnummer"), TEXT_H),
                             ("Blatt", blatt_text, TEXT_H)])
    masse = werte.get("masse_g")
    masse_text = None
    if isinstance(masse, (int, float)):
        masse_text = (f"{masse / 1000:.3f} kg" if masse >= 1000 else f"{masse:.1f} g").replace(".", ",")
    xs = zeile(1, [45, 45, 30, 30, 30], [("Werkstoff", werte.get("werkstoff"), TEXT_KLEIN + 0.5),
                                         ("Halbzeug", werte.get("halbzeug"), TEXT_KLEIN + 0.5),
                                         ("Masse", masse_text, TEXT_KLEIN + 0.5),
                                         ("Maßstab", massstab, TEXT_H), ("", None, TEXT_H)])
    g.text("Projektionsmethode 1", xs[4] + 1.2, ys[1] - 1.2 - TEXT_LABEL, TEXT_LABEL, art="schriftfeld_label")
    projektionssymbol(g, (xs[4] + xs[5]) / 2 - 1.0, ys[2] + 3.0, 3.6)
    zeile(2, [40, 22, 28, 45, 45], [("Allgemeintoleranz", werte.get("allgemeintoleranz"), TEXT_KLEIN + 0.5),
                                    ("Stückzahl", werte.get("stueckzahl"), TEXT_KLEIN + 0.5),
                                    ("Format", fmt, TEXT_KLEIN + 0.5),
                                    ("Dokumentart", werte.get("dokumentart"), TEXT_KLEIN + 0.5),
                                    ("Version", werte.get("version"), TEXT_KLEIN + 0.5)])
    zeile(3, [45, 40, 30, 35, 30], [("Projekt", werte.get("projekt"), TEXT_KLEIN),
                                    ("Eigentümer", werte.get("eigentuemer"), TEXT_KLEIN),
                                    ("Erstellt", werte.get("gezeichnet"), TEXT_KLEIN),
                                    ("Freigegeben", werte.get("freigegeben"), TEXT_KLEIN),
                                    ("Ausgabedatum", werte.get("datum"), TEXT_KLEIN)])
    return g


def umbrechen(zeilen: list[str], breite: float, hoehe: float = TEXT_KLEIN) -> list[str]:
    """Zeilen an Kommas bzw. Leerzeichen umbrechen, damit sie in ``breite`` mm passen."""
    out: list[str] = []
    for z in zeilen:
        if textbreite(z, hoehe) <= breite:
            out.append(z)
            continue
        teile = z.split(", ")
        trenn = ", "
        if len(teile) == 1:
            teile, trenn = z.split(" "), " "
        akt = ""
        for t in teile:
            probe = (akt + trenn + t) if akt else t
            if akt and textbreite(probe, hoehe) > breite:
                out.append(akt + trenn.rstrip())
                akt = "  " + t
            else:
                akt = probe
        if akt:
            out.append(akt)
    return out


def allgemeinangaben_rechteck(breite: float, hoehe: float, zeilen: list[str]) -> Rechteck | None:
    """Platz der allgemeinen Angaben: links neben dem Schriftfeld, wenn dort mindestens 70 mm frei sind (spart Höhe),
    sonst über dem Schriftfeld."""
    if not zeilen:
        return None
    z = zeichenflaeche(breite, hoehe)
    r = schriftfeld_rechteck(breite, hoehe)
    links = r.x0 - z.x0 - 8.0
    if links >= 70.0 and len(umbrechen(zeilen, links)) * TEXT_KLEIN * 1.8 + 3.0 <= SCHRIFTFELD_H:
        zeilen = umbrechen(zeilen, links)
    else:
        zeilen = umbrechen(zeilen, SCHRIFTFELD_B - 2.0)
    h = len(zeilen) * TEXT_KLEIN * 1.8 + 3.0
    w = max(textbreite(t, TEXT_KLEIN) for t in zeilen) + 4.0
    if r.x0 - z.x0 >= max(70.0, w + 6.0) and h <= SCHRIFTFELD_H:
        return Rechteck(z.x0 + 2.0, z.y0, z.x0 + 2.0 + w + 2.0, z.y0 + h + 1.0)  # unten links, frei von der Mittenmarke
    return Rechteck(r.x0, r.y1, r.x1, r.y1 + h)


def allgemeinangaben(breite: float, hoehe: float, zeilen: list[str]) -> tuple[Grafik, Rechteck | None]:
    """Allgemeine Angaben (z. B. „Nicht bemaßte Radien R3“) nahe am Schriftfeld, linksbündig."""
    g = Grafik()
    r = allgemeinangaben_rechteck(breite, hoehe, zeilen)
    if r is None:
        return g, None
    zeilen = umbrechen(zeilen, r.breite - 2.0)
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
            while hh > 2.0 and textbreite(text, hh) > s.breite - 2.0:
                hh = round(hh - 0.2, 2)
            while len(text) > 3 and textbreite(text, hh) > s.breite - 2.0:
                text = text[:-2].rstrip(" ,;/") + "…"
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


STUECKLISTE_SPALTEN = [Spalte("Pos.", 10, "mitte"), Spalte("Menge", 12, "mitte"), Spalte("Benennung", 56),
                       Spalte("Abmessung / Norm", 44), Spalte("Werkstoff", 40), Spalte("Masse", 18, "rechts")]


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
        benennung = str(ln.get("benennung") or "")
        if "/" in benennung:  # Druck- und Eigenteile heißen wie das Teil: letzter Teil des Namens genügt
            benennung = benennung.rsplit("/", 1)[-1]
        out.append([ln.get("pos"), ln.get("anzahl"), benennung, abm, ln.get("material") or "", masse])
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
