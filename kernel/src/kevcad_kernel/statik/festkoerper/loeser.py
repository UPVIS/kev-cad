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

- **Druck** p (N/mm², simulation2) senkrecht auf jedes Randdreieck: Zugspannung t = −p n (n nach außen).

Zwangsbedingungen (simulation2, ``Zwang``): außer festen Freiheitsgraden (u = 0) auch schräge (gleitende Lager:
u · h = 0 je gehaltener Richtung h, genau auch schräg zu den Achsen) und gekoppelte (gelenkiges Lager auf einer Fläche,
wie ein RBE3 mit festem Bezugspunkt: die mittlere Verschiebung der Fläche ist null, ∫ u dA = 0, und die mittlere
Drehung um die gehaltenen Achsen, ∫ (b × r) · u dA = 0 mit b = J⁻¹ t; die Fläche selbst bleibt frei verformbar und
dreht um die übrigen Achsen). Gelöst wird über u = T q mit den freien Koordinaten q: schräge Bedingungen je Ort über eine
Drehung seiner drei Freiheitsgrade, gekoppelte über Haupt- und Nebenfreiheitsgrade (QR mit Pivotsuche), dann
(Tᵀ K T) q = Tᵀ f. Die Matrix bleibt symmetrisch positiv definit; SuperLU und pyamg rechnen wie ohne Zwang.

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

    def last_druck(self, facetten: np.ndarray, p: float) -> np.ndarray:
        """Druck p (N/mm²) senkrecht auf die Randdreiecke ``facetten``: Zugspannung −p n (n nach außen, je Dreieck
        konstant); auf einer Ebene ist die Resultierende −p A n."""
        from skfem import FacetBasis, LinearForm, asm

        fb = FacetBasis(self.mesh, self.basis.elem, facets=self.rand_index[facetten], intorder=3)
        pp = float(p)

        @LinearForm
        def druck(v, w):
            n = w.n
            return -pp * (n[0] * v[0] + n[1] * v[1] + n[2] * v[2])

        f = np.asarray(asm(druck, fb)).reshape(-1)
        # w.n zeigt bei Randfacetten nach außen; an der Summe prüfen (sonst umdrehen)
        soll = -pp * (self.rand_normale[facetten] * self.rand_flaeche_mm2[facetten, None]).sum(axis=0)
        ist = np.array([f[self.basis.nodal_dofs[c]].sum() + f[self.basis.edge_dofs[c]].sum() for c in range(3)])
        if float(np.dot(ist, soll)) < 0:
            f = -f
        return f

    # -- Zwangsbedingungen (simulation2) ------------------------------------------------------------------------------

    def orte(self) -> tuple[np.ndarray, np.ndarray]:
        """Freiheitsgrade je Ort (Ecken, dann Kantenmitten): ``trip`` (Orte, 3) und Ort je Freiheitsgrad (N,)."""
        trip = np.concatenate([self.basis.nodal_dofs.T, self.basis.edge_dofs.T]).astype(np.int64)
        ort = np.full(self.N, -1, dtype=np.int64)
        ort[trip.reshape(-1)] = np.repeat(np.arange(len(trip)), 3)
        return trip, ort

    def facetten_dofs(self, facetten: np.ndarray) -> np.ndarray:
        return np.unique(self.basis.get_dofs(facets=self.rand_index[facetten]).all())

    def gelenk_zeilen(self, facetten: np.ndarray, drehachsen: list[Any]) -> list[np.ndarray]:
        """Zwangsbedingungen eines gelenkigen Lagers auf einer Fläche (wie ein RBE3, Bezugspunkt fest): mittlere
        Verschiebung null (drei Zeilen ∫ N dA je Richtung) und mittlere Drehung um jede gehaltene Achse t null
        (∫ (b × r) · u dA mit b = J⁻¹ t, r = x − Schwerpunkt). Um die übrigen Achsen dreht die Fläche frei."""
        from skfem import FacetBasis, LinearForm, asm

        fb = FacetBasis(self.mesh, self.basis.elem, facets=self.rand_index[facetten], intorder=3)
        zeilen = []
        for c in range(3):
            def mittel(v, w, c=c):
                return v[c]

            zeilen.append(np.asarray(asm(LinearForm(mittel), fb)).reshape(-1))
        if drehachsen:
            g = self.flaeche_geometrie(facetten)
            c0 = g["c"]
            Jinv = np.linalg.pinv(g["J"])
            for t in drehachsen:
                b = Jinv @ np.asarray(t, float)
                if float(np.linalg.norm(b)) < 1e-300:
                    continue

                def drehung(v, w, b=b):
                    x = w.x
                    r = [x[i] - c0[i] for i in range(3)]
                    return ((b[1] * r[2] - b[2] * r[1]) * v[0] + (b[2] * r[0] - b[0] * r[2]) * v[1]
                            + (b[0] * r[1] - b[1] * r[0]) * v[2])

                zeilen.append(np.asarray(asm(LinearForm(drehung), fb)).reshape(-1))
        return zeilen

    def zwang(self, fest: np.ndarray, schief: list[tuple[np.ndarray, list[Any]]] | None = None,
              kopplung: list[np.ndarray] | None = None) -> Zwang:
        """Zwangsbedingungen zu u = T q: ``fest`` Freiheitsgrade mit u = 0, ``schief`` je (Freiheitsgrade, gehaltene
        Richtungen) u · h = 0 an jedem Ort dieser Freiheitsgrade, ``kopplung`` Zeilen c mit c · u = 0."""
        return Zwang(self, fest, schief or [], kopplung or [])

    def starr_frei(self, zwang: Zwang) -> tuple[int, list[str]]:
        """Wie viele der sechs Starrkörperbewegungen die Zwangsbedingungen zulassen, und welche (Texte)."""
        B = self.starrkoerper()
        groesse = float(np.max(np.ptp(self.basis.doflocs, axis=1))) or 1.0
        B[:, 3:] /= groesse  # Drehungen auf die Teilgröße bezogen, damit Rang und Toleranz passen
        Cb = zwang.mal_bedingungen(B)
        if Cb.shape[0] == 0:
            return 6, ["frei in allen Richtungen"]
        Cb = Cb / np.maximum(np.linalg.norm(Cb, axis=1, keepdims=True), 1e-300)
        _, s, vt = np.linalg.svd(Cb, full_matrices=True)
        tol = 1e-8 * max(float(s[0]) if len(s) else 1.0, 1e-30)
        rang = int((s > tol).sum())
        frei = []
        for v in vt[rang:]:
            t, r = v[:3], np.array([v[4], v[5], v[3]])  # Spalten 3, 4, 5: Drehung um z, x, y
            def txt(a):
                a = a / np.linalg.norm(a)
                a = a * np.sign(a[int(np.argmax(np.abs(a)))])  # Vorzeichen: größte Komponente positiv
                return "(" + "; ".join(f"{round(float(c), 2) + 0.0:.2f}".replace(".", ",") for c in a) + ")"
            frei.append(f"verschiebbar in {txt(t)}" if float(np.linalg.norm(t)) >= float(np.linalg.norm(r))
                        else f"drehbar um {txt(r)}")
        return 6 - rang, frei

    def komponente(self) -> np.ndarray:
        comp = np.full(self.N, -1, dtype=np.int64)
        for c in range(3):
            comp[self.basis.nodal_dofs[c]] = c
            comp[self.basis.edge_dofs[c]] = c
        return comp

    def reaktion(self, K: sp.csr_matrix, u: np.ndarray, f: np.ndarray, dofs: np.ndarray) -> np.ndarray:
        """Resultierende Lagerkraft (N) auf den Freiheitsgraden ``dofs``: Summe von K u − f je Richtung."""
        r = np.asarray(K @ u).reshape(-1) - f
        comp = self.komponente()
        return np.array([float(r[dofs[comp[dofs] == c]].sum()) for c in range(3)])

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
              duenn: bool = False, zwang: Zwang | None = None) -> tuple[list[np.ndarray], dict[str, Any]]:
        """Löst K u = f für alle Lastvektoren mit den festen Freiheitsgraden ``fest`` (u = 0), mit ``zwang`` statt
        dessen unter allgemeinen Zwangsbedingungen u = T q (``fest`` steckt dann in T).

        pyamg (Smoothed Aggregation, CG) für gedrungene Teile; bei dünnen, langen Teilen (Platten, Leisten) kommt
        AMG mit Tetraedern kaum voran, dort und bei kleinen Systemen zerlegt SuperLU direkt (symmetrische Ordnung,
        ein Mal für alle Lastfälle). Kommt AMG nicht unter die Toleranz, rechnet SuperLU nach (bis ``LU_MAX``)."""
        t0 = time.perf_counter()
        if zwang is not None:
            T = zwang.T
            frei = np.arange(T.shape[1])
            A = (T.T @ K @ T).tocsr()
        else:
            T = None
            frei = np.setdiff1d(np.arange(self.N), fest)
            A = K[frei][:, frei].tocsr()
        info: dict[str, Any] = {"freiheitsgrade": int(len(frei)), "iterationen": [], "residuum": [], "verfahren": []}
        if zwang is not None:
            info["zwang"] = dict(zwang.info)
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
            block = T is None and len(frei) % 3 == 0 and bool(
                np.all(frei.reshape(-1, 3) - frei.reshape(-1, 3)[:, :1] == [0, 1, 2]))
            nah = zwang.restriktion(self.starrkoerper()) if zwang is not None else self.starrkoerper()[frei]
            ml = pyamg.smoothed_aggregation_solver(sp.bsr_matrix(A, blocksize=(3, 3)) if block else A,
                                                   B=nah, symmetry="symmetric",
                                                   strength="symmetric", max_coarse=300)
            info["amg_ms"] = round((time.perf_counter() - t) * 1000, 1)
            info["ebenen"] = len(ml.levels)
        out = []
        for f in lasten:
            if abbruch is not None:
                abbruch()
            b = np.asarray(T.T @ f).reshape(-1) if T is not None else f[frei]
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
            if T is not None:
                u = np.asarray(T @ x).reshape(-1)
            else:
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


class Zwang:
    """Lineare Zwangsbedingungen als u = T q (siehe Moduldoku). ``T`` (N × M, dünn); ``restriktion(B)`` bildet
    Starrkörperbewegungen in die freien Koordinaten ab (Nahkern für pyamg)."""

    def __init__(self, netz: Netz, fest: np.ndarray, schief: list[tuple[np.ndarray, list[Any]]],
                 kopplung: list[np.ndarray]) -> None:
        import scipy.linalg as sla

        N = netz.N
        trip, ort = netz.orte()
        self._trip = trip
        komp = netz.komponente()
        achsen = np.eye(3)
        gehalten: dict[int, list[np.ndarray]] = {}
        fest = np.asarray(fest, dtype=np.int64).reshape(-1)
        for d in fest:
            gehalten.setdefault(int(ort[d]), []).append(achsen[komp[d]])
        schraeg = 0
        for dofs, richt in schief:
            hs = [np.asarray(h, float) / max(float(np.linalg.norm(h)), 1e-300) for h in richt]
            schraeg += sum(1 for h in hs if float(np.max(np.abs(h))) < 1 - 1e-9)
            for o in np.unique(ort[np.asarray(dofs, dtype=np.int64)]):
                gehalten.setdefault(int(o), []).extend(hs)
        self.halt: dict[int, np.ndarray] = {}  # Ort → gehaltene Richtungen (orthonormale Zeilen)
        frei_orte = np.ones(len(trip), dtype=bool)
        if gehalten:
            frei_orte[np.fromiter(gehalten, dtype=np.int64)] = False
        idx = np.flatnonzero(frei_orte)
        rows = [trip[idx].reshape(-1)]
        cols = [np.arange(3 * len(idx))]
        vals = [np.ones(3 * len(idx))]
        spalte = 3 * len(idx)
        for o, hs in sorted(gehalten.items()):
            H = np.asarray(hs, float)
            _, s, vt = np.linalg.svd(H)
            r = int((s > 1e-9 * s[0]).sum()) if len(s) else 0
            self.halt[o] = vt[:r]
            for v in vt[r:]:
                rows.append(trip[o])
                cols.append(np.full(3, spalte))
                vals.append(v)
                spalte += 1
        T0 = sp.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(N, spalte))
        T0.eliminate_zeros()
        self.T0 = T0
        self.koppel = np.asarray(kopplung, float).reshape(-1, N) if len(kopplung) else np.zeros((0, N))
        self.info: dict[str, Any] = {"fest": int(len(fest)), "schraeg": int(schraeg),
                                     "kopplung": int(len(self.koppel)), "frei": int(spalte)}
        self.haupt = np.arange(spalte)
        if len(self.koppel) == 0:
            self.T = T0.tocsr()
            return
        C0 = (sp.csr_matrix(self.koppel) @ T0).tocsc()  # Bedingungen in den Koordinaten nach T0
        J = np.unique(C0.nonzero()[1])
        D = C0[:, J].toarray()
        # abhängige Bedingungen weg (orthonormale Zeilen), dann Nebenfreiheitsgrade über QR mit Pivotsuche
        _, s, vt = np.linalg.svd(D, full_matrices=False)
        k = int((s > 1e-10 * s[0]).sum()) if len(s) else 0
        Dn = vt[:k]
        _, _, P = sla.qr(Dn, mode="economic", pivoting=True)
        neben, haupt_lok = P[:k], P[k:]
        X = -np.linalg.solve(Dn[:, neben], Dn[:, haupt_lok])  # u_neben = X · u_haupt
        neben_glob = J[neben]
        haupt_mask = np.ones(spalte, dtype=bool)
        haupt_mask[neben_glob] = False
        self.haupt = np.flatnonzero(haupt_mask)
        pos = np.full(spalte, -1, dtype=np.int64)
        pos[self.haupt] = np.arange(len(self.haupt))
        hj = pos[J[haupt_lok]]
        r1 = [self.haupt] + [np.full(len(hj), g) for g in neben_glob]
        c1 = [np.arange(len(self.haupt))] + [hj] * len(neben_glob)
        v1 = [np.ones(len(self.haupt))] + [X[i] for i in range(len(neben_glob))]
        T1 = sp.csr_matrix((np.concatenate(v1), (np.concatenate(r1), np.concatenate(c1))),
                           shape=(spalte, len(self.haupt)))
        self.T = (T0 @ T1).tocsr()
        self.T.eliminate_zeros()
        self.info["kopplung_unabhaengig"] = k
        self.info["frei"] = int(len(self.haupt))

    def restriktion(self, B: np.ndarray) -> np.ndarray:
        """Starrkörperbewegungen (N, 6) in den freien Koordinaten (Hauptfreiheitsgrade nach T0)."""
        return np.asarray(self.T0.T @ B)[self.haupt]

    def mal_bedingungen(self, B: np.ndarray) -> np.ndarray:
        """Alle Bedingungen angewandt auf die Spalten von B (N, k): gehaltene Richtungen je Ort und Kopplungen."""
        zeilen = [H @ B[self._trip[o]] for o, H in self.halt.items() if len(H)]
        if len(self.koppel):
            zeilen.append(self.koppel @ B)
        return np.vstack(zeilen) if zeilen else np.zeros((0, B.shape[1]))


def komponenten(t: np.ndarray, n: int) -> np.ndarray:
    """Zusammenhangskomponente je Knoten (Tetraeder teilen Ecken)."""
    from scipy.sparse.csgraph import connected_components

    r = np.repeat(t[:, 0], 3)
    c = t[:, 1:].reshape(-1)
    g = sp.coo_matrix((np.ones(len(r)), (r, c)), shape=(n, n))
    return connected_components(g, directed=False)[1]
