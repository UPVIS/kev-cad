"""Schnittansichten (ISO 128-40/44, Schraffur ISO 128-50) und Einzelheiten.

Schnitt (``ansichten[i].schnitt``): ``{"von": "v1", "ebene": {"punkt": [x, y, z], "normale": [nx, ny, nz]},
"name": "A"}`` im System des Blatts (bei Einzelteilen das lokale System des Teils). ``normale`` ist die Blickrichtung
des Schnitts: Kev CAD entfernt den Teil vor der Ebene (auf der Seite des Betrachters) und zeigt den Rest. Schnittflächen
werden schraffiert, schmale Volllinien unter 45°, Abstand nach Flächengröße; im Zusammenbau hat jedes Teil eigene
Winkel bzw. Abstände, damit benachbarte Teile unterscheidbar sind. In der Ausgangsansicht erscheint der Schnittverlauf
(Strichpunktlinie, an den Enden breit) mit Pfeilen in Blickrichtung und dem Namen.

Einzelheit (``ansichten[i].einzelheit``): ``{"von": "v1", "mitte": [x, y], "radius": r, "faktor": 4, "name": "B"}`` mit
Mitte und Radius in Modell-mm der Ausgangsansicht; die Linien im Kreis erscheinen vergrößert, in der Ausgangsansicht
markiert ein schmaler Kreis mit dem Namen die Stelle.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.ansichten import aus_richtung
from kevcad_kernel.zeichnung.geo2d import clip_kreis, ringe_aus_strecken, schraffur
from kevcad_kernel.zeichnung.projektion import LINIENARTEN, Projektion, _kanten, _rahmen, projiziere, verbinde

GROSS = 1e5


def _halbraum(punkt: np.ndarray, normale: np.ndarray) -> Any:
    """Großer Quader auf der Seite −normale der Ebene (der Teil vor dem Schnitt, der entfernt wird)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    n = normale / np.linalg.norm(normale)
    hilf = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(n, hilf)
    x /= np.linalg.norm(x)
    # Ecke so, dass der Quader von der Ebene aus in −n reicht und seitlich weit übersteht
    y = np.cross(n, x)
    ecke = punkt - x * GROSS / 2 - y * GROSS / 2 - n * GROSS
    ax = gp_Ax2(gp_Pnt(*ecke), gp_Dir(*n), gp_Dir(*x))
    return BRepPrimAPI_MakeBox(ax, GROSS, GROSS, GROSS).Shape()


def schneide(form: Any, punkt: np.ndarray, normale: np.ndarray) -> Any | None:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    shape = form.wrapped if hasattr(form, "wrapped") else form
    op = BRepAlgoAPI_Cut(shape, _halbraum(punkt, normale))
    if not op.IsDone():
        return None
    return op.Shape()


def schnittflaechen(geschnitten: Any, punkt: np.ndarray, normale: np.ndarray) -> list[Any]:
    """Ebene Flächen des geschnittenen Körpers, die in der Schnittebene liegen."""
    from build123d import Shape

    from kevcad_kernel.zeichnung.topologie import analysiere

    out = []
    if geschnitten is None:
        return out
    top = analysiere(Shape.cast(geschnitten))
    n = normale / np.linalg.norm(normale)
    for f in top.flaechen:
        if f.typ == "ebene" and f.n is not None and abs(float(np.dot(f.n, n))) > 1 - 1e-6 \
                and abs(float(np.dot(f.punkt - punkt, n))) < 1e-4:
            out.append(f.form)
    return out


def _ringe(flaechen: list[Any], b: Any) -> list[np.ndarray]:
    """Ränder der Schnittflächen in der Ansicht (Modell-2D) als geschlossene Ringe."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf

    from kevcad_kernel.zeichnung.projektion import kante_polylinie

    trsf = gp_Trsf()
    ax = gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(*(-np.asarray(b.d))), gp_Dir(*b.rechts))
    trsf.SetTransformation(ax)  # Welt → Ansicht (x = rechts, y = oben, z = zum Betrachter)
    linien = []
    for f in flaechen:
        moved = BRepBuilderAPI_Transform(f.wrapped, trsf, True).Shape()
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer

        exp = TopExp_Explorer(moved, TopAbs_EDGE)
        while exp.More():
            pl = kante_polylinie(exp.Current(), 0.01)
            if pl is not None:
                linien.append(pl)
            exp.Next()
    return ringe_aus_strecken(linien, 1e-4)


def schnittansicht(e: dict[str, Any], formen: dict[str, Any], schluessel: dict[str, str],
                   ansichten: dict[str, Any]) -> Any:
    """Schnittansicht als _Ansicht (zeichner.py) mit Schraffur; markiert den Verlauf in der Ausgangsansicht."""
    from kevcad_kernel.zeichnung.zeichner import _Ansicht

    sp = e.get("schnitt") or {}
    ebene = sp.get("ebene") or {}
    punkt = np.asarray(ebene.get("punkt") or [0, 0, 0], dtype=float)
    normale = np.asarray(ebene.get("normale") or [0, 1, 0], dtype=float)
    normale = normale / (np.linalg.norm(normale) or 1.0)
    oben = (0, 1, 0) if abs(normale[2]) > 0.9 else (0, 0, 1)
    b = aus_richtung(normale, oben, "schnitt")
    geschnitten: dict[str, Any] = {}
    ringe_je_teil: list[list[np.ndarray]] = []
    for name, f in formen.items():
        g = schneide(f, punkt, normale)
        if g is None:
            continue
        from build123d import Shape

        geschnitten[name] = Shape.cast(g)
        ringe_je_teil.append(_ringe(schnittflaechen(g, punkt, normale), b))
    if not geschnitten:
        return None
    p = projiziere(geschnitten, b, verdeckt=False, glatt=True, mittel=False, je_teil=len(geschnitten) > 1,
                   schluessel={n: f"{schluessel.get(n, n)}|schnitt|{punkt.tolist()}|{normale.tolist()}"
                               for n in geschnitten})
    v = _Ansicht(e, b, p, titel=e.get("titel"))
    v.schraffur_ringe = ringe_je_teil
    # Schnittverlauf in der Ausgangsansicht (Modell-2D der Ausgangsansicht)
    von = ansichten.get(sp.get("von"))
    if von is not None:
        bv = von.blick
        u = np.cross(normale, bv.d)  # Spur der Ebene in der Ausgangsansicht (senkrecht zu Normale und Blick)
        if np.linalg.norm(u) > 1e-6:
            u /= np.linalg.norm(u)
            x0, y0, x1, y1 = von.rahmen_m
            c2 = bv.projiziere(punkt)
            u2 = bv.projiziere(u)
            u2 = u2 / (np.linalg.norm(u2) or 1.0)
            halb = 0.5 * math.hypot(x1 - x0, y1 - y0) + 3
            a, bb = c2 - u2 * halb, c2 + u2 * halb
            von.zusatz.setdefault("schnitt", []).append(np.array([a, bb]))
            von.e["_schnittverlauf"] = von.e.get("_schnittverlauf", []) + [
                {"name": sp.get("name", "A"), "a": a.tolist(), "b": bb.tolist(),
                 "pfeil": bv.projiziere(normale).tolist()}]
    return v


def schraffur_linien(v: Any) -> list[np.ndarray]:
    """Schraffur der Schnittflächen in Blatt-mm (nach der Maßstabswahl)."""
    out = []
    for i, ringe in enumerate(getattr(v, "schraffur_ringe", []) or []):
        if not ringe:
            continue
        blatt_ringe = [v.blatt(r) for r in ringe]
        groesse = max(max(float(np.ptp(r[:, 0])), float(np.ptp(r[:, 1]))) for r in blatt_ringe)
        from kevcad_kernel.zeichnung.hausregeln import aktiv

        basis = aktiv().schraffurabstand
        abstand = basis * (0.6 if groesse < 15 else 1.0 if groesse < 60 else 1.6)
        winkel = (45.0, 135.0, 60.0, 120.0)[i % 4]
        abstand *= (1.0, 1.0, 1.3, 1.3)[i % 4]
        out += schraffur(blatt_ringe, winkel, abstand)
        out += [r for r in blatt_ringe]
    return out


def einzelheit(e: dict[str, Any], ansichten: dict[str, Any]) -> Any:
    from kevcad_kernel.zeichnung.zeichner import _Ansicht

    ez = e.get("einzelheit") or {}
    von = ansichten.get(ez.get("von"))
    if von is None:
        return None
    c = np.asarray(ez.get("mitte") or [0, 0], dtype=float)
    r = float(ez.get("radius") or 10.0)
    p = Projektion(von.blick)
    for art in LINIENARTEN:
        for pl in von.proj.linien.get(art) or []:
            p.linien[art] += clip_kreis(pl, c, r)
    t = np.linspace(0, 2 * math.pi, 73)
    kreis = np.stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t)], axis=1)
    p.linien["duenn"].append(kreis)
    p.rahmen = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    v = _Ansicht(e, von.blick, p, titel=e.get("titel"))
    von.zusatz.setdefault("duenn", []).append(kreis)
    von.e["_einzelheit_marke"] = von.e.get("_einzelheit_marke", []) + [
        {"name": ez.get("name", "B"), "mitte": c.tolist(), "radius": r}]
    _ = verbinde, _kanten, _rahmen
    return v
