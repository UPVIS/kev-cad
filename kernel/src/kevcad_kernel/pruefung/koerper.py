"""Ein Teil, wie die Prüfung es sieht: B-Rep (für exakte Rechnungen), Dreiecksnetz (für schnelle Raster) und die
Angaben aus dem Lauf (Material, nachgiebig, Verbindungselement, Achse).

Die Prüfung rechnet in Weltkoordinaten. Für den Zwischenspeicher zählt aber die Form ohne Lage (``form``) und die
Lage (``lage``, 4×4): Verschiebt sich eine ganze Baugruppe, bleiben die Ergebnisse ihrer Teilepaare gültig.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np

DIR_DIGITS = 6  # Richtungen auf 1e-6 runden (Schlüssel)


def einheit(v: Any) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise ValueError("Richtung (0, 0, 0) ist keine Richtung")
    return a / n


def richtung_schluessel(d: np.ndarray) -> tuple[int, int, int]:
    return tuple(int(round(float(x) * 10 ** DIR_DIGITS)) for x in d)  # type: ignore[return-value]


_BASIS: dict[tuple, np.ndarray] = {}


def basis(d: np.ndarray) -> np.ndarray:
    """Orthonormale Zeilen (u, v, d): u und v spannen die Bildebene senkrecht zu d auf (zwischengespeichert)."""
    x, y, z = (float(c) for c in d)
    key = (round(x, 9), round(y, 9), round(z, 9))
    R = _BASIS.get(key)
    if R is not None:
        return R
    n = (x * x + y * y + z * z) ** 0.5
    if n < 1e-12:
        raise ValueError("Richtung (0, 0, 0) ist keine Richtung")
    x, y, z = x / n, y / n, z / n
    ax, ay, az = (1.0, 0.0, 0.0) if abs(x) < 0.9 else (0.0, 1.0, 0.0)
    ux, uy, uz = y * az - z * ay, z * ax - x * az, x * ay - y * ax
    un = (ux * ux + uy * uy + uz * uz) ** 0.5
    ux, uy, uz = ux / un, uy / un, uz / un
    vx, vy, vz = y * uz - z * uy, z * ux - x * uz, x * uy - y * ux
    R = np.array([[ux, uy, uz], [vx, vy, vz], [x, y, z]])
    if len(_BASIS) > 4096:
        _BASIS.clear()
    _BASIS[key] = R
    return R


@dataclass
class Projektion:
    """Netz eines Körpers in der Basis (u, v, d): uvw je Punkt, Hüllrechteck in der Bildebene, Tiefenbereich."""

    uvw: np.ndarray
    uv_min: np.ndarray
    uv_max: np.ndarray
    w_min: float
    w_max: float


@dataclass
class Koerper:
    name: str
    key: str  # Formschlüssel des Laufs (Weltlage)
    shape: Any  # TopoDS_Shape in Weltlage
    pos: np.ndarray  # (n, 3) Netzpunkte, Welt
    tri: np.ndarray  # (m, 3) Indizes
    bmin: np.ndarray
    bmax: np.ndarray
    volumen: float = 0.0
    zentrum: np.ndarray = field(default_factory=lambda: np.zeros(3))
    masse_g: float | None = None
    info: dict[str, Any] = field(default_factory=dict)
    flaechen: list[dict[str, Any]] = field(default_factory=list)  # faces aus PART_UPSERT
    form: str = ""  # Schlüssel der Form ohne Lage
    lage: np.ndarray = field(default_factory=lambda: np.eye(4))
    _proj: dict[tuple, Projektion] = field(default_factory=dict, repr=False)
    _strahl: Any = field(default=None, repr=False)
    _solids: list[Any] | None = field(default=None, repr=False)

    # -- Angaben ----------------------------------------------------------------------------------------------------

    @property
    def nachgiebig(self) -> bool:
        return bool(self.info.get("nachgiebig"))

    @property
    def material(self) -> str | None:
        return self.info.get("material")

    @property
    def art(self) -> str | None:
        """Lagerteil-Art (schraube, mutter, scheibe, rohr …) oder None."""
        return self.info.get("art")

    @property
    def ist_verbindungselement(self) -> bool:
        return self.art in ("schraube", "mutter", "scheibe")

    @property
    def groesse(self) -> float:
        return float(np.max(self.bmax - self.bmin))

    @property
    def kurz(self) -> str:
        return self.name.rsplit("/", 1)[-1]

    # -- Raster und Strahlen ----------------------------------------------------------------------------------------

    def projektion(self, R: np.ndarray, key: tuple) -> Projektion:
        p = self._proj.get(key)
        if p is None:
            uvw = self.pos @ R.T
            if len(uvw):
                p = Projektion(uvw, uvw[:, :2].min(axis=0), uvw[:, :2].max(axis=0), float(uvw[:, 2].min()),
                               float(uvw[:, 2].max()))
            else:
                z = np.zeros(2)
                p = Projektion(uvw, z, z - 1, 0.0, -1.0)
            if len(self._proj) > 64:
                self._proj.clear()
            self._proj[key] = p
        return p

    def strahl(self, start: np.ndarray, d: np.ndarray) -> tuple[float, float] | None:
        """Exakte Schnittpunkte der Geraden start + t·d mit der Oberfläche: (kleinstes t, größtes t) oder None."""
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

        if self._strahl is None:
            it = IntCurvesFace_ShapeIntersector()
            it.Load(self.shape, 1e-6)
            self._strahl = it
        it = self._strahl
        it.Perform(gp_Lin(gp_Pnt(*map(float, start)), gp_Dir(*map(float, d))), -1e12, 1e12)
        if not it.IsDone() or it.NbPnt() == 0:
            return None
        ts = [it.WParameter(i + 1) for i in range(it.NbPnt())]
        return min(ts), max(ts)

    def innen(self, punkt: np.ndarray, tol: float = 1e-6) -> bool:
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN

        if self._solids is None:
            from OCP.TopAbs import TopAbs_SOLID
            from OCP.TopExp import TopExp_Explorer

            out = []
            ex = TopExp_Explorer(self.shape, TopAbs_SOLID)
            while ex.More():
                out.append(ex.Current())
                ex.Next()
            self._solids = out
        p = gp_Pnt(*map(float, punkt))
        for s in self._solids:
            if BRepClass3d_SolidClassifier(s, p, tol).State() == TopAbs_IN:
                return True
        return False

    def punkte_unter(self, z: float) -> np.ndarray:
        """Netzpunkte mit z ≤ z (für Bodenkontakte)."""
        if not len(self.pos):
            return np.zeros((0, 3))
        return self.pos[self.pos[:, 2] <= z]

    def zylinder_achsen(self, limit: int = 3) -> list[np.ndarray]:
        """Achsen der größten Zylinderflächen (für Einführrichtungen von Bolzen, Rohren, Bohrungen)."""
        zyl = [f for f in self.flaechen if f.get("t") == "cylinder" and f.get("ax")]
        zyl.sort(key=lambda f: -float(f.get("a") or 0.0))
        out: list[np.ndarray] = []
        for f in zyl:
            try:
                a = einheit(f["ax"])
            except ValueError:
                continue
            if any(abs(float(np.dot(a, b))) > 0.996 for b in out):
                continue
            out.append(a)
            if len(out) >= limit:
                break
        return out


# ---------------------------------------------------------------------------------------------------------------------
# Aufbau aus den Daten eines Laufs


def lage_von(shape: Any) -> np.ndarray:
    tr = shape.Location().Transformation()
    m = np.eye(4)
    for r in range(3):
        for c in range(4):
            m[r, c] = tr.Value(r + 1, c + 1)
    return m


def form_schluessel(shape: Any) -> str:
    """Hash der Form ohne Lage (BRep-Binärform mit Einheitslage). Über eine Kopie ohne Netz: Vernetzen und Boolesche
    Operationen hängen Daten an die geteilten Kanten und Flächen, die Binärform des Originals ändert sich dadurch."""
    from OCP.BinTools import BinTools, BinTools_FormatVersion
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.TopLoc import TopLoc_Location

    bare = BRepBuilderAPI_Copy(shape.Located(TopLoc_Location()), True, False).Shape()
    bio = io.BytesIO()
    BinTools.Write_s(bare, bio, False, False, BinTools_FormatVersion.BinTools_FormatVersion_CURRENT)
    return hashlib.sha1(bio.getvalue()).hexdigest()


_FORMEN: dict[str, str] = {}  # Weltschlüssel → Formschlüssel (spart das erneute Serialisieren)


def koerper_aus_topo(name: str, key: str, shape: Any, positions: np.ndarray, triangles: np.ndarray,
                     bbox: dict[str, Any], props: dict[str, Any], faces: list[dict[str, Any]] | None = None,
                     info: dict[str, Any] | None = None, density: float | None = None) -> Koerper:
    """Körper aus TopoDS_Shape (Weltlage), Netz, Hüllquader und Eigenschaften (wie im Kopf von PART_UPSERT)."""
    lage = lage_von(shape)
    # immer neu serialisieren (nicht den Weltschlüssel nehmen): die Binärform hängt auch davon ab, ob die Form schon
    # vernetzt ist, und Formen mit und ohne Lage sollen denselben Schlüssel bekommen
    form = _FORMEN.get(key) or form_schluessel(shape)
    if len(_FORMEN) > 20_000:
        _FORMEN.clear()
    _FORMEN[key] = form
    masse = props.get("mass")
    vol = float(props.get("volume") or 0.0)
    if masse is None and density:
        masse = vol * float(density) * 1e-6
    return Koerper(
        name=name, key=key, shape=shape, pos=np.asarray(positions, dtype=np.float64).reshape(-1, 3),
        tri=np.asarray(triangles, dtype=np.int64).reshape(-1, 3),
        bmin=np.asarray(bbox.get("min") or [0, 0, 0], dtype=np.float64),
        bmax=np.asarray(bbox.get("max") or [0, 0, 0], dtype=np.float64), volumen=vol,
        zentrum=np.asarray(props.get("center") or [0, 0, 0], dtype=np.float64),
        masse_g=float(masse) if masse is not None else None, info=dict(info or {}),
        flaechen=list(faces or []), form=form, lage=lage)


def koerper_aus(name: str, key: str, brep: bytes, positions: np.ndarray, triangles: np.ndarray,
                header: dict[str, Any], info: dict[str, Any] | None = None, density: float | None = None) -> Koerper:
    """Körper aus BRep-Binärform, Netz und Kopf des PART_UPSERT."""
    from kevcad_kernel.tessellate import deserialize_shape

    shape = deserialize_shape(brep).wrapped
    return koerper_aus_topo(name, key, shape, positions, triangles, header.get("bbox") or {},
                            header.get("props") or {}, header.get("faces"), info, density)


def koerper_aus_form(name: str, shape: Any, info: dict[str, Any] | None = None, deviation: float = 0.1,
                     angular: float = 0.2) -> Koerper:
    """Körper direkt aus einer build123d-Form (Tests, Animation): vernetzt selbst."""
    from kevcad_kernel.tessellate import tessellate_shape

    # wie im Rechenprozess: erst vernetzen, dann den Formschlüssel bilden (die Binärform enthält Netzdaten der Kanten)
    tess = tessellate_shape(shape, deviation, angular, cache=None)
    return koerper_aus_topo(name, tess.key, shape.wrapped, tess.geometry.positions, tess.geometry.triangles,
                            tess.bbox, tess.props, tess.geometry.faces, info)
