"""Strang „Feinschliff 2“, Punkt 5: Wandschleifen um Löcher und Bohrungen im Bahnmodell der Schätzung. Gezählt werden
die Umrisse je Höhenband (Außenkontur und jedes Loch); jede weitere Schleife kostet je Schicht ``s_loch``."""

import dataclasses

import numpy as np
import pytest
from build123d import Align, Box, Cylinder, Pos, Rot

from kevcad_kernel.druck import schaetzung as sz
from kevcad_kernel.druck.vorschau_geo import schleifen_je_hoehe

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)


def netz(teil):
    verts, tris = teil.tessellate(0.01, 0.2)
    return np.array([[v.X, v.Y, v.Z] for v in verts], dtype=float), np.array(tris, dtype=np.int64)


def test_umrisse_je_hoehe():
    scheibe = Cylinder(25, 10, align=UNTEN)
    for i in range(12):
        scheibe -= Rot(0, 0, i * 30) * Pos(18, 0, 0) * Cylinder(2, 10, align=UNTEN)
    P, T = netz(scheibe)
    assert schleifen_je_hoehe(P, T, np.array([2.5, 7.5])) == [13, 13]
    # zwei Bohrungen von unten bis 15 mm, darüber voll
    halter = Box(60, 40, 20, align=UNTEN) - Pos(15, 0, 0) * Cylinder(5, 30) - Pos(-15, 0, 0) * Cylinder(5, 30)
    P, T = netz(halter)
    assert schleifen_je_hoehe(P, T, np.array([5.0, 17.5])) == [3, 1]
    # offener Kasten: Boden eine Kontur, darüber außen und innen
    kasten = Box(80, 60, 40, align=UNTEN) - Pos(0, 0, 2) * Box(76, 56, 40, align=UNTEN)
    P, T = netz(kasten)
    assert schleifen_je_hoehe(P, T, np.array([1.0, 20.0])) == [1, 2]
    assert schleifen_je_hoehe(P, T, np.array([50.0])) == [0]


def test_schaetzung_mit_schleifen():
    geo = {"volumen": 18000.0, "seite": 4100.0, "oben": 1800.0, "unten": 0.0, "auflage": 1800.0,
           "groesse": [50.0, 50.0, 10.0], "umriss_umfang": 157.0, "seite_baender": [205.0] * 20,
           "waag_baender": [90.0] * 20}
    e = {"schicht_mm": 0.2, "waende": 2, "decken": 5, "boeden": 3, "fuellung": 0.15, "muster": "grid"}
    ohne = sz.schaetze(geo, e, "petg")
    eins = sz.schaetze({**geo, "schleifen_baender": [1] * 20}, e, "petg")
    mit = sz.schaetze({**geo, "schleifen_baender": [13] * 20}, e, "petg")
    assert eins["roh"]["zeit_s"] == ohne["roh"]["zeit_s"], "eine Schleife je Schicht: wie bisher"
    schichten = mit["schichten"]
    assert mit["roh"]["zeit_s"] - ohne["roh"]["zeit_s"] == pytest.approx(12 * sz.MODELL.s_loch * schichten, rel=0.02)
    assert mit["roh"]["volumen_cm3"] == ohne["roh"]["volumen_cm3"], "Material hängt an der Wandfläche, nicht an Schleifen"
    null = sz.schaetze({**geo, "schleifen_baender": [13] * 20}, e, "petg", m=dataclasses.replace(sz.MODELL, s_loch=0.0))
    assert null["roh"]["zeit_s"] == pytest.approx(ohne["roh"]["zeit_s"])
