"""Kontrollbilder: Modellkanten über dem Foto.

Farben: Umriss gegen die Maske grün, innere Kanten gegen Bildkanten gelb, nicht zugeordnete Punkte rot; die Kante
der Bildmaske dünn blau. Darunter das Foto, leicht abgedunkelt.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def kontrollbild(ausgleich, i, plan, datei=None, titel=None, linien=True):
    A = ausgleich
    A.sichtbarkeit(plan)
    a = A.ansichten[i]
    st = a.bild.stufe(plan.breite)
    farbe = cv2.resize(a.bild.farbe, (st.breite, st.hoehe), interpolation=cv2.INTER_AREA)
    bild = (farbe.astype(np.float32) * 0.6).astype(np.uint8)
    if st.weich is not None:
        rand = (st.weich >= 0.5).astype(np.uint8)
        rand = rand - cv2.erode(rand, np.ones((3, 3), np.uint8))
        bild[rand > 0] = (255, 140, 40)
    o = A._ansicht(i, A.z, plan, False)
    P = A.proben[i]
    if o is not None:
        u = o["u"]
        for j in range(len(u)):
            if not o["innen"][j]:
                c = (60, 60, 255)
            elif P["typ"][j] == 0:
                c = (80, 255, 80)
            else:
                c = (40, 230, 255)
            cv2.circle(bild, (int(u[j, 0]), int(u[j, 1])), 1, c, -1, lineType=cv2.LINE_AA)
    if titel:
        cv2.putText(bild, titel, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    if datei:
        Path(datei).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(datei), bild, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return bild


def kanten_ueber_foto(netz, kamera, theta, winkel, farbe_bild, s, datei=None, farbe=(40, 230, 255), titel=None):
    """Alle sichtbaren Modellkanten (Merkmals- und Umrisskanten) als Linien über dem Foto, ohne Einpass-Zustand."""
    from .gl import Zeichner
    V = netz.ecken(theta, winkel)
    zr = Zeichner(V, netz.tris)
    h, w = farbe_bild.shape[:2]
    tiefe = zr.tiefe(kamera, s, (w, h))
    P = netz.kanten_proben(V, kamera, s, abstand=1.0, hoechstens=200000)
    bild = (farbe_bild.astype(np.float32) * 0.6).astype(np.uint8)
    if P is not None:
        u, z = P["u"], P["z"]
        ix = np.clip(u[:, 0].astype(int), 0, w - 1)
        iy = np.clip(u[:, 1].astype(int), 0, h - 1)
        t = cv2.dilate(np.where(tiefe > 0, tiefe, 1e9).astype(np.float32), np.ones((3, 3), np.uint8))
        sicht = t[iy, ix] >= z * 0.996 - 1
        for (x, y) in u[sicht]:
            bild[int(y), int(x)] = farbe
    if titel:
        cv2.putText(bild, titel, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    if datei:
        Path(datei).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(datei), bild, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return bild
