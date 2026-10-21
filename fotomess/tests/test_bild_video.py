import numpy as np

from fotomess.bild import Stufe
from fotomess.masken import kleine_loecher_fuellen
from fotomess.video import auswaehlen


def test_kantenversatz_harte_maske():
    m = np.zeros((40, 40), np.float32)
    m[10:30, 10:30] = 1.0
    st = Stufe(np.full((40, 40), 128, np.uint8), 1.0, maske=m, mit_kanten=False)
    q, d = st.kanaele[0].suche(np.array([[35.0, 20.5]]))
    assert np.allclose(q[0], [29.5, 20.5])
    assert np.allclose(st.kantenversatz(q, np.array([[1.0, 0.0]])), 0.5)


def test_weiche_kante():
    m = np.zeros((40, 40), np.float32)
    m[10:30, 10:30] = 1.0
    m[10:30, 30] = 0.4                      # Kante liegt 0,4 Pixel im nächsten Pixel
    st = Stufe(np.full((40, 40), 128, np.uint8), 1.0, maske=m, mit_kanten=False)
    q, _ = st.kanaele[0].suche(np.array([[35.0, 20.5]]))
    assert np.isclose(st.kantenversatz(q, np.array([[1.0, 0.0]]))[0], 0.9)


def test_loecher():
    m = np.ones((100, 100), bool)
    m[10:12, 10:12] = False                  # kleines Loch: zu
    m[40:70, 40:70] = False                  # große Öffnung: bleibt
    out = kleine_loecher_fuellen(m, 0.002)
    assert out[10:12, 10:12].all() and not out[50, 50]


def test_auswahl_verteilt_und_scharf():
    k = []
    for i in range(120):
        k.append(dict(t=i / 6, schaerfe=100.0 + (50 if i % 10 == 3 else 0), bewegung=1.0, anteil=0.1,
                      rand=0.0 if i % 2 else 0.05))
    w = auswaehlen(k, 4)
    assert len(w) == 4
    assert all(k[i]["rand"] == 0.0 for i in w)
    t = [k[i]["t"] for i in w]
    assert min(np.diff(t)) > 3
