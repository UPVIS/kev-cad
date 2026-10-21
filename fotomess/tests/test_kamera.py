import math

import numpy as np

from fotomess.kamera import (Kamera, blick, brennweite_aus_35mm, exp_so3, log_so3, projektion_ableitung, rollwinkel,
                             winkel_zwischen)


def test_exp_log():
    rng = np.random.default_rng(0)
    for _ in range(20):
        w = rng.normal(0, 1.0, 3)
        w *= min(1.0, 3.0 / np.linalg.norm(w))
        R = exp_so3(w)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-10)
        assert np.allclose(exp_so3(log_so3(R)), R, atol=1e-8)


def test_blick_auf_ursprung():
    for az, el in [(0, 0), (45, 30), (200, -40)]:
        R = blick(az, el)
        C = -1000 * R[2]
        k = Kamera(R=R, t=-R @ C, f=1000, w=800, h=600)
        u, z = k.projiziere(np.zeros((1, 3)))
        assert np.allclose(u[0], [400, 300])
        assert abs(rollwinkel(R)) < 1e-6


def test_projektion_ableitung():
    rng = np.random.default_rng(1)
    Xk = rng.normal(0, 200, (10, 3)) + [0, 0, 1500]
    f = 1234.0
    J, Jf = projektion_ableitung(Xk, f)
    def proj(X, f):
        return np.stack([f * X[:, 0] / X[:, 2], f * X[:, 1] / X[:, 2]], 1)
    for j in range(3):
        d = np.zeros(3)
        d[j] = 1e-4
        num = (proj(Xk + d, f) - proj(Xk - d, f)) / 2e-4
        assert np.allclose(num, J[:, :, j], rtol=1e-5, atol=1e-6)
    num_f = (proj(Xk, f * math.exp(1e-6)) - proj(Xk, f * math.exp(-1e-6))) / 2e-6
    assert np.allclose(num_f, Jf, rtol=1e-5)


def test_fotocad_hin_und_zurueck():
    R = blick(130, 20, 2.0)
    C = np.array([100.0, -50, 300]) - 4000 * R[2]
    k = Kamera(R=R, t=-R @ C, f=8000, w=5906, h=3937, cx=2960, cy=1960)
    k2 = Kamera.aus_fotocad(k.als_fotocad())
    assert winkel_zwischen(k.R, k2.R) < 1e-6
    assert np.allclose(k.zentrum, k2.zentrum)
    assert abs(k2.cx - k.cx) < 1e-9 and abs(k2.cy - k.cy) < 1e-9


def test_brennweite_iphone():
    # 24 mm KB-Äquivalent, lange Kante 3840 -> etwa 2660 px (Hauptkamera ohne Beschnitt)
    assert 2600 < brennweite_aus_35mm(24, 2160, 3840) < 2720
