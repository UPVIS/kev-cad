"""Bauteil als Kragträger (S0, T-A): Hält ein Teil, das kein Stab ist (Halter, Konsole, Druckteil), seine Last?

Vereinfachung: Das Teil ist ein Kragträger von seiner Einspannung (Mitte der Berührung mit den Teilen, an denen es
hängt) bis zum Lastpunkt. An mehreren Schnitten quer zu dieser Linie schneidet Kev CAD das echte Teil (dünne Scheibe,
OCCT), nimmt Fläche und Flächenmomente des Schnitts und rechnet Normalspannung aus Biegung und Längskraft und
Schubspannung aus Torsion (von Mises). Die kleinste Sicherheit über die Schnitte zählt.

Druckteile: Die Spannung wirkt senkrecht zum Schnitt, also längs der Linie Einspannung → Last. Liegt diese Linie in
Aufbaurichtung (quer zu den Schichten), trägt das Teil nur den Anteil ``quer_zur_schicht`` (Katalog, PLA 0,5, PETG
0,4); dazwischen gleitend ``1 − (1 − q)·cos²``. Der Vorschlag nennt dann eine bessere Druckausrichtung und wie viel
höher der Querschnitt werden müsste.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kevcad_kernel.statik.modell import StatikModell
from kevcad_kernel.statik.szenario import Szenario

SCHNITTE = (0.06, 0.15, 0.3, 0.45, 0.6, 0.75)
DICKE = 0.05  # mm, Scheibe für den Schnitt
_SPEICHER: dict[tuple, list[dict[str, Any]]] = {}


def _schnitt(shape: Any, S: np.ndarray, e: np.ndarray, groesse: float) -> dict[str, Any] | None:
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.GProp import GProp_GProps
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    from kevcad_kernel.pruefung.kollision import schnittmenge, vernetzen

    u = np.cross(e, [0, 0, 1.0]) if abs(e[2]) < 0.9 else np.cross(e, [1.0, 0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(e, u)
    W = groesse
    o = S - u * W - v * W - e * DICKE / 2
    ax = gp_Ax2(gp_Pnt(*map(float, o)), gp_Dir(*map(float, e)), gp_Dir(*map(float, u)))
    box = BRepPrimAPI_MakeBox(ax, 2 * W, 2 * W, DICKE).Shape()
    com = schnittmenge(shape, box)
    if com is None:
        return None
    best = None
    ex = TopExp_Explorer(com, TopAbs_SOLID)
    while ex.More():
        sol = ex.Current()
        ex.Next()
        p = GProp_GProps()
        BRepGProp.VolumeProperties_s(sol, p)
        V = float(p.Mass())
        if V <= 1e-9:
            continue
        c = p.CentreOfMass()
        C = np.array([c.X(), c.Y(), c.Z()])
        d = float(np.linalg.norm(C - S))
        if best is None or d < best[0]:
            best = (d, sol, V, C, p.MatrixOfInertia())
    if best is None:
        return None
    _, sol, V, C, Mi = best
    J = np.array([[Mi.Value(i + 1, j + 1) for j in range(3)] for i in range(3)]) / DICKE
    try:
        pts = np.asarray(vernetzen(sol, 0.05)[0], dtype=float)
    except Exception:  # noqa: BLE001
        pts = np.zeros((0, 3))
    return {"A": V / DICKE, "C": C, "J": J, "punkte": pts}


def schnitte(k: Any, R: np.ndarray, P: np.ndarray) -> list[dict[str, Any]]:
    """Schnitte durch das Teil quer zur Linie R → P (zwischengespeichert je Form, Lage und Linie)."""
    key = (k.form, tuple(np.round(np.asarray(k.lage, dtype=float).reshape(-1), 4)), tuple(np.round(R, 2)),
           tuple(np.round(P, 2)))
    if key in _SPEICHER:
        return _SPEICHER[key]
    r = P - R
    L = float(np.linalg.norm(r))
    e = r / L
    groesse = float(np.max(np.asarray(k.bmax) - np.asarray(k.bmin))) + 10.0
    out = []
    for f in SCHNITTE:
        S = R + e * (f * L)
        s = _schnitt(k.shape, S, e, groesse)
        if s is not None:
            s["s"] = f * L
            out.append(s)
    if len(_SPEICHER) > 256:
        _SPEICHER.clear()
    _SPEICHER[key] = out
    return out


def einspannung(m: StatikModell, name: str, koerper: dict[str, Any]) -> np.ndarray | None:
    """Mitte der Berührung des Teils mit den Teilen, die es tragen (ohne Anbauteile; Verbindungselemente nur, wenn sonst
    nichts da ist)."""
    k = koerper[name]
    nach: list[tuple[bool, np.ndarray]] = []
    for e in m.kanten.values():
        if name not in (e["a"], e["b"]):
            continue
        x = e["b"] if e["a"] == name else e["a"]
        if x not in koerper:
            continue
        o = koerper[x]
        lo, hi = np.maximum(k.bmin, o.bmin), np.minimum(k.bmax, o.bmax)
        ve = x in m.teile and m.teile[x].verbindungselement
        nach.append((ve, (lo + hi) / 2))
    feste = [p for ve, p in nach if not ve] or [p for _, p in nach]
    if not feste:
        return None
    return np.mean(feste, axis=0)


def pruefe_last(m: StatikModell, sz: Szenario, koerper: dict[str, Any], name: str, F: np.ndarray,
                P: np.ndarray | None) -> dict[str, Any] | None:
    """Kragträger-Nachweis für ein Teil mit Last F (N) am Punkt P (mm, sonst Schwerpunkt)."""
    t = m.teile.get(name)
    k = koerper.get(name)
    if t is None or k is None or name in m.staebe:
        return None
    w = t.werkstoff
    if w is None or not w.grenze:
        return {"teil": name, "sicherheit": None, "text": f"{name}: Material ohne Festigkeitswerte im Katalog, "
                                                          "nicht nachgewiesen"}
    R = einspannung(m, name, koerper)
    if R is None:
        return None
    P = np.asarray(P if P is not None else t.schwerpunkt, dtype=float)
    r = P - R
    L = float(np.linalg.norm(r))
    if L < 5.0:
        return None
    e = r / L
    beste = None
    for s in schnitte(k, R, P):
        A, C, J, pts = s["A"], s["C"], s["J"], s["punkte"]
        if A <= 1e-6:
            continue
        M = np.cross(P - C, F)
        T = float(np.dot(M, e))
        Mb = M - e * T
        N = float(np.dot(F, e))
        sig = abs(N) / A
        mb = float(np.linalg.norm(Mb))
        if mb > 1e-9:
            mh = Mb / mb
            I_m = float(mh @ J @ mh)
            quer = np.cross(e, mh)
            c = float(np.max(np.abs((pts - C) @ quer))) if len(pts) else math.sqrt(A / math.pi)
            sig += mb * c / max(I_m, 1e-9)
        Ip = float(e @ J @ e)
        rmax = float(np.max(np.linalg.norm((pts - C) - np.outer((pts - C) @ e, e), axis=1))) if len(pts) else 0.0
        tau = abs(T) * rmax / max(Ip, 1e-9)
        sv = math.sqrt(sig * sig + 3 * tau * tau)
        if beste is None or sv > beste["spannung"]:
            beste = {"spannung": sv, "s": s["s"], "A": A, "C": C}
    if beste is None:
        return None
    faktor, quer_schicht = 1.0, False
    if t.druckteil:
        q = w.quer if w.quer else 0.5
        if t.druck_oben is not None:
            cz = float(np.dot(e, t.druck_oben))
            faktor = 1 - (1 - q) * cz * cz
            quer_schicht = abs(cz) > 0.7
        else:
            faktor, quer_schicht = q, True
    f_eff = float(w.grenze) * faktor
    sf = f_eff / beste["spannung"] if beste["spannung"] > 1e-12 else math.inf
    ziel = sz.ziel_fuer(t.druckteil)
    return {"teil": name, "sicherheit": round(sf, 3), "ziel": ziel, "spannung": round(beste["spannung"], 2),
            "grenze": round(f_eff, 2), "festigkeit": float(w.grenze), "schichtfaktor": round(faktor, 3),
            "quer_zur_schicht": quer_schicht, "druckteil": t.druckteil, "hebel_mm": round(L, 1),
            "schnitt_mm": round(beste["s"], 1), "schnitt_flaeche_mm2": round(beste["A"], 1),
            "einspannung": [round(float(c), 1) for c in R], "lastpunkt": [round(float(c), 1) for c in P],
            "richtung": [round(float(c), 3) for c in e], "werkstoff": w.id}


def vorschlag_druck(m: StatikModell, koerper: dict[str, Any], b: dict[str, Any]) -> str:
    """„drehen oder verstärken“ mit konkreter Ausrichtung (im System der Druckteil-Form) und Höhenzuwachs."""
    name = b["teil"]
    k = koerper.get(name)
    teile = []
    if b.get("quer_zur_schicht") and k is not None:
        e = np.asarray(b["richtung"], dtype=float)
        lage = np.asarray(k.lage, dtype=float).reshape(4, 4)
        rahmen = k.info.get("druck_rahmen")
        Rm = np.asarray(rahmen, dtype=float).reshape(4, 4)[:3, :3] if rahmen is not None else lage[:3, :3]
        e_lok = Rm @ (lage[:3, :3].T @ e)
        kand = []
        for ax, vec in (("-z", (0, 0, -1)), ("-y", (0, -1, 0)), ("-x", (-1, 0, 0)), ("+y", (0, 1, 0)),
                        ("+x", (1, 0, 0)), ("+z", (0, 0, 1))):
            kand.append((abs(float(np.dot(e_lok, vec))), ax))
        # bevorzugt flach (-z), dann auf die Seite; bei Gleichstand gilt diese Reihenfolge
        _, ax = kand[min(range(len(kand)), key=lambda i: (round(kand[i][0], 3), i))]
        teile.append(f"drehen: so drucken, dass die Schichten längs der Last liegen (z. B. lager.druckteil(…, "
                     f"ausrichtung=\"{ax}\"); dann trägt es etwa das {_de(1 / max(b['schichtfaktor'], 1e-3), 1)}-Fache)")
    sf, ziel = b.get("sicherheit") or 0.0, b.get("ziel") or 2.0
    if sf and sf < ziel:
        h = math.sqrt(ziel / sf) - 1
        teile.append(f"{'oder ' if teile else ''}verstärken: an der Einspannung (bei {_de(b['schnitt_mm'], 0)} mm) in "
                     f"Lastrichtung um etwa {_de(h * 100, 0)} % höher machen")
    text = "; ".join(teile)
    return text[:1].upper() + text[1:] if text else ""


def _de(x: float, n: int) -> str:
    from kevcad_kernel.bom import de_num

    return de_num(x, n)
