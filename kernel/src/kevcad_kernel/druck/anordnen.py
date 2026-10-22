"""Schnelles Anordnen der Druckteile auf Platten (Druckvorschau V3, DRUCKVORSCHAU.md).

Grundriss je Teil in Druckausrichtung (konvexe Hülle aus ``druck/vorschau_geo.py``, Hüllrechteck mit langer Seite in
X), Drehung in 90°-Schritten, Abstand zwischen den Teilen, Bauraum 256 × 256 mm des P1P und die Sperrzone vorn links
(18 × 28 mm). Gepackt wird als „Skyline“ unten links: Teile der Größe nach (große zuerst), gleiche Teile hintereinander,
damit so viele gleiche wie möglich auf einer Platte landen; jede Platte trägt ein Material (P1P ohne AMS). Die genaue
Anordnung rechnet danach Bambu Studio (``--arrange``, druck/slicer.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.druck.regeln import P1P, Drucker

ABSTAND = 6.0   # mm zwischen den Teilen (wie Bambu Studio beim Anordnen)


@dataclass
class Stueck:
    gruppe: str
    name: str
    material: str
    w: float                      # Hüllrechteck in X (lange Seite)
    h: float                      # in Y
    umriss: list[list[float]]     # konvexe Hülle, Mitte des Hüllrechtecks bei (0, 0)
    flaeche: float = 0.0
    rand: float = 0.0             # zusätzlich je Seite (Brim)
    ersatz: bool = False
    hoehe: float = 0.0
    farbe: str | None = None      # Strang „Rest Druck“: Druckfarbe oder None (egal)


@dataclass
class Lage:
    stueck: Stueck
    x: float
    y: float
    drehung: int

    def umriss(self) -> list[list[float]]:
        p = np.asarray(self.stueck.umriss, dtype=np.float64).reshape(-1, 2)
        if self.drehung % 360:
            w = math.radians(self.drehung)
            c, s = math.cos(w), math.sin(w)
            p = p @ np.array([[c, s], [-s, c]])
        p = p + [self.x, self.y]
        return [[round(float(a), 2), round(float(b), 2)] for a, b in p]

    def eintrag(self) -> dict[str, Any]:
        return {"name": self.stueck.name, "gruppe": self.stueck.gruppe, "x": round(self.x, 2), "y": round(self.y, 2),
                "drehung": int(self.drehung), "umriss": self.umriss(), "ersatz": bool(self.stueck.ersatz)}


@dataclass
class Platte:
    material: str
    lagen: list[Lage] = field(default_factory=list)
    passt_nicht: bool = False
    skyline: list[list[float]] = field(default_factory=list)   # [x, breite, y] in erweiterten Koordinaten
    farbe: str | None = None      # Strang „Rest Druck“: eine Farbe je Platte (P1P ohne AMS), None = keine Vorgabe

    def auslastung(self, drucker: Drucker = P1P) -> float:
        bx, by, _ = drucker.bauraum
        sx, sy = drucker.sperrflaeche
        nutz = bx * by - sx * sy
        return round(sum(l_.stueck.flaeche for l_ in self.lagen) / nutz, 3) if nutz > 0 else 0.0


class Skyline:
    """Unten-links-Packen von Rechtecken in einem Feld W × H mit erhöhtem Anfangsstück (Sperrzone)."""

    def __init__(self, W: float, H: float, sperre: tuple[float, float] = (0.0, 0.0)) -> None:
        self.W, self.H = W, H
        self.seg: list[list[float]] = []
        if sperre[0] > 0 and sperre[1] > 0:
            self.seg.append([0.0, min(W, sperre[0]), sperre[1]])
            if sperre[0] < W:
                self.seg.append([sperre[0], W - sperre[0], 0.0])
        else:
            self.seg.append([0.0, W, 0.0])

    def _hoehe(self, i: int, breite: float) -> float | None:
        x0 = self.seg[i][0]
        if x0 + breite > self.W + 1e-9:
            return None
        y, ende, j = 0.0, x0 + breite, i
        while j < len(self.seg) and self.seg[j][0] < ende - 1e-9:
            y = max(y, self.seg[j][2])
            j += 1
        return y

    def finde(self, w: float, h: float) -> tuple[float, float, float] | None:
        """Beste Stelle (x, y, oben) oder None."""
        beste = None
        for i in range(len(self.seg)):
            y = self._hoehe(i, w)
            if y is None or y + h > self.H + 1e-9:
                continue
            kand = (y + h, self.seg[i][0], y)
            if beste is None or kand < beste:
                beste = kand
        if beste is None:
            return None
        oben, x, y = beste
        return x, y, oben

    def setze(self, x: float, w: float, oben: float) -> None:
        neu: list[list[float]] = []
        ende = x + w
        for s in self.seg:
            sx, sw, sy = s
            se = sx + sw
            if se <= x + 1e-9 or sx >= ende - 1e-9:
                neu.append(s)
                continue
            if sx < x - 1e-9:
                neu.append([sx, x - sx, sy])
            if se > ende + 1e-9:
                neu.append([ende, se - ende, sy])
        neu.append([x, w, oben])
        neu.sort(key=lambda s: s[0])
        zus: list[list[float]] = []
        for s in neu:
            if zus and abs(zus[-1][2] - s[2]) < 1e-9 and abs(zus[-1][0] + zus[-1][1] - s[0]) < 1e-9:
                zus[-1][1] += s[1]
            else:
                zus.append(list(s))
        self.seg = zus


def _neue_platte(material: str, drucker: Drucker, a: float, farbe: str | None = None) -> tuple[Platte, Skyline]:
    bx, by, _ = drucker.bauraum
    sx, sy = drucker.sperrflaeche
    return Platte(material, farbe=farbe), Skyline(bx + a, by + a, (sx + a, sy + a))


def farben_je_material(stuecke: list[Any]) -> dict[str, list[str]]:
    """Farben je Material in der Reihenfolge des ersten Auftretens (Stücke oder Gruppen mit ``material``, ``farbe``)."""
    out: dict[str, list[str]] = {}
    for s in stuecke:
        f = getattr(s, "farbe", None)
        liste = out.setdefault(str(s.material), [])
        if f and f not in liste:
            liste.append(f)
    return out


def anordne(stuecke: list[Stueck], drucker: Drucker = P1P, abstand: float = ABSTAND) -> list[Platte]:
    """Platten je Material (in der Reihenfolge des ersten Auftretens); Teile, die nicht passen, je auf eine eigene
    Platte mit ``passt_nicht``.

    Farben (Strang „Rest Druck“): Hat ein Material Teile in mehreren Farben, bekommt jede Farbe eigene Platten (der P1P
    druckt ohne AMS eine Farbe je Platte); Teile ohne Farbe füllen danach diese Platten mit auf, erst dann kommen neue
    Platten ohne Farbe. Mit höchstens einer Farbe je Material wie bisher, die Platten tragen dann diese Farbe."""
    a = float(abstand)
    materialien: list[str] = []
    for s in stuecke:
        if s.material not in materialien:
            materialien.append(s.material)
    gruppen_rang: dict[str, int] = {}
    for s in stuecke:
        gruppen_rang.setdefault(s.gruppe, len(gruppen_rang))
    platten: list[Platte] = []
    bx, by, _ = drucker.bauraum
    farben = farben_je_material(stuecke)
    for mat in materialien:
        alle = [s for s in stuecke if s.material == mat]
        # große zuerst (längste Seite, dann Fläche), gleiche Teile zusammen, Ersatzteile am Ende ihrer Gruppe
        alle.sort(key=lambda s: (-round(max(s.w, s.h) + 2 * s.rand, 1), -round(s.w * s.h, 1),
                                 gruppen_rang[s.gruppe], s.ersatz))
        mehrfarbig = len(farben.get(mat) or []) > 1
        if mehrfarbig:  # je Farbe, danach die Teile ohne Farbe (dürfen auf jede Platte des Materials)
            klassen = [(f, [s for s in alle if s.farbe == f]) for f in farben[mat]]
            klassen.append((None, [s for s in alle if not s.farbe]))
        else:
            klassen = [((farben.get(mat) or [None])[0], alle)]
        offen: list[tuple[Platte, Skyline]] = []
        for farbe_k, teile in klassen:
            _packe(teile, mat, farbe_k, mehrfarbig, offen, drucker, a)
        platten += [p for p, _ in offen]
    return platten


def _packe(teile: list[Stueck], mat: str, farbe_k: str | None, mehrfarbig: bool,
           offen: list[tuple[Platte, Skyline]], drucker: Drucker, a: float) -> None:
    """Teile einer Farbklasse packen: erst auf offene Platten des Materials (bei mehreren Farben nur auf Platten
    derselben Farbe; Teile ohne Farbe auf jede), sonst auf neue Platten dieser Farbe. ``offen`` wächst mit."""
    bx, by, _ = drucker.bauraum
    for s in teile:
        w, h = s.w + 2 * s.rand + a, s.h + 2 * s.rand + a

        def setze(platte: Platte, sky: Skyline, s: Stueck = s, w: float = w, h: float = h) -> bool:
            beste = None
            for dreh, (rw, rh) in ((0, (w, h)), (90, (h, w))):
                pos = sky.finde(rw, rh)
                if pos is not None and (beste is None or (pos[2], pos[0]) < (beste[1][2], beste[1][0])):
                    beste = (dreh, pos, rw, rh)
            if beste is None:
                return False
            dreh, (x, y, oben), rw, rh = beste
            sky.setze(x, rw, oben)
            platte.lagen.append(Lage(s, x + rw / 2 - a / 2, y + rh / 2 - a / 2, dreh))
            return True

        erlaubt = [(p, sky) for p, sky in offen if not p.passt_nicht
                   and (not mehrfarbig or farbe_k is None or p.farbe == farbe_k)]
        if any(setze(p, sky) for p, sky in erlaubt):
            continue
        neu = _neue_platte(mat, drucker, a, farbe_k)
        if setze(*neu):
            offen.append(neu)
            continue
        p = Platte(mat, passt_nicht=True, farbe=farbe_k)  # passt auch auf eine leere Platte nicht
        p.lagen.append(Lage(s, bx / 2, by / 2, 0))
        offen.append((p, Skyline(0, 0)))


def stuecke_aus_gruppe(gruppe: str, material: str, geo: dict[str, Any], namen: list[str], anzahl: int,
                       brim: bool, farbe: str | None = None) -> list[Stueck]:
    """Stück je zu druckendem Teil einer Gruppe: erst die gezeigten Namen, dann Ersatzteile (``ersatz``)."""
    gr = geo.get("groesse") or [0, 0, 0]
    out = []
    for i in range(max(anzahl, 1)):
        name = namen[i] if i < len(namen) else namen[(i - len(namen)) % len(namen)] if namen else gruppe
        out.append(Stueck(gruppe=gruppe, name=name, material=material, w=float(gr[0]), h=float(gr[1]),
                          umriss=list(geo.get("umriss") or []), flaeche=float(geo.get("umriss_flaeche") or 0.0),
                          rand=5.0 if brim else 0.0, ersatz=i >= len(namen), hoehe=float(gr[2] if len(gr) > 2 else 0),
                          farbe=farbe))
    return out
