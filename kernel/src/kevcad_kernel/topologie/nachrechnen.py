"""Nachrechnen mit der Festkörper-FEM (Statik Stufe 3), vorher am Ausgangsteil und nachher am optimierten Körper.

Bausteine aus ``statik/festkoerper`` (nur genutzt, nicht verändert): Gmsh vernetzt das Ausgangsteil aus der BREP bzw.
den optimierten Körper aus seinem Oberflächennetz (diskrete Fläche, das Volumen wird mit genau diesen Dreiecken als Rand
vernetzt), ``loeser.Netz`` baut die P2-Steifigkeit, ``kontakt`` findet die Lagerflächen an den Nachbarn, ``werkstoff``
rechnet quer zur Schicht weicher und prüft die Schichtfuge, ``prozess._bewerten`` liefert Sicherheit, Ort und das Feld
für den Viewer wie beim Festkörper. Lasten wie dort: über die Kontaktfläche zum Nachbarn, am Punkt auf der Fläche um den
Punkt (beim optimierten Körper auf den Dreiecken, die auf der Lastfläche des Ausgangsteils liegen, damit beide gleich
belastet werden), ohne Punkt über das Volumen, dazu das Eigengewicht im Beschleunigungsfeld des Szenarios.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

LAST_TOL = 0.4  # mm (plus 0,15 Netzgrößen): Dreiecke des optimierten Körpers auf der Lastfläche des Ausgangsteils
MAX_TET = 8_000


def vernetze_oberflaeche(punkte: np.ndarray, dreiecke: np.ndarray, h: float, faeden: int = 4) -> dict[str, Any]:
    """Tetraeder (erster Ordnung) in einem geschlossenen Oberflächennetz; der Rand bleibt genau dieses Netz."""
    import gmsh

    t0 = time.perf_counter()
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", int(faeden))
        gmsh.model.add("optimiert")
        s = gmsh.model.addDiscreteEntity(2)
        n = len(punkte)
        gmsh.model.mesh.addNodes(2, s, list(range(1, n + 1)), np.asarray(punkte, float).reshape(-1).tolist())
        gmsh.model.mesh.addElementsByType(s, 2, [], (np.asarray(dreiecke, np.int64) + 1).reshape(-1).tolist())
        # Volumen über eine Flächenschleife aus der diskreten Fläche: Gmsh vernetzt es mit genau diesen Dreiecken als
        # Rand (ein diskretes Volumen gälte als schon vernetzt und bliebe leer)
        schleife = gmsh.model.geo.addSurfaceLoop([s])
        v = gmsh.model.geo.addVolume([schleife])
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(h))
        gmsh.option.setNumber("Mesh.MeshSizeMin", float(h) / 4)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)
        tags, xyz, _ = gmsh.model.mesh.getNodes()
        xyz = np.asarray(xyz, float).reshape(-1, 3)
        tags = np.asarray(tags, dtype=np.int64)
        idx = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
        idx[tags] = np.arange(len(tags))
        et, _, en = gmsh.model.mesh.getElements(3, v)
        t = None
        for typ, knoten in zip(et, en):
            if int(typ) == 4:
                t = idx[np.asarray(knoten, dtype=np.int64)].reshape(-1, 4)
        if t is None or len(t) == 0:
            raise RuntimeError("Gmsh hat keine Tetraeder erzeugt (Oberfläche nicht geschlossen?)")
        used = np.unique(t)
        remap = np.full(len(xyz), -1, dtype=np.int64)
        remap[used] = np.arange(len(used))
        return {"p": xyz[used], "t": remap[t], "h": float(h), "ms": round((time.perf_counter() - t0) * 1000, 1)}
    finally:
        gmsh.finalize()


def _flaeche(netz: tuple[np.ndarray, np.ndarray]) -> float:
    p, t = netz
    return float(0.5 * np.linalg.norm(np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]]), axis=1).sum())


def _flaechen_netz(N: Any, sel: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Randdreiecke ``sel`` als eigenes Netz (Punkte, Dreiecke) für den Abstand."""
    f = N.rand[sel]
    used, inv = np.unique(f.reshape(-1), return_inverse=True)
    return N.p[used], inv.reshape(-1, 3)


def rechne(N: Any, h: float, T: dict[str, Any], fall: dict[str, Any], nachbarn: dict[str, Any],
           lastflaechen_vorher: list[Any] | None = None, direkt: bool = False, zugabe: float = 0.0
           ) -> tuple[dict[str, Any], dict[str, np.ndarray], list[Any]]:
    """Ein Lastfall auf dem Netz ``N`` (``loeser.Netz``). ``T``: werkstoff, druckteil, schicht, masse_kg, volumen,
    bmin, bmax, ausrichtungen. ``lastflaechen_vorher``: je Last die Lastfläche des Ausgangsteils (Punkte, Dreiecke)
    oder None. Rückgabe: Kurzfassung, Felder (Oberfläche mit Ausnutzung), Lastflächen dieses Netzes."""
    from kevcad_kernel.statik.festkoerper import kontakt
    from kevcad_kernel.statik.festkoerper import werkstoff as wk
    from kevcad_kernel.statik.festkoerper.prozess import _bewerten, _lastflaeche

    t0 = time.perf_counter()
    w = T["werkstoff"]
    C = wk.steifigkeit(w["E"], w["nu"], w.get("E_z") if T["druckteil"] else None,
                       T.get("schicht") if T["druckteil"] else None)
    K = N.steifigkeit(C)
    t_k = (time.perf_counter() - t0) * 1000
    from kevcad_kernel.topologie.raster import naechstes_dreieck

    beruehrt: dict[str, np.ndarray] = {}
    for x, nb in nachbarn.items():
        with np.load(nb["datei"]) as z:
            # Toleranz wie beim Festkörper; das Netz des optimierten Körpers liegt bis etwa 0,2 mm neben der Fläche
            d, _ = naechstes_dreieck(N.rand_mitte, z["pos"], z["tri"], float(nb["tol"]) + zugabe)
        beruehrt[x] = np.where(np.isfinite(d))[0]
    lager = fall["lager"]
    fest = np.unique(np.concatenate([beruehrt.get(x, np.zeros(0, dtype=np.int64)) for x in lager])) if lager else \
        np.zeros(0, dtype=np.int64)
    if len(fest) == 0:
        raise ValueError(f"keine Lagerfläche zu {', '.join(lager)} gefunden")
    from kevcad_kernel.statik.festkoerper import loeser

    komp = loeser.komponenten(N.t, N.n)
    mit_lager = np.unique(komp[np.unique(N.rand[fest])])
    lose = ~np.isin(komp[N.t[:, 0]], mit_lager)
    fest_dofs = N.feste_dofs(fest)
    hinweise = []
    if lose.any():
        hinweise.append(f"{int(lose.sum())} Tetraeder ohne Verbindung zum Lager weggelassen")
        weg_knoten = np.unique(N.t[lose])
        weg_knoten = weg_knoten[~np.isin(weg_knoten, np.unique(N.t[~lose]))]
        fest_dofs = np.union1d(fest_dofs, N.basis.nodal_dofs[:, weg_knoten].reshape(-1))
        weg_kanten = np.unique(N.kante[:, lose])
        weg_kanten = weg_kanten[~np.isin(weg_kanten, np.unique(N.kante[:, ~lose]))]
        fest_dofs = np.union1d(fest_dofs, N.basis.edge_dofs[:, weg_kanten].reshape(-1))
    groesse = float(np.max(np.asarray(T["bmax"]) - np.asarray(T["bmin"])))
    V = float(N.vol.sum())
    lv = np.zeros(N.N)
    summe = np.zeros(3)
    flaechen: list[Any] = []
    for i, last in enumerate(fall["lasten"]):
        F = np.asarray(last["kraft"], float)
        M = np.asarray(last["moment"], float) if last.get("moment") is not None else None
        P = np.asarray(last["punkt"], float) if last.get("punkt") is not None else None
        summe += F
        sel = None
        if last.get("kontakt_mit"):
            sel = beruehrt.get(last["kontakt_mit"], np.zeros(0, dtype=np.int64))
        vorher = (lastflaechen_vorher or [None] * len(fall["lasten"]))[i] if lastflaechen_vorher else None
        if (sel is None or len(sel) == 0) and vorher is not None:
            d = kontakt.abstand(N.rand_mitte, vorher[0], vorher[1], LAST_TOL + 0.15 * h)
            sel = np.where(np.isfinite(d))[0]
        if (sel is None or len(sel) == 0) and P is not None:
            sel = _lastflaeche(N, P, groesse, h)
        if sel is not None and len(sel):
            lv += N.last_flaeche(sel, F, M, P)
            flaechen.append(_flaechen_netz(N, sel))
        else:
            lv += N.last_volumen(F / V)
            if M is not None and np.any(M):
                lv += N.last_flaeche(np.arange(len(N.rand)), np.zeros(3), M, None)
            flaechen.append(None)
    g = np.asarray(fall.get("feld") or (0, 0, 0), float) * (T["masse_kg"] / max(T["volumen"], 1e-9))
    lv += N.last_volumen(g)
    # Fachwerke aus dünnen Stegen: AMG kommt mit Tetraedern dort selten unter die Toleranz, SuperLU zerlegt bis
    # 150 000 Freiheitsgrade in wenigen Sekunden (wie beim Festkörper für dünne Teile)
    duenn = direkt or groesse / max(2.0 * V / max(float(N.rand_flaeche_mm2.sum()), 1e-9), 1e-9) > 25
    t1 = time.perf_counter()
    us, info = N.loese(K, fest_dofs, [lv], duenn=duenn)
    t_l = (time.perf_counter() - t1) * 1000
    fest_knoten = np.unique(N.rand[fest])
    kurz, felder = _bewerten(N, us[0], C, T, fall, fest_knoten)
    kurz.update({"lagerflaeche_mm2": round(float(N.rand_flaeche_mm2[fest].sum()), 1),
                 "lastflaechen_mm2": [round(_flaeche(f_), 1) if f_ is not None else None for f_ in flaechen],
                 "kraft_n": [round(float(c), 3) for c in summe], "hinweise": hinweise,
                 "netz": {"knoten": int(N.n), "tetraeder": int(len(N.t)), "freiheitsgrade": int(N.N),
                          "h_mm": round(float(h), 2)},
                 "loeser": {"verfahren": info["verfahren"][0], "iterationen": info["iterationen"][0]},
                 "volumen_mm3": round(V, 1),
                 "ms": {"steifigkeit": round(t_k, 1), "loesen": round(t_l, 1),
                        "gesamt": round((time.perf_counter() - t0) * 1000, 1)}})
    return kurz, felder, flaechen


def netzgroesse(volumen: float, flaeche: float, groesse: float, max_tet: int = MAX_TET) -> float:
    """Wie der Festkörper: mittlere Wandstärke 2 V / A, begrenzt über die Elementzahl."""
    from kevcad_kernel.statik.festkoerper.netz import TET_JE_H3

    wand = 2.0 * volumen / max(flaeche, 1e-9)
    h_min = (TET_JE_H3 * volumen / max_tet) ** (1 / 3)
    return float(min(max(wand, h_min), groesse / 6.0))


def kennzahlen(kurz: dict[str, Any], ziel: float) -> dict[str, Any]:
    sf = kurz.get("sicherheit")
    a = ziel / sf if sf else math.inf
    from kevcad_kernel.statik.bewertung import ampel_a

    return {"sicherheit": sf, "ziel": ziel, "ampel": ampel_a(a), "ausnutzung": round(a, 4) if math.isfinite(a) else None,
            "spannung_max": kurz.get("spannung_max"), "verformung_max_mm": kurz.get("verformung_max_mm"),
            "kriterium": kurz.get("kriterium"), "ort": kurz.get("ort"), "ausrichtungen": kurz.get("ausrichtungen")}
