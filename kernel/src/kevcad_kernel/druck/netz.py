"""Dreiecksnetz und Topologie einer Form für die Druckprüfung.

Vernetzt wird eine Kopie der Form (``BRepBuilderAPI_Copy``), damit die Prüfung keine Dreiecke an der Originalform
hinterlässt, die der Viewer sonst mitbenutzen würde. Die Kopie hat dieselbe Flächenreihenfolge wie ``form.faces()``;
alle Flächennummern beziehen sich darauf.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from build123d import Compound, Shape
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.gp import gp_Pnt, gp_Vec
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape

try:  # OCP 8
    from OCP.collections import (
        IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as _EdgeFaceMap,
    )
except ImportError:  # OCP 7
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape as _EdgeFaceMap

_TYPEN = {
    GeomAbs_SurfaceType.GeomAbs_Plane: "ebene",
    GeomAbs_SurfaceType.GeomAbs_Cylinder: "zylinder",
    GeomAbs_SurfaceType.GeomAbs_Cone: "kegel",
    GeomAbs_SurfaceType.GeomAbs_Sphere: "kugel",
    GeomAbs_SurfaceType.GeomAbs_Torus: "torus",
}


@dataclass
class Zylinder:
    achse: np.ndarray      # Einheitsvektor
    punkt: np.ndarray      # Punkt auf der Achse
    radius: float
    winkel: float          # Bogen der Fläche in Grad (360 = voller Umfang)
    hohl: bool             # True: Bohrung (Fläche zeigt zur Achse), False: Stift/Rundung


@dataclass
class FlaecheInfo:
    index: int
    typ: str
    flaeche: float
    normale: np.ndarray | None = None     # nur Ebenen: Normale nach außen
    zylinder: Zylinder | None = None


class Kante:
    """Kante mit angrenzenden Flächen; Abtastpunkte werden erst bei Bedarf berechnet."""

    def __init__(self, index: int, topo, flaechen: tuple[int, ...]):
        self.index = index
        self.topo = topo
        self.flaechen = flaechen
        self._kurve = BRepAdaptor_Curve(topo)
        self.gerade = self._kurve.GetType() == GeomAbs_CurveType.GeomAbs_Line
        self._laenge: float | None = None
        self._abtastung: dict[float, tuple[np.ndarray, np.ndarray]] = {}

    @property
    def laenge(self) -> float:
        if self._laenge is None:
            self._laenge = float(GCPnts_AbscissaPoint.Length_s(self._kurve))
        return self._laenge

    def abtasten(self, schritt: float = 1.0, max_punkte: int = 200) -> tuple[np.ndarray, np.ndarray]:
        """Punkte (k×3) und Einheitstangenten (k×3) im Abstand von etwa ``schritt``, ohne die Endpunkte."""
        if schritt not in self._abtastung:
            c = self._kurve
            u0, u1 = c.FirstParameter(), c.LastParameter()
            n = int(min(max(round(self.laenge / schritt), 3), max_punkte))
            pts, tans = np.empty((n, 3)), np.empty((n, 3))
            p, v = gp_Pnt(), gp_Vec()
            for i in range(n):
                c.D1(u0 + (u1 - u0) * (i + 0.5) / n, p, v)
                pts[i] = p.Coord()
                tans[i] = v.Coord()
            tans /= np.maximum(np.linalg.norm(tans, axis=1), 1e-12)[:, None]
            self._abtastung[schritt] = (pts, tans)
        return self._abtastung[schritt]


@dataclass
class Netz:
    form: Shape
    kopie: object                    # TopoDS_Shape (vernetzt)
    V: np.ndarray                    # Knoten (n×3)
    T: np.ndarray                    # Dreiecke (m×3)
    tri_face: np.ndarray             # Fläche je Dreieck
    tri_n: np.ndarray                # Einheitsnormale je Dreieck (nach außen)
    tri_a: np.ndarray                # Dreiecksfläche
    tri_c: np.ndarray                # Schwerpunkt
    infos: list[FlaecheInfo]
    kanten: list[Kante]
    nachbarn: list[set[int]]
    diag: float
    solids: list = field(default_factory=list)
    _klass: list = field(default_factory=list)

    @property
    def flaechenzahl(self) -> int:
        return len(self.infos)

    def tri_ecken(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self.V[self.T[:, 0]], self.V[self.T[:, 1]], self.V[self.T[:, 2]]

    def innen(self, punkte: np.ndarray, tol: float = 1e-4) -> np.ndarray:
        """Liegen die Punkte im Material? (OCCT-Klassifikation, für wenige Punkte gedacht)."""
        if not self._klass:
            self._klass = [BRepClass3d_SolidClassifier(s) for s in self.solids]
        out = np.zeros(len(punkte), dtype=bool)
        for i, p in enumerate(np.asarray(punkte, dtype=float)):
            gp = gp_Pnt(*p)
            for k in self._klass:
                k.Perform(gp, tol)
                if k.State() == TopAbs_IN:
                    out[i] = True
                    break
        return out


def als_shape(form) -> Shape:
    """build123d-Form, Builder (``bp.part``) oder TopoDS_Shape → build123d ``Shape``."""
    if form is None:
        raise ValueError("Keine Form übergeben")
    if not isinstance(form, Shape):
        if isinstance(getattr(form, "part", None), Shape):  # BuildPart
            form = form.part
        elif isinstance(form, TopoDS_Shape):
            form = Shape.cast(form)
        elif isinstance(form, (list, tuple)):
            form = Compound(children=[als_shape(f) for f in form])
    if not isinstance(form, Shape):
        raise TypeError(f"Keine build123d-Form: {type(form).__name__}")
    return form


def _ablenkung(diag: float) -> tuple[float, float]:
    return min(max(diag / 1000.0, 0.01), 0.1), 0.3


def baue_netz(form) -> Netz:
    shape = als_shape(form)
    faces = shape.faces()
    if not faces:
        raise ValueError("Die Form hat keine Flächen (kein Volumenkörper)")
    bb = shape.bounding_box()
    diag = float(math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2)) or 1.0

    kopie = BRepBuilderAPI_Copy(shape.wrapped, True, False).Shape()
    kopie_shape = Shape.cast(kopie)
    kfaces = kopie_shape.faces()
    if len(kfaces) != len(faces):  # sollte nie passieren
        raise RuntimeError("Kopie der Form hat eine andere Flächenzahl")
    lin, ang = _ablenkung(diag)
    BRepMesh_IncrementalMesh(kopie, lin, False, ang, True)

    pos: list[np.ndarray] = []
    tris: list[np.ndarray] = []
    tf: list[np.ndarray] = []
    infos: list[FlaecheInfo] = []
    offset = 0
    loc = TopLoc_Location()
    for i, (f, kf) in enumerate(zip(faces, kfaces)):
        topo = TopoDS.Face(kf.wrapped)
        poly = BRep_Tool.Triangulation_s(topo, loc)
        if poly is not None and poly.NbTriangles() > 0:
            trsf = loc.Transformation()
            P = np.array([poly.Node(j).Transformed(trsf).Coord() for j in range(1, poly.NbNodes() + 1)], dtype=float)
            Tr = np.array([poly.Triangle(j).Get() for j in range(1, poly.NbTriangles() + 1)], dtype=np.int64) - 1
            if topo.Orientation() == TopAbs_REVERSED:
                Tr = Tr[:, [0, 2, 1]]
            pos.append(P)
            tris.append(Tr + offset)
            tf.append(np.full(len(Tr), i, dtype=np.int64))
            offset += len(P)
        infos.append(_flaeche_info(i, f))

    V = np.concatenate(pos) if pos else np.zeros((0, 3))
    T = np.concatenate(tris) if tris else np.zeros((0, 3), dtype=np.int64)
    tri_face = np.concatenate(tf) if tf else np.zeros(0, dtype=np.int64)
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    cr = np.cross(b - a, c - a)
    nrm = np.linalg.norm(cr, axis=1)
    ok = nrm > 1e-12
    V_, T, tri_face, cr, nrm = V, T[ok], tri_face[ok], cr[ok], nrm[ok]
    tri_n = cr / nrm[:, None]
    tri_a = nrm / 2
    tri_c = (V_[T[:, 0]] + V_[T[:, 1]] + V_[T[:, 2]]) / 3

    kanten, nachbarn = _kanten(kopie, kfaces)
    solids = []
    exp = TopExp_Explorer(kopie, TopAbs_SOLID)
    while exp.More():
        solids.append(TopoDS.Solid(exp.Current()))
        exp.Next()
    return Netz(shape, kopie, V_, T, tri_face, tri_n, tri_a, tri_c, infos, kanten, nachbarn, diag, solids)


def _flaeche_info(i: int, f) -> FlaecheInfo:
    s = BRepAdaptor_Surface(f.wrapped)
    typ = _TYPEN.get(s.GetType(), "frei")
    info = FlaecheInfo(i, typ, float(f.area))
    try:
        if typ == "ebene":
            n = f.normal_at(f.center())
            info.normale = np.array([n.X, n.Y, n.Z], dtype=float)
        elif typ == "zylinder":
            cyl = s.Cylinder()
            ax = cyl.Axis()
            d = np.array(ax.Direction().Coord(), dtype=float)
            p0 = np.array(ax.Location().Coord(), dtype=float)
            u0, u1, v0, v1 = BRepTools.UVBounds_s(f.wrapped)
            pt = f.position_at(0.5, 0.5)
            nv = f.normal_at(pt)
            q = np.array([pt.X, pt.Y, pt.Z]) - p0
            radial = q - d * float(q @ d)
            hohl = float(np.array([nv.X, nv.Y, nv.Z]) @ radial) < 0
            info.zylinder = Zylinder(d, p0, float(cyl.Radius()), math.degrees(u1 - u0), hohl)
    except Exception:  # noqa: BLE001 - Zusatzwissen; ohne bleibt die Fläche "frei"
        pass
    return info


def _kanten(kopie, kfaces) -> tuple[list[Kante], list[set[int]]]:
    index = {hash(f.wrapped): i for i, f in enumerate(kfaces)}
    m = _EdgeFaceMap()
    TopExp.MapShapesAndAncestors_s(kopie, TopAbs_EDGE, TopAbs_FACE, m)
    nachbarn: list[set[int]] = [set() for _ in kfaces]
    kanten: list[Kante] = []
    for k in range(1, m.Extent() + 1):
        e = TopoDS.Edge(m.FindKey(k))
        if BRep_Tool.Degenerated_s(e):
            continue
        lst = m.FindFromIndex(k)
        # Iterieren über die OCP-Liste ist sehr langsam (ms je Kante); First/Last genügt für zwei Flächen
        roh = [lst.First(), lst.Last()] if lst.Size() <= 2 else list(lst)
        fl = tuple(sorted({index[hash(f)] for f in roh if hash(f) in index})) if lst.Size() else ()
        for a in fl:
            for b in fl:
                if a != b:
                    nachbarn[a].add(b)
        kanten.append(Kante(len(kanten), e, fl))
    return kanten, nachbarn
