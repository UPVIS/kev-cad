"""Netze in einer Blickrichtung rastern: je Bildpunkt die kleinste und größte Tiefe der Oberfläche.

Basis (u, v, w): u und v spannen die Bildebene senkrecht zur Richtung auf, w ist die Tiefe entlang der Richtung
(``pruefung.koerper.basis``). Bildpunkt (i, j) hat seine Mitte bei ((i + 0,5) · h, (j + 0,5) · h); ein Dreieck zählt
für einen Bildpunkt, wenn dessen Mitte im projizierten Dreieck liegt. So ist das Raster dasselbe wie ein Strahl je
Bildpunktmitte gegen das Netz, und ein exakter Strahl (OCCT) an derselben Stelle bestätigt es.

Genutzt für Einführwege (wege.py), Sichtbarkeit und Kamerawahl (bild.py) und das Strichbild (projektion.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

OFF = 1 << 21  # Versatz der Bildpunktnummern (negativ erlaubt)
MUL = 1 << 22
CHUNK = 1_500_000  # Kandidaten je Rechenschritt (Speicher)
EPS = 1e-9


def schluessel(i: np.ndarray, j: np.ndarray) -> np.ndarray:
    return (np.asarray(i, dtype=np.int64) + OFF) * MUL + (np.asarray(j, dtype=np.int64) + OFF)


def zerlege(keys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    keys = np.asarray(keys, dtype=np.int64)
    return keys // MUL - OFF, keys % MUL - OFF


@dataclass
class Raster:
    h: float
    keys: np.ndarray  # int64, sortiert, eindeutig
    wmin: np.ndarray
    wmax: np.ndarray

    def __len__(self) -> int:
        return int(len(self.keys))

    @property
    def leer(self) -> bool:
        return len(self.keys) == 0

    def suche(self, keys: np.ndarray) -> np.ndarray:
        """Index je Schlüssel oder -1."""
        keys = np.asarray(keys, dtype=np.int64)
        if not len(self.keys) or not len(keys):
            return np.full(len(keys), -1, dtype=np.int64)
        idx = np.searchsorted(self.keys, keys)
        idx = np.clip(idx, 0, len(self.keys) - 1)
        ok = self.keys[idx] == keys
        return np.where(ok, idx, -1)

    def verschoben(self, du: float, dv: float, dw: float) -> Raster:
        """Raster eines um (du, dv, dw) verschobenen Körpers (auf ganze Bildpunkte gerundet)."""
        di, dj = int(round(du / self.h)), int(round(dv / self.h))
        i, j = zerlege(self.keys)
        return Raster(self.h, schluessel(i + di, j + dj), self.wmin + dw, self.wmax + dw)


def leer(h: float) -> Raster:
    z = np.zeros(0)
    return Raster(h, np.zeros(0, dtype=np.int64), z, z)


def reduziere(keys: np.ndarray, wmin: np.ndarray, wmax: np.ndarray, h: float) -> Raster:
    if not len(keys):
        return leer(h)
    order = np.argsort(keys, kind="stable")
    k, a, b = keys[order], wmin[order], wmax[order]
    start = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    return Raster(h, k[start], np.minimum.reduceat(a, start), np.maximum.reduceat(b, start))


def vereinige(raster: list[Raster], h: float) -> Raster:
    """Mehrere Raster gleicher Auflösung zu einem (kleinste und größte Tiefe je Bildpunkt)."""
    teile = [r for r in raster if len(r)]
    if not teile:
        return leer(h)
    return reduziere(np.concatenate([r.keys for r in teile]), np.concatenate([r.wmin for r in teile]),
                     np.concatenate([r.wmax for r in teile]), h)


def rastern(uvw: np.ndarray, tri: np.ndarray, h: float,
            fenster: tuple[float, float, float, float] | None = None) -> Raster:
    """Raster eines Netzes in Basiskoordinaten ``uvw`` (n, 3) mit Dreiecken ``tri`` (m, 3) und Bildpunktgröße ``h``.
    ``fenster`` (u0, v0, u1, v1) begrenzt auf einen Ausschnitt."""
    uvw = np.asarray(uvw, dtype=np.float64)
    tri = np.asarray(tri, dtype=np.int64).reshape(-1, 3)
    if not len(tri) or not len(uvw):
        return leer(h)
    P = uvw[tri]  # (m, 3, 3)
    x = P[:, :, 0] / h - 0.5  # Bildpunktmitten liegen auf ganzen Zahlen
    y = P[:, :, 1] / h - 0.5
    w = P[:, :, 2]
    i0 = np.ceil(x.min(axis=1) - EPS).astype(np.int64)
    i1 = np.floor(x.max(axis=1) + EPS).astype(np.int64)
    j0 = np.ceil(y.min(axis=1) - EPS).astype(np.int64)
    j1 = np.floor(y.max(axis=1) + EPS).astype(np.int64)
    if fenster is not None:
        fu0, fv0, fu1, fv1 = fenster
        i0 = np.maximum(i0, int(np.floor(fu0 / h - 0.5)))
        i1 = np.minimum(i1, int(np.ceil(fu1 / h - 0.5)))
        j0 = np.maximum(j0, int(np.floor(fv0 / h - 0.5)))
        j1 = np.minimum(j1, int(np.ceil(fv1 / h - 0.5)))
    x0, x1, x2 = x[:, 0], x[:, 1], x[:, 2]
    y0, y1, y2 = y[:, 0], y[:, 1], y[:, 2]
    det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    ok = (i1 >= i0) & (j1 >= j0) & (np.abs(det) > 1e-12)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return leer(h)
    wid = (i1 - i0 + 1)[idx]
    hei = (j1 - j0 + 1)[idx]
    cnt = wid * hei
    keys_out: list[np.ndarray] = []
    w_out: list[np.ndarray] = []
    # in Häppchen, damit sehr große Dreiecke (Plattenflächen) den Speicher nicht sprengen
    grenzen = np.cumsum(cnt)
    beginn = 0
    while beginn < len(idx):
        basis_sum = grenzen[beginn - 1] if beginn > 0 else 0
        ende = int(np.searchsorted(grenzen, basis_sum + CHUNK, side="right"))
        ende = max(ende, beginn + 1)
        sel = idx[beginn:ende]
        c = cnt[beginn:ende]
        wd = wid[beginn:ende]
        total = int(c.sum())
        t = np.repeat(np.arange(len(sel)), c)
        starts = np.cumsum(c) - c
        local = np.arange(total, dtype=np.int64) - np.repeat(starts, c)
        pi = i0[sel][t] + local % wd[t]
        pj = j0[sel][t] + local // wd[t]
        s = sel[t]
        d = det[s]
        l0 = ((y1[s] - y2[s]) * (pi - x2[s]) + (x2[s] - x1[s]) * (pj - y2[s])) / d
        l1 = ((y2[s] - y0[s]) * (pi - x2[s]) + (x0[s] - x2[s]) * (pj - y2[s])) / d
        l2 = 1.0 - l0 - l1
        inn = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
        if inn.any():
            ww = l0 * w[s, 0] + l1 * w[s, 1] + l2 * w[s, 2]
            keys_out.append(schluessel(pi[inn], pj[inn]))
            w_out.append(ww[inn])
        beginn = ende
    if not keys_out:
        return leer(h)
    k = np.concatenate(keys_out)
    ww = np.concatenate(w_out)
    return reduziere(k, ww, ww, h)


def mitten(keys: np.ndarray, h: float) -> np.ndarray:
    """(u, v) der Bildpunktmitten."""
    i, j = zerlege(keys)
    return np.stack([(i + 0.5) * h, (j + 0.5) * h], axis=1)


def stufe(groesse: float, teile: int = 24, minimum: float = 0.25, maximum: float = 2.0) -> float:
    """Bildpunktgröße als Zweierpotenz-Stufe (0,25 · 2^k), etwa ``groesse / teile``."""
    ziel = min(max(groesse / teile, minimum), maximum)
    k = int(np.floor(np.log2(ziel / 0.25) + 1e-9))
    return float(0.25 * 2 ** max(k, 0))
