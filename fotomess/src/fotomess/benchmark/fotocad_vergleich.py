"""Vergleich mit dem bisherigen Verfahren (fotocad): Powell auf der weichen Überdeckung, jede Auswertung ein
GPU-Bild des ganzen Netzes (fotocad.netz_gl, 8-fach Kantenglättung), Kameras als Umlauf (fotocad.kamera.packe),
danach die Maße über alle Fotos (wie messung/netz_buendel.py der Küche: Kamera grob 700 px, fein 1200 px; Maße
900 px, Vorgabe zugunsten der Startwerte).

Gleiche Startkameras wie fotomess (aus dessen Grobsuche), damit nur das Einpassen verglichen wird. Die Grobstufe
der Küche (messung/mehrfach.py mit Ersatzkörpern) ist projektspezifisch und hier nicht nachgebaut.
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np
from scipy.optimize import minimize

from ..kamera import Kamera

SCHRITT_MASS = 3.0
VORGABE_MM = 15.0
VORGABE_KOSTEN = 0.0001


def _fuelle(m):
    hh, ww = m.shape
    flut = np.pad((m > 0).astype(np.uint8), 1)
    maske = np.zeros((hh + 4, ww + 4), np.uint8)
    cv2.floodFill(flut, maske, (0, 0), 2)
    return (flut[1:-1, 1:-1] != 2).astype(np.float32)


class FotocadAnsicht:
    def __init__(self, bild, netz, breite):
        self.bild, self.netz = bild, netz
        st = bild.stufe(breite)
        self.s = st.s
        self.breite, self.hoehe = st.breite, st.hoehe
        self.foto = cv2.GaussianBlur((st.weich >= 0.5).astype(np.float32), (0, 0), 0.7)
        self.gueltig = np.ones(self.foto.shape, bool) if st.ignorieren is None else ~st.ignorieren


class Fotocad:
    def __init__(self, netze):
        from fotocad.netz_gl import Netz, Zeichner
        self.netze = netze
        self.z = {}
        self.stand = {}
        for name, n in netze.items():
            self.z[name] = Zeichner(Netz(dreiecke=self._dreiecke(n, n.theta0)))
            self.stand[name] = None
        self.auswertungen = 0

    @staticmethod
    def _dreiecke(netz, theta):
        V = netz.ecken(theta)
        return {t: V[netz.tris[netz.tri_teil == i]].reshape(-1, 3) for i, t in enumerate(netz.teile)}

    def setze(self, name, theta):
        key = tuple(np.round(theta, 4))
        if self.stand[name] != key:
            self.z[name].setze_netz(self._dreiecke(self.netze[name], theta))
            self.stand[name] = key

    def iou(self, ans, cam, winkel, name, theta):
        from fotocad.netz_gl import haube_matrix
        self.setze(name, theta)
        n = self.netze[name]
        bew = {}
        if n.gelenke and winkel is not None and winkel[0]:
            p = n.gelenk_punkt(0, theta)
            bew = {1: haube_matrix(float(winkel[0]), p[1], p[2])}
        m = self.z[name].maske(cam.als_fotocad(), ans.s, bew, groesse=(ans.breite, ans.hoehe))
        m = np.maximum(m, _fuelle(m > 0.5))
        f, g = ans.foto, ans.gueltig
        self.auswertungen += 1
        inter = (f * m)[g].sum()
        return float(inter / max((f + m - f * m)[g].sum(), 1.0))


def kamera_einpassen(fc, ans, kam, winkel, name, theta, maxfev, mit_gelenk):
    from fotocad.kamera import entpacke, packe, schritte
    netz = fc.netze[name]
    dreh = netz.mitte
    extra = [float(winkel[0])] if mit_gelenk else []
    v0 = packe(kam.als_fotocad(), dreh, extra)
    sk = schritte(v0, [1.0] if mit_gelenk else [])

    def ziel(x):
        c, e = entpacke(v0 + x * sk, kam.w, kam.h, dreh, abstand_min=300.0)
        w = np.array([e[0]]) if mit_gelenk else winkel
        return 1.0 - fc.iou(ans, Kamera.aus_fotocad(c), w, name, theta)

    r = minimize(ziel, np.zeros(len(v0)), method="Powell", options=dict(xtol=1e-3, ftol=1e-7, maxfev=maxfev))
    c, e = entpacke(v0 + r.x * sk, kam.w, kam.h, dreh, abstand_min=300.0)
    return Kamera.aus_fotocad(c), (np.array([e[0]]) if mit_gelenk else winkel), 1.0 - r.fun


def lauf(netze, ansichten, theta_start, frei, breiten=(700, 1200), breite_masse=900, maxfev=(1500, 2500, 4000),
         protokoll=None):
    """ansichten: Liste (bild, netzname, startkamera, startwinkel, gelenk_frei). Rückgabe: theta, Kameras, Winkel,
    Zeiten, Zahl der Auswertungen."""
    t0 = time.perf_counter()
    fc = Fotocad(netze)
    namen = list(theta_start)
    kams, winkel = [], []
    for bild, name, kam, w, frei_g in ansichten:
        th = np.array([theta_start[k] for k in netze[name].parameter])
        for breite, fev in zip(breiten, maxfev[:2]):
            ans = FotocadAnsicht(bild, netze[name], breite)
            kam, w, q = kamera_einpassen(fc, ans, kam, w, name, th, fev, frei_g)
        kams.append(kam)
        winkel.append(w)
        if protokoll:
            protokoll(f"  fotocad {bild.name}: IoU {q:.4f}")
    t1 = time.perf_counter()
    theta = dict(theta_start)
    ans_m = [FotocadAnsicht(b, netze[n], breite_masse) for b, n, *_ in ansichten]
    x0 = np.zeros(len(frei))

    def th_von(x, name):
        d = dict(theta)
        for k, v in zip(frei, x * SCHRITT_MASS):
            d[k] = theta_start[k] + v
        return np.array([d[k] for k in netze[name].parameter])

    def ziel(x):
        s = 0.0
        for a, (b, n, *_), kam, w in zip(ans_m, ansichten, kams, winkel):
            s += 1.0 - fc.iou(a, kam, w, n, th_von(x, n))
        vorgabe = VORGABE_KOSTEN * float(((x * SCHRITT_MASS / VORGABE_MM) ** 2).sum())
        return s / len(ans_m) + vorgabe

    if frei:
        r = minimize(ziel, x0, method="Powell", options=dict(xtol=1e-2, ftol=1e-7, maxfev=maxfev[2]))
        for k, v in zip(frei, r.x * SCHRITT_MASS):
            theta[k] = theta_start[k] + v
    t2 = time.perf_counter()
    return dict(theta=theta, kameras=kams, winkel=winkel, zeiten=dict(kameras=t1 - t0, masse=t2 - t1, gesamt=t2 - t0),
                auswertungen=fc.auswertungen)
