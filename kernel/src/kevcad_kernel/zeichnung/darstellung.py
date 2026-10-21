"""Darstellung der Maße nach ISO 129-1 und ISO 128-22: fertige Linien, Pfeile, Texte in Blatt-mm.

Regeln (begründet):

- Maßlinie und Maßhilfslinien schmal (0,25 mm); Hilfslinien beginnen 1 mm vor dem Körper (Lücke, damit sie nicht wie
  Kanten aussehen) und stehen 2 mm über die Maßlinie hinaus.
- Pfeile gefüllt, 15° offen, Länge 3 mm (≈ 10 × Linienbreite bei Maßzahlen 3,5 mm). Reicht der Platz zwischen den
  Hilfslinien nicht für zwei Pfeile und die Zahl, stehen die Pfeile außen und die Zahl neben der Maßlinie.
- Maßzahl 3,5 mm über der Maßlinie, lesbar von unten oder von rechts (senkrechte Maße um 90° gedreht).
- Hinweislinien (Bohrungen, Radien, Fasen) beginnen mit einem Pfeil am Element und enden mit einer waagrechten
  Bezugslinie unter dem Text.
- Steigende Bemaßung (``bezugskette``): ein Ursprung (Kreis), eine durchgehende Maßlinie, je Lage ein Pfeil und die
  Zahl an der Hilfslinie (ISO 129-1, 9.3); spart Platz bei vielen Lagen auf einer Achse, z. B. Bohrungen ab Rohrende.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.blatt import TEXT_H
from kevcad_kernel.zeichnung.geo2d import Rechteck, textbox, textbreite

PFEIL_L = 3.0
PFEIL_B = 1.0  # halbe Breite ≈ L · tan(15°) · 1,25
LUECKE = 1.0
UEBERSTAND = 2.0
TEXT_ABSTAND = 0.9  # Maßzahl über der Maßlinie
ERSTE_LINIE = 9.0  # Abstand erste Maßlinie vom Körper
LINIEN_ABSTAND = 7.0  # Abstand weiterer Maßlinien


@dataclass
class MassGrafik:
    id: str
    linien: list[np.ndarray] = field(default_factory=list)
    pfeile: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    text_lage: tuple[float, float] = (0.0, 0.0)
    text_winkel: float = 0.0
    text_hoehe: float = TEXT_H
    wert: float | None = None
    einheit: str = "mm"
    box: Rechteck | None = None
    weitere_texte: list[dict[str, Any]] = field(default_factory=list)  # Bezugskette: Zahl je Lage

    def als_dict(self) -> dict[str, Any]:
        return {"id": self.id, "linien": [[[round(float(x), 3), round(float(y), 3)] for x, y in pl]
                                          for pl in self.linien],
                "pfeile": self.pfeile, "text": self.text,
                "text_lage": [round(float(self.text_lage[0]), 3), round(float(self.text_lage[1]), 3)],
                "text_winkel": round(float(self.text_winkel), 3), "text_hoehe": self.text_hoehe,
                "wert": None if self.wert is None else round(float(self.wert), 4), "einheit": self.einheit,
                "box": self.box.liste() if self.box else None, "texte": self.weitere_texte}

    def rechtecke(self) -> list[Rechteck]:
        out = [self.box] if self.box else []
        for t in self.weitere_texte:
            out.append(textbox(t["text"], tuple(t["lage"]), t["hoehe"], t["winkel"], t.get("anker", "mitte")))
        return out


def pfeil(spitze: np.ndarray, richtung: np.ndarray, art: str = "voll") -> dict[str, Any]:
    """Pfeil an ``spitze``, ``richtung`` = Richtung, in die die Spitze zeigt. ``polygon`` für einfache Zeichner."""
    d = np.asarray(richtung, dtype=float)
    d = d / (np.linalg.norm(d) or 1.0)
    n = np.array([-d[1], d[0]])
    s = np.asarray(spitze, dtype=float)
    if art == "punkt":
        t = np.linspace(0, 2 * math.pi, 13)
        poly = np.stack([s[0] + 0.6 * np.cos(t), s[1] + 0.6 * np.sin(t)], axis=1)
    elif art == "ursprung":
        t = np.linspace(0, 2 * math.pi, 17)
        poly = np.stack([s[0] + 1.2 * np.cos(t), s[1] + 1.2 * np.sin(t)], axis=1)
    else:
        poly = np.array([s, s - d * PFEIL_L + n * PFEIL_B, s - d * PFEIL_L - n * PFEIL_B, s])
    return {"spitze": [round(float(s[0]), 3), round(float(s[1]), 3)],
            "richtung": [round(float(d[0]), 5), round(float(d[1]), 5)], "art": art, "laenge": PFEIL_L,
            "breite": 2 * PFEIL_B, "polygon": [[round(float(x), 3), round(float(y), 3)] for x, y in poly]}


def _einheit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([1.0, 0.0])


def linear(mid: str, p1: np.ndarray, p2: np.ndarray, richtung: str, versatz: float, text: str,
           wert: float | None, text_versatz: float | None = None, hoehe: float = TEXT_H) -> MassGrafik:
    """Lineares Maß zwischen p1 und p2 (Blatt-mm). ``richtung`` x (waagrecht), y (senkrecht) oder frei (parallel
    zu p1→p2). ``versatz``: Abstand der Maßlinie von p1 senkrecht zur Messrichtung (positiv: +y bzw. +x bzw. links
    von p1→p2). ``text_versatz``: Lage der Zahl entlang der Maßlinie ab ihrer Mitte (None = mittig/automatisch)."""
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    if richtung == "x":
        u = np.array([1.0, 0.0])
    elif richtung == "y":
        u = np.array([0.0, 1.0])
    else:
        u = _einheit(p2 - p1)
    n = np.array([-u[1], u[0]])  # links von u: bei x → +y, bei y → −x
    if richtung == "y":
        n = np.array([1.0, 0.0])  # Vertrag: positiv = +x für senkrechte Maße
    # Maßlinie: Punkte auf der Linie, die durch p1 + n·versatz geht, parallel zu u
    basis = p1 + n * versatz
    a = basis + u * float((p1 - basis) @ u)
    b = basis + u * float((p2 - basis) @ u)
    if float((b - a) @ u) < 0:
        a, b = b, a
    g = MassGrafik(mid, text=text, wert=wert, text_hoehe=hoehe)
    # Hilfslinien von p zur Maßlinie, mit Lücke am Körper und Überstand
    for p, q in ((p1, a if float((p1 - a) @ u) ** 2 < float((p1 - b) @ u) ** 2 else b),
                 (p2, b if float((p2 - b) @ u) ** 2 < float((p2 - a) @ u) ** 2 else a)):
        d = q - p
        L = float(np.linalg.norm(d))
        if L > LUECKE + 0.2:
            e = d / L
            g.linien.append(np.array([p + e * LUECKE, q + e * UEBERSTAND]))
    laenge = float(np.linalg.norm(b - a))
    tw = textbreite(text, hoehe)
    innen = laenge >= 2 * PFEIL_L + tw + 2.0
    if laenge >= 2 * PFEIL_L + 1.0 or innen:
        g.linien.append(np.array([a, b]))
        g.pfeile += [pfeil(a, -u), pfeil(b, u)]
    else:  # Pfeile außen, Maßlinie über die Hilfslinien verlängert
        g.linien.append(np.array([a - u * (PFEIL_L + 3.0), b + u * (PFEIL_L + 3.0)]))
        g.pfeile += [pfeil(a, u), pfeil(b, -u)]
    winkel = math.degrees(math.atan2(u[1], u[0]))
    if winkel > 90.0 + 1e-6 or winkel <= -90.0 + 1e-6:  # lesbar von unten bzw. rechts
        winkel += 180.0
        winkel = (winkel + 180) % 360 - 180
    # Zahl über der Linie (auf der Seite von n, bei senkrechten Maßen links der Linie)
    oben = np.array([-math.sin(math.radians(winkel)), math.cos(math.radians(winkel))])
    mitte = (a + b) / 2
    if text_versatz is not None:
        mitte = mitte + u * text_versatz
    elif not innen:
        mitte = b + u * (PFEIL_L + 3.0 + tw / 2 + 1.0)  # Zahl rechts bzw. oben neben dem äußeren Pfeil
        g.linien[-1] = np.array([g.linien[-1][0], b + u * (PFEIL_L + 4.0 + tw + 1.0)])
    lage = mitte + oben * TEXT_ABSTAND
    g.text_lage = (float(lage[0]), float(lage[1]))
    g.text_winkel = winkel
    g.box = textbox(text, g.text_lage, hoehe, winkel, "mitte")
    return g


def kette(mid: str, ursprung: np.ndarray, punkte: list[np.ndarray], texte: list[str], richtung: str, versatz: float,
          werte: list[float], hoehe: float = TEXT_H) -> MassGrafik:
    """Steigende Bemaßung: eine Maßlinie ab dem Ursprung, Pfeile an jeder Lage, Zahlen an den Hilfslinien."""
    o = np.asarray(ursprung, dtype=float)
    u = np.array([1.0, 0.0]) if richtung == "x" else np.array([0.0, 1.0])
    n = np.array([0.0, 1.0]) if richtung == "x" else np.array([1.0, 0.0])
    basis = o + n * versatz
    g = MassGrafik(mid, text="0", wert=0.0, text_hoehe=hoehe)
    alle = [o] + [np.asarray(p, dtype=float) for p in punkte]
    ts = [float((p - basis) @ u) for p in alle]
    t0, t1 = min(ts), max(ts)
    g.linien.append(np.array([basis + u * t0, basis + u * (t1 + 2.0)]))
    for p, t in zip(alle, ts):
        q = basis + u * t
        d = q - p
        L = float(np.linalg.norm(d))
        if L > LUECKE + 0.2:
            e = d / L
            g.linien.append(np.array([p + e * LUECKE, q + e * UEBERSTAND]))
    g.pfeile.append(pfeil(basis + u * ts[0], u, "ursprung"))
    sgn = 1.0 if versatz >= 0 else -1.0
    winkel = 90.0 if richtung == "x" else 0.0
    # Zahl des Ursprungs (0) und je Lage parallel zur Hilfslinie, am Pfeil
    for k, (p, t) in enumerate(zip(alle, ts)):
        q = basis + u * t
        if k > 0:
            g.pfeile.append(pfeil(q, u if t > ts[0] else -u))
        text = "0" if k == 0 else texte[k - 1]
        tw = textbreite(text, hoehe)
        if richtung == "x":
            # senkrecht geschrieben, links neben der Hilfslinie, vom Pfeil weg nach außen
            lage = q + np.array([-TEXT_ABSTAND, sgn * (1.5 + (tw / 2 if sgn > 0 else tw / 2))])
            lage = q + np.array([-TEXT_ABSTAND, sgn * (1.5 + tw / 2)])
            tl = (float(lage[0]), float(lage[1]))
        else:
            lage = q + np.array([sgn * (1.5 + tw / 2), TEXT_ABSTAND])
            tl = (float(lage[0]), float(lage[1]))
        eintrag = {"text": text, "lage": [round(tl[0], 3), round(tl[1], 3)], "hoehe": hoehe, "winkel": winkel,
                   "anker": "mitte", "wert": round(float(werte[k - 1]), 4) if k > 0 else 0.0}
        if k == 0:
            g.text_lage, g.text_winkel = tl, winkel
            g.box = textbox(text, tl, hoehe, winkel, "mitte")
        else:
            g.weitere_texte.append(eintrag)
    g.wert = float(werte[-1]) if werte else 0.0
    return g


def hinweis(mid: str, ziel: np.ndarray, richtung_zum_ziel: np.ndarray | None, text_lage: np.ndarray, text: str,
            wert: float | None, hoehe: float = TEXT_H, pfeil_art: str = "voll", zweiter: list[str] | None = None) \
        -> MassGrafik:
    """Hinweislinie mit Pfeil am Ziel (Kreis, Bogen, Fase) und waagrechter Bezugslinie unter dem Text.
    ``text_lage``: Anfang der Bezugslinie (Knick); der Text steht über der Bezugslinie, weg vom Ziel."""
    z = np.asarray(ziel, dtype=float)
    k = np.asarray(text_lage, dtype=float)
    g = MassGrafik(mid, text=text, wert=wert, text_hoehe=hoehe)
    rechts = k[0] >= z[0]
    zeilen = [text] + list(zweiter or [])
    tw = max(textbreite(t, hoehe) for t in zeilen)
    ende = k + np.array([tw + 1.5, 0.0]) if rechts else k - np.array([tw + 1.5, 0.0])
    g.linien.append(np.array([z, k, ende]))
    d = z - k if richtung_zum_ziel is None else np.asarray(richtung_zum_ziel, dtype=float)
    g.pfeile.append(pfeil(z, d, pfeil_art))
    mitte_x = (k[0] + ende[0]) / 2
    g.text_lage = (float(mitte_x), float(k[1] + TEXT_ABSTAND))
    g.text_winkel = 0.0
    g.box = textbox(text, g.text_lage, hoehe, 0.0, "mitte")
    for i, t in enumerate(zweiter or []):
        lage = (float(mitte_x), float(k[1] - TEXT_ABSTAND - (i + 1) * hoehe * 1.6))
        g.weitere_texte.append({"text": t, "lage": [round(lage[0], 3), round(lage[1], 3)], "hoehe": hoehe,
                                "winkel": 0.0, "anker": "mitte"})
    return g


def winkel(mid: str, scheitel: np.ndarray, d1: np.ndarray, d2: np.ndarray, radius: float, text: str, wert: float,
           hoehe: float = TEXT_H) -> MassGrafik:
    """Winkelmaß: Bogen um den Scheitel zwischen den Richtungen d1 und d2 (Blatt), Pfeile an den Enden."""
    c = np.asarray(scheitel, dtype=float)
    a1 = math.atan2(d1[1], d1[0])
    a2 = math.atan2(d2[1], d2[0])
    da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    ts = np.linspace(a1, a1 + da, 33)
    bogen = np.stack([c[0] + radius * np.cos(ts), c[1] + radius * np.sin(ts)], axis=1)
    g = MassGrafik(mid, text=text, wert=wert, einheit="°", text_hoehe=hoehe)
    g.linien.append(bogen)
    # Schenkel bis zum Bogen verlängern (Hilfslinien)
    for a in (a1, a1 + da):
        e = np.array([math.cos(a), math.sin(a)])
        g.linien.append(np.array([c, c + e * (radius + UEBERSTAND)]))
    s = 1.0 if da > 0 else -1.0
    t_start = np.array([-math.sin(a1), math.cos(a1)]) * s
    t_end = np.array([-math.sin(a1 + da), math.cos(a1 + da)]) * s
    g.pfeile += [pfeil(bogen[0], -t_start), pfeil(bogen[-1], t_end)]
    am = a1 + da / 2
    lage = c + np.array([math.cos(am), math.sin(am)]) * (radius + hoehe * 0.6 + 1.0)
    g.text_lage = (float(lage[0]), float(lage[1] - hoehe / 2))
    g.text_winkel = 0.0
    g.box = textbox(text, g.text_lage, hoehe, 0.0, "mitte")
    return g


def textmass(mid: str, lage: tuple[float, float], text: str, hoehe: float = TEXT_H) -> MassGrafik:
    """Reine Angabe ohne Linien (z. B. „t = 5“)."""
    g = MassGrafik(mid, text=text, text_lage=lage, text_hoehe=hoehe)
    g.box = textbox(text, lage, hoehe, 0.0, "mitte")
    return g
