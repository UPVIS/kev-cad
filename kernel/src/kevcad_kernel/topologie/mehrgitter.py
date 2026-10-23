"""Lineare Elastizität auf einem Voxelgitter: Hexaeder mit acht Knoten (H8), geometrisches Mehrgitter als Vorkonditionierer
für das CG-Verfahren (wie Amir, Aage, Lazarov 2014, „On multigrid-CG for efficient topology optimization“).

Gitter: ``nx × ny × nz`` gleiche Würfel der Kante ``h`` (mm), Knoten ``(nx+1) × (ny+1) × (nz+1)``, je Knoten drei
Verschiebungen. Ein Element ``e`` hat die Steifigkeit ``s_e · h · KE`` (``KE`` für den Einheitswürfel mit E = 1 aus der
6×6-Steifigkeit ``C``, bei Druckteilen quer zur Schicht weicher). Elemente außerhalb des Bauraums haben ``s_e = 0``.

Mehrgitter:

- Ebenen durch Halbieren (Elementzahl je Richtung gerade, das Gitter wird dafür aufgefüllt), trilineare Prolongation
  ``P`` je Richtung über Verschiebungen im Feld (keine Matrizen).
- Grobe Operatoren exakt nach Galerkin ``Pᵀ K P``, aber elementweise: Ein grobes Element hat acht Kinder, und
  ``Pᵀ K P`` ist die Summe ``Σ_c P_cᵀ K_kind P_c`` mit festen 24×24-Matrizen ``P_c`` (gleiche Teilung bei allen
  Elementen). Ebene 1 ist damit ``Σ_c s_kind · (P_cᵀ KE P_c)``, ein Matrixprodukt; tiefere Ebenen je Element.
- Lager (feste Freiheitsgrade) sind Masken. Ein grober Knoten ist fest, sobald ein feiner Knoten in seinem Einfluss
  (3×3×3) fest ist; damit ist die maskierte Galerkin-Rechnung genau ``P'ᵀ A P'`` und der V-Zyklus symmetrisch.
- Glätter: Chebyshev vom Grad 2 auf l1-Jacobi (Diagonale = Summe der Beträge je Zeile, aus den Elementmatrizen;
  Baker, Falgout, Kolev, Yang 2011), stabil auch bei 1e-6 Steifigkeit neben 1 (gedämpftes Jacobi mit fester Dämpfung
  divergiert dort); gröbste Ebene direkt (SuperLU, wenige tausend Freiheitsgrade).

Alles auf der feinsten Ebene läuft matrixfrei über Feldausschnitte (BLAS für 24×24 · 24×n), auf den groben Ebenen über
Indexlisten der aktiven Elemente.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import scipy.sparse as sp

OFFS = [(dx, dy, dz) for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]  # lokaler Knoten a = dx + 2 dy + 4 dz
GROB_MAX = 6_000  # Freiheitsgrade der gröbsten Ebene (direkt gelöst)
OMEGA = 1.0  # Dämpfung des l1-Jacobi-Glätters (konvergiert für jede SPD-Matrix mit 1)
GLAETTEN = 2  # Grad des Chebyshev-Glätters vor und nach der Grobgitterkorrektur


def hex8_ke(C: np.ndarray) -> np.ndarray:
    """Steifigkeit (24×24) des Einheitswürfels für die 6×6-Steifigkeit ``C`` (Voigt xx, yy, zz, yz, xz, xy mit
    technischen Gleitungen), 2×2×2 Gauß-Punkte (exakt für trilineare Ansätze). Freiheitsgrad 3 a + c."""
    g = (0.5 - 0.5 / math.sqrt(3.0), 0.5 + 0.5 / math.sqrt(3.0))
    KE = np.zeros((24, 24))
    for xi in g:
        for eta in g:
            for zeta in g:
                B = np.zeros((6, 24))
                for a, (dx, dy, dz) in enumerate(OFFS):
                    fx = xi if dx else 1 - xi
                    fy = eta if dy else 1 - eta
                    fz = zeta if dz else 1 - zeta
                    nx = (1 if dx else -1) * fy * fz
                    ny = fx * (1 if dy else -1) * fz
                    nz = fx * fy * (1 if dz else -1)
                    c = 3 * a
                    B[0, c] = nx
                    B[1, c + 1] = ny
                    B[2, c + 2] = nz
                    B[3, c + 1], B[3, c + 2] = nz, ny
                    B[4, c], B[4, c + 2] = nz, nx
                    B[5, c], B[5, c + 1] = ny, nx
                KE += B.T @ C @ B / 8.0
    return KE


def hex8_b_mitte() -> np.ndarray:
    """Verzerrungs-Verschiebungs-Matrix (6×24) in der Mitte des Einheitswürfels (für Spannungen je Element)."""
    B = np.zeros((6, 24))
    for a, (dx, dy, dz) in enumerate(OFFS):
        nx = (1 if dx else -1) * 0.25
        ny = (1 if dy else -1) * 0.25
        nz = (1 if dz else -1) * 0.25
        c = 3 * a
        B[0, c] = nx
        B[1, c + 1] = ny
        B[2, c + 2] = nz
        B[3, c + 1], B[3, c + 2] = nz, ny
        B[4, c], B[4, c + 2] = nz, nx
        B[5, c], B[5, c + 1] = ny, nx
    return B


def kind_interpolation() -> np.ndarray:
    """P_c (8, 24, 24): Verschiebungen der acht Knoten des Kinds c aus denen des groben Elements (trilinear)."""
    P = np.zeros((8, 24, 24))
    for c, (cx, cy, cz) in enumerate(OFFS):
        W = np.zeros((8, 8))
        for a, (dx, dy, dz) in enumerate(OFFS):
            xi, eta, zeta = (cx + dx) / 2.0, (cy + dy) / 2.0, (cz + dz) / 2.0
            for b, (bx, by, bz) in enumerate(OFFS):
                W[a, b] = (xi if bx else 1 - xi) * (eta if by else 1 - eta) * (zeta if bz else 1 - zeta)
        P[c] = np.kron(W, np.eye(3))
    return P


# -- Prolongation und Restriktion je Richtung -------------------------------------------------------------------------


def _prolong_achse(c: np.ndarray, achse: int) -> np.ndarray:
    n = c.shape[achse]
    form = list(c.shape)
    form[achse] = 2 * n - 1
    f = np.zeros(form, dtype=c.dtype)
    sl = [slice(None)] * c.ndim
    sl[achse] = slice(0, None, 2)
    f[tuple(sl)] = c
    a = [slice(None)] * c.ndim
    b = [slice(None)] * c.ndim
    a[achse] = slice(0, n - 1)
    b[achse] = slice(1, n)
    sl[achse] = slice(1, None, 2)
    f[tuple(sl)] = 0.5 * (c[tuple(a)] + c[tuple(b)])
    return f


def _restrict_achse(f: np.ndarray, achse: int) -> np.ndarray:
    n = (f.shape[achse] + 1) // 2
    sl = [slice(None)] * f.ndim
    sl[achse] = slice(0, None, 2)
    c = f[tuple(sl)].copy()
    sl[achse] = slice(1, None, 2)
    ungerade = 0.5 * f[tuple(sl)]  # n - 1 Werte zwischen den groben Knoten
    a = [slice(None)] * f.ndim
    b = [slice(None)] * f.ndim
    a[achse] = slice(0, n - 1)
    b[achse] = slice(1, n)
    c[tuple(a)] += ungerade
    c[tuple(b)] += ungerade
    return c


def prolong(c: np.ndarray) -> np.ndarray:
    """(3, nx+1, ny+1, nz+1) grob → fein (trilinear)."""
    f = c
    for achse in (1, 2, 3):
        f = _prolong_achse(f, achse)
    return f


def restrict(f: np.ndarray) -> np.ndarray:
    c = f
    for achse in (1, 2, 3):
        c = _restrict_achse(c, achse)
    return c


# -- Ebenen -----------------------------------------------------------------------------------------------------------


class Ebene:
    """Eine Ebene des Mehrgitters: Elemente (aktiv), Knotenmaske der freien Freiheitsgrade, Diagonale."""

    def __init__(self, ne: tuple[int, int, int]) -> None:
        self.ne = ne
        self.nn = (ne[0] + 1, ne[1] + 1, ne[2] + 1)
        self.frei: np.ndarray = np.ones((3,) + self.nn, dtype=bool)
        self.diag: np.ndarray = np.ones((3,) + self.nn)
        # nur grobe Ebenen: aktive Elemente, ihre Knoten (linear) und Elementmatrizen (ne_akt, 24, 24)
        self.akt: np.ndarray | None = None
        self.enode: np.ndarray | None = None
        self.K: np.ndarray | None = None

    def knoten_index(self, akt: np.ndarray) -> np.ndarray:
        """Lineare Knotennummern (ne_akt, 8) der aktiven Elemente (lineare Elementnummern, C-Reihenfolge)."""
        nx, ny, nz = self.ne
        i, j, k = np.unravel_index(akt, self.ne)
        out = np.empty((len(akt), 8), dtype=np.int64)
        for a, (dx, dy, dz) in enumerate(OFFS):
            out[:, a] = np.ravel_multi_index((i + dx, j + dy, k + dz), self.nn)
        return out


class Mehrgitter:
    """Löser für ``K(s) u = f`` auf dem Voxelgitter. ``KE`` Einheitswürfel, ``h`` Kantenlänge (mm), ``fest`` (3, nn)
    feste Freiheitsgrade (Lager), ``aktiv`` (ne) Bauraum. ``setze(s)`` vor jedem Lösen (Steifigkeitsfaktoren je
    Element, 0 außerhalb)."""

    def __init__(self, KE: np.ndarray, h: float, aktiv: np.ndarray, fest: np.ndarray, grob_max: int = GROB_MAX
                 ) -> None:
        t0 = time.perf_counter()
        self.KE = KE * float(h)
        self.KE32 = self.KE.astype(np.float32)
        self.h = float(h)
        ne = tuple(int(n) for n in aktiv.shape)
        stufen = 1
        # so viele Ebenen, bis die gröbste höchstens grob_max Freiheitsgrade hat (geschätzt über den Bauraum)
        anteil = float(aktiv.mean()) if aktiv.size else 1.0
        while True:
            f = 2 ** (stufen - 1)
            if 3 * anteil * (ne[0] / f + 1) * (ne[1] / f + 1) * (ne[2] / f + 1) <= grob_max or min(ne) / f < 4:
                break
            stufen += 1
        teiler = 2 ** (stufen - 1)
        self.ne_original = ne
        self.ne = tuple(int(math.ceil(n / teiler) * teiler) for n in ne)
        self.stufen = stufen
        a = np.zeros(self.ne, dtype=bool)
        a[: ne[0], : ne[1], : ne[2]] = aktiv
        self.aktiv = a
        fe = np.zeros((3,) + tuple(n + 1 for n in self.ne), dtype=bool)
        fe[:, : ne[0] + 1, : ne[1] + 1, : ne[2] + 1] = fest
        self.Pc = kind_interpolation()
        self.G = np.einsum("cai,ab,cbj->cij", self.Pc, self.KE, self.Pc)  # (8, 24, 24): P_cᵀ KE P_c
        self.ebenen: list[Ebene] = []
        e0 = Ebene(self.ne)
        # Knoten, die ein aktives Element berühren
        kn = np.zeros(e0.nn, dtype=bool)
        for dx, dy, dz in OFFS:
            kn[dx:dx + self.ne[0], dy:dy + self.ne[1], dz:dz + self.ne[2]] |= a
        self.fest0 = fe
        e0.frei = kn[None] & ~fe
        # feinste Ebene nur über die aktiven Elemente (Teile füllen ihren Hüllquader oft nur zu einem Viertel)
        self.akt0 = np.flatnonzero(a.reshape(-1))
        self.enode0 = e0.knoten_index(self.akt0)
        self._idx0 = np.ascontiguousarray(self.enode0.T.reshape(-1))
        n0 = int(np.prod(e0.nn))
        # flache Indizes (24, ne): Freiheitsgrad 3 a + c des Elements e liegt bei c · n + Knoten
        self._idx24 = np.ascontiguousarray(
            (np.arange(3)[None, :, None] * n0 + self.enode0.T[:, None, :]).reshape(24, -1))
        self._idx24_flach = self._idx24.reshape(-1)
        self.ebenen.append(e0)
        akt_fein = a
        fest_fein = fe
        for _ in range(1, stufen):
            vorher = self.ebenen[-1]
            nec = tuple(n // 2 for n in vorher.ne)
            e = Ebene(nec)
            # grobes Element aktiv, sobald eines seiner acht Kinder aktiv ist
            ak = np.zeros(nec, dtype=bool)
            for cx, cy, cz in OFFS:
                ak |= akt_fein[cx::2, cy::2, cz::2]
            e.akt = np.flatnonzero(ak.reshape(-1))
            e.enode = e.knoten_index(e.akt)
            knc = np.zeros(e.nn, dtype=bool)
            for dx, dy, dz in OFFS:
                knc[dx:dx + nec[0], dy:dy + nec[1], dz:dz + nec[2]] |= ak
            # fest, wenn ein feiner Knoten im Einfluss (3×3×3) fest ist
            from scipy.ndimage import maximum_filter

            fg = np.stack([maximum_filter(fest_fein[c], size=3, mode="constant")[::2, ::2, ::2] for c in range(3)])
            e.frei = knc[None] & ~fg
            # Kinder je grobem aktivem Element (lineare Nummern der feinen Ebene, -1 = außerhalb/inaktiv)
            ic, jc, kc = np.unravel_index(e.akt, nec)
            kinder = np.empty((len(e.akt), 8), dtype=np.int64)
            for c, (cx, cy, cz) in enumerate(OFFS):
                kinder[:, c] = np.ravel_multi_index((2 * ic + cx, 2 * jc + cy, 2 * kc + cz), vorher.ne)
            e.kinder = kinder  # type: ignore[attr-defined]
            self.ebenen.append(e)
            akt_fein, fest_fein = ak, fg
        self.ms_aufbau = (time.perf_counter() - t0) * 1000
        self.s0: np.ndarray | None = None
        self._lu = None
        self.statistik: dict[str, Any] = {"loesungen": 0, "iterationen": 0}

    # -- Operatoren -----------------------------------------------------------------------------------------------

    def _elemente0(self, U: np.ndarray, dtype: Any = np.float64) -> np.ndarray:
        """Verschiebungen (24, ne_aktiv) der aktiven Elemente der feinsten Ebene, Freiheitsgrad 3 a + c."""
        n = int(np.prod(self.ebenen[0].nn))
        Ue = U.reshape(3, n)[:, self.enode0.T]  # (3, 8, ne)
        return np.ascontiguousarray(np.transpose(Ue, (1, 0, 2)).reshape(24, -1), dtype=dtype)

    def _apply0(self, U: np.ndarray) -> np.ndarray:
        e0 = self.ebenen[0]
        n = int(np.prod(e0.nn))
        # einfache Genauigkeit für das Matrixprodukt (doppelt so schnell; CG und Glätter rechnen doppelt genau)
        Fe = self.KE32 @ self._elemente0(U, np.float32)
        Fe *= self.s_akt32
        F = np.bincount(self._idx24_flach, weights=Fe.reshape(-1), minlength=3 * n)
        return F.reshape((3,) + e0.nn)

    def _apply_grob(self, e: Ebene, U: np.ndarray) -> np.ndarray:
        n = int(np.prod(e.nn))
        Uf = U.reshape(3, n)
        Ue = Uf[:, e.enode]  # (3, ne, 8)
        Ue = np.transpose(Ue, (1, 2, 0)).reshape(len(e.akt), 24)
        Fe = np.einsum("eij,ej->ei", e.K, Ue, optimize=True).reshape(len(e.akt), 8, 3)
        F = np.empty((3, n))
        idx = e.enode.reshape(-1)
        for c in range(3):
            F[c] = np.bincount(idx, weights=Fe[:, :, c].reshape(-1), minlength=n)
        return F.reshape((3,) + e.nn)

    def anwenden(self, stufe: int, U: np.ndarray) -> np.ndarray:
        """A U mit den Masken (Identität auf festen und unberührten Freiheitsgraden)."""
        e = self.ebenen[stufe]
        Um = np.where(e.frei, U, 0.0)
        F = self._apply0(Um) if stufe == 0 else self._apply_grob(e, Um)
        return np.where(e.frei, F, U)

    # -- Steifigkeit setzen --------------------------------------------------------------------------------------

    def setze(self, s: np.ndarray) -> None:
        """Steifigkeitsfaktoren je Element (ne_original); baut Diagonalen, grobe Elementmatrizen und die Zerlegung
        der gröbsten Ebene."""
        s0 = np.zeros(self.ne)
        n0 = self.ne_original
        s0[: n0[0], : n0[1], : n0[2]] = s
        s0[~self.aktiv] = 0.0
        self.s0 = s0
        s_akt = s0.reshape(-1)[self.akt0]
        self.s_akt32 = s_akt.astype(np.float32)
        e0 = self.ebenen[0]
        d = np.abs(self.KE).sum(axis=1)  # (24,) l1-Zeilensummen
        n = int(np.prod(e0.nn))
        gew = d.reshape(8, 3)[:, :, None] * s_akt[None, None, :]  # (8, 3, ne)
        D = np.stack([np.bincount(self._idx0, weights=gew[:, c, :].reshape(-1), minlength=n)
                      for c in range(3)]).reshape((3,) + e0.nn)
        e0.diag = np.where(e0.frei & (D > 0), D, 1.0)
        e0.frei = e0.frei & (D > 0)
        vorher_s = s0.reshape(-1)
        vorher_K = None
        for stufe in range(1, self.stufen):
            e = self.ebenen[stufe]
            kinder = e.kinder  # type: ignore[attr-defined]
            if stufe == 1:
                sk = vorher_s[kinder]  # (ne, 8)
                K = (sk @ self.G.reshape(8, 576)).reshape(-1, 24, 24)
            else:
                vorher = self.ebenen[stufe - 1]
                pos = np.full(int(np.prod(vorher.ne)), -1, dtype=np.int64)
                pos[vorher.akt] = np.arange(len(vorher.akt))
                K = np.zeros((len(e.akt), 24, 24))
                for c in range(8):
                    j = pos[kinder[:, c]]
                    ok = j >= 0
                    if not ok.any():
                        continue
                    Kk = vorher_K[j[ok]]
                    K[ok] += np.matmul(np.matmul(self.Pc[c].T[None], Kk), self.Pc[c][None])
            e.K = K
            vorher_K = K
            # Diagonale
            n = int(np.prod(e.nn))
            dk = np.abs(K).sum(axis=2).reshape(len(e.akt), 8, 3)  # l1-Zeilensummen
            Dg = np.stack([np.bincount(e.enode.reshape(-1), weights=dk[:, :, c].reshape(-1), minlength=n)
                           for c in range(3)]).reshape((3,) + e.nn)
            e.frei = e.frei & (Dg > 0)
            e.diag = np.where(e.frei, Dg, 1.0)
        self._grob_zerlegen()

    def _grob_zerlegen(self) -> None:
        import scipy.sparse.linalg as spla

        e = self.ebenen[-1]
        if self.stufen == 1:
            # nur eine Ebene: Matrix aus den Elementen der feinsten Ebene
            akt = np.flatnonzero(self.aktiv.reshape(-1))
            enode = e.knoten_index(akt)
            K = self.s0.reshape(-1)[akt][:, None, None] * self.KE[None]
        else:
            enode, K = e.enode, e.K
        n = int(np.prod(e.nn))
        dof = (enode[:, :, None] * 3 + np.arange(3)[None, None, :]).reshape(len(enode), 24)
        # Freiheitsgrade in der Reihenfolge (Knoten, Komponente); frei[c, knoten]
        frei = np.transpose(e.frei.reshape(3, n), (1, 0)).reshape(-1)
        r = np.repeat(dof, 24, axis=1).reshape(-1)
        c = np.tile(dof, (1, 24)).reshape(-1)
        A = sp.coo_matrix((K.reshape(-1), (r, c)), shape=(3 * n, 3 * n)).tocsr()
        idx = np.flatnonzero(frei)
        self._grob_idx = idx
        self._grob_n = n
        if len(idx) == 0:
            self._lu = None
            return
        Af = A[idx][:, idx].tocsc()
        self._lu = spla.splu(Af, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0, options={"SymmetricMode": True})

    def _grob_loesen(self, R: np.ndarray) -> np.ndarray:
        e = self.ebenen[-1]
        n = self._grob_n
        r = np.transpose(R.reshape(3, n), (1, 0)).reshape(-1)
        x = np.zeros(3 * n)
        if self._lu is not None:
            x[self._grob_idx] = self._lu.solve(r[self._grob_idx])
        X = np.transpose(x.reshape(n, 3), (1, 0)).reshape((3,) + e.nn)
        return np.where(e.frei, X, 0.0)

    # -- V-Zyklus und CG -------------------------------------------------------------------------------------------

    def glaetten(self, stufe: int, R: np.ndarray, X: np.ndarray | None) -> np.ndarray:
        """Chebyshev-Glätter auf l1-Jacobi (Adams, Brezina, Hu, Tuminaro 2003): Polynom vom Grad ``GLAETTEN`` in
        D⁻¹A, ausgelegt auf [λ/8, λ] mit λ = 1 (für l1-Jacobi ist 1 eine sichere Obergrenze). Symmetrisch, also für CG
        geeignet; gegenüber Jacobi glättet es mit derselben Zahl an Produkten deutlich besser."""
        e = self.ebenen[stufe]
        lmax = 1.0
        lmin = lmax / 8.0
        theta = 0.5 * (lmax + lmin)
        delta = 0.5 * (lmax - lmin)
        sigma = theta / delta
        rho = 1.0 / sigma
        Dinv = 1.0 / e.diag
        r = R.copy() if X is None else R - self.anwenden(stufe, X)
        X = np.zeros_like(R) if X is None else X
        d = Dinv * r / theta
        for _ in range(GLAETTEN - 1):
            X += d
            r -= self.anwenden(stufe, d)
            rho_neu = 1.0 / (2.0 * sigma - rho)
            d = rho_neu * rho * d + (2.0 * rho_neu / delta) * (Dinv * r)
            rho = rho_neu
        X += d
        return X

    def vzyklus(self, stufe: int, R: np.ndarray) -> np.ndarray:
        e = self.ebenen[stufe]
        if stufe == self.stufen - 1:
            return self._grob_loesen(R)
        X = self.glaetten(stufe, R, None)
        Rf = R - self.anwenden(stufe, X)
        g = self.ebenen[stufe + 1]
        Rc = np.where(g.frei, restrict(np.where(e.frei, Rf, 0.0)), 0.0)
        Xc = self.vzyklus(stufe + 1, Rc)
        X += np.where(e.frei, prolong(Xc), 0.0)
        return self.glaetten(stufe, R, X)

    def loese(self, F: np.ndarray, U0: np.ndarray | None = None, tol: float = 1e-5, maxiter: int = 200,
              abbruch: Any = None) -> tuple[np.ndarray, dict[str, Any]]:
        """CG mit V-Zyklus. ``F`` (3, nn_original); Rückgabe U (3, nn_original) und Angaben."""
        t0 = time.perf_counter()
        e0 = self.ebenen[0]
        no = tuple(n + 1 for n in self.ne_original)
        B = np.zeros((3,) + e0.nn)
        B[:, : no[0], : no[1], : no[2]] = F
        B = np.where(e0.frei, B, 0.0)
        X = np.zeros_like(B)
        if U0 is not None:
            X[:, : no[0], : no[1], : no[2]] = U0
            X = np.where(e0.frei, X, 0.0)
        nb = float(np.linalg.norm(B))
        info: dict[str, Any] = {"iterationen": 0, "residuum": 0.0}
        if nb == 0:
            return X[:, : no[0], : no[1], : no[2]], info
        R = B - self.anwenden(0, X)
        Z = self.vzyklus(0, R)
        P = Z.copy()
        rz = float(np.vdot(R, Z))
        it = 0
        res = float(np.linalg.norm(R)) / nb
        while res > tol and it < maxiter:
            if abbruch is not None:
                abbruch()
            AP = self.anwenden(0, P)
            alpha = rz / float(np.vdot(P, AP))
            X += alpha * P
            R -= alpha * AP
            res = float(np.linalg.norm(R)) / nb
            it += 1
            if res <= tol:
                break
            Z = self.vzyklus(0, R)
            rz_neu = float(np.vdot(R, Z))
            P = Z + (rz_neu / rz) * P
            rz = rz_neu
        info = {"iterationen": it, "residuum": res, "ms": round((time.perf_counter() - t0) * 1000, 1)}
        self.statistik["loesungen"] += 1
        self.statistik["iterationen"] += it
        return X[:, : no[0], : no[1], : no[2]], info

    def energie(self, U: np.ndarray) -> np.ndarray:
        """uₑᵀ (h KE) uₑ je Element (ne_original) für den Steifigkeitsfaktor 1 (0 außerhalb des Bauraums)."""
        e0 = self.ebenen[0]
        no = tuple(n + 1 for n in self.ne_original)
        X = np.zeros((3,) + e0.nn)
        X[:, : no[0], : no[1], : no[2]] = U
        Ue = self._elemente0(X)
        w = np.zeros(int(np.prod(self.ne)))
        w[self.akt0] = np.einsum("ie,ie->e", Ue, self.KE @ Ue)
        n0 = self.ne_original
        return w.reshape(self.ne)[: n0[0], : n0[1], : n0[2]]
