"""Automatische Druckprüfung für 3D-Druckteile (FDM auf dem Bambu Lab P1P).

``pruefe_druckteil(form, material="petg", ausrichtung=None)`` legt das Teil (auf Wunsch automatisch) aufs Bett und
prüft Bauraum, Auflage, Überhänge, Brücken, freie Unterseiten, Gegenbohrungen zur Bettseite, waagrechte und kleine
Bohrungen, dünne Stifte, Wandstärken, Bettkanten (Elefantenfuß, Rundungen unten), Verzug und das Schichtraster.

Alle Flächennummern beziehen sich auf ``form.faces()`` der übergebenen Form, alle Punkte auf ihre Modellkoordinaten
(so wie der Viewer das Teil zeigt). Die Ausrichtung ist die Drehung, mit der das Teil auf dem Bett liegt:
``Rot(*ergebnis["ausrichtung"]["drehung"]) * form``.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from kevcad_kernel.druck.netz import Netz, baue_netz
from kevcad_kernel.druck.regeln import (
    FESTIGKEIT,
    P1P,
    Drucker,
    Material,
    Schwellen,
    bohrung_zugabe,
    material as material_fuer,
    schwellen as schwellen_fuer,
)

SCHWEREN = ("fehler", "warnung", "hinweis")
_RANG = {s: i for i, s in enumerate(SCHWEREN)}

_BETT_TOL = 0.02          # mm: Dreieck liegt auf dem Bett
_WAAGRECHT = 0.9995       # |n·oben| für waagrechte Ebenen (≈ 1,8°)
_WINKEL_TOL = 0.5        # Grad Toleranz auf die Überhanggrenze (genau 60° bei PLA ist noch gut)
# Durchgangs- (ISO 273 mittel) und Senkungsmaße (ISO 4762) mit glattem Wert: haben ihr Spiel schon
_TABELLENMASSE = (4.5, 5.5, 9.0, 11.0, 13.5, 17.5, 6.5, 15.0, 18.0)
_ACHSEN = {
    "-z": (0, 0, -1), "z": (0, 0, 1), "+z": (0, 0, 1), "-x": (-1, 0, 0), "x": (1, 0, 0), "+x": (1, 0, 0),
    "-y": (0, -1, 0), "y": (0, 1, 0), "+y": (0, 1, 0), "modell": (0, 0, -1), "wie modelliert": (0, 0, -1),
}


# ---------------------------------------------------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------------------------------------------------


def _z(x: float, nd: int = 1) -> str:
    """Zahl mit deutschem Komma."""
    s = f"{x:.{nd}f}"
    if s.startswith("-") and float(s) == 0:
        s = s[1:]
    return s.replace(".", ",")


def _p(v) -> list[float]:
    return [round(float(c), 3) + 0.0 for c in v]


def _hinweis(art: str, schwere: str, befund: str, abhilfe: str, flaeche: int | None = None,
             flaechen: list[int] | None = None, punkt=None, **werte) -> dict:
    fl = sorted({int(f) for f in (flaechen or ([] if flaeche is None else [flaeche]))})
    if flaeche is None and fl:
        flaeche = fl[0]
    return {
        "art": art,
        "schwere": schwere,
        "text": f"{befund}. Abhilfe: {abhilfe}.",
        "befund": befund,
        "abhilfe": abhilfe,
        "flaeche": None if flaeche is None else int(flaeche),
        "flaechen": fl,
        "punkt": None if punkt is None else _p(punkt),
        "werte": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in werte.items()},
    }


def _drehung_zu_unten(unten: np.ndarray) -> np.ndarray:
    """Drehmatrix R (Modell → Druck), die ``unten`` auf −Z legt (kürzeste Drehung)."""
    a = unten / np.linalg.norm(unten)
    b = np.array([0.0, 0.0, -1.0])
    c = float(a @ b)
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        return np.diag([1.0, -1.0, -1.0])
    v = np.cross(a, b)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def _euler_xyz(R: np.ndarray) -> list[float]:
    """Winkel für build123d ``Rot(x, y, z)`` (= Rx · Ry · Rz) aus der Drehmatrix."""
    ry = math.asin(max(-1.0, min(1.0, R[0, 2])))
    if abs(math.cos(ry)) > 1e-9:
        rx = math.atan2(-R[1, 2], R[2, 2])
        rz = math.atan2(-R[0, 1], R[0, 0])
    else:
        rz = 0.0
        rx = math.atan2(R[2, 1], R[1, 1])
    return [round(math.degrees(w), 4) + 0.0 for w in (rx, ry, rz)]


def _richtung_text(unten: np.ndarray) -> str:
    for name, v in (("−Z", (0, 0, -1)), ("+Z", (0, 0, 1)), ("−X", (-1, 0, 0)), ("+X", (1, 0, 0)),
                    ("−Y", (0, -1, 0)), ("+Y", (0, 1, 0))):
        if float(np.dot(unten, v)) > 0.9999:
            return f"{name}-Seite unten"
    return f"Richtung ({_z(unten[0], 2)}; {_z(unten[1], 2)}; {_z(unten[2], 2)}) unten"


def _rechteck_2d(xy: np.ndarray, schritt: float = 1.0) -> tuple[float, float, float]:
    """Kleinstes umschließendes Rechteck über Drehungen 0–90°: (Seite a ≥ b, b, Winkel)."""
    if len(xy) == 0:
        return 0.0, 0.0, 0.0
    if len(xy) > 4000:
        xy = xy[np.linspace(0, len(xy) - 1, 4000).astype(int)]
    w = np.radians(np.arange(0.0, 90.0, schritt))
    c, s = np.cos(w), np.sin(w)
    u = xy[:, :1] * c + xy[:, 1:2] * s
    v = -xy[:, :1] * s + xy[:, 1:2] * c
    du = u.max(0) - u.min(0)
    dv = v.max(0) - v.min(0)
    i = int(np.argmin(du * dv))
    a, b = float(du[i]), float(dv[i])
    return max(a, b), min(a, b), float(np.degrees(w[i]))


# ---------------------------------------------------------------------------------------------------------------------
# Geometrie-Gruppen (Bohrungen, Stifte, Decken)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Rund:
    flaechen: list[int]
    radius: float
    achse: np.ndarray
    punkt: np.ndarray
    winkel: float
    hohl: bool

    @property
    def d(self) -> float:
        return 2 * self.radius


def _rundungen(netz: Netz) -> list[_Rund]:
    """Zylinderflächen gleicher Achse und gleichen Radius zusammenfassen (Bohrungen sind oft in zwei Hälften)."""
    gruppen: list[_Rund] = []
    for info in netz.infos:
        z = info.zylinder
        if z is None:
            continue
        for g in gruppen:
            if (g.hohl == z.hohl and abs(g.radius - z.radius) < 1e-3 and abs(float(g.achse @ z.achse)) > 0.9999):
                q = z.punkt - g.punkt
                if np.linalg.norm(q - g.achse * float(q @ g.achse)) < 1e-3:
                    g.flaechen.append(info.index)
                    g.winkel += z.winkel
                    break
        else:
            gruppen.append(_Rund([info.index], z.radius, z.achse.copy(), z.punkt.copy(), z.winkel, z.hohl))
    return gruppen


def _umfang(netz: Netz, f: int) -> float:
    return sum(k.laenge for k in netz.kanten if f in k.flaechen)


# ---------------------------------------------------------------------------------------------------------------------
# Lage auf dem Bett
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Lage:
    netz: Netz
    unten: np.ndarray
    oben: np.ndarray
    R: np.ndarray
    hV: np.ndarray          # Höhe der Knoten über dem Bett
    hT: np.ndarray          # (m×3) Höhe der Dreiecksecken
    nz: np.ndarray          # n·oben je Dreieck
    bett: np.ndarray        # Dreieck liegt auf dem Bett
    hoehe: float
    auflage: float
    bett_flaechen: list[int] = field(default_factory=list)


def _lage(netz: Netz, unten: np.ndarray) -> _Lage:
    unten = np.asarray(unten, dtype=float)
    unten = unten / np.linalg.norm(unten)
    oben = -unten
    h = netz.V @ oben
    h0 = float(h.min())
    hV = h - h0
    hT = hV[netz.T]
    nz = netz.tri_n @ oben
    eben = np.array([i.typ == "ebene" for i in netz.infos], dtype=bool)
    # nur ebene Flächen zählen als Auflage (eine Facette eines liegenden Zylinders ist ein Netz-Artefakt)
    bett = (nz < -_WAAGRECHT) & (hT.max(axis=1) < _BETT_TOL) & eben[netz.tri_face]
    lage = _Lage(netz, unten, oben, _drehung_zu_unten(unten), hV, hT, nz, bett, float(hV.max()),
                 float(netz.tri_a[bett].sum()))
    if bett.any():
        fl = np.unique(netz.tri_face[bett])
        lage.bett_flaechen = [int(f) for f in fl if netz.infos[f].typ == "ebene"]
    return lage


def _ausdehnung(xy: np.ndarray, schritt: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Breite und Tiefe des Grundrisses für Drehungen um Z von 0 bis < 90° (Winkel in Grad)."""
    if len(xy) > 4000:
        xy = xy[np.linspace(0, len(xy) - 1, 4000).astype(int)]
    w = np.arange(0.0, 90.0, schritt)
    c, s = np.cos(np.radians(w)), np.sin(np.radians(w))
    u = xy[:, :1] * c + xy[:, 1:2] * s
    v = -xy[:, :1] * s + xy[:, 1:2] * c
    return u.max(0) - u.min(0), v.max(0) - v.min(0), w


def _bauraum(netz: Netz, lage: _Lage, drucker: Drucker, schritt: float = 1.0) -> dict:
    """Passt das Teil in dieser Lage aufs Bett – gerade, mit Rand, notfalls um Z gedreht?"""
    P = netz.V @ lage.R.T
    du, dv, w = _ausdehnung(P[:, :2], schritt)
    bx, by, bz = drucker.bauraum
    r = drucker.rand
    z_ok = lage.hoehe <= bz + 1e-6

    sx, sy = drucker.sperrflaeche

    def passt(rand):   # je Winkel, beide Bettlagen (Breite auf X oder auf Y), Sperrbereich in einer Ecke frei
        ok = np.zeros_like(du, dtype=bool)
        for w_, h_ in ((du, dv), (dv, du)):
            innen = (w_ <= bx - 2 * rand + 1e-6) & (h_ <= by - 2 * rand + 1e-6)
            frei = (w_ <= bx - sx - 2 * rand + 1e-6) | (h_ <= by - sy - 2 * rand + 1e-6)
            ok |= innen & frei
        return z_ok & ok

    ok, ok_rand = passt(0.0), passt(r)
    if ok_rand.any():
        i = 0 if ok_rand[0] else int(np.flatnonzero(ok_rand)[np.argmin(np.maximum(du, dv)[ok_rand])])
    elif ok.any():
        i = 0 if ok[0] else int(np.flatnonzero(ok)[np.argmin(np.maximum(du, dv)[ok])])
    else:
        i = int(np.argmin(np.maximum(du, dv)))
    return {
        "x": float(du[0]), "y": float(dv[0]), "z": lage.hoehe,
        "a": float(max(du[i], dv[i])), "b": float(min(du[i], dv[i])), "winkel": float(w[i]),
        "passt_gerade": bool(ok[0]), "passt_gerade_rand": bool(ok_rand[0]),
        "passt": bool(ok.any()), "passt_rand": bool(ok_rand.any()), "z_ok": z_ok,
    }


# ---------------------------------------------------------------------------------------------------------------------
# Automatische Ausrichtung
# ---------------------------------------------------------------------------------------------------------------------


def _kandidaten(netz: Netz, anzahl_flaechen: int = 8) -> list[np.ndarray]:
    dirs = [np.array(v, dtype=float) for v in ((0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))]
    ebenen = sorted((i for i in netz.infos if i.typ == "ebene" and i.normale is not None), key=lambda i: -i.flaeche)
    for info in ebenen[:anzahl_flaechen]:
        n = info.normale / np.linalg.norm(info.normale)
        dirs.append(n)
    out: list[np.ndarray] = []
    for d in dirs:
        if all(float(d @ o) < 0.999 for o in out):
            out.append(d)
    return out


def _bewerte(netz: Netz, unten: np.ndarray, mat: Material, drucker: Drucker, rund: list[_Rund],
             decken_dh: dict[int, float]) -> dict:
    lage = _lage(netz, unten)
    s = -lage.nz
    grenze = math.sin(math.radians(min(mat.ueberhang_max + _WINKEL_TOL, 89.9)))
    ueber = (s > grenze) & (lage.hT.mean(axis=1) > drucker.erste_schicht) & ~lage.bett
    # kurze Brücken (waagrechte Decken mit kleinem hydraulischem Durchmesser) brauchen keine Stütze
    for f, dh in decken_dh.items():
        info = netz.infos[f]
        if dh <= mat.bruecke_gut and float(info.normale @ lage.oben) < -_WAAGRECHT:
            ueber &= netz.tri_face != f
    stuetz = float((netz.tri_a * s)[ueber].sum())
    f_ueber = np.bincount(netz.tri_face[ueber], minlength=netz.flaechenzahl) > 0
    bohr = [g for g in rund if g.hohl and g.winkel >= 180]
    waagrecht = [g for g in bohr if abs(float(g.achse @ lage.oben)) < 0.1 and f_ueber[g.flaechen].any()]
    br = _bauraum(netz, lage, drucker, schritt=5.0)
    return {"unten": unten, "lage": lage, "stuetz": stuetz, "auflage": lage.auflage, "hoehe": lage.hoehe,
            "waagrechte_bohrungen": len(waagrecht), "bohrungen": len(bohr), "passt": br["passt"],
            "passt_rand": br["passt_rand"]}


def _waehle(bewertungen: list[dict], netz: Netz, sw: Schwellen) -> list[dict]:
    gesamt = float(netz.tri_a.sum())
    s_max = max(b["stuetz"] for b in bewertungen)
    a_max = max(b["auflage"] for b in bewertungen) or 1.0
    h_max = max(b["hoehe"] for b in bewertungen) or 1.0
    for i, b in enumerate(bewertungen):
        p = 1.0 * b["stuetz"] / (s_max + 0.02 * gesamt + 1.0)
        p += 0.6 * (1 - b["auflage"] / a_max)
        p += 0.25 * b["hoehe"] / h_max
        p += 0.3 * (b["waagrechte_bohrungen"] / b["bohrungen"] if b["bohrungen"] else 0.0)
        p += 0.5 if b["auflage"] < sw.auflage_min else 0.0
        p += 0.0 if b["passt"] else 10.0
        p += 0.0 if (b["passt_rand"] or not b["passt"]) else 1.0
        p -= 0.05 if i == 0 else 0.0     # wie modelliert bevorzugen, wenn es (fast) gleich gut ist
        b["punkte"] = p
    return sorted(bewertungen, key=lambda b: b["punkte"])


# ---------------------------------------------------------------------------------------------------------------------
# Wandstärke: Strahlen von der Oberfläche ins Innere (vektorisiert auf dem Netz)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Strahlen:
    P: np.ndarray       # Startpunkte auf der Oberfläche
    N: np.ndarray       # Außennormale
    F: np.ndarray       # Fläche des Startpunkts
    t: np.ndarray       # Wanddicke entlang −N (inf: dicker als die Reichweite)
    Fh: np.ndarray      # getroffene Fläche (−1: keine)
    a_s: float          # Oberfläche je Stichprobe (mm²)


def _strahlen(netz: Netz, reichweite: float, ziel: int = 4000, seed: int = 7) -> _Strahlen:
    A = netz.tri_a
    gesamt = float(A.sum())
    a_s = max(gesamt / ziel, 1e-3)
    rng = np.random.default_rng(seed)
    k = np.floor(A / a_s + rng.random(len(A))).astype(np.int64)
    idx = np.repeat(np.arange(len(A)), k)
    if len(idx) > 2 * ziel:
        idx = rng.choice(idx, 2 * ziel, replace=False)
    r1, r2 = rng.random(len(idx)), rng.random(len(idx))
    sq = np.sqrt(r1)
    ta, tb, tc = netz.tri_ecken()
    P = ((1 - sq)[:, None] * ta[idx] + (sq * (1 - r2))[:, None] * tb[idx] + (sq * r2)[:, None] * tc[idx])
    N = netz.tri_n[idx]
    F = netz.tri_face[idx]
    D = -N
    O = P + D * 1e-4
    t_best = np.full(len(idx), np.inf)
    f_best = np.full(len(idx), -1, dtype=np.int64)
    if len(idx) == 0:
        return _Strahlen(P, N, F, t_best, f_best, a_s)

    E1, E2 = tb - ta, tc - ta
    tmin = np.minimum(np.minimum(ta, tb), tc)
    tmax = np.maximum(np.maximum(ta, tb), tc)
    # Nur die gegenüberliegende, nahezu parallele Fläche zählt als Wandrückseite (≤ 20° Keilwinkel). So melden
    # spitz zulaufende Kanten (Fasen, Keile, Rundungsauslauf) keine dünne Wand, echte Wände und Klingen aber schon.
    parallel = math.cos(math.radians(20))

    zelle = max(2 * reichweite, netz.diag / 16)
    g = np.floor((O - O.min(axis=0)) / zelle).astype(np.int64)
    key = (g[:, 0] * 100003 + g[:, 1]) * 100003 + g[:, 2]
    order = np.argsort(key, kind="stable")
    grenzen = np.flatnonzero(np.diff(key[order])) + 1
    for gruppe in np.split(order, grenzen):
        lo = O[gruppe].min(axis=0) - reichweite
        hi = O[gruppe].max(axis=0) + reichweite
        cand = np.flatnonzero((tmax >= lo).all(axis=1) & (tmin <= hi).all(axis=1))
        if len(cand) == 0:
            continue
        e1, e2, a0, nc, fc = E1[cand], E2[cand], ta[cand], netz.tri_n[cand], netz.tri_face[cand]
        stueck = max(1, int(2e5 // len(cand)))
        for j in range(0, len(gruppe), stueck):
            sub = gruppe[j:j + stueck]
            d, o = D[sub], O[sub]
            pvec = np.cross(d[:, None, :], e2[None, :, :])
            det = np.einsum("sck,ck->sc", pvec, e1)
            ok = np.abs(det) > 1e-14
            inv = 1.0 / np.where(ok, det, 1.0)
            tvec = o[:, None, :] - a0[None, :, :]
            u = np.einsum("sck,sck->sc", tvec, pvec) * inv
            qvec = np.cross(tvec, e1[None, :, :])
            v = np.einsum("sck,sk->sc", qvec, d) * inv
            t = np.einsum("sck,ck->sc", qvec, e2) * inv
            # Strahl verlässt das Material durch eine Fläche, deren Außennormale fast in Strahlrichtung zeigt
            raus = (d @ nc.T) > parallel
            treffer = ok & raus & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7) & (t > 1e-3) & (t <= reichweite)
            tt = np.where(treffer, t, np.inf)
            jj = np.argmin(tt, axis=1)
            tb_ = tt[np.arange(len(sub)), jj]
            besser = tb_ < t_best[sub]
            t_best[sub[besser]] = tb_[besser]
            f_best[sub[besser]] = fc[jj[besser]]
    return _Strahlen(P, N, F, t_best, f_best, a_s)


# ---------------------------------------------------------------------------------------------------------------------
# Einzelprüfungen
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Ctx:
    netz: Netz
    mat: Material
    dr: Drucker
    sw: Schwellen
    lage: _Lage
    rund: list[_Rund]
    grenze: float                                   # Überhanggrenze (Grad)
    hinweise: list[dict] = field(default_factory=list)
    erledigt: set[int] = field(default_factory=set)  # Flächen, die eine eigene Meldung bekommen haben
    stuetz: float = 0.0                              # Stützfläche (projiziert, mm²)


def _pruefe_bauraum(c: _Ctx, alle: list[dict] | None) -> dict:
    br = _bauraum(c.netz, c.lage, c.dr)
    bx, by, bz = c.dr.bauraum
    mass = f"{_z(br['x'], 0)} × {_z(br['y'], 0)} × {_z(br['z'], 0)} mm"
    raum = f"{_z(bx, 0)} × {_z(by, 0)} × {_z(bz, 0)} mm"
    if not br["passt"]:
        anders = [b for b in (alle or []) if b["passt"]]
        abhilfe = ("teilen: ebene Fügefläche mit 2 Passstiften (Ø 3–5 mm, Spiel 0,1 mm) oder Schwalbenschwanz "
                   "(Spiel 0,1 mm), verkleben oder verschrauben (Rezept „Teilung mit Passstiften“)")
        if anders:
            abhilfe = f"anders legen ({_richtung_text(anders[0]['unten'])} passt) oder {abhilfe}"
        c.hinweise.append(_hinweis(
            "bauraum", "fehler", f"Teil {mass} passt nicht in den Bauraum {raum} des {c.dr.name}"
            + ("" if br["z_ok"] else " (zu hoch)") + ", auch nicht diagonal"
            + (f" (vorne links {_z(c.dr.sperrflaeche[0], 0)} × {_z(c.dr.sperrflaeche[1], 0)} mm gesperrt)"
               if any(c.dr.sperrflaeche) and br["z_ok"] else ""), abhilfe,
            punkt=c.netz.V[np.argmax(c.lage.hV)], x=br["x"], y=br["y"], z=br["z"]))
    elif not br["passt_gerade"]:
        c.hinweise.append(_hinweis(
            "bauraum", "hinweis", f"Teil {mass} passt nur diagonal ({_z(br['winkel'], 0)}° um Z gedreht) aufs Bett",
            "im Slicer entsprechend drehen; kein Platz für Prime Tower und Brim, ggf. teilen",
            winkel=br["winkel"]))
    elif not br["passt_gerade_rand"]:
        c.hinweise.append(_hinweis(
            "bauraum", "warnung", f"Teil {mass} füllt den Bauraum fast ganz ({_z(c.dr.rand, 0)} mm Rand fehlen)",
            "kein Platz für Brim (5 mm) und, mit AMS, Prime Tower (35 mm) – etwas kleiner konstruieren oder teilen"))
    return br


def _pruefe_auflage(c: _Ctx) -> None:
    a, h = c.lage.auflage, c.lage.hoehe
    if h < 3.0:
        return
    if a < 1e-3:
        c.hinweise.append(_hinweis(
            "auflage", "warnung", "Teil liegt nur auf einer Kante oder einem Punkt auf",
            "eine ebene Auflagefläche anlegen (z. B. 0,6 mm abflachen) oder anders legen; sonst Stütze darunter",
            punkt=c.netz.V[np.argmin(c.lage.hV)]))
        return
    fl = max(c.lage.bett_flaechen, key=lambda f: c.netz.infos[f].flaeche) if c.lage.bett_flaechen else None
    if a < c.sw.auflage_min:
        c.hinweise.append(_hinweis(
            "auflage", "warnung", f"Auflagefläche nur {_z(a, 1)} mm²: Teil kann sich lösen oder umkippen",
            "Brim (5–10 mm) einschalten, Auflage vergrößern oder Teil flacher legen", flaeche=fl, auflage=a))
    elif h / math.sqrt(a) > c.sw.schlank:
        c.hinweise.append(_hinweis(
            "auflage", "hinweis", f"hohes, schlankes Teil ({_z(h, 0)} mm hoch auf {_z(a, 0)} mm²): wackelt beim Drucken",
            "Brim 5 mm, langsamer drucken oder liegend drucken", flaeche=fl, auflage=a, hoehe=h))


def _pruefe_bohrungen(c: _Ctx) -> None:
    netz, lage = c.netz, c.lage
    s = -lage.nz
    grenze = math.sin(math.radians(min(c.grenze + _WINKEL_TOL, 89.9)))
    nenn: list[tuple[float, list[int]]] = []
    for g in c.rund:
        if not g.hohl or g.winkel < 180:
            continue
        mask = np.isin(netz.tri_face, g.flaechen)
        mitte = netz.tri_c[mask].mean(axis=0) if mask.any() else g.punkt
        voll = g.winkel >= 300
        if voll and g.d < c.sw.bohrung_fehler:
            c.hinweise.append(_hinweis(
                "bohrung_klein", "fehler", f"Bohrung Ø {_z(g.d, 2)} mm ist zu klein und setzt beim Drucken zu",
                "nach dem Druck bohren (im Modell nur ankörnen, Ø ≤ 1 mm weglassen) oder auf ≥ 2 mm vergrößern",
                flaechen=g.flaechen, punkt=mitte, durchmesser=g.d))
            c.erledigt.update(g.flaechen)
            continue
        if voll and g.d < c.sw.bohrung_warnung:
            c.hinweise.append(_hinweis(
                "bohrung_klein", "warnung", f"Bohrung Ø {_z(g.d, 2)} mm: unter 2 mm wird sie unrund und zu eng",
                f"im Modell Ø {_z(g.d + bohrung_zugabe(g.d), 1)} vorsehen und nachbohren", flaechen=g.flaechen,
                punkt=mitte, durchmesser=g.d))
        if c.mat.fdm and abs(float(g.achse @ lage.oben)) < 0.1:
            m = mask & (s > grenze) & (lage.hT.mean(axis=1) > c.dr.erste_schicht)
            if m.any():
                winkel = math.degrees(math.asin(min(1.0, float(s[m].max()))))
                spitze = g.radius * math.sqrt(2)
                schwere = "warnung" if g.d >= 3 else "hinweis"
                c.hinweise.append(_hinweis(
                    "waagrechte_bohrung", schwere,
                    f"waagrechte Bohrung Ø {_z(g.d, 1)} mm: oben hängt sie bis {_z(winkel, 0)}° über und wird "
                    "unrund (Durchhang ca. 0,1–0,3 mm, im Slicer sonst Stütze in der Bohrung)",
                    f"Tropfenform mit 45°-Spitze (Spitze {_z(spitze, 2)} mm über der Mitte, Rezept „Tropfenbohrung“), "
                    "oben 0,3 mm abflachen oder das Teil so legen, dass die Bohrung senkrecht steht",
                    flaechen=g.flaechen, punkt=netz.tri_c[m][np.argmax(lage.hT[m].mean(axis=1))],
                    durchmesser=g.d, winkel=winkel))
                c.erledigt.update(g.flaechen)
                c.stuetz += float((netz.tri_a * s)[m].sum())
        if (voll and c.sw.bohrung_warnung <= g.d <= 25 and abs(g.d * 2 - round(g.d * 2)) < 0.02
                and not any(abs(g.d - m) < 0.02 for m in _TABELLENMASSE)):
            nenn.append((g.d, g.flaechen))
    if nenn and c.mat.fdm:
        ds = sorted({round(d, 2) for d, _ in nenn})
        liste = ", ".join(f"Ø {_z(d, 1)}" for d in ds[:6])
        fl = [f for _, ff in nenn for f in ff]
        bsp = ds[0]
        c.hinweise.append(_hinweis(
            "bohrung_mass", "hinweis",
            f"Bohrungen mit glattem Nennmaß ({liste}): gedruckte Bohrungen fallen ca. 0,2–0,3 mm kleiner aus – "
            "soll dort ein Stift, eine Welle oder Schraube hinein, wird es eng",
            f"für Spiel das Nennmaß plus Zugabe konstruieren (z. B. Ø {_z(bsp, 1)} → Ø {_z(bsp + bohrung_zugabe(bsp), 2)}; "
            "Schraubendurchgang M3 → 3,4, M4 → 4,5); Gewindeeinsätze nach Tabelle (M3 → 4,0–4,2)",
            flaechen=fl, punkt=netz.tri_c[np.isin(netz.tri_face, nenn[0][1])].mean(axis=0),
            durchmesser=ds))


def _pruefe_stifte(c: _Ctx) -> None:
    netz, lage = c.netz, c.lage
    for g in c.rund:
        if g.hohl or g.winkel < 300 or g.d >= c.sw.stift_hinweis:
            continue
        mask = np.isin(netz.tri_face, g.flaechen)
        if not mask.any():
            continue
        proj = netz.V[netz.T[mask]].reshape(-1, 3) @ g.achse
        laenge = float(proj.max() - proj.min())
        if laenge < g.d:
            continue    # flacher Zapfen oder Rundung, kein Stift
        senkrecht = abs(float(g.achse @ lage.oben)) > 0.9
        schwere = "warnung" if g.d < c.sw.stift_warnung else "hinweis"
        befund = f"Stift Ø {_z(g.d, 1)} × {_z(laenge, 1)} mm: besteht nur aus Wandbahnen und bricht leicht"
        if senkrecht:
            befund += ", stehend bricht er zwischen den Schichten"
        c.hinweise.append(_hinweis(
            "stift", schwere, befund,
            "Ø ≥ 3 mm (besser 5) und Fuß verrunden, liegend drucken oder einen Metallstift einsetzen "
            "(Bohrung = Stift-Ø, Presspassung)", flaechen=g.flaechen, punkt=netz.tri_c[mask].mean(axis=0),
            durchmesser=g.d, laenge=laenge))


def _decken(c: _Ctx) -> list[int]:
    out = []
    for f in range(c.netz.flaechenzahl):
        info = c.netz.infos[f]
        if info.typ != "ebene" or info.normale is None or f in c.lage.bett_flaechen or info.flaeche < 0.5:
            continue
        if float(info.normale @ c.lage.oben) < -_WAAGRECHT:
            out.append(f)
    return out


def _im_dreiecksnetz(Q: np.ndarray, tri2d: np.ndarray) -> np.ndarray:
    """2D: liegen die Punkte Q (q×2) in einem der Dreiecke tri2d (t×3×2)?"""
    a, b, cc = tri2d[:, 0], tri2d[:, 1], tri2d[:, 2]
    v0, v1 = cc - a, b - a
    v2 = Q[:, None, :] - a[None, :, :]
    d00 = np.einsum("ij,ij->i", v0, v0)
    d01 = np.einsum("ij,ij->i", v0, v1)
    d11 = np.einsum("ij,ij->i", v1, v1)
    d20 = np.einsum("qij,ij->qi", v2, v0)
    d21 = np.einsum("qij,ij->qi", v2, v1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-18, 1e-18, den)
    u = (d11 * d20 - d01 * d21) / den
    v = (d00 * d21 - d01 * d20) / den
    return ((u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)).any(axis=1)


def _pruefe_decken(c: _Ctx) -> None:
    """Waagrechte Unterseiten oberhalb des Betts: Brücke, freie Auskragung oder Gegenbohrung zur Bettseite.

    Halt (Anker) hat eine Randkante, unter der direkt Material liegt. Wie im Slicer wird jede Fläche in **einer**
    Richtung überbrückt: Für 12 Richtungen (alle 15°) sucht jede Stichprobe den nächsten Anker voraus und zurück
    (Kegel ±20°), der Weg dorthin muss in der Fläche liegen (nicht über ein Loch). Gewählt wird die Richtung mit den
    wenigsten frei hängenden Punkten, dann der kürzesten Spannweite. Punkte ohne Halt auf beiden Seiten kragen aus.
    """
    netz, lage, mat = c.netz, c.lage, c.mat
    oben = lage.oben
    e1 = np.cross(oben, [1.0, 0, 0] if abs(oben[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(oben, e1)
    rng = np.random.default_rng(3)
    seitlich, tiefer = 0.3, min(0.3, c.dr.schichthoehe / 2)
    richtungen = np.radians(np.arange(0.0, 180.0, 15.0))
    kegel = math.radians(20)
    for f in _decken(c):
        mask = netz.tri_face == f
        if not mask.any():
            continue
        h = float(lage.hT[mask].mean())
        kanten = [k for k in netz.kanten if f in k.flaechen]
        umfang = sum(k.laenge for k in kanten)
        schritt = max(0.3, min(2.0, umfang / 150))
        pts, tans = [], []
        for k in kanten:
            p, t = k.abtasten(schritt)
            pts.append(p)
            tans.append(t)
        if not pts:
            continue
        Pk, Tk = np.concatenate(pts), np.concatenate(tans)
        o = np.cross(Tk, oben)
        o /= np.maximum(np.linalg.norm(o, axis=1), 1e-12)[:, None]
        test = np.concatenate([Pk + o * seitlich - oben * tiefer, Pk - o * seitlich - oben * tiefer])
        innen = netz.innen(test)
        anker = Pk[innen[:len(Pk)] | innen[len(Pk):]]
        ta, tb, tc = netz.V[netz.T[mask, 0]], netz.V[netz.T[mask, 1]], netz.V[netz.T[mask, 2]]
        a = netz.tri_a[mask]
        n_s = 160
        wahl = rng.choice(len(a), n_s, p=a / a.sum())
        r1, r2 = rng.random(n_s), rng.random(n_s)
        sq = np.sqrt(r1)
        S = (1 - sq)[:, None] * ta[wahl] + (sq * (1 - r2))[:, None] * tb[wahl] + (sq * r2)[:, None] * tc[wahl]
        if len(anker) == 0:
            c.hinweise.append(_hinweis(
                "freie_unterseite", "warnung",
                f"waagrechte Unterseite {_z(netz.infos[f].flaeche, 0)} mm² in {_z(h, 1)} mm Höhe hängt ohne Halt in der Luft",
                "Stütze einplanen oder die Unterseite mit 45° zum Bett hin abschrägen", flaeche=f, punkt=S.mean(axis=0),
                hoehe=h))
            c.erledigt.add(f)
            c.stuetz += netz.infos[f].flaeche
            continue
        tri2d = np.stack([np.stack([x @ e1, x @ e2], axis=1) for x in (ta, tb, tc)], axis=1)
        V = anker[None, :, :] - S[:, None, :]
        D = np.linalg.norm(V, axis=2)
        d1 = D.min(axis=1)
        phi = np.arctan2(V @ e2, V @ e1)
        S2 = np.stack([S @ e1, S @ e2], axis=1)
        A2 = np.stack([anker @ e1, anker @ e2], axis=1)

        def weg_ok(idx, j):
            ok = np.ones(len(idx), dtype=bool)
            for frac in (0.3, 0.6, 0.9):
                ok &= _im_dreiecksnetz(S2[idx] + (A2[j] - S2[idx]) * frac, tri2d)
            return ok

        beste = None
        for th in richtungen:
            dw = np.angle(np.exp(1j * (phi - th)))
            hin = np.where(np.abs(dw) < kegel, D, np.inf)
            her = np.where(np.abs(dw) > math.pi - kegel, D, np.inf)
            jh, jr = np.argmin(hin, axis=1), np.argmin(her, axis=1)
            dh, dr_ = hin[np.arange(n_s), jh], her[np.arange(n_s), jr]
            gh, gr = np.isfinite(dh), np.isfinite(dr_)
            for g, j in ((gh, jh), (gr, jr)):
                idx = np.flatnonzero(g)
                if len(idx):
                    g[idx[~weg_ok(idx, j[idx])]] = False
            beide = gh & gr
            spann = np.where(beide, dh + dr_, np.inf)
            # nicht beidseitig gehalten: kragt aus, gemessen bis zum nächsten Anker (so druckt der Slicer die Wände)
            krag = np.where(beide, 0.0, d1)
            frei = krag > mat.kragarm_max
            wert = (int(frei.sum()), float(spann[beide].max()) if beide.any() else 0.0)
            if beste is None or wert < beste[0]:
                beste = (wert, th, spann, krag, frei, beide)
        _, th, spann, krag, frei, beide = beste
        if frei.any():
            laenge = float(krag[frei].max())
            p = S[frei][np.argmax(krag[frei])]
            loch_oben = any(netz.infos[g].zylinder is not None and netz.infos[g].zylinder.hohl
                            and abs(float(netz.infos[g].zylinder.achse @ oben)) > 0.99
                            and float(lage.hT[netz.tri_face == g].max()) > h + 0.05 for g in netz.nachbarn[f])
            if loch_oben:
                c.hinweise.append(_hinweis(
                    "gegenbohrung_unten", "warnung",
                    f"Senkung/Gegenbohrung zur Bettseite: die Ringfläche in {_z(h, 1)} mm Höhe hängt {_z(laenge, 1)} mm "
                    "frei, der Slicer druckt dort Ringe in die Luft",
                    f"Opferschicht: die Bohrung erst {_z(c.dr.schichthoehe, 1)} mm (1 Schicht) über der Senkung beginnen "
                    "und nach dem Druck durchstechen, oder Brückentrick (2 Stufen à 1 Schicht), Rezept "
                    "„Gegenbohrung mit Opferschicht“; oder die Senkung nach oben legen",
                    flaeche=f, punkt=p, laenge=laenge, hoehe=h))
            else:
                c.hinweise.append(_hinweis(
                    "kragarm", "warnung",
                    f"waagrechte Unterseite kragt {_z(laenge, 1)} mm frei aus (in {_z(h, 1)} mm Höhe, 90° Überhang)",
                    "darunter eine 45°-Schräge oder gestufte Fase vorsehen, Teil drehen oder Stütze einplanen",
                    flaeche=f, punkt=p, laenge=laenge, hoehe=h))
            c.erledigt.add(f)
            c.stuetz += netz.infos[f].flaeche
            continue
        if beide.any():
            weite = float(spann[beide].max())
            p = S[beide][np.argmax(spann[beide])]
            richtung = (math.cos(th) * e1 + math.sin(th) * e2)
            if weite > mat.bruecke_max:
                c.hinweise.append(_hinweis(
                    "bruecke", "warnung",
                    f"Brücke {_z(weite, 0)} mm in {_z(h, 1)} mm Höhe: zu lang für {mat.name} (bis ca. "
                    f"{_z(mat.bruecke_max, 0)} mm), hängt durch", "Zwischenwand oder Rippe einziehen, die Decke als "
                    "45°-Dach/Bogen formen, Teil drehen oder Stütze einplanen", flaeche=f, punkt=p, spannweite=weite,
                    hoehe=h, richtung=_p(richtung)))
                c.stuetz += netz.infos[f].flaeche
            elif weite > mat.bruecke_gut:
                c.hinweise.append(_hinweis(
                    "bruecke", "hinweis",
                    f"Brücke {_z(weite, 0)} mm in {_z(h, 1)} mm Höhe: druckbar, Unterseite hängt leicht durch",
                    f"unter {_z(mat.bruecke_gut, 0)} mm bleiben oder Rippe einziehen, wenn die Unterseite sauber "
                    "sein muss", flaeche=f, punkt=p, spannweite=weite, hoehe=h, richtung=_p(richtung)))
        c.erledigt.add(f)


def _pruefe_ueberhaenge(c: _Ctx, bettrund: set[int]) -> None:
    netz, lage = c.netz, c.lage
    s = -lage.nz
    grenze = math.sin(math.radians(min(c.grenze + _WINKEL_TOL, 89.9)))
    decken = set(_decken(c))
    ueber = (s > grenze) & (lage.hT.mean(axis=1) > c.dr.erste_schicht) & ~lage.bett
    ausnahmen = np.array(sorted(c.erledigt | decken | bettrund), dtype=np.int64)
    if len(ausnahmen):
        ueber &= ~np.isin(netz.tri_face, ausnahmen)
    if not ueber.any():
        return
    proj = netz.tri_a * s
    flaechen = np.unique(netz.tri_face[ueber])
    funde = []
    for f in flaechen:
        m = ueber & (netz.tri_face == f)
        a = float(proj[m].sum())
        if a < 1.0:
            continue
        # schmale Überhänge (Grundriss ≤ Kragarm-Grenze, z. B. Unterseiten erhabener Schrift) drucken wie ein Absatz
        grund = netz.V[netz.T[m]].reshape(-1, 3) @ lage.R.T
        if _rechteck_2d(grund[:, :2], 5.0)[1] <= c.mat.kragarm_max:
            continue
        w = math.degrees(math.asin(min(1.0, float(s[m].max()))))
        p = (netz.tri_c[m] * proj[m][:, None]).sum(axis=0) / max(proj[m].sum(), 1e-12)
        funde.append((a, w, int(f), p))
    funde.sort(key=lambda x: -x[0])
    for a, w, f, p in funde[:10]:
        info = netz.infos[f]
        rund = info.typ != "ebene" and not (info.zylinder is not None and info.zylinder.hohl)
        abhilfe = ("Rundung an der Unterseite durch eine 45°-Fase ersetzen (oben darf es rund bleiben)" if rund else
                   "Unterseite auf ≤ 45° abschrägen oder in Stufen auflösen, Teil drehen oder Stütze einplanen")
        if not c.mat.fdm:
            abhilfe = "Stützen einplanen (beim Harzdruck üblich) oder Teil kippen"
        c.hinweise.append(_hinweis(
            "ueberhang", "warnung" if c.mat.fdm else "hinweis",
            f"Überhang bis {_z(w, 0)}° auf {_z(a, 0)} mm² (ohne Stütze bis ca. {_z(c.grenze, 0)}° für {c.mat.name})",
            abhilfe, flaeche=f, punkt=p, winkel=w, flaeche_mm2=a))
        c.stuetz += a
    if len(funde) > 10:
        rest = sum(x[0] for x in funde[10:])
        c.hinweise.append(_hinweis(
            "ueberhang", "warnung", f"{len(funde) - 10} weitere Überhangflächen mit zusammen {_z(rest, 0)} mm²",
            "siehe oben; Teil drehen oder Stützen einplanen", flaechen=[x[2] for x in funde[10:]],
            punkt=funde[10][3]))
        c.stuetz += rest


def _pruefe_bettkanten(c: _Ctx) -> set[int]:
    """Scharfe Unterkanten (Elefantenfuß) und Rundungen an der Bettkante. Gibt die Rundungsflächen zurück."""
    netz, lage = c.netz, c.lage
    scharf: dict[int, float] = {}
    loch_scharf = False
    rundungen: dict[int, float] = {}
    punkt = None
    laengste = 0.0
    nah = lage.hT.min(axis=1) < 0.05
    for b in lage.bett_flaechen:
        for f in netz.nachbarn[b]:
            if f in lage.bett_flaechen:
                continue
            m = (netz.tri_face == f) & nah & (lage.hT.mean(axis=1) < 1.0)
            if not m.any():
                m = (netz.tri_face == f) & nah
            if not m.any():
                continue
            nz = float((lage.nz[m] * netz.tri_a[m]).sum() / netz.tri_a[m].sum())
            info = netz.infos[f]
            ks = [k for k in netz.kanten if k.flaechen == tuple(sorted((b, f)))]
            laenge = sum(k.laenge for k in ks)
            if abs(nz) < 0.35:
                scharf[f] = scharf.get(f, 0.0) + laenge
                if info.zylinder is not None and info.zylinder.hohl:
                    loch_scharf = True
                if laenge > laengste and ks:
                    laengste = laenge
                    pts, _ = ks[0].abtasten(1.0)
                    punkt = pts[len(pts) // 2]
            elif nz < -0.85 and info.typ in ("zylinder", "torus", "kugel", "frei"):
                hoch = float(lage.hT[netz.tri_face == f].max())
                if hoch <= c.dr.erste_schicht + 0.05:
                    continue    # liegt in der ersten Schicht, spielt keine Rolle
                rundungen[f] = info.zylinder.radius if info.zylinder is not None else hoch
    # Eckstücke (Kugel/Torus) zwischen Rundungen berühren das Bett nur in einem Punkt: über Nachbarschaft aufnehmen
    neu = True
    while rundungen and neu:
        neu = False
        for f in range(netz.flaechenzahl):
            info = netz.infos[f]
            if f in rundungen or info.typ == "ebene" or not (netz.nachbarn[f] & rundungen.keys()):
                continue
            m = (netz.tri_face == f) & nah
            if m.any() and float((lage.nz[m] * netz.tri_a[m]).sum() / netz.tri_a[m].sum()) < -0.85:
                rundungen[f] = max(rundungen[g] for g in netz.nachbarn[f] & rundungen.keys())
                neu = True
    if scharf and c.mat.fdm:
        gesamt = sum(scharf.values())
        fl = max(lage.bett_flaechen, key=lambda f: netz.infos[f].flaeche)
        c.hinweise.append(_hinweis(
            "elefantenfuss", "hinweis",
            f"scharfe Unterkanten ({_z(gesamt, 0)} mm): die erste Schicht quillt 0,1–0,2 mm heraus (Elefantenfuß)"
            + (", Bohrungen werden unten enger" if loch_scharf else ""),
            f"Fase {_z(c.sw.bettfase, 1)} mm × 45° an der Bettkante (Bambu gleicht nur 0,15 mm aus)"
            + ("; Bohrungen an der Bettseite 0,3–0,5 mm fasen" if loch_scharf else "")
            + " (Rezept „Bettfase“)", flaeche=fl, flaechen=[fl, *scharf.keys()], punkt=punkt, kantenlaenge=gesamt))
    if rundungen and c.mat.fdm:
        rmax = max(rundungen.values())
        f0 = max(rundungen, key=lambda f: netz.infos[f].flaeche)
        m = np.isin(netz.tri_face, list(rundungen))
        c.hinweise.append(_hinweis(
            "rundung_unten", "warnung" if rmax > 2.0 else "hinweis",
            f"Rundung{' R ' + _z(rmax, 1) if rmax else ''} an der Bettkante: unten fast waagrecht (Überhang bis 90°), "
            "franst aus und zeigt Elefantenfuß",
            f"an der Unterseite eine 45°-Fase ({_z(max(rmax, 0.5), 1)} mm) statt der Rundung; oben darf es rund bleiben",
            flaeche=f0, flaechen=list(rundungen), punkt=netz.tri_c[m][np.argmin(lage.hT[m].mean(axis=1))],
            radius=rmax))
    return set(rundungen)


def _pruefe_verzug(c: _Ctx) -> None:
    mat, netz, lage = c.mat, c.netz, c.lage
    if not mat.fdm or mat.verzug < 1 or mat.verzug_laenge is None or not lage.bett.any():
        return
    P = netz.V[netz.T[lage.bett]].reshape(-1, 3) @ lage.R.T
    a, b, _ = _rechteck_2d(P[:, :2])
    fl = max(lage.bett_flaechen, key=lambda f: netz.infos[f].flaeche) if lage.bett_flaechen else None
    abhilfe = (f"Ecken mit R ≥ {_z(c.sw.verzug_eckradius, 0)} mm runden, Mouse Ears (Scheiben Ø 10–15 mm, 0,4 mm "
               "hoch) oder Brim 5–10 mm, große Flächen in Rippen auflösen"
               + ("; der Bauraum ist offen: Zugluft vermeiden, Bett vorheizen, für ABS/ASA/PC/PA Einhausung"
                  if not c.dr.geschlossen else "; Bett 10 min vorheizen, Tür zu"))
    if a > mat.verzug_laenge:
        c.hinweise.append(_hinweis(
            "verzug", "warnung" if mat.verzug >= 2 else "hinweis",
            f"Auflage {_z(a, 0)} × {_z(b, 0)} mm: {mat.name} verzieht sich ab etwa {_z(mat.verzug_laenge, 0)} mm "
            f"Länge (Schwund ca. {_z(mat.schwund, 1)} %, Ecken heben ab)", abhilfe, flaeche=fl,
            punkt=netz.tri_c[lage.bett].mean(axis=0), laenge=a, breite=b))
    if mat.verzug < 2:
        return
    # spitze senkrechte Außenecken an der Grundfläche
    ecken = []
    oben = lage.oben
    for k in netz.kanten:
        if not k.gerade or len(k.flaechen) != 2:
            continue
        pts, tans = k.abtasten(1.0, max_punkte=3)
        if abs(float(tans[0] @ oben)) < 0.999:
            continue
        hmin = min(float((pts @ oben).min()), 1e9) - float((netz.V @ oben).min())
        if hmin > max(k.laenge, 1.0):
            continue
        f1, f2 = (netz.infos[f] for f in k.flaechen)
        if f1.normale is None or f2.normale is None:
            continue
        cosw = float(f1.normale @ f2.normale)
        if cosw > 0.5:      # Innenwinkel > 120°: stumpf genug
            continue
        p = pts[0] - oben * float((pts[0] @ oben) - (netz.V @ oben).min()) + oben * 0.3
        ecken.append((p, f1.normale - f2.normale, k))
    if ecken:
        test = np.array([p + d / max(np.linalg.norm(d), 1e-12) * 0.2 for p, d, _ in ecken])
        konvex = ~netz.innen(test)
        spitz = [e for e, kv in zip(ecken, konvex) if kv]
        if spitz:
            c.hinweise.append(_hinweis(
                "verzug_ecken", "hinweis",
                f"{len(spitz)} spitze Außenecken an der Grundfläche: dort hebt {mat.name} zuerst ab",
                f"senkrechte Kanten mit R ≥ {_z(c.sw.verzug_eckradius, 0)} mm runden oder Mouse Ears an die Ecken",
                flaechen=sorted({f for _, _, k in spitz for f in k.flaechen}), punkt=spitz[0][0], anzahl=len(spitz)))


def _pruefe_schichtraster(c: _Ctx) -> None:
    if not c.mat.fdm:
        return
    netz, lage = c.netz, c.lage
    schicht = c.dr.schichthoehe
    abweich = []
    for info in netz.infos:
        if info.typ != "ebene" or info.normale is None or abs(float(info.normale @ lage.oben)) < _WAAGRECHT:
            continue
        m = netz.tri_face == info.index
        if not m.any():
            continue
        h = float(lage.hT[m].mean())
        if h < 0.01:
            continue
        rest = abs(h - round(h / schicht) * schicht)
        if rest > c.sw.z_toleranz:
            abweich.append((h, info.index))
    if abweich:
        hs = sorted({round(h, 2) for h, _ in abweich})
        liste = ", ".join(_z(h, 2) for h in hs[:6]) + (" …" if len(hs) > 6 else "")
        h0 = hs[0]
        c.hinweise.append(_hinweis(
            "schichtraster", "hinweis",
            f"Höhen {liste} mm liegen nicht im Schichtraster {_z(schicht, 2)} mm: der Slicer rundet um bis zu "
            f"{_z(schicht / 2, 2)} mm", f"Z-Maße als Vielfache von {_z(schicht, 2)} mm konstruieren "
            f"(z. B. {_z(h0, 2)} → {_z(c.dr.z_mass(h0), 2)})", flaechen=[f for _, f in abweich],
            punkt=netz.tri_c[netz.tri_face == abweich[0][1]].mean(axis=0), hoehen=hs))


def _opferschicht(c: _Ctx, flaechen: set[int]) -> bool:
    """Dünne waagrechte Haut über einem Hohlraum, aus deren Oberseite eine senkrechte Bohrung weitergeht
    (gewollte Opferschicht über Senkung oder Mutterntasche)."""
    netz, oben = c.netz, c.lage.oben
    boden = decke = False
    for f in flaechen:
        info = netz.infos[f]
        if info.typ != "ebene" or info.normale is None or abs(float(info.normale @ oben)) < _WAAGRECHT:
            return False
        if float(info.normale @ oben) < 0:
            decke = True
        elif any(netz.infos[g].zylinder is not None and netz.infos[g].zylinder.hohl
                 and abs(float(netz.infos[g].zylinder.achse @ oben)) > 0.99 for g in netz.nachbarn[f]):
            boden = True
    return boden and decke


def _pruefe_waende(c: _Ctx, st: _Strahlen) -> None:
    netz, lage, sw, dr = c.netz, c.lage, c.sw, c.dr
    dünn = np.isfinite(st.t)
    if not dünn.any():
        return
    cz = np.abs(st.N @ lage.oben)
    xy = cz <= math.sqrt(0.5)
    mass = np.where(xy, st.t / np.sqrt(np.maximum(1 - cz ** 2, 1e-12)), st.t / np.maximum(cz, 1e-12))
    schwere = np.full(len(st.t), 3)
    for i, (gx, gz) in enumerate(((sw.wand_fehler, sw.schicht_fehler), (sw.wand_warnung, sw.schicht_warnung),
                                  (sw.wand_hinweis, sw.schicht_hinweis))):
        grenz = np.where(xy, gx, gz) - 0.01
        schwere = np.where((schwere == 3) & dünn & (mass < grenz), i, schwere)
    sel = np.flatnonzero(schwere < 3)
    if len(sel) == 0:
        return
    gruppen: dict[tuple, dict] = {}
    for i in sel:
        a, b = int(st.F[i]), int(st.Fh[i])
        key = (min(a, b), max(a, b), bool(xy[i]))
        g = gruppen.setdefault(key, {"n": 0, "min": np.inf, "schwere": 3, "punkt": None})
        g["n"] += 1
        g["schwere"] = min(g["schwere"], int(schwere[i]))
        if mass[i] < g["min"]:
            g["min"] = float(mass[i])
            g["punkt"] = st.P[i]
    funde = [(k, g) for k, g in gruppen.items() if g["n"] >= 2 or g["n"] * st.a_s >= 0.3]
    funde.sort(key=lambda kg: (kg[1]["schwere"], kg[1]["min"]))
    zusammen: list[dict] = []
    for (a, b, ixy), g in funde:
        for z in zusammen:
            if z["schwere"] == g["schwere"] and z["xy"] == ixy and abs(z["min"] - g["min"]) <= 0.05:
                z["flaechen"].update((a, b))
                z["n"] += g["n"]
                break
        else:
            zusammen.append({"schwere": g["schwere"], "xy": ixy, "min": g["min"], "punkt": g["punkt"],
                             "flaechen": {a, b}, "n": g["n"]})
    for z in zusammen[:8]:
        t = z["min"]
        sch = SCHWEREN[z["schwere"]]
        if not z["xy"] and t <= 2 * dr.schichthoehe + 0.01 and _opferschicht(c, z["flaechen"]):
            c.hinweise.append(_hinweis(
                "opferschicht", "hinweis",
                f"Opferschicht {_z(t, 2)} mm über einer Bohrung erkannt: sie überbrückt die Senkung beim Druck",
                "nach dem Druck mit Bohrer oder Ahle durchstechen", flaechen=sorted(z["flaechen"]), punkt=z["punkt"],
                dicke=t))
            continue
        if z["xy"]:
            bahnen = sum(1 for n in range(1, 8) if dr.wandstaerke(n) <= t + 0.01)
            if z["schwere"] == 0:
                befund = (f"Wand nur {_z(t, 2)} mm dick: dünner als eine Bahn ({_z(dr.linienbreite, 2)} mm), "
                          "fällt im Slicer weg")
                abhilfe = f"auf mind. {_z(dr.wandstaerke(2), 2)} mm (2 Bahnen) verstärken"
            elif z["schwere"] == 1:
                befund = f"Wand nur {_z(t, 2)} mm dick: passt nur eine Bahn, wird instabil und lückig"
                abhilfe = (f"auf {_z(dr.wandstaerke(2), 2)} mm (2 Bahnen) oder besser {_z(dr.wandstaerke(3), 2)} mm "
                           "(3 Bahnen) verstärken, sonst im Slicer „Dünne Wände erkennen“ einschalten")
            else:
                befund = f"Wand {_z(t, 2)} mm ({bahnen} Bahnen): für tragende Wände knapp"
                abhilfe = (f"≥ {_z(dr.wandstaerke(3), 2)} mm (3 Bahnen), besser {_z(dr.wandstaerke(4), 2)} mm (4 Bahnen) "
                           "für Festigkeit")
        else:
            schichten = int(round(t / dr.schichthoehe + 1e-6))
            befund = f"waagrechte Platte nur {_z(t, 2)} mm dick ({schichten} Schicht{'en' if schichten != 1 else ''})"
            abhilfe = f"mind. {_z(3 * dr.schichthoehe, 1)} mm (3 Schichten) vorsehen"
            if z["schwere"] == 0:
                befund += ", dünner als eine Schicht – wird nicht gedruckt"
        c.hinweise.append(_hinweis(
            "wand", sch, befund + f" ({len(z['flaechen'])} Flächen betroffen)", abhilfe,
            flaechen=sorted(z["flaechen"]), punkt=z["punkt"], dicke=t, flaeche_mm2=z["n"] * st.a_s))


# ---------------------------------------------------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------------------------------------------------


def _unten_aus(ausrichtung, netz: Netz) -> tuple[np.ndarray, str]:
    if isinstance(ausrichtung, str):
        key = ausrichtung.strip().lower().replace("−", "-")
        if key not in _ACHSEN:
            raise ValueError(f"Unbekannte Ausrichtung „{ausrichtung}“: {', '.join(_ACHSEN)} oder Flächennummer")
        return np.array(_ACHSEN[key], dtype=float), f"vorgegeben: {_richtung_text(np.array(_ACHSEN[key], float))}"
    if isinstance(ausrichtung, (int, np.integer)) and not isinstance(ausrichtung, bool):
        i = int(ausrichtung)
        if not 0 <= i < netz.flaechenzahl or netz.infos[i].normale is None:
            raise ValueError(f"Fläche {i} ist keine ebene Fläche der Form")
        return netz.infos[i].normale.copy(), f"vorgegeben: Fläche {i} aufs Bett"
    trsf = getattr(getattr(ausrichtung, "wrapped", None), "Transformation", None)
    if callable(trsf):
        t = trsf()
        R = np.array([[t.Value(r, s) for s in range(1, 4)] for r in range(1, 4)])
        return R.T @ np.array([0.0, 0.0, -1.0]), "vorgegeben: Drehung"
    v = np.asarray(ausrichtung, dtype=float).reshape(3)
    if np.linalg.norm(v) < 1e-9:
        raise ValueError("Ausrichtung: Nullvektor")
    return v / np.linalg.norm(v), f"vorgegeben: {_richtung_text(v / np.linalg.norm(v))}"


def _begruendung(beste: dict, modell: dict, netz: Netz, mat: Material, liegt_auf: int | None) -> str:
    teile = []
    if beste is modell:
        teile.append("Wie modelliert liegt das Teil am besten")
    else:
        wo = f"Fläche {liegt_auf} aufs Bett ({_richtung_text(beste['unten'])})" if liegt_auf is not None else \
            _richtung_text(beste["unten"])
        teile.append(wo)
    teile.append(f"Stützfläche ca. {_z(beste['stuetz'], 0)} mm²"
                 + ("" if beste is modell else f" (wie modelliert {_z(modell['stuetz'], 0)} mm²)"))
    teile.append(f"Auflage {_z(beste['auflage'], 0)} mm², Höhe {_z(beste['hoehe'], 1)} mm")
    if beste["bohrungen"]:
        if beste["waagrechte_bohrungen"] < modell["waagrechte_bohrungen"]:
            teile.append(f"waagrechte Bohrungen {modell['waagrechte_bohrungen']} → {beste['waagrechte_bohrungen']}")
        elif beste["waagrechte_bohrungen"]:
            teile.append(f"{beste['waagrechte_bohrungen']} Bohrung(en) liegen waagrecht")
    if not beste["passt"]:
        teile.append("passt in keiner Lage in den Bauraum")
    satz = "; ".join(teile) + "."
    satz += (f" Festigkeit: quer zu den Schichten hält {mat.name} nur etwa {_z(mat.z_festigkeit * 100, 0)} % – "
             "Hauptlasten (Zug, Biegung, Haken) in die Schichtebene legen, sonst Ausrichtung vorgeben.")
    return satz


def _pruefe_material(c: _Ctx) -> None:
    """Passt das Material zum Drucker? (Harzdruck, Einhausung, gehärtete Düse)"""
    mat, dr = c.mat, c.dr
    if not mat.fdm:
        c.hinweise.append(_hinweis(
            "material", "fehler", f"{mat.name}: kein Harzdrucker vorhanden, der {dr.name} druckt nur FDM",
            "als FDM-Druckteil aus PLA oder PETG konstruieren und prüfen"))
        return
    if mat.einhausung and not dr.geschlossen:
        c.hinweise.append(_hinweis(
            "material", "warnung", f"{mat.name} auf dem offenen {dr.name}: Bambu rät ohne geschlossenen Bauraum ab "
            "(Verzug, Lagentrennung, Risse)",
            "PLA oder PETG nehmen; sonst nur mit Einhausung (P1P Enclosure Kit oder Druckbox) und Brim drucken"))
    if mat.gehaertete_duese and not dr.duese_gehaertet:
        c.hinweise.append(_hinweis(
            "material", "warnung", f"{mat.name} ist abrasiv und braucht eine gehärtete Düse (HRC 40); der {dr.name} "
            f"hat ab Werk {dr.duese_material}", "PLA bzw. PETG ohne Faser nehmen oder ein gehärtetes Hotend nachrüsten"))


def _druckhinweise(mat: Material, dr: Drucker) -> list[str]:
    out = []
    if mat.fdm:
        t = f"{mat.name}: Düse {mat.duese_temp}, Bett {mat.bett_temp}"
        out.append(t + (f"; {mat.kammer}" if mat.kammer else "") + ".")
        if mat.trocknen:
            out.append(f"Trocknen: {mat.trocknen}. AMS: {mat.ams}.")
    out.extend(f"{mat.name}: {h}." for h in mat.hinweise)
    if mat.fdm:
        out.extend(FESTIGKEIT)
        out.append(f"Standardprofil {dr.name}: {dr.waende} Wände, {dr.deckschichten} Deck-/{dr.bodenschichten} "
                   f"Bodenschichten, Linienbreite {_z(dr.linienbreite, 2)} mm, Schicht {_z(dr.schichthoehe, 2)} mm, "
                   f"Elefantenfuß-Ausgleich {_z(dr.elefantenfuss_kompensation, 2)} mm.")
        bx, by, bz = dr.bauraum
        out.append(f"{dr.name}: {'geschlossen' if dr.geschlossen else 'offener Bauraum ohne Kammer'}, Bett bis "
                   f"{_z(dr.bett_max, 0)} °C, Düse {dr.duese_material} bis {_z(dr.duese_max, 0)} °C, Druckraum "
                   f"{_z(bx, 0)} × {_z(by, 0)} × {_z(bz, 0)} mm (vorne links {_z(dr.sperrflaeche[0], 0)} × "
                   f"{_z(dr.sperrflaeche[1], 0)} mm frei lassen); Mehrfarbe: {dr.ams}.")
    return out


def pruefe_druckteil(form, material: str | Material = "petg", ausrichtung=None, drucker: Drucker = P1P) -> dict:
    """Prüft ein 3D-Druckteil auf Druckbarkeit und gibt Ausrichtung, Hinweise und Kennzahlen zurück.

    ``form``: build123d-Form (Part, Solid, Compound), ``BuildPart`` oder Liste davon.
    ``material``: id oder Alias eines druckbaren Materials (``regeln.MATERIALIEN``), z. B. "petg", "pla", "asa".
    ``ausrichtung``: ``None`` = automatisch; "-z" (wie modelliert), "+z", "+x" … = diese Seite des Modells liegt
    auf dem Bett; Flächennummer (int) = diese ebene Fläche liegt auf dem Bett; Vektor = Richtung im Modell, die aufs
    Bett zeigt; build123d ``Rot(...)``/``Location`` = so gedreht wird gedruckt.

    Rückgabe (dict): ``ok`` (kein Fehler), ``zusammenfassung``, ``ausrichtung`` (``unten``, ``drehung`` für
    ``Rot(*drehung) * form``, ``liegt_auf``, ``automatisch``, ``begruendung``, ``kandidaten``), ``hinweise`` (Liste mit
    ``art``, ``schwere`` fehler/warnung/hinweis, ``text``, ``befund``, ``abhilfe``, ``flaeche``, ``flaechen``,
    ``punkt``, ``werte``), ``kennzahlen`` und ``druckhinweise`` (Materialeinstellungen, Festigkeit).
    """
    t0 = time.perf_counter()
    mat = material_fuer(material)
    sw = schwellen_fuer(drucker, mat)
    netz = baue_netz(form)
    rund = _rundungen(netz)
    decken_dh = {}
    for info in netz.infos:
        if info.typ == "ebene" and info.normale is not None:
            u = _umfang(netz, info.index)
            if u > 0:
                decken_dh[info.index] = 4 * info.flaeche / u

    modell_unten = np.array([0.0, 0.0, -1.0])
    if ausrichtung is None:
        kands = _kandidaten(netz)
        bew = [_bewerte(netz, d, mat, drucker, rund, decken_dh) for d in kands]
        modell = bew[0]
        sortiert = _waehle(bew, netz, sw)
        beste = sortiert[0]
        automatisch = True
    else:
        unten, _quelle = _unten_aus(ausrichtung, netz)
        beste = _bewerte(netz, unten, mat, drucker, rund, decken_dh)
        modell = beste if float(unten @ modell_unten) > 0.9999 else _bewerte(netz, modell_unten, mat, drucker, rund,
                                                                              decken_dh)
        sortiert = [beste]
        automatisch = False

    lage: _Lage = beste["lage"]
    liegt_auf = max(lage.bett_flaechen, key=lambda f: netz.infos[f].flaeche) if lage.bett_flaechen else None
    grenze = min(mat.ueberhang_max, drucker.ueberhang_grenze) if mat.fdm else mat.ueberhang_max
    c = _Ctx(netz, mat, drucker, sw, lage, rund, grenze)

    t_pruef = time.perf_counter()
    br = _pruefe_bauraum(c, sortiert if automatisch else None) if mat.fdm else None
    _pruefe_material(c)
    _pruefe_auflage(c)
    _pruefe_bohrungen(c)
    _pruefe_stifte(c)
    if mat.fdm:
        _pruefe_decken(c)
    bettrund = _pruefe_bettkanten(c)
    _pruefe_ueberhaenge(c, bettrund)
    st = _strahlen(netz, reichweite=max(sw.wand_hinweis, sw.schicht_hinweis) + 0.1)
    _pruefe_waende(c, st)
    _pruefe_verzug(c)
    _pruefe_schichtraster(c)
    c.hinweise.sort(key=lambda h: _RANG[h["schwere"]])

    anzahl = {s: sum(1 for h in c.hinweise if h["schwere"] == s) for s in SCHWEREN}
    worte = {"fehler": ("Fehler", "Fehler"), "warnung": ("Warnung", "Warnungen"), "hinweis": ("Hinweis", "Hinweise")}
    teile = [f"{n} {worte[s][0] if n == 1 else worte[s][1]}" for s, n in anzahl.items() if n]
    zusammenfassung = (", ".join(teile) if teile else "druckbar ohne Hinweise") + f" ({mat.name}, {drucker.name})"

    P = netz.V @ lage.R.T
    abm = P.max(axis=0) - P.min(axis=0)
    volumen = float(abs(netz.form.volume)) if hasattr(netz.form, "volume") else 0.0
    kennzahlen = {
        "stuetzflaeche_mm2": round(c.stuetz, 1),
        "auflageflaeche_mm2": round(lage.auflage, 1),
        "hoehe_mm": round(lage.hoehe, 2),
        "schichten": int(math.ceil(lage.hoehe / drucker.schichthoehe - 1e-6)) if mat.fdm else None,
        "abmessungen_mm": [round(float(x), 2) for x in abm],
        "bauraum_ausnutzung_prozent": (round(100 * max(br["a"] / max(drucker.bauraum[:2]), br["b"] /
                                                       min(drucker.bauraum[:2]), lage.hoehe / drucker.bauraum[2]), 1)
                                       if br else None),
        "volumen_cm3": round(volumen / 1000, 3),
        "masse_voll_g": round(volumen / 1000 * mat.dichte, 1),
        "dreiecke": int(len(netz.T)),
        "stichproben_wand": int(len(st.t)),
        "laufzeit_ms": round((time.perf_counter() - t0) * 1000, 1),
        "laufzeit_pruefung_ms": round((time.perf_counter() - t_pruef) * 1000, 1),
    }

    def kand(b: dict) -> dict:
        lg: _Lage = b["lage"]
        auf = max(lg.bett_flaechen, key=lambda f: netz.infos[f].flaeche) if lg.bett_flaechen else None
        return {"unten": _p(b["unten"]), "liegt_auf": auf, "stuetzflaeche_ca_mm2": round(b["stuetz"], 1),
                "auflage_mm2": round(b["auflage"], 1), "hoehe_mm": round(b["hoehe"], 2),
                "waagrechte_bohrungen": b["waagrechte_bohrungen"], "passt": bool(b["passt"]),
                "punkte": round(b.get("punkte", 0.0), 3)}

    return {
        "ok": anzahl["fehler"] == 0,
        "zusammenfassung": zusammenfassung,
        "material": mat.id,
        "material_name": mat.name,
        "drucker": drucker.name,
        "ausrichtung": {
            "unten": _p(lage.unten),
            "drehung": _euler_xyz(lage.R),
            "matrix": [[round(float(x), 6) + 0.0 for x in row] for row in lage.R],
            "liegt_auf": liegt_auf,
            "automatisch": automatisch,
            "begruendung": _begruendung(beste, modell, netz, mat, liegt_auf),
            "kandidaten": [kand(b) for b in sortiert[:5]],
        },
        "hinweise": c.hinweise,
        "kennzahlen": kennzahlen,
        "druckhinweise": _druckhinweise(mat, drucker),
    }


def als_warnungen(ergebnis: dict, max_anzahl: int = 8, mit_hinweisen: bool = False) -> list[str]:
    """Kurze Textzeilen für ``RUN_END.warnings`` oder eine MCP-Antwort (Fehler und Warnungen zuerst)."""
    zeilen = []
    for h in ergebnis["hinweise"]:
        if h["schwere"] == "hinweis" and not mit_hinweisen:
            continue
        ort = f" [#f{h['flaeche']}]" if h["flaeche"] is not None else ""
        zeilen.append(f"Druck {h['schwere'].capitalize()}: {h['text']}{ort}")
    if len(zeilen) > max_anzahl:
        rest = len(zeilen) - max_anzahl
        zeilen = zeilen[:max_anzahl] + [f"… {rest} weitere (druckpruefung zeigt alle)"]
    return zeilen
