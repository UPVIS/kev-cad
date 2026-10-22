"""SIMP auf dem Voxelgitter: minimale Nachgiebigkeit bei vorgegebenem Volumenanteil.

Kette je Iteration: Entwurf ``x`` (je Element 0…1) → Dichtefilter (Kegel mit Radius r, normiert auf den Bauraum, Sigmund
2007) → ``x̃`` → auf Wunsch Überhangfilter in Druckrichtung (Langelaar 2017, 45° über das Kreuz aus fünf Elementen der
Schicht darunter) → gedruckte Dichte ``x̂`` → Steifigkeit ``E_min + x̂^p (1 − E_min)`` mit p = 3. Ziel: Summe der
Nachgiebigkeiten ``fᵀu`` aller Lastfälle; Nebenbedingung: Volumen von ``x̂`` (geschützte Elemente zählen mit) gleich
``behalten`` mal Bauraum. Neue Werte nach dem Optimalitätskriterium (OC) mit Schrittweite 0,2 und Bisektion auf das
linearisierte Volumen. Geschützte Elemente (Schutzzonen) bleiben bei 1.

Der Überhangfilter: Schicht für Schicht von unten nach oben ist ``x̂_e = smin(x̃_e, ξ_e)`` mit ``ξ_e = smax`` der
gedruckten Dichten im Kreuz darunter (P = 40, Q so, dass smax von lauter 0,5 genau 0,5 ist). Die unterste Schicht liegt
auf dem Bett. Elemente, die schon im Ausgangsteil frei hängen (Überhänge des Entwurfs, Brücken über Bohrungen), gelten
als gestützt: Der Filter verhindert neue Überhänge, alte bleiben, wie sie waren. Ableitungen rückwärts Schicht für
Schicht (adjungiert).
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable

import numpy as np

from kevcad_kernel.topologie.mehrgitter import Mehrgitter

P_STRAFE = 3.0
E_MIN = 1e-6
SCHRITT = 0.2
AM_P = 40.0
AM_XI0 = 0.5
AM_EPS = 1e-4
KREUZ = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))


class Abbruch(RuntimeError):
    pass


# -- Dichtefilter ------------------------------------------------------------------------------------------------------


def kegel(radius: float) -> np.ndarray:
    """Kegelförmiger Filterkern mit Radius ``radius`` (in Elementen)."""
    r = max(float(radius), 1.0)
    n = int(math.ceil(r)) - 1 if float(r).is_integer() else int(math.floor(r))
    ax = np.arange(-n, n + 1)
    X, Y, Z = np.meshgrid(ax, ax, ax, indexing="ij")
    w = np.maximum(0.0, r - np.sqrt(X ** 2 + Y ** 2 + Z ** 2))
    return w


class Dichtefilter:
    def __init__(self, aktiv: np.ndarray, radius: float) -> None:
        from scipy.ndimage import correlate

        self._corr = correlate
        self.w = kegel(radius)
        self.a = aktiv.astype(float)
        self.hs = correlate(self.a, self.w, mode="constant")
        self.hs[self.hs <= 0] = 1.0

    def vor(self, x: np.ndarray) -> np.ndarray:
        return self._corr(x * self.a, self.w, mode="constant") / self.hs * self.a

    def rueck(self, g: np.ndarray) -> np.ndarray:
        return self._corr(g * self.a / self.hs, self.w, mode="constant") * self.a


# -- Überhangfilter (Langelaar) ------------------------------------------------------------------------------------------


def _verschiebe(a: np.ndarray, di: int, dj: int) -> np.ndarray:
    """a[i + di, j + dj] mit 0 außerhalb (2D)."""
    out = np.zeros_like(a)
    nx, ny = a.shape
    i0, i1 = max(0, -di), min(nx, nx - di)
    j0, j1 = max(0, -dj), min(ny, ny - dj)
    out[i0:i1, j0:j1] = a[i0 + di:i1 + di, j0 + dj:j1 + dj]
    return out


class Ueberhangfilter:
    """Druckrichtung +z des Gitters (Schicht k liegt auf k − 1)."""

    def __init__(self, aktiv: np.ndarray, frei_gestuetzt: np.ndarray | None = None) -> None:
        self.aktiv = aktiv
        n = len(KREUZ)
        self.Q = AM_P + math.log(n) / math.log(AM_XI0)
        self.gestuetzt = np.zeros(aktiv.shape, dtype=bool) if frei_gestuetzt is None else frei_gestuetzt
        self._speicher: dict[str, Any] = {}

    @staticmethod
    def ausgangsueberhaenge(aktiv: np.ndarray) -> np.ndarray:
        """Elemente, die im vollen Ausgangsteil nicht gestützt sind (Überhänge des Entwurfs): Schicht für Schicht, ein
        Element ist gestützt, wenn im Kreuz darunter ein Element des Teils liegt (oder es selbst so markiert ist)."""
        nx, ny, nz = aktiv.shape
        out = np.zeros(aktiv.shape, dtype=bool)
        for k in range(1, nz):
            unten = aktiv[:, :, k - 1]
            st = np.zeros((nx, ny), dtype=bool)
            for di, dj in KREUZ:
                st |= _verschiebe(unten, di, dj) > 0
            out[:, :, k] = aktiv[:, :, k] & ~st
        return out

    def _smax(self, werte: list[np.ndarray]) -> tuple[np.ndarray, list[np.ndarray]]:
        s = np.zeros_like(werte[0])
        for w in werte:
            s += np.power(np.maximum(w, 0.0), AM_P)
        xi = np.power(np.maximum(s, 1e-300), 1.0 / self.Q)
        # d xi / d w_k = (P/Q) w_k^(P-1) s^(1/Q - 1)
        f = (AM_P / self.Q) * np.power(np.maximum(s, 1e-300), 1.0 / self.Q - 1.0)
        abl = [f * np.power(np.maximum(w, 0.0), AM_P - 1.0) for w in werte]
        return xi, abl

    @staticmethod
    def _smin(x: np.ndarray, xi: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        d = x - xi
        w = np.sqrt(d * d + AM_EPS)
        y = 0.5 * (x + xi - w + math.sqrt(AM_EPS))
        dx = 0.5 * (1.0 - d / w)
        dxi = 0.5 * (1.0 + d / w)
        return y, dx, dxi

    def vor(self, xt: np.ndarray) -> np.ndarray:
        nx, ny, nz = xt.shape
        xh = np.zeros_like(xt)
        xh[:, :, 0] = xt[:, :, 0]
        abl_x, abl_xi, abl_w = [None] * nz, [None] * nz, [None] * nz
        for k in range(1, nz):
            unten = xh[:, :, k - 1]
            werte = [_verschiebe(unten, di, dj) for di, dj in KREUZ]
            xi, dw = self._smax(werte)
            g = self.gestuetzt[:, :, k]
            xi = np.where(g, 1.0, xi)
            y, dx, dxi = self._smin(xt[:, :, k], xi)
            xh[:, :, k] = y
            abl_x[k], abl_xi[k] = dx, np.where(g, 0.0, dxi)
            abl_w[k] = dw
        self._speicher = {"x": abl_x, "xi": abl_xi, "w": abl_w}
        return xh

    def rueck(self, g_hat: np.ndarray) -> np.ndarray:
        """Ableitung nach x̃ aus der Ableitung nach x̂ (nach ``vor``)."""
        nx, ny, nz = g_hat.shape
        lam = g_hat.copy()
        out = np.zeros_like(g_hat)
        sp = self._speicher
        for k in range(nz - 1, 0, -1):
            out[:, :, k] = lam[:, :, k] * sp["x"][k]
            t = lam[:, :, k] * sp["xi"][k]
            for (di, dj), dw in zip(KREUZ, sp["w"][k]):
                # werte[m][i, j] = unten[i + di, j + dj]  →  Beitrag an unten[i + di, j + dj]
                lam[:, :, k - 1] += _verschiebe(t * dw, -di, -dj)
        out[:, :, 0] = lam[:, :, 0]
        return out


# -- Optimierer --------------------------------------------------------------------------------------------------------


class Optimierer:
    """``aktiv`` (nx, ny, nz) Bauraum, ``passiv`` geschützt (bleibt 1), ``KE`` Einheitswürfel (E = 1, in N/mm²
    multipliziert über ``E``), ``h`` Kante (mm), ``fest`` (3, nx+1, ny+1, nz+1) Lager, ``lasten`` Liste von
    Knotenkräften (3, nx+1, ny+1, nz+1) in N."""

    def __init__(self, aktiv: np.ndarray, passiv: np.ndarray, KE: np.ndarray, E: float, h: float, fest: np.ndarray,
                 lasten: list[np.ndarray], behalten: float, radius: float, ueberhang: bool = False,
                 gestuetzt: np.ndarray | None = None) -> None:
        self.aktiv = aktiv.astype(bool)
        self.passiv = passiv.astype(bool) & self.aktiv
        self.E = float(E)
        self.mg = Mehrgitter(KE, h, self.aktiv, fest)
        self.lasten = lasten
        self.n = int(self.aktiv.sum())
        self.ziel_volumen = float(behalten) * self.n
        self.behalten = float(behalten)
        self.filter = Dichtefilter(self.aktiv, radius)
        self.ueberhang = Ueberhangfilter(self.aktiv, gestuetzt) if ueberhang else None
        self.x = np.where(self.aktiv, self.behalten, 0.0)
        self.x[self.passiv] = 1.0
        self.U: list[np.ndarray | None] = [None] * len(lasten)
        self.verlauf: list[dict[str, Any]] = []
        self.xt = self.x.copy()
        self.xh = self.x.copy()

    def _dichte(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xt = self.filter.vor(x)
        xt[self.passiv] = 1.0
        xh = self.ueberhang.vor(xt) if self.ueberhang is not None else xt
        xh = np.where(self.aktiv, xh, 0.0)
        return xt, xh

    def _rueck(self, g_hat: np.ndarray) -> np.ndarray:
        g = self.ueberhang.rueck(g_hat) if self.ueberhang is not None else g_hat
        g = np.where(self.passiv, 0.0, g)
        return self.filter.rueck(g)

    def schritt(self, tol: float, abbruch: Callable[[], None] | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        xt, xh = self._dichte(self.x)
        self.xt, self.xh = xt, xh
        s = E_MIN + np.power(np.clip(xh, 0.0, 1.0), P_STRAFE) * (1.0 - E_MIN)
        self.mg.setze(np.where(self.aktiv, s, 0.0) * self.E)
        c = 0.0
        dc_hat = np.zeros_like(xh)
        its = []
        for i, F in enumerate(self.lasten):
            U, info = self.mg.loese(F, U0=self.U[i], tol=tol, abbruch=abbruch)
            self.U[i] = U
            its.append(info.get("iterationen", 0))
            c += float(np.vdot(F, U))
            w = self.mg.energie(U) * self.E
            dc_hat -= P_STRAFE * np.power(np.clip(xh, 0.0, 1.0), P_STRAFE - 1.0) * (1.0 - E_MIN) * w
        dc_hat = np.where(self.aktiv, dc_hat, 0.0)
        dc = self._rueck(dc_hat)
        dv = self._rueck(np.where(self.aktiv, 1.0, 0.0))
        frei = self.aktiv & ~self.passiv
        dc = np.minimum(dc, 0.0)
        dv = np.maximum(dv, 1e-12)
        v_jetzt = float(xh[self.aktiv].sum())
        x = self.x
        lo, hi = 0.0, 1e9 if not np.any(dc) else float(np.max(-dc / dv)) * 1e3 + 1e-30
        lo = 1e-40
        xneu = x
        for _ in range(80):
            lam = math.sqrt(lo * hi)
            xb = x * np.sqrt(np.maximum(-dc, 0.0) / (lam * dv))
            xneu = np.clip(xb, np.maximum(0.0, x - SCHRITT), np.minimum(1.0, x + SCHRITT))
            xneu = np.where(frei, xneu, x)
            v = v_jetzt + float(np.sum((dv * (xneu - x))[frei]))
            if v > self.ziel_volumen:
                lo = lam
            else:
                hi = lam
            if hi / lo < 1 + 1e-6:
                break
        aenderung = float(np.max(np.abs(xneu - x)[frei])) if frei.any() else 0.0
        self.x = xneu
        grau = float(4 * np.mean((xh * (1 - xh))[self.aktiv]))
        eintrag = {"c": c, "volumen": v_jetzt / max(self.n, 1), "aenderung": aenderung, "grau": grau,
                   "cg": its, "ms": round((time.perf_counter() - t0) * 1000, 1)}
        self.verlauf.append(eintrag)
        return eintrag

    def lauf(self, max_iter: int = 60, min_iter: int = 20, melde: Callable[[int, dict[str, Any]], None] | None = None,
             abbruch: Callable[[], None] | None = None, zeit_s: float | None = None) -> dict[str, Any]:
        """Iterieren bis zur Konvergenz: höchstens ``max_iter`` Schritte, mindestens ``min_iter``; fertig, wenn sich
        der Entwurf drei Schritte lang um weniger als 0,01 ändert oder die Nachgiebigkeit über fünf Schritte um weniger
        als 0,2 %. ``zeit_s``: Zeitgrenze (dann der Stand bis dahin, ``grund`` = "zeit")."""
        t0 = time.perf_counter()
        ruhig = 0
        grund = "iterationen"
        for it in range(max_iter):
            if abbruch is not None:
                abbruch()
            # CG-Toleranz: 3e-3 genügt mit Warmstart (Kragträger: gleiche Dichte bis auf 1e-4, 40 % weniger CG-Schritte)
            tol = 1e-2 if it < 5 else 3e-3
            e = self.schritt(tol, abbruch)
            if melde is not None:
                melde(it, e)
            ruhig = ruhig + 1 if e["aenderung"] < 0.01 else 0
            cs = [v["c"] for v in self.verlauf]
            flach = len(cs) > 6 and abs(cs[-1] - cs[-6]) <= 0.002 * abs(cs[-1])
            if it + 1 >= min_iter and (ruhig >= 3 or flach):
                grund = "konvergiert"
                break
            if zeit_s is not None and time.perf_counter() - t0 > zeit_s:
                grund = "zeit"
                break
        # Endstand: Dichte des letzten Entwurfs
        self.xt, self.xh = self._dichte(self.x)
        return {"iterationen": len(self.verlauf), "ms": round((time.perf_counter() - t0) * 1000, 1),
                "konvergiert": grund == "konvergiert", "grund": grund,
                "c": self.verlauf[-1]["c"] if self.verlauf else None,
                "c0": self.verlauf[0]["c"] if self.verlauf else None,
                "volumen": float(self.xh[self.aktiv].sum()) / max(self.n, 1)}
