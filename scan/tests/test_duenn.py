"""Dünne Teile (Rollwagen-Scan, 23.10.2026): schwaches Freiräumen weit vor der Fläche in der TSDF."""

from __future__ import annotations

import numpy as np

from kevscan.tsdf import TSDF

K = np.array([[300.0, 0.0, 100.0], [0.0, 300.0, 100.0], [0.0, 0.0, 1.0]])
W = H = 200


def _kamera_von_oben(x0: float, y0: float, hoehe: float = 400.0) -> tuple[np.ndarray, np.ndarray]:
    """OpenCV-Kamera über dem Ursprung, Blick nach −z: x_c = x − x0, y_c = −(y − y0), z_c = hoehe − z."""
    R = np.diag([1.0, -1.0, -1.0])
    return R, -R @ np.array([x0, y0, hoehe])


def _tiefe_platte(R, t, platte: bool, boden_z: float = -500.0) -> np.ndarray:
    """Tiefe (mm) einer Platte 100 × 100 bei z = 0 über fernem Boden; platte=False: Strahlen gehen an ihr vorbei."""
    v, u = np.mgrid[0:H, 0:W].astype(float)
    C = -R.T @ t
    d = np.stack([(u + 0.5 - K[0, 2]) / K[0, 0], (v + 0.5 - K[1, 2]) / K[1, 1], np.ones_like(u)], -1) @ R  # Welt
    s_p = (0.0 - C[2]) / d[..., 2]
    X = C + s_p[..., None] * d
    auf = (np.abs(X[..., 0]) < 50) & (np.abs(X[..., 1]) < 50) & platte
    s_b = (boden_z - C[2]) / d[..., 2]
    s = np.where(auf, s_p, s_b)
    return (s * (d @ R.T)[..., 2]).astype(np.float32)   # z der Kamera = Tiefe


def _platte_im_netz(tsdf: TSDF) -> int:
    n = tsdf.netz()
    P = n["positions"]
    return int(((np.abs(P[:, 2]) < 6) & (np.abs(P[:, 0]) < 40) & (np.abs(P[:, 1]) < 40)).sum())


def test_duenne_platte_bleibt_mit_schwachem_freiraeumen():
    gut = [_kamera_von_oben(x, y) for x, y in ((0, 0), (40, 0), (-40, 20), (0, -40))]
    stoer = [_kamera_von_oben(x, y) for x, y in ((20, 20), (-20, -20), (30, -10), (-30, 10), (10, 30), (-10, -30))]
    ergebnis = {}
    for fg in (1.0, 0.1):
        ts = TSDF((-80, -80, -30), (80, 80, 30), 2.0, 8.0, farbe=False, geraet=None, frei_gewicht=fg)
        for R, t in gut:
            ts.integriere(_tiefe_platte(R, t, True), K, R, t)
        for R, t in stoer:   # Sichtstrahlen, die an der Platte vorbei den Boden treffen
            ts.integriere(_tiefe_platte(R, t, False), K, R, t)
        ergebnis[fg] = _platte_im_netz(ts)
    assert ergebnis[1.0] < 50, ergebnis          # voll gewichtet: die Platte ist weggeräumt
    assert ergebnis[0.1] > 500, ergebnis         # schwach gewichtet: sie bleibt stehen


def test_nah_vor_der_flaeche_wird_voll_geraeumt():
    """Freier Raum nah vor einer Fläche (bis 2 · trunc) zählt voll: Rauschen macht kompakte Teile nicht dicker."""
    ts = TSDF((-80, -80, -30), (80, 80, 30), 2.0, 8.0, farbe=False, geraet=None, frei_gewicht=0.1)
    assert ts.frei_ab == 16.0
