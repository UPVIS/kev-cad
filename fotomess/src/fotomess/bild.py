"""Bildseite: Pyramide, Kanten nach Richtung getrennt, Maskenrand, je Kanal die nächste Kante zu jedem Pixel.

Statt das Modell bei jeder Auswertung neu zu zeichnen und Flächen zu vergleichen (fotocad: Powell auf der
Überdeckung), wird je Bild und Stufe einmal vorberechnet, wo die nächste Bildkante liegt (Distanztransformation mit
Marken, OpenCV). Ein projizierter Modellkantenpunkt findet dann in O(1) seinen Partner; der Rest ist ein glattes
Ausgleichsproblem (Punkt-zu-Linie-Abstand entlang der Modellnormale).

Kanäle: 0 = Maskenrand (Silhouette), 1..NB = Bildkanten (Canny) nach Gradientenrichtung, jeder Kanal nimmt
Kanten bis zu einer Fächerbreite Abweichung auf (überlappend), damit ein Modellpunkt nur gleich gerichtete Kanten
findet. Das unterdrückt Fehlzuordnungen an Fliesenfugen, Spiegelungen und Hintergrund.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np

NB = 6                         # Richtungsfächer über 180 Grad
FAECHER = math.pi / NB         # halbe Überlappung: jeder Kanal nimmt +-FAECHER um seine Mitte


@dataclass
class NaechsteKante:
    """Nächstgelegenes Merkmalspixel je Pixel (Mittelpunkte in stetigen Koordinaten)."""
    labels: np.ndarray        # int32 (h, w)
    tabelle: np.ndarray       # (n + 1, 2) float32: Marke -> (x, y) + 0.5
    abstand: np.ndarray       # float32 (h, w)
    leer: bool = False

    @classmethod
    def aus(cls, merkmal):
        if not merkmal.any():
            h, w = merkmal.shape
            return cls(np.zeros((h, w), np.int32), np.zeros((1, 2), np.float32), np.full((h, w), 1e6, np.float32), True)
        src = np.where(merkmal, 0, 255).astype(np.uint8)
        dist, lab = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(merkmal)
        tab = np.zeros((int(lab.max()) + 1, 2), np.float32)
        tab[lab[ys, xs]] = np.stack([xs, ys], 1).astype(np.float32) + 0.5
        return cls(lab, tab, dist)

    def suche(self, u):
        """u (n, 2) stetige Pixel -> nächster Merkmalspunkt (n, 2) und Abstand (n,)."""
        h, w = self.labels.shape
        ix = np.clip(u[:, 0].astype(np.int32), 0, w - 1)
        iy = np.clip(u[:, 1].astype(np.int32), 0, h - 1)
        q = self.tabelle[self.labels[iy, ix]]
        return q, np.linalg.norm(u - q, axis=1) if not self.leer else np.full(len(u), 1e6)


class Stufe:
    """Ein Bild in einer Pyramidenstufe: Skala s gegenüber dem Original, Kanäle mit nächster Kante."""

    def __init__(self, grau, s, maske=None, ignorieren=None, canny=(40, 100), mit_kanten=True, rand_px=2):
        self.s = s
        self.hoehe, self.breite = grau.shape
        self.grau = grau
        self.maske = maske
        self.ignorieren = ignorieren
        self.kanaele = [None] * (NB + 1)
        auftraege = []
        self.weich = None
        if maske is not None:
            # weiche Maske (Deckung je Pixel): daraus die Lage der Kante innerhalb des Randpixels
            self.weich = maske.astype(np.float32) if maske.dtype != bool else maske.astype(np.float32)
            m = self.weich >= 0.5
            kreuz = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], np.uint8)
            rand = m & ~cv2.erode(m.astype(np.uint8), kreuz).astype(bool)
            rand = _ohne_bildrand(rand, rand_px)
            if ignorieren is not None:
                rand &= ~ignorieren
            auftraege.append((0, rand))
        if mit_kanten:
            g = cv2.GaussianBlur(grau, (0, 0), 1.0)
            kanten = cv2.Canny(g, canny[0], canny[1], L2gradient=True) > 0
            gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
            phi = np.mod(np.arctan2(gy, gx), math.pi)          # Gradientenrichtung = Kantennormale, mod 180
            kanten = _ohne_bildrand(kanten, rand_px)
            if ignorieren is not None:
                kanten &= ~ignorieren
            self.kanten = kanten
            for j in range(NB):
                mitte = j * math.pi / NB
                d = np.abs(np.mod(phi - mitte + math.pi / 2, math.pi) - math.pi / 2)
                auftraege.append((1 + j, kanten & (d <= FAECHER)))
        else:
            self.kanten = None
        with ThreadPoolExecutor(max_workers=min(8, len(auftraege) or 1)) as ex:
            for j, nk in zip([a[0] for a in auftraege], ex.map(lambda a: NaechsteKante.aus(a[1]), auftraege)):
                self.kanaele[j] = nk

    def kanal_fuer(self, normale):
        """Kanalnummer 1..NB je Modellnormale (n, 2)."""
        phi = np.mod(np.arctan2(normale[:, 1], normale[:, 0]), math.pi)
        return 1 + (np.rint(phi / (math.pi / NB)).astype(int) % NB)

    def kantenversatz(self, q, n):
        """Lage der Maskenkante gegenüber dem Mittelpunkt des inneren Randpixels q entlang der Außennormale n:
        Deckung des Randpixels - 0,5 + Deckung des nächsten Pixels nach außen (0,5 bei harter Maske)."""
        if self.weich is None:
            return np.full(len(q), 0.5)
        h, w = self.weich.shape
        ix = np.clip(q[:, 0].astype(np.int32), 0, w - 1)
        iy = np.clip(q[:, 1].astype(np.int32), 0, h - 1)
        jx = np.clip((q[:, 0] + n[:, 0]).astype(np.int32), 0, w - 1)
        jy = np.clip((q[:, 1] + n[:, 1]).astype(np.int32), 0, h - 1)
        return self.weich[iy, ix] - 0.5 + self.weich[jy, jx]

    def ignoriert(self, u):
        if self.ignorieren is None:
            return np.zeros(len(u), bool)
        ix = np.clip(u[:, 0].astype(np.int32), 0, self.breite - 1)
        iy = np.clip(u[:, 1].astype(np.int32), 0, self.hoehe - 1)
        return self.ignorieren[iy, ix]


def _ohne_bildrand(m, r):
    if r <= 0:
        return m
    m = m.copy()
    m[:r] = False
    m[-r:] = False
    m[:, :r] = False
    m[:, -r:] = False
    return m


class Bild:
    """Ein Foto mit Maske (optional) und Pyramide; Stufen werden bei Bedarf gebaut und gemerkt.

    farbe darf verkleinert sein (Arbeitskopie); ursprung = (Breite, Höhe) des Originals, auf das sich Kamera und
    Brennweite beziehen. maske und ignorieren: bool in der Größe von farbe."""

    def __init__(self, farbe, name="", maske=None, ignorieren=None, ursprung=None, canny=(40, 100), mit_kanten=True):
        self.name = name
        self.farbe = farbe
        self.hoehe_arbeit, self.breite_arbeit = farbe.shape[:2]
        self.breite, self.hoehe = ursprung or (self.breite_arbeit, self.hoehe_arbeit)
        self.maske = maske
        self.ignorieren = ignorieren
        self.canny = canny
        self.mit_kanten = mit_kanten
        self.stufen = {}

    def stufe(self, breite):
        """Stufe mit gegebener Breite in Pixeln; s = breite / Originalbreite."""
        breite = min(int(breite), self.breite_arbeit)
        if breite not in self.stufen:
            s = breite / self.breite
            hoehe = round(self.hoehe * s)
            klein = cv2.resize(self.farbe, (breite, hoehe), interpolation=cv2.INTER_AREA)
            grau = cv2.cvtColor(klein, cv2.COLOR_BGR2GRAY) if klein.ndim == 3 else klein
            m = None if self.maske is None else cv2.resize(self.maske.astype(np.float32), (breite, hoehe),
                                                           interpolation=cv2.INTER_AREA)
            ig = None if self.ignorieren is None else cv2.resize(self.ignorieren.astype(np.uint8) * 255, (breite, hoehe),
                                                                 interpolation=cv2.INTER_AREA) > 0
            self.stufen[breite] = Stufe(grau, s, m, ig, self.canny, self.mit_kanten)
        return self.stufen[breite]

    def freigeben(self):
        self.stufen.clear()
