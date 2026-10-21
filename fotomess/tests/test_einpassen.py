import time

import numpy as np

from fotomess import unsicherheit as U
from fotomess.ablauf import Eingabe, Plaene, vermessen
from fotomess.bild import NaechsteKante
from fotomess.einpassen import Ansicht, Ausgleich, Einstellungen, Stufenplan
from fotomess.kamera import winkel_zwischen
from fotomess.start import grobsuche
from fotomess.synth import tisch

from conftest import WAHR

START = dict(L=610.0, B=410.0, H=140.0, d=30.0, b=55.0)
PLAENE = [Stufenplan(480, sigma=2.0, tor=25, abstand=3), Stufenplan(960, sigma=1.0, tor=8, abstand=3)]


def test_naechste_kante():
    m = np.zeros((50, 60), bool)
    m[20, 10:50] = True
    nk = NaechsteKante.aus(m)
    q, d = nk.suche(np.array([[30.5, 25.5], [5.2, 20.5]]))
    assert np.allclose(q[0], [30.5, 20.5]) and np.isclose(d[0], 5.0)
    assert np.allclose(q[1], [10.5, 20.5])


def test_kameras_und_masse(tisch_szene):
    netz_w, kams, bilder = tisch_szene
    netz, _ = tisch(START)
    rng = np.random.default_rng(1)
    ans = []
    for b, k in zip(bilder, kams):
        k0 = k.schritt(rng.normal(0, 0.03, 3), rng.normal(0, 30, 3))
        k0.f = 1600.0 * 1.08
        ans.append(Ansicht(bild=b, netz="t", kamera=k0))
    A = Ausgleich({"t": netz}, ans, START, frei=["H", "d", "b"], einstellungen=Einstellungen(f_sigma_log=None))
    t = time.perf_counter()
    A.loese(PLAENE[:1], nur_kameras=True)
    A.loese(PLAENE)
    dauer = time.perf_counter() - t
    th = A.theta_dict()
    for k in ("H", "d", "b"):
        assert abs(th[k] - WAHR[k]) < 1.0, (k, th[k])
    for kk, k in zip(A.z.kameras, kams):
        assert winkel_zwischen(kk.R, k.R) < 0.2
    assert dauer < 5.0
    kov = U.kovarianz(A, PLAENE[-1])
    assert all(np.isfinite(v) and v < 2.0 for v in kov["sigma"].values())
    nm = U.nachmessen(kov, A.frei)
    assert nm[0][2] < nm[0][1]


def test_grobsuche(tisch_szene):
    netz_w, kams, bilder = tisch_szene
    k = kams[0]
    erg = grobsuche(netz_w, netz_w.theta0, bilder[0].maske, k.f * 1.05, k.w, k.h, hoehen=np.arange(0, 81, 10.0))
    sc, kam = erg[0]
    assert sc > 0.8
    # Tisch ist um 180 Grad symmetrisch: eine der beiden Lagen muss passen
    dreh = min(winkel_zwischen(kam.R, k.R), winkel_zwischen(kam.R, k.R @ np.diag([-1, -1, 1.0])))
    assert dreh < 12


def test_ablauf_ohne_vorwissen(tisch_szene):
    netz_w, kams, bilder = tisch_szene
    netz, _ = tisch(START)
    E = [Eingabe(bild=b, netz="t", f=1700.0, hoehen=tuple(range(0, 81, 10))) for b in bilder]
    pl = Plaene(kandidaten=[Stufenplan(240, sigma=3.0, tor=25, abstand=2.0, aussen=2, innen=3, hoechstens=1200)],
                kameras=[Stufenplan(480, sigma=2.0, tor=20, abstand=2.5, aussen=3, innen=4)],
                buendel=[Stufenplan(480, sigma=2.0, tor=15, abstand=2.5, aussen=3, innen=4),
                         Stufenplan(960, sigma=1.0, tor=6, abstand=3.0, aussen=3, innen=4)])
    erg = vermessen({"t": netz}, E, START, ["H", "d", "b"], einst=Einstellungen(f_sigma_log=0.2), plaene=pl,
                    protokoll=None)
    for k in ("H", "d", "b"):
        assert abs(erg.theta[k] - WAHR[k]) < 1.5, (k, erg.theta[k])
    assert erg.zeiten["gesamt"] < 10


def test_einrasten():
    assert U.einrasten(57.6, 1.0, raster=5) is None
    assert U.einrasten(58.2, 2.0, raster=5) == 60
    assert U.einrasten(99.4, 1.0, werte=[100, 125]) == 100
