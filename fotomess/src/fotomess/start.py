"""Startwerte für die Kameras ohne Vorwissen über die Lage: Grobsuche über die Silhouette, viele Kandidaten auf einmal
auf der GPU (Kachel-Atlas), dazu eine Feinsuche um die besten.

Ablauf je Bild (Maske nötig):
1. Kandidatendrehungen aus Azimut, Höhe und Roll (Roll nur 0 oder 180 Grad: Kamera waagerecht gehalten, Objekt
   aufrecht oder auf dem Kopf). Je Kandidat eine Normkamera mit dem Objekt in der Mitte, alle in einem Atlas.
2. Aus Fläche und Schwerpunkt jeder Kachel folgt die Verschiebung, mit der die Silhouette Fläche und Schwerpunkt
   der Bildmaske trifft (Abstand über die Fläche, Lage über den Schwerpunkt, Brennweite aus der Vorgabe).
3. Alle so gesetzten Kandidaten noch einmal in Bildgröße (klein) zeichnen und gegen die Maske vergleichen
   (Überdeckung, IoU). Die besten, untereinander verschiedenen, kommen in die Feinsuche (kleinere Winkelschritte)
   und dann als Startwerte ins Einpassen.
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

from .gl import fuer_netz
from .kamera import Kamera, blick, exp_so3, winkel_zwischen


def _kandidaten(azimute, hoehen, rolls):
    out = []
    for r in rolls:
        for e in hoehen:
            for a in azimute:
                out.append((a, e, r))
    return out


def _momente(m):
    """Fläche und Schwerpunkt je Kachel (n, h, w) uint8/bool."""
    m = m.astype(np.float32) / 255.0 if m.dtype == np.uint8 else np.clip(m.astype(np.float32), 0.0, 1.0)
    n, h, w = m.shape
    A = m.sum((1, 2))
    ys = np.arange(h, dtype=np.float32) + 0.5
    xs = np.arange(w, dtype=np.float32) + 0.5
    cx = (m.sum(1) * xs).sum(1) / np.maximum(A, 1)
    cy = (m.sum(2) * ys).sum(1) / np.maximum(A, 1)
    return A, cx, cy


def _iou(kacheln, maske):
    k = kacheln > 127
    m = maske[None] > 0.5
    inter = (k & m).sum((1, 2))
    vere = (k | m).sum((1, 2))
    return inter / np.maximum(vere, 1)


def setze_kameras(zr, drehungen, maske_klein, s_klein, f, w, h, mitte, radius, kachel=64):
    """Je Drehung eine Kamera, deren Silhouette Fläche und Schwerpunkt der Maske trifft."""
    d0 = 3.0 * radius
    f0 = 0.42 * kachel * d0 / radius
    norm = []
    for R in drehungen:
        C = mitte - d0 * R[2]
        norm.append(Kamera(R=R, t=-R @ C, f=f0, w=kachel, h=kachel))
    k = zr.atlas(norm, 1.0, (kachel, kachel))
    A, cx, cy = _momente(k)
    Am, mx, my = _momente(maske_klein[None])
    # in Originalpixeln
    Ai = Am[0] / s_klein ** 2
    ci = np.array([mx[0], my[0]]) / s_klein
    out = []
    for R, a, x, y in zip(drehungen, A, cx, cy):
        if a < 4:
            out.append(None)
            continue
        d = d0 * math.sqrt((a / f0 ** 2) / (Ai / f ** 2))
        off = np.array([(x - kachel / 2) / f0, (y - kachel / 2) / f0]) * d0 / d       # Winkel Schwerpunkt - Mitte
        phi = (ci - np.array([w / 2, h / 2])) / f - off
        Xo = d * np.array([phi[0], phi[1], 1.0])
        out.append(Kamera(R=R, t=Xo - R @ mitte, f=f, w=w, h=h))
    return out


def grobsuche(netz, theta, maske, f, w, h, winkel=None, azimute=None, hoehen=None, rolls=(0.0,), beste=4,
              breite_klein=160, fein=True, zeichner=None, protokoll=None, paare=None):
    """Grobe Kameralage aus der Silhouette. maske: float/bool in beliebiger Auflösung (Seitenverhältnis wie das Bild),
    f, w, h: Brennweite (Vorgabe) und Bildgröße in Originalpixeln. Rückgabe: Liste (IoU, Kamera), beste zuerst."""
    t0 = time.perf_counter()
    azimute = np.arange(0, 360, 10.0) if azimute is None else azimute
    hoehen = np.arange(-10, 81, 10.0) if hoehen is None else hoehen
    V = netz.ecken(theta, winkel)
    zr = zeichner or fuer_netz(netz)
    zr.setze(V)
    lo, hi = V.min(0), V.max(0)
    mitte, radius = (lo + hi) / 2, float(np.linalg.norm(hi - lo) / 2)
    s_klein = breite_klein / w
    hk = round(h * s_klein)
    mk = cv2.resize(maske.astype(np.float32), (breite_klein, hk), interpolation=cv2.INTER_AREA)
    if paare is not None:                      # (Höhe, Roll)-Paare, z. B. aufrecht von oben und kopfüber von unten
        kand = [(a, e, r) for e, r in paare for a in azimute]
    else:
        kand = _kandidaten(azimute, hoehen, rolls)
    drehungen = [blick(a, e, r) for a, e, r in kand]
    kams = setze_kameras(zr, drehungen, mk, s_klein, f, w, h, mitte, radius)
    gueltig = [i for i, k in enumerate(kams) if k is not None]
    kach = zr.atlas([kams[i] for i in gueltig], s_klein, (breite_klein, hk))
    iou = _iou(kach, mk)
    ordnung = np.argsort(-iou)
    gewaehlt = []
    for j in ordnung:
        i = gueltig[j]
        if all(winkel_zwischen(drehungen[i], drehungen[g]) > 20 for g, _ in gewaehlt):
            gewaehlt.append((i, float(iou[j])))
        if len(gewaehlt) >= beste:
            break
    ergebnis = [(sc, kams[i], kand[i]) for i, sc in gewaehlt]
    if fein:
        verfeinert = []
        for sc, kam, (a, e, r) in ergebnis:
            schritte = [-6.0, -3.0, 0.0, 3.0, 6.0]
            dreh = []
            for da in schritte:
                for de in schritte:
                    for dr in (-6.0, 0.0, 6.0):
                        dreh.append(blick(a + da, e + de, r + dr))
            kk = setze_kameras(zr, dreh, mk, s_klein, f, w, h, mitte, radius)
            ok = [k for k in kk if k is not None]
            kach = zr.atlas(ok, s_klein, (breite_klein, hk))
            io = _iou(kach, mk)
            j = int(np.argmax(io))
            verfeinert.append((float(io[j]), ok[j], (a, e, r)))
        ergebnis = sorted(verfeinert, key=lambda t: -t[0])
    if protokoll:
        protokoll(f"Grobsuche: {len(kand)} Kandidaten, beste IoU {ergebnis[0][0]:.3f}, {time.perf_counter() - t0:.2f} s")
    return [(sc, k) for sc, k, _ in ergebnis]
