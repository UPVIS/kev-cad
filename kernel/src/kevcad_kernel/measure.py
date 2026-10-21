"""Exakt messen mit OCCT (BRepExtrema, GProp) an aufgelösten Referenzen (refs.py).

Ergebnis wie ``MEASURE_RES.result`` in PROTOCOL.md: ``refs``, ``run``, ``kind`` (distance, angle, face, edge, vertex,
part), ``values``, ``points`` (Endpunkte für die Anzeige) und ``text`` (deutsch, Komma, drei Nachkommastellen).
"""

from __future__ import annotations

import math
from typing import Any

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.gp import gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS

from kevcad_kernel.refs import Resolved
from kevcad_kernel.tessellate import face_info

ANGLE_TOL_DEG = 1e-6
_R = 6

TYPE_GERMAN = {
    "plane": "Ebene Fläche", "cylinder": "Zylinderfläche", "cone": "Kegelfläche", "sphere": "Kugelfläche",
    "torus": "Torusfläche", "bspline": "Freiformfläche", "other": "Fläche",
}
EDGE_GERMAN = {"line": "Gerade Kante", "circle": "Kreiskante", "ellipse": "Ellipsenkante", "bspline": "Freiformkante",
               "other": "Kante"}


# ---------------------------------------------------------------------------------------------------------------------
# Zahlen deutsch
# ---------------------------------------------------------------------------------------------------------------------


def fmt(x: float, digits: int = 3) -> str:
    """12.5 → "12,500"; 48000 → "48.000,000"; -0.0 → "0,000"."""
    v = round(float(x), digits)
    if v == 0:
        v = 0.0
    s = f"{v:,.{digits}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_point(p: list[float]) -> str:
    return "(" + "; ".join(fmt(c) for c in p) + ")"


def _r(x: float) -> float:
    v = round(float(x), _R)
    return 0.0 if v == 0 else v


def _v(p) -> list[float]:
    return [_r(p.X()), _r(p.Y()), _r(p.Z())]


def _sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: list[float]) -> list[float]:
    n = _norm(a)
    return [c / n for c in a] if n > 0 else a


def _angle_deg(a: list[float], b: list[float]) -> float:
    c = max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))
    return math.degrees(math.acos(c))


def _components(d: list[float]) -> str:
    parts = [f"{n} {fmt(c)}" for n, c in zip(("dx", "dy", "dz"), d) if abs(round(c, 3)) > 0]
    return f" ({', '.join(parts)})" if parts else ""


# ---------------------------------------------------------------------------------------------------------------------
# Eigenschaften einzelner Elemente
# ---------------------------------------------------------------------------------------------------------------------


def _edge_props(edge) -> dict[str, Any]:
    e = TopoDS.Edge(edge.wrapped)
    adaptor = BRepAdaptor_Curve(e)
    ctype = adaptor.GetType()
    lp = GProp_GProps()
    BRepGProp.LinearProperties_s(e, lp)
    start = adaptor.Value(adaptor.FirstParameter())
    end = adaptor.Value(adaptor.LastParameter())
    v: dict[str, Any] = {"length": _r(lp.Mass()), "start": _v(start), "end": _v(end), "center": _v(lp.CentreOfMass())}
    if ctype == GeomAbs_CurveType.GeomAbs_Line:
        v["type"] = "line"
        v["direction"] = _v(adaptor.Line().Direction())
    elif ctype == GeomAbs_CurveType.GeomAbs_Circle:
        circ = adaptor.Circle()
        v["type"] = "circle"
        v["radius"] = _r(circ.Radius())
        v["diameter"] = _r(2 * circ.Radius())
        v["center"] = _v(circ.Location())
        v["axis"] = _v(circ.Axis().Direction())
        span = adaptor.LastParameter() - adaptor.FirstParameter()
        v["arc_angle"] = _r(math.degrees(span))
        v["closed"] = bool(abs(span - 2 * math.pi) < 1e-9)
    elif ctype == GeomAbs_CurveType.GeomAbs_Ellipse:
        el = adaptor.Ellipse()
        v["type"] = "ellipse"
        v["radius"] = _r(el.MajorRadius())
        v["minor_radius"] = _r(el.MinorRadius())
        v["center"] = _v(el.Location())
        v["axis"] = _v(el.Axis().Direction())
    elif ctype in (GeomAbs_CurveType.GeomAbs_BSplineCurve, GeomAbs_CurveType.GeomAbs_BezierCurve):
        v["type"] = "bspline"
    else:
        v["type"] = "other"
    return v


def _face_props(face) -> dict[str, Any]:
    info = face_info(face)
    sp = GProp_GProps()
    BRepGProp.SurfaceProperties_s(TopoDS.Face(face.wrapped), sp)
    v: dict[str, Any] = {"type": info["t"], "area": info["a"], "centroid": _v(sp.CentreOfMass())}
    if info["t"] == "plane":
        v["normal"] = info["n"]
        v["point"] = info["c"]
    if "r" in info:
        v["radius"] = info["r"]
        if info["t"] in ("cylinder", "sphere"):
            v["diameter"] = _r(2 * info["r"])
    if "r2" in info:
        v["minor_radius"] = info["r2"]
    if "ax" in info:
        v["axis"] = info["ax"]
    if info["t"] in ("cylinder", "cone", "sphere", "torus"):
        v["center"] = info["c"]
    if "ang" in info:
        v["semi_angle"] = info["ang"]
    return v


def _bbox(records) -> dict[str, list[float]]:
    mins = [min(r.bbox["min"][i] for r in records) for i in range(3)]
    maxs = [max(r.bbox["max"][i] for r in records) for i in range(3)]
    return {"min": mins, "max": maxs, "size": [_r(b - a) for a, b in zip(mins, maxs)]}


def _part_values(records) -> dict[str, Any]:
    volume = sum(r.props.get("volume", 0.0) for r in records)
    area = sum(r.props.get("area", 0.0) for r in records)
    v: dict[str, Any] = {"bbox": _bbox(records), "volume": _r(volume), "area": _r(area)}
    # Schwerpunkt: Volumen-gewichtet (gleiche Dichte), bei bekannten Materialien massengewichtet
    weights = [(r.props.get("volume", 0.0), r.props.get("center")) for r in records if r.props.get("center")]
    wsum = sum(w for w, _ in weights)
    if wsum > 0:
        v["center"] = [_r(sum(w * c[i] for w, c in weights) / wsum) for i in range(3)]
    elif records and records[0].props.get("center"):
        v["center"] = records[0].props["center"]
    masses = [(r.props.get("mass"), r.props.get("center")) for r in records]
    known = [(m, c) for m, c in masses if m is not None and c]
    if known:
        msum = sum(m for m, _ in known)
        v["mass"] = _r(msum)
        if msum > 0:
            v["center_of_mass"] = [_r(sum(m * c[i] for m, c in known) / msum) for i in range(3)]
        if len(known) < len(records):
            v["mass_incomplete"] = True
    mats = sorted({r.material for r in records if r.material})
    if mats:
        v["material"] = mats[0] if len(mats) == 1 else mats
    v["faces"] = sum(r.counts.get("face", 0) for r in records)
    v["edges"] = sum(r.counts.get("edge", 0) for r in records)
    if len(records) > 1:
        v["parts"] = len(records)
    return v


def measure_one(res: Resolved) -> dict[str, Any]:
    kind = res.kind
    if kind == "face":
        v = _face_props(res.shape)
        t = v["type"]
        text = f"{TYPE_GERMAN.get(t, 'Fläche')}: {fmt(v['area'])} mm²"
        if t == "plane":
            text += f", Normale {fmt_point(v['normal'])}"
        elif t in ("cylinder", "sphere"):
            text = f"{TYPE_GERMAN[t]}: r {fmt(v['radius'])} mm (Ø {fmt(v['diameter'])}), {fmt(v['area'])} mm²"
        elif t == "cone":
            text = f"Kegelfläche: Halbwinkel {fmt(abs(v.get('semi_angle', 0.0)))}°, {fmt(v['area'])} mm²"
        elif t == "torus":
            text = f"Torusfläche: R {fmt(v['radius'])} mm, r {fmt(v.get('minor_radius', 0.0))} mm, " \
                   f"{fmt(v['area'])} mm²"
        return {"kind": "face", "values": v, "points": [v.get("centroid")], "text": text}
    if kind == "edge":
        v = _edge_props(res.shape)
        t = v["type"]
        if t == "circle":
            text = f"Kreiskante: r {fmt(v['radius'])} mm (Ø {fmt(v['diameter'])}), Länge {fmt(v['length'])} mm"
            points = [v["center"]] if v.get("closed") else [v["start"], v["end"]]
        else:
            text = f"{EDGE_GERMAN.get(t, 'Kante')}: Länge {fmt(v['length'])} mm"
            points = [v["start"], v["end"]]
        return {"kind": "edge", "values": v, "points": points, "text": text}
    if kind == "vertex":
        p = BRep_Tool.Pnt_s(TopoDS.Vertex(res.shape.wrapped))
        pt = _v(p)
        v = {"point": pt, "x": pt[0], "y": pt[1], "z": pt[2]}
        return {"kind": "vertex", "values": v, "points": [pt], "text": f"Punkt {fmt_point(pt)}"}
    # Teil oder Gruppe
    v = _part_values(res.records)
    size = v["bbox"]["size"]
    label = f"Gruppe {res.ref.part} ({len(res.records)} Teile)" if kind == "group" else f"Teil {res.record.name}"
    text = f"{label}: {fmt(size[0])} × {fmt(size[1])} × {fmt(size[2])} mm"
    if v["volume"] > 0:
        text += f", Volumen {fmt(v['volume'])} mm³"
    if "mass" in v:
        text += f", Masse {fmt(v['mass'])} g"
    return {"kind": "part", "values": v, "points": [v["bbox"]["min"], v["bbox"]["max"]], "text": text}


# ---------------------------------------------------------------------------------------------------------------------
# Zwei Elemente
# ---------------------------------------------------------------------------------------------------------------------


def _exact_face(face) -> dict[str, Any]:
    """Ungerundete Werte einer Fläche für Winkel und Abstände: Typ, Normale/Punkt (Ebene), Achse/Mitte (Zylinder,
    Kegel), Mittelpunkt (Kugel)."""
    f = TopoDS.Face(face.wrapped)
    adaptor = BRepAdaptor_Surface(f)
    st = adaptor.GetType()
    sp = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, sp)
    c = sp.CentreOfMass()
    centroid = [c.X(), c.Y(), c.Z()]
    if st == GeomAbs_SurfaceType.GeomAbs_Plane:
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        p, n = gp_Pnt(), gp_Vec()
        BRepGProp_Face(f).Normal((u0 + u1) / 2, (v0 + v1) / 2, p, n)
        return {"t": "plane", "n": _unit([n.X(), n.Y(), n.Z()]), "c": centroid}
    if st in (GeomAbs_SurfaceType.GeomAbs_Cylinder, GeomAbs_SurfaceType.GeomAbs_Cone):
        ax = adaptor.Cylinder().Axis() if st == GeomAbs_SurfaceType.GeomAbs_Cylinder else adaptor.Cone().Axis()
        o, d = ax.Location(), ax.Direction()
        dv = [d.X(), d.Y(), d.Z()]
        ov = [o.X(), o.Y(), o.Z()]
        t = _dot(_sub(centroid, ov), dv)
        center = [ov[i] + t * dv[i] for i in range(3)]
        return {"t": "cylinder" if st == GeomAbs_SurfaceType.GeomAbs_Cylinder else "cone", "ax": dv, "c": center}
    if st == GeomAbs_SurfaceType.GeomAbs_Sphere:
        loc = adaptor.Sphere().Location()
        return {"t": "sphere", "c": [loc.X(), loc.Y(), loc.Z()]}
    return {"t": "other", "c": centroid}


def _exact_edge(edge) -> dict[str, Any]:
    adaptor = BRepAdaptor_Curve(TopoDS.Edge(edge.wrapped))
    ct = adaptor.GetType()
    if ct == GeomAbs_CurveType.GeomAbs_Line:
        d = adaptor.Line().Direction()
        p = adaptor.Value(adaptor.FirstParameter())
        return {"t": "line", "d": [d.X(), d.Y(), d.Z()], "p": [p.X(), p.Y(), p.Z()]}
    if ct in (GeomAbs_CurveType.GeomAbs_Circle, GeomAbs_CurveType.GeomAbs_Ellipse):
        g = adaptor.Circle() if ct == GeomAbs_CurveType.GeomAbs_Circle else adaptor.Ellipse()
        loc, d = g.Location(), g.Axis().Direction()
        return {"t": "circle" if ct == GeomAbs_CurveType.GeomAbs_Circle else "ellipse",
                "ax": [d.X(), d.Y(), d.Z()], "c": [loc.X(), loc.Y(), loc.Z()]}
    return {"t": "other"}


def _direction(res: Resolved) -> tuple[str, list[float], list[float]] | None:
    """(Art, Richtung, Punkt) für Winkel: Ebene → ("plane", Normale, Punkt), Gerade → ("line", Richtung, Start),
    Zylinder/Kegel/Kreis → ("axis", Achse, Mittelpunkt)."""
    if res.kind == "face":
        info = _exact_face(res.shape)
        if info["t"] == "plane":
            return "plane", info["n"], info["c"]
        if info["t"] in ("cylinder", "cone"):
            return "axis", info["ax"], info["c"]
    elif res.kind == "edge":
        info = _exact_edge(res.shape)
        if info["t"] == "line":
            return "line", info["d"], info["p"]
        if info["t"] in ("circle", "ellipse"):
            return "axis", info["ax"], info["c"]
    return None


def _circular(res: Resolved) -> tuple[str, list[float], list[float]] | None:
    """Kreis/Bohrung/Kugel: ("circle"|"cylinder"|"sphere", Mittelpunkt, Achse)."""
    if res.kind == "face":
        info = _exact_face(res.shape)
        if info["t"] == "cylinder":
            return "cylinder", info["c"], info["ax"]
        if info["t"] == "sphere":
            return "sphere", info["c"], [0.0, 0.0, 1.0]
    elif res.kind == "edge":
        info = _exact_edge(res.shape)
        if info["t"] == "circle":
            return "circle", info["c"], info["ax"]
    return None


def measure_two(a: Resolved, b: Resolved) -> dict[str, Any]:
    dist = BRepExtrema_DistShapeShape(a.shape.wrapped, b.shape.wrapped)
    if not dist.IsDone() or dist.NbSolution() < 1:
        raise ValueError("OCCT konnte den Abstand nicht bestimmen")
    p1, p2 = _v(dist.PointOnShape1(1)), _v(dist.PointOnShape2(1))
    d = _sub(p2, p1)
    values: dict[str, Any] = {"distance": _r(dist.Value()), "dx": _r(d[0]), "dy": _r(d[1]), "dz": _r(d[2])}
    points = [p1, p2]
    kind = "distance"
    text = f"Abstand {fmt(dist.Value())} mm{_components(d)}"

    da, db = _direction(a), _direction(b)
    angle_text = None
    if da and db:
        ka, va, ca = da
        kb, vb, cb = db
        raw = _angle_deg(va, vb)  # 0…180
        if (ka == "plane") != (kb == "plane"):
            # Gerade oder Achse gegen Ebene: Winkel zur Ebene = 90° - Winkel zur Normalen
            angle = abs(90.0 - min(raw, 180.0 - raw))
        else:
            angle = min(raw, 180.0 - raw)
        parallel = angle < ANGLE_TOL_DEG
        values["angle"] = _r(angle)
        values["parallel"] = bool(parallel)
        if ka == "plane" and kb == "plane":
            values["normal_angle"] = _r(raw)
        if parallel and ka == "plane" and kb == "plane":
            n = _unit(va)
            offset = _dot(_sub(cb, ca), n)
            foot = [ca[i] + offset * n[i] for i in range(3)]
            values["plane_distance"] = _r(abs(offset))
            dd = _sub(foot, ca)
            points = [[_r(c) for c in ca], [_r(c) for c in foot]]
            inner = _components(dd)[2:-1]
            text = f"Abstand {fmt(abs(offset))} mm (parallele Ebenen" + (f", {inner}" if inner else "") + ")"
            if abs(abs(offset) - dist.Value()) > 1e-6:
                text += f", kleinster Abstand {fmt(dist.Value())} mm"
        elif not parallel:
            kind = "angle"
            angle_text = f"Winkel {fmt(angle)}°"
            text = angle_text + (f", kleinster Abstand {fmt(dist.Value())} mm" if dist.Value() > 1e-9 else "")

    ra, rb = _circular(a), _circular(b)
    if ra and rb:
        ta, ca, axa = ra
        tb, cb, axb = rb
        axis_angle = _angle_deg(axa, axb)
        if "cylinder" in (ta, tb) and min(axis_angle, 180.0 - axis_angle) < 1e-6:
            # parallele Achsen: senkrechter Abstand der Achsen
            ax = _unit(axa if ta == "cylinder" else axb)
            delta = _sub(cb, ca)
            along = _dot(delta, ax)
            cb_proj = [cb[i] - along * ax[i] for i in range(3)]
            cdist = _norm(_cross(delta, ax))
            cpoints = [[_r(c) for c in ca], [_r(c) for c in cb_proj]]
        else:
            cdist = _norm(_sub(cb, ca))
            cpoints = [[_r(c) for c in ca], [_r(c) for c in cb]]
        cd = _sub(cpoints[1], cpoints[0])
        values["center_distance"] = _r(cdist)
        values["center_dx"], values["center_dy"], values["center_dz"] = _r(cd[0]), _r(cd[1]), _r(cd[2])
        values["center_points"] = cpoints
        points = cpoints
        kind = "distance"
        text = f"Mittenabstand {fmt(cdist)} mm{_components(cd)}, kleinster Abstand {fmt(dist.Value())} mm"
        if angle_text and values.get("angle", 0) > ANGLE_TOL_DEG:
            text += f", {angle_text}"
    return {"kind": kind, "values": values, "points": points, "text": text}


def measure(resolved: list[Resolved]) -> dict[str, Any]:
    """1 oder 2 aufgelöste Referenzen → MeasureResult ohne ``refs``/``run``/``ok`` (setzt die Laufzeit)."""
    if len(resolved) == 1:
        return measure_one(resolved[0])
    if len(resolved) == 2:
        return measure_two(resolved[0], resolved[1])
    raise ValueError("Messen braucht eine oder zwei Referenzen")
