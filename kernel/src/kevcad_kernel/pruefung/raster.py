"""Tiefenraster entlang einer Richtung: Kann ein Teil in Richtung d an einem anderen vorbei, und wie weit?

Beide Netze werden senkrecht zu d auf ein gemeinsames Pixelraster projiziert (Pixelmitten, wie beim Rendern). Je Pixel
zählt die Tiefe w = x·d: vom bewegten Teil p die kleinste (sein hinterster Punkt in dieser Säule), vom Hindernis q die
größte. p stößt beim Herausziehen entlang +d an q, sobald in einem Pixel beide vorkommen und q dort weiter vorn liegt
als der hinterste Punkt von p (qmax > pmin). Das ist bis auf die Pixelgröße exakt, auch für Teile in Bohrungen.

Netze sind Näherungen (Sehnen statt Kreisbögen). Wenige Treffer an Rändern, wie sie bei Passungen ohne Spiel entstehen,
werden deshalb mit exakten Strahlen gegen die B-Rep beider Teile nachgeprüft.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from kevcad_kernel.pruefung.koerper import Koerper, basis, richtung_schluessel

N_PIXEL = 192  # Pixel über die längere Seite des Überlappungsbereichs
GROB_PIXEL = 40  # erster, grober Durchgang
H_MIN = 0.02  # kleinste Pixelgröße in mm
H_MAX = 2.0  # größte Pixelgröße in mm (große Bereiche bekommen mehr Pixel)
MAX_PIXEL = 1_200_000  # Obergrenze Pixel je Raster
MAX_KANDIDATEN = 1_000_000  # Pixel-Dreieck-Paare je Rechenblock
VERSATZ = 0.381966  # Pixelmitten liegen nicht auf runden Koordinaten (genau anliegende Flächen)
TOL = 0.02  # mm: so weit darf q vor dem hintersten Punkt von p liegen (Berühren ist frei)
STICHPROBE = 24  # Pixel, die bei unsicheren Treffern exakt nachgeprüft werden


@dataclass
class Gitter:
    u0: float
    v0: float
    h: float
    nu: int
    nv: int

    def mitte(self, i: np.ndarray, j: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.u0 + (i + 0.5) * self.h, self.v0 + (j + 0.5) * self.h


def gitter_fuer(lo: np.ndarray, hi: np.ndarray, n_pixel: int = N_PIXEL) -> Gitter:
    ext = np.maximum(hi - lo, 1e-9)
    h = max(H_MIN, float(ext.max()) / n_pixel)
    if n_pixel >= N_PIXEL:
        h = min(H_MAX, h)
    if (ext[0] / h + 2) * (ext[1] / h + 2) > MAX_PIXEL:
        h = math.sqrt(float(ext[0] * ext[1]) / MAX_PIXEL) * 1.05
    nu, nv = int(math.ceil(ext[0] / h)) + 2, int(math.ceil(ext[1] / h)) + 2
    return Gitter(float(lo[0]) - h * (1 + VERSATZ), float(lo[1]) - h * (1 + VERSATZ), h, nu, nv)


def _expand(starts: np.ndarray, counts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Je Eintrag k die Werte starts[k] … starts[k] + counts[k] - 1: (Eintragsindex, Wert)."""
    total = int(counts.sum())
    owner = np.repeat(np.arange(len(counts)), counts)
    offs = np.cumsum(counts) - counts
    return owner, starts[owner] + (np.arange(total) - offs[owner])


def rastern(uvw: np.ndarray, tri: np.ndarray, g: Gitter, modus: str) -> np.ndarray:
    """Kleinste (``modus="min"``) oder größte Tiefe je Pixel; leer = +inf bzw. -inf. Form (nu, nv).

    Zeilenweise (Scanline): je Dreieck und Pixelzeile das Intervall der Pixelmitten im Dreieck, die Tiefe aus der
    Ebenengleichung des Dreiecks."""
    leer = np.inf if modus == "min" else -np.inf
    buf = np.full(g.nu * g.nv, leer)
    if not len(tri):
        return buf.reshape(g.nu, g.nv)
    P = uvw[tri]  # (m, 3 Ecken, 3)
    vmin, vmax = P[:, :, 1].min(axis=1), P[:, :, 1].max(axis=1)
    umin, umax = P[:, :, 0].min(axis=1), P[:, :, 0].max(axis=1)
    j0 = np.maximum(np.ceil((vmin - g.v0) / g.h - 0.5), 0).astype(np.int64)
    j1 = np.minimum(np.floor((vmax - g.v0) / g.h - 0.5), g.nv - 1).astype(np.int64)
    e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
    area2 = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    keep = (j1 >= j0) & (np.abs(area2) > 1e-12) & (umax >= g.u0) & (umin <= g.u0 + g.nu * g.h)
    if not keep.any():
        return buf.reshape(g.nu, g.nv)
    P, j0, j1, e1, e2, area2 = P[keep], j0[keep], j1[keep], e1[keep], e2[keep], area2[keep]
    # Ebene w = a·u + b·v + c je Dreieck
    nw = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    na = e1[:, 1] * e2[:, 2] - e1[:, 2] * e2[:, 1]
    nb = e1[:, 2] * e2[:, 0] - e1[:, 0] * e2[:, 2]
    ca, cb = -na / nw, -nb / nw
    cc = P[:, 0, 2] - ca * P[:, 0, 0] - cb * P[:, 0, 1]
    reduce = np.minimum if modus == "min" else np.maximum
    rows = j1 - j0 + 1
    csum = np.cumsum(rows)
    start = 0
    n = len(rows)
    while start < n:
        base = csum[start - 1] if start else 0
        stop = max(int(np.searchsorted(csum, base + MAX_KANDIDATEN // 8, side="right")), start + 1)
        t, jj = _expand(j0[start:stop], rows[start:stop])
        t += start
        vc = g.v0 + (jj + 0.5) * g.h
        # Schnitt der Zeile mit den drei Kanten
        lo = np.full(len(t), np.inf)
        hi = np.full(len(t), -np.inf)
        for a_i, b_i in ((0, 1), (1, 2), (2, 0)):
            pa, pb = P[t, a_i], P[t, b_i]
            dv = pb[:, 1] - pa[:, 1]
            with np.errstate(divide="ignore", invalid="ignore"):
                s = (vc - pa[:, 1]) / dv
            ok = (dv != 0) & (s >= 0) & (s <= 1)
            u = pa[:, 0] + s * (pb[:, 0] - pa[:, 0])
            lo = np.where(ok, np.minimum(lo, u), lo)
            hi = np.where(ok, np.maximum(hi, u), hi)
        i0 = np.maximum(np.ceil((lo - g.u0) / g.h - 0.5), 0)
        i1 = np.minimum(np.floor((hi - g.u0) / g.h - 0.5), g.nu - 1)
        good = np.isfinite(i0) & np.isfinite(i1) & (i1 >= i0)
        if good.any():
            t, jj = t[good], jj[good]
            i0, i1 = i0[good].astype(np.int64), i1[good].astype(np.int64)
            cnt = i1 - i0 + 1
            sub = 0
            # Pixel in Blöcken ausrollen
            ccum = np.cumsum(cnt)
            while sub < len(cnt):
                b0 = ccum[sub - 1] if sub else 0
                s1 = max(int(np.searchsorted(ccum, b0 + MAX_KANDIDATEN, side="right")), sub + 1)
                r, ii = _expand(i0[sub:s1], cnt[sub:s1])
                r += sub
                tt, jr = t[r], jj[r]
                uc = g.u0 + (ii + 0.5) * g.h
                w = ca[tt] * uc + cb[tt] * (g.v0 + (jr + 0.5) * g.h) + cc[tt]
                reduce.at(buf, ii * g.nv + jr, w)
                sub = s1
        start = stop
    return buf.reshape(g.nu, g.nv)


@dataclass
class Sperre:
    """Ergebnis von ``blockiert``: blockiert ja/nein, Treffer-Pixel, Ort des Anstoßens (Welt)."""

    blockiert: bool
    pixel: int = 0
    ort: tuple[float, float, float] | None = None
    exakt: bool = False


FREI = Sperre(False)


def _ueberlappung(Pp, Pq) -> tuple[np.ndarray, np.ndarray] | None:
    lo = np.maximum(Pp.uv_min, Pq.uv_min)
    hi = np.minimum(Pp.uv_max, Pq.uv_max)
    if np.any(hi - lo <= 0):
        return None
    return lo, hi


def blockiert(p: Koerper, q: Koerper, d: np.ndarray, tol: float = TOL) -> Sperre:
    """Stößt p beim Herausziehen entlang d (bis ins Unendliche) an q?"""
    R = basis(d)
    key = richtung_schluessel(R[2])
    Pp, Pq = p.projektion(R, key), q.projektion(R, key)
    if Pq.w_max <= Pp.w_min + tol or not len(p.tri) or not len(q.tri):
        return FREI
    box = _ueberlappung(Pp, Pq)
    if box is None:
        return FREI
    # Erst grob: deutliche Sperren (viele Treffer) stehen damit schon fest
    for n_px, mindest in ((GROB_PIXEL, 8), (N_PIXEL, 30)):
        g = gitter_fuer(*box, n_pixel=n_px)
        pmin = rastern(Pp.uvw, p.tri, g, "min")
        qmax = rastern(Pq.uvw, q.tri, g, "max")
        hit = qmax > pmin + tol
        n = int(np.count_nonzero(hit))
        if n == 0:
            continue
        ii, jj = np.nonzero(hit)
        margin = (qmax - pmin)[ii, jj]
        best = int(np.argmax(margin))
        pu, pv = g.mitte(ii[best], jj[best])
        ort = pu * R[0] + pv * R[1] + float(pmin[ii[best], jj[best]]) * R[2]
        p_count = int(np.count_nonzero(np.isfinite(pmin)))
        if n >= mindest and n >= 0.05 * max(p_count, 1):
            return Sperre(True, n, tuple(float(x) for x in ort))
    if n == 0:
        return FREI
    # Wenige Treffer: Randfehler der Netze oder echtes dünnes Hindernis? Exakt mit Strahlen nachprüfen
    order = np.argsort(-margin)
    pick = order[:STICHPROBE // 2]
    if len(order) > len(pick):
        rest = order[len(pick):]
        step = max(1, len(rest) // (STICHPROBE - len(pick)))
        pick = np.concatenate([pick, rest[::step][:STICHPROBE - len(pick)]])
    for k in pick:
        u, v = g.mitte(ii[k], jj[k])
        start = u * R[0] + v * R[1]
        sp = p.strahl(start, R[2])
        sq = q.strahl(start, R[2])
        if sp is None or sq is None:
            continue
        if sq[1] > sp[0] + tol:
            ort = start + sp[0] * R[2]
            return Sperre(True, n, tuple(float(x) for x in ort), exakt=True)
    return Sperre(False, n, exakt=True)


def luecke(c: Koerper, q: Koerper, d: np.ndarray, tol: float = TOL) -> float | None:
    """Wie weit kann c entlang d rücken, bis es an q stößt? None, wenn q nicht im Weg liegt (Näherung: je Pixel die
    vordere Fläche von q, die ganz vor c liegt)."""
    R = basis(d)
    key = richtung_schluessel(R[2])
    Pc, Pq = c.projektion(R, key), q.projektion(R, key)
    if Pq.w_max <= Pc.w_min or not len(c.tri) or not len(q.tri):
        return None
    box = _ueberlappung(Pc, Pq)
    if box is None:
        return None
    g = gitter_fuer(*box)
    cmax = rastern(Pc.uvw, c.tri, g, "max")
    qmin = rastern(Pq.uvw, q.tri, g, "min")
    ok = np.isfinite(cmax) & np.isfinite(qmin) & (qmin >= cmax - tol)
    if not ok.any():
        return None
    return max(0.0, float((qmin - cmax)[ok].min()))
