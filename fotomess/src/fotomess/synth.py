"""Künstliche Prüfmodelle ohne build123d: Quader, deren Grenzen linear von Maßen abhängen (für Tests und Probebilder).

Ein Quader ist (x0, x1, y0, y1, z0, z1), jede Grenze ein dict {Maß: Faktor, "": Konstante}. Das Netz hat je Seite
eine eigene Fläche (wie ein B-Rep-Export), die Ableitungen sind exakt.
"""
from __future__ import annotations

import numpy as np

from .modell import ParamNetz

_SEITEN = [  # Ecken-Indizes (x, y, z) je Seite, gegen den Uhrzeigersinn von außen
    [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)],   # unten
    [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],   # oben
    [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)],   # y0
    [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)],   # y1
    [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)],   # x0
    [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],   # x1
]


def _lin(g, p):
    return g.get("", 0.0) + sum(v * p[k] for k, v in g.items() if k)


def quader_netz(quader, p, parameter):
    """quader: {Teil: (x0, x1, y0, y1, z0, z1)} mit linearen Grenzen; liefert basis und ableitung wie
    fotocad.cad_netz.Jacobi."""
    basis, ableitung = {}, {}
    for name, grenzen in quader.items():
        werte = [_lin(g, p) for g in grenzen]
        flaechen, abl = [], {k: [] for k in parameter}
        for seite in _SEITEN:
            ecken = np.array([[werte[0 + i], werte[2 + j], werte[4 + k]] for i, j, k in seite])
            d = {k: np.array([[grenzen[0 + i].get(k, 0.0), grenzen[2 + j].get(k, 0.0), grenzen[4 + kk].get(k, 0.0)]
                              for i, j, kk in seite]) for k in parameter}
            tri = [[0, 1, 2], [0, 2, 3]]
            flaechen.append(ecken[tri])
            for k in parameter:
                abl[k].append(d[k][tri])
        basis[name] = flaechen
        for k in parameter:
            ableitung[(k, name)] = np.concatenate(abl[k])
    return basis, ableitung


def tisch(p=None):
    """Tisch: Platte L x B x d auf vier Beinen b x b, Gesamthöhe H. Maße: L, B, H, d, b."""
    p = dict(L=600.0, B=400.0, H=300.0, d=30.0, b=40.0) if p is None else dict(p)
    parameter = ["L", "B", "H", "d", "b"]
    q = {"Platte": ({"L": -0.5}, {"L": 0.5}, {"B": -0.5}, {"B": 0.5}, {"H": 1.0, "d": -1.0}, {"H": 1.0})}
    for i, (sx, sy) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        xa = {"L": 0.5 * sx}
        xb = {"L": 0.5 * sx, "b": -1.0 * sx}
        ya = {"B": 0.5 * sy}
        yb = {"B": 0.5 * sy, "b": -1.0 * sy}
        x0, x1 = (xb, xa) if sx > 0 else (xa, xb)
        y0, y1 = (yb, ya) if sy > 0 else (ya, yb)
        q[f"Bein {i + 1}"] = (x0, x1, y0, y1, {"": 0.0}, {"H": 1.0, "d": -1.0})
    basis, abl = quader_netz(q, p, parameter)
    return ParamNetz(basis, abl, parameter, p), p
