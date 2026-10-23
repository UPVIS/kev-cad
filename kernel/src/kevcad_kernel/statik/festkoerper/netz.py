"""Vernetzen mit Gmsh (nur im FEM-Prozess, Gmsh ist GPL): BREP → Tetraeder erster Ordnung (der Löser macht daraus
P2-Elemente mit Kantenmitten), dazu je Randdreieck die B-Rep-Fläche, aus der es stammt.

Netzgröße h: aus der mittleren Wandstärke 2 V / A (für eine Platte die Dicke, für einen Würfel ein Drittel der
Kante), mit ``WAND_ANTEIL`` davon (P2 rechnet Biegung schon mit einem Element über die Dicke auf etwa 1 % genau),
begrenzt durch die Elementzahl (Tetraeder ≈ 5 V / h³, höchstens ``MAX_TET``) und höchstens ein Sechstel der
Teilgröße. Kleine Löcher und Rundungen verfeinert Gmsh über die Krümmung
(``KRUEMMUNG`` Elemente je Vollkreis), höchstens bis h / 3.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

WAND_ANTEIL = 1.0
WAND_ANTEIL_FEIN = 0.5
MAX_TET = 8_000
MAX_TET_FEIN = 40_000
KRUEMMUNG = 18
KRUEMMUNG_FEIN = 32
TET_JE_H3 = 5.0  # Tetraeder je h³ Volumen (gemessen an Quadern, Gmsh HXT)


def netzgroesse(volumen: float, flaeche: float, groesse: float, fein: bool = False,
                h_vorgabe: float | None = None) -> float:
    if h_vorgabe:
        return float(h_vorgabe)
    wand = 2.0 * volumen / max(flaeche, 1e-9)
    h = (WAND_ANTEIL_FEIN if fein else WAND_ANTEIL) * wand
    max_tet = MAX_TET_FEIN if fein else MAX_TET
    h_min = (TET_JE_H3 * volumen / max_tet) ** (1 / 3)
    return float(min(max(h, h_min), groesse / 6.0))


def vernetze(brep: str, fein: bool = False, h_vorgabe: float | None = None, faeden: int = 4,
             verfeinern: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Tetraedernetz aus einer BREP-Datei: ``p`` (n, 3), ``t`` (m, 4), ``rand`` (k, 3) Randdreiecke, ``flaeche`` (k,)
    B-Rep-Fläche je Randdreieck, ``h``, ``volumen``, ``ms``. ``verfeinern`` (Stufe 4, additiv): Kugeln
    ``{"punkt", "radius", "h", "aussen"}``, in denen das Netz höchstens ``h`` groß ist (nach außen bis ``aussen``,
    sonst dem Dreifachen des Radius, auf die Netzgröße übergehend), etwa an einem Punktkontakt."""
    import gmsh

    t0 = time.perf_counter()
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", int(faeden))
        gmsh.model.add("teil")
        try:
            gmsh.model.occ.importShapes(brep, highestDimOnly=True)
        except Exception:  # noqa: BLE001 - BREP einer anderen OCCT-Fassung: noch einmal mit Heilen
            gmsh.model.occ.importShapes(brep, highestDimOnly=False)
            gmsh.model.occ.healShapes()
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        if not vols:
            raise ValueError("Das Teil hat keinen Volumenkörper (offene Fläche oder nur Kanten)")
        V = sum(gmsh.model.occ.getMass(3, t) for _, t in vols)
        A = sum(gmsh.model.occ.getMass(2, t) for _, t in gmsh.model.getEntities(2))
        lo = np.full(3, np.inf)
        hi = np.full(3, -np.inf)
        for _, t in vols:
            b = gmsh.model.getBoundingBox(3, t)
            lo = np.minimum(lo, b[:3])
            hi = np.maximum(hi, b[3:])
        groesse = float(np.max(hi - lo))
        h = netzgroesse(V, A, groesse, fein, h_vorgabe)
        out = None
        for versuch, algo in enumerate((10, 1)):  # HXT (parallel), sonst Delaunay
            try:
                gmsh.model.mesh.clear()
                gmsh.option.setNumber("Mesh.MeshSizeMax", h)
                gmsh.option.setNumber("Mesh.MeshSizeMin", h / 3.0)
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", KRUEMMUNG_FEIN if fein else KRUEMMUNG)
                gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
                gmsh.option.setNumber("Mesh.Algorithm3D", algo)
                if verfeinern:
                    _felder(gmsh, verfeinern, h)
                gmsh.model.mesh.generate(3)
                out = _auslesen(gmsh)
                break
            except Exception as exc:  # noqa: BLE001
                if versuch == 1:
                    raise RuntimeError(f"Gmsh konnte das Teil nicht vernetzen: {exc}") from exc
        assert out is not None
        out.update({"h": h, "volumen": V, "flaeche_mm2": A, "groesse": groesse,
                    "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return out
    finally:
        gmsh.finalize()


def _felder(gmsh: Any, verfeinern: list[dict[str, Any]], h: float) -> None:
    """Größenfelder für örtliche Verfeinerung (Abstand zu einem Punkt, Schwelle), als Minimum aller Felder."""
    f = gmsh.model.mesh.field
    ids = []
    for v in verfeinern:
        p = gmsh.model.occ.addPoint(*[float(c) for c in v["punkt"]])
        gmsh.model.occ.synchronize()
        d = f.add("Distance")
        f.setNumbers(d, "PointsList", [p])
        t = f.add("Threshold")
        f.setNumber(t, "InField", d)
        f.setNumber(t, "SizeMin", float(v["h"]))
        f.setNumber(t, "SizeMax", float(h))
        f.setNumber(t, "DistMin", float(v["radius"]))
        f.setNumber(t, "DistMax", float(v.get("aussen") or 3.0 * float(v["radius"])))
        ids.append(t)
    m = f.add("Min")
    f.setNumbers(m, "FieldsList", ids)
    f.setAsBackgroundMesh(m)
    gmsh.option.setNumber("Mesh.MeshSizeMin", min(float(v["h"]) for v in verfeinern))
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)


def _auslesen(gmsh: Any) -> dict[str, Any]:
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    xyz = np.asarray(xyz, float).reshape(-1, 3)
    tags = np.asarray(tags, dtype=np.int64)
    idx = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
    idx[tags] = np.arange(len(tags))
    tets = []
    for _, vt in gmsh.model.getEntities(3):
        et, _, en = gmsh.model.mesh.getElements(3, vt)
        for typ, knoten in zip(et, en):
            if int(typ) == 4:
                tets.append(idx[np.asarray(knoten, dtype=np.int64)].reshape(-1, 4))
    if not tets:
        raise RuntimeError("keine Tetraeder erzeugt")
    t = np.concatenate(tets)
    rand, flaeche = [], []
    for _, ft in gmsh.model.getEntities(2):
        et, _, en = gmsh.model.mesh.getElements(2, ft)
        for typ, knoten in zip(et, en):
            if int(typ) == 2:
                d = idx[np.asarray(knoten, dtype=np.int64)].reshape(-1, 3)
                rand.append(d)
                flaeche.append(np.full(len(d), ft, dtype=np.int64))
    used = np.unique(t)
    remap = np.full(len(xyz), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    r = np.concatenate(rand) if rand else np.zeros((0, 3), dtype=np.int64)
    fl = np.concatenate(flaeche) if flaeche else np.zeros(0, dtype=np.int64)
    ok = (remap[r] >= 0).all(axis=1) if len(r) else np.zeros(0, dtype=bool)
    return {"p": xyz[used], "t": remap[t], "rand": remap[r[ok]], "flaeche": fl[ok]}
