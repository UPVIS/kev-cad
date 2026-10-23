"""Silhouetten aus freigestellten Studiofotos (Produkt vor reinem Weiß) und Vergleich mit gerenderten Masken.

Die Kante liegt bei Schwelle 245 im dunkelsten Farbkanal; ein Versuch mit Halbwertskante (Deckung aus dem Kontrast
zur Umgebung) war schlechter, weil Edelstahl fast so hell ist wie der Grund (Outdoor-Küche, Oktober 2026).
Löcher werden in Foto und Modell gleich geschlossen (alles, was vom Bildrand aus nicht erreichbar ist).
"""
import os
from pathlib import Path

import cv2
import numpy as np


def fuelle(m):
    """Löcher schließen: alles, was nicht vom Rand her als Hintergrund erreichbar ist, gehört zum Körper."""
    hh, ww = m.shape
    flut = np.pad((m > 0).astype(np.uint8), 1)
    maske = np.zeros((hh + 4, ww + 4), np.uint8)
    cv2.floodFill(flut, maske, (0, 0), 2)
    return (flut[1:-1, 1:-1] != 2).astype(np.uint8)


def foto_silhouette(bild, schwelle=245, weich=0.7):
    """Gefüllte Silhouette als float 0..1 (leicht geglättet für die Suche, weich=0 für die Bewertung)."""
    m = (bild.min(axis=2) < schwelle).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    m = fuelle(m).astype(np.float32)
    return cv2.GaussianBlur(m, (0, 0), weich) if weich else m


def foto_maske(pfad, breite, cache=None, schwelle=245):
    """Silhouette eines Fotos in der Arbeitsbreite, zwischengespeichert (atomar, für parallele Prozesse)."""
    pfad = Path(pfad)
    if cache:
        cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
        ziel = cache / f"maske_{pfad.stem}_{breite}.npz"
        if ziel.exists():
            z = np.load(ziel)
            return z["m"], int(z["w"]), int(z["h"])
    im = cv2.imread(str(pfad))
    h, w = im.shape[:2]
    klein = cv2.resize(im, (breite, round(h * breite / w)), interpolation=cv2.INTER_AREA)
    m = foto_silhouette(klein, schwelle)
    if cache:
        tmp = ziel.with_name(ziel.stem + f".{os.getpid()}.tmp.npz")
        np.savez_compressed(tmp, m=m, w=w, h=h)
        tmp.replace(ziel)
    return m, w, h


def iou_weich(f, m, gueltig):
    inter = (f * m)[gueltig].sum()
    return float(inter / max((f + m - f * m)[gueltig].sum(), 1.0))


def iou_binaer(bild, modell_deckung, gueltig, schwelle=245):
    """Bewertung wie in den Vergleichsbildern: Schwelle im Foto, Deckung > 0,5 im Modell, Löcher gefüllt."""
    f = fuelle(cv2.morphologyEx((bild.min(axis=2) < schwelle).astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))) > 0
    m = fuelle(cv2.morphologyEx((modell_deckung > 0.5).astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))) > 0
    return float((f & m & gueltig).sum() / max((f | m)[gueltig].sum(), 1)), f, m
