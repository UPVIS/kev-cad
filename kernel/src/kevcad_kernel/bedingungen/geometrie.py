"""Bezüge der Bedingungen: benannte Flächen, Achsen und Punkte eines Teils, dazu die Rechenhilfen (4×4-Matrizen).

Ein ``Bezug`` hält seine Geometrie in Weltkoordinaten so, wie sie beim Anlegen war, und merkt sich das Teil, zu dem er
gehört (``quelle``: die OCCT-Form mit ihrer Lage). Wird das Teil danach verschoben oder gedreht (``Pos(...) * teil``,
``platziere``), teilt die gezeigte Form ihre Geometrie mit der Quelle (OCCT „Partner“); die Prüfung rechnet den Bezug
dann mit der Lageänderung um. So wandern Bezüge mit ihrem Teil, wie in CAD-Programmen.

Bezüge entstehen über Namen und Auswahlen, nie über Flächennummern (PLAN-BEDINGUNGEN.md, B2):

- Standardnamen: ``oben``/``unten`` (±Z), ``rechts``/``links`` (±X), ``hinten``/``vorn`` (±Y, vorn = −Y wie die
  Vorderansicht), ``x_max`` … ``z_min``; ``mitte`` (Mitte des Hüllquaders), ``schwerpunkt``; ``achse`` (Achse der
  größten Zylinderfläche, sonst längste Richtung des Hüllquaders), ``achse_x``/``achse_y``/``achse_z``; ``bohrung``
  (Bohrung, mit ``nahe=(x, y, z)`` die nächste); ``teil`` (das ganze Teil).
- Auswahl aus build123d: Fläche, Liste ebener Flächen in einer Ebene, Kante (Gerade, Kreis), Punkt, Funktion
  ``lambda t: t.faces().sort_by(Axis.Z)[0]``, ``Plane``, ``Axis``, ``Location``, Punkt als Tupel.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

EPS = 1e-3  # mm: Lage gilt als gleich
EPS_WINKEL = 0.01  # Grad
EPS_RICHTUNG = 1e-6  # 1 - cos: Richtungen gelten als parallel

STANDARD_EBENEN = {
    "oben": (2, 1), "unten": (2, -1), "rechts": (0, 1), "links": (0, -1), "hinten": (1, 1), "vorn": (1, -1),
    "vorne": (1, -1), "x_max": (0, 1), "x_min": (0, -1), "y_max": (1, 1), "y_min": (1, -1), "z_max": (2, 1),
    "z_min": (2, -1),
}
STANDARD_NAMEN = tuple(STANDARD_EBENEN) + ("mitte", "schwerpunkt", "achse", "achse_x", "achse_y", "achse_z", "bohrung",
                                           "teil")


class BezugFehler(ValueError):
    """Bezug lässt sich nicht bilden (unbekannter Name, leere Auswahl, falsche Art)."""


# ---------------------------------------------------------------------------------------------------------------------
# Vektoren und Matrizen


def v3(value: Any) -> np.ndarray:
    """build123d-Vector, gp_Pnt/gp_Dir/gp_Vec, Tupel oder Liste → numpy (3,)."""
    if isinstance(value, np.ndarray):
        return value.astype(float).reshape(3)
    if hasattr(value, "X") and not callable(value.X):
        return np.array([float(value.X), float(value.Y), float(value.Z)])
    if hasattr(value, "X") and callable(value.X):  # gp_Pnt, gp_Dir
        return np.array([float(value.X()), float(value.Y()), float(value.Z())])
    vals = [float(x) for x in value]
    if len(vals) == 2:
        vals.append(0.0)
    if len(vals) != 3:
        raise BezugFehler(f"Punkt oder Richtung braucht drei Zahlen, nicht {value!r}")
    return np.array(vals)


def einheit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise BezugFehler("Richtung hat die Länge null")
    return v / n


def senkrecht_zu(d: np.ndarray) -> np.ndarray:
    """Eine feste Richtung senkrecht zu ``d`` (für Bezugsrichtungen von Achsen und Ebenen)."""
    a = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = a - d * float(np.dot(a, d))
    return einheit(x)


def winkel_grad(u: np.ndarray, v: np.ndarray) -> float:
    c = float(np.clip(np.dot(u, v), -1.0, 1.0))
    return math.degrees(math.acos(c))


def linien_winkel(u: np.ndarray, v: np.ndarray) -> float:
    """Kleinster Winkel zwischen zwei Geraden (0…90°)."""
    w = winkel_grad(u, v)
    return min(w, 180.0 - w)


def gerichteter_winkel(x: np.ndarray, y: np.ndarray, achse: np.ndarray) -> float:
    """Winkel von x nach y um ``achse`` in Grad (−180…180), beide in die Ebene senkrecht zur Achse projiziert."""
    xp = x - achse * float(np.dot(x, achse))
    yp = y - achse * float(np.dot(y, achse))
    if np.linalg.norm(xp) < 1e-12 or np.linalg.norm(yp) < 1e-12:
        return 0.0
    return math.degrees(math.atan2(float(np.dot(np.cross(xp, yp), achse)), float(np.dot(xp, yp))))


def drehmatrix(achse: np.ndarray, winkel_rad: float) -> np.ndarray:
    """Rodrigues: Drehung um ``achse`` (Einheitsvektor) um ``winkel_rad``."""
    k = einheit(achse)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(winkel_rad) * K + (1 - math.cos(winkel_rad)) * (K @ K)


def drehvektor_matrix(w: np.ndarray) -> np.ndarray:
    a = float(np.linalg.norm(w))
    if a < 1e-15:
        return np.eye(3)
    return drehmatrix(w / a, a)


def minimale_drehung(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Kleinste Drehung, die die Richtung u auf v bringt."""
    u, v = einheit(u), einheit(v)
    c = float(np.dot(u, v))
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        return drehmatrix(senkrecht_zu(u), math.pi)
    return drehmatrix(np.cross(u, v), math.acos(max(-1.0, min(1.0, c))))


def pose(R: np.ndarray, zentrum: np.ndarray, t: np.ndarray) -> np.ndarray:
    """4×4-Matrix für x' = R (x − zentrum) + zentrum + t."""
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = zentrum - R @ zentrum + t
    return M


def drehung_um_gerade(punkt: np.ndarray, achse: np.ndarray, winkel_grad_: float) -> np.ndarray:
    return pose(drehmatrix(achse, math.radians(winkel_grad_)), punkt, np.zeros(3))


def verschiebung(t: np.ndarray) -> np.ndarray:
    M = np.eye(4)
    M[:3, 3] = t
    return M


def trsf_matrix(trsf: Any) -> np.ndarray:
    M = np.eye(4)
    for r in range(3):
        for c in range(4):
            M[r, c] = trsf.Value(r + 1, c + 1)
    return M


def form_matrix(topods: Any) -> np.ndarray:
    """Lage einer OCCT-Form als 4×4-Matrix."""
    return trsf_matrix(topods.Location().Transformation())


def matrix_trsf(M: np.ndarray) -> Any:
    from OCP.gp import gp_Trsf

    t = gp_Trsf()
    t.SetValues(*(float(M[r, c]) for r in range(3) for c in range(4)))
    return t


def matrix_location(M: np.ndarray) -> Any:
    from build123d import Location
    from OCP.TopLoc import TopLoc_Location

    return Location(TopLoc_Location(matrix_trsf(M)))


def ist_einheit(M: np.ndarray | None) -> bool:
    return M is None or bool(np.allclose(M, np.eye(4), atol=1e-12))


def transform_abstand(M1: np.ndarray, M2: np.ndarray, laenge: float = 100.0) -> float:
    """Wie verschieden zwei Lagen sind (mm, Drehung über ``laenge`` gewichtet)."""
    return float(np.linalg.norm(M1[:3, 3] - M2[:3, 3]) + laenge * np.linalg.norm(M1[:3, :3] - M2[:3, :3]))


# ---------------------------------------------------------------------------------------------------------------------
# Bezug


@dataclass(eq=False)
class Bezug:
    """Benannte Ebene, Achse, Punkt, Lage oder ganzes Teil in Weltkoordinaten (beim Anlegen).

    - ``ebene``: ``p`` Punkt (Mitte der Fläche), ``d`` Normale (aus dem Material heraus), ``flaechen`` die Flächen
    - ``achse``: ``p`` Punkt auf der Achse (Mitte der Ausdehnung), ``d`` Richtung, ``r`` Radius (Zylinder, Kreis),
      ``t`` Ausdehnung entlang ``d`` relativ zu ``p``, ``innen`` bei Bohrungen
    - ``punkt``: ``p``, bei Kugeln ``r``
    - ``lage``: ``p``, ``d`` (z-Richtung), ``x`` (x-Richtung); taugt als Ebene, Achse und Punkt
    - ``teil``: das ganze Teil (``p`` Mitte des Hüllquaders)
    """

    art: str
    p: np.ndarray
    d: np.ndarray | None = None
    x: np.ndarray | None = None
    r: float | None = None
    t: tuple[float, float] | None = None
    form: str = ""
    name: str = ""
    innen: bool = False
    quelle: Any = None  # TopoDS_Shape des Teils beim Anlegen (None: fester Weltbezug)
    M_q: np.ndarray | None = None
    quelle_koerper: list[Any] = field(default_factory=list)
    label: str = ""
    teil_form: Any = None  # build123d-Form des Teils (für Abstände und Wandstärken)
    flaechen: list[Any] = field(default_factory=list)  # TopoDS-Flächen (Weltlage beim Anlegen)
    M_extra: np.ndarray | None = None  # seither angewandte Lageänderung (für flaechen und abgeleitete Bezüge)
    M_form: np.ndarray | None = None  # Lageänderung, die teil_form noch braucht (None: liegt schon richtig)
    teilname: str | None = None  # gezeigter Name, sobald aufgelöst
    M_platziert: np.ndarray | None = None  # Lageänderung durch platziere (für Teile, die danach noch gebohrt werden)
    per_name: str | None = None  # Teil über seinen Namen aus show(), erst bei der Prüfung ausgewertet
    auswahl_args: tuple | None = None  # (name_oder_auswahl, auswahl, nahe, umkehren) für per_name

    def __post_init__(self) -> None:
        if self.x is None and self.d is not None:
            self.x = senkrecht_zu(self.d)

    # -- Anzeige --------------------------------------------------------------------------------------------------

    @property
    def welt(self) -> bool:
        return self.quelle is None and self.per_name is None

    def anzeigename(self) -> str:
        if self.welt:
            return self.name or self.label or "Welt"
        owner = self.teilname or self.label or "Teil"
        if self.art == "teil":
            return owner
        return f"{owner}.{self.name}" if self.name else owner

    # -- Lage -----------------------------------------------------------------------------------------------------

    def bewegt(self, M: np.ndarray) -> Bezug:
        """Derselbe Bezug nach der Lageänderung M (4×4, Welt → Welt)."""
        if ist_einheit(M):
            return replace(self)
        R = M[:3, :3]
        return replace(
            self, p=R @ self.p + M[:3, 3], d=None if self.d is None else R @ self.d,
            x=None if self.x is None else R @ self.x,
            M_extra=M if self.M_extra is None else M @ self.M_extra,
            M_form=M if self.M_form is None else M @ self.M_form)

    def flaechen_welt(self) -> list[Any]:
        if ist_einheit(self.M_extra):
            return list(self.flaechen)
        from OCP.TopLoc import TopLoc_Location

        loc = TopLoc_Location(matrix_trsf(self.M_extra))
        return [f.Moved(loc) for f in self.flaechen]

    def form_welt(self) -> Any:
        """Die build123d-Form des Teils in der aktuellen Lage (oder None)."""
        if self.teil_form is None:
            return None
        if ist_einheit(self.M_form):
            return self.teil_form
        return matrix_location(self.M_form) * self.teil_form

    # -- Sichten ----------------------------------------------------------------------------------------------------

    def kann(self, art: str) -> bool:
        if art == "ebene":
            return self.art in ("ebene", "lage")
        if art == "achse":
            return self.art in ("achse", "lage")
        if art == "punkt":
            return True
        if art == "richtung":
            return self.d is not None
        return self.art == art

    @property
    def richtung(self) -> np.ndarray:
        if self.d is None:
            raise BezugFehler(f"{self.anzeigename()} hat keine Richtung (Punkt)")
        return self.d

    def mitte(self) -> np.ndarray:
        if self.art == "achse" and self.t is not None and self.d is not None:
            return self.p + self.d * (self.t[0] + self.t[1]) / 2
        return self.p

    def kurz(self) -> dict[str, Any]:
        out: dict[str, Any] = {"art": self.art, "name": self.name, "teil": self.teilname or self.label or None,
                               "p": [round(float(c), 4) for c in self.p]}
        if self.d is not None:
            out["d"] = [round(float(c), 6) for c in self.d]
        if self.r is not None:
            out["r"] = round(float(self.r), 4)
        return out


def boden() -> Bezug:
    """Die Ebene z = 0 (fester Weltbezug, Normale +Z)."""
    return Bezug("ebene", np.zeros(3), np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]), form="welt", name="Boden",
                 label="Boden")


# ---------------------------------------------------------------------------------------------------------------------
# Formen lesen


def als_form(obj: Any) -> Any:
    """Builder → Ergebnis; Formen unverändert; sonst None."""
    from build123d import BuildLine, BuildPart, BuildSketch, Shape

    if isinstance(obj, BuildPart):
        return obj.part
    if isinstance(obj, BuildSketch):
        return obj.sketch
    if isinstance(obj, BuildLine):
        return obj.line
    return obj if isinstance(obj, Shape) else None


def _flaeche_daten(face: Any) -> dict[str, Any]:
    """Ebene, Zylinder, Kugel oder Kegel einer Fläche mit Lage (Welt), Normale, Radius."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere

    s = BRepAdaptor_Surface(face.wrapped)
    typ = s.GetType()
    if typ == GeomAbs_Plane:
        return {"typ": "ebene", "n": einheit(v3(face.normal_at())), "c": v3(face.center()), "a": float(face.area)}
    if typ in (GeomAbs_Cylinder, GeomAbs_Cone):
        geo = s.Cylinder() if typ == GeomAbs_Cylinder else s.Cone()
        ax = geo.Axis()
        p0, d = v3(ax.Location()), einheit(v3(ax.Direction()))
        xdir = v3(geo.Position().XDirection())
        pts = np.array([v3(v) for v in face.vertices()]) if face.vertices() else np.array([p0])
        ts = (pts - p0) @ d
        # Ausdehnung auch über die Kanten (Vollzylinder haben nur zwei Punkte auf der Naht)
        lo, hi = float(ts.min()), float(ts.max())
        sp = face.position_at(0.5, 0.5)
        n = v3(face.normal_at(sp))
        radial = v3(sp) - (p0 + d * float(np.dot(v3(sp) - p0, d)))
        innen = bool(np.dot(n, radial) < 0)
        out = {"typ": "zylinder" if typ == GeomAbs_Cylinder else "kegel", "p0": p0, "d": d, "x": xdir, "t": (lo, hi),
               "innen": innen, "a": float(face.area)}
        if typ == GeomAbs_Cylinder:
            out["r"] = float(geo.Radius())
        else:
            out["r"] = None
            out["winkel"] = math.degrees(float(geo.SemiAngle()))
        return out
    if typ == GeomAbs_Sphere:
        sph = s.Sphere()
        return {"typ": "kugel", "c": v3(sph.Location()), "r": float(sph.Radius()), "a": float(face.area)}
    return {"typ": "andere", "a": float(face.area)}


def _quelle(teil: Any) -> dict[str, Any]:
    """Felder eines Bezugs, die das Teil beschreiben (Quelle für das Wiederfinden in der Szene)."""
    if teil is None:
        return {}
    wrapped = getattr(teil, "wrapped", None)
    if wrapped is None:
        return {}
    try:
        koerper = [s.wrapped for s in teil.solids()]
    except Exception:  # noqa: BLE001
        koerper = []
    return {"quelle": wrapped, "M_q": form_matrix(wrapped), "quelle_koerper": koerper,
            "label": str(getattr(teil, "label", "") or ""), "teil_form": teil}


def _aus_flaechen(faces: list[Any], name: str, teil: Any) -> Bezug:
    infos = [(f, _flaeche_daten(f)) for f in faces]
    typen = {i["typ"] for _, i in infos}
    if typen == {"ebene"}:
        n0 = infos[0][1]["n"]
        for _, i in infos[1:]:
            if float(np.dot(i["n"], n0)) < 1 - 1e-6 or abs(float(np.dot(i["c"] - infos[0][1]["c"], n0))) > EPS:
                raise BezugFehler(f"Bezug {name or ''}: die Flächen liegen nicht in einer Ebene")
        flaeche = sum(i["a"] for _, i in infos)
        c = sum(i["c"] * i["a"] for _, i in infos) / flaeche if flaeche > 0 else infos[0][1]["c"]
        return Bezug("ebene", c, n0, form="flaeche", name=name, flaechen=[f.wrapped for f, _ in infos],
                     **_quelle(teil))
    if len(infos) == 1:
        f, i = infos[0]
        if i["typ"] in ("zylinder", "kegel"):
            mid = (i["t"][0] + i["t"][1]) / 2
            p = i["p0"] + i["d"] * mid
            return Bezug("achse", p, i["d"], x=i["x"], r=i["r"], t=(i["t"][0] - mid, i["t"][1] - mid), form=i["typ"],
                         name=name, innen=i["innen"], flaechen=[f.wrapped], **_quelle(teil))
        if i["typ"] == "kugel":
            return Bezug("punkt", i["c"], r=i["r"], form="kugel", name=name, flaechen=[f.wrapped], **_quelle(teil))
        raise BezugFehler(f"Bezug {name or ''}: Fläche ist weder eben noch zylindrisch noch kugelig")
    if typen <= {"zylinder"}:  # geteilte Zylinderfläche (Naht, Schnitt)
        return _zylinder_gruppe([f for f, _ in infos], [i for _, i in infos], name, teil)
    raise BezugFehler(f"Bezug {name or ''}: Flächen gemischter Art ({', '.join(sorted(typen))}); eine Ebene, einen "
                      "Zylinder oder eine Kugel wählen")


def _zylinder_gruppe(faces: list[Any], infos: list[dict[str, Any]], name: str, teil: Any) -> Bezug:
    i0 = infos[0]
    d, p0 = i0["d"], i0["p0"]
    lo, hi = [], []
    for i in infos:
        if abs(float(np.dot(i["d"], d))) < 1 - 1e-6 or abs((i["r"] or 0) - (i0["r"] or 0)) > EPS:
            raise BezugFehler(f"Bezug {name or ''}: Zylinderflächen sind nicht koaxial")
        off = i["p0"] - p0
        if np.linalg.norm(off - d * float(np.dot(off, d))) > EPS:
            raise BezugFehler(f"Bezug {name or ''}: Zylinderflächen sind nicht koaxial")
        s = float(np.dot(i["d"], d))
        base = float(np.dot(off, d))
        lo.append(base + min(s * i["t"][0], s * i["t"][1]))
        hi.append(base + max(s * i["t"][0], s * i["t"][1]))
    a, b = min(lo), max(hi)
    mid = (a + b) / 2
    return Bezug("achse", p0 + d * mid, d, x=i0["x"], r=i0["r"], t=(a - mid, b - mid), form="zylinder", name=name,
                 innen=i0["innen"], flaechen=[f.wrapped for f in faces], **_quelle(teil))


def _aus_kante(edge: Any, name: str, teil: Any) -> Bezug:
    from build123d import GeomType
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    if edge.geom_type == GeomType.LINE:
        a, b = v3(edge.position_at(0)), v3(edge.position_at(1))
        length = float(np.linalg.norm(b - a))
        d = einheit(b - a)
        return Bezug("achse", (a + b) / 2, d, t=(-length / 2, length / 2), form="kante", name=name, **_quelle(teil))
    if edge.geom_type == GeomType.CIRCLE:
        circ = BRepAdaptor_Curve(edge.wrapped).Circle()
        ax = circ.Axis()
        return Bezug("achse", v3(circ.Location()), einheit(v3(ax.Direction())), x=v3(circ.XAxis().Direction()),
                     r=float(circ.Radius()), t=(0.0, 0.0), form="kreis", name=name, **_quelle(teil))
    raise BezugFehler(f"Bezug {name or ''}: nur gerade Kanten und Kreiskanten (nicht {edge.geom_type.name})")


def _hueller(teil: Any, achse: int, vorzeichen: int, name: str) -> Bezug:
    bb = teil.bounding_box()
    lo, hi = v3(bb.min), v3(bb.max)
    p = (lo + hi) / 2
    p[achse] = hi[achse] if vorzeichen > 0 else lo[achse]
    n = np.zeros(3)
    n[achse] = float(vorzeichen)
    return Bezug("ebene", p, n, form="huelle", name=name, **_quelle(teil))


def standard_ebene(teil: Any, name: str) -> Bezug:
    """Ebene Fläche(n), die am besten in die Weltrichtung zeigen (höchstens 45° daneben, so findet „unten“ auch die
    Unterseite eines schräg modellierten Teils), davon die äußersten in einer Ebene; sonst die Hüllebene."""
    from build123d import GeomType

    achse, vorzeichen = STANDARD_EBENEN[name]
    n = np.zeros(3)
    n[achse] = float(vorzeichen)
    kandidaten = []
    for f in teil.faces():
        if f.geom_type != GeomType.PLANE:
            continue
        fn = v3(f.normal_at())
        c = float(np.dot(fn, n))
        if c < 0.7071:
            continue
        kandidaten.append((round(c, 6), fn, f))
    if not kandidaten:
        return _hueller(teil, achse, vorzeichen, name)
    beste = max(k[0] for k in kandidaten)
    gleich_gerichtet = [(fn, f) for c, fn, f in kandidaten if c >= beste - 1e-6]
    fn0 = gleich_gerichtet[0][0]
    lagen = [(float(np.dot(v3(f.center()), fn0)), f) for _, f in gleich_gerichtet]
    aussen = max(k for k, _ in lagen)
    faces = [f for k, f in lagen if k > aussen - 1e-4]
    return _aus_flaechen(faces, name, teil)


def bohrungen_von(teil: Any) -> list[Bezug]:
    """Alle Bohrungen (nach innen gewölbte Zylinderflächen), koaxiale Teilflächen gleichen Radius zusammengefasst,
    sortiert nach Lage (x, y, z)."""
    from build123d import GeomType

    gruppen: list[tuple[list[Any], list[dict[str, Any]]]] = []
    for f in teil.faces():
        if f.geom_type != GeomType.CYLINDER:
            continue
        info = _flaeche_daten(f)
        if not info.get("innen"):
            continue
        for faces, infos in gruppen:
            i0 = infos[0]
            off = info["p0"] - i0["p0"]
            if abs(float(np.dot(info["d"], i0["d"]))) > 1 - 1e-6 and abs(info["r"] - i0["r"]) < EPS and \
                    np.linalg.norm(off - i0["d"] * float(np.dot(off, i0["d"]))) < EPS:
                faces.append(f)
                infos.append(info)
                break
        else:
            gruppen.append(([f], [info]))
    out = []
    for faces, infos in gruppen:
        b = _zylinder_gruppe(faces, infos, "bohrung", teil)
        out.append(b)
    out.sort(key=lambda b: (round(float(b.p[0]), 3), round(float(b.p[1]), 3), round(float(b.p[2]), 3)))
    for i, b in enumerate(out):
        b.name = f"Bohrung Ø{_kurz(2 * (b.r or 0))}" if len(out) == 1 else f"Bohrung {i + 1} Ø{_kurz(2 * (b.r or 0))}"
    return out


def _kurz(x: float) -> str:
    from .text import zahl

    return zahl(x, 2)


def _naechste(kandidaten: list[Bezug], nahe: Any) -> Bezug:
    q = v3(nahe)

    def abstand(b: Bezug) -> float:
        if b.d is None:
            return float(np.linalg.norm(b.p - q))
        off = q - b.p
        along = float(np.dot(off, b.d))
        lo, hi = b.t if b.t is not None else (along, along)
        radial = float(np.linalg.norm(off - b.d * along))
        axial = max(0.0, lo - along, along - hi)
        return math.hypot(radial, axial)

    return min(kandidaten, key=abstand)


def achse_von(teil: Any, name: str = "achse") -> Bezug:
    """Achse der größten Zylinderfläche, sonst längste Richtung des Hüllquaders durch seine Mitte."""
    from build123d import GeomType

    zyl = [f for f in teil.faces() if f.geom_type == GeomType.CYLINDER]
    if zyl:
        f = max(zyl, key=lambda f: f.area)
        b = _aus_flaechen([f], name, teil)
        return b
    bb = teil.bounding_box()
    size = v3(bb.max) - v3(bb.min)
    k = int(np.argmax(size))
    d = np.zeros(3)
    d[k] = 1.0
    c = (v3(bb.max) + v3(bb.min)) / 2
    return Bezug("achse", c, d, t=(-size[k] / 2, size[k] / 2), form="huelle", name=name, **_quelle(teil))


def _aus_auswahl(teil: Any, auswahl: Any, name: str, nahe: Any) -> Bezug:
    from build123d import Axis, Edge, Face, Location, Plane, Shape, ShapeList, Vector, Vertex

    if callable(auswahl) and not isinstance(auswahl, (Shape, Plane, Axis, Location)):
        if teil is None:
            raise BezugFehler("Auswahl als Funktion braucht ein Teil: bezug(teil, lambda t: t.faces()...)")
        return _aus_auswahl(teil, auswahl(teil), name, nahe)
    if isinstance(auswahl, Face):
        return _aus_flaechen([auswahl], name, teil)
    if isinstance(auswahl, Edge):
        return _aus_kante(auswahl, name, teil)
    if isinstance(auswahl, Vertex):
        return Bezug("punkt", v3(auswahl.center()), form="punkt", name=name, **_quelle(teil))
    if isinstance(auswahl, (ShapeList, list, tuple)) and auswahl and all(isinstance(a, Face) for a in auswahl):
        faces = list(auswahl)
        if nahe is not None and len(faces) > 1:
            q = v3(nahe)
            faces = [min(faces, key=lambda f: float(np.linalg.norm(v3(f.center()) - q)))]
        return _aus_flaechen(faces, name, teil)
    if isinstance(auswahl, (ShapeList, list)) and auswahl and all(isinstance(a, Edge) for a in auswahl):
        edges = list(auswahl)
        if nahe is not None:
            q = v3(nahe)
            edges = [min(edges, key=lambda e: float(np.linalg.norm(v3(e.center()) - q)))]
        if len(edges) != 1:
            raise BezugFehler(f"Bezug {name or ''}: {len(edges)} Kanten gewählt; genau eine (oder nahe=(x, y, z))")
        return _aus_kante(edges[0], name, teil)
    if isinstance(auswahl, (ShapeList, list)) and not auswahl:
        raise BezugFehler(f"Bezug {name or ''}: die Auswahl ist leer")
    if isinstance(auswahl, Plane):
        return Bezug("ebene", v3(auswahl.origin), einheit(v3(auswahl.z_dir)), x=einheit(v3(auswahl.x_dir)),
                     form="ebene", name=name, **_quelle(teil))
    if isinstance(auswahl, Axis):
        return Bezug("achse", v3(auswahl.position), einheit(v3(auswahl.direction)), form="achse", name=name,
                     **_quelle(teil))
    if isinstance(auswahl, Location):
        pl = Plane(auswahl)
        return Bezug("lage", v3(pl.origin), einheit(v3(pl.z_dir)), x=einheit(v3(pl.x_dir)), form="lage", name=name,
                     **_quelle(teil))
    if isinstance(auswahl, Vector) or (isinstance(auswahl, (tuple, list)) and len(auswahl) == 3
                                       and all(isinstance(c, (int, float)) for c in auswahl)):
        return Bezug("punkt", v3(auswahl), form="punkt", name=name, **_quelle(teil))
    lage = getattr(auswahl, "location", None) or getattr(auswahl, "lage", None)
    if isinstance(lage, Location):  # Bezugspunkt aus dem Katalog (Strang Kameras) und ähnliche Objekte
        return _aus_auswahl(teil, lage, name or str(getattr(auswahl, "name", "") or ""), nahe)
    raise BezugFehler(f"Bezug {name or ''}: {type(auswahl).__name__} lässt sich nicht als Bezug verwenden (Fläche, "
                      "Kante, Punkt, Plane, Axis, Location, Funktion oder Standardname)")


def bezug(teil: Any, name_oder_auswahl: Any = None, auswahl: Any = None, *, nahe: Any = None,
          umkehren: bool = False) -> Bezug:
    """Bezug am Teil, siehe Moduldoku. ``bezug(teil, "unten")``, ``bezug(teil, "Auflage", fläche)``,
    ``bezug(teil, fläche)``, ``bezug(platte, "bohrung", nahe=(40, 0, 0))``; ``umkehren`` dreht Normale bzw. Richtung."""
    if isinstance(teil, Bezug):
        b = replace(teil)
        if umkehren:
            b = _umgekehrt(b)
        return b
    if isinstance(teil, str):
        return _per_name(teil, name_oder_auswahl, auswahl, nahe, umkehren)
    from build123d import Axis, Location, Plane, Vector

    form = als_form(teil)
    if form is None:  # Weltbezug: Plane, Axis, Location, Punkt
        if isinstance(teil, (Plane, Axis, Location, Vector, tuple, list)):
            name = name_oder_auswahl if isinstance(name_oder_auswahl, str) else ""
            b = _aus_auswahl(None, teil, name, None)
            return _umgekehrt(b) if umkehren else b
        lage = getattr(teil, "location", None)
        if isinstance(lage, Location):
            b = _aus_auswahl(getattr(teil, "teil", None), lage, str(getattr(teil, "name", "") or ""), None)
            return _umgekehrt(b) if umkehren else b
        raise BezugFehler(f"bezug(): {type(teil).__name__} ist kein Teil (build123d-Form, Plane, Axis, Location)")
    if isinstance(name_oder_auswahl, str):
        name = name_oder_auswahl.strip()
        if auswahl is not None:
            b = _aus_auswahl(form, auswahl, name, nahe)
        else:
            b = _standard(form, name.lower(), nahe)
    elif name_oder_auswahl is None:
        b = _standard(form, "teil", nahe)
    else:
        b = _aus_auswahl(form, name_oder_auswahl, "", nahe)
    return _umgekehrt(b) if umkehren else b


def _per_name(name: str, name_oder_auswahl: Any, auswahl: Any, nahe: Any, umkehren: bool) -> Bezug:
    """Bezug an einem Teil über seinen Namen aus show(): schon gezeigt → sofort an dieser Form, sonst bei der Prüfung
    an der gezeigten Form ausgewertet (Standardnamen und ganzes Teil)."""
    from .sammlung import aktive

    teilname = name.strip().strip("/")
    s = aktive()
    form = s.gezeigte_form(teilname) if s is not None else None
    if form is not None:
        b = bezug(form, name_oder_auswahl, auswahl, nahe=nahe, umkehren=umkehren)
        b.teilname = teilname
        b.per_name, b.auswahl_args = teilname, (name_oder_auswahl, auswahl, nahe, umkehren)
        return b
    wahl = name_oder_auswahl.lower() if isinstance(name_oder_auswahl, str) and auswahl is None else None
    if name_oder_auswahl is None or wahl == "teil":
        art = "teil"
    elif wahl in STANDARD_EBENEN:
        art = "ebene"
    elif wahl in ("achse", "achse_x", "achse_y", "achse_z", "bohrung", "loch"):
        art = "achse"
    elif wahl in ("mitte", "schwerpunkt"):
        art = "punkt"
    else:
        raise BezugFehler(f"Teil {teilname!r} ist (noch) nicht gezeigt: Bezug mit eigener Auswahl erst nach "
                          "show() nehmen oder die Form selbst übergeben")
    d = np.array([0.0, 0.0, 1.0]) if art in ("ebene", "achse") else None
    return Bezug(art, np.zeros(3), d, form="name", name=wahl if wahl not in (None, "teil") else "", label=teilname,
                 per_name=teilname, auswahl_args=(name_oder_auswahl, auswahl, nahe, umkehren))


def _umgekehrt(b: Bezug) -> Bezug:
    if b.d is None:
        return b
    return replace(b, d=-b.d, t=None if b.t is None else (-b.t[1], -b.t[0]))


def _standard(form: Any, name: str, nahe: Any) -> Bezug:
    if name in STANDARD_EBENEN:
        return standard_ebene(form, name)
    bb = form.bounding_box()
    if name == "mitte":
        return Bezug("punkt", (v3(bb.min) + v3(bb.max)) / 2, form="mitte", name="mitte", **_quelle(form))
    if name == "schwerpunkt":
        try:
            c = v3(form.center())
        except Exception:  # noqa: BLE001
            c = (v3(bb.min) + v3(bb.max)) / 2
        return Bezug("punkt", c, form="schwerpunkt", name="schwerpunkt", **_quelle(form))
    if name == "achse":
        return achse_von(form)
    if name in ("achse_x", "achse_y", "achse_z"):
        k = "xyz".index(name[-1])
        d = np.zeros(3)
        d[k] = 1.0
        size = v3(bb.max) - v3(bb.min)
        return Bezug("achse", (v3(bb.min) + v3(bb.max)) / 2, d, t=(-size[k] / 2, size[k] / 2), form="huelle",
                     name=name, **_quelle(form))
    if name in ("bohrung", "loch"):
        alle = bohrungen_von(form)
        if not alle:
            raise BezugFehler("Bezug bohrung: das Teil hat keine Bohrung (nach innen gewölbte Zylinderfläche)")
        if len(alle) == 1:
            return alle[0]
        if nahe is None:
            lagen = "; ".join(f"{b.name} bei {_punkt_text(b.p)}" for b in alle[:6])
            raise BezugFehler(f"Bezug bohrung: {len(alle)} Bohrungen ({lagen}{' …' if len(alle) > 6 else ''}); mit "
                              "nahe=(x, y, z) eine wählen")
        return _naechste(alle, nahe)
    if name == "teil":
        return Bezug("teil", (v3(bb.min) + v3(bb.max)) / 2, form="teil", name="", **_quelle(form))
    import difflib

    tips = difflib.get_close_matches(name, STANDARD_NAMEN, n=3, cutoff=0.5)
    raise BezugFehler(f"Bezug {name!r} unbekannt" + (f". Meinten Sie {', '.join(repr(t) for t in tips)}?" if tips else "")
                      + f" Standardnamen: {', '.join(STANDARD_NAMEN)}; sonst bezug(teil, \"Name\", auswahl)")


def _punkt_text(p: np.ndarray) -> str:
    from .text import vektor

    return vektor(p, 1)


def als_bezug(obj: Any) -> Bezug:
    """Bezug, Tupel (teil, name[, auswahl]) oder Teil (ganzes Teil) → Bezug."""
    if isinstance(obj, Bezug):
        return obj
    if isinstance(obj, tuple) and obj and not all(isinstance(c, (int, float)) for c in obj):
        teil, *rest = obj
        kwargs: dict[str, Any] = {}
        if rest and isinstance(rest[-1], dict):
            kwargs = rest.pop()
        return bezug(teil, *rest, **kwargs)
    return bezug(obj)


# ---------------------------------------------------------------------------------------------------------------------
# Schrauben


@dataclass
class SchraubenDaten:
    achse: Bezug  # Schaftachse, d zeigt vom Kopf zur Spitze, p am Kopfende des Schafts
    d: float  # Nenndurchmesser
    laenge: float  # Schaftlänge
    steigung: float | None
    kopf: Bezug  # Auflage des Kopfes (Ebene durch p, Normale zur Spitze)


def schraube_daten(teil: Any) -> SchraubenDaten:
    """Achse, Nenndurchmesser, Schaftlänge und Kopfauflage einer Schraube (Lagerteil oder selbst modelliert)."""
    from build123d import GeomType

    form = als_form(teil)
    if form is None:
        raise BezugFehler("in_bohrung: die Schraube muss ein Teil sein (z. B. schraube.verbauen(...))")
    zyl = []
    for f in form.faces():
        if f.geom_type != GeomType.CYLINDER:
            continue
        info = _flaeche_daten(f)
        if info.get("innen"):
            continue
        zyl.append((f, info))
    if not zyl:
        raise BezugFehler("in_bohrung: an der Schraube gibt es keinen zylindrischen Schaft")
    # Achse: längster Zylinder; dazu alle Zylinder auf derselben Achse (Schaft, Gewindeteil, Kopf)
    f, info = max(zyl, key=lambda fi: (round(fi[1]["t"][1] - fi[1]["t"][0], 3), -fi[1]["r"]))
    d_dir, p0 = info["d"], info["p0"]
    koaxial = []  # (Radius, von, bis) entlang d_dir ab p0
    for _, i2 in zyl:
        off = i2["p0"] - p0
        if np.linalg.norm(off - d_dir * float(np.dot(off, d_dir))) < EPS and abs(float(np.dot(i2["d"], d_dir))) > 1 - 1e-6:
            s = float(np.dot(i2["d"], d_dir))
            base = float(np.dot(off, d_dir))
            koaxial.append((float(i2["r"]), base + min(s * i2["t"][0], s * i2["t"][1]),
                            base + max(s * i2["t"][0], s * i2["t"][1])))
    nenn, steig = None, None
    lt = getattr(form, "lagerteil", None)
    groesse = str(getattr(lt, "masse", {}).get("groesse", "")) if lt is not None else ""
    if groesse.upper().startswith("M"):
        try:
            teile = groesse[1:].split("-")
            nenn = float(teile[0].replace(",", "."))
            if len(teile) > 1:
                steig = float(teile[1].replace(",", "."))
        except ValueError:
            nenn = None
    r_schaft = nenn / 2 + 0.05 if nenn else float(info["r"]) + EPS
    schaft = [k for k in koaxial if k[0] <= r_schaft]
    if not schaft:
        raise BezugFehler("in_bohrung: an der Schraube gibt es keinen zylindrischen Schaft")
    lo, hi = min(k[1] for k in schaft), max(k[2] for k in schaft)
    if nenn is None:
        nenn = 2 * max(k[0] for k in schaft)
    # Kopf: Seite, auf der die Form über den Schaft hinausragt
    pts = np.array([v3(v) for v in form.vertices()])
    proj = (pts - p0) @ d_dir
    radial = np.linalg.norm((pts - p0) - np.outer(proj, d_dir), axis=1)
    dick = radial > nenn / 2 + 0.1
    kopf_bei_lo = True
    if dick.any():
        mitte_dick = float(proj[dick].mean())
        kopf_bei_lo = abs(mitte_dick - lo) < abs(mitte_dick - hi)
    tip = d_dir if kopf_bei_lo else -d_dir  # zeigt zur Spitze
    # Kopfauflage: ebene Fläche quer zur Achse, zur Spitze gewandt, mit dem größten Außenradius (Unterseite des Kopfes)
    beste, beste_r = None, -1.0
    for g in form.faces():
        if g.geom_type != GeomType.PLANE:
            continue
        n = v3(g.normal_at())
        if float(np.dot(n, tip)) < 1 - 1e-6:
            continue
        gp = np.array([v3(v) for v in g.vertices()]) if g.vertices() else np.array([v3(g.center())])
        rr = float(np.max(np.linalg.norm((gp - p0) - np.outer((gp - p0) @ d_dir, d_dir), axis=1)))
        if rr > beste_r + 1e-6:
            beste, beste_r = float(np.dot(v3(g.center()) - p0, tip)), rr
    spitze = hi if kopf_bei_lo else -lo  # Ende des Schafts, gemessen entlang tip
    start =beste if beste is not None and beste_r > nenn / 2 + 0.1 else (lo if kopf_bei_lo else -hi)
    p_kopf = p0 + tip * start
    q = _quelle(form)
    laenge = spitze - start
    achse = Bezug("achse", p_kopf, tip, x=info["x"], r=nenn / 2, t=(0.0, laenge), form="schaft", name="Schaft", **q)
    kopf = Bezug("ebene", p_kopf, tip, form="kopf", name="Kopfauflage", **q)
    return SchraubenDaten(achse=achse, d=nenn, laenge=laenge, steigung=steig, kopf=kopf)


def bohrung_ende(teil_form: Any, bohrung: Bezug, ende: int) -> tuple[np.ndarray, np.ndarray]:
    """Punkt und Normale (aus dem Material heraus) der Bohrungsöffnung am Ende ``ende`` (−1: t[0], +1: t[1])."""
    assert bohrung.d is not None and bohrung.t is not None
    t = bohrung.t[1] if ende > 0 else bohrung.t[0]
    p = bohrung.p + bohrung.d * t
    n = bohrung.d * (1.0 if ende > 0 else -1.0)
    return p, n


def punkt_im_koerper(form: Any, p: np.ndarray) -> bool:
    """Liegt der Punkt im Material (oder auf dem Rand)?"""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    try:
        solids = form.solids() if hasattr(form, "solids") else []
    except Exception:  # noqa: BLE001
        solids = []
    for s in solids or [form]:
        c = BRepClass3d_SolidClassifier(s.wrapped, gp_Pnt(*map(float, p)), 1e-6)
        if c.State() in (TopAbs_IN, TopAbs_ON):
            return True
    return False


def iter_bezuege(objs: Iterable[Any]) -> list[Bezug]:
    return [als_bezug(o) for o in objs]


Auswahl = Callable[[Any], Any]
