"""Hüllquader-Zwischenspeicher für model.py (Prüftempo, 22.10.2026).

Am Kugelschieber gingen 84 von 126 s eines Laufs mit ``montage_pruefen=1`` in ``Shape.bounding_box()``: Die eigene
Ausbauprüfung in model.py fährt jedes Teil in Schritten und vergleicht in jedem Schritt die Hüllquader mit allen
noch verbauten Teilen (19.040 Aufrufe von ``BRepBndLib.AddOptimal``, je etwa 4 ms auf Torus- und Freiformflächen).
Dieselben Formen in derselben Lage kommen dabei hundertfach wieder.

Während model.py läuft, merkt sich ``bounding_box()`` (Standardaufruf ohne Toleranz, ``optimal=True``) deshalb das
Ergebnis je Form und Lage (``TopoDS_Shape.IsSame``: gleiche TShape, gleiche Location). Das Ergebnis ist dasselbe wie
ohne Speicher: build123d entfernt vor ``AddOptimal`` jedes Netz (``BRepTools.Clean``), der Hüllquader hängt also nur
an Geometrie und Lage; diesen Nebeneffekt behält der Treffer bei. Andere Aufrufe (mit Toleranz, ``optimal=False``)
gehen unverändert an build123d. Nach dem Lauf ist der Speicher wieder aus und leer.
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict
from collections.abc import Iterator
from typing import Any

MAXIMUM = 8192  # Einträge; ältere fallen heraus

_original: Any = None
_speicher: OrderedDict[int, list[tuple[Any, tuple[float, ...] | None]]] | None = None
statistik = {"treffer": 0, "neu": 0}


def _bounding_box(self: Any, tolerance: float | None = None, optimal: bool = True) -> Any:
    speicher = _speicher
    topo = getattr(self, "wrapped", None)
    if speicher is None or tolerance is not None or not optimal or topo is None:
        return _original(self, tolerance, optimal)
    from build123d.geometry import BoundBox
    from OCP.Bnd import Bnd_Box
    from OCP.BRepTools import BRepTools

    h = hash(topo)
    eintraege = speicher.get(h)
    if eintraege:
        for form, werte in eintraege:
            if form.IsSame(topo):
                speicher.move_to_end(h)
                statistik["treffer"] += 1
                BRepTools.Clean_s(topo)  # wie build123d: ein vorhandenes Netz entfernen (Nebeneffekt beibehalten)
                box = Bnd_Box()
                if werte is not None:
                    box.Update(*werte)
                return BoundBox(box)
    bb = _original(self, tolerance, optimal)
    werte = None if bb.wrapped is None else (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)
    speicher.setdefault(h, []).append((topo, werte))
    speicher.move_to_end(h)
    statistik["neu"] += 1
    while len(speicher) > MAXIMUM:
        speicher.popitem(last=False)
    return bb


@contextlib.contextmanager
def zwischenspeicher() -> Iterator[None]:
    """Hüllquader-Speicher für die Dauer des Blocks (ein Lauf von model.py) einschalten."""
    global _original, _speicher
    from build123d import Shape

    if _speicher is not None:  # schon an (verschachtelt)
        yield
        return
    _original = Shape.bounding_box
    _speicher = OrderedDict()
    statistik.update(treffer=0, neu=0)
    Shape.bounding_box = _bounding_box  # type: ignore[method-assign]
    try:
        yield
    finally:
        Shape.bounding_box = _original  # type: ignore[method-assign]
        _speicher = None
