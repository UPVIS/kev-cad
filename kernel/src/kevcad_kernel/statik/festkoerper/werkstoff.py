"""Werkstoff im Festkörper (S3): Steifigkeit und Festigkeitskriterium.

Steifigkeit (Voigt, technische Gleitungen, Reihenfolge xx, yy, zz, yz, xz, xy):

- isotrop aus E und ν;
- Druckteile quer zur Schicht weicher (transversal isotrop), wenn der Katalog ``e_modul_z`` nennt: in der Schicht E und
  ν, quer dazu E_z; angenommen ν_zp = ν (Zug quer zur Schicht verkürzt in der Schicht wie sonst) und
  G_zp = E_z / (2 (1 + ν)). Die Schichtnormale ist die Aufbaurichtung in Weltkoordinaten.

Kriterium je Punkt, als Index i = Vergleichsspannung / Festigkeit (Sicherheit = 1 / i):

- von Mises gegen die Festigkeit f (Metall Streckgrenze, Kunststoff Zugfestigkeit);
- Druckteile zusätzlich die Schichtfuge: Normalspannung quer zur Schicht σ_n (nur Zug) und Schub in der Fuge τ gegen
  q·f (q = ``quer_zur_schicht``): i = √((σ_n⁺ / (q f))² + 3 (τ / (q f))²). Für q = 1 und einachsigen Zug quer zur
  Schicht ist das dasselbe wie von Mises. Maßgebend ist der größere Index.
"""

from __future__ import annotations

import numpy as np

VOIGT = ((0, 0), (1, 1), (2, 2), (1, 2), (0, 2), (0, 1))


def _c_lokal(E: float, nu: float, Ez: float | None) -> np.ndarray:
    if not Ez or abs(Ez - E) < 1e-9 * E:
        lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        mu = E / (2 * (1 + nu))
        C = np.zeros((6, 6))
        C[:3, :3] = lam
        C[[0, 1, 2], [0, 1, 2]] += 2 * mu
        C[3, 3] = C[4, 4] = C[5, 5] = mu
        return C
    S = np.zeros((6, 6))
    S[0, 0] = S[1, 1] = 1 / E
    S[2, 2] = 1 / Ez
    S[0, 1] = S[1, 0] = -nu / E
    S[0, 2] = S[2, 0] = S[1, 2] = S[2, 1] = -nu / Ez
    Gz = Ez / (2 * (1 + nu))
    S[3, 3] = S[4, 4] = 1 / Gz
    S[5, 5] = 2 * (1 + nu) / E
    return np.linalg.inv(S)


def _basis(n: np.ndarray) -> np.ndarray:
    """Drehung, deren dritte Spalte n ist (lokal z = Schichtnormale)."""
    n = np.asarray(n, float) / float(np.linalg.norm(n))
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return np.stack([u, v, n], axis=1)


def _tensor(C6: np.ndarray) -> np.ndarray:
    C4 = np.zeros((3, 3, 3, 3))
    for I, (i, j) in enumerate(VOIGT):
        for J, (k, l) in enumerate(VOIGT):
            for a, b in ((i, j), (j, i)):
                for c, d in ((k, l), (l, k)):
                    C4[a, b, c, d] = C6[I, J]
    return C4


def steifigkeit(E: float, nu: float, Ez: float | None = None, normale: np.ndarray | None = None) -> np.ndarray:
    """6×6-Steifigkeit in Weltkoordinaten (N/mm²)."""
    C = _c_lokal(float(E), float(nu), Ez if normale is not None else None)
    if normale is None or not Ez:
        return C
    R = _basis(np.asarray(normale, float))
    C4 = np.einsum("ia,jb,kc,ld,abcd->ijkl", R, R, R, R, _tensor(C), optimize=True)
    return np.array([[C4[i, j, k, l] for (k, l) in VOIGT] for (i, j) in VOIGT])


def mises(s: np.ndarray) -> np.ndarray:
    """Vergleichsspannung nach von Mises aus Voigt-Spannungen (n, 6)."""
    sx, sy, sz, tyz, txz, txy = s.T
    return np.sqrt(np.maximum(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2)
                              + 3 * (tyz ** 2 + txz ** 2 + txy ** 2), 0.0))


def tensor_aus_voigt(s: np.ndarray) -> np.ndarray:
    T = np.empty((len(s), 3, 3))
    for I, (i, j) in enumerate(VOIGT):
        T[:, i, j] = s[:, I]
        T[:, j, i] = s[:, I]
    return T


def schicht(s: np.ndarray, normale: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(σ_n, τ) in der Schichtfuge mit der Normalen ``normale`` (Welt) je Punkt."""
    n = np.asarray(normale, float) / float(np.linalg.norm(normale))
    t = tensor_aus_voigt(s) @ n  # Spannungsvektor auf der Fuge
    sn = t @ n
    tau = np.linalg.norm(t - sn[:, None] * n[None, :], axis=1)
    return sn, tau


def index(s: np.ndarray, f: float, q: float | None = None, normale: np.ndarray | None = None
          ) -> tuple[np.ndarray, np.ndarray | None]:
    """(Index von Mises, Index Schichtfuge oder None) je Punkt; Sicherheit = 1 / max(Index)."""
    i_m = mises(s) / float(f)
    if normale is None or q is None:
        return i_m, None
    sn, tau = schicht(s, normale)
    qf = float(q) * float(f)
    i_s = np.sqrt((np.maximum(sn, 0.0) / qf) ** 2 + 3 * (tau / qf) ** 2)
    return i_m, i_s
