"""Kleinste Wandstärke eines Teils über sein Dreiecksnetz (für ``min_wand``).

Von Punkten auf der Oberfläche (Dreiecksmitten, nach Fläche gewichtet ausgewählt) geht je ein Strahl entgegen der
Außennormale ins Material; die Entfernung bis zum nächsten Treffer ist die Wandstärke dort. Genau auf die Sehnenabweichung
des Netzes (Standard 0,1 mm). Möller-Trumbore mit numpy, in Blöcken.
"""

from __future__ import annotations

import numpy as np

MAX_STRAHLEN = 700


def kleinste_wand(positions: np.ndarray, triangles: np.ndarray, normals: np.ndarray | None = None,
                  M: np.ndarray | None = None, max_strahlen: int = MAX_STRAHLEN) -> tuple[float | None, np.ndarray | None]:
    """(kleinste Wandstärke in mm, Ort in Weltkoordinaten) oder (None, None) ohne Netz."""
    P = np.asarray(positions, dtype=float).reshape(-1, 3)
    T = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if len(T) == 0:
        return None, None
    if M is not None:
        P = P @ M[:3, :3].T + M[:3, 3]
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    flaeche = np.linalg.norm(n, axis=1)
    ok = flaeche > 1e-12
    a, b, c, n, flaeche = a[ok], b[ok], c[ok], n[ok], flaeche[ok]
    if not len(a):
        return None, None
    n = n / flaeche[:, None]
    if normals is not None:
        N = np.asarray(normals, dtype=float).reshape(-1, 3)
        if M is not None:
            N = N @ M[:3, :3].T
        vn = (N[T[ok, 0]] + N[T[ok, 1]] + N[T[ok, 2]])
        flip = np.einsum("ij,ij->i", vn, n) < 0
        n[flip] *= -1  # Netz mit vertauschter Reihenfolge: Normalen der Punkte gelten
    mitte = (a + b + c) / 3
    rng = np.random.default_rng(0)
    k = min(max_strahlen, len(mitte))
    w = flaeche / flaeche.sum()
    wahl = rng.choice(len(mitte), size=k, replace=False, p=w) if k < len(mitte) else np.arange(len(mitte))
    o = mitte[wahl] - n[wahl] * 1e-4
    d = -n[wahl]
    e1, e2 = b - a, c - a
    best = np.full(len(o), np.inf)
    block = max(1, min(64, 300_000 // max(1, len(a))))  # Speicher je Block etwa 300 000 Strahl-Dreieck-Paare
    for s in range(0, len(o), block):
        oo, dd = o[s:s + block], d[s:s + block]
        pvec = np.cross(dd[:, None, :], e2[None, :, :])
        det = np.einsum("tj,rtj->rt", e1, pvec)
        mask = np.abs(det) > 1e-12
        inv = np.where(mask, 1.0 / np.where(mask, det, 1.0), 0.0)
        tvec = oo[:, None, :] - a[None, :, :]
        u = np.einsum("rtj,rtj->rt", tvec, pvec) * inv
        qvec = np.cross(tvec, e1[None, :, :])
        v = np.einsum("rj,rtj->rt", dd, qvec) * inv
        t = np.einsum("tj,rtj->rt", e2, qvec) * inv
        hit = mask & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-3)
        t = np.where(hit, t, np.inf)
        best[s:s + block] = np.minimum(best[s:s + block], t.min(axis=1))
    if not np.isfinite(best).any():
        return None, None
    i = int(np.argmin(best))
    return float(best[i]), o[i] + d[i] * best[i] / 2
