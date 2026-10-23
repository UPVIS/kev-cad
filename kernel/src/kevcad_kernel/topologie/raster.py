"""Voxelgitter des Bauraums in Drucklage: Rahmen, innen/außen, Abstandsfeld, nächste Fläche, Bohrungen.

- **Druckrahmen** ``R`` (3×3, Zeilen): Welt → Druck, die dritte Zeile ist die Aufbaurichtung (Schichtnormale aus der
  Druckprüfung), x und y folgen der Weltachse, die am wenigsten mit ihr zu tun hat. Das Gitter beginnt auf dem Bett
  (unterste Fläche des Teils), Schicht k liegt auf Schicht k − 1.
- **Innen/außen** über Strahlen in Aufbaurichtung (Parität der Schnitte mit dem Dreiecksnetz des Teils), je Spalte des
  Gitters; die Strahlen sind um Bruchteile eines Voxels versetzt, damit sie keine Kante und keinen Eckpunkt treffen.
- **Abstandsfeld** (mit Vorzeichen, innen negativ) nur in einem schmalen Band um die Oberfläche genau (Punkt ↔
  Dreieck), außerhalb abgeschnitten: Marching Cubes braucht nur die Nähe der Fläche.
- **Nächstes Dreieck** mit B-Rep-Fläche: Lastflächen wie im Festkörper auf derselben Fläche wie der nächste Punkt.
- **Bohrungen**: zylindrische Innenflächen (die Wand liegt außen) mit zusammen mindestens 300° Umfang, je Achse und
  Radius zusammengefasst; Rundungen (Viertelzylinder) zählen nicht.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

VERSATZ = (0.000123, 0.000271)  # Strahlversatz in Voxeln (keine Kante, kein Eckpunkt treffen)


def druckrahmen(oben: Any | None) -> np.ndarray:
    """Zeilen (x, y, z) des Druckrahmens in Weltkoordinaten; z = Aufbaurichtung (``oben``), sonst Welt-z."""
    z = np.array([0.0, 0.0, 1.0]) if oben is None else np.asarray(oben, float)
    z = z / float(np.linalg.norm(z))
    achsen = np.eye(3)
    x = achsen[int(np.argmin(np.abs(achsen @ z)))]
    x = x - z * float(x @ z)
    x /= float(np.linalg.norm(x))
    y = np.cross(z, x)
    return np.stack([x, y, z])


# -- Dreiecksnetz eines B-Rep mit Flächennummern ----------------------------------------------------------------------


def brep_netz(shape: Any, ablenkung: float = 0.05, winkel: float = 0.25) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Punkte (n, 3), Dreiecke (m, 3, nach außen orientiert) und B-Rep-Fläche je Dreieck (Reihenfolge von TopExp)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, float(ablenkung), False, float(winkel), True)
    pos, tri, fl = [], [], []
    n0 = 0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    i = 0
    while ex.More():
        f = TopoDS.Face_s(ex.Current()) if hasattr(TopoDS, "Face_s") else TopoDS.Face(ex.Current())
        loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is not None:
            trsf = loc.Transformation()
            p = np.array([(lambda q: (q.X(), q.Y(), q.Z()))(t.Node(k).Transformed(trsf)) for k in
                          range(1, t.NbNodes() + 1)], dtype=np.float64)
            d = np.array([t.Triangle(k).Get() for k in range(1, t.NbTriangles() + 1)], dtype=np.int64) - 1
            if f.Orientation() == TopAbs_REVERSED:
                d = d[:, [0, 2, 1]]
            pos.append(p)
            tri.append(d + n0)
            fl.append(np.full(len(d), i, dtype=np.int64))
            n0 += len(p)
        i += 1
        ex.Next()
    if not pos:
        raise ValueError("Das Teil ließ sich nicht vernetzen")
    return np.concatenate(pos), np.concatenate(tri), np.concatenate(fl)


# -- innen/außen über Strahlen ---------------------------------------------------------------------------------------


def _schnitte(P: np.ndarray, T: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Schnitte der senkrechten Strahlen (xs[i], ys[j]) mit den Dreiecken: Spalte (i * ny + j) und z, sortiert."""
    nx, ny = len(xs), len(ys)
    A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)
    dx = xs[1] - xs[0] if nx > 1 else 1.0
    dy = ys[1] - ys[0] if ny > 1 else 1.0
    i0 = np.clip(np.ceil((lo[:, 0] - xs[0]) / dx).astype(np.int64), 0, nx)
    i1 = np.clip(np.floor((hi[:, 0] - xs[0]) / dx).astype(np.int64), -1, nx - 1)
    j0 = np.clip(np.ceil((lo[:, 1] - ys[0]) / dy).astype(np.int64), 0, ny)
    j1 = np.clip(np.floor((hi[:, 1] - ys[0]) / dy).astype(np.int64), -1, ny - 1)
    ni = np.maximum(i1 - i0 + 1, 0)
    nj = np.maximum(j1 - j0 + 1, 0)
    anz = ni * nj
    ok = anz > 0
    tid = np.flatnonzero(ok)
    anz = anz[ok]
    if len(tid) == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    cols, zs = [], []
    STUECK = 4_000_000
    start = 0
    grenzen = np.cumsum(anz)
    while start < len(tid):
        ende = int(np.searchsorted(grenzen, (grenzen[start - 1] if start else 0) + STUECK, side="right"))
        ende = max(ende, start + 1)
        t = tid[start:ende]
        a = anz[start:ende]
        rep = np.repeat(np.arange(len(t)), a)
        lokal = np.arange(int(a.sum())) - np.repeat(np.cumsum(a) - a, a)
        tt = t[rep]
        ii = i0[tt] + lokal // nj[tt]
        jj = j0[tt] + lokal % nj[tt]
        px, py = xs[ii], ys[jj]
        ax, ay, az = A[tt, 0], A[tt, 1], A[tt, 2]
        bx, by, bz = B[tt, 0], B[tt, 1], B[tt, 2]
        cx, cy, cz = C[tt, 0], C[tt, 1], C[tt, 2]
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        gut = np.abs(det) > 1e-14
        with np.errstate(divide="ignore", invalid="ignore"):
            l1 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det
            l2 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det
            l3 = 1.0 - l1 - l2
            drin = gut & (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
            zs.append((l1 * az + l2 * bz + l3 * cz)[drin])
        cols.append((ii * ny + jj)[drin])
        start = ende
    col = np.concatenate(cols)
    z = np.concatenate(zs)
    o = np.lexsort((z, col))
    return col[o], z[o]


def innen_gitter(P: np.ndarray, T: np.ndarray, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """(nx, ny, nz) bool: Punkt (xs[i], ys[j], zs[k]) liegt im geschlossenen Netz (P, T)."""
    nx, ny, nz = len(xs), len(ys), len(zs)
    dx = (xs[1] - xs[0]) if nx > 1 else 1.0
    dy = (ys[1] - ys[0]) if ny > 1 else 1.0
    col, z = _schnitte(P, T, xs + VERSATZ[0] * dx, ys + VERSATZ[1] * dy)
    out = np.zeros((nx * ny, nz), dtype=bool)
    if len(col) == 0:
        return out.reshape(nx, ny, nz)
    zmin = float(min(z.min(), zs.min())) - 1.0
    spanne = float(max(z.max(), zs.max()) - zmin) + 2.0
    schluessel = col.astype(np.float64) * spanne + (z - zmin)
    alle = np.arange(nx * ny)
    anfang = np.searchsorted(schluessel, alle * spanne)
    for k, zk in enumerate(zs):
        q = alle * spanne + (zk - zmin)
        unter = np.searchsorted(schluessel, q) - anfang
        out[:, k] = (unter % 2) == 1
    return out.reshape(nx, ny, nz)


# -- Abstände --------------------------------------------------------------------------------------------------------


def unterteilen(P: np.ndarray, T: np.ndarray, max_kante: float, box: tuple[np.ndarray, np.ndarray] | None = None
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lange Dreiecke an der längsten Kante halbieren, bis keine Kante länger als ``max_kante`` ist; mit ``box`` (min,
    max) fallen Dreiecke außerhalb weg (lange Stangen der Nachbarn reichen weit über das Teil hinaus, ihre schmalen
    Dreiecke werden so nur der Länge nach geteilt). Rückgabe: Punkte, Dreiecke und je Dreieck das ursprüngliche."""
    P = np.asarray(P, float)
    T = np.asarray(T, np.int64)
    herkunft = np.arange(len(T))
    for _ in range(40):
        if box is not None and len(T):
            A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
            lo, hi = np.minimum(np.minimum(A, B), C), np.maximum(np.maximum(A, B), C)
            drin = np.all((hi >= box[0]) & (lo <= box[1]), axis=1)
            T, herkunft = T[drin], herkunft[drin]
        if len(T) == 0:
            break
        A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        lk = np.stack([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1), np.linalg.norm(A - C, axis=1)], 1)
        lang = lk.max(axis=1) > max_kante
        if not lang.any():
            break
        t = T[lang]
        k = np.argmax(lk[lang], axis=1)  # längste Kante: 0 = (0,1), 1 = (1,2), 2 = (2,0)
        r = np.stack([t[np.arange(len(t)), k], t[np.arange(len(t)), (k + 1) % 3], t[np.arange(len(t)), (k + 2) % 3]], 1)
        m = (P[r[:, 0]] + P[r[:, 1]]) / 2.0
        im = len(P) + np.arange(len(t))
        P = np.concatenate([P, m])
        neu = np.concatenate([np.stack([r[:, 0], im, r[:, 2]], 1), np.stack([im, r[:, 1], r[:, 2]], 1)])
        h = herkunft[lang]
        T = np.concatenate([T[~lang], neu])
        herkunft = np.concatenate([herkunft[~lang], h, h])
    return P, T, herkunft


def naechstes_dreieck(punkte: np.ndarray, P: np.ndarray, T: np.ndarray, grenze: float, k: int = 12
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Abstand und Nummer des nächsten Dreiecks je Punkt, für Abstände bis ``grenze`` (weiter: ``inf`` und -1).
    Große Dreiecke werden vorher geteilt (Kante höchstens ``grenze``), dann je Punkt die ``k`` nächsten
    Dreiecksmitten im Umkreis und genau Punkt ↔ Dreieck (k-d-Baum, ohne Listen)."""
    from scipy.spatial import cKDTree

    from kevcad_kernel.statik.festkoerper.kontakt import punkt_dreieck

    X = np.asarray(punkte, float)
    best = np.full(len(X), np.inf)
    arg = np.full(len(X), -1, dtype=np.int64)
    if len(X) == 0 or len(T) == 0:
        return best, arg
    box = (X.min(axis=0) - grenze - 1e-6, X.max(axis=0) + grenze + 1e-6)
    P2, T2, herkunft = unterteilen(P, T, max(float(grenze), 1.0), box)
    if len(T2) == 0:
        return best, arg
    A, B, C = P2[T2[:, 0]], P2[T2[:, 1]], P2[T2[:, 2]]
    mitte = (A + B + C) / 3.0
    rmax = float(np.max(np.stack([np.linalg.norm(A - mitte, axis=1), np.linalg.norm(B - mitte, axis=1),
                                  np.linalg.norm(C - mitte, axis=1)])))
    kk = min(k, len(T2))
    _, idx = cKDTree(mitte).query(X, k=kk, distance_upper_bound=float(grenze) + rmax)
    idx = np.asarray(idx).reshape(len(X), kk)
    for s in range(kk):
        t = idx[:, s]
        ok = t < len(T2)
        if not ok.any():
            break
        i = np.flatnonzero(ok)
        d = punkt_dreieck(X[i], A[t[i]], B[t[i]], C[t[i]])
        besser = d < best[i]
        best[i[besser]] = d[besser]
        arg[i[besser]] = herkunft[t[i[besser]]]
    weit = best > grenze
    best[weit] = np.inf
    arg[weit] = -1
    return best, arg


def abstand_band(innen: np.ndarray, punkte_fn: Any, P: np.ndarray, T: np.ndarray, band: float, breite: int = 2
                 ) -> np.ndarray:
    """Abstandsfeld mit Vorzeichen (innen negativ) auf dem Gitter ``innen``; genau nur im Band von ``breite`` Zellen
    um den Wechsel innen/außen, sonst ±``band``. ``punkte_fn(idx)`` liefert die Koordinaten der Knoten (k, 3)."""
    from scipy.ndimage import binary_dilation, binary_erosion

    st = np.ones((3, 3, 3), dtype=bool)
    nah = binary_dilation(innen, st, iterations=breite) & ~binary_erosion(innen, st, iterations=breite,
                                                                           border_value=0)
    f = np.where(innen, -band, band).astype(np.float64)
    idx = np.flatnonzero(nah.reshape(-1))
    if len(idx):
        d, _ = naechstes_dreieck(punkte_fn(idx), P, T, band)
        d = np.minimum(d, band)
        flach = f.reshape(-1)
        flach[idx] = np.where(innen.reshape(-1)[idx], -d, d)
    return f


# -- Bohrungen -----------------------------------------------------------------------------------------------------


@dataclass
class Bohrung:
    punkt: np.ndarray  # auf der Achse (Welt)
    achse: np.ndarray  # Einheitsvektor
    radius: float
    t0: float  # Bereich entlang der Achse (vom Punkt aus)
    t1: float
    umfang_grad: float
    flaechen: list[int] = field(default_factory=list)

    def abstand(self, X: np.ndarray) -> np.ndarray:
        """Abstand der Punkte zur Zylinderfläche (Welt), axial außerhalb des Bereichs zum Rand gemessen."""
        v = X - self.punkt[None, :]
        t = v @ self.achse
        r = np.linalg.norm(v - t[:, None] * self.achse[None, :], axis=1)
        radial = np.abs(r - self.radius)
        axial = np.maximum(np.maximum(self.t0 - t, t - self.t1), 0.0)
        return np.sqrt(radial ** 2 + axial ** 2)

    def kurz(self) -> dict[str, Any]:
        return {"punkt": [round(float(c), 3) for c in self.punkt], "achse": [round(float(c), 5) for c in self.achse],
                "d": round(2 * self.radius, 3), "tiefe": round(self.t1 - self.t0, 3),
                "umfang_grad": round(self.umfang_grad, 1), "flaechen": self.flaechen}


def bohrungen(shape: Any, max_radius: float = 30.0) -> list[Bohrung]:
    """Zylindrische Bohrungen (Wand außen, zusammen mindestens 300° Umfang) einer Form in Weltkoordinaten."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    gruppen: dict[tuple, list[tuple[int, float, float, float, np.ndarray, np.ndarray, float]]] = {}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    i = 0
    while ex.More():
        f = TopoDS.Face_s(ex.Current()) if hasattr(TopoDS, "Face_s") else TopoDS.Face(ex.Current())
        try:
            s = BRepAdaptor_Surface(f)
            if s.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                cyl = s.Cylinder()
                ax = cyl.Axis()
                p0 = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
                d = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
                r = float(cyl.Radius())
                umin, umax, vmin, vmax = BRepTools.UVBounds_s(f) if hasattr(BRepTools, "UVBounds_s") else \
                    BRepTools.UVBounds(f)
                um, vm = (umin + umax) / 2, (vmin + vmax) / 2
                gp = BRepGProp_Face(f)
                p = gp_Pnt()
                n = gp_Vec()
                gp.Normal(um, vm, p, n)
                P = np.array([p.X(), p.Y(), p.Z()])
                N = np.array([n.X(), n.Y(), n.Z()])
                v = P - p0
                radial = v - d * float(v @ d)
                hohl = float(N @ radial) < 0
                if hohl and r <= max_radius:
                    # gleiche Achse (Richtung bis aufs Vorzeichen, Punkt auf der Achse) und gleicher Radius
                    dd = d if (d[np.argmax(np.abs(d))] > 0) else -d
                    q = p0 - dd * float(p0 @ dd)
                    key = (tuple(np.round(dd, 4)), tuple(np.round(q, 2)), round(r, 3))
                    gruppen.setdefault(key, []).append((i, umax - umin, vmin * float(d @ dd), vmax * float(d @ dd),
                                                        p0, dd, r))
        except Exception:  # noqa: BLE001 - eine seltsame Fläche verhindert nicht die anderen
            pass
        i += 1
        ex.Next()
    out = []
    for key, fl in gruppen.items():
        umfang = sum(abs(x[1]) for x in fl) * 180.0 / math.pi
        if umfang < 300.0:
            continue
        p0, dd, r = fl[0][4], fl[0][5], fl[0][6]
        # Bereich entlang der Achse vom gemeinsamen Punkt p0 aus
        ts = []
        for _i, _u, a, b, q0, _d, _r in fl:
            off = float((q0 - p0) @ dd)
            ts += [off + min(a, b), off + max(a, b)]
        out.append(Bohrung(p0, dd, r, min(ts), max(ts), min(umfang, 360.0), [x[0] for x in fl]))
    return out


# -- Gitter ---------------------------------------------------------------------------------------------------------


@dataclass
class Gitter:
    """Elementgitter in Druckkoordinaten: Ursprung ``o`` (Druck, mm), Kante ``h``, Elemente ``ne``."""

    R: np.ndarray
    o: np.ndarray
    h: float
    ne: tuple[int, int, int]

    @property
    def nn(self) -> tuple[int, int, int]:
        return (self.ne[0] + 1, self.ne[1] + 1, self.ne[2] + 1)

    def zu_druck(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(X, float) @ self.R.T

    def zu_welt(self, Q: np.ndarray) -> np.ndarray:
        return np.asarray(Q, float) @ self.R

    def mitten(self, idx: np.ndarray | None = None) -> np.ndarray:
        """Elementmitten (Welt) aller oder der linearen Nummern ``idx``."""
        if idx is None:
            idx = np.arange(int(np.prod(self.ne)))
        ijk = np.stack(np.unravel_index(idx, self.ne), axis=1)
        return self.zu_welt(self.o[None, :] + (ijk + 0.5) * self.h)

    def knoten(self, idx: np.ndarray | None = None) -> np.ndarray:
        if idx is None:
            idx = np.arange(int(np.prod(self.nn)))
        ijk = np.stack(np.unravel_index(idx, self.nn), axis=1)
        return self.zu_welt(self.o[None, :] + ijk * self.h)

    def achsen_mitte(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return tuple(self.o[a] + (np.arange(self.ne[a]) + 0.5) * self.h for a in range(3))  # type: ignore[return-value]

    def kurz(self) -> dict[str, Any]:
        return {"R": np.round(self.R, 6).tolist(), "o": np.round(self.o, 4).tolist(), "h": round(self.h, 4),
                "ne": list(self.ne)}


def gitter_fuer(Pw: np.ndarray, R: np.ndarray, volumen: float, ziel_voxel: int, h_min: float = 0.3,
                h_max: float | None = None) -> Gitter:
    """Gitter über dem Hüllquader des Teils in Druckkoordinaten; Kante so, dass etwa ``ziel_voxel`` Elemente im Teil
    liegen. Das Gitter beginnt unten genau auf dem Bett."""
    Q = Pw @ R.T
    lo, hi = Q.min(axis=0), Q.max(axis=0)
    h = (max(volumen, 1e-9) / max(ziel_voxel, 1)) ** (1.0 / 3.0)
    h = max(h, h_min)
    if h_max:
        h = min(h, h_max)
    ne = tuple(max(1, int(math.ceil((hi[a] - lo[a]) / h - 1e-9))) for a in range(3))
    # mittig über x und y, unten bündig mit dem Bett
    rest = np.array([ne[a] * h - (hi[a] - lo[a]) for a in range(3)])
    o = lo - np.array([rest[0] / 2, rest[1] / 2, 0.0])
    return Gitter(R, o, h, ne)  # type: ignore[arg-type]
