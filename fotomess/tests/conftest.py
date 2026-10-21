import cv2
import numpy as np
import pytest

from fotomess.bild import Bild
from fotomess.gl import Zeichner
from fotomess.kamera import Kamera, blick
from fotomess.synth import tisch

WAHR = dict(L=610.0, B=410.0, H=160.0, d=35.0, b=45.0)


def probebild(netz, kam, rauschen=3.0, seed=0):
    """Graues Probefoto (flach schattiert, heller Grund) und Maske aus dem Netz."""
    zr = Zeichner(netz.V0, netz.tris)
    img = zr.schattiert(kam, 1.0)
    grau = np.clip(img * 255 * 0.8 + 30, 0, 255)
    grau = np.where(img > 0, grau, 235)
    grau = np.clip(grau + np.random.default_rng(seed).normal(0, rauschen, grau.shape), 0, 255).astype(np.uint8)
    return cv2.cvtColor(grau, cv2.COLOR_GRAY2BGR), img > 0


@pytest.fixture(scope="session")
def tisch_szene():
    netz_w, _ = tisch(WAHR)
    kams, bilder = [], []
    for az, el in [(30, 35), (120, 25), (250, 50)]:
        R = blick(az, el, 3.0)
        C = np.array([0, 0, 80.0]) - 1500 * R[2]
        k = Kamera(R=R, t=-R @ C, f=1600.0, w=1920, h=1080)
        farbe, maske = probebild(netz_w, k, seed=az)
        bilder.append(Bild(farbe, f"b{az}", maske=maske))
        kams.append(k)
    return netz_w, kams, bilder
