"""Wege: Kommt ein Teil entlang einer Richtung frei an seinen Platz? Kommt das Werkzeug an die Schraube? Steht die
Teilbaugruppe?

Einführweg (Umkehrung des Ausbaus): Teil p fährt aus seiner Lage entlang der Ausbaurichtung d (= −Einführrichtung)
um ``weg`` mm (``None``: bis ins Freie). Ein anderes Teil q sperrt, wenn ein Strahl entlang d durch p und q geht und q
vor dem hintersten Punkt von p liegt (und, bei endlichem Weg, nicht weiter als der Weg). Gerechnet wird je Teilepaar:
Raster beider Netze in der Ebene senkrecht zu d (raster.py), Kandidaten dort, wo q vor p liegt, dann exakte Strahlen
(OCCT) an diesen Bildpunkten. Berühren mit ``TOL`` sperrt nicht.

Ausnahmen wie in der Prüfung: Paare mit erlaubter Überlappung, sich durchdringende Paare (eigener Befund) und
Gewindeeingriffe (Schraube im Einsatz oder Kernloch) entlang ihrer Achse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.bauplan import raster as rs
from kevcad_kernel.pruefung.koerper import Koerper, basis, einheit, richtung_schluessel

TOL = 0.05  # mm: Berühren
MAX_STRAHLEN = 48  # exakte Strahlen je Paar höchstens


def richtung_text(d: Any) -> str:
    """„von oben“ usw. für eine Einführrichtung (Richtung, in die das Teil beim Einbau fährt)."""
    v = np.asarray(d, dtype=float)
    v = v / (np.linalg.norm(v) or 1.0)
    namen = [((0, 0, -1), "von oben"), ((0, 0, 1), "von unten"), ((1, 0, 0), "von links"), ((-1, 0, 0), "von rechts"),
             ((0, 1, 0), "von vorn"), ((0, -1, 0), "von hinten")]
    best = max(namen, key=lambda kv: float(np.dot(v, kv[0])))
    if float(np.dot(v, best[0])) > 0.985:
        return best[1]
    teile = []
    for i, (pos, neg) in enumerate((("von links", "von rechts"), ("von vorn", "von hinten"), ("von unten", "von oben"))):
        if abs(v[i]) > 0.2:
            teile.append(pos if v[i] > 0 else neg)
    return "schräg " + " und ".join(teile) if teile else "schräg"


@dataclass
class Sperre:
    teil: str
    gegen: str
    pixel: int
    bestaetigt: int
    tiefe: float  # wie weit q vor p liegt (mm)
    ort: list[float] | None = None


@dataclass
class WegPruefer:
    """Einführwege für die Teile eines Bauplans. ``koerper``: Name → Körper (Weltlage)."""

    koerper: dict[str, Koerper]
    ausschluss: set[frozenset] = field(default_factory=set)  # erlaubt oder durchdringend
    gewinde: dict[frozenset, np.ndarray] = field(default_factory=dict)  # Paar → Gewindeachse
    tests: int = 0
    strahlen: int = 0
    _cache: dict[tuple, dict[str, Sperre]] = field(default_factory=dict)
    _rcache: dict[tuple, rs.Raster] = field(default_factory=dict)
    _endlich: dict[tuple, Sperre | None] = field(default_factory=dict)

    # -- Paare --------------------------------------------------------------------------------------------------

    def _ausgenommen(self, p: str, q: str, d: np.ndarray) -> bool:
        key = frozenset((p, q))
        if key in self.ausschluss:
            return True
        achse = self.gewinde.get(key)
        return achse is not None and abs(float(np.dot(achse, d))) > 0.98

    def _raster(self, name: str, R: np.ndarray, dkey: tuple, h: float,
                fenster: tuple[float, float, float, float] | None) -> rs.Raster:
        k = self.koerper[name]
        proj = k.projektion(R, dkey)
        flaeche = float(np.prod(np.maximum(proj.uv_max - proj.uv_min, h)))
        if flaeche / (h * h) <= 250_000:  # klein genug: ganz rastern und merken
            key = (name, dkey, h)
            r = self._rcache.get(key)
            if r is None:
                if len(self._rcache) > 4000:
                    self._rcache.clear()
                r = rs.rastern(proj.uvw, k.tri, h)
                self._rcache[key] = r
            return r
        return rs.rastern(proj.uvw, k.tri, h, fenster)

    def paar(self, p: str, q: str, d: Any, weg: float | None = None, versatz: Any = None) -> Sperre | None:
        """Sperrt q den Weg von p entlang d (Ausbaurichtung)? ``weg``: endlicher Weg (mm), sonst bis ins Freie.
        ``versatz``: p steht vorher um diesen Vektor verschoben (zweiter Abschnitt eines zweistufigen Wegs)."""
        d = einheit(d)
        if p == q or self._ausgenommen(p, q, d):
            return None
        if weg is not None or versatz is not None:
            vk = None if versatz is None else tuple(int(round(float(c) * 10)) for c in np.asarray(versatz, float))
            key = (p, q, richtung_schluessel(d), None if weg is None else int(round(weg * 10)), vk)
            if key in self._endlich:
                return self._endlich[key]
            out = self._paar(p, q, d, weg, versatz)
            if len(self._endlich) > 200_000:
                self._endlich.clear()
            self._endlich[key] = out
            return out
        return self._paar(p, q, d, None, None)

    def _paar(self, p: str, q: str, d: np.ndarray, weg: float | None, versatz: Any) -> Sperre | None:
        kp, kq = self.koerper[p], self.koerper[q]
        R = basis(d)
        dkey = richtung_schluessel(d)
        pp, pq = kp.projektion(R, dkey), kq.projektion(R, dkey)
        v = np.zeros(3) if versatz is None else R @ np.asarray(versatz, dtype=float)  # (du, dv, dw)
        p_uv_min, p_uv_max = pp.uv_min + v[:2], pp.uv_max + v[:2]
        p_wmin, p_wmax = pp.w_min + v[2], pp.w_max + v[2]
        # Vorprüfung: Hüllrechtecke in der Bildebene, Tiefenbereiche
        if np.any(p_uv_max < pq.uv_min - TOL) or np.any(pq.uv_max < p_uv_min - TOL):
            return None
        if pq.w_max <= p_wmin + TOL:
            return None
        if weg is not None and pq.w_min >= p_wmax + weg - TOL:
            return None
        self.tests += 1
        groesse = float(min(np.max(pp.uv_max - pp.uv_min), np.max(pq.uv_max - pq.uv_min)))
        h = rs.stufe(max(groesse, 0.5))
        lo = np.maximum(p_uv_min, pq.uv_min) - h
        hi = np.minimum(p_uv_max, pq.uv_max) + h
        fenster = (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))
        if versatz is None:
            rp = self._raster(p, R, dkey, h, fenster)
        else:
            f0 = (fenster[0] - v[0], fenster[1] - v[1], fenster[2] - v[0], fenster[3] - v[1])
            rp = self._raster(p, R, dkey, h, f0).verschoben(v[0], v[1], v[2])
        rq = self._raster(q, R, dkey, h, fenster)
        if rp.leer or rq.leer:
            return None
        _, ip, iq = np.intersect1d(rp.keys, rq.keys, assume_unique=True, return_indices=True)
        if not len(ip):
            return None
        vor = rq.wmax[iq] - rp.wmin[ip]
        kand = vor > TOL
        if weg is not None:
            kand &= rq.wmin[iq] < rp.wmax[ip] + weg - TOL
        if not kand.any():
            return None
        ip, iq, vor = ip[kand], iq[kand], vor[kand]
        # exakt bestätigen: stärkste Kandidaten zuerst, dazu eine Stichprobe
        order = np.argsort(-vor)
        wahl = list(order[:MAX_STRAHLEN // 2])
        rest = order[MAX_STRAHLEN // 2:]
        if len(rest):
            rng = np.random.default_rng(len(rest))
            wahl += list(rng.choice(rest, size=min(len(rest), MAX_STRAHLEN // 2), replace=False))
        uv = rs.mitten(rp.keys[ip[wahl]], h)
        bestaetigt = 0
        tiefe = 0.0
        ort = None
        vers = np.zeros(3) if versatz is None else np.asarray(versatz, dtype=float)
        for (u, w2) in uv:
            start = u * R[0] + w2 * R[1]
            self.strahlen += 2
            sp = kp.strahl(start - vers, d)  # p in seiner Lage, Strahl um den Versatz zurückgeschoben
            if sp is None:
                continue
            sp = (sp[0] + v[2], sp[1] + v[2])
            sq = kq.strahl(start, d)
            if sq is None:
                continue
            vorne = sq[1] - sp[0]
            if vorne <= TOL:
                continue
            if weg is not None and sq[0] >= sp[1] + weg - TOL:
                continue
            bestaetigt += 1
            if vorne > tiefe:
                tiefe = float(vorne)
                ort = [round(float(c), 2) for c in start + d * max(sp[0], min(sq[1], sp[1]))]
            if bestaetigt >= 3:
                break
        if bestaetigt >= 2 or (bestaetigt == 1 and tiefe > 1.0):
            return Sperre(p, q, int(len(ip)), bestaetigt, round(tiefe, 2), ort)
        return None

    # -- Teile und Gruppen ----------------------------------------------------------------------------------------

    def sperrer(self, p: str, d: Any, gegen: list[str] | None = None, weg: float | None = None,
                versatz: Any = None) -> dict[str, Sperre]:
        """Alle Teile (aus ``gegen``, sonst alle), die p entlang d sperren; Ergebnisse je Paar gemerkt."""
        d = einheit(d)
        dkey = richtung_schluessel(d)
        namen = list(self.koerper) if gegen is None else list(gegen)
        if weg is None and versatz is None:
            cache = self._cache.setdefault((p, dkey), {})
            fertig = self._cache.setdefault((p, dkey, "fertig"), {})
            out: dict[str, Sperre] = {}
            for q in namen:
                if q == p or q not in self.koerper:
                    continue
                if q not in fertig:
                    s = self.paar(p, q, d)
                    fertig[q] = True  # type: ignore[assignment]
                    if s is not None:
                        cache[q] = s
                if q in cache:
                    out[q] = cache[q]
            return out
        out = {}
        for q in namen:
            if q == p or q not in self.koerper:
                continue
            s = self.paar(p, q, d, weg, versatz)
            if s is not None:
                out[q] = s
        return out

    def fluchtweg(self, teile: list[str], d: Any, gegen: list[str]) -> float:
        """Weg (mm) entlang d, bis die Teile aus den Hüllquadern der Teile heraus sind, mit denen sie sich die Hülle
        teilen (Mutter über das Stiftende, Klotz aus dem Rahmen); mindestens die eigene Ausdehnung entlang d."""
        d = einheit(d)
        eig = [self.koerper[t] for t in teile if t in self.koerper]
        if not eig:
            return 0.0
        lo = np.min([k.bmin for k in eig], axis=0)
        hi = np.max([k.bmax for k in eig], axis=0)
        ecken = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = ecken @ d
        e_min, e_max = float(w.min()), float(w.max())
        L = 0.0
        for q in gegen:
            k = self.koerper.get(q)
            if k is None or q in teile:
                continue
            if np.any(k.bmin > hi + 0.5) or np.any(k.bmax < lo - 0.5):
                continue
            qe = np.array([[x, y, z] for x in (k.bmin[0], k.bmax[0]) for y in (k.bmin[1], k.bmax[1])
                           for z in (k.bmin[2], k.bmax[2])]) @ d
            L = max(L, float(qe.max()) - e_min)
        if L <= 0:  # nichts teilt sich die Hülle: ein kurzes Stück genügt
            L = min(e_max - e_min, 10.0)
        return float(np.ceil((L + 1.0) / 5.0) * 5.0)  # auf 5 mm (Zwischenspeicher)


# ---------------------------------------------------------------------------------------------------------------------
# Werkzeugzugang


def zylinder(p: Any, d: Any, r: float, laenge: float) -> Any:
    """Zylinder (TopoDS) ab Punkt p entlang d."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    d = einheit(d)
    ax = gp_Ax2(gp_Pnt(*map(float, p)), gp_Dir(*map(float, d)))
    return BRepPrimAPI_MakeCylinder(ax, float(r), float(laenge)).Shape()


def ring(p: Any, d: Any, r_innen: float, r_aussen: float, laenge: float) -> Any:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    aussen = zylinder(p, d, r_aussen, laenge)
    if r_innen <= 0:
        return aussen
    innen = zylinder(np.asarray(p, dtype=float) - einheit(d) * 0.5, d, r_innen, laenge + 1.0)
    op = BRepAlgoAPI_Cut(aussen, innen)
    op.Build()
    return op.Shape() if op.IsDone() else aussen


def _box(shape: Any) -> tuple[np.ndarray, np.ndarray]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    x0, y0, z0, x1, y1, z1 = b.Get()
    return np.array([x0, y0, z0]), np.array([x1, y1, z1])


def schnittvolumen(a: Any, b: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    from kevcad_kernel.pruefung.kollision import schnittmenge

    s = schnittmenge(a, b)
    if s is None:
        return 0.0
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, g)
    return abs(float(g.Mass()))


def raum_frei(raum: Any, koerper: dict[str, Koerper], gegen: list[str], ohne: set[str],
              min_volumen: float = 0.5) -> list[tuple[str, float]]:
    """Teile aus ``gegen``, die in den Raum (TopoDS) ragen: [(Name, Volumen mm³)]."""
    lo, hi = _box(raum)
    out = []
    for n in gegen:
        if n in ohne or n not in koerper:
            continue
        k = koerper[n]
        if np.any(k.bmin > hi) or np.any(k.bmax < lo):
            continue
        v = schnittvolumen(raum, k.shape)
        if v > min_volumen:
            out.append((n, round(v, 1)))
    out.sort(key=lambda x: -x[1])
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Standsicherheit


def _huelle(punkte: np.ndarray) -> np.ndarray:
    """Konvexe Hülle in 2D (monotone Kette), gegen den Uhrzeigersinn."""
    pts = np.unique(np.round(np.asarray(punkte, dtype=float), 3), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

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


def _abstand_innen(p: np.ndarray, huelle: np.ndarray) -> float:
    """Abstand von p zum Rand der Hülle (positiv innen, negativ außen)."""
    if len(huelle) < 3:
        if len(huelle) == 0:
            return -math.inf
        # Linie oder Punkt: außen um den Abstand
        d = min(float(np.linalg.norm(p - q)) for q in huelle)
        return -d
    innen = True
    best = math.inf
    n = len(huelle)
    for i in range(n):
        a, b = huelle[i], huelle[(i + 1) % n]
        e = b - a
        L = float(np.linalg.norm(e))
        if L < 1e-9:
            continue
        kreuz = (e[0] * (p[1] - a[1]) - e[1] * (p[0] - a[0])) / L
        if kreuz < 0:
            innen = False
        t = float(np.clip(np.dot(p - a, e) / (L * L), 0.0, 1.0))
        best = min(best, float(np.linalg.norm(p - (a + t * e))))
    return best if innen else -best


@dataclass
class Stand:
    steht: bool  # berührt den Boden
    sicher: bool
    schwerpunkt: list[float]
    abstand: float  # Schwerpunkt bis Rand der Aufstandsfläche (mm, negativ = außerhalb)
    kippwinkel: float | None  # Grad bis zum Kippen über die nächste Kante
    flaeche: list[list[float]]
    masse_g: float
    geschaetzt: bool


def standsicherheit(teile: list[Any], boden_z: float, tol: float = 0.5) -> Stand:
    """Schwerpunkt der Teile über ihrer Aufstandsfläche? ``teile``: BTeil (Masse, Zentrum, Netz)."""
    m = np.array([max(t.masse_g, 1e-6) for t in teile])
    c = np.array([t.zentrum for t in teile])
    sp = (m[:, None] * c).sum(axis=0) / m.sum()
    punkte = []
    for t in teile:
        pos = t.koerper.pos
        if len(pos) and float(t.bmin[2]) <= boden_z + tol:
            unten = pos[pos[:, 2] <= boden_z + tol]
            if len(unten):
                punkte.append(unten[:, :2])
    geschaetzt = any(t.masse_geschaetzt for t in teile)
    if not punkte:
        return Stand(False, False, [round(float(x), 1) for x in sp], -math.inf, None, [], float(m.sum()), geschaetzt)
    h = _huelle(np.concatenate(punkte))
    a = _abstand_innen(sp[:2], h)
    hoehe = max(float(sp[2]) - boden_z, 1e-6)
    kipp = math.degrees(math.atan2(a, hoehe)) if a > 0 else 0.0
    return Stand(True, a > 0, [round(float(x), 1) for x in sp], round(a, 1), round(kipp, 1),
                 [[round(float(x), 1), round(float(y), 1)] for x, y in h], float(m.sum()), geschaetzt)
