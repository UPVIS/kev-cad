"""Zwangsbedingungen in model.py: ``from kevcad.bedingungen import *`` (PLAN-BEDINGUNGEN.md).

Teile hängen wie in CAD-Programmen über Bedingungen an ihrem Gegenstück statt an frei gewählten Koordinaten. Kev CAD
prüft nach jedem Lauf alle Bedingungen gegen die gezeigte Geometrie; verletzte sind Befunde wie eine Durchdringung
(rot im Viewer, Export gesperrt).

```python
rahmen = platziere(rahmen, auf((rahmen, "unten"), (rolle, "oben")),          # Fläche auf Fläche
                   konzentrisch((rahmen, "bohrung", {"nahe": p1}), (rolle, "achse")))
schraube = platziere(schraube, in_bohrung(schraube, bezug(platte, "bohrung", nahe=(40, 0, 0))))
klappe = platziere(klappe, drehgelenk((klappe, "achse"), (scharnier, "achse"), winkel=30, bereich=(0, 110),
                                      bedienung="finger"))
verbinde(platte, gestell, art="schraube", mit=[schraube, mutter])           # Befestigung (Pflicht)
wand = param("wand", 2.0, min=1.2)                                          # Grenzen: Verstoß ist ein Befund
spiel(deckel, gehaeuse, min=0.2)
```

Bezüge (``bezug(teil, name_oder_auswahl, auswahl=None, nahe=None, umkehren=False, richtung=None)`` oder als Tupel
``(teil, "unten")``): Standardnamen ``oben``/``unten`` (±Z), ``rechts``/``links`` (±X), ``hinten``/``vorn`` (±Y, vorn =
−Y wie die Vorderansicht), ``x_min`` … ``z_max``, ``mitte``, ``schwerpunkt``, ``achse`` (größter Zylinder),
``achse_x``/``achse_y``/``achse_z``, ``bohrung`` (mit ``nahe=(x, y, z)``), ``teil``; dazu build123d-Auswahlen (Fläche,
ebene Flächen einer Ebene, Kante, Punkt, Funktion ``lambda t: t.faces().sort_by(Axis.Z)[0]``), ``Plane``, ``Axis``,
``Location`` und Bezugspunkte aus dem Katalog. Nie Flächennummern. ``boden`` ist die Ebene z = 0.

Erster Bezug = das Teil, das sich anpasst (bei ``platziere`` das bewegte), zweiter = das Gegenstück.

Montage: ``auf`` (Flächen gegenüber, optional ``abstand``), ``buendig``, ``konzentrisch``, ``parallel``, ``senkrecht``,
``abstand(a, b, wert)``, ``winkel(a, b, wert)``, ``tangential(a, b, innen=False)``, ``mittig(a, b, achsen="xy")``,
``in_bohrung(schraube, bohrung, gewinde=False, klemmlaenge=None, seite=None)``.

Gelenke (Freiheitsgrade für Animation und Bewegungsraum, Grundlage build123d-Joints über ``gelenk.als_joints``):
``drehgelenk(a, b, winkel=0, bereich=None, versatz=None)``, ``schiebegelenk(a, b, weg=0, bereich=None)``,
``zylindergelenk(a, b, winkel=0, weg=0)``, ``kugelgelenk(a, b, drehung=None)``, ``fest(a, b)``. Mit ``bereich`` wird der
ganze Weg bei jedem Lauf auf Kollision geprüft (``schritte``, ``mitbewegt=[…]``, ``ignorieren=[…]``,
``bedienung="finger" | "hand" | "werkzeug" | "fluegel"`` oder ``freiraum=mm`` am ``griff``; Teile, die um ihre eigene
Achse gedreht werden, wie Flügelmuttern und Drehknöpfe, prüfen den Griffraum als Zylinder um die Drehachse über der
Auflage). ``gelenk.fuer_animation()`` liefert
Art, Achse und Grenzen für ``animation.gelenk``. Statik: Ein Gelenk mit ``bereich`` gilt als festgestellt (Einstellung
mit Klemme oder Sterngriff); läuft es im Betrieb wirklich frei (Schublade, Tür ohne Feststeller), ``frei=True`` angeben,
dann rechnen Stabwerk und Ablauf es als Gelenk mit Anschlägen an den Enden von ``bereich``.

Befestigung (Pflicht für jedes Teil): ``verbinde(a, b, art="schraube" | "klemmung" | "steck" | "formschluss" |
"kleben" | "aufliegen", mit=[schraube, mutter, scheibe])``; ``b`` darf ``boden`` sein.

Maße: ``param(name, wert, min, max)`` (aus ``kevcad``), ``gleich(a, b, …)``, ``spiel(a, b, min, max)``,
``min_abstand(a, b, wert)``, ``min_wand(teil, wert)``.

``platziere(teil, *bedingungen)`` liefert das Teil in der Lage, die alle Bedingungen erfüllt (wie ``Pos(...) *
teil``); widersprüchliche Bedingungen und freie Freiheitsgrade meldet die Prüfung.
"""

from __future__ import annotations

from typing import Any

from kevcad_kernel.bedingungen.arten import (
    Abstand,
    Auf,
    BedingungsFehler,
    Buendig,
    Drehgelenk,
    Fest,
    Gleich,
    InBohrung,
    Konzentrisch,
    Kugelgelenk,
    MinAbstand,
    MinWand,
    Mittig,
    Parallel,
    Schiebegelenk,
    Senkrecht,
    Spiel,
    Tangential,
    Verbindung,
    Winkel,
    Zylindergelenk,
)
from kevcad_kernel.bedingungen.geometrie import Bezug, BezugFehler, bohrungen_von, richte_bohrung
from kevcad_kernel.bedingungen.geometrie import bezug as _bezug
from kevcad_kernel.bedingungen.geometrie import boden as _boden
from kevcad_kernel.bedingungen.loeser import platziere

__all__ = [
    "BedingungsFehler", "Bezug", "BezugFehler", "abstand", "auf", "bezug", "boden", "bohrungen", "buendig",
    "drehgelenk", "fest", "gleich", "in_bohrung", "konzentrisch", "kugelgelenk", "min_abstand", "min_wand", "mittig",
    "parallel", "platziere", "schiebegelenk", "senkrecht", "spiel", "tangential", "verbinde", "winkel",
    "zylindergelenk",
]

boden: Bezug = _boden()


def bezug(teil: Any, name_oder_auswahl: Any = None, auswahl: Any = None, *, nahe: Any = None,
          umkehren: bool = False, richtung: Any = None) -> Bezug:
    """Benannter Bezug am Teil (siehe Moduldoku): ``bezug(platte, "oben")``, ``bezug(platte, "bohrung",
    nahe=(40, 0, 0))``, ``bezug(teil, "Auflage", teil.faces().sort_by(Axis.Z)[0])``.

    ``richtung=(1, 0, 0)`` oder ``"+x"`` legt die Richtung einer Achse bzw. Normale fest (Gelenke zählen ``bereich``
    und ``weg`` entlang der Richtung des festen Bezugs). Ohne Angabe zeigt eine Bohrung aus sich heraus durch ihre
    Eintrittsöffnung (Sackloch), eine Durchgangsbohrung in die positive Hauptrichtung (+Z, +X oder +Y)."""
    return _bezug(teil, name_oder_auswahl, auswahl, nahe=nahe, umkehren=umkehren, richtung=richtung)


def bohrungen(teil: Any) -> list[Bezug]:
    """Alle Bohrungen eines Teils als Achsen-Bezüge, sortiert nach Lage (x, y, z), gerichtet wie bei
    ``bezug(teil, "bohrung")``."""
    form = teil.part if hasattr(teil, "part") else teil
    return [richte_bohrung(form, b) for b in bohrungen_von(form)]


def auf(a: Any, b: Any, abstand: float = 0.0, **kw: Any) -> Auf:
    """Fläche a liegt auf Fläche b (Normalen gegenläufig), mit ``abstand`` mm Luft."""
    return Auf(a, b, abstand, **kw)


def buendig(a: Any, b: Any, abstand: float = 0.0, **kw: Any) -> Buendig:
    """Flächen in einer Ebene, gleich gerichtet (``abstand``: Versatz entlang der Normale)."""
    return Buendig(a, b, abstand, **kw)


def konzentrisch(a: Any, b: Any, **kw: Any) -> Konzentrisch:
    """Achsen deckungsgleich (Bohrung, Welle, Kreiskante); Kugelmitten aufeinander."""
    return Konzentrisch(a, b, **kw)


def parallel(a: Any, b: Any, **kw: Any) -> Parallel:
    return Parallel(a, b, **kw)


def senkrecht(a: Any, b: Any, **kw: Any) -> Senkrecht:
    return Senkrecht(a, b, **kw)


def abstand(a: Any, b: Any, wert: float, **kw: Any) -> Abstand:
    """Abstand in mm zwischen Ebenen (parallel), Punkten, Achsen."""
    return Abstand(a, b, wert, **kw)


def winkel(a: Any, b: Any, wert: float, **kw: Any) -> Winkel:
    """Winkel in Grad zwischen zwei Richtungen."""
    return Winkel(a, b, wert, **kw)


def tangential(a: Any, b: Any, innen: bool = False, **kw: Any) -> Tangential:
    """Zylinder oder Kugel berührt Ebene, Zylinder oder Kugel (``innen=True``: läuft innen)."""
    return Tangential(a, b, innen, **kw)


def mittig(a: Any, b: Any, achsen: str = "xyz", **kw: Any) -> Mittig:
    """Mitte von a auf der Mitte von b, nur entlang ``achsen`` (Weltachsen, z. B. "xy")."""
    return Mittig(a, b, achsen, **kw)


def in_bohrung(schraube: Any, bohrung: Any, gewinde: bool = False, klemmlaenge: float | None = None,
               seite: Any = None, **kw: Any) -> InBohrung:
    """Schraube in Bohrung: konzentrisch, Kopf liegt auf, Durchmesser und Länge passen (``gewinde=True``:
    Kernloch, sonst Durchgangsbohrung)."""
    return InBohrung(schraube, bohrung, gewinde, klemmlaenge, seite, **kw)


def drehgelenk(a: Any, b: Any, winkel: float = 0.0, bereich: tuple[float, float] | None = None,
               versatz: float | None = None, **kw: Any) -> Drehgelenk:
    """Drehgelenk: Achse a (bewegtes Teil) auf Achse b (festes Teil), ``winkel`` gegenüber der Modelllage."""
    return Drehgelenk(a, b, winkel, bereich, versatz, **kw)


def schiebegelenk(a: Any, b: Any, weg: float = 0.0, bereich: tuple[float, float] | None = None,
                  **kw: Any) -> Schiebegelenk:
    """Schiebegelenk entlang der Achse b, ``weg`` in mm gegenüber der Modelllage."""
    return Schiebegelenk(a, b, weg, bereich, **kw)


def zylindergelenk(a: Any, b: Any, winkel: float = 0.0, weg: float = 0.0,
                   bereich: tuple[float, float] | None = None, **kw: Any) -> Zylindergelenk:
    return Zylindergelenk(a, b, winkel, weg, bereich, **kw)


def kugelgelenk(a: Any, b: Any, drehung: tuple[float, float, float] | None = None, **kw: Any) -> Kugelgelenk:
    return Kugelgelenk(a, b, drehung, **kw)


def fest(a: Any, b: Any, **kw: Any) -> Fest:
    """Starr verbunden (Teile: modellierte Lage bleibt; Bezüge: Punkt und Richtungen aufeinander)."""
    return Fest(a, b, **kw)


def verbinde(a: Any, b: Any, art: str = "aufliegen", mit: Any = None, spiel: float = 0.5, **kw: Any) -> Verbindung:
    """Befestigung von a an b (Pflicht für jedes Teil): art schraube, klemmung, steck, formschluss, kleben,
    aufliegen; ``mit``: Schrauben, Muttern, Scheiben. Die Prüfung kontrolliert, dass die Verbindung da ist."""
    return Verbindung(a, b, art, mit, spiel, **kw)


def gleich(a: Any, b: Any, *weitere: Any, toleranz: float | None = None) -> Gleich:
    """Werte gleich: Zahlen, Parameternamen oder Bezüge (Durchmesser bzw. Länge)."""
    return Gleich(a, b, *weitere, toleranz=toleranz)


def spiel(a: Any, b: Any, min: float | None = None, max: float | None = None, **kw: Any) -> Spiel:  # noqa: A002
    """Luft zwischen zwei Teilen (kleinster Abstand) oder je Seite zwischen Welle und Bohrung."""
    return Spiel(a, b, min, max, **kw)


def min_abstand(a: Any, b: Any, wert: float, **kw: Any) -> MinAbstand:
    return MinAbstand(a, b, wert, **kw)


def min_wand(teil: Any, wert: float, **kw: Any) -> MinWand:
    """Kleinste Wandstärke des Teils in mm."""
    return MinWand(teil, wert, **kw)
