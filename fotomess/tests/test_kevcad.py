"""Einstieg für Kev CAD: Netz mit Ableitungen aus den Varianten des Kernels, Farbteile je Dreieck, Richtungstexte."""
import numpy as np
import pytest

from fotomess.kevcad import _richtung_text, netz_aus_varianten


def kasten_flaechen(b, t, h, x0=0.0):
    """Quader b x t x h (Mitte x0, 0, Boden z = 0) als sechs Flächen mit je zwei Dreiecken (n, 3, 3)."""
    xs, ys, zs = (x0 - b / 2, x0 + b / 2), (-t / 2, t / 2), (0.0, h)
    P = lambda i, j, k: np.array([xs[i], ys[j], zs[k]])  # noqa: E731
    quads = [((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), ((0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)),
             ((0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)), ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)),
             ((0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)), ((1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0))]
    out = []
    for q in quads:
        a, b_, c, d = (P(*v) for v in q)
        out.append(np.stack([np.stack([a, b_, c]), np.stack([a, c, d])]))
    return out


def daten(p, schritt=0.5):
    def bau(pp):
        return {"Korpus": kasten_flaechen(pp["b"], pp["t"], pp["h"]),
                "Griff": kasten_flaechen(10, 10, 10, x0=pp["b"] / 2 + 5)}
    var = []
    for k in ("b", "h"):
        q = dict(p)
        q[k] += schritt
        var.append(bau(q))
    return {"p": dict(p), "parameter": ["b", "h"], "schritt": schritt, "basis": bau(p), "varianten": var,
            "farbflaechen": {"Korpus": [True, True, True, True, False, False], "Griff": [False] * 6},
            "zwillinge": [], "messmodell": {}, "warnungen": []}


def test_netz_aus_varianten_ableitung_und_farbteile(tmp_path):
    d = daten({"b": 100.0, "t": 60.0, "h": 40.0})
    netz, unstetig = netz_aus_varianten(d, tmp_path)
    assert unstetig == [] and netz.parameter == ["b", "h"] and netz.teile == ["Griff", "Korpus"]
    V = netz.ecken(np.array([110.0, 45.0]))
    korpus = V[netz.punkt_teil == netz.teile.index("Korpus")]
    assert korpus[:, 0].max() == pytest.approx(55.0) and korpus[:, 2].max() == pytest.approx(45.0)
    griff = V[netz.punkt_teil == netz.teile.index("Griff")]
    assert griff[:, 0].min() == pytest.approx(55.0)  # der Griff wandert mit der Breite
    # Farbteile: Korpus ohne die Stirnflächen (x = ±b/2), Griff nie
    ti = netz.tri_teil == netz.teile.index("Korpus")
    assert netz.farb_tris[~ti].sum() == 0 and netz.farb_tris[ti].sum() == 8
    # zweiter Aufruf aus dem Zwischenspeicher
    netz2, _ = netz_aus_varianten(d, tmp_path)
    assert np.allclose(netz2.V0, netz.V0) and (netz2.farb_tris == netz.farb_tris).all()
    assert len(list(tmp_path.glob("netz-*.pkl"))) == 1


def test_richtung_text():
    assert _richtung_text(270, 5) == "von vorne (−Y), flach"
    assert _richtung_text(315, 30) == "schräg von vorne rechts, 30° hoch"
    assert _richtung_text(90, 85) == "von hinten (+Y), steil von oben"
