"""Abstand von Punkten zu Dreiecksnetzen (S3): welche Randflächen des FEM-Netzes berühren einen Nachbarn?

Die Lager eines Teils sind die Randdreiecke des FEM-Netzes, deren Schwerpunkt höchstens ``tol`` vom Oberflächennetz
eines tragenden Nachbarn entfernt liegt. Die Nachbarnetze kommen aus der Prüfung (Netz wie im Viewer), auf den
Hüllquader des Teils zugeschnitten. Vorauswahl über einen k-d-Baum der Punkte, dann genauer Abstand Punkt ↔ Dreieck
(nächster Punkt nach Ericson, Real-Time Collision Detection, 5.1.5), vektorisiert.
"""

from __future__ import annotations

import numpy as np

STUECK = 400_000  # Paare je Rechenschritt


def punkt_dreieck(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Abstand je Paar (alle Felder (n, 3))."""
    ab, ac, ap = b - a, c - a, p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    q = np.empty_like(p)
    fertig = np.zeros(len(p), dtype=bool)

    def setze(maske: np.ndarray, wert: np.ndarray) -> None:
        m = maske & ~fertig
        q[m] = wert[m]
        fertig[m] = True

    setze((d1 <= 0) & (d2 <= 0), a)
    setze((d3 >= 0) & (d4 <= d3), b)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(d1 - d3 != 0, d1 / (d1 - d3), 0.0)
        setze((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + v[:, None] * ab)
        setze((d6 >= 0) & (d5 <= d6), c)
        w = np.where(d2 - d6 != 0, d2 / (d2 - d6), 0.0)
        setze((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + w[:, None] * ac)
        den = (d4 - d3) + (d5 - d6)
        w2 = np.where(den != 0, (d4 - d3) / den, 0.0)
        setze((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), b + w2[:, None] * (c - b))
        s = va + vb + vc
        s = np.where(np.abs(s) > 1e-300, s, 1.0)
        v2, w3 = vb / s, vc / s
    setze(np.ones(len(p), dtype=bool), a + v2[:, None] * ab + w3[:, None] * ac)
    return np.linalg.norm(p - q, axis=1)


def abstand(punkte: np.ndarray, pos: np.ndarray, tri: np.ndarray, tol: float) -> np.ndarray:
    """Kleinster Abstand jedes Punkts zum Netz (pos, tri); ``inf`` für Punkte weiter als ``tol``."""
    from scipy.spatial import cKDTree

    P = np.asarray(punkte, float)
    out = np.full(len(P), np.inf)
    if len(P) == 0 or len(tri) == 0:
        return out
    T = np.asarray(pos, float)[np.asarray(tri, dtype=np.int64)]  # (m, 3, 3)
    mitte = T.mean(axis=1)
    radius = np.max(np.linalg.norm(T - mitte[:, None, :], axis=2), axis=1) + tol
    baum = cKDTree(P)
    listen = baum.query_ball_point(mitte, radius)
    laengen = np.fromiter((len(x) for x in listen), dtype=np.int64, count=len(listen))
    if laengen.sum() == 0:
        return out
    ti = np.repeat(np.arange(len(T)), laengen)
    pi = np.fromiter((i for x in listen for i in x), dtype=np.int64, count=int(laengen.sum()))
    for s in range(0, len(ti), STUECK):
        a, b = ti[s:s + STUECK], pi[s:s + STUECK]
        d = punkt_dreieck(P[b], T[a, 0], T[a, 1], T[a, 2])
        np.minimum.at(out, b, d)
    out[out > tol] = np.inf
    return out
