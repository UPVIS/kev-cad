"""Lineare Elastizität mit Tetraedern zweiter Ordnung (P2), nur im FEM-Prozess.

scikit-fem liefert Netz-Topologie (Kanten, Randflächen), Nummerierung der Freiheitsgrade (``Basis`` mit
``ElementVector(ElementTetP2())``, je Ort x, y, z nebeneinander) und die Flächenlasten (``FacetBasis``, konsistent
integriert). Die Steifigkeit baut ein eigener vektorisierter Kern mit derselben Formel wie ``skfem.asm`` mit
``linear_elasticity`` (4-Punkt-Regel, exakt für P2 auf geraden Tetraedern; gleiche Matrix bis auf Rundung, siehe
Test), nur mehrfach schneller und mit beliebiger 6×6-Steifigkeit (quer zur Schicht weicher). pyamg löst mit
Smoothed Aggregation in 3×3-Blöcken und den sechs Starrkörperbewegungen als Nahkern, beschleunigt mit CG; kleine
Systeme und dünne Teile (Platten, an denen AMG mit Tetraedern kaum vorankommt) zerlegt SuperLU direkt.

Lasten:

- **Flächenlast** wie ein RBE3: Kraft F und Moment M am Punkt P auf eine Randfläche verteilt, Zugspannung
  t(x) = F / A + ω × (x − c) mit J ω = M + (P − c) × F, J = ∫ (|r|² I − r rᵀ) dA über die Fläche (c ihr Schwerpunkt).
  Summe und Moment stimmen genau, die Verteilung ist linear (wie bei einer steifen Platte).
- **Volumenlast** b (N/mm³), etwa Eigengewicht oder eine Last „am Schwerpunkt“ ohne Punkt: konsistent mit
  ∫ N dV (Ecken −V/20, Kantenmitten V/5).

Spannung: je Element an den vier Ecken aus den P2-Gradienten, dann je Knoten gemittelt (Knotenmittelwert).
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import scipy.sparse as sp

KANTEN = np.array([[0, 1], [1, 2], [0, 2], [0, 3], [1, 3], [2, 3]])
_QA, _QB = 0.5854101966249685, 0.1381966011250105
QL = np.array([[_QA, _QB, _QB, _QB], [_QB, _QA, _QB, _QB], [_QB, _QB, _QA, _QB], [_QB, _QB, _QB, _QA]])
TOL = 1e-7
MAXITER_AMG = 150  # darüber lohnt SuperLU
MAXITER = 1000
LU_KLEIN = 25_000  # bis hierhin immer direkt
LU_MAX = 150_000  # SuperLU höchstens bis hier (Speicher)


def _grad_formfunktionen(gL: np.ndarray, L: np.ndarray) -> np.ndarray:
    """Gradienten der 10 P2-Formfunktionen (ne, 10, 3) an der baryzentrischen Stelle L (4,)."""
    ne = gL.shape[0]
    G = np.empty((ne, 10, 3))
    for i in range(4):
        G[:, i] = (4 * L[i] - 1) * gL[:, i]
    for k, (i, j) in enumerate(KANTEN):
        G[:, 4 + k] = 4 * (L[j] * gL[:, i] + L[i] * gL[:, j])
    return G


def _b_matrix(G: np.ndarray) -> np.ndarray:
    """Verzerrungs-Verschiebungs-Matrix (…, 6, 30) aus Gradienten (…, 10, 3), Voigt mit technischen Gleitungen."""
    B = np.zeros(G.shape[:-2] + (6, 30))
    for a in range(10):
        gx, gy, gz = G[..., a, 0], G[..., a, 1], G[..., a, 2]
        c = 3 * a
        B[..., 0, c] = gx
        B[..., 1, c + 1] = gy
        B[..., 2, c + 2] = gz
        B[..., 3, c + 1] = gz
        B[..., 3, c + 2] = gy
        B[..., 4, c] = gz
        B[..., 4, c + 2] = gx
        B[..., 5, c] = gy
        B[..., 5, c + 1] = gx
    return B


class Netz:
    """P2-Netz eines Teils mit Randflächen (nach außen orientiert) und Freiheitsgraden aus scikit-fem."""

    def __init__(self, p: np.ndarray, t: np.ndarray, rand: np.ndarray | None = None,
                 flaeche: np.ndarray | None = None) -> None:
        from skfem import Basis, ElementTetP2, ElementVector, MeshTet

        t0 = time.perf_counter()
        self.mesh = MeshTet(np.ascontiguousarray(np.asarray(p, float).T),
                            np.ascontiguousarray(np.asarray(t, dtype=np.int64).T))
        self.basis = Basis(self.mesh, ElementVector(ElementTetP2()), intorder=2)
        m = self.mesh
        self.p = m.p.T  # (n, 3); skfem sortiert die Tetraeder-Ecken nicht um
        self.t = m.t.T  # (ne, 4)
        self.n = self.p.shape[0]
        self.N = int(self.basis.N)
        # globale Kante je Element und lokaler Kante (KANTEN), unabhängig von der Reihenfolge in skfem
        ek = np.sort(m.edges, axis=0).astype(np.int64)
        key = ek[0] * self.n + ek[1]
        order = np.argsort(key)
        a = np.sort(np.stack([m.t[KANTEN[:, 0]], m.t[KANTEN[:, 1]]]), axis=0).astype(np.int64)
        k2 = a[0] * self.n + a[1]
        self.kante = order[np.searchsorted(key[order], k2)]  # (6, ne)
        self.dofs = np.empty((m.t.shape[1], 30), dtype=np.int64)
        for i in range(4):
            self.dofs[:, 3 * i:3 * i + 3] = self.basis.nodal_dofs[:, m.t[i]].T
        ed = self.basis.edge_dofs[:, self.kante]  # (3, 6, ne)
        self.dofs[:, 12:] = np.transpose(ed, (2, 1, 0)).reshape(-1, 18)
        # Geometrie je Element
        X = self.p[self.t]  # (ne, 4, 3)
        J = np.stack([X[:, 1] - X[:, 0], X[:, 2] - X[:, 0], X[:, 3] - X[:, 0]], axis=2)  # Spalten = Kanten
        self.det = np.linalg.det(J)
        Ji = np.linalg.inv(J)
        self.gL = np.empty((len(self.det), 4, 3))
        self.gL[:, 1:] = Ji
        self.gL[:, 0] = -Ji.sum(axis=1)
        self.vol = np.abs(self.det) / 6.0
        # Randflächen, nach außen orientiert
        bf = m.boundary_facets()
        f = m.facets[:, bf].T.astype(np.int64)  # (k, 3)
        el = m.f2t[0, bf]
        vierte = self._vierte(el, f)
        nrm = np.cross(self.p[f[:, 1]] - self.p[f[:, 0]], self.p[f[:, 2]] - self.p[f[:, 0]])
        innen = np.einsum("ij,ij->i", nrm, self.p[vierte] - self.p[f[:, 0]]) > 0
        f[innen] = f[innen][:, [0, 2, 1]]
        nrm[innen] *= -1
        self.rand_index = bf  # Facettennummern in skfem
        self.rand = f
        self.rand_flaeche_mm2 = 0.5 * np.linalg.norm(nrm, axis=1)
        self.rand_normale = nrm / np.maximum(2 * self.rand_flaeche_mm2, 1e-300)[:, None]
        self.rand_mitte = self.p[f].mean(axis=1)
        # B-Rep-Fläche je Randdreieck (aus Gmsh), sonst -1
        self.rand_brep = np.full(len(f), -1, dtype=np.int64)
        if rand is not None and flaeche is not None and len(rand):
            s = np.sort(np.asarray(rand, dtype=np.int64), axis=1)
            kg = (s[:, 0] * self.n + s[:, 1]) * self.n + s[:, 2]
            sf = np.sort(f, axis=1)
            kf = (sf[:, 0] * self.n + sf[:, 1]) * self.n + sf[:, 2]
            o = np.argsort(kg)
            pos = np.clip(np.searchsorted(kg[o], kf), 0, len(kg) - 1)
            treffer = kg[o][pos] == kf
            self.rand_brep[treffer] = np.asarray(flaeche, dtype=np.int64)[o][pos[treffer]]
        self.ms_aufbau = (time.perf_counter() - t0) * 1000

    def _vierte(self, el: np.ndarray, f: np.ndarray) -> np.ndarray:
        T = self.mesh.t[:, el].T  # (k, 4)
        maske = (T[:, :, None] != f[:, None, :]).all(axis=2)  # Ecke nicht in der Facette
        return T[np.arange(len(T)), np.argmax(maske, axis=1)]

    # -- Steifigkeit -------------------------------------------------------------------------------------------------

    def steifigkeit(self, C: np.ndarray, stueck: int = 20_000) -> sp.csr_matrix:
        """Gesamtsteifigkeit (N × N, CSR) für die 6×6-Steifigkeit C (Welt)."""
        ne = len(self.vol)
        rows, cols, vals = [], [], []
        idx_r = np.repeat(np.arange(30), 30)
        idx_c = np.tile(np.arange(30), 30)
        for s in range(0, ne, stueck):
            e = slice(s, min(ne, s + stueck))
            gL = self.gL[e]
            Ke = np.zeros((gL.shape[0], 30, 30))
            for q in range(4):
                B = _b_matrix(_grad_formfunktionen(gL, QL[q]))  # (n, 6, 30)
                Ke += np.einsum("eai,ab,ebj->eij", B, C, B, optimize=True)
            Ke *= (self.vol[e] / 4.0)[:, None, None]
            d = self.dofs[e]
            rows.append(d[:, idx_r].reshape(-1))
            cols.append(d[:, idx_c].reshape(-1))
            vals.append(Ke.reshape(-1))
        K = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                          shape=(self.N, self.N)).tocsr()
        K.sum_duplicates()
        return K

    # -- Lasten ------------------------------------------------------------------------------------------------------

    def last_volumen(self, b: np.ndarray, elemente: np.ndarray | None = None) -> np.ndarray:
        """Konsistente Knotenlasten einer gleichmäßigen Volumenlast b (N/mm³)."""
        f = np.zeros(self.N)
        b = np.asarray(b, float)
        e = slice(None) if elemente is None else elemente
        v = self.vol[e]
        d = self.dofs[e]
        for c in range(3):
            if abs(b[c]) < 1e-300:
                continue
            np.add.at(f, d[:, c:12:3].reshape(-1), np.repeat(-v / 20.0 * b[c], 4))
            np.add.at(f, d[:, 12 + c::3].reshape(-1), np.repeat(v / 5.0 * b[c], 6))
        return f

    def flaeche_geometrie(self, facetten: np.ndarray) -> dict[str, Any]:
        """Fläche, Schwerpunkt und Flächenträgheit J = ∫ (|r|² I − r rᵀ) dA einer Auswahl von Randdreiecken."""
        f = self.rand[facetten]
        P = self.p[f]  # (k, 3, 3)
        A = self.rand_flaeche_mm2[facetten]
        mitten = np.stack([(P[:, 0] + P[:, 1]) / 2, (P[:, 1] + P[:, 2]) / 2, (P[:, 0] + P[:, 2]) / 2], axis=1)
        At = float(A.sum())
        c = (A[:, None] * P.mean(axis=1)).sum(axis=0) / max(At, 1e-300)
        r = mitten - c  # Kantenmitten-Regel: exakt für quadratische Funktionen
        rr = np.einsum("kqi,kqj,k->ij", r, r, A / 3.0)
        J = np.trace(rr) * np.eye(3) - rr
        return {"A": At, "c": c, "J": J}

    def last_flaeche(self, facetten: np.ndarray, F: np.ndarray, M: np.ndarray | None = None,
                     P: np.ndarray | None = None) -> np.ndarray:
        """Kraft F (N) und Moment M (Nmm) am Punkt P, verteilt wie ein RBE3 über die Randdreiecke ``facetten``."""
        from skfem import FacetBasis, LinearForm, asm

        g = self.flaeche_geometrie(facetten)
        F = np.asarray(F, float)
        c = g["c"]
        Mc = (np.zeros(3) if M is None else np.asarray(M, float)) + (
            np.cross(np.asarray(P, float) - c, F) if P is not None else 0.0)
        omega = np.linalg.lstsq(g["J"], Mc, rcond=1e-12)[0] if np.any(np.abs(Mc) > 0) else np.zeros(3)
        a = F / max(g["A"], 1e-300)
        fb = FacetBasis(self.mesh, self.basis.elem, facets=self.rand_index[facetten], intorder=3)

        @LinearForm
        def zug(v, w):
            x = w.x
            r = [x[i] - c[i] for i in range(3)]
            tx = a[0] + omega[1] * r[2] - omega[2] * r[1]
            ty = a[1] + omega[2] * r[0] - omega[0] * r[2]
            tz = a[2] + omega[0] * r[1] - omega[1] * r[0]
            return tx * v[0] + ty * v[1] + tz * v[2]

        return asm(zug, fb)

    # -- Lösen -------------------------------------------------------------------------------------------------------

    def starrkoerper(self) -> np.ndarray:
        """Sechs Starrkörperbewegungen (N, 6) an den Orten der Freiheitsgrade (Nahkern für pyamg)."""
        X = self.basis.doflocs
        comp = np.zeros(self.N, dtype=np.int64)
        for c in range(3):
            comp[self.basis.nodal_dofs[c]] = c
            comp[self.basis.edge_dofs[c]] = c
        x, y, z = X - X.mean(axis=1, keepdims=True)
        B = np.zeros((self.N, 6))
        for c in range(3):
            B[comp == c, c] = 1.0
        B[comp == 0, 3], B[comp == 1, 3] = -y[comp == 0], x[comp == 1]
        B[comp == 1, 4], B[comp == 2, 4] = -z[comp == 1], y[comp == 2]
        B[comp == 2, 5], B[comp == 0, 5] = -x[comp == 2], z[comp == 0]
        return B

    def feste_dofs(self, facetten: np.ndarray, komponenten: list[int] | None = None) -> np.ndarray:
        """Freiheitsgrade der Randfacetten; ``komponenten`` (0 = x, 1 = y, 2 = z): nur diese Richtungen (gleitendes
        Lager, Simulation)."""
        dofs = np.unique(self.basis.get_dofs(facets=self.rand_index[facetten]).all())
        if komponenten is None:
            return dofs
        comp = np.full(self.N, -1, dtype=np.int64)
        for c in range(3):
            comp[self.basis.nodal_dofs[c]] = c
            comp[self.basis.edge_dofs[c]] = c
        return dofs[np.isin(comp[dofs], komponenten)]

    def loese(self, K: sp.csr_matrix, fest: np.ndarray, lasten: list[np.ndarray], abbruch: Any = None,
              duenn: bool = False) -> tuple[list[np.ndarray], dict[str, Any]]:
        """Löst K u = f für alle Lastvektoren mit den festen Freiheitsgraden ``fest`` (u = 0).

        pyamg (Smoothed Aggregation, CG) für gedrungene Teile; bei dünnen, langen Teilen (Platten, Leisten) kommt
        AMG mit Tetraedern kaum voran, dort und bei kleinen Systemen zerlegt SuperLU direkt (symmetrische Ordnung,
        ein Mal für alle Lastfälle). Kommt AMG nicht unter die Toleranz, rechnet SuperLU nach (bis ``LU_MAX``)."""
        t0 = time.perf_counter()
        frei = np.setdiff1d(np.arange(self.N), fest)
        A = K[frei][:, frei].tocsr()
        info: dict[str, Any] = {"freiheitsgrade": int(len(frei)), "iterationen": [], "residuum": [], "verfahren": []}
        lu = None
        ml = None

        def zerlegen() -> Any:
            import scipy.sparse.linalg as spla

            t = time.perf_counter()
            z = spla.splu(A.tocsc(), permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                          options={"SymmetricMode": True})
            info["lu_ms"] = round((time.perf_counter() - t) * 1000, 1)
            return z

        if len(frei) <= LU_KLEIN or (duenn and len(frei) <= LU_MAX):
            lu = zerlegen()
        else:
            import pyamg

            t = time.perf_counter()
            block = len(frei) % 3 == 0 and bool(np.all(frei.reshape(-1, 3) - frei.reshape(-1, 3)[:, :1] == [0, 1, 2]))
            ml = pyamg.smoothed_aggregation_solver(sp.bsr_matrix(A, blocksize=(3, 3)) if block else A,
                                                   B=self.starrkoerper()[frei], symmetry="symmetric",
                                                   strength="symmetric", max_coarse=300)
            info["amg_ms"] = round((time.perf_counter() - t) * 1000, 1)
            info["ebenen"] = len(ml.levels)
        out = []
        for f in lasten:
            if abbruch is not None:
                abbruch()
            b = f[frei]
            nb = float(np.linalg.norm(b))
            u = np.zeros(self.N)
            if nb == 0:
                out.append(u)
                info["iterationen"].append(0)
                info["residuum"].append(0.0)
                info["verfahren"].append("null")
                continue
            res: list[float] = []
            if lu is None and ml is not None:
                x = ml.solve(b, tol=TOL, accel="cg", maxiter=MAXITER_AMG, residuals=res)
                r = float(np.linalg.norm(b - A @ x)) / nb
                verfahren = "amg"
                if r > 10 * TOL and len(frei) <= LU_MAX:  # AMG kommt nicht hin: direkt lösen
                    if abbruch is not None:
                        abbruch()
                    lu = zerlegen()
                elif r > 10 * TOL:  # zu groß für SuperLU: weiter iterieren
                    x = ml.solve(b, x0=x, tol=TOL, accel="cg", maxiter=MAXITER, residuals=res)
                    r = float(np.linalg.norm(b - A @ x)) / nb
            if lu is not None:
                x = lu.solve(b)
                r = float(np.linalg.norm(b - A @ x)) / nb
                verfahren = "superlu"
            u[frei] = x
            out.append(u)
            info["iterationen"].append(len(res))
            info["residuum"].append(r)
            info["verfahren"].append(verfahren)
        info["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out, info

    # -- Auswerten ---------------------------------------------------------------------------------------------------

    def verschiebung(self, u: np.ndarray) -> np.ndarray:
        """Verschiebung der Ecken (n, 3) in mm."""
        return u[self.basis.nodal_dofs].T

    def spannung(self, u: np.ndarray, C: np.ndarray) -> np.ndarray:
        """Spannung (n, 6) je Knoten, Knotenmittelwert der Elementwerte an den Ecken (Voigt, N/mm²)."""
        ue = u[self.dofs]  # (ne, 30)
        summe = np.zeros((self.n, 6))
        zahl = np.zeros(self.n)
        for i in range(4):
            L = np.zeros(4)
            L[i] = 1.0
            B = _b_matrix(_grad_formfunktionen(self.gL, L))  # (ne, 6, 30)
            eps = np.einsum("eaj,ej->ea", B, ue)
            sig = eps @ C.T
            np.add.at(summe, self.t[:, i], sig)
            np.add.at(zahl, self.t[:, i], 1.0)
        return summe / np.maximum(zahl, 1)[:, None]


def komponenten(t: np.ndarray, n: int) -> np.ndarray:
    """Zusammenhangskomponente je Knoten (Tetraeder teilen Ecken)."""
    from scipy.sparse.csgraph import connected_components

    r = np.repeat(t[:, 0], 3)
    c = t[:, 1:].reshape(-1)
    g = sp.coo_matrix((np.ones(len(r)), (r, c)), shape=(n, n))
    return connected_components(g, directed=False)[1]
