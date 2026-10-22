"""Flächen eines Teils für Teilsystem und Merkmalerkennung: Typ, Lage, Achse, Radius, Wölbung, Winkelspanne, Nachbarn.

Alle Werte in Weltkoordinaten (wie die Form in der Szene). Die Flächennummern folgen ``tessellate.faces_of``, also
derselben Zählung wie die Referenzen ``Teil#fN`` (PROTOCOL.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_SurfaceType
from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED
from OCP.TopoDS import TopoDS


_TYP = {
    GeomAbs_SurfaceType.GeomAbs_Plane: "ebene",
    GeomAbs_SurfaceType.GeomAbs_Cylinder: "zylinder",
    GeomAbs_SurfaceType.GeomAbs_Cone: "kegel",
    GeomAbs_SurfaceType.GeomAbs_Sphere: "kugel",
    GeomAbs_SurfaceType.GeomAbs_Torus: "torus",
}


def _v(p: Any) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=float)


@dataclass
class Flaeche:
    """Eine Fläche des Teils. ``n`` bei Ebenen ist die äußere Normale (zeigt aus dem Material)."""

    index: int
    typ: str  # ebene | zylinder | kegel | kugel | torus | andere
    flaeche: float  # mm²
    form: Any = field(repr=False, default=None)  # build123d-Face
    n: np.ndarray | None = None  # Ebene: äußere Normale
    punkt: np.ndarray | None = None  # Ebene: Mittelpunkt; Zylinder/Kegel: Punkt auf der Achse; Kugel/Torus: Mitte
    achse: np.ndarray | None = None  # Zylinder, Kegel, Torus
    radius: float | None = None  # Zylinder, Kugel, Torus (großer Radius), Kegel: Radius bei punkt
    radius2: float | None = None  # Torus: kleiner Radius
    halbwinkel: float | None = None  # Kegel, Grad
    innen: bool = False  # nach innen gewölbt (Bohrung, Kehle): Material liegt außen
    spanne: float = 360.0  # Winkelspanne um die Achse, Grad
    t: tuple[float, float] = (0.0, 0.0)  # Ausdehnung entlang der Achse ab punkt
    radien: tuple[float, float] | None = None  # Kegel: Radius bei t[0] und t[1]
    mitte: np.ndarray | None = None  # Schwerpunkt der Fläche (ungefähr: Mitte der Parameterfläche)
    lo: np.ndarray | None = None  # Hüllquader der Fläche
    hi: np.ndarray | None = None
    nachbarn: set[int] = field(default_factory=set)

    @property
    def rund(self) -> bool:
        return self.typ in ("zylinder", "kegel")


@dataclass
class Topologie:
    flaechen: list[Flaeche]
    lo: np.ndarray
    hi: np.ndarray

    @property
    def groesse(self) -> np.ndarray:
        return self.hi - self.lo


def _bbox(shape: Any) -> tuple[np.ndarray, np.ndarray]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    if box.IsVoid():
        return np.zeros(3), np.zeros(3)
    a, b = box.CornerMin(), box.CornerMax()
    return np.array([a.X(), a.Y(), a.Z()]), np.array([b.X(), b.Y(), b.Z()])


def analysiere(form: Any) -> Topologie:
    """Alle Flächen der Form mit ihren Kennwerten und Nachbarn (über gemeinsame Kanten)."""
    from build123d import Shape

    from kevcad_kernel.tessellate import faces_of

    shape = form if isinstance(form, Shape) else Shape.cast(form)
    faces = list(faces_of(shape))
    out = [_flaeche(i, f) for i, f in enumerate(faces)]
    # Nachbarn über gemeinsame Kanten (Hash ohne Orientierung; Nahtkanten derselben Fläche zählen nicht)
    from OCP.TopExp import TopExp_Explorer

    kanten: dict[int, set[int]] = {}
    for i, f in enumerate(faces):
        exp = TopExp_Explorer(f.wrapped, TopAbs_EDGE)
        while exp.More():
            kanten.setdefault(_schluessel(exp.Current()), set()).add(i)
            exp.Next()
    for ids in kanten.values():
        for a in ids:
            out[a].nachbarn.update(ids - {a})
    lo, hi = _bbox(shape.wrapped)
    return Topologie(out, lo, hi)


def _schluessel(s: Any) -> int:
    """Gleiche TShape und Lage (Orientierung egal), wie TopTools_ShapeMapHasher."""
    try:
        return hash(s)  # OCP: __hash__ nutzt den Shape-Hasher (ohne Orientierung)
    except TypeError:  # pragma: no cover
        return s.HashCode(1 << 30)


def _flaeche(i: int, f: Any) -> Flaeche:
    face = TopoDS.Face(f.wrapped)
    s = BRepAdaptor_Surface(face)
    typ = _TYP.get(s.GetType(), "andere")
    reversed_ = face.Orientation() == TopAbs_REVERSED
    try:
        area = float(f.area)
    except Exception:  # noqa: BLE001
        area = 0.0
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    info = Flaeche(index=i, typ=typ, flaeche=area, form=f)
    lo, hi = _bbox(face)
    info.lo, info.hi = lo, hi
    um, vm = (umin + umax) / 2, (vmin + vmax) / 2
    p_mid = _v(s.Value(um, vm))
    info.mitte = p_mid
    if typ == "ebene":
        pl = s.Plane()
        n = _v(pl.Axis().Direction())
        if reversed_:
            n = -n
        info.n = n / (np.linalg.norm(n) or 1.0)
        try:
            c = f.center()
            info.punkt = np.array([c.X, c.Y, c.Z], dtype=float)
        except Exception:  # noqa: BLE001
            info.punkt = p_mid
        return info
    if typ in ("zylinder", "kegel"):
        geo = s.Cylinder() if typ == "zylinder" else s.Cone()
        ax = geo.Axis()
        p0, d = _v(ax.Location()), _v(ax.Direction())
        d = d / (np.linalg.norm(d) or 1.0)
        info.achse, info.punkt = d, p0
        info.spanne = math.degrees(abs(umax - umin))
        if typ == "zylinder":
            info.radius = float(geo.Radius())
        else:
            info.halbwinkel = math.degrees(abs(float(geo.SemiAngle())))
            info.radius = float(geo.RefRadius())
        # Ausdehnung entlang der Achse über die Parameter (v ist bei Zylinder und Kegel die Achsrichtung)
        ts = []
        for u in (umin, um, umax):
            for v in (vmin, vmax):
                ts.append(float(np.dot(_v(s.Value(u, v)) - p0, d)))
        info.t = (min(ts), max(ts))
        if typ == "kegel":
            ends = []
            for v in (vmin, vmax):
                q = _v(s.Value(um, v))
                tq = float(np.dot(q - p0, d))
                ends.append((tq, float(np.linalg.norm(q - (p0 + d * tq)))))
            ends.sort()
            info.radien = (ends[0][1], ends[1][1])
        # Wölbung: äußere Normale zeigt zur Achse hin → nach innen gewölbt (Bohrung)
        from OCP.BRepLProp import BRepLProp_SLProps

        props = BRepLProp_SLProps(s, um, vm, 1, 1e-6)
        if props.IsNormalDefined():
            n = _v(props.Normal())
            if reversed_:
                n = -n
            radial = p_mid - (p0 + d * float(np.dot(p_mid - p0, d)))
            info.innen = bool(np.dot(n, radial) < 0)
        return info
    if typ == "kugel":
        sph = s.Sphere()
        info.punkt, info.radius = _v(sph.Location()), float(sph.Radius())
        info.spanne = math.degrees(abs(umax - umin))
        return info
    if typ == "torus":
        tor = s.Torus()
        ax = tor.Axis()
        info.punkt, info.achse = _v(ax.Location()), _v(ax.Direction())
        info.radius, info.radius2 = float(tor.MajorRadius()), float(tor.MinorRadius())
        from OCP.BRepLProp import BRepLProp_SLProps

        props = BRepLProp_SLProps(s, um, vm, 1, 1e-6)
        if props.IsNormalDefined():
            n = _v(props.Normal())
            if reversed_:
                n = -n
            # Mitte des Rohrquerschnitts beim Parameter um
            d = info.achse / (np.linalg.norm(info.achse) or 1.0)
            radial = p_mid - (info.punkt + d * float(np.dot(p_mid - info.punkt, d)))
            rn = np.linalg.norm(radial)
            ring = info.punkt + d * float(np.dot(p_mid - info.punkt, d)) + (radial / rn * info.radius if rn > 1e-9
                                                                              else 0)
            info.innen = bool(np.dot(n, p_mid - ring) < 0)
        return info
    return info


def kanten_von(flaeche: Flaeche) -> list[Any]:
    """Kanten einer Fläche (build123d-Edges, ohne degenerierte)."""
    return [e for e in flaeche.form.edges() if not BRep_Tool.Degenerated_s(e.wrapped)]
