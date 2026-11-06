"""Geometrische Prüfung eines fertigen Modells gegen seine Aufgabe (Orakel des Benchmarks).

Grundlage sind die B-Rep-Formen der Szene (``refs.PartRecord.shape``), also genau das, was der Kernel zuletzt gezeigt
hat. Das Orakel misst selbst (OpenCascade), es vertraut weder dem Agenten noch der eingebauten Prüfung des Kernels.
Maße in mm, Lagen in Weltkoordinaten.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder


@dataclass
class Teil:
    name: str
    form: Any  # build123d Shape
    kopf: dict[str, Any] = field(default_factory=dict)

    @property
    def material(self) -> str:
        return str(self.kopf.get("material") or "")

    def box(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        bb = self.form.bounding_box()
        return (bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)

    def masse(self) -> tuple[float, float, float]:
        lo, hi = self.box()
        return hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]

    def mitte(self) -> tuple[float, float, float]:
        lo, hi = self.box()
        return tuple((a + b) / 2 for a, b in zip(lo, hi))  # type: ignore[return-value]

    @property
    def volumen(self) -> float:
        return float(self.form.volume)


def teile(rt: Any) -> list[Teil]:
    """Gezeigte Teile des letzten Laufs ohne Kulisse und Skizzen."""
    out: list[Teil] = []
    for rec in rt.scene.records():
        kopf = dict(getattr(rec, "header", {}) or {})
        if kopf.get("kulisse") or str(rec.name).startswith("Skizze/") or not getattr(rec, "visible", True):
            continue
        try:
            form = rec.shape
        except Exception:  # noqa: BLE001 - ein Teil ohne Form zählt nicht
            continue
        if form is None:
            continue
        out.append(Teil(rec.name, form, kopf))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Zylinder, Bohrungen, Kegel


@dataclass
class Zylinder:
    r: float
    achse: tuple[float, float, float]  # Einheitsvektor
    punkt: tuple[float, float, float]  # Punkt auf der Achse
    innen: bool  # Bohrung (Fläche zeigt zur Achse) statt Außenfläche
    laenge: float  # Ausdehnung der Fläche entlang der Achse


def _norm(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return v[0] / n, v[1] / n, v[2] / n


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def zylinder(form: Any) -> list[Zylinder]:
    out: list[Zylinder] = []
    for f in form.faces():
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() != GeomAbs_Cylinder:
            continue
        c = s.Cylinder()
        ax = c.Axis()
        d = _norm((ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()))
        p = (ax.Location().X(), ax.Location().Y(), ax.Location().Z())
        mitte = f.center()
        try:
            n = f.normal_at(mitte)
            n = (n.X, n.Y, n.Z)
        except Exception:  # noqa: BLE001
            n = (0.0, 0.0, 0.0)
        q = (mitte.X, mitte.Y, mitte.Z)
        rel = _sub(q, p)
        radial = _sub(rel, tuple(_dot(rel, d) * c_ for c_ in d))  # vom Achsenfuß zum Flächenpunkt
        innen = _dot(n, radial) < 0
        ecken = [(v.X, v.Y, v.Z) for v in f.vertices()] or [q]
        proj = [_dot(_sub(e, p), d) for e in ecken]
        out.append(Zylinder(c.Radius(), d, p, innen, max(proj) - min(proj)))
    return out


def _achsfuss(z: Zylinder) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Richtung (Vorzeichen vereinheitlicht) und Punkt der Achse, der dem Ursprung am nächsten liegt."""
    d = z.achse
    if (d[2], d[1], d[0]) < (0, 0, 0):
        d = (-d[0], -d[1], -d[2])
    t = _dot(z.punkt, d)
    return d, (z.punkt[0] - t * d[0], z.punkt[1] - t * d[1], z.punkt[2] - t * d[2])


def bohrungen(form: Any, d: float, tol: float = 0.06, innen: bool = True) -> list[dict[str, Any]]:
    """Bohrungen (bzw. mit ``innen=False`` Zapfen/Rundungen) mit Durchmesser ``d``: je Achse eine, auch wenn die Fläche
    in mehrere Stücke geteilt ist. Ergebnis: Achse, Achsfuß, Länge."""
    gruppen: list[dict[str, Any]] = []
    for z in zylinder(form):
        if z.innen != innen or abs(2 * z.r - d) > tol:
            continue
        richtung, fuss = _achsfuss(z)
        for g in gruppen:
            if abs(_dot(g["achse"], richtung)) > 0.999 and math.dist(g["fuss"], fuss) < 0.05:
                g["laenge"] = max(g["laenge"], z.laenge)
                break
        else:
            gruppen.append({"achse": richtung, "fuss": fuss, "laenge": z.laenge})
    return gruppen


def kegel(form: Any) -> int:
    """Zahl der Kegelflächen (Fasen an runden Kanten)."""
    n = 0
    for f in form.faces():
        if BRepAdaptor_Surface(f.wrapped).GetType() == GeomAbs_Cone:
            n += 1
    return n


def schnittvolumen(a: Any, b: Any) -> float:
    """Volumen der Durchdringung zweier Teile (0, wenn sie sich nur berühren)."""
    try:
        common = a.intersect(b)
    except Exception:  # noqa: BLE001
        return 0.0
    try:
        return float(common.volume) if common is not None else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------------------------------------------------
# Prüfpunkte


@dataclass
class Punkt:
    was: str
    ok: bool
    ist: Any = None
    soll: Any = None

    def als_dict(self) -> dict[str, Any]:
        return {"was": self.was, "ok": self.ok, "ist": self.ist, "soll": self.soll}


class Bogen:
    """Sammelt Prüfpunkte einer Aufgabe."""

    def __init__(self) -> None:
        self.punkte: list[Punkt] = []

    def pruefe(self, was: str, ok: bool, ist: Any = None, soll: Any = None) -> bool:
        self.punkte.append(Punkt(was, bool(ok), _rund(ist), _rund(soll)))
        return bool(ok)

    def nahe(self, was: str, ist: float, soll: float, tol: float, relativ: bool = False) -> bool:
        grenze = abs(soll) * tol if relativ else tol
        return self.pruefe(was, ist is not None and abs(ist - soll) <= grenze, ist, soll)

    def masse(self, was: str, teil: Teil, soll: tuple[float, ...], tol: float = 0.25) -> bool:
        ist = sorted(teil.masse())
        ok = all(abs(a - b) <= tol for a, b in zip(ist, sorted(soll)))
        return self.pruefe(was, ok, ist, sorted(soll))

    @property
    def bestanden(self) -> bool:
        return bool(self.punkte) and all(p.ok for p in self.punkte)

    @property
    def anteil(self) -> float:
        return sum(p.ok for p in self.punkte) / len(self.punkte) if self.punkte else 0.0

    def als_dict(self) -> dict[str, Any]:
        return {"bestanden": self.bestanden, "anteil": round(self.anteil, 3),
                "punkte": [p.als_dict() for p in self.punkte]}


def _rund(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, (list, tuple)):
        return [_rund(x) for x in v]
    return v


def lochkreis(gruppen: list[dict[str, Any]], mitte: tuple[float, float]) -> tuple[list[float], list[float]]:
    """Abstände der Bohrungsachsen (senkrecht, Z) von ``mitte`` und Winkelschritte zwischen Nachbarn in Grad."""
    lagen = [(g["fuss"][0] - mitte[0], g["fuss"][1] - mitte[1]) for g in gruppen]
    radien = [math.hypot(x, y) for x, y in lagen]
    winkel = sorted(math.degrees(math.atan2(y, x)) % 360 for x, y in lagen)
    schritte = [(winkel[(i + 1) % len(winkel)] - winkel[i]) % 360 for i in range(len(winkel))] if winkel else []
    return radien, schritte
