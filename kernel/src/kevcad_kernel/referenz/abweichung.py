"""Abweichung zwischen Modell und Referenznetz (Phase 4): Abstand je Punkt als Farbkarte und Kennzahlen je Teil.

Zwei Richtungen, beide mit Vorzeichen **positiv = die Referenz liegt außerhalb des Modells** (der echte Gegenstand
ragt dort über das Modell hinaus, das Modell ist zu klein), negativ = die Referenz liegt innerhalb (Modell zu groß):

- ``auf_modell``: je Teil die Oberfläche des Modells (aus PART_UPSERT, fein unterteilt), Abstand jedes Punkts zur
  nächsten Stelle des Referenznetzes; Vorzeichen über die Außennormale des Modells.
- ``auf_referenz``: je Punkt des Referenznetzes der Abstand zur nächsten Stelle des Modells (alle Teile zusammen);
  Vorzeichen über die Außennormale des getroffenen Modelldreiecks.

Ein Punkt gilt als **nicht abgedeckt** (NaN, in der App grau), wenn die Referenz weiter als ``grenze_mm`` weg ist
oder nur schräg daneben liegt (Winkel zur Normale über 60°, ab 1 mm Abstand): etwa die Unterseite, die ein Scan nie
sieht, oder Bodenreste neben dem Gegenstand. Kennzahlen zählen nur abgedeckte Punkte, gewichtet mit ihrer Fläche.

Abstand Punkt ↔ Netz: Kandidaten über einen k-d-Baum aus Flächenproben (Schwerpunkt jedes Dreiecks und Proben im
Abstand ``h``, je Probe ihr Dreieck), dann exakt der nächste Punkt auf jedem Kandidatendreieck (Ericson,
„Real-Time Collision Detection“, 5.1.5) in Blöcken, damit der Speicher klein bleibt. Rein numpy und scipy, keine
OCCT-Formen: ein Lauf mit einem Scan von 225 000 Dreiecken und einem Modell mit 100 000 Punkten braucht rund 1 s.
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Any

import numpy as np

GRENZE_MIN_MM = 10.0
GRENZE_ANTEIL = 0.06  # der Diagonale des Referenznetzes
GRENZE_MAX_MM = 60.0
NAH_MM = 1.0  # bis hierhin zählt ein Punkt auch ohne Blick entlang der Normale als abgedeckt
COS_MIN = 0.5  # höchstens 60° zwischen Normale und Richtung zur Referenz
MAX_DREIECKE_FELD = 250_000  # alle Teile zusammen, nach dem Unterteilen
MAX_DREIECKE_TEIL = 60_000
KANTE_MIN_MM = 1.0
MAX_PROBEN = 400_000
KANDIDATEN = 8
BLOCK = 30_000
SKALEN_MM = (0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 20.0, 30.0, 50.0)


# ---------------------------------------------------------------------------------------------------------------------
# Geometrie

def naechster_punkt(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Nächster Punkt auf den Dreiecken (a, b, c) zu den Punkten p (alle (..., 3)); vektorisiert nach Ericson.

    Die Fälle schließen sich in Ericsons Reihenfolge aus (Ecke A, Ecke B, Kante AB, Ecke C, Kante AC, Kante BC, Innen);
    hier werden sie rückwärts überschrieben, damit der zuerst passende Fall gewinnt."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("...i,...i", ab, ap), np.einsum("...i,...i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("...i,...i", ab, bp), np.einsum("...i,...i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("...i,...i", ab, cp), np.einsum("...i,...i", ac, cp)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    eps = 1e-30
    nenner = va + vb + vc
    nenner = np.where(np.abs(nenner) < eps, eps, nenner)
    v = vb / nenner
    w = vc / nenner
    q = a + ab * v[..., None] + ac * w[..., None]
    # Kante BC
    e43, e56 = d4 - d3, d5 - d6
    t = e43 / np.where(np.abs(e43 + e56) < eps, eps, e43 + e56)
    m = (va <= 0) & (e43 >= 0) & (e56 >= 0)
    q = np.where(m[..., None], b + (c - b) * t[..., None], q)
    # Kante AC
    t = d2 / np.where(np.abs(d2 - d6) < eps, eps, d2 - d6)
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    q = np.where(m[..., None], a + ac * t[..., None], q)
    # Ecke C
    m = (d6 >= 0) & (d5 <= d6)
    q = np.where(m[..., None], c, q)
    # Kante AB
    t = d1 / np.where(np.abs(d1 - d3) < eps, eps, d1 - d3)
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    q = np.where(m[..., None], a + ab * t[..., None], q)
    # Ecke B
    m = (d3 >= 0) & (d4 <= d3)
    q = np.where(m[..., None], b, q)
    # Ecke A
    m = (d1 <= 0) & (d2 <= 0)
    q = np.where(m[..., None], a, q)
    return q


def flaechennormalen(V: np.ndarray, T: np.ndarray, N: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Einheitsnormalen und Flächen je Dreieck; mit Punktnormalen ``N`` nach außen gedreht (die Tessellierung liefert
    die Normalen der Flächen mit, der Umlaufsinn ist nicht immer verlässlich)."""
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(b - a, c - a)
    fl = np.linalg.norm(n, axis=1)
    n = n / np.maximum(fl, 1e-12)[:, None]
    if N is not None and len(N) == len(V):
        soll = N[T[:, 0]] + N[T[:, 1]] + N[T[:, 2]]
        n = np.where((np.einsum("ij,ij->i", n, soll) < 0)[:, None], -n, n)
    return n, fl / 2


class Flaeche:
    """Dreiecksnetz als Ziel von Abstandsabfragen (k-d-Baum aus Flächenproben, je Probe ihr Dreieck)."""

    def __init__(self, V: np.ndarray, T: np.ndarray, normalen: np.ndarray | None = None, h: float | None = None,
                 max_proben: int = MAX_PROBEN, seed: int = 7) -> None:
        from scipy.spatial import cKDTree

        self.V = np.ascontiguousarray(V, dtype=np.float64).reshape(-1, 3)
        T = np.ascontiguousarray(T, dtype=np.int64).reshape(-1, 3)
        n, fl = flaechennormalen(self.V, T)
        ok = fl > 1e-12
        self.T = T[ok]
        fl = fl[ok]
        self.n = normalen[ok] if normalen is not None else n[ok]
        a, b, c = self.V[self.T[:, 0]], self.V[self.T[:, 1]], self.V[self.T[:, 2]]
        proben = [(a + b + c) / 3]
        tri = [np.arange(len(self.T))]
        gesamt = float(fl.sum())
        if h is None:
            h = math.sqrt(gesamt / max(1, max_proben)) if gesamt > 0 else 1.0
        h = max(float(h), math.sqrt(gesamt / max(1, max_proben)) if gesamt > 0 else 0.0, 1e-3)
        # Zusätzliche Proben auf großen Dreiecken (Flächen des Modells sind oft wenige große Dreiecke)
        anzahl = np.floor(fl / (h * h)).astype(np.int64)
        gross = np.nonzero(anzahl > 0)[0]
        if len(gross):
            rng = np.random.default_rng(seed)
            wahl = np.repeat(gross, anzahl[gross])
            u, v = rng.random(len(wahl)), rng.random(len(wahl))
            aussen = u + v > 1
            u[aussen], v[aussen] = 1 - u[aussen], 1 - v[aussen]
            proben.append(a[wahl] + u[:, None] * (b[wahl] - a[wahl]) + v[:, None] * (c[wahl] - a[wahl]))
            tri.append(wahl)
        self.proben = np.concatenate(proben)
        self.proben_tri = np.concatenate(tri)
        self.baum = cKDTree(self.proben)
        self.h = h

    def abfrage(self, P: np.ndarray, k: int = KANDIDATEN, block: int = BLOCK
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Je Punkt: Abstand, nächster Punkt, Dreieck (Index in ``self.T``)."""
        P = np.ascontiguousarray(P, dtype=np.float64).reshape(-1, 3)
        n = len(P)
        d = np.empty(n)
        Q = np.empty((n, 3))
        t_out = np.empty(n, dtype=np.int64)
        if not len(self.T):
            d.fill(np.inf)
            Q[:] = P
            t_out.fill(-1)
            return d, Q, t_out
        k = max(1, min(k, len(self.proben)))
        for s in range(0, n, block):
            p = P[s:s + block]
            _, idx = self.baum.query(p, k=k, workers=-1)
            idx = np.asarray(idx).reshape(len(p), k)
            kand = self.proben_tri[idx]  # (m, k)
            a, b, c = self.V[self.T[kand, 0]], self.V[self.T[kand, 1]], self.V[self.T[kand, 2]]
            q = naechster_punkt(p[:, None, :], a, b, c)
            dist = np.linalg.norm(q - p[:, None, :], axis=2)
            j = np.argmin(dist, axis=1)
            r = np.arange(len(p))
            d[s:s + block] = dist[r, j]
            Q[s:s + block] = q[r, j]
            t_out[s:s + block] = kand[r, j]
        return d, Q, t_out


def verfeinern(V: np.ndarray, T: np.ndarray, n_tri: np.ndarray, kante: float
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Dreiecke gleichmäßig unterteilen, bis keine Kante länger als ``kante`` ist (je Dreieck ein Raster aus
    s² Teildreiecken). Rückgabe: Punkte, Dreiecke, Normale je Punkt (die des Ausgangsdreiecks), Fläche je Punkt
    (Teildreiecksfläche / 3 aufsummiert)."""
    V = np.asarray(V, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64)
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    laenge = np.maximum.reduce([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1),
                                np.linalg.norm(a - c, axis=1)])
    s_je = np.clip(np.ceil(laenge / max(kante, 1e-6)).astype(np.int64), 1, 64)
    punkte, dreiecke, normalen, gewichte = [], [], [], []
    basis = 0
    for s in np.unique(s_je):
        s = int(s)
        sel = np.nonzero(s_je == s)[0]
        # Raster (i, j) mit i + j <= s; Punkt = a + (b - a) i/s + (c - a) j/s
        ij = np.array([(i, j) for i in range(s + 1) for j in range(s + 1 - i)], dtype=np.float64)
        nr = {(int(i), int(j)): k for k, (i, j) in enumerate(ij)}
        lokal = []
        for i in range(s):
            for j in range(s - i):
                lokal.append((nr[(i, j)], nr[(i + 1, j)], nr[(i, j + 1)]))
                if i + j < s - 1:
                    lokal.append((nr[(i + 1, j)], nr[(i + 1, j + 1)], nr[(i, j + 1)]))
        lokal = np.asarray(lokal, dtype=np.int64)
        u, v = ij[:, 0] / s, ij[:, 1] / s
        A, B, C = a[sel], b[sel], c[sel]
        P = A[:, None, :] + (B - A)[:, None, :] * u[None, :, None] + (C - A)[:, None, :] * v[None, :, None]
        m = len(ij)
        punkte.append(P.reshape(-1, 3))
        versatz = basis + np.arange(len(sel), dtype=np.int64)[:, None, None] * m
        dreiecke.append((lokal[None, :, :] + versatz).reshape(-1, 3))
        normalen.append(np.repeat(n_tri[sel], m, axis=0))
        fl = np.linalg.norm(np.cross(B - A, C - A), axis=1) / 2 / (s * s)  # Fläche je Teildreieck
        # Gewicht je Rasterpunkt: Zahl der anliegenden Teildreiecke × Fläche / 3
        anliegend = np.zeros(m)
        np.add.at(anliegend, lokal.reshape(-1), 1.0)
        gewichte.append((fl[:, None] * anliegend[None, :] / 3).reshape(-1))
        basis += len(sel) * m
    if not punkte:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros((0, 3)), np.zeros(0)
    return (np.concatenate(punkte), np.concatenate(dreiecke), np.concatenate(normalen), np.concatenate(gewichte))


# ---------------------------------------------------------------------------------------------------------------------
# Werte und Kennzahlen

def grenze_aus(ref_V: np.ndarray, grenze_mm: float | None = None) -> float:
    if grenze_mm is not None and grenze_mm > 0:
        return float(grenze_mm)
    if not len(ref_V):
        return GRENZE_MIN_MM
    diag = float(np.linalg.norm(ref_V.max(0) - ref_V.min(0)))
    return float(min(GRENZE_MAX_MM, max(GRENZE_MIN_MM, GRENZE_ANTEIL * diag)))


def _gewichtetes_quantil(x: np.ndarray, w: np.ndarray, q: float) -> float:
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w)
    if c[-1] <= 0:
        return float(x[-1])
    return float(x[min(len(x) - 1, int(np.searchsorted(c, q * c[-1])))])


def kennzahlen(werte: np.ndarray, gewichte: np.ndarray, punkte: np.ndarray | None = None) -> dict[str, Any]:
    """Mittlere, größte (und 95-%-) Abweichung, Versatz (Mittel mit Vorzeichen), Anteil abgedeckt (nach Fläche)."""
    w = np.asarray(gewichte, float)
    v = np.asarray(werte, float)
    ok = np.isfinite(v)
    gesamt = float(w.sum())
    out: dict[str, Any] = {"abgedeckt": round(float(w[ok].sum() / gesamt), 3) if gesamt > 0 else 0.0,
                           "punkte": int(len(v))}
    if not ok.any():
        out.update(mittel_mm=None, max_mm=None, p95_mm=None, versatz_mm=None, ort_max=None)
        return out
    a, wo = np.abs(v[ok]), w[ok]
    sw = float(wo.sum()) or 1.0
    i = int(np.argmax(a))
    out.update(mittel_mm=round(float((a * wo).sum() / sw), 2), max_mm=round(float(a[i]), 2),
               p95_mm=round(_gewichtetes_quantil(a, wo, 0.95), 2),
               versatz_mm=round(float((v[ok] * wo).sum() / sw), 2),
               ort_max=[round(float(x), 1) for x in punkte[ok][i]] if punkte is not None else None)
    return out


def skala_auto(felder: list[dict[str, Any]]) -> float:
    """Spanne der Legende: 95-%-Wert aller abgedeckten Abweichungen, aufgerundet auf 0,5 / 1 / 2 / 3 / 5 / 10 / 15 …
    mm."""
    werte = [f["kennzahlen"].get("p95_mm") for f in felder if f.get("kennzahlen", {}).get("p95_mm") is not None]
    p = max(werte) if werte else 1.0
    for s in SKALEN_MM:
        if p <= s:
            return s
    return SKALEN_MM[-1]


def _werte(d: np.ndarray, richtung: np.ndarray, normale: np.ndarray, grenze: float) -> np.ndarray:
    """Abstand mit Vorzeichen (positiv, wenn ``richtung`` mit der Normale zeigt); NaN = nicht abgedeckt."""
    proj = np.einsum("ij,ij->i", richtung, normale)
    cos = np.abs(proj) / np.maximum(d, 1e-9)
    werte = np.where(proj >= 0, d, -d)
    ok = np.isfinite(d) & (d <= grenze) & ((d <= NAH_MM) | (cos >= COS_MIN))
    return np.where(ok, werte, np.nan)


def kantenlaenge(flaechen: list[float]) -> tuple[float, list[float]]:
    """Kantenlänge für das Unterteilen: insgesamt höchstens ``MAX_DREIECKE_FELD``, je Teil ``MAX_DREIECKE_TEIL``
    (gleichseitig etwa 0,43 · L² je Dreieck)."""
    gesamt = sum(flaechen)
    L = max(KANTE_MIN_MM, math.sqrt(gesamt / (0.43 * MAX_DREIECKE_FELD)) if gesamt > 0 else KANTE_MIN_MM)
    return L, [max(L, math.sqrt(f / (0.43 * MAX_DREIECKE_TEIL))) for f in flaechen]


def vorbereiten(t: dict[str, Any]) -> dict[str, Any] | None:
    """Teil (``name``, ``positions``, ``triangles``, optional ``normals``) mit Außennormalen und Fläche; None ohne
    Dreiecke."""
    V = np.asarray(t["positions"], np.float64).reshape(-1, 3)
    T = np.asarray(t["triangles"], np.int64).reshape(-1, 3)
    if not len(T):
        return None
    N = t.get("normals")
    n, fl = flaechennormalen(V, T, np.asarray(N, np.float64).reshape(-1, 3) if N is not None else None)
    ok = fl > 1e-12
    return {"name": t["name"], "V": V, "T": T[ok], "n": n[ok], "flaeche": float(fl[ok].sum())}


def teil_feld(v: dict[str, Any], kante: float, ref: Flaeche, grenze: float) -> dict[str, Any]:
    """Abweichung auf der Oberfläche eines vorbereiteten Teils (Kantenlänge ``kante`` nach dem Unterteilen)."""
    P, T2, N2, W = verfeinern(v["V"], v["T"], v["n"], kante)
    d, Q, _ = ref.abfrage(P)
    werte = _werte(d, Q - P, N2, grenze)
    return {"teil": v["name"], "punkte": P.astype(np.float32), "dreiecke": T2.astype(np.uint32),
            "werte": werte.astype(np.float32), "kennzahlen": kennzahlen(werte, W, P), "kante_mm": round(kante, 2)}


def auf_modell(teile: list[dict[str, Any]], ref: Flaeche, grenze: float) -> list[dict[str, Any]]:
    """Je Teil (``name``, ``positions``, ``normals``, ``triangles``) die Abweichung auf der Oberfläche des Modells."""
    vorbereitet = [v for v in (vorbereiten(t) for t in teile) if v is not None]
    _, kanten = kantenlaenge([v["flaeche"] for v in vorbereitet])
    return [teil_feld(v, L, ref, grenze) for v, L in zip(vorbereitet, kanten)]


def auf_referenz(teile: list[dict[str, Any]], ref_V: np.ndarray, ref_T: np.ndarray, grenze: float
                 ) -> dict[str, Any] | None:
    """Abweichung je Punkt des Referenznetzes zum Modell (alle Teile zusammen)."""
    Vs, Ts, Ns = [], [], []
    basis = 0
    for t in teile:
        V = np.asarray(t["positions"], np.float64).reshape(-1, 3)
        T = np.asarray(t["triangles"], np.int64).reshape(-1, 3)
        if not len(T):
            continue
        n, _ = flaechennormalen(V, T, np.asarray(t.get("normals"), np.float64).reshape(-1, 3)
                                if t.get("normals") is not None else None)
        Vs.append(V)
        Ts.append(T + basis)
        Ns.append(n)
        basis += len(V)
    if not Vs or not len(ref_V):
        return None
    modell = Flaeche(np.concatenate(Vs), np.concatenate(Ts), normalen=np.concatenate(Ns), h=1.5)
    P = np.asarray(ref_V, np.float64).reshape(-1, 3)
    d, Q, tri = modell.abfrage(P)
    werte = _werte(d, P - Q, modell.n[np.maximum(tri, 0)], grenze)
    T = np.asarray(ref_T, np.int64).reshape(-1, 3)
    # Gewicht je Punkt: ein Drittel der anliegenden Dreiecksflächen
    _, fl = flaechennormalen(P, T)
    W = np.zeros(len(P))
    for k in range(3):
        np.add.at(W, T[:, k], fl / 3)
    return {"teil": None, "punkte": P.astype(np.float32), "dreiecke": T.astype(np.uint32),
            "werte": werte.astype(np.float32), "kennzahlen": kennzahlen(werte, W, P)}


def schluessel(*teile: Any) -> str:
    h = hashlib.sha1()
    for t in teile:
        h.update(repr(t).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:20]


def rechnen(teile: list[dict[str, Any]], ref_V: np.ndarray, ref_T: np.ndarray, *, grenze_mm: float | None = None,
            richtungen: tuple[str, ...] = ("modell", "referenz")) -> dict[str, Any]:
    """Beide Richtungen auf einmal. {"grenze_mm", "skala_mm", "modell": [Feld je Teil], "referenz": Feld | None,
    "ms"}"""
    t0 = time.perf_counter()
    grenze = grenze_aus(np.asarray(ref_V), grenze_mm)
    out: dict[str, Any] = {"grenze_mm": round(grenze, 1), "modell": [], "referenz": None}
    if "modell" in richtungen and teile and len(ref_T):
        ref = Flaeche(ref_V, ref_T)
        out["modell"] = auf_modell(teile, ref, grenze)
    t1 = time.perf_counter()
    if "referenz" in richtungen and teile:
        out["referenz"] = auf_referenz(teile, ref_V, ref_T, grenze)
    out["skala_mm"] = skala_auto(out["modell"] + ([out["referenz"]] if out["referenz"] else []))
    out["ms"] = {"modell": round((t1 - t0) * 1000, 1), "referenz": round((time.perf_counter() - t1) * 1000, 1)}
    return out
