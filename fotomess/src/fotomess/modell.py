"""Modellanbindung: build123d-Modell als Netz, das linear von den Maßen abhängt, mit Kanten-Topologie und Gelenken.

Gebaut und abgeleitet wird mit fotocad.cad_netz (Kevins Verfahren: je Maß eine gebaute Variante, Flächen über
Schwerpunkt und Normale zugeordnet). Hier kommt dazu, was das Einpassen an Kanten braucht:

- Eckpunkte je Bauteil verschweißt (gleiche Lage = ein Punkt), Ableitung je Punkt nach allen Maßen (nv, 3, k).
- Kanten mit ihren zwei Dreiecken; Merkmalskanten sind Kanten mit Knick über KNICK_GRAD oder Randkanten.
- Gelenke: Bauteilgruppen, die sich je Bild um eine Achse drehen (Haube, Lenkrollen). Ableitung analytisch.

Je Ansicht liefert `kanten_proben` die sichtbaren Kandidaten: Merkmalskanten mit einer zugewandten Fläche und
Umrisskanten (eine Fläche zugewandt, die andere abgewandt), als Punkte im Abstand von etwa `abstand` Pixeln.
"""
from __future__ import annotations

import hashlib
import math
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get("FOTOMESS_CACHE", Path.home() / "Library/Caches/de.upvis.kevcad.testdaten/fotomess"))
KNICK_GRAD = 25.0


@dataclass
class Gelenk:
    """Drehgelenk: Bauteile, deren Name mit einem der Präfixe beginnt, drehen sich um die Achse (punkt, richtung).
    punkt darf von den Maßen abhängen: punkt_ableitung {Maß: d punkt / d Maß}."""
    name: str
    praefixe: tuple
    punkt: tuple
    richtung: tuple
    punkt_ableitung: dict = field(default_factory=dict)
    start: float = 0.0                   # Startwinkel in Grad


def drehung(richtung, winkel_grad):
    a = np.asarray(richtung, float)
    a = a / np.linalg.norm(a)
    w = math.radians(winkel_grad)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(w) * K + (1 - math.cos(w)) * K @ K


class ParamNetz:
    """Netz V(theta) = V0 + D (theta - theta0), verschweißt je Bauteil, mit Kanten und Gelenken."""

    def __init__(self, basis, ableitung, parameter, p0, gelenke=(), auslassen=(), knick_grad=KNICK_GRAD):
        self.parameter = list(parameter)
        self.p0 = dict(p0)
        self.theta0 = np.array([float(_wert(p0, k)) for k in self.parameter])
        self.gelenke = list(gelenke)
        k = len(self.parameter)
        V, D, T, teil_id, namen = [], [], [], [], []
        offset = 0
        for name in sorted(basis):
            if name.startswith(tuple(auslassen)):
                continue
            flaechen = basis[name]
            tris = np.concatenate([np.asarray(f, float).reshape(-1, 3, 3) for f in flaechen])
            ecken = tris.reshape(-1, 3)
            dk = np.zeros((len(ecken), 3, k), np.float32)
            for j, p in enumerate(self.parameter):
                d = ableitung.get((p, name))
                if d is not None:
                    dk[:, :, j] = np.asarray(d, np.float32).reshape(-1, 3)
            schl = np.round(ecken, 3)
            uniq, inv = np.unique(schl, axis=0, return_inverse=True)
            inv = inv.ravel()
            nv = len(uniq)
            pos = np.zeros((nv, 3))
            np.add.at(pos, inv, ecken)
            zahl = np.bincount(inv, minlength=nv).astype(float)
            pos /= zahl[:, None]
            dv = np.zeros((nv, 3, k), np.float32)
            np.add.at(dv, inv, dk)
            dv /= zahl[:, None, None]
            tri = inv.reshape(-1, 3)
            # entartete Dreiecke weg
            a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
            fl = np.linalg.norm(np.cross(b - a, c - a), axis=1)
            tri = tri[(fl > 1e-6) & (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])]
            V.append(pos)
            D.append(dv)
            T.append(tri + offset)
            teil_id.append(np.full(len(tri), len(namen), np.int32))
            namen.append(name)
            offset += nv
        self.teile = namen
        self.V0 = np.concatenate(V)
        self.D = np.concatenate(D)                        # (nv, 3, k)
        self.D2 = self.D.reshape(len(self.V0) * 3, k)
        self.tris = np.concatenate(T).astype(np.int32)
        self.tri_teil = np.concatenate(teil_id)
        self.punkt_teil = np.zeros(len(self.V0), np.int32)
        self.punkt_teil[self.tris.ravel()] = np.repeat(self.tri_teil, 3)
        self._kanten(knick_grad)
        # Gelenk je Eckpunkt (-1 = fest)
        self.punkt_gelenk = np.full(len(self.V0), -1, np.int32)
        for g, gel in enumerate(self.gelenke):
            ids = [i for i, n in enumerate(self.teile) if n.lower().startswith(tuple(p.lower() for p in gel.praefixe))]
            self.punkt_gelenk[np.isin(self.punkt_teil, ids)] = g
        lo, hi = self.V0.min(0), self.V0.max(0)
        self.mitte = (lo + hi) / 2
        self.radius = float(np.linalg.norm(hi - lo) / 2)

    # ------------------------------------------------------------------ Topologie
    def _kanten(self, knick_grad):
        t = self.tris
        e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
        tri = np.concatenate([np.arange(len(t))] * 3)
        e = np.sort(e, axis=1)
        schl = e[:, 0].astype(np.int64) * (len(self.V0) + 1) + e[:, 1]
        ordnung = np.argsort(schl, kind="stable")
        schl, e, tri = schl[ordnung], e[ordnung], tri[ordnung]
        neu = np.r_[True, schl[1:] != schl[:-1]]
        start = np.flatnonzero(neu)
        zahl = np.diff(np.r_[start, len(schl)])
        kanten = e[start]
        t0 = tri[start]
        t1 = np.where(zahl >= 2, tri[np.minimum(start + 1, len(tri) - 1)], -1)
        self.kanten = kanten.astype(np.int32)
        self.kanten_tris = np.stack([t0, t1], 1).astype(np.int32)
        n = self._normalen(self.V0)
        cosw = np.where(t1 >= 0, np.einsum("ij,ij->i", n[t0], n[np.maximum(t1, 0)]), -1.0)
        self.kante_merkmal = (cosw < math.cos(math.radians(knick_grad))) | (t1 < 0) | (zahl > 2)

    def _aktiv(self):
        """Kanten, die je Ansicht überhaupt Umriss oder Merkmal sein können: alles außer den Diagonalen ebener
        Flächen (Knick unter einem halben Grad). Bei CAD-Netzen aus Quadern sind das meist weniger als die Hälfte."""
        if getattr(self, "_aktiv_cache", None) is None:
            n = self._normalen(self.V0)
            t0, t1 = self.kanten_tris[:, 0], self.kanten_tris[:, 1]
            cosw = np.where(t1 >= 0, np.einsum("ij,ij->i", n[t0], n[np.maximum(t1, 0)]), -1.0)
            aktiv = np.flatnonzero(self.kante_merkmal | (cosw < math.cos(math.radians(0.5))))
            kt = self.kanten_tris[aktiv]
            tris = np.unique(kt[kt >= 0])
            lut = np.full(len(self.tris), -1, np.int64)
            lut[tris] = np.arange(len(tris))
            akt = np.where(kt >= 0, lut[np.maximum(kt, 0)], -1)
            self._aktiv_cache = (aktiv, tris, akt)
        return self._aktiv_cache

    def _normalen(self, V):
        a, b, c = V[self.tris[:, 0]], V[self.tris[:, 1]], V[self.tris[:, 2]]
        n = np.cross(b - a, c - a)
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)

    # ------------------------------------------------------------------ Lage
    def ecken(self, theta, winkel=None):
        """Eckpunkte bei Maßen theta (absolut, Reihenfolge self.parameter) und Gelenkwinkeln (Grad)."""
        d = np.asarray(theta, float) - self.theta0
        V = self.V0 + (self.D2 @ d.astype(np.float32)).reshape(-1, 3) if len(d) else self.V0.copy()
        if winkel is not None and self.gelenke:
            for g, gel in enumerate(self.gelenke):
                w = float(winkel[g])
                if not w:
                    continue
                m = self.punkt_gelenk == g
                p = self.gelenk_punkt(g, theta)
                R = drehung(gel.richtung, w)
                V[m] = (V[m] - p) @ R.T + p
        return V

    def ecken_teil(self, ids, theta, winkel=None):
        """Nur die Eckpunkte ids (schneller als ecken, wenn nur Kantenpunkte gebraucht werden)."""
        d = (np.asarray(theta, float) - self.theta0).astype(np.float32)
        V = self.V0[ids] + (self.D[ids] @ d) if len(d) else self.V0[ids].copy()
        if winkel is not None and self.gelenke:
            g_pkt = self.punkt_gelenk[ids]
            for g, gel in enumerate(self.gelenke):
                w = float(winkel[g])
                m = g_pkt == g
                if not w or not m.any():
                    continue
                p = self.gelenk_punkt(g, theta)
                V[m] = (V[m] - p) @ drehung(gel.richtung, w).T + p
        return V

    def gelenk_punkt(self, g, theta):
        gel = self.gelenke[g]
        p = np.array(gel.punkt, float)
        for k, dp in gel.punkt_ableitung.items():
            if k in self.parameter:
                j = self.parameter.index(k)
                p = p + (theta[j] - self.theta0[j]) * np.asarray(dp, float)
        return p

    def ableitung_punkte(self, ids_a, ids_b, s, theta, winkel=None, V=None):
        """Ableitung der Punkte (1-s) V[a] + s V[b] nach theta (n, 3, k) und nach den Gelenkwinkeln (n, 3, g)
        in Bogenmaß; X sind die Punkte selbst. V: Eckpunkte bei (theta, winkel), falls schon berechnet."""
        s = s[:, None, None]
        dX = ((1 - s) * self.D[ids_a] + s * self.D[ids_b]).astype(np.float64)
        if V is None:
            V = self.ecken(theta, winkel)
        X = (1 - s[:, :, 0]) * V[ids_a] + s[:, :, 0] * V[ids_b]
        ng = len(self.gelenke)
        dW = np.zeros((len(X), 3, ng))
        if ng and winkel is not None:
            g_pkt = self.punkt_gelenk[ids_a]
            for g, gel in enumerate(self.gelenke):
                m = g_pkt == g
                if not m.any():
                    continue
                R = drehung(gel.richtung, float(winkel[g]))
                dX[m] = np.einsum("ij,njk->nik", R, dX[m])
                a = np.asarray(gel.richtung, float)
                a = a / np.linalg.norm(a)
                p = self.gelenk_punkt(g, theta)
                dW[m, :, g] = np.cross(a, X[m] - p)
                # Achspunkt hängt von Maßen ab: Punkt bewegt sich mit (I - R) dp
                for k, dp in gel.punkt_ableitung.items():
                    if k in self.parameter:
                        j = self.parameter.index(k)
                        dX[m, :, j] += (np.eye(3) - R) @ np.asarray(dp, float)
        return X, dX, dW

    # ------------------------------------------------------------------ Kanten je Ansicht
    def kanten_proben(self, V, kamera, s, abstand=3.0, hoechstens=4000, rand=2.0):
        """Kandidaten-Kantenpunkte für eine Ansicht.

        Rückgabe dict: a, b (Eckpunkt-Ids), s (Lage auf der Kante), umriss (bool, eine Seite abgewandt), u (Bild-
        punkte der Stufe s), z (Tiefe). Sichtbarkeit prüft der Aufrufer am Tiefenbild."""
        C = kamera.zentrum
        aktiv, atris, akt = self._aktiv()
        T = self.tris[atris]
        a_, b_, c_ = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        n = np.cross(b_ - a_, c_ - a_)
        vorn = np.einsum("ij,ij->i", n, C - (a_ + b_ + c_) / 3) > 0
        t0, t1 = akt[:, 0], akt[:, 1]
        v0 = vorn[t0]
        v1 = np.where(t1 >= 0, vorn[np.maximum(t1, 0)], False)
        umriss_a = (v0 != v1) | ((t1 < 0) & v0)
        merkmal = self.kante_merkmal[aktiv] & (v0 | v1)
        sel = np.flatnonzero(umriss_a | merkmal)
        if not len(sel):
            return None
        wahl = aktiv[sel]
        umriss = np.zeros(len(self.kanten), bool)
        umriss[wahl] = umriss_a[sel]
        a, b = self.kanten[wahl, 0], self.kanten[wahl, 1]
        ua, za = kamera.projiziere(V[a], s)
        ub, zb = kamera.projiziere(V[b], s)
        ok = (za > 1) & (zb > 1)
        laenge = np.linalg.norm(ub - ua, axis=1)
        gesamt = float(laenge[ok].sum())
        if gesamt <= 0:
            return None
        abst = max(abstand, gesamt / hoechstens)
        zahl = np.where(ok, np.floor(laenge / abst).astype(int), 0)
        zahl = np.where(ok & (laenge >= abst * 0.5) & (zahl == 0), 1, zahl)
        ke = np.repeat(np.arange(len(wahl)), zahl)
        if not len(ke):
            return None
        erste = np.cumsum(zahl) - zahl
        rang = np.arange(len(ke)) - np.repeat(erste, zahl)
        sp = (rang + 0.5) / np.repeat(np.maximum(zahl, 1), zahl)
        A, B = a[ke], b[ke]
        X = (1 - sp[:, None]) * V[A] + sp[:, None] * V[B]
        u, z = kamera.projiziere(X, s)
        d = ub[ke] - ua[ke]
        d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
        breite, hoehe = kamera.w * s, kamera.h * s
        drin = (u[:, 0] > rand) & (u[:, 0] < breite - rand) & (u[:, 1] > rand) & (u[:, 1] < hoehe - rand)
        return dict(a=A[drin], b=B[drin], s=sp[drin], umriss=umriss[wahl][ke][drin], u=u[drin], z=z[drin],
                    richtung=d[drin], kante=wahl[ke][drin])

    # ------------------------------------------------------------------ Speichern
    def speichere(self, pfad):
        pfad = Path(pfad)
        tmp = pfad.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(pfad)

    @staticmethod
    def lade(pfad):
        with open(pfad, "rb") as f:
            return pickle.load(f)


def _wert(p, k):
    if "." in k:
        name, i = k.split(".")
        return p[name][int(i)]
    return p[k]


def cache_schluessel(*teile):
    h = hashlib.sha1()
    for t in teile:
        h.update(repr(t).encode())
    return h.hexdigest()[:16]


def baue_param_netz(bauer, p, parameter, argumente=None, gelenke=(), auslassen=(), prozesse=4, cache=True,
                    schritt=0.5, datei_stand=None):
    """ParamNetz aus einem build123d-Bauer ("datei.py:funktion" -> Compound mit benannten Teilen), zwischengespeichert.
    Die Ableitungen baut fotocad.cad_netz.Jacobi aus 1 + len(parameter) Varianten (parallel)."""
    os.environ.setdefault("FOTOCAD_TMP", str(CACHE / "bau"))
    argumente = dict(argumente or {})
    stand = datei_stand
    if stand is None and isinstance(bauer, str):
        datei = bauer.rsplit(":", 1)[0]
        try:
            stand = Path(datei).stat().st_mtime
        except OSError:
            stand = None
    schl = cache_schluessel(bauer, sorted(p.items()), parameter, sorted(argumente.items()), stand, schritt,
                            [(g.name, g.praefixe, g.punkt, g.richtung) for g in gelenke], tuple(auslassen))
    pfad = CACHE / "netze" / f"netz_{schl}.pkl"
    if cache and pfad.exists():
        return ParamNetz.lade(pfad)
    from fotocad.cad_netz import Jacobi
    from .system import warte_auf_speicher
    warte_auf_speicher(25)
    jac = Jacobi(p, bauer, argumente, parameter, schritt=schritt, prozesse=prozesse)
    netz = ParamNetz(jac.basis, jac.ableitung, parameter, p, gelenke=gelenke, auslassen=auslassen)
    netz.unstetig = jac.unstetig
    if cache:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        netz.speichere(pfad)
    return netz
