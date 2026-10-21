import numpy as np

from fotomess.kamera import Kamera, blick
from fotomess.modell import Gelenk, ParamNetz
from fotomess.synth import quader_netz, tisch


def test_tisch_linear():
    netz, p = tisch()
    th = netz.theta0.copy()
    V0 = netz.ecken(th)
    th2 = th.copy()
    th2[netz.parameter.index("H")] += 10
    V1 = netz.ecken(th2)
    # Platte oben und Beine oben wandern um 10 mm, Fußpunkte bleiben
    dz = V1[:, 2] - V0[:, 2]
    assert np.isclose(dz.max(), 10.0) and np.isclose(dz.min(), 0.0)
    ids = np.arange(0, len(V0), 3)
    assert np.allclose(netz.ecken_teil(ids, th2), V1[ids])


def test_kanten_und_proben():
    netz, _ = tisch()
    # 5 Quader, je 12 Kanten mit 90 Grad Knick
    assert netz.kante_merkmal.sum() == 5 * 12
    R = blick(30, 30)
    C = -1500 * R[2]
    k = Kamera(R=R, t=-R @ C, f=1500, w=1000, h=800)
    P = netz.kanten_proben(netz.V0, k, 1.0, abstand=3.0)
    assert P is not None and len(P["u"]) > 100
    assert P["umriss"].any() and (~P["umriss"]).any()


def test_gelenk_ableitung():
    q = {"Fest": ({"": -100}, {"": 100}, {"": -50}, {"": 50}, {"": 0}, {"": 20}),
         "Klappe": ({"": -100}, {"": 100}, {"": -50}, {"a": 1.0}, {"": 20}, {"": 30})}
    p = dict(a=60.0)
    basis, abl = quader_netz(q, p, ["a"])
    g = Gelenk("Klappe", ("klappe",), (0.0, -50.0, 20.0), (1.0, 0.0, 0.0))
    netz = ParamNetz(basis, abl, ["a"], p, gelenke=[g])
    th = np.array([60.0])
    w = np.array([30.0])
    V = netz.ecken(th, w)
    m = netz.punkt_gelenk >= 0
    assert m.any() and not np.allclose(V[m], netz.V0[m])
    ids = np.flatnonzero(m)[:4]
    X, dX, dW = netz.ableitung_punkte(ids, ids, np.zeros(len(ids)), th, w, V)
    h = 1e-3
    Vp = netz.ecken(th, w + h)
    Vm = netz.ecken(th, w - h)
    num = (Vp[ids] - Vm[ids]) / (2 * h) / (np.pi / 180)
    assert np.allclose(num, dW[:, :, 0], atol=1e-4)
    Vp = netz.ecken(th + h, w)
    Vm = netz.ecken(th - h, w)
    assert np.allclose((Vp[ids] - Vm[ids]) / (2 * h), dX[:, :, 0], atol=1e-4)
