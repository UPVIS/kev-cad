"""Die Bedingungen: Montage (auf, bündig, konzentrisch, …), Gelenke (drehgelenk, …) und Maße (spiel, min_wand, …).

Jede Bedingung kennt zwei Bezüge ``a`` und ``b`` (Ausnahmen: ``gleich``, ``min_wand``) und liefert

- für das Platzieren (loeser.py): Richtungspaare (``richtungen``), lineare Gleichungen für die Verschiebung
  (``zeilen``) und einen Restvektor (``residuen``, mm; Winkel über die Teilgröße L in mm umgerechnet),
- für die Prüfung nach dem Lauf (pruefung.py): ``pruefe(A, B)`` mit Stand, Soll, Ist, Ort und Lösung.

``A`` und ``B`` sind die Bezüge in ihrer aktuellen Weltlage. Gelenke tragen zusätzlich ihre Freiheitsgrade
(``freie_bewegungen``) und können ihr Teil entlang dieser bewegen (``bewegung``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .geometrie import (
    EPS,
    EPS_WINKEL,
    Bezug,
    BezugFehler,
    als_bezug,
    bezug,
    bohrung_ende,
    drehmatrix,
    drehung_um_gerade,
    einheit,
    gerichteter_winkel,
    linien_winkel,
    punkt_im_koerper,
    schraube_daten,
    verschiebung,
    winkel_grad,
)
from .sammlung import aktive, aufrufstelle
from .text import grad, mm, richtung, vektor, zahl

# Kernloch-Steigungen (Regelgewinde ISO 261) für Schrauben ohne Steigung im Namen
REGEL_STEIGUNG = {2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0,
                  20: 2.5, 24: 3.0}
# Durchgangsbohrung mittel nach ISO 273
DURCHGANG_MITTEL = {2: 2.4, 2.5: 2.9, 3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 14: 15.5, 16: 17.5,
                    20: 22.0, 24: 26.0}


class BedingungsFehler(ValueError):
    """Bedingung falsch angegeben (falsche Art der Bezüge, fehlende Werte)."""


@dataclass
class Ergebnis:
    """Prüfergebnis einer Bedingung (Stand und Werte für Anzeige und Befund)."""

    stand: str  # erfuellt | verletzt | ungeprueft
    soll: str = ""
    ist: str = ""
    abweichung: float | None = None
    einheit: str = "mm"
    ort: np.ndarray | None = None
    punkte: list[np.ndarray] = field(default_factory=list)
    loesung: str | None = None
    schwere: str = "fehler"  # gilt, wenn verletzt
    hinweis: str | None = None
    weitere: list[Ergebnis] = field(default_factory=list)  # zusätzliche Befunde (in_bohrung)


def _ok(soll: str, ist: str, abw: float | None = 0.0, einheit: str = "mm", punkte: list | None = None) -> Ergebnis:
    return Ergebnis("erfuellt", soll, ist, abw, einheit, punkte=punkte or [])


def _sign(x: float) -> float:
    return -1.0 if x < 0 else 1.0


def _perp(d: np.ndarray) -> np.ndarray:
    return np.eye(3) - np.outer(d, d)


def _basis(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from .geometrie import senkrecht_zu

    e1 = senkrecht_zu(d)
    return e1, np.cross(d, e1)


def _wrap(w: float) -> float:
    return (w + 180.0) % 360.0 - 180.0


class Bedingung:
    """Grundklasse. ``a`` gehört zum Teil, das sich anpasst (beim Platzieren das bewegte), ``b`` zum Bezugsteil."""

    art = "bedingung"
    gruppe = "montage"
    symbol = "?"
    nimmt = 0  # entfernte Freiheitsgrade (Anzeige)

    def __init__(self, *bezuege: Any, toleranz: float | None = None, winkel_toleranz: float | None = None,
                 name: str | None = None, registrieren: bool = True) -> None:
        self.bezuege: list[Bezug] = [als_bezug(b) for b in bezuege]
        self.toleranz = EPS if toleranz is None else float(toleranz)
        self.winkel_toleranz = EPS_WINKEL if winkel_toleranz is None else float(winkel_toleranz)
        self.name = name
        self.id = ""
        self.datei, self.zeile = aufrufstelle()
        self.platzierung: Any = None
        self._pruefe_arten()
        s = aktive()
        if registrieren and s is not None:
            s.neu(self)

    @property
    def a(self) -> Bezug:
        return self.bezuege[0]

    @property
    def b(self) -> Bezug:
        return self.bezuege[1]

    def _pruefe_arten(self) -> None:
        """Wirft BedingungsFehler, wenn die Bezüge nicht passen."""

    def __repr__(self) -> str:
        return f"<{self.art} {self.id or ''} {' / '.join(b.anzeigename() for b in self.bezuege)}>"

    # -- Text -----------------------------------------------------------------------------------------------------

    def beschreibung(self, A: Bezug, B: Bezug) -> str:
        return f"{A.anzeigename()} {self.art} {B.anzeigename()}"

    # -- Lösen ----------------------------------------------------------------------------------------------------

    def richtungen(self, A: Bezug, B: Bezug) -> list[tuple[np.ndarray, np.ndarray]]:
        """Paare (Richtung an A, Richtung an B), die gleich werden sollen."""
        return []

    def zeilen(self, A: Bezug, B: Bezug) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, float]]:
        """Lineare Gleichungen n · (qA − qB) = s als (n, qA, qB, s); qA verschiebt sich mit A."""
        return []

    def residuen(self, A: Bezug, B: Bezug, L: float) -> np.ndarray:
        return np.zeros(0)

    def vor_platzieren(self, A: Bezug, B: Bezug) -> None:
        """Merkt sich Bezugswerte (Gelenke) nach dem Ausrichten, bevor die Werte gesetzt werden."""

    def nachdrehung(self, A: Bezug, B: Bezug) -> np.ndarray | None:
        """Bewegung nach dem Lösen (Gelenkwert setzen), 4×4 oder None."""
        return None

    def freie_bewegungen(self, A: Bezug, B: Bezug) -> list[tuple[str, np.ndarray, np.ndarray]]:
        """Gewollte Freiheitsgrade (Gelenke): (Art, Punkt, Richtung) mit Art "drehung" oder "verschiebung"."""
        return []

    # -- Prüfen ---------------------------------------------------------------------------------------------------

    def pruefe(self, A: Bezug, B: Bezug) -> Ergebnis:
        return Ergebnis("ungeprueft", hinweis="Prüfung für diese Bedingung fehlt")

    def info(self) -> dict[str, Any]:
        """Zusätzliche Felder für das Protokoll (Gelenke: Achse, Wert, Bereich)."""
        return {}


def _verlange(b: Bezug, art: str, wer: str, wofuer: str) -> None:
    if not b.kann(art):
        namen = {"ebene": "eine Ebene (Fläche, Plane, \"oben\" …)", "achse": "eine Achse (Zylinder, Kante, Axis)",
                 "richtung": "eine Ebene oder Achse"}
        raise BedingungsFehler(f"{wofuer}: {wer} ist {b.art} ({b.anzeigename()}), gebraucht wird "
                               f"{namen.get(art, art)}")


def _richtung_von(b: Bezug) -> np.ndarray:
    return b.richtung


def _kontakt(A: Bezug, B: Bezug) -> tuple[float, np.ndarray | None]:
    """Kleinster Abstand der Flächen (oder Formen bei Hüllebenen) zweier Ebenenbezüge und der Punkt auf A."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.TopoDS import TopoDS_Compound

    def shape_of(bz: Bezug) -> Any:
        faces = bz.flaechen_welt()
        if faces:
            if len(faces) == 1:
                return faces[0]
            comp = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(comp)
            for f in faces:
                builder.Add(comp, f)
            return comp
        form = bz.form_welt()
        return None if form is None else form.wrapped

    sa, sb = shape_of(A), shape_of(B)
    if sa is None or sb is None:
        return 0.0, None
    dist = BRepExtrema_DistShapeShape(sa, sb)
    if not dist.IsDone() or dist.NbSolution() == 0:
        return 0.0, None
    p = dist.PointOnShape1(1)
    return float(dist.Value()), np.array([p.X(), p.Y(), p.Z()])


def _schieben_text(A: Bezug, n: np.ndarray, betrag: float) -> str:
    owner = A.teilname or A.label or "das Teil"
    return f"{owner} um {mm(abs(betrag))} entlang {richtung(n * (-1 if betrag > 0 else 1))} verschieben"


def _platziere_tipp(c: Bedingung) -> str:
    return f" – oder die Lage mit platziere(teil, {c.art}(…)) aus der Bedingung ableiten (Zeile {c.zeile})" \
        if c.zeile else ""


# ---------------------------------------------------------------------------------------------------------------------
# Montagebedingungen


class Auf(Bedingung):
    """Fläche auf Fläche: Ebenen fallen zusammen, Normalen gegenläufig (Berührung), mit ``abstand`` Luft dazwischen."""

    art, symbol, nimmt = "auf", "auf", 3

    def __init__(self, a: Any, b: Any, abstand: float = 0.0, **kw: Any) -> None:
        self.abstand = float(abstand)
        super().__init__(a, b, **kw)

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "ebene", "der erste Bezug", "auf")
        _verlange(self.b, "ebene", "der zweite Bezug", "auf")

    def beschreibung(self, A: Bezug, B: Bezug) -> str:
        luft = f" mit {mm(self.abstand)} Abstand" if self.abstand else ""
        return f"{A.anzeigename()} auf {B.anzeigename()}{luft}"

    def richtungen(self, A, B):
        return [(A.d, -B.d)]

    def zeilen(self, A, B):
        return [(B.d, A.p, B.p, self.abstand)]

    def residuen(self, A, B, L):
        return np.concatenate([L * (A.d + B.d), [float(np.dot(B.d, A.p - B.p)) - self.abstand]])

    def pruefe(self, A, B):
        w = winkel_grad(A.d, -B.d)
        dist = float(np.dot(B.d, A.p - B.p))
        abw = dist - self.abstand
        soll = f"Abstand {mm(self.abstand)}, Flächen gegenüber"
        punkte = [A.p, B.p + B.d * float(np.dot(B.d, A.p - B.p))]
        if w > self.winkel_toleranz:
            return Ergebnis("verletzt", soll, f"Flächen um {grad(w)} verkippt", w, "°", ort=A.p, punkte=punkte,
                            loesung=f"{A.teilname or 'Teil'} drehen, bis {A.anzeigename()} parallel zu "
                                    f"{B.anzeigename()} liegt{_platziere_tipp(self)}")
        if abs(abw) > self.toleranz:
            was = "Luft" if abw > 0 else "Durchdringung"
            return Ergebnis("verletzt", soll, f"Abstand {mm(dist)} ({was} {mm(abs(abw))})", abw, "mm", ort=A.p,
                            punkte=punkte, loesung=_schieben_text(A, B.d, abw) + _platziere_tipp(self))
        if abs(self.abstand) <= self.toleranz:
            kontakt, ort = _kontakt(A, B)
            if kontakt > max(self.toleranz, 0.01):
                return Ergebnis("verletzt", "Flächen berühren sich", f"in einer Ebene, aber seitlich {mm(kontakt)} "
                                f"auseinander", kontakt, "mm", ort=ort if ort is not None else A.p, punkte=punkte,
                                loesung=f"{A.teilname or 'Teil'} in der Ebene so verschieben, dass die Flächen "
                                        f"übereinander liegen (konzentrisch(…) oder mittig(…) dazunehmen)")
            if ort is not None:
                punkte = [ort, ort]
        return _ok(soll, f"Abstand {mm(dist)}", abw, punkte=punkte)


class Buendig(Bedingung):
    """Bündig: Ebenen fallen zusammen, Normalen gleich gerichtet (mit ``abstand`` versetzt entlang der Normale)."""

    art, symbol, nimmt = "buendig", "buendig", 3

    def __init__(self, a: Any, b: Any, abstand: float = 0.0, **kw: Any) -> None:
        self.abstand = float(abstand)
        super().__init__(a, b, **kw)

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "ebene", "der erste Bezug", "buendig")
        _verlange(self.b, "ebene", "der zweite Bezug", "buendig")

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} bündig mit {B.anzeigename()}" + (f" (+{mm(self.abstand)})" if self.abstand else "")

    def richtungen(self, A, B):
        return [(A.d, B.d)]

    def zeilen(self, A, B):
        return [(B.d, A.p, B.p, self.abstand)]

    def residuen(self, A, B, L):
        return np.concatenate([L * (A.d - B.d), [float(np.dot(B.d, A.p - B.p)) - self.abstand]])

    def pruefe(self, A, B):
        w = winkel_grad(A.d, B.d)
        dist = float(np.dot(B.d, A.p - B.p))
        abw = dist - self.abstand
        soll = f"in einer Ebene{' +' + mm(self.abstand) if self.abstand else ''}, gleich gerichtet"
        punkte = [A.p, B.p]
        if w > self.winkel_toleranz:
            return Ergebnis("verletzt", soll, f"um {grad(w)} verkippt", w, "°", ort=A.p, punkte=punkte,
                            loesung=f"{A.teilname or 'Teil'} drehen, bis die Flächen gleich gerichtet sind"
                                    f"{_platziere_tipp(self)}")
        if abs(abw) > self.toleranz:
            return Ergebnis("verletzt", soll, f"Versatz {mm(abw)}", abw, "mm", ort=A.p, punkte=punkte,
                            loesung=_schieben_text(A, B.d, abw) + _platziere_tipp(self))
        return _ok(soll, f"Versatz {mm(abw)}", abw, punkte=punkte)


class Konzentrisch(Bedingung):
    """Achsen deckungsgleich (Richtung beliebig); Kugelmitte auf Achse; zwei Kugelmitten aufeinander."""

    art, symbol, nimmt = "konzentrisch", "konzentrisch", 4

    def _pruefe_arten(self) -> None:
        for wer, b in (("der erste Bezug", self.a), ("der zweite Bezug", self.b)):
            if not (b.kann("achse") or b.art == "punkt"):
                raise BedingungsFehler(f"konzentrisch: {wer} ist {b.art} ({b.anzeigename()}), gebraucht wird eine "
                                       "Achse (Zylinder, Bohrung, Kreiskante) oder eine Kugel")

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} konzentrisch zu {B.anzeigename()}"

    @staticmethod
    def _ist_achse(b: Bezug) -> bool:
        return b.kann("achse")

    def richtungen(self, A, B):
        if self._ist_achse(A) and self._ist_achse(B):
            return [(A.d, _sign(float(np.dot(A.d, B.d))) * B.d)]
        return []

    def zeilen(self, A, B):
        if self._ist_achse(B):
            e1, e2 = _basis(B.d)
            return [(e1, A.p, B.p, 0.0), (e2, A.p, B.p, 0.0)]
        if self._ist_achse(A):
            e1, e2 = _basis(A.d)
            return [(e1, A.p, B.p, 0.0), (e2, A.p, B.p, 0.0)]
        return [(np.eye(3)[k], A.p, B.p, 0.0) for k in range(3)]

    def residuen(self, A, B, L):
        if self._ist_achse(A) and self._ist_achse(B):
            s = _sign(float(np.dot(A.d, B.d)))
            return np.concatenate([L * (A.d - s * B.d), _perp(B.d) @ (A.p - B.p)])
        if self._ist_achse(B):
            return _perp(B.d) @ (A.p - B.p)
        if self._ist_achse(A):
            return _perp(A.d) @ (B.p - A.p)
        return A.p - B.p

    def pruefe(self, A, B):
        soll = "Achsen deckungsgleich"
        if self._ist_achse(A) and self._ist_achse(B):
            w = linien_winkel(A.d, B.d)
            off = _perp(B.d) @ (A.mitte() - B.p)
            versatz = float(np.linalg.norm(off))
            foot = A.mitte() - off
            punkte = [A.mitte(), foot]
            if w > self.winkel_toleranz:
                return Ergebnis("verletzt", soll, f"Achsen um {grad(w)} verkippt, Versatz {mm(versatz)}", w, "°",
                                ort=A.mitte(), punkte=punkte,
                                loesung=f"{A.teilname or 'Teil'} ausrichten, bis die Achsen parallel sind"
                                        f"{_platziere_tipp(self)}")
            if versatz > self.toleranz:
                return Ergebnis("verletzt", soll, f"Versatz {mm(versatz)} ({vektor(-off, 3)})", versatz, "mm",
                                ort=A.mitte(), punkte=punkte,
                                loesung=f"{A.teilname or 'Teil'} um {vektor(-off, 3)} mm verschieben oder die Bohrung "
                                        f"dorthin legen{_platziere_tipp(self)}")
            return _ok(soll, f"Versatz {mm(versatz)}", versatz, punkte=punkte)
        res = self.residuen(A, B, 1.0)
        versatz = float(np.linalg.norm(res))
        if versatz > self.toleranz:
            return Ergebnis("verletzt", soll if self._ist_achse(B) or self._ist_achse(A) else "Mitten aufeinander",
                            f"Versatz {mm(versatz)}", versatz, "mm", ort=A.p, punkte=[A.p, B.p],
                            loesung=f"{A.teilname or 'Teil'} um {vektor(-res, 3)} mm verschieben{_platziere_tipp(self)}")
        return _ok(soll, f"Versatz {mm(versatz)}", versatz, punkte=[A.p, B.p])


class Parallel(Bedingung):
    """Richtungen parallel (Ebene–Ebene: Normalen, Achse–Achse, Achse parallel zu Ebene)."""

    art, symbol, nimmt = "parallel", "parallel", 2

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "richtung", "der erste Bezug", "parallel")
        _verlange(self.b, "richtung", "der zweite Bezug", "parallel")

    def _gemischt(self, A: Bezug, B: Bezug) -> bool:
        return (A.art == "ebene") != (B.art == "ebene") and "lage" not in (A.art, B.art)

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} parallel zu {B.anzeigename()}"

    def richtungen(self, A, B):
        if self._gemischt(A, B):
            return []
        return [(A.d, _sign(float(np.dot(A.d, B.d))) * B.d)]

    def residuen(self, A, B, L):
        if self._gemischt(A, B):
            return np.array([L * float(np.dot(A.d, B.d))])
        return L * (A.d - _sign(float(np.dot(A.d, B.d))) * B.d)

    def pruefe(self, A, B):
        w = 90.0 - linien_winkel(A.d, B.d) if self._gemischt(A, B) else linien_winkel(A.d, B.d)
        if w > self.winkel_toleranz:
            return Ergebnis("verletzt", "parallel (0°)", f"{grad(w)} Abweichung", w, "°", ort=A.p, punkte=[A.p, B.p],
                            loesung=f"{A.teilname or 'Teil'} um {grad(w)} drehen{_platziere_tipp(self)}")
        return _ok("parallel (0°)", grad(w), w, "°", punkte=[A.p, B.p])


class Senkrecht(Bedingung):
    """Richtungen senkrecht (Ebene–Ebene, Achse–Achse; Achse senkrecht zu Ebene = parallel zur Normale)."""

    art, symbol, nimmt = "senkrecht", "senkrecht", 1

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "richtung", "der erste Bezug", "senkrecht")
        _verlange(self.b, "richtung", "der zweite Bezug", "senkrecht")

    def _gemischt(self, A: Bezug, B: Bezug) -> bool:
        return (A.art == "ebene") != (B.art == "ebene") and "lage" not in (A.art, B.art)

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} senkrecht zu {B.anzeigename()}"

    def richtungen(self, A, B):
        if self._gemischt(A, B):
            return [(A.d, _sign(float(np.dot(A.d, B.d))) * B.d)]
        return []

    def residuen(self, A, B, L):
        if self._gemischt(A, B):
            return L * (A.d - _sign(float(np.dot(A.d, B.d))) * B.d)
        return np.array([L * float(np.dot(A.d, B.d))])

    def pruefe(self, A, B):
        w = linien_winkel(A.d, B.d) if self._gemischt(A, B) else 90.0 - linien_winkel(A.d, B.d)
        if w > self.winkel_toleranz:
            return Ergebnis("verletzt", "senkrecht (90°)", f"{grad(90 - w)}", w, "°", ort=A.p, punkte=[A.p, B.p],
                            loesung=f"{A.teilname or 'Teil'} um {grad(w)} drehen{_platziere_tipp(self)}")
        return _ok("senkrecht (90°)", grad(90 - w), w, "°", punkte=[A.p, B.p])


class Winkel(Bedingung):
    """Winkel zwischen zwei Richtungen in Grad (Ebenen: Normalen 0…180°, mit einer Achse 0…90°)."""

    art, symbol, nimmt = "winkel", "winkel", 1

    def __init__(self, a: Any, b: Any, wert: float, **kw: Any) -> None:
        self.wert = float(wert)
        super().__init__(a, b, **kw)

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "richtung", "der erste Bezug", "winkel")
        _verlange(self.b, "richtung", "der zweite Bezug", "winkel")

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} unter {grad(self.wert)} zu {B.anzeigename()}"

    def _ist(self, A: Bezug, B: Bezug) -> float:
        if A.art == "achse" or B.art == "achse":
            return linien_winkel(A.d, B.d)
        return winkel_grad(A.d, B.d)

    def residuen(self, A, B, L):
        return np.array([L * math.radians(self._ist(A, B) - self.wert)])

    def pruefe(self, A, B):
        ist = self._ist(A, B)
        abw = ist - self.wert
        if abs(abw) > self.winkel_toleranz:
            return Ergebnis("verletzt", grad(self.wert), grad(ist), abw, "°", ort=A.p, punkte=[A.p, B.p],
                            loesung=f"{A.teilname or 'Teil'} um {grad(abs(abw))} drehen{_platziere_tipp(self)}")
        return _ok(grad(self.wert), grad(ist), abw, "°", punkte=[A.p, B.p])


class Abstand(Bedingung):
    """Abstand zwischen Ebenen (parallel), Punkten, Achsen und Mischungen; ``wert`` in mm."""

    art, symbol, nimmt = "abstand", "abstand", 1

    def __init__(self, a: Any, b: Any, wert: float, **kw: Any) -> None:
        self.wert = float(wert)
        if self.wert < 0:
            raise BedingungsFehler("abstand: wert muss ≥ 0 sein (Richtung ergibt sich aus der Lage)")
        super().__init__(a, b, **kw)

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} {mm(self.wert)} von {B.anzeigename()}"

    def _fall(self, A: Bezug, B: Bezug) -> str:
        ka = "ebene" if A.art == "ebene" else ("achse" if A.kann("achse") else "punkt")
        kb = "ebene" if B.art == "ebene" else ("achse" if B.kann("achse") else "punkt")
        return f"{ka}-{kb}"

    def _messen(self, A: Bezug, B: Bezug) -> tuple[float, np.ndarray, np.ndarray]:
        """(Abstand, Punkt an A, Punkt an B)."""
        fall = self._fall(A, B)
        if fall in ("ebene-ebene", "punkt-ebene", "achse-ebene"):
            dist = float(np.dot(B.d, A.p - B.p))
            return abs(dist), A.p, A.p - B.d * dist
        if fall in ("ebene-punkt", "ebene-achse"):
            dist = float(np.dot(A.d, B.p - A.p))
            return abs(dist), B.p - A.d * dist, B.p
        if fall == "punkt-punkt":
            return float(np.linalg.norm(A.p - B.p)), A.p, B.p
        if fall == "punkt-achse":
            off = _perp(B.d) @ (A.p - B.p)
            return float(np.linalg.norm(off)), A.p, A.p - off
        if fall == "achse-punkt":
            off = _perp(A.d) @ (B.p - A.p)
            return float(np.linalg.norm(off)), B.p - off, B.p
        # achse-achse
        n = np.cross(A.d, B.d)
        if np.linalg.norm(n) < 1e-9:
            off = _perp(B.d) @ (A.mitte() - B.p)
            return float(np.linalg.norm(off)), A.mitte(), A.mitte() - off
        n = einheit(n)
        dist = float(np.dot(n, A.p - B.p))
        return abs(dist), A.p, A.p - n * dist

    def richtungen(self, A, B):
        fall = self._fall(A, B)
        if fall in ("ebene-ebene", "achse-achse"):
            return [(A.d, _sign(float(np.dot(A.d, B.d))) * B.d)]
        return []

    def zeilen(self, A, B):
        fall = self._fall(A, B)
        if fall in ("ebene-ebene", "punkt-ebene", "achse-ebene"):
            s = _sign(float(np.dot(B.d, A.p - B.p)))
            return [(B.d, A.p, B.p, s * self.wert)]
        if fall in ("ebene-punkt", "ebene-achse"):
            s = _sign(float(np.dot(A.d, B.p - A.p)))
            return [(-A.d, A.p, B.p, s * self.wert)]
        return []

    def residuen(self, A, B, L):
        fall = self._fall(A, B)
        dist, _, _ = self._messen(A, B)
        if fall in ("ebene-ebene", "punkt-ebene", "achse-ebene", "ebene-punkt", "ebene-achse"):
            # mit Vorzeichen, damit der Rest auch bei Abstand 0 glatt ist (Freiheitsgrade über die Jacobi-Matrix)
            signed = float(np.dot(B.d, A.p - B.p)) if fall in ("ebene-ebene", "punkt-ebene", "achse-ebene") \
                else float(np.dot(A.d, B.p - A.p))
            seite = _sign(signed) if self.wert > 0 and abs(signed) > self.wert / 2 else 1.0
            dist = signed * seite
        extra: list[float] = []
        if fall == "ebene-ebene" or (fall == "achse-achse" and abs(float(np.dot(A.d, B.d))) > 0.5):
            extra = list(L * (A.d - _sign(float(np.dot(A.d, B.d))) * B.d))
        elif fall == "achse-ebene":
            extra = [L * float(np.dot(A.d, B.d))]
        elif fall == "ebene-achse":
            extra = [L * float(np.dot(B.d, A.d))]
        return np.array(extra + [dist - self.wert])

    def pruefe(self, A, B):
        fall = self._fall(A, B)
        if fall == "ebene-ebene" and linien_winkel(A.d, B.d) > self.winkel_toleranz:
            w = linien_winkel(A.d, B.d)
            return Ergebnis("verletzt", f"{mm(self.wert)}, parallel", f"Ebenen um {grad(w)} verkippt", w, "°", ort=A.p,
                            punkte=[A.p, B.p], loesung=f"{A.teilname or 'Teil'} parallel ausrichten"
                                                       f"{_platziere_tipp(self)}")
        dist, pa, pb = self._messen(A, B)
        abw = dist - self.wert
        if abs(abw) > self.toleranz:
            richtung_ = einheit(pa - pb) if np.linalg.norm(pa - pb) > 1e-9 else np.array([0.0, 0.0, 1.0])
            return Ergebnis("verletzt", mm(self.wert), mm(dist), abw, "mm", ort=pa, punkte=[pa, pb],
                            loesung=_schieben_text(A, richtung_, abw) + _platziere_tipp(self))
        return _ok(mm(self.wert), mm(dist), abw, punkte=[pa, pb])


class Tangential(Bedingung):
    """Berührung gekrümmter Flächen: Zylinder oder Kugel auf Ebene, Zylinder an Zylinder, Kugel an Kugel.
    ``innen=True``: das eine Teil läuft innen im anderen (Abstand der Achsen = Differenz der Radien)."""

    art, symbol, nimmt = "tangential", "tangential", 1

    def __init__(self, a: Any, b: Any, innen: bool = False, **kw: Any) -> None:
        self.innen = bool(innen)
        super().__init__(a, b, **kw)

    def _pruefe_arten(self) -> None:
        if self.a.r is None and self.b.r is None:
            raise BedingungsFehler("tangential: mindestens ein Bezug muss gekrümmt sein (Zylinder, Kugel, Bohrung)")
        for wer, b in (("der erste Bezug", self.a), ("der zweite Bezug", self.b)):
            if b.r is None and b.art != "ebene":
                raise BedingungsFehler(f"tangential: {wer} ({b.anzeigename()}) ist weder Ebene noch Zylinder/Kugel")

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} berührt {B.anzeigename()}" + (" (innen)" if self.innen else "")

    def _soll_ist(self, A: Bezug, B: Bezug) -> tuple[float, float, np.ndarray, np.ndarray]:
        """(Soll-Abstand der Mitten/Achsen, Ist-Abstand, Punkt an A, Punkt an B)."""
        if B.art == "ebene" or A.art == "ebene":
            E, K = (B, A) if B.art == "ebene" else (A, B)
            c = K.mitte()
            dist = float(np.dot(E.d, c - E.p))
            foot = c - E.d * dist
            return float(K.r or 0), abs(dist), (c if K is A else foot), (foot if K is A else c)
        ra, rb = float(A.r or 0), float(B.r or 0)
        soll = abs(ra - rb) if self.innen else ra + rb
        if A.art == "achse" and B.art == "achse":
            off = _perp(B.d) @ (A.mitte() - B.p)
            return soll, float(np.linalg.norm(off)), A.mitte(), A.mitte() - off
        if B.art == "achse":
            off = _perp(B.d) @ (A.p - B.p)
            return soll, float(np.linalg.norm(off)), A.p, A.p - off
        if A.art == "achse":
            off = _perp(A.d) @ (B.p - A.p)
            return soll, float(np.linalg.norm(off)), B.p - off, B.p
        return soll, float(np.linalg.norm(A.p - B.p)), A.p, B.p

    def richtungen(self, A, B):
        if A.art == "achse" and B.art == "achse":
            return [(A.d, _sign(float(np.dot(A.d, B.d))) * B.d)]
        return []

    def zeilen(self, A, B):
        if B.art == "ebene" and A.r is not None:
            s = _sign(float(np.dot(B.d, A.mitte() - B.p)))
            return [(B.d, A.mitte(), B.p, s * float(A.r))]
        if A.art == "ebene" and B.r is not None:
            s = _sign(float(np.dot(A.d, B.mitte() - A.p)))
            return [(-A.d, A.p, B.mitte(), s * float(B.r))]
        return []

    def residuen(self, A, B, L):
        soll, ist, _, _ = self._soll_ist(A, B)
        extra: list[float] = []
        if A.art == "achse" and B.art == "ebene":
            extra = [L * float(np.dot(A.d, B.d))]
        elif B.art == "achse" and A.art == "ebene":
            extra = [L * float(np.dot(B.d, A.d))]
        elif A.art == "achse" and B.art == "achse":
            extra = list(L * (A.d - _sign(float(np.dot(A.d, B.d))) * B.d))
        return np.array(extra + [ist - soll])

    def pruefe(self, A, B):
        soll, ist, pa, pb = self._soll_ist(A, B)
        abw = ist - soll
        if abs(abw) > self.toleranz:
            was = "Luft" if abw > 0 else "Durchdringung"
            return Ergebnis("verletzt", f"Mittenabstand {mm(soll)} (Berührung)", f"{mm(ist)} ({was} {mm(abs(abw))})",
                            abw, "mm", ort=(pa + pb) / 2, punkte=[pa, pb],
                            loesung=_schieben_text(A, einheit(pa - pb) if np.linalg.norm(pa - pb) > 1e-9
                                                   else np.array([0, 0, 1.0]), abw) + _platziere_tipp(self))
        return _ok(f"Mittenabstand {mm(soll)}", mm(ist), abw, punkte=[pa, pb])


class Mittig(Bedingung):
    """Mitten übereinander: Mitte von a auf der Mitte von b, nur entlang ``achsen`` (Weltachsen, z. B. "xy")."""

    art, symbol, nimmt = "mittig", "mittig", 3

    def __init__(self, a: Any, b: Any, achsen: str = "xyz", **kw: Any) -> None:
        self.achsen = "".join(c for c in achsen.lower() if c in "xyz") or "xyz"
        self.nimmt = len(self.achsen)
        super().__init__(a, b, **kw)

    def beschreibung(self, A, B):
        welche = "" if self.achsen == "xyz" else f" in {self.achsen.upper()}"
        return f"{A.anzeigename()} mittig zu {B.anzeigename()}{welche}"

    def zeilen(self, A, B):
        return [(np.eye(3)["xyz".index(c)], A.mitte(), B.mitte(), 0.0) for c in self.achsen]

    def residuen(self, A, B, L):
        diff = A.mitte() - B.mitte()
        return np.array([diff["xyz".index(c)] for c in self.achsen])

    def pruefe(self, A, B):
        res = self.residuen(A, B, 1.0)
        abw = float(np.linalg.norm(res))
        punkte = [A.mitte(), B.mitte()]
        if abw > self.toleranz:
            move = -np.array([(A.mitte() - B.mitte())[k] if "xyz"[k] in self.achsen else 0.0 for k in range(3)])
            return Ergebnis("verletzt", f"Mitten gleich in {self.achsen.upper()}", f"Versatz {vektor(-move, 3)}", abw,
                            "mm", ort=A.mitte(), punkte=punkte,
                            loesung=f"{A.teilname or 'Teil'} um {vektor(move, 3)} mm verschieben{_platziere_tipp(self)}")
        return _ok(f"Mitten gleich in {self.achsen.upper()}", f"Versatz {mm(abw)}", abw, punkte=punkte)


class InBohrung(Bedingung):
    """Schraube in Bohrung: konzentrisch, Kopf liegt an der Öffnung auf, Durchmesser und Länge passen.

    ``gewinde=True``: die Bohrung ist ein Gewinde-Kernloch (die Schraube schraubt sich hinein), sonst eine
    Durchgangsbohrung. ``klemmlaenge``: Dicke der geklemmten Teile über dem Gewinde (für die Einschraubtiefe).
    ``seite``: Ebene der Öffnung, auf der der Kopf liegt (Standard: die Öffnung, die weiter oben liegt)."""

    art, symbol, nimmt = "in_bohrung", "in_bohrung", 5

    def __init__(self, schraube: Any, bohrung: Any, gewinde: bool = False, klemmlaenge: float | None = None,
                 seite: Any = None, **kw: Any) -> None:
        from .geometrie import als_form

        form = als_form(schraube.teil_form if isinstance(schraube, Bezug) else schraube)
        if form is None:
            raise BedingungsFehler("in_bohrung: erstes Argument ist die Schraube (Teil aus verbauen(...))")
        self.gewinde = bool(gewinde)
        self.klemmlaenge = None if klemmlaenge is None else float(klemmlaenge)
        try:
            self.schraube = schraube_daten(form)
        except BezugFehler as exc:
            raise BedingungsFehler(str(exc)) from exc
        b = als_bezug(bohrung)
        if b.art != "achse" or b.r is None:
            raise BedingungsFehler(f"in_bohrung: zweites Argument muss eine Bohrung sein (bezug(teil, \"bohrung\", "
                                   f"nahe=…)), nicht {b.art} {b.anzeigename()}")
        self.bohrung_form = b.teil_form
        self.ende = self._ende(b, seite)
        p, n = bohrung_ende(self.bohrung_form, b, self.ende)
        self.eintritt = Bezug("ebene", p, n, form="oeffnung", name="Öffnung", quelle=b.quelle, M_q=b.M_q,
                              quelle_koerper=b.quelle_koerper, label=b.label, teil_form=b.teil_form)
        super().__init__(bezug(form), b, **kw)

    def _ende(self, b: Bezug, seite: Any) -> int:
        assert b.d is not None
        if seite is not None:
            s = als_bezug(seite)
            if s.d is None:
                raise BedingungsFehler("in_bohrung: seite muss eine Ebene sein (Fläche, an der der Kopf liegt)")
            return 1 if float(np.dot(s.d, b.d)) > 0 else -1
        # Sackloch: nur eine Öffnung ist offen
        offen = []
        for ende in (1, -1):
            p, n = bohrung_ende(self.bohrung_form, b, ende)
            if self.bohrung_form is None or not punkt_im_koerper(self.bohrung_form, p + n * 0.3):
                offen.append(ende)
        if len(offen) == 1:
            return offen[0]
        # Schraube steht schon vor einer Öffnung: diese
        k = self.schraube.kopf.p
        ax = float(np.dot(k - b.p, b.d))
        assert b.t is not None
        if np.linalg.norm(_perp(b.d) @ (k - b.p)) < 1.2 * (b.r or 1) and \
                (b.t[1] - 0.01 <= ax <= b.t[1] + 2 * self.schraube.d or b.t[0] - 2 * self.schraube.d <= ax <= b.t[0] + 0.01):
            return 1 if ax > (b.t[0] + b.t[1]) / 2 else -1
        return 1 if float(b.d[2]) >= 0 else -1  # sonst die obere Öffnung

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} in {B.anzeigename()}"

    def _abgeleitet(self, A: Bezug, B: Bezug) -> tuple[Bezug, Bezug, Bezug]:
        """Schaftachse, Kopfauflage (mit A bewegt) und Öffnungsebene (mit B bewegt)."""
        MA = A.M_extra if A.M_extra is not None else np.eye(4)
        MB = B.M_extra if B.M_extra is not None else np.eye(4)
        return self.schraube.achse.bewegt(MA), self.schraube.kopf.bewegt(MA), self.eintritt.bewegt(MB)

    def richtungen(self, A, B):
        S, _, E = self._abgeleitet(A, B)
        return [(S.d, -E.d)]

    def zeilen(self, A, B):
        S, K, E = self._abgeleitet(A, B)
        e1, e2 = _basis(B.d)
        return [(e1, S.p, B.p, 0.0), (e2, S.p, B.p, 0.0), (E.d, K.p, E.p, 0.0)]

    def residuen(self, A, B, L):
        S, K, E = self._abgeleitet(A, B)
        return np.concatenate([L * (S.d + E.d), _perp(B.d) @ (S.p - B.p), [float(np.dot(E.d, K.p - E.p))]])

    def pruefe(self, A, B):
        S, K, E = self._abgeleitet(A, B)
        d_nenn, laenge = self.schraube.d, self.schraube.laenge
        r_b = float(B.r or 0)
        mx = self.schraube.bezeichnung  # „M6“ oder „3/8"-16 UNC“
        gew = self.schraube.gewinde if self.schraube.gewinde is not None and \
            abs(self.schraube.gewinde.d - d_nenn) < 0.05 else None
        norm = "free fit" if gew is not None and gew.zoll else "ISO 273 mittel"
        befunde: list[Ergebnis] = []
        punkte = [K.p, E.p]
        # Lage
        w = winkel_grad(S.d, -E.d)
        off = _perp(B.d) @ (K.p - B.p)
        versatz = float(np.linalg.norm(off))
        spalt = float(np.dot(E.d, K.p - E.p))
        if w > max(self.winkel_toleranz, 0.05):
            befunde.append(Ergebnis("verletzt", "Schraube in Bohrungsrichtung", f"um {grad(w)} schräg", w, "°", ort=K.p,
                                    punkte=punkte, loesung=f"Schraube mit platziere({A.teilname or 'schraube'}, "
                                                           f"in_bohrung(…)) setzen (Zeile {self.zeile})"))
        if versatz > self.toleranz:
            befunde.append(Ergebnis("verletzt", "Schraube mittig in der Bohrung", f"Versatz {mm(versatz)}", versatz,
                                    "mm", ort=K.p, punkte=[K.p, K.p - off],
                                    loesung=f"Schraube um {vektor(-off, 3)} mm verschieben oder die Bohrung auf die "
                                            f"Schraubenachse legen{_platziere_tipp(self)}"))
        if abs(spalt) > self.toleranz:
            was = "steht über" if spalt > 0 else "steckt zu tief"
            befunde.append(Ergebnis("verletzt", "Kopf liegt auf", f"Kopf {was} ({mm(abs(spalt))})", spalt, "mm",
                                    ort=K.p, punkte=punkte, loesung=_schieben_text(A, E.d, spalt) + _platziere_tipp(self)))
        # Durchmesser
        d_bohr = 2 * r_b
        steig = self.schraube.steigung or REGEL_STEIGUNG.get(round(d_nenn, 1)) or REGEL_STEIGUNG.get(int(d_nenn))
        if self.gewinde:
            kern = gew.kernloch if gew is not None else d_nenn - (steig or 0.1 * d_nenn)
            if d_bohr > d_nenn - 0.05:
                befunde.append(Ergebnis("verletzt", f"Kernloch Ø {mm(kern, 2)} für {mx}", f"Ø {mm(d_bohr, 2)}",
                                        d_bohr - kern, "mm", ort=B.p, punkte=[B.p],
                                        loesung=f"Bohrung ist so groß wie das Gewinde: Kernloch Ø {mm(kern, 2)} bohren "
                                                f"oder Durchgangsbohrung mit Mutter (gewinde=False)"))
            elif d_bohr < kern - 0.4:
                befunde.append(Ergebnis("verletzt", f"Kernloch Ø {mm(kern, 2)} für {mx}", f"Ø {mm(d_bohr, 2)}",
                                        d_bohr - kern, "mm", ort=B.p, punkte=[B.p], schwere="warnung",
                                        loesung=f"Kernloch auf Ø {mm(kern, 2)} aufbohren"))
        else:
            mittel = gew.durchgang if gew is not None else \
                DURCHGANG_MITTEL.get(round(d_nenn, 1), DURCHGANG_MITTEL.get(int(d_nenn), d_nenn * 1.1))
            if d_bohr < d_nenn - 0.01:
                kleiner = max((k for k in DURCHGANG_MITTEL if DURCHGANG_MITTEL[k] <= d_bohr + 1e-9), default=None)
                tipp = f" oder kleinere Schraube (M{zahl(kleiner)})" if kleiner else ""
                befunde.append(Ergebnis("verletzt", f"Durchgang ≥ Ø {mm(d_nenn, 2)} für {mx} (mittel Ø {mm(mittel, 2)})",
                                        f"Ø {mm(d_bohr, 2)}", d_bohr - d_nenn, "mm", ort=B.p, punkte=[B.p],
                                        loesung=f"Bohrung auf Ø {mm(mittel, 2)} vergrößern ({norm}){tipp}"))
            elif d_bohr < d_nenn + 0.1:
                befunde.append(Ergebnis("verletzt", f"Durchgang Ø {mm(mittel, 2)} für {mx}", f"Ø {mm(d_bohr, 2)} "
                                        f"(ohne Spiel)", d_bohr - d_nenn, "mm", ort=B.p, punkte=[B.p], schwere="warnung",
                                        loesung=f"Bohrung auf Ø {mm(mittel, 2)} ({norm}) vergrößern"))
        # Länge
        assert B.t is not None
        tiefe = float(B.t[1] - B.t[0])
        form_b = B.form_welt()
        blind = False
        if form_b is not None:
            assert B.d is not None
            fern_p, fern_n = bohrung_ende(None, B, -self.ende)
            blind = punkt_im_koerper(form_b, fern_p + fern_n * 0.3)
        if self.gewinde:
            klemm = self.klemmlaenge or 0.0
            einschraub = laenge - klemm
            if blind and einschraub > tiefe - 0.2:
                befunde.append(Ergebnis("verletzt", f"Einschraubtiefe ≤ {mm(tiefe - 0.2, 1)} (Sackloch)",
                                        f"{mm(einschraub, 1)}", einschraub - tiefe, "mm", ort=B.p, punkte=[B.p],
                                        loesung=f"Schraube um {mm(math.ceil(einschraub - tiefe + 0.2), 0)} kürzer "
                                                f"wählen oder das Loch tiefer bohren"))
            greift = min(einschraub, tiefe)
            if greift < d_nenn - 0.01:
                befunde.append(Ergebnis("verletzt", f"Einschraubtiefe ≥ {mm(d_nenn, 1)} (1 × d, Stahl)",
                                        mm(greift, 1), greift - d_nenn, "mm", ort=B.p, punkte=[B.p], schwere="warnung",
                                        loesung="längere Schraube oder tieferes Gewinde; in Alu und Kunststoff "
                                                "1,5–2 × d"))
        else:
            if laenge < tiefe - 0.01:
                befunde.append(Ergebnis("verletzt", f"Schaft ≥ {mm(tiefe, 1)} (Bohrungslänge)", mm(laenge, 1),
                                        laenge - tiefe, "mm", ort=B.p, punkte=[B.p],
                                        loesung=f"Schraube mindestens {mx} × {zahl(math.ceil(tiefe + d_nenn))} wählen "
                                                f"(Bohrung plus Mutter)"))
        if not befunde:
            return _ok(f"{mx} × {zahl(laenge, 1)} in Ø {mm(d_bohr, 2)}", "sitzt", 0.0, punkte=punkte)
        haupt = befunde[0]
        haupt.weitere = befunde[1:]
        if all(b.schwere != "fehler" for b in befunde):
            haupt.schwere = "warnung"
        return haupt

    def info(self) -> dict[str, Any]:
        return {"schraube": {"d": self.schraube.d, "laenge": round(self.schraube.laenge, 3),
                             "bezeichnung": self.schraube.bezeichnung}, "gewinde": self.gewinde}


# ---------------------------------------------------------------------------------------------------------------------
# Gelenke (auf Basis der build123d-Joints, siehe als_joints)


# Freiraum je Bedienart (mm). Hebel und Klappen: Abstand am Griffpunkt über den ganzen Weg. Teile, die um ihre eigene
# Achse gedreht werden (Flügelmutter, Knopf; "fluegel" immer, "finger"/"hand" bei Schwerpunkt auf der Achse): Griffraum
# als Ring um die Drehachse über der Auflage, radial Spitze plus Freiraum, axial Oberkante plus Freiraum.
FREIRAUM = {"finger": 15.0, "hand": 25.0, "werkzeug": 10.0, "fluegel": 10.0}


class Gelenk(Bedingung):
    """Grundklasse der Gelenke. Bewegungsraum (B8): ``bereich`` wird bei jedem Lauf über den ganzen Weg geprüft
    (``schritte``, Kollision gegen alle nicht mitbewegten Teile); ``mitbewegt`` sind Teile, die mit dem bewegten Teil
    fest verbunden sind (Schrauben, Griff); ``ignorieren`` Teile, die nicht stören (z. B. ein Polster).
    Bedienteile: ``bedienung="finger" | "hand" | "werkzeug"`` oder ``freiraum=mm`` verlangt am ``griff`` (Punkt oder
    Bezug am bewegten Teil, sonst der Punkt am weitesten von der Achse) über den ganzen Weg so viel Platz. Teile, die
    um ihre eigene Achse gedreht werden (Flügelmutter, Flügelschraube, Knopf: ``bedienung="fluegel"``, bei
    ``"finger"``/``"hand"`` ohne ``griff``, wenn der Schwerpunkt auf der Drehachse liegt), prüfen stattdessen den
    Griffraum: einen Ring um die Drehachse über der Auflage, bis Spitze plus Freiraum.

    Statik (PLAN-STATIK.md T30, T33): Ein Gelenk mit ``bereich`` gilt in Stabwerk, Ablauf und Festkörper als
    festgestellt (Einstellung mit Klemme, Sterngriff, Kopf). ``frei=True`` sagt, dass es im Betrieb wirklich frei läuft
    (Schublade, Tür ohne Feststeller, Schlitten ohne Klemme): Dann rechnet die Statik es als Gelenk, der Ablauf lässt es
    laufen und hält es an den Enden von ``bereich`` an. Ohne ``bereich`` läuft ein Gelenk ohnehin frei."""

    gruppe = "gelenk"
    joint_art = ""
    anim_art = ""

    def __init__(self, a: Any, b: Any, bereich: tuple[float, float] | None = None, weg_pruefen: bool = True,
                 schritte: int | None = None, mitbewegt: Any = None, ignorieren: Any = None,
                 bedienung: str | None = None, freiraum: float | None = None, griff: Any = None, frei: bool = False,
                 **kw: Any) -> None:
        if not isinstance(frei, bool):
            raise BedingungsFehler(f"frei={frei!r}: True (läuft im Betrieb frei) oder False (festgestellt, Vorgabe)")
        self.frei = frei
        self.bereich = None if bereich is None else (float(bereich[0]), float(bereich[1]))
        if self.bereich is not None and self.bereich[0] > self.bereich[1]:
            raise BedingungsFehler(f"bereich {self.bereich}: erst der kleinere, dann der größere Wert")
        self.weg_pruefen = bool(weg_pruefen)
        self.schritte = None if schritte is None else max(1, int(schritte))
        self.mitbewegt = [] if mitbewegt is None else list(mitbewegt if isinstance(mitbewegt, (list, tuple))
                                                           else [mitbewegt])
        self.ignorieren = [] if ignorieren is None else list(ignorieren if isinstance(ignorieren, (list, tuple))
                                                             else [ignorieren])
        if bedienung is not None and bedienung not in FREIRAUM:
            raise BedingungsFehler(f"bedienung {bedienung!r}: erlaubt sind {', '.join(FREIRAUM)}")
        self.bedienung = bedienung
        self.freiraum = float(freiraum) if freiraum is not None else (FREIRAUM[bedienung] if bedienung else None)
        self.griff = griff
        self._phi_ref: float | None = None
        self._axial_ref: float | None = None
        self.achse_welt: tuple[np.ndarray, np.ndarray] | None = None  # nach der Prüfung: Achse in der gezeigten Lage
        super().__init__(a, b, **kw)

    def grenzen(self) -> tuple[float, float] | None:
        return self.bereich

    def fuer_animation(self, lage: Any = None) -> dict[str, Any]:
        """Achse und Grenzen für ``anim.gelenk(name, **gelenk.fuer_animation(), werte={0: 0, 2: 90})`` (Strang ANI):
        ``{"art": "dreh" | "schub", "achse": ((x, y, z), (dx, dy, dz)), "grenzen": (min, max) | None}``.

        Die Werte der Animation zählen ab der Ruhelage aus model.py, also ab dem Gelenkwert, mit dem platziert wurde
        (``winkel`` bzw. ``weg``); die Grenzen sind darum um diesen Wert verschoben. Die Achse gilt in der Lage, in der
        die Bezüge genommen wurden; wird das feste Teil danach noch verschoben gezeigt (``show(rig * teil)``),
        dieselbe Lage als ``lage`` übergeben."""
        if self.achse_welt is not None:
            p, d = self.achse_welt
        else:
            p, d = self.b.p, self.b.d if self.b.d is not None else np.array([0.0, 0.0, 1.0])
        if lage is not None:
            from .geometrie import trsf_matrix

            M = trsf_matrix(lage.wrapped.Transformation()) if hasattr(lage, "wrapped") \
                else np.asarray(lage, dtype=float)
            p, d = M[:3, :3] @ p + M[:3, 3], M[:3, :3] @ d
        grenzen = None
        if self.bereich is not None:
            w = self.wert()
            grenzen = (self.bereich[0] - w, self.bereich[1] - w)
        return {"art": self.anim_art or "dreh", "achse": (tuple(round(float(c), 6) for c in p),
                                                          tuple(round(float(c), 9) for c in d)),
                "grenzen": grenzen}

    def wert(self) -> float:
        return 0.0

    def einheit_wert(self) -> str:
        return "°"

    def bewegung(self, B: Bezug, von: float, nach: float) -> np.ndarray:
        """Lageänderung des bewegten Teils von Gelenkwert ``von`` nach ``nach`` (4×4, Welt)."""
        return np.eye(4)

    def info(self) -> dict[str, Any]:
        out: dict[str, Any] = {"gelenk": self.joint_art, "wert": self.wert(), "wert_einheit": self.einheit_wert()}
        if self.bereich is not None:
            out["bereich"] = list(self.bereich)
        if self.frei:  # Statik: läuft im Betrieb frei, auch mit Bereich (T33)
            out["frei"] = True
        return out

    def _bereich_ergebnis(self, ist: float, punkte: list[np.ndarray]) -> Ergebnis | None:
        if self.bereich is None:
            return None
        lo, hi = self.bereich
        if ist < lo - 1e-9 or ist > hi + 1e-9:
            e = self.einheit_wert()
            fmt = grad if e == "°" else mm
            return Ergebnis("verletzt", f"{fmt(lo)} … {fmt(hi)}", fmt(ist), ist - (lo if ist < lo else hi), e,
                            ort=punkte[0] if punkte else None, punkte=punkte,
                            loesung=f"Gelenkwert in den Bereich legen oder bereich erweitern (Zeile {self.zeile})")
        return None

    def als_joints(self, fest_teil: Any, bewegt_teil: Any, label: str | None = None) -> Any:
        """Dieselbe Verbindung als build123d-Joints an den beiden Teilen (für Animation und Baugruppen):
        liefert ``GelenkJoints`` mit ``.fest`` (Revolute/Linear/Cylindrical/BallJoint am festen Teil), ``.bewegt``
        (RigidJoint am bewegten Teil) und ``setze(wert)``, das das bewegte Teil wie dieses Gelenk stellt."""
        raise NotImplementedError


@dataclass
class GelenkJoints:
    gelenk: Gelenk
    fest: Any
    bewegt: Any

    def setze(self, wert: float | tuple[float, float] | None = None) -> None:
        self.gelenk._setze_joint(self, wert)


def _achsen_lage(p: np.ndarray, d: np.ndarray) -> Any:
    from build123d import Axis

    return Axis(tuple(map(float, p)), tuple(map(float, d)))


class Drehgelenk(Gelenk):
    """Drehgelenk: Achsen deckungsgleich, axial fest (``versatz`` oder wie modelliert), ein Freiheitsgrad Drehung.
    ``winkel`` dreht das bewegte Teil gegenüber der modellierten Lage, ``bereich=(min, max)`` in Grad."""

    art, symbol, nimmt, joint_art, anim_art = "drehgelenk", "drehgelenk", 5, "revolute", "dreh"

    def __init__(self, a: Any, b: Any, winkel: float = 0.0, bereich: tuple[float, float] | None = None,
                 versatz: float | None = None, **kw: Any) -> None:
        self.winkel = float(winkel)
        self.versatz = None if versatz is None else float(versatz)
        super().__init__(a, b, bereich=bereich, **kw)

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "achse", "der erste Bezug (bewegtes Teil)", self.art)
        _verlange(self.b, "achse", "der zweite Bezug (festes Teil)", self.art)

    def wert(self) -> float:
        return self.winkel

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} dreht um {B.anzeigename()}"

    def _s(self, A: Bezug, B: Bezug) -> float:
        return _sign(float(np.dot(A.d, B.d)))

    def richtungen(self, A, B):
        return [(A.d, self._s(A, B) * B.d)]

    def zeilen(self, A, B):
        e1, e2 = _basis(B.d)
        rows = [(e1, A.p, B.p, 0.0), (e2, A.p, B.p, 0.0)]
        axial = self.versatz if self.versatz is not None else float(np.dot(B.d, A.p - B.p))
        rows.append((B.d, A.p, B.p, axial))
        return rows

    def vor_platzieren(self, A, B):
        self._phi_ref = gerichteter_winkel(B.x, A.x, B.d)
        self._axial_ref = self.versatz if self.versatz is not None else float(np.dot(B.d, A.p - B.p))

    def nachdrehung(self, A, B):
        return drehung_um_gerade(B.p, B.d, self.winkel) if self.winkel else None

    def residuen(self, A, B, L):
        s = self._s(A, B)
        out = [L * (A.d - s * B.d), _perp(B.d) @ (A.p - B.p)]
        if self._axial_ref is not None:
            out.append([float(np.dot(B.d, A.p - B.p)) - self._axial_ref])
        return np.concatenate(out)

    def freie_bewegungen(self, A, B):
        return [("drehung", B.p, B.d)]

    def ist_winkel(self, A: Bezug, B: Bezug) -> float | None:
        if self._phi_ref is None:
            return None
        return _wrap(gerichteter_winkel(B.x, A.x, B.d) - self._phi_ref)

    def bewegung(self, B, von, nach):
        return drehung_um_gerade(B.p, B.d, nach - von)

    def pruefe(self, A, B):
        w = linien_winkel(A.d, B.d)
        off = _perp(B.d) @ (A.p - B.p)
        versatz = float(np.linalg.norm(off))
        punkte = [A.p, B.p]
        soll = "Achsen deckungsgleich"
        if w > self.winkel_toleranz:
            return Ergebnis("verletzt", soll, f"Achsen um {grad(w)} verkippt", w, "°", ort=A.p, punkte=punkte,
                            loesung=f"Gelenkteile mit platziere(…, {self.art}(…)) setzen (Zeile {self.zeile})")
        if versatz > self.toleranz:
            return Ergebnis("verletzt", soll, f"Versatz {mm(versatz)}", versatz, "mm", ort=A.p, punkte=punkte,
                            loesung=f"{A.teilname or 'Teil'} um {vektor(-off, 3)} mm verschieben{_platziere_tipp(self)}")
        if self._axial_ref is not None:
            ax = float(np.dot(B.d, A.p - B.p)) - self._axial_ref
            if abs(ax) > self.toleranz:
                return Ergebnis("verletzt", "axial fest", f"um {mm(ax)} entlang der Achse verschoben", ax, "mm",
                                ort=A.p, punkte=punkte, loesung=_schieben_text(A, B.d, ax) + _platziere_tipp(self))
        ist = self.ist_winkel(A, B)
        if ist is not None:
            if abs(_wrap(ist - self.winkel)) > max(self.winkel_toleranz, 0.05):
                return Ergebnis("verletzt", f"Winkel {grad(self.winkel)}", grad(ist), _wrap(ist - self.winkel), "°",
                                ort=A.p, punkte=punkte,
                                loesung="Teil nur über das Gelenk drehen (Wert winkel=…), nicht von Hand")
            fehler = self._bereich_ergebnis(ist, punkte)
            if fehler:
                return fehler
        return _ok(soll + (f", Winkel {grad(self.winkel)}" if ist is not None else ""), f"Versatz {mm(versatz)}",
                   versatz, punkte=punkte)

    def als_joints(self, fest_teil, bewegt_teil, label=None):
        from build123d import Location, Plane, RevoluteJoint, RigidJoint

        from .pruefung import aufloesen_an

        label = label or f"kevcad-{self.id or 'gelenk'}"
        A = aufloesen_an(self.a, bewegt_teil)
        B = aufloesen_an(self.b, fest_teil)
        lo, hi = self.bereich if self.bereich is not None else (-360.0, 360.0)
        fest = RevoluteJoint(label, to_part=fest_teil, axis=_achsen_lage(B.p, B.d),
                             angular_range=(lo - self.winkel, hi - self.winkel))
        # RigidJoint am bewegten Teil: die Achsenlage des festen Gelenks, wie das Teil gerade steht (Wert 0)
        lage = Location(Plane(origin=tuple(map(float, B.p)), z_dir=tuple(map(float, B.d))))
        bewegt = RigidJoint(label, to_part=bewegt_teil, joint_location=lage)
        _ = A
        return GelenkJoints(self, fest, bewegt)

    def _setze_joint(self, j: GelenkJoints, wert: Any) -> None:
        w = self.winkel if wert is None else float(wert)
        j.fest.connect_to(j.bewegt, angle=w - self.winkel)


class Schiebegelenk(Gelenk):
    """Schiebegelenk: Achsen deckungsgleich, Drehung um die Achse gesperrt, ein Freiheitsgrad Verschiebung.
    ``weg`` verschiebt gegenüber der modellierten Lage (mm), ``bereich=(min, max)``."""

    art, symbol, nimmt, joint_art, anim_art = "schiebegelenk", "schiebegelenk", 5, "linear", "schub"

    def __init__(self, a: Any, b: Any, weg: float = 0.0, bereich: tuple[float, float] | None = None, **kw: Any):
        self.weg = float(weg)
        super().__init__(a, b, bereich=bereich, **kw)

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "achse", "der erste Bezug (bewegtes Teil)", self.art)
        _verlange(self.b, "achse", "der zweite Bezug (festes Teil)", self.art)

    def wert(self) -> float:
        return self.weg

    def einheit_wert(self) -> str:
        return "mm"

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} gleitet entlang {B.anzeigename()}"

    def richtungen(self, A, B):
        return [(A.d, _sign(float(np.dot(A.d, B.d))) * B.d)]

    def zeilen(self, A, B):
        e1, e2 = _basis(B.d)
        return [(e1, A.p, B.p, 0.0), (e2, A.p, B.p, 0.0), (B.d, A.p, B.p, float(np.dot(B.d, A.p - B.p)))]

    def vor_platzieren(self, A, B):
        self._phi_ref = gerichteter_winkel(B.x, A.x, B.d)
        self._axial_ref = float(np.dot(B.d, A.p - B.p))

    def nachdrehung(self, A, B):
        return verschiebung(B.d * self.weg) if self.weg else None

    def residuen(self, A, B, L):
        s = _sign(float(np.dot(A.d, B.d)))
        out = [L * (A.d - s * B.d), _perp(B.d) @ (A.p - B.p)]
        if self._phi_ref is not None:
            out.append([L * math.radians(_wrap(gerichteter_winkel(B.x, A.x, B.d) - self._phi_ref))])
        return np.concatenate(out)

    def freie_bewegungen(self, A, B):
        return [("verschiebung", B.p, B.d)]

    def bewegung(self, B, von, nach):
        return verschiebung(B.d * (nach - von))

    def ist_weg(self, A: Bezug, B: Bezug) -> float | None:
        if self._axial_ref is None:
            return None
        return float(np.dot(B.d, A.p - B.p)) - self._axial_ref

    def pruefe(self, A, B):
        w = linien_winkel(A.d, B.d)
        off = _perp(B.d) @ (A.p - B.p)
        versatz = float(np.linalg.norm(off))
        punkte = [A.p, B.p]
        soll = "auf der Führung"
        if w > self.winkel_toleranz or versatz > self.toleranz:
            return Ergebnis("verletzt", soll, f"Versatz {mm(versatz)}, Winkel {grad(w)}", max(versatz, w), "mm",
                            ort=A.p, punkte=punkte, loesung=f"mit platziere(…, schiebegelenk(…)) setzen (Zeile "
                                                            f"{self.zeile})")
        if self._phi_ref is not None:
            dreh = _wrap(gerichteter_winkel(B.x, A.x, B.d) - self._phi_ref)
            if abs(dreh) > max(self.winkel_toleranz, 0.05):
                return Ergebnis("verletzt", "nicht verdreht", f"um {grad(dreh)} verdreht", dreh, "°", ort=A.p,
                                punkte=punkte, loesung="Teil nur entlang der Führung bewegen")
        ist = self.ist_weg(A, B)
        if ist is not None:
            if abs(ist - self.weg) > self.toleranz:
                return Ergebnis("verletzt", f"Weg {mm(self.weg)}", mm(ist), ist - self.weg, "mm", ort=A.p,
                                punkte=punkte, loesung="Teil nur über das Gelenk verschieben (Wert weg=…)")
            fehler = self._bereich_ergebnis(ist, punkte)
            if fehler:
                return fehler
        return _ok(soll, f"Versatz {mm(versatz)}", versatz, punkte=punkte)

    def als_joints(self, fest_teil, bewegt_teil, label=None):
        from build123d import Location, Plane, LinearJoint, RigidJoint

        from .pruefung import aufloesen_an

        label = label or f"kevcad-{self.id or 'gelenk'}"
        A = aufloesen_an(self.a, bewegt_teil)
        B = aufloesen_an(self.b, fest_teil)
        lo, hi = self.bereich if self.bereich is not None else (-1e6, 1e6)
        fest = LinearJoint(label, to_part=fest_teil, axis=_achsen_lage(B.p, B.d),
                           linear_range=(lo - self.weg, hi - self.weg))
        lage = Location(Plane(origin=tuple(map(float, B.p)), x_dir=tuple(map(float, B.x)),
                              z_dir=tuple(map(float, B.d))))
        _ = A
        bewegt = RigidJoint(label, to_part=bewegt_teil, joint_location=lage)
        return GelenkJoints(self, fest, bewegt)

    def _setze_joint(self, j: GelenkJoints, wert: Any) -> None:
        w = self.weg if wert is None else float(wert)
        j.fest.connect_to(j.bewegt, position=w - self.weg)


class Zylindergelenk(Gelenk):
    """Zylindergelenk: Achsen deckungsgleich, Drehung und Verschiebung entlang der Achse frei (2 Freiheitsgrade)."""

    art, symbol, nimmt, joint_art, anim_art = "zylindergelenk", "zylindergelenk", 4, "cylindrical", "dreh"

    def __init__(self, a: Any, b: Any, winkel: float = 0.0, weg: float = 0.0,
                 bereich: tuple[float, float] | None = None, **kw: Any) -> None:
        self.winkel, self.weg = float(winkel), float(weg)
        super().__init__(a, b, bereich=bereich, **kw)

    def _pruefe_arten(self) -> None:
        _verlange(self.a, "achse", "der erste Bezug (bewegtes Teil)", self.art)
        _verlange(self.b, "achse", "der zweite Bezug (festes Teil)", self.art)

    def wert(self) -> float:
        return self.winkel

    def info(self) -> dict[str, Any]:
        return {**super().info(), "weg": self.weg}

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} dreht und gleitet um {B.anzeigename()}"

    def richtungen(self, A, B):
        return [(A.d, _sign(float(np.dot(A.d, B.d))) * B.d)]

    def zeilen(self, A, B):
        e1, e2 = _basis(B.d)
        return [(e1, A.p, B.p, 0.0), (e2, A.p, B.p, 0.0)]

    def nachdrehung(self, A, B):
        M = drehung_um_gerade(B.p, B.d, self.winkel) if self.winkel else np.eye(4)
        if self.weg:
            M = verschiebung(B.d * self.weg) @ M
        return None if np.allclose(M, np.eye(4)) else M

    def residuen(self, A, B, L):
        s = _sign(float(np.dot(A.d, B.d)))
        return np.concatenate([L * (A.d - s * B.d), _perp(B.d) @ (A.p - B.p)])

    def freie_bewegungen(self, A, B):
        return [("drehung", B.p, B.d), ("verschiebung", B.p, B.d)]

    def bewegung(self, B, von, nach):
        return drehung_um_gerade(B.p, B.d, nach - von)

    def pruefe(self, A, B):
        w = linien_winkel(A.d, B.d)
        off = _perp(B.d) @ (A.p - B.p)
        versatz = float(np.linalg.norm(off))
        if w > self.winkel_toleranz or versatz > self.toleranz:
            return Ergebnis("verletzt", "Achsen deckungsgleich", f"Versatz {mm(versatz)}, Winkel {grad(w)}",
                            max(versatz, w), "mm", ort=A.p, punkte=[A.p, B.p],
                            loesung=f"mit platziere(…, zylindergelenk(…)) setzen (Zeile {self.zeile})")
        return _ok("Achsen deckungsgleich", f"Versatz {mm(versatz)}", versatz, punkte=[A.p, B.p])

    def als_joints(self, fest_teil, bewegt_teil, label=None):
        from build123d import CylindricalJoint, Location, Plane, RigidJoint

        from .pruefung import aufloesen_an

        label = label or f"kevcad-{self.id or 'gelenk'}"
        B = aufloesen_an(self.b, fest_teil)
        fest = CylindricalJoint(label, to_part=fest_teil, axis=_achsen_lage(B.p, B.d),
                                linear_range=(-1e6, 1e6), angular_range=(-360, 360))
        lage = Location(Plane(origin=tuple(map(float, B.p)), z_dir=tuple(map(float, B.d))))
        bewegt = RigidJoint(label, to_part=bewegt_teil, joint_location=lage)
        return GelenkJoints(self, fest, bewegt)

    def _setze_joint(self, j: GelenkJoints, wert: Any) -> None:
        w, s = (self.winkel, self.weg) if wert is None else (float(wert[0]), float(wert[1]))
        j.fest.connect_to(j.bewegt, angle=w - self.winkel, position=s - self.weg)


class Kugelgelenk(Gelenk):
    """Kugelgelenk: Punkte aufeinander, drei Drehungen frei. ``drehung=(rx, ry, rz)`` in Grad um den Punkt."""

    art, symbol, nimmt, joint_art = "kugelgelenk", "kugelgelenk", 3, "ball"

    def __init__(self, a: Any, b: Any, drehung: tuple[float, float, float] | None = None, **kw: Any) -> None:
        self.drehung = None if drehung is None else tuple(float(x) for x in drehung)
        super().__init__(a, b, **kw)

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} Kugelgelenk an {B.anzeigename()}"

    def zeilen(self, A, B):
        return [(np.eye(3)[k], A.mitte(), B.mitte(), 0.0) for k in range(3)]

    def nachdrehung(self, A, B):
        if not self.drehung:
            return None
        from .geometrie import pose

        R = drehmatrix(np.array([0, 0, 1.0]), math.radians(self.drehung[2])) @ \
            drehmatrix(np.array([0, 1.0, 0]), math.radians(self.drehung[1])) @ \
            drehmatrix(np.array([1.0, 0, 0]), math.radians(self.drehung[0]))
        return pose(R, B.mitte(), np.zeros(3))

    def residuen(self, A, B, L):
        return A.mitte() - B.mitte()

    def freie_bewegungen(self, A, B):
        return [("drehung", B.mitte(), np.eye(3)[k]) for k in range(3)]

    def pruefe(self, A, B):
        abw = float(np.linalg.norm(A.mitte() - B.mitte()))
        if abw > self.toleranz:
            return Ergebnis("verletzt", "Gelenkpunkte aufeinander", f"Versatz {mm(abw)}", abw, "mm", ort=A.mitte(),
                            punkte=[A.mitte(), B.mitte()],
                            loesung=f"mit platziere(…, kugelgelenk(…)) setzen (Zeile {self.zeile})")
        return _ok("Gelenkpunkte aufeinander", f"Versatz {mm(abw)}", abw, punkte=[A.mitte(), B.mitte()])

    def als_joints(self, fest_teil, bewegt_teil, label=None):
        from build123d import BallJoint, Location, RigidJoint

        from .pruefung import aufloesen_an

        label = label or f"kevcad-{self.id or 'gelenk'}"
        B = aufloesen_an(self.b, fest_teil)
        fest = BallJoint(label, to_part=fest_teil, joint_location=Location(tuple(map(float, B.mitte()))))
        bewegt = RigidJoint(label, to_part=bewegt_teil, joint_location=Location(tuple(map(float, B.mitte()))))
        return GelenkJoints(self, fest, bewegt)

    def _setze_joint(self, j: GelenkJoints, wert: Any) -> None:
        j.fest.connect_to(j.bewegt, angles=tuple(wert) if wert is not None else (0, 0, 0))


class Fest(Gelenk):
    """Starr verbunden: mit zwei ganzen Teilen bleibt die modellierte Lage zueinander; mit Bezügen fallen Punkt,
    Richtung und Bezugsrichtung zusammen. Kein Freiheitsgrad."""

    art, symbol, nimmt, joint_art = "fest", "fest", 6, "rigid"

    def __init__(self, a: Any, b: Any, **kw: Any) -> None:
        super().__init__(a, b, weg_pruefen=False, **kw)
        A, B = self.a, self.b
        self._teile = A.art == "teil" and B.art == "teil"
        self._ref = None
        if self._teile and A.M_q is not None and B.M_q is not None:
            self._ref = np.linalg.inv(B.M_q) @ A.M_q

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} fest an {B.anzeigename()}"

    @staticmethod
    def _rahmen(b: Bezug) -> np.ndarray:
        M = b.M_q if b.M_q is not None else np.eye(4)
        return (b.M_extra if b.M_extra is not None else np.eye(4)) @ M

    def richtungen(self, A, B):
        if self._teile:
            R = (self._rahmen(B) @ self._ref)[:3, :3] if self._ref is not None else np.eye(3)
            Ra = self._rahmen(A)[:3, :3]
            return [(Ra[:, 0], R[:, 0]), (Ra[:, 2], R[:, 2])]
        out = []
        if A.d is not None and B.d is not None:
            out.append((A.d, B.d))
            if A.x is not None and B.x is not None:
                out.append((A.x, B.x))
        return out

    def zeilen(self, A, B):
        if self._teile:
            soll = (self._rahmen(B) @ self._ref)[:3, 3] if self._ref is not None else self._rahmen(A)[:3, 3]
            ist = self._rahmen(A)[:3, 3]
            return [(np.eye(3)[k], ist, soll, 0.0) for k in range(3)]
        return [(np.eye(3)[k], A.p, B.p, 0.0) for k in range(3)]

    def residuen(self, A, B, L):
        if self._teile:
            if self._ref is None:
                return np.zeros(0)
            soll = self._rahmen(B) @ self._ref
            ist = self._rahmen(A)
            return np.concatenate([L * (ist[:3, :3] - soll[:3, :3]).ravel(), ist[:3, 3] - soll[:3, 3]])
        out = [A.p - B.p]
        if A.d is not None and B.d is not None:
            out.append(L * (A.d - B.d))
            if A.x is not None and B.x is not None:
                out.append(L * (A.x - B.x))
        return np.concatenate(out)

    def pruefe(self, A, B):
        res = self.residuen(A, B, 100.0)
        abw = float(np.max(np.abs(res))) if len(res) else 0.0
        if abw > self.toleranz:
            return Ergebnis("verletzt", "starr verbunden", f"Lage weicht ab ({mm(abw)})", abw, "mm", ort=A.p,
                            punkte=[A.p, B.p], loesung=f"{A.teilname or 'Teil'} zusammen mit {B.teilname or 'Teil'} "
                                                       f"bewegen (gleiche Lageänderung) oder mit platziere setzen")
        return _ok("starr verbunden", "Lage stimmt", abw, punkte=[A.p, B.p])

    def als_joints(self, fest_teil, bewegt_teil, label=None):
        from build123d import Location, RigidJoint

        label = label or f"kevcad-{self.id or 'fest'}"
        lage = fest_teil.location  # beide Joints an derselben Stelle: die modellierte Lage bleibt
        fest = RigidJoint(label, to_part=fest_teil, joint_location=lage)
        bewegt = RigidJoint(label, to_part=bewegt_teil, joint_location=lage)
        _ = Location
        return GelenkJoints(self, fest, bewegt)

    def _setze_joint(self, j: GelenkJoints, wert: Any) -> None:
        j.fest.connect_to(j.bewegt)


# ---------------------------------------------------------------------------------------------------------------------
# Befestigung (B9)

VERBINDUNGSARTEN = ("schraube", "klemmung", "steck", "formschluss", "kleben", "aufliegen")


class Verbindung(Bedingung):
    """Befestigung zweier Teile (B9): ``verbinde(a, b, art=..., mit=[Schraube, Mutter, …])``. ``b`` darf ``boden``
    sein. Die Prüfung kontrolliert, dass die Verbindung physisch da ist (siehe befestigung.py)."""

    art, gruppe, symbol = "verbinde", "befestigung", "verbinde"

    def __init__(self, a: Any, b: Any, art: str = "aufliegen", mit: Any = None, spiel: float = 0.5,
                 **kw: Any) -> None:
        if art not in VERBINDUNGSARTEN:
            import difflib

            tips = difflib.get_close_matches(str(art), VERBINDUNGSARTEN, n=2, cutoff=0.4)
            raise BedingungsFehler(f"verbinde: art {art!r} unbekannt (erlaubt: {', '.join(VERBINDUNGSARTEN)})"
                                   + (f". Meinten Sie {' oder '.join(repr(t) for t in tips)}?" if tips else ""))
        self.verbindungsart = art
        liste = [] if mit is None else list(mit if isinstance(mit, (list, tuple)) else [mit])
        self.mit = [als_bezug(m) for m in liste]
        self.spiel = float(spiel)
        if art == "schraube" and not self.mit:
            raise BedingungsFehler("verbinde(..., art=\"schraube\") braucht mit=[schraube, (mutter, scheibe …)]")
        super().__init__(a, b, **kw)

    def _pruefe_arten(self) -> None:
        for wer, b in (("erstes Teil", self.a), ("zweites Teil", self.b)):
            if b.art != "teil" and not (b.welt and b.art == "ebene"):
                raise BedingungsFehler(f"verbinde: {wer} muss ein Teil sein (oder boden), nicht {b.art} "
                                       f"{b.anzeigename()}")

    def beschreibung(self, A, B):
        mit = f" mit {', '.join(m.anzeigename() for m in self.mit)}" if self.mit else ""
        return f"{A.anzeigename()} {self.verbindungsart} an {B.anzeigename()}{mit}"

    def info(self) -> dict[str, Any]:
        return {"verbindung": self.verbindungsart}


# ---------------------------------------------------------------------------------------------------------------------
# Maßbedingungen


class Gleich(Bedingung):
    """Werte gleich: Zahlen, Parameternamen oder Bezüge (Radius bei Zylinder/Kreis/Kugel, Länge bei Kanten)."""

    art, gruppe, symbol = "gleich", "mass", "gleich"

    def __init__(self, a: Any, b: Any, *weitere: Any, toleranz: float | None = None, name: str | None = None) -> None:
        self.werte = [a, b, *weitere]
        bez = [als_bezug(w) for w in self.werte if not isinstance(w, (int, float, str))]
        super().__init__(*bez, toleranz=toleranz, name=name)

    @staticmethod
    def _zahl(w: Any, params: dict[str, Any]) -> tuple[float | None, str]:
        if isinstance(w, bool):
            return float(w), str(w)
        if isinstance(w, (int, float)):
            return float(w), zahl(w)
        if isinstance(w, str):
            v = params.get(w)
            return (float(v) if isinstance(v, (int, float)) else None), w
        b = als_bezug(w)
        if b.r is not None:
            return 2 * float(b.r), f"Ø {b.anzeigename()}"
        if b.t is not None:
            return float(b.t[1] - b.t[0]), f"Länge {b.anzeigename()}"
        return None, b.anzeigename()

    def beschreibung_werte(self, params: dict[str, Any], bezuege: list[Bezug]) -> tuple[list[float | None], list[str]]:
        werte, namen = [], []
        it = iter(bezuege)
        for w in self.werte:
            if isinstance(w, (int, float, str)):
                v, n = self._zahl(w, params)
            else:
                b = next(it)
                v, n = self._zahl(b, params)
            werte.append(v)
            namen.append(n)
        return werte, namen

    def pruefe_werte(self, params: dict[str, Any], bezuege: list[Bezug]) -> tuple[str, Ergebnis]:
        werte, namen = self.beschreibung_werte(params, bezuege)
        text = " = ".join(namen)
        if any(v is None for v in werte):
            fehlt = [n for v, n in zip(werte, namen) if v is None]
            return text, Ergebnis("ungeprueft", hinweis=f"Wert unbekannt: {', '.join(fehlt)}")
        lo, hi = min(werte), max(werte)  # type: ignore[type-var]
        abw = float(hi - lo)  # type: ignore[operator]
        ist = " / ".join(zahl(v) for v in werte)
        if abw > self.toleranz:
            return text, Ergebnis("verletzt", "gleich", ist, abw, "mm", ort=bezuege[0].p if bezuege else None,
                                  loesung=f"Werte angleichen: {text} (Differenz {zahl(abw)}); am besten aus einem "
                                          "Parameter ableiten")
        return text, _ok("gleich", ist, abw)


def _teil_form(b: Bezug) -> Any:
    return b.form_welt()


class Spiel(Bedingung):
    """Luft zwischen zwei Teilen (kleinster Abstand der Körper) oder je Seite zwischen Welle und Bohrung
    (zwei Zylinder-Bezüge); ``min`` und/oder ``max`` in mm."""

    art, gruppe, symbol = "spiel", "mass", "spiel"

    def __init__(self, a: Any, b: Any, min: float | None = None, max: float | None = None, **kw: Any) -> None:  # noqa: A002
        if min is None and max is None:
            raise BedingungsFehler(f"{self.art}: min und/oder max angeben, z. B. {self.art}(deckel, gehaeuse, min=0.2)")
        self.min = None if min is None else float(min)
        self.max = None if max is None else float(max)
        super().__init__(a, b, **kw)

    def beschreibung(self, A, B):
        grenzen = []
        if self.min is not None:
            grenzen.append(f"≥ {mm(self.min)}")
        if self.max is not None:
            grenzen.append(f"≤ {mm(self.max)}")
        return f"Spiel {A.anzeigename()} ↔ {B.anzeigename()} {' und '.join(grenzen)}"

    def messen(self, A: Bezug, B: Bezug) -> tuple[float | None, np.ndarray | None, np.ndarray | None, str]:
        """(Spiel, Punkt an A, Punkt an B, Art der Messung)."""
        if A.r is not None and B.r is not None and A.d is not None and B.d is not None \
                and linien_winkel(A.d, B.d) < 1.0:
            off = float(np.linalg.norm(_perp(B.d) @ (A.mitte() - B.p)))
            spiel = abs(float(B.r) - float(A.r)) - off
            return spiel, A.mitte(), B.mitte(), "je Seite"
        fa, fb = _teil_form(A), _teil_form(B)
        if A.art != "teil" or B.art != "teil" or fa is None or fb is None:
            d, p = _kontakt(A, B)
            return d, p, None, "Abstand"
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape

        dist = BRepExtrema_DistShapeShape(fa.wrapped, fb.wrapped)
        if not dist.IsDone() or dist.NbSolution() == 0:
            return None, None, None, "Abstand"
        pa, pb = dist.PointOnShape1(1), dist.PointOnShape2(1)
        value = float(dist.Value())
        if value < 1e-9:
            from build123d import Shape

            try:
                inter = (fa & fb)
                vol = float(inter.volume) if isinstance(inter, Shape) else 0.0
            except Exception:  # noqa: BLE001
                vol = 0.0
            if vol > 1e-6:
                return -vol ** (1 / 3), np.array([pa.X(), pa.Y(), pa.Z()]), np.array([pb.X(), pb.Y(), pb.Z()]), \
                    "Durchdringung"
        return value, np.array([pa.X(), pa.Y(), pa.Z()]), np.array([pb.X(), pb.Y(), pb.Z()]), "Abstand"

    def pruefe(self, A, B):
        spiel, pa, pb, wie = self.messen(A, B)
        soll = []
        if self.min is not None:
            soll.append(f"≥ {mm(self.min)}")
        if self.max is not None:
            soll.append(f"≤ {mm(self.max)}")
        soll_text = " und ".join(soll) + (f" ({wie})" if wie == "je Seite" else "")
        punkte = [p for p in (pa, pb) if p is not None]
        if spiel is None:
            return Ergebnis("ungeprueft", soll_text, hinweis="Abstand nicht messbar")
        ist = f"Durchdringung (~{mm(-spiel, 2)})" if wie == "Durchdringung" else mm(spiel)
        if self.min is not None and spiel < self.min - 1e-6:
            return Ergebnis("verletzt", soll_text, ist, spiel - self.min, "mm", ort=pa, punkte=punkte,
                            loesung=f"{mm(self.min - spiel)} mehr Luft: {A.teilname or 'Teil'} kleiner, "
                                    f"{B.teilname or 'Gegenstück'} größer oder weiter auseinander")
        if self.max is not None and spiel > self.max + 1e-6:
            return Ergebnis("verletzt", soll_text, ist, spiel - self.max, "mm", ort=pa, punkte=punkte,
                            schwere="warnung", loesung=f"{mm(spiel - self.max)} weniger Luft (Passung enger machen)")
        return _ok(soll_text, ist, 0.0, punkte=punkte)


class MinAbstand(Spiel):
    """Mindestabstand zwischen zwei Teilen oder Bezügen (z. B. Kabel zum Lüfter, Teil zum Boden)."""

    art, symbol = "min_abstand", "min_abstand"

    def __init__(self, a: Any, b: Any, wert: float, **kw: Any) -> None:
        super().__init__(a, b, min=float(wert), **kw)

    def beschreibung(self, A, B):
        return f"{A.anzeigename()} mindestens {mm(self.min)} von {B.anzeigename()}"


class MinWand(Bedingung):
    """Kleinste Wandstärke eines Teils (Strahlen von der Oberfläche nach innen über das Dreiecksnetz)."""

    art, gruppe, symbol = "min_wand", "mass", "min_wand"

    def __init__(self, teil: Any, wert: float, **kw: Any) -> None:
        self.wert = float(wert)
        super().__init__(teil, **kw)

    def beschreibung_teil(self, A: Bezug) -> str:
        return f"Wand von {A.anzeigename()} ≥ {mm(self.wert)}"

    def pruefe_netz(self, A: Bezug, netz: tuple[np.ndarray, np.ndarray, np.ndarray | None] | None) -> Ergebnis:
        """``netz``: (Punkte, Dreiecke, Normalen) der gezeigten Form in Weltlage."""
        if netz is None:
            return Ergebnis("ungeprueft", f"≥ {mm(self.wert)}", hinweis="kein Dreiecksnetz des Teils")
        from .wand import kleinste_wand

        dicke, ort = kleinste_wand(*netz)
        if dicke is None:
            return Ergebnis("ungeprueft", f"≥ {mm(self.wert)}", hinweis="Wandstärke nicht messbar")
        if dicke < self.wert - 1e-6:
            return Ergebnis("verletzt", f"≥ {mm(self.wert)}", mm(dicke, 2), dicke - self.wert, "mm", ort=ort,
                            punkte=[ort] if ort is not None else [],
                            loesung=f"Wand an dieser Stelle um {mm(self.wert - dicke, 2)} dicker machen (Parameter "
                                    "der Wandstärke erhöhen)")
        return _ok(f"≥ {mm(self.wert)}", mm(dicke, 2), dicke - self.wert, punkte=[ort] if ort is not None else [])
