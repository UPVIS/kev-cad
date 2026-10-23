"""Tessellierung: build123d-Form → ``protocol.PartGeometry`` samt Flächen- und Kantenwerten (PROTOCOL.md).

- Dreiecke je Fläche kommen von ocp-tessellate (ohne dessen eigenen Zwischenspeicher), Kantenzüge rechnen wir
  selbst, damit ihre Reihenfolge exakt ``part.edges()`` entspricht (degenerierte Kanten fehlen dort, sie werden
  übersprungen; Kanten ohne Fläche oder ohne Polygon bekommen einen Ersatz-Polygonzug, damit nichts verrutscht).
- Flächenreihenfolge = ``part.faces()``, Kantenreihenfolge = ``part.edges()``, Punkte = ``part.vertices()``. Für
  Drähte (``Wire``) gilt die Reihenfolge der Basisklasse ``Shape`` (Erkundungsreihenfolge, nicht Verbindungsreihenfolge);
  die Funktionen ``faces_of``/``edges_of``/``vertices_of`` sind deshalb die einzige Quelle der Nummerierung.
- Genauigkeit relativ zur Teilgröße (``compute_quality`` wie im AP0-Test).
- Zwischenspeicher über einen Formschlüssel (SHA-1 der BRep-Binärform ohne Dreiecke plus Genauigkeit): eine beim
  Neu-Rechnen unveränderte Form wird nicht neu tesselliert.
"""

from __future__ import annotations

import hashlib
import io
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import numpy as np
from build123d import Shape, ShapeList
from OCP.BinTools import BinTools, BinTools_FormatVersion
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepTools import BRepTools
from OCP.GCPnts import GCPnts_AbscissaPoint, GCPnts_TangentialDeflection
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.gp import gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape
from ocp_tessellate.tessellator import compute_quality
from ocp_tessellate.tessellator import tessellate as _ocp_tessellate

from kevcad_kernel.protocol import PartGeometry

try:  # OCP 8: Sammlungsklassen liegen in OCP.collections
    from OCP.collections import (
        IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedDataMapOfShapeListOfShape,
    )
except ImportError:  # OCP 7
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

# Ohne den Zwischenspeicher von ocp-tessellate (wir halten selbst einen, sonst läge alles doppelt im Speicher)
_tessellate_raw = getattr(_ocp_tessellate, "__wrapped__", _ocp_tessellate)

DEFAULT_DEVIATION = 0.1
DEFAULT_ANGULAR = 0.2

_SURFACE_TYPES = {
    GeomAbs_SurfaceType.GeomAbs_Plane: "plane",
    GeomAbs_SurfaceType.GeomAbs_Cylinder: "cylinder",
    GeomAbs_SurfaceType.GeomAbs_Cone: "cone",
    GeomAbs_SurfaceType.GeomAbs_Sphere: "sphere",
    GeomAbs_SurfaceType.GeomAbs_Torus: "torus",
    GeomAbs_SurfaceType.GeomAbs_BSplineSurface: "bspline",
    GeomAbs_SurfaceType.GeomAbs_BezierSurface: "bspline",
}

_CURVE_TYPES = {
    GeomAbs_CurveType.GeomAbs_Line: "line",
    GeomAbs_CurveType.GeomAbs_Circle: "circle",
    GeomAbs_CurveType.GeomAbs_Ellipse: "ellipse",
    GeomAbs_CurveType.GeomAbs_BSplineCurve: "bspline",
    GeomAbs_CurveType.GeomAbs_BezierCurve: "bspline",
}

_R = 6  # Nachkommastellen in den Metadaten


def _r(x: float) -> float:
    v = round(float(x), _R)
    return 0.0 if v == 0 else v  # kein -0.0 im JSON


def _p3(p) -> list[float]:
    """gp_Pnt, gp_Dir, gp_Vec oder build123d-Vektor → [x, y, z]."""
    return [_r(p.X()), _r(p.Y()), _r(p.Z())] if callable(getattr(p, "X", None)) else [_r(p.X), _r(p.Y), _r(p.Z)]


# ---------------------------------------------------------------------------------------------------------------------
# Nummerierung (einzige Quelle für Referenzen #f/#e/#v)
# ---------------------------------------------------------------------------------------------------------------------


def faces_of(shape: Shape) -> ShapeList:
    """Flächen in der Reihenfolge von ``part.faces()``."""
    return Shape.get_shape_list(shape, "Face")


def edges_of(shape: Shape) -> ShapeList:
    """Kanten in der Reihenfolge von ``part.edges()`` (ohne degenerierte Kanten)."""
    return Shape.get_shape_list(shape, "Edge").filter_by(lambda e: BRep_Tool.Degenerated_s(e.wrapped), reverse=True)


def vertices_of(shape: Shape) -> ShapeList:
    """Punkte in der Reihenfolge von ``part.vertices()``."""
    return Shape.get_shape_list(shape, "Vertex")


# ---------------------------------------------------------------------------------------------------------------------
# BRep-Binärform (Formschlüssel und Übergabe an den Elternprozess)
# ---------------------------------------------------------------------------------------------------------------------


def serialize_shape(topods: TopoDS_Shape) -> bytes:
    """BRep-Binärform ohne Dreiecke und Normalen (deterministisch für gleiche Geometrie)."""
    bio = io.BytesIO()
    BinTools.Write_s(topods, bio, False, False, BinTools_FormatVersion.BinTools_FormatVersion_CURRENT)
    return bio.getvalue()


def deserialize_shape(data: bytes) -> Shape:
    shape = TopoDS_Shape()
    BinTools.Read_s(shape, io.BytesIO(data))
    return Shape.cast(shape)


def shape_key(brep: bytes, deviation: float, angular: float) -> str:
    return f"{hashlib.sha1(brep).hexdigest()}:{deviation:g}:{angular:g}"


# ---------------------------------------------------------------------------------------------------------------------
# Metadaten je Fläche und Kante
# ---------------------------------------------------------------------------------------------------------------------


def face_info(face: Shape) -> dict[str, Any]:
    """Typ, Flächeninhalt und je nach Typ Normale, Punkt/Mittelpunkt, Achse, Radius (siehe PROTOCOL.md)."""
    f = TopoDS.Face(face.wrapped)
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, props)
    centroid = props.CentreOfMass()
    adaptor = BRepAdaptor_Surface(f)
    stype = adaptor.GetType()
    d: dict[str, Any] = {"t": _SURFACE_TYPES.get(stype, "other"), "a": _r(props.Mass())}
    if stype == GeomAbs_SurfaceType.GeomAbs_Plane:
        d["n"] = face_normal(f)
        d["c"] = _p3(centroid)
    elif stype == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        cyl = adaptor.Cylinder()
        ax = cyl.Axis()
        d["r"] = _r(cyl.Radius())
        d["ax"] = _p3(ax.Direction())
        d["c"] = _p3(_project_on_axis(centroid, ax))
    elif stype == GeomAbs_SurfaceType.GeomAbs_Cone:
        cone = adaptor.Cone()
        d["ax"] = _p3(cone.Axis().Direction())
        d["c"] = _p3(cone.Apex())
        d["r"] = _r(cone.RefRadius())
        d["ang"] = _r(math.degrees(cone.SemiAngle()))
    elif stype == GeomAbs_SurfaceType.GeomAbs_Sphere:
        sph = adaptor.Sphere()
        d["c"] = _p3(sph.Location())
        d["r"] = _r(sph.Radius())
    elif stype == GeomAbs_SurfaceType.GeomAbs_Torus:
        tor = adaptor.Torus()
        d["c"] = _p3(tor.Location())
        d["ax"] = _p3(tor.Axis().Direction())
        d["r"] = _r(tor.MajorRadius())
        d["r2"] = _r(tor.MinorRadius())
    return d


def face_normal(f) -> list[float]:
    """Normale in der Mitte des Parameterbereichs, Flächenorientierung berücksichtigt."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    p, n = gp_Pnt(), gp_Vec()
    BRepGProp_Face(f).Normal((u0 + u1) / 2, (v0 + v1) / 2, p, n)
    m = n.Magnitude()
    if m > 0:
        n.Divide(m)
    return [_r(n.X()), _r(n.Y()), _r(n.Z())]


def _project_on_axis(p: gp_Pnt, ax) -> gp_Pnt:
    o, d = ax.Location(), ax.Direction()
    t = (p.X() - o.X()) * d.X() + (p.Y() - o.Y()) * d.Y() + (p.Z() - o.Z()) * d.Z()
    return gp_Pnt(o.X() + t * d.X(), o.Y() + t * d.Y(), o.Z() + t * d.Z())


def edge_info(edge: Shape) -> dict[str, Any]:
    """Typ und Länge, bei Kreisen Radius, Mittelpunkt und Achse."""
    adaptor = BRepAdaptor_Curve(TopoDS.Edge(edge.wrapped))
    ctype = adaptor.GetType()
    d: dict[str, Any] = {"t": _CURVE_TYPES.get(ctype, "other"), "l": _r(GCPnts_AbscissaPoint.Length_s(adaptor))}
    if ctype == GeomAbs_CurveType.GeomAbs_Circle:
        circ = adaptor.Circle()
        d["r"] = _r(circ.Radius())
        d["c"] = _p3(circ.Location())
        d["ax"] = _p3(circ.Axis().Direction())
    elif ctype == GeomAbs_CurveType.GeomAbs_Ellipse:
        el = adaptor.Ellipse()
        d["r"] = _r(el.MajorRadius())
        d["r2"] = _r(el.MinorRadius())
        d["c"] = _p3(el.Location())
        d["ax"] = _p3(el.Axis().Direction())
    return d


# ---------------------------------------------------------------------------------------------------------------------
# Kantenzüge
# ---------------------------------------------------------------------------------------------------------------------


def _edge_polyline(edge_topo, edge_faces: TopTools_IndexedDataMapOfShapeListOfShape, deflection: float,
                   angular: float) -> list[tuple[float, float, float]]:
    """Polygonzug einer Kante: bevorzugt das Polygon auf der Dreiecksvernetzung der ersten Nachbarfläche (liegt exakt
    auf dem Netzrand), sonst das 3D-Polygon, sonst eine eigene Abtastung."""
    if edge_faces.Contains(edge_topo):
        faces = edge_faces.FindFromKey(edge_topo)
        if faces.Size() > 0:
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(TopoDS.Face(faces.First()), loc)
            if tri is not None:
                poly = BRep_Tool.PolygonOnTriangulation_s(edge_topo, tri, loc)
                if poly is not None and poly.NbNodes() >= 2:
                    trsf = loc.Transformation()
                    node = poly.Node
                    return [tri.Node(node(j)).Transformed(trsf).Coord() for j in range(1, poly.NbNodes() + 1)]
    loc = TopLoc_Location()
    p3d = BRep_Tool.Polygon3D_s(edge_topo, loc)
    if p3d is not None and p3d.NbNodes() >= 2:
        trsf = loc.Transformation()
        nodes = p3d.Nodes()
        return [nodes.Value(i).Transformed(trsf).Coord() for i in range(nodes.Lower(), nodes.Upper() + 1)]
    try:
        adaptor = BRepAdaptor_Curve(edge_topo)
        disc = GCPnts_TangentialDeflection(adaptor, angular, max(deflection, 1e-4), 2)
        if disc.NbPoints() >= 2:
            return [disc.Value(i).Coord() for i in range(1, disc.NbPoints() + 1)]
        p0 = adaptor.Value(adaptor.FirstParameter()).Coord()
        p1 = adaptor.Value(adaptor.LastParameter()).Coord()
        return [p0, p1]
    except Exception:  # noqa: BLE001 - lieber ein leerer Zug als ein verrutschter Index
        return []


# ---------------------------------------------------------------------------------------------------------------------
# Tessellierung mit Zwischenspeicher
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Tessellation:
    geometry: PartGeometry
    bbox: dict[str, list[float]]  # {"min", "max"}
    props: dict[str, Any]  # {"volume", "area", "center"}
    key: str
    tess_ms: float = 0.0
    cached: bool = False

    def nbytes(self) -> int:
        g = self.geometry
        arrays = (g.positions, g.normals, g.triangles, g.tri_face, g.edge_points, g.edge_offsets, g.vertices)
        return int(sum(a.nbytes for a in arrays)) + 120 * (len(g.faces) + len(g.edges)) + 512


class TessCache:
    """LRU-Zwischenspeicher Formschlüssel → Tessellation, begrenzt über die Größe der Arrays.

    Zweiter Schlüssel ist ein Geometrie-Fingerabdruck (``geometry_fingerprint``): Manche booleschen Operationen
    liefern bei gleichem Code Formen, deren BRep sich nur in Toleranzwerten unterscheidet; die werden darüber trotzdem
    wiedererkannt.
    """

    def __init__(self, max_bytes: int = 512 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[str, Tessellation] = OrderedDict()
        self._sizes: dict[str, int] = {}
        self._by_fp: dict[str, str] = {}  # Fingerabdruck -> Schlüssel
        self._fp_of: dict[str, str] = {}  # Schlüssel -> Fingerabdruck
        self._alias: dict[str, str] = {}  # weiterer BRep-Schlüssel -> Schlüssel
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Tessellation | None:
        with self._lock:
            item = self._items.get(self._alias.get(key, key))
            if item is None:
                return None
            self._items.move_to_end(item.key)
            self.hits += 1
            return item

    def get_fingerprint(self, fp: str, alias: str | None = None) -> Tessellation | None:
        with self._lock:
            key = self._by_fp.get(fp)
            item = self._items.get(key) if key else None
            if item is None:
                self.misses += 1
                return None
            self._items.move_to_end(key)
            if alias and alias != key:
                self._alias[alias] = key
            self.hits += 1
            return item

    def put(self, item: Tessellation, fp: str | None = None) -> None:
        with self._lock:
            key = item.key
            if key in self._items:
                return
            size = item.nbytes()
            self._items[key] = item
            self._sizes[key] = size
            self._bytes += size
            if fp:
                self._by_fp[fp] = key
                self._fp_of[key] = fp
            while self._bytes > self.max_bytes and len(self._items) > 1:
                old_key, _ = self._items.popitem(last=False)
                self._bytes -= self._sizes.pop(old_key, 0)
                old_fp = self._fp_of.pop(old_key, None)
                if old_fp and self._by_fp.get(old_fp) == old_key:
                    del self._by_fp[old_fp]
                for a in [a for a, k in self._alias.items() if k == old_key]:
                    del self._alias[a]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._sizes.clear()
            self._by_fp.clear()
            self._fp_of.clear()
            self._alias.clear()
            self._bytes = 0

    def __len__(self) -> int:
        return len(self._items)


CACHE = TessCache()


def geometry_fingerprint(vertices: list[tuple[float, float, float]], faces: list[dict[str, Any]],
                         edges: list[dict[str, Any]], deviation: float, angular: float) -> str:
    """Fingerabdruck aus Anzahl und Reihenfolge der Punkte, Flächen und Kanten samt Lage, Typ, Inhalt und Länge
    (gerundet). Gleicher Fingerabdruck heißt: gleiche Nummerierung und gleiche Geometrie bis auf Rundung."""
    parts = [f"{len(faces)}:{len(edges)}:{len(vertices)}:{deviation:g}:{angular:g}"]
    parts += [f"{round(x, 4) + 0.0},{round(y, 4) + 0.0},{round(z, 4) + 0.0}" for x, y, z in vertices]
    parts += [f"{f['t']}:{round(f['a'], 3) + 0.0}" for f in faces]
    parts += [f"{e['t']}:{round(e['l'], 4) + 0.0}" for e in edges]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def mesh_quality(xsize: float, ysize: float, zsize: float, deviation: float = DEFAULT_DEVIATION) -> float:
    """Lineare Abweichung der Vernetzung relativ zur Teilgröße (wie ``compute_quality`` aus ocp-tessellate, aber
    auch für flache Teile, bei denen eine Kantenlänge 0 ist)."""
    sizes = [s if s > 1e-9 else 0.0 for s in (xsize, ysize, zsize)]
    if not any(sizes):
        return max(deviation * 0.01, 1e-3)
    if all(sizes):
        q = compute_quality(SimpleNamespace(xsize=sizes[0], ysize=sizes[1], zsize=sizes[2]), deviation)
    else:
        q = sum(sizes) / 300 * deviation
    return q if q > 0 else max(deviation * 0.01, 1e-3)


def _empty(n: int, cols: int, dtype) -> np.ndarray:
    return np.zeros((n, cols), dtype=dtype) if cols > 1 else np.zeros((n,), dtype=dtype)


def _has(shape: TopoDS_Shape, kind) -> bool:
    return TopExp_Explorer(shape, kind).More()


def shape_props(shape: Shape, bbox_center: list[float]) -> dict[str, Any]:
    """Volumen, Oberfläche und Schwerpunkt (Volumen, sonst Fläche, sonst Kantenlänge, sonst Hüllquadermitte)."""
    topo = shape.wrapped
    volume = 0.0
    center = None
    if _has(topo, TopAbs_SOLID):
        vp = GProp_GProps()
        BRepGProp.VolumeProperties_s(topo, vp)
        volume = vp.Mass()
        if volume > 0:
            center = vp.CentreOfMass()
    sp = GProp_GProps()
    BRepGProp.SurfaceProperties_s(topo, sp)
    area = sp.Mass()
    if center is None and area > 0:
        center = sp.CentreOfMass()
    if center is None and _has(topo, TopAbs_EDGE):
        lp = GProp_GProps()
        BRepGProp.LinearProperties_s(topo, lp)
        if lp.Mass() > 0:
            center = lp.CentreOfMass()
    return {
        "volume": _r(volume),
        "area": _r(area),
        "center": _p3(center) if center is not None else [_r(c) for c in bbox_center],
    }


NETZ_MIN_FLAECHEN = 300
NETZ_SCHARF_GRAD = 30.0


def _ist_netzkoerper(face_meta: list[dict[str, Any]], kanten: int) -> bool:
    """Körper aus einem Dreiecksnetz (etwa das Ergebnis der Topologieoptimierung, ``BRepBuilderAPI_MakeShapeOnMesh``):
    viele ebene Flächen und anderthalb Kanten je Fläche wie bei einem geschlossenen Dreiecksnetz."""
    n = len(face_meta)
    if n < NETZ_MIN_FLAECHEN:
        return False
    eben = sum(1 for f in face_meta if f.get("t") == "plane")
    return eben >= 0.95 * n and abs(kanten - 1.5 * n) <= 0.12 * n


def _scharf(edge_topo: Any, edge_faces: Any) -> bool:
    """Kante zwischen zwei ebenen Flächen mit mehr als ``NETZ_SCHARF_GRAD`` Knick (oder nicht zwischen zwei ebenen)."""
    if not edge_faces.Contains(edge_topo):
        return True
    fl = edge_faces.FindFromKey(edge_topo)
    if fl.Size() != 2:
        return True
    ns = []
    for f in (fl.First(), fl.Last()):
        face = TopoDS.Face(f)
        a = BRepAdaptor_Surface(face)
        if a.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
            return True
        n = face_normal(face)
        ns.append(n)
    c = sum(x * y for x, y in zip(ns[0], ns[1]))
    return c < math.cos(math.radians(NETZ_SCHARF_GRAD))


def _weiche_normalen(positions: np.ndarray, triangles: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """Normalen je Punkt über alle Dreiecke am selben Ort gemittelt (nach Fläche gewichtet); weicht die Mittelung mehr
    als 40° von der eigenen Flächennormale ab (Knick), bleibt die eigene."""
    if len(triangles) == 0:
        return normals
    P = positions.astype(np.float64)
    a, b, c = P[triangles[:, 0]], P[triangles[:, 1]], P[triangles[:, 2]]
    fn = np.cross(b - a, c - a)  # Länge = doppelte Fläche
    ort = np.round(P / 1e-4).astype(np.int64)
    _, gruppe = np.unique(ort, axis=0, return_inverse=True)
    gruppe = gruppe.reshape(-1)
    summe = np.zeros((int(gruppe.max()) + 1, 3))
    for k in range(3):
        np.add.at(summe, gruppe[triangles[:, k]], fn)
    weich = summe[gruppe]
    weich /= np.maximum(np.linalg.norm(weich, axis=1, keepdims=True), 1e-300)
    eigen = normals.astype(np.float64)
    eigen /= np.maximum(np.linalg.norm(eigen, axis=1, keepdims=True), 1e-300)
    gut = np.einsum("ij,ij->i", weich, eigen) > math.cos(math.radians(40.0))
    out = np.where(gut[:, None], weich, eigen)
    return out.astype(np.float32)


def tessellate_shape(
    shape: Shape,
    deviation: float = DEFAULT_DEVIATION,
    angular: float = DEFAULT_ANGULAR,
    brep: bytes | None = None,
    cache: TessCache | None = CACHE,
) -> Tessellation:
    """build123d-Form → Tessellation. ``brep`` (aus ``serialize_shape``) spart das erneute Serialisieren."""
    if brep is None:
        brep = serialize_shape(shape.wrapped)
    key = shape_key(brep, deviation, angular)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return Tessellation(hit.geometry, hit.bbox, hit.props, hit.key, 0.0, True)

    t0 = time.perf_counter()
    topo = shape.wrapped
    faces = faces_of(shape)
    edges = edges_of(shape)
    vertex_list = [(v.X, v.Y, v.Z) for v in vertices_of(shape)]
    face_meta = [face_info(f) for f in faces]
    edge_meta = [edge_info(e) for e in edges]
    fp = geometry_fingerprint(vertex_list, face_meta, edge_meta, deviation, angular)
    if cache is not None:
        hit = cache.get_fingerprint(fp, alias=key)
        if hit is not None:
            # Schlüssel des gespeicherten Eintrags zurückgeben: für den Elternprozess bleibt das Teil "unverändert"
            return Tessellation(hit.geometry, hit.bbox, hit.props, hit.key, (time.perf_counter() - t0) * 1000, True)

    bb = shape.bounding_box()
    bbox = {"min": _p3(bb.min), "max": _p3(bb.max)}

    # Dreiecke (ocp-tessellate vernetzt mit BRepMesh und liest die Dreiecke je Fläche aus)
    quality = mesh_quality(bb.size.X, bb.size.Y, bb.size.Z, deviation)
    if faces:
        t = _tessellate_raw(topo, key, deviation=deviation, quality=quality, angular_tolerance=angular,
                            compute_faces=True, compute_edges=False)
        positions = np.asarray(t["vertices"], dtype=np.float32).reshape(-1, 3)
        normals = np.asarray(t["normals"], dtype=np.float32).reshape(-1, 3)
        triangles = np.asarray(t["triangles"], dtype=np.uint32).reshape(-1, 3)
        tpf = np.asarray(t["triangles_per_face"], dtype=np.int64)
        if len(tpf) == len(faces):
            face_ids = np.arange(len(faces), dtype=np.int32)
        else:
            # ocp-tessellate überspringt Flächen ohne Vernetzung; Index trotzdem auf part.faces() abbilden
            loc = TopLoc_Location()
            face_ids = np.asarray(
                [i for i, f in enumerate(faces) if BRep_Tool.Triangulation_s(TopoDS.Face(f.wrapped), loc)
                 is not None], dtype=np.int32)
            if len(face_ids) != len(tpf):  # sollte nie passieren
                raise RuntimeError(f"Flächenzuordnung passt nicht: {len(tpf)} Dreiecksgruppen, {len(face_ids)} Flächen")
        tri_face = np.repeat(face_ids, tpf).astype(np.int32)
    else:
        positions, normals = _empty(0, 3, np.float32), _empty(0, 3, np.float32)
        triangles, tri_face = _empty(0, 3, np.uint32), _empty(0, 1, np.int32)

    # Kantenzüge in der Reihenfolge von part.edges()
    edge_faces = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(topo, TopAbs_EDGE, TopAbs_FACE, edge_faces)
    netz = _ist_netzkoerper(face_meta, len(edges))
    if netz:  # Netzkörper (Topologie): weich schattieren, nur scharfe Kanten zeichnen
        normals = _weiche_normalen(positions, triangles, normals)
    pts: list[tuple[float, float, float]] = []
    offsets = [0]
    for e in edges:
        if not netz or _scharf(e.wrapped, edge_faces):
            pts.extend(_edge_polyline(e.wrapped, edge_faces, quality, angular))
        offsets.append(len(pts))

    geometry = PartGeometry(
        positions=positions,
        normals=normals,
        triangles=triangles,
        tri_face=tri_face,
        edge_points=np.asarray(pts, dtype=np.float32).reshape(-1, 3),
        edge_offsets=np.asarray(offsets, dtype=np.uint32),
        vertices=np.asarray(vertex_list, dtype=np.float32).reshape(-1, 3),
        faces=face_meta,
        edges=edge_meta,
    )
    center = [(a + b) / 2 for a, b in zip(bbox["min"], bbox["max"])]
    props = shape_props(shape, center)
    result = Tessellation(geometry, bbox, props, key, (time.perf_counter() - t0) * 1000, False)
    if cache is not None:
        cache.put(result, fp)
    return result
