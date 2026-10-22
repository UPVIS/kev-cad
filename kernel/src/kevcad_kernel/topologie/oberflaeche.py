"""Oberfläche aus einem Feld: Marching Cubes, Glätten, Netzwerte.

- **Marching Cubes** auf einem regelmäßigen Gitter, innen ist ``f < 0``. Die Fallunterscheidung (256 Fälle) wird beim
  ersten Aufruf aus den Würfelflächen erzeugt statt aus einer abgeschriebenen Tabelle: Auf jeder Würfelfläche liegen 0, 2
  oder 4 Schnittpunkte; bei 4 (mehrdeutig) trennt die Fläche die inneren Ecken voneinander. Die Regel hängt nur von den
  vier Ecken der Fläche ab, Nachbarwürfel entscheiden also gleich: Das Netz ist geschlossen und mannigfaltig. Die
  Schnittpunkte bilden Ringe (jeder Punkt liegt auf zwei Flächen), jeder Ring wird ein Fächer aus Dreiecken, nach außen
  orientiert (vom inneren zum äußeren Eckpunkt).
- Punkte werden über die Kante des Gitters geteilt (Nummer = Knoten · 3 + Richtung), das Netz ist also indiziert.
- **Glätten** nach Taubin (λ/μ, schrumpft nicht), auf Wunsch nur für ausgewählte Punkte (die Flächen des Ausgangsteils
  bleiben, nur die neu entstandenen Schnittflächen werden rund).
"""

from __future__ import annotations

import functools
from typing import Any

import numpy as np

ECKEN = np.array([(c & 1, (c >> 1) & 1, (c >> 2) & 1) for c in range(8)])
KANTEN: list[tuple[int, int, int]] = []  # (Ecke a, Ecke b, Achse)
for _achse in range(3):
    _bit = 1 << _achse
    for _c in range(8):
        if not _c & _bit:
            KANTEN.append((_c, _c | _bit, _achse))


def _kante(a: int, b: int) -> int:
    a, b = min(a, b), max(a, b)
    for i, (x, y, _) in enumerate(KANTEN):
        if x == a and y == b:
            return i
    raise KeyError((a, b))


def _flaechen() -> list[list[int]]:
    """Je Würfelfläche die vier Ecken im Umlauf."""
    out = []
    for achse in range(3):
        b, c = [x for x in range(3) if x != achse]
        for seite in (0, 1):
            ecken = []
            for ub, uc in ((0, 0), (1, 0), (1, 1), (0, 1)):
                ecken.append((seite << achse) | (ub << b) | (uc << c))
            out.append(ecken)
    return out


@functools.lru_cache(maxsize=1)
def tabelle() -> np.ndarray:
    """(256, 16) Kantennummern der Dreiecke je Fall, -1 = Ende."""
    flaechen = _flaechen()
    tab = np.full((256, 16), -1, dtype=np.int64)
    for m in range(256):
        innen = [(m >> c) & 1 for c in range(8)]
        nachbar: dict[int, list[int]] = {}
        for ecken in flaechen:
            k = [(ecken[i], ecken[(i + 1) % 4]) for i in range(4)]
            wechsel = [i for i in range(4) if innen[k[i][0]] != innen[k[i][1]]]
            paare: list[tuple[int, int]] = []
            if len(wechsel) == 2:
                paare.append((_kante(*k[wechsel[0]]), _kante(*k[wechsel[1]])))
            elif len(wechsel) == 4:
                # mehrdeutig: jede innere Ecke für sich abschneiden (ihre beiden Kanten verbinden)
                for i in range(4):
                    if innen[ecken[i]]:
                        vor = k[(i - 1) % 4]
                        nach = k[i]
                        paare.append((_kante(*vor), _kante(*nach)))
            for a, b in paare:
                nachbar.setdefault(a, []).append(b)
                nachbar.setdefault(b, []).append(a)
        ringe: list[list[int]] = []
        frei = set(nachbar)
        while frei:
            start = min(frei)
            ring = [start]
            frei.discard(start)
            vorher, jetzt = None, start
            while True:
                kand = [x for x in nachbar[jetzt] if x != vorher]
                nxt = kand[0] if kand else nachbar[jetzt][0]
                if nxt == start:
                    break
                ring.append(nxt)
                frei.discard(nxt)
                vorher, jetzt = jetzt, nxt
            ringe.append(ring)
        dreiecke: list[int] = []
        for ring in ringe:
            pos = np.array([(ECKEN[KANTEN[e][0]] + ECKEN[KANTEN[e][1]]) / 2.0 for e in ring])
            n = np.zeros(3)
            for i in range(len(ring)):
                p, q = pos[i], pos[(i + 1) % len(ring)]
                n += np.cross(p, q)
            ref = np.zeros(3)
            for e in ring:
                a, b, _ = KANTEN[e]
                ref += (ECKEN[b] - ECKEN[a]) if innen[a] else (ECKEN[a] - ECKEN[b])
            if np.dot(n, ref) < 0:
                ring = ring[::-1]
            for i in range(1, len(ring) - 1):
                dreiecke += [ring[0], ring[i], ring[i + 1]]
        assert len(dreiecke) <= 15, (m, dreiecke)
        tab[m, : len(dreiecke)] = dreiecke
    return tab


def marching_cubes(f: np.ndarray, h: float | tuple[float, float, float] = 1.0,
                   ursprung: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[np.ndarray, np.ndarray]:
    """Fläche ``f = 0`` des Knotenfelds ``f`` (nx, ny, nz), innen ``f < 0``. Rückgabe: Punkte (n, 3) in mm (Knoten i
    liegt bei ursprung + i h), Dreiecke (m, 3), nach außen orientiert."""
    f = np.asarray(f, dtype=np.float64)
    nx, ny, nz = f.shape
    hv = np.broadcast_to(np.asarray(h, dtype=np.float64), (3,))
    innen = f < 0
    cfg = np.zeros((nx - 1, ny - 1, nz - 1), dtype=np.int64)
    for c, (dx, dy, dz) in enumerate(ECKEN):
        cfg |= innen[dx:dx + nx - 1, dy:dy + ny - 1, dz:dz + nz - 1].astype(np.int64) << c
    zellen = np.flatnonzero((cfg != 0) & (cfg != 255))
    if len(zellen) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    cfgz = cfg.reshape(-1)[zellen]
    ci, cj, ck = np.unravel_index(zellen, cfg.shape)
    tab = tabelle()
    # Kante e einer Zelle → globale Kante: (Knoten der unteren Ecke) * 3 + Achse
    kante_basis = np.array([KANTEN[e][0] for e in range(12)])
    kante_achse = np.array([KANTEN[e][2] for e in range(12)])
    tris = []
    for s in range(5):
        e = tab[cfgz, 3 * s:3 * s + 3]
        ok = e[:, 0] >= 0
        if not ok.any():
            continue
        e = e[ok]
        i, j, k = ci[ok], cj[ok], ck[ok]
        ids = np.empty_like(e)
        for t in range(3):
            o = ECKEN[kante_basis[e[:, t]]]
            knoten = np.ravel_multi_index((i + o[:, 0], j + o[:, 1], k + o[:, 2]), f.shape)
            ids[:, t] = knoten * 3 + kante_achse[e[:, t]]
        tris.append(ids)
    alle = np.concatenate(tris)
    eindeutig, inv = np.unique(alle.reshape(-1), return_inverse=True)
    dreiecke = inv.reshape(-1, 3)
    knoten = eindeutig // 3
    achse = eindeutig % 3
    a = np.stack(np.unravel_index(knoten, f.shape), axis=1)
    b = a.copy()
    b[np.arange(len(b)), achse] += 1
    fa = f[a[:, 0], a[:, 1], a[:, 2]]
    fb = f[b[:, 0], b[:, 1], b[:, 2]]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(np.abs(fb - fa) > 1e-300, (0.0 - fa) / (fb - fa), 0.5)
    t = np.clip(t, 0.0, 1.0)
    p = a + t[:, None] * (b - a)
    punkte = np.asarray(ursprung, dtype=np.float64)[None, :] + p * hv[None, :]
    # entartete Dreiecke (zwei gleiche Punkte) weglassen
    d = dreiecke
    ok = (d[:, 0] != d[:, 1]) & (d[:, 1] != d[:, 2]) & (d[:, 0] != d[:, 2])
    return punkte, d[ok]


def nachbarn(n: int, dreiecke: np.ndarray) -> Any:
    import scipy.sparse as sp

    d = dreiecke
    r = np.concatenate([d[:, 0], d[:, 1], d[:, 2], d[:, 1], d[:, 2], d[:, 0]])
    c = np.concatenate([d[:, 1], d[:, 2], d[:, 0], d[:, 0], d[:, 1], d[:, 2]])
    A = sp.coo_matrix((np.ones(len(r)), (r, c)), shape=(n, n)).tocsr()
    A.data[:] = 1.0
    return A


def glaetten(punkte: np.ndarray, dreiecke: np.ndarray, beweglich: np.ndarray | None = None, schritte: int = 10,
             lam: float = 0.5, mu: float = -0.53) -> np.ndarray:
    """Taubin-Glättung (gleich gewichtete Nachbarn); ``beweglich`` (n,) bool: nur diese Punkte bewegen sich."""
    A = nachbarn(len(punkte), dreiecke)
    grad = np.asarray(A.sum(axis=1)).reshape(-1)
    grad[grad == 0] = 1.0
    p = punkte.copy()
    m = np.ones(len(p), dtype=bool) if beweglich is None else beweglich
    for _ in range(schritte):
        for f in (lam, mu):
            mitte = (A @ p) / grad[:, None]
            p[m] += f * (mitte[m] - p[m])
    return p


def volumen(punkte: np.ndarray, dreiecke: np.ndarray) -> float:
    a, b, c = punkte[dreiecke[:, 0]], punkte[dreiecke[:, 1]], punkte[dreiecke[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def flaeche(punkte: np.ndarray, dreiecke: np.ndarray) -> float:
    a, b, c = punkte[dreiecke[:, 0]], punkte[dreiecke[:, 1]], punkte[dreiecke[:, 2]]
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


def offene_kanten(dreiecke: np.ndarray) -> int:
    """Anzahl der Kanten, die nicht genau zwei Dreiecke haben (0 = geschlossen und mannigfaltig)."""
    d = dreiecke
    k = np.concatenate([d[:, [0, 1]], d[:, [1, 2]], d[:, [2, 0]]])
    k = np.sort(k, axis=1)
    _, n = np.unique(k, axis=0, return_counts=True)
    return int(np.sum(n != 2))


def normalen(punkte: np.ndarray, dreiecke: np.ndarray) -> np.ndarray:
    a, b, c = punkte[dreiecke[:, 0]], punkte[dreiecke[:, 1]], punkte[dreiecke[:, 2]]
    fn = np.cross(b - a, c - a)
    vn = np.zeros_like(punkte)
    for i in range(3):
        np.add.at(vn, dreiecke[:, i], fn)
    n = np.linalg.norm(vn, axis=1, keepdims=True)
    return vn / np.maximum(n, 1e-300)
