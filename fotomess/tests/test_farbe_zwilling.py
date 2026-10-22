"""Werkzeuge aus der Scarlett-Probe (22.10.2026): Rot über H = 0, Maske mit Innenbereich und Unterlage, Zwillingslagen
fast symmetrischer Gegenstände, Farbteil-Überdeckung."""
import cv2
import numpy as np

from fotomess import masken
from fotomess.ablauf import zwilling
from fotomess.bild import Bild
from fotomess.einpassen import Ansicht, Ausgleich
from fotomess.gl import Zeichner
from fotomess.kamera import Kamera, blick
from fotomess.synth import tisch

from conftest import WAHR


def _hsv_bild(werte):
    hsv = np.array([werte], np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_farbbereich_ueber_null():
    bild = _hsv_bild([(175, 220, 200), (2, 220, 200), (15, 220, 200), (175, 40, 200)])
    m = masken.farbbereich(bild, (168, 4), 70, 25)[0]
    assert m.tolist() == [True, True, False, False]       # Rot beidseits von 0, Holz nicht, blasses Rot nicht


def test_kombiniert_innen_und_unterlage():
    holz = (15, 150, 200)
    hsv = np.zeros((200, 300, 3), np.uint8)
    hsv[...] = (0, 0, 90)                                   # grauer Boden
    cv2.circle(hsv, (150, 110), 95, holz, -1)               # Holzscheibe
    hsv[60:140, 90:210] = (176, 230, 180)                   # rotes Gehäuse (Rahmen)
    hsv[70:130, 100:200] = (0, 0, 25)                       # schwarze Blende darin
    hsv[90:100, 120:160] = holz                             # Holz spiegelt sich in der Blende
    hsv[95:105, 210:222] = (0, 0, 30)                       # Knopf, steht rechts über
    hsv[170:180, 140:160] = (0, 0, 30)                      # dunkler Fleck auf der Scheibe, weit weg
    bild = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    vision = np.zeros((200, 300), np.float32)
    cv2.circle(vision, (150, 110), 95, 1.0, -1)             # Vision zählt die Scheibe mit
    fm = masken.farbe(bild, (168, 4), 70, 25)
    ys, xs = np.nonzero(fm)
    innen = np.zeros(fm.shape, np.uint8)
    cv2.fillConvexPoly(innen, cv2.convexHull(np.stack([xs, ys], 1).astype(np.int32)), 1)
    m = masken.kombiniert(bild, vision, fm, ausschluss=((6, 24), 50, 45), umkreis=20, innen=innen > 0,
                          aussen_oeffnen=2, schliessen=2, loch_anteil=0.05) >= 0.5
    assert m[100, 140] and m[75, 150]                       # Blende samt Spiegelung gehört dazu
    assert m[100, 215]                                      # Knopf am Gehäuse gehört dazu
    assert not m[175, 150] and not m[30, 150] and not m[110, 70]   # Fleck, Scheibe und Boden nicht


def test_zwilling_sieht_gedrehtes_modell():
    rng = np.random.default_rng(3)
    X = rng.uniform(-80, 80, (50, 3))
    R = blick(35, 25, 2.0)
    k = Kamera(R=R, t=-R @ (np.array([0, 0, 20.0]) - 900 * R[2]), f=1500.0, w=1920, h=1080)
    Q, c = np.diag([-1.0, -1.0, 1.0]), np.array([4.0, -6.0, 11.0])
    u_gedreht, _ = k.projiziere((X - c) @ Q.T + c)
    u_zwilling, _ = zwilling(k, Q, c).projiziere(X)
    assert np.allclose(u_gedreht, u_zwilling, atol=1e-6)


def test_iou_farbe_trennt_lagen():
    netz, _ = tisch(WAHR)
    platte = np.array([netz.teile[i] == "Platte" for i in netz.tri_teil])
    netz.farb_tris = platte
    R = blick(30, 35, 0.0)
    k = Kamera(R=R, t=-R @ (np.array([0, 0, 80.0]) - 1500 * R[2]), f=1600.0, w=960, h=540)
    voll = Zeichner(netz.V0, netz.tris).tiefe(k, 1.0)
    teil = Zeichner(netz.V0, netz.tris[platte]).tiefe(k, 1.0)
    farbmaske = ((teil > 0) & (np.abs(teil - voll) < 1.0)).astype(np.float32)
    b = Bild(np.zeros((540, 960, 3), np.uint8), "probe", maske=(voll > 0).astype(np.float32))
    b.farbmaske = farbmaske
    falsch = k.schritt(np.zeros(3), np.array([0.0, 60.0, 0.0]))     # 60 mm nach unten verschoben
    A = Ausgleich({"t": netz}, [Ansicht(bild=b, netz="t", kamera=k), Ansicht(bild=b, netz="t", kamera=falsch)],
                  dict(WAHR), frei=[], protokoll=None)
    from fotomess.einpassen import Stufenplan
    plan = Stufenplan(960)
    assert A.iou_farbe(0, plan) > 0.97
    assert A.iou_farbe(1, plan) < 0.85
    assert A.guete(0, plan) > A.guete(1, plan)
