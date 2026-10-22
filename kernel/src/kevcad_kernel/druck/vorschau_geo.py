"""Druckvorschau im Rechenprozess: Geometrie je Druckteil in Druckausrichtung (Prüfer „druckvorschau“).

Läuft direkt nach dem Prüfer „druck“ (druck/anbindung.py) und nimmt dessen Ausrichtung (``ausrichtung.drehung``).
Rechnet nur auf dem Netz, das der Lauf ohnehin hat (kein neues Vernetzen): Grundriss als konvexe Hülle, Hüllmaß,
Flächen nach Richtung (Seitenwände, Decken, Unterseiten, Auflage), mittlere Höhe der Überhänge. Das Ergebnis steht in
``ergebnis["druck"]["vorschau"]`` (CHECK-Kopf, Feld ``druck.vorschau``) und ist reines JSON. Daraus baut die Laufzeit
die Druckvorschau (``druck/vorschau.py``), ohne Formen anzufassen.

Bezugssystem je Teil: ``p_druck = matrix · (p_welt − t) − versatz``; Druckkoordinaten mit der Auflage bei z = 0 und der
Mitte des Hüllrechtecks bei x = y = 0, das Hüllrechteck achsparallel und die lange Seite in X.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from typing import Any

import numpy as np

from kevcad_kernel.pruefung.pruefer import PruefKontext, registriere

MAX_UMRISS = 64          # höchstens so viele Punkte im Umriss
ZWISCHENSPEICHER_MAX = 512
_SPEICHER: OrderedDict[tuple, dict[str, Any]] = OrderedDict()


def rot_xyz(winkel: Any) -> np.ndarray:
    """Drehmatrix für build123d ``Rot(x, y, z)`` (= Rx · Ry · Rz), Winkel in Grad."""
    ax, ay, az = (math.radians(float(w)) for w in winkel)
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rx @ ry @ rz


def rot_z(grad: float) -> np.ndarray:
    w = math.radians(grad)
    c, s = math.cos(w), math.sin(w)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def konvexe_huelle(xy: np.ndarray) -> np.ndarray:
    """Punkte der konvexen Hülle gegen den Uhrzeigersinn (Andrew, numpy)."""
    pts = np.unique(np.round(np.asarray(xy, dtype=np.float64).reshape(-1, 2), 4), axis=0)
    if len(pts) < 3:
        return pts
    try:
        from scipy.spatial import ConvexHull

        return pts[ConvexHull(pts).vertices]
    except Exception:  # noqa: BLE001 - entartete Punktmengen (alle auf einer Linie)
        pass

    def kreuz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    unten: list = []
    for p in pts:
        while len(unten) >= 2 and kreuz(unten[-2], unten[-1], p) <= 0:
            unten.pop()
        unten.append(p)
    oben: list = []
    for p in pts[::-1]:
        while len(oben) >= 2 and kreuz(oben[-2], oben[-1], p) <= 0:
            oben.pop()
        oben.append(p)
    return np.array(unten[:-1] + oben[:-1])


def flaeche_polygon(p: np.ndarray) -> float:
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def kleinstes_rechteck(huelle: np.ndarray) -> float:
    """Winkel (Grad), um den die Hülle gedreht werden muss, damit ihr Hüllrechteck am kleinsten ist (Kanten der Hülle
    durchprobieren); danach liegt die lange Seite in X."""
    if len(huelle) < 3:
        return 0.0
    kanten = np.roll(huelle, -1, axis=0) - huelle
    winkel = np.unique(np.round(np.degrees(np.arctan2(kanten[:, 1], kanten[:, 0])) % 90.0, 6))
    beste, bester = 0.0, None
    for w in np.concatenate([[0.0], winkel]):
        c, s = math.cos(math.radians(-w)), math.sin(math.radians(-w))
        u = huelle[:, 0] * c - huelle[:, 1] * s
        v = huelle[:, 0] * s + huelle[:, 1] * c
        a = (u.max() - u.min()) * (v.max() - v.min())
        if bester is None or a < bester - 1e-6:
            beste, bester = float(-w), a
    c, s = math.cos(math.radians(beste)), math.sin(math.radians(beste))
    u = huelle[:, 0] * c - huelle[:, 1] * s
    v = huelle[:, 0] * s + huelle[:, 1] * c
    if (v.max() - v.min()) > (u.max() - u.min()) + 1e-6:
        beste += 90.0
    return ((beste + 180.0) % 360.0) - 180.0


def vereinfachen(huelle: np.ndarray, n: int = MAX_UMRISS) -> np.ndarray:
    """Konvexe Hülle auf höchstens n Punkte (Visvalingam: kleinste Dreiecke zuerst weg)."""
    p = [tuple(x) for x in huelle]
    while len(p) > n:
        m = len(p)
        flaechen = [abs((p[i][0] - p[i - 1][0]) * (p[(i + 1) % m][1] - p[i - 1][1])
                        - (p[(i + 1) % m][0] - p[i - 1][0]) * (p[i][1] - p[i - 1][1])) for i in range(m)]
        del p[int(np.argmin(flaechen))]
    return np.array(p)


def _form_geometrie(pos: np.ndarray, tri: np.ndarray, B0: np.ndarray, ueberhang_max: float,
                    erste_schicht: float) -> dict[str, Any]:
    """Kennzahlen eines Teils aus dem Netz in Formkoordinaten (``pos`` schon ohne Lage, ``B0`` = Form → Druck)."""
    P = pos @ B0.T
    huelle0 = konvexe_huelle(P[:, :2])
    dreh = kleinstes_rechteck(huelle0)
    Rz = rot_z(dreh)
    B = Rz @ B0
    P = pos @ B.T
    zmin = float(P[:, 2].min())
    huelle = konvexe_huelle(P[:, :2])
    lo, hi = P[:, :2].min(axis=0), P[:, :2].max(axis=0)
    mitte = (lo + hi) / 2
    versatz = np.array([mitte[0], mitte[1], zmin])
    P = P - versatz
    huelle = huelle - mitte
    # Flächen nach Richtung
    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    n = np.cross(b - a, c - a)
    dop = np.linalg.norm(n, axis=1)
    ok = dop > 1e-12
    flaeche = dop / 2
    nz = np.zeros(len(tri))
    nz[ok] = n[ok, 2] / dop[ok]
    zc = (a[:, 2] + b[:, 2] + c[:, 2]) / 3
    zmax_tri = np.maximum(np.maximum(a[:, 2], b[:, 2]), c[:, 2])
    seite = float((flaeche * np.sqrt(np.clip(1 - nz * nz, 0, 1))).sum())
    oben = float((flaeche * nz)[nz > 0.7].sum())
    unten_m = nz < -0.7
    bett = (nz < -0.9995) & (zmax_tri < 0.02)
    unten = float((flaeche * -nz)[unten_m & ~bett].sum())
    auflage = float(flaeche[bett].sum())
    grenze = math.sin(math.radians(min(ueberhang_max + 0.5, 89.9)))
    ueber = (-nz > grenze) & (zc > erste_schicht) & ~bett
    gew = (flaeche * -nz)[ueber]
    ueberhang_flaeche = float(gew.sum())
    ueberhang_hoehe = float((gew * zc[ueber]).sum() / gew.sum()) if gew.sum() > 1e-9 else 0.0
    # Seitenfläche je Höhe (für die Mindestschichtzeit): 20 Bänder; ein Dreieck verteilt sich über seine Höhe
    hoehe = float(P[:, 2].max())
    baender = 20
    if hoehe > 1e-6:
        zmin_tri = np.minimum(np.minimum(a[:, 2], b[:, 2]), c[:, 2])
        grenzen = np.linspace(0.0, hoehe, baender + 1)
        spanne = zmax_tri - zmin_tri
        flach = spanne < 1e-6
        ueber = np.clip(np.minimum(zmax_tri[:, None], grenzen[None, 1:]) - np.maximum(zmin_tri[:, None],
                                                                                   grenzen[None, :-1]), 0, None)
        anteil = np.where(flach[:, None], 0.0, ueber / np.where(flach, 1.0, spanne)[:, None])
        idx = np.clip((zc / hoehe * baender).astype(int), 0, baender - 1)
        anteil[flach, idx[flach]] = 1.0
        seite_band = (anteil * (flaeche * np.sqrt(np.clip(1 - nz * nz, 0, 1)))[:, None]).sum(axis=0)
        waag_band = (anteil * (flaeche * np.abs(nz) * (np.abs(nz) > 0.7))[:, None]).sum(axis=0)
    else:
        seite_band = np.zeros(baender)
        waag_band = np.zeros(baender)
    umriss = vereinfachen(huelle)
    from kevcad_kernel.druck.signatur import mit_deckung

    sig, deckung = mit_deckung(P, tri, [float(x) for x in (hi - lo).tolist() + [hoehe]])
    return {
        "signatur": sig, "_deckung": deckung,
        "B": B, "versatz": versatz, "drehung_z": round(dreh, 4),
        "groesse": [round(float(x), 3) for x in (hi - lo).tolist() + [hoehe]],
        "umriss": [[round(float(x), 3), round(float(y), 3)] for x, y in umriss],
        "umriss_flaeche": round(flaeche_polygon(huelle), 2),
        "umriss_umfang": round(float(np.linalg.norm(np.roll(huelle, -1, axis=0) - huelle, axis=1).sum()), 2),
        "oberflaeche": round(float(flaeche.sum()), 2), "seite": round(seite, 2), "oben": round(oben, 2),
        "unten": round(unten, 2), "auflage": round(auflage, 2),
        "ueberhang_flaeche": round(ueberhang_flaeche, 2), "ueberhang_hoehe": round(ueberhang_hoehe, 3),
        "seite_baender": [round(float(x), 2) for x in seite_band],
        "waag_baender": [round(float(x), 2) for x in waag_band],
    }


def geometrie(k: Any, teil: dict[str, Any], formen: dict[str, Any] | None = None,
              deckung: dict[str, Any] | None = None) -> dict[str, Any]:
    """Druckvorschau-Geometrie eines Körpers (``pruefung.koerper.Koerper``) mit dem Ergebnis der Druckprüfung
    (``ergebnis["druck"]["teile"][name]``). Mit ``formen`` stehen die Kennzahlen der Form einmal je Form dort
    (Schlüssel ``fid``), im Ergebnis nur Lage und Angaben des Teils; ohne ``formen`` alles im Ergebnis."""
    import hashlib

    from kevcad_kernel.druck.regeln import P1P, material as material_fuer

    a = teil.get("ausrichtung") or {}
    M = rot_xyz(a.get("drehung") or [0, 0, 0])
    rahmen = k.info.get("druck_rahmen")
    lage = np.asarray(k.lage, dtype=np.float64).reshape(4, 4)
    R = np.asarray(rahmen, dtype=np.float64).reshape(4, 4)[:3, :3] if rahmen is not None else lage[:3, :3]
    L3, t = lage[:3, :3], lage[:3, 3]
    mid = str(teil.get("material") or k.info.get("druck_material") or "pla")
    try:
        mat = material_fuer(mid)
        ueberhang = min(mat.ueberhang_max, P1P.ueberhang_grenze)
    except ValueError:
        ueberhang = P1P.ueberhang_grenze
    schluessel = (k.form, tuple(np.round(R, 9).ravel()), tuple(np.round(M, 9).ravel()), round(ueberhang, 3))
    form = _SPEICHER.get(schluessel)
    aus_speicher = form is not None
    if form is None:
        q = (np.asarray(k.pos, dtype=np.float64) - t) @ L3   # Netz ohne Lage (Form)
        form = _form_geometrie(q, np.asarray(k.tri, dtype=np.int64), M @ R, ueberhang, P1P.erste_schicht)
        _SPEICHER[schluessel] = form
        while len(_SPEICHER) > ZWISCHENSPEICHER_MAX:
            _SPEICHER.popitem(last=False)
    else:
        _SPEICHER.move_to_end(schluessel)
    A = form["B"] @ L3.T   # Welt (ohne Verschiebung) → Druck
    kz = teil.get("kennzahlen") or {}
    fid = hashlib.sha1(repr(schluessel).encode()).hexdigest()[:12]
    kennzahlen = {k_: v for k_, v in form.items() if k_ not in ("B", "versatz", "_deckung")}
    if deckung is not None and form.get("_deckung") is not None:
        deckung.setdefault(fid, form["_deckung"])
    kennzahlen["form_matrix"] = [[round(float(x), 9) + 0.0 for x in row] for row in form["B"]]
    kennzahlen["form"] = k.form
    if formen is not None:
        formen.setdefault(fid, kennzahlen)
        out: dict[str, Any] = {"fid": fid}
    else:
        out = {"fid": fid, **kennzahlen}
    out.update({
        "matrix": [[round(float(x), 9) + 0.0 for x in row] for row in A],
        "t": [round(float(x), 6) for x in t],
        "versatz": [round(float(x), 6) for x in form["versatz"]],
        "volumen": round(float(k.volumen), 3),
        "material": mid,
        "stueck": int(k.info.get("druck_stueck") or 0),
        "zweck": k.info.get("druck_zweck"),
        "anzahl": k.info.get("druck_anzahl"),
        "stuetzflaeche": float(kz.get("stuetzflaeche_mm2") or 0.0),
        "auflage_pruefung": float(kz.get("auflageflaeche_mm2") or 0.0),
        "ausrichtung_text": a.get("text"),
        "liegt_auf": a.get("liegt_auf"),
        "zwischenspeicher": aus_speicher,
    })
    return out


def pruefe(ctx: PruefKontext) -> list[dict[str, Any]]:
    """Prüffunktion „druckvorschau“: keine Befunde, nur ``ergebnis["druck"]["vorschau"]``."""
    druck = ctx.ergebnis.get("druck")
    if not druck or not druck.get("teile"):
        return []
    t0 = time.perf_counter()
    geo: dict[str, Any] = {}
    formen: dict[str, Any] = {}
    fehler: dict[str, str] = {}
    deckung: dict[str, Any] = {}
    for name, teil in (druck.get("teile") or {}).items():
        k = ctx.koerper.get(name)
        if k is None:
            continue
        ctx.abbrechen()
        try:
            geo[name] = geometrie(k, teil, formen, deckung)
        except Exception as exc:  # noqa: BLE001 - ein Teil darf die Vorschau der übrigen nicht verhindern
            fehler[name] = f"{type(exc).__name__}: {exc}"
    try:
        gleichteile(formen, deckung, ctx.abbrechen)
    except Exception as exc:  # noqa: BLE001 - ohne Gleichteile gruppiert die Vorschau nach der Signatur
        fehler["(gleichteile)"] = f"{type(exc).__name__}: {exc}"
    ms = (time.perf_counter() - t0) * 1000
    ctx.zeiten["druckvorschau"] = ms
    druck["vorschau"] = {"teile": geo, "formen": formen, "fehler": fehler, "ms": round(ms, 1)}
    return []


_KLASSEN_SPEICHER: OrderedDict[tuple[str, str], str | None] = OrderedDict()


def gleichteile(formen: dict[str, Any], deckung: dict[str, Any], abbrechen: Any = None) -> None:
    """Gleiche Teile über Formschlüssel hinweg (Strang „Feinschliff 2“, Punkt 3): Formen mit gleicher Signatur werden
    genau verglichen (``signatur.deckung``); je Form steht danach ``gleichteil: {"fid", "gespiegelt"}`` mit der ersten
    Form ihrer Klasse. Drehsymmetrische Formen (Achsen nicht fest) gelten bei gleicher Signatur als gleich."""
    from kevcad_kernel.druck import signatur as sg

    vertreter: list[str] = []
    for fid, f in formen.items():
        if abbrechen is not None:
            abbrechen()
        sig = f.get("signatur")
        f["gleichteil"] = {"fid": fid, "gespiegelt": False}
        if not isinstance(sig, dict):
            continue
        for rep in vertreter:
            s_rep = formen[rep].get("signatur")
            if not sg.gleich_skalar(s_rep, sig):
                continue
            if sig.get("e") or s_rep.get("e") or fid not in deckung or rep not in deckung:
                urteil: str | None = "gleich"
            else:
                key = (rep, fid)
                if key in _KLASSEN_SPEICHER:
                    urteil = _KLASSEN_SPEICHER[key]
                    _KLASSEN_SPEICHER.move_to_end(key)
                else:
                    urteil = sg.deckung(deckung[rep], deckung[fid])
                    _KLASSEN_SPEICHER[key] = urteil
                    while len(_KLASSEN_SPEICHER) > ZWISCHENSPEICHER_MAX:
                        _KLASSEN_SPEICHER.popitem(last=False)
            if urteil is not None:
                f["gleichteil"] = {"fid": rep, "gespiegelt": urteil == "gespiegelt"}
                break
        if f["gleichteil"]["fid"] == fid:
            vertreter.append(fid)


def teil_mit_form(vorschau: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Angaben eines Teils samt den Kennzahlen seiner Form (aus ``druck.vorschau`` im CHECK)."""
    t = (vorschau.get("teile") or {}).get(name)
    if t is None:
        return None
    f = (vorschau.get("formen") or {}).get(t.get("fid")) or {}
    return {**f, **t}


registriere("druckvorschau", pruefe, nach="druck")
