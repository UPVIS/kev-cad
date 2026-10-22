"""Geometrische Signatur der Druckteile (Strang „Feinschliff 2“, Punkt 3): gleiche Teile in anderer Lage sind gleich,
Spiegelbilder chiraler Teile gespiegelt, symmetrische Teile auch gespiegelt gleich, andere Formen verschieden. Dazu die
Gruppen der Druckvorschau aus Teilen, die einzeln in Weltlage gebaut sind."""

import numpy as np
import pytest
from build123d import Axis, Box, Cylinder, Plane, Pos, Rot, mirror

from kevcad_kernel.druck import signatur as sg


def netz(teil):
    verts, tris = teil.tessellate(0.01, 0.2)
    P = np.array([[v.X, v.Y, v.Z] for v in verts], dtype=float)
    T = np.array(tris, dtype=np.int64)
    P[:, 2] -= P[:, 2].min()  # Auflage z = 0 wie in Druckkoordinaten
    bb = teil.bounding_box().size
    return P, T, sorted([bb.X, bb.Y])[::-1] + [bb.Z]


def sig(teil):
    P, T, g = netz(teil)
    return sg.berechnen(P, T, g)


def winkel(loch_x=12.0):
    """Chiral: L-Winkel mit Loch außermittig und Fase nur an einer Seite."""
    t = Box(40, 10, 8) + Pos(-15, 12, 0) * Box(10, 16, 8) + Pos(15, -2, 6) * Box(6, 4, 4)
    return t - Pos(loch_x, 0, 0) * Cylinder(2.5, 20)


def test_gleich_in_anderer_lage():
    a = winkel()
    b = Pos(300, -120, 0) * Rot(0, 0, 90) * winkel()
    gleich, gespiegelt = sg.vergleich(sig(a), sig(b))
    assert gleich and not gespiegelt


def test_spiegelbild_eines_chiralen_teils():
    a = winkel()
    b = Pos(80, 0, 0) * mirror(winkel(), Plane.YZ)
    s_a, s_b = sig(a), sig(b)
    assert s_a["v"] == pytest.approx(s_b["v"], rel=1e-3) and s_a["m"] == pytest.approx(s_b["m"], rel=1e-3)
    gleich, gespiegelt = sg.vergleich(s_a, s_b)
    assert gleich and gespiegelt
    # auch gedreht bleibt es ein Spiegelbild
    c = Rot(0, 0, 180) * mirror(winkel(), Plane.XZ)
    assert sg.vergleich(s_a, sig(c)) == (True, True)


def test_symmetrisches_teil_ist_gespiegelt_gleich():
    halter = Box(40, 20, 10) - Pos(0, 0, 0) * Cylinder(4, 20) + Pos(0, 12, 0) * Box(10, 4, 10)
    gleich, gespiegelt = sg.vergleich(sig(halter), sig(mirror(halter, Plane.YZ)))
    assert gleich and not gespiegelt


def test_andere_form_ist_verschieden():
    assert sg.vergleich(sig(winkel()), sig(winkel(loch_x=8.0))) == (False, False)
    assert sg.vergleich(sig(winkel()), sig(Box(40, 10, 8))) == (False, False)
    unterschiede = sg.unterschiede(sig(Box(40, 10, 8)), sig(Box(40, 10, 9)))
    assert any(u.startswith("Volumen +12,5 %") for u in unterschiede) and "Höhe 8 → 9 mm" in unterschiede


def test_drehsymmetrisch_ohne_feste_achsen():
    rolle = Cylinder(15, 40) - Cylinder(4, 50)
    s = sig(rolle)
    assert s["e"] is True
    assert sg.vergleich(s, sig(Pos(50, 50, 0) * Rot(0, 0, 33) * rolle)) == (True, False)


def test_gruppen_der_vorschau_mit_signatur():
    """Vier Teile in Weltlage: zwei deckungsgleich (verschiedene Formschlüssel), eines gespiegelt, eines anders."""
    from kevcad_kernel.druck.vorschau import gruppen

    def geo(teil, form):
        s = sig(teil)
        return {"fid": form, "form": form, "signatur": s, "groesse": s["g"], "auflage": 100.0, "material": "petg",
                "zweck": "funktion", "matrix": np.eye(3).tolist(), "form_matrix": np.eye(3).tolist(),
                "t": [0, 0, 0], "versatz": [0, 0, 0], "volumen": s["v"], "umriss": [[0, 0], [10, 0], [10, 10]],
                "umriss_flaeche": 100.0, "umriss_umfang": 40.0, "oberflaeche": s["a"], "seite": 1.0, "oben": 1.0,
                "unten": 0.0, "ueberhang_flaeche": 0.0, "ueberhang_hoehe": 0.0, "seite_baender": [1.0] * 20,
                "waag_baender": [0.0] * 20, "stueck": 0, "anzahl": None}

    teile = {"Wagen/Winkel vorn (Druck)": geo(winkel(), "f1"),
             "Wagen/Winkel hinten (Druck)": geo(Pos(200, 0, 0) * Rot(0, 0, 180) * winkel(), "f2"),
             "Wagen/Winkel links (Druck)": geo(mirror(winkel(), Plane.YZ), "f3"),
             "Wagen/Platte (Druck)": geo(Box(30, 30, 3), "f4")}
    druck = {"teile": {n: {} for n in teile}, "vorschau": {"teile": teile, "formen": {}}}
    gr, ohne = gruppen(druck, [], {}, {"drucker": "p1p-0.4"})
    assert ohne == []
    assert [(g.name, g.anzahl, g.gespiegelt_von) for g in gr] == [
        ("Winkel (Druck)", 2, None), ("Winkel links (Druck) (gespiegelt)", 1, "g1"), ("Platte (Druck)", 1, None)]
    assert gr[0].teile == ["Wagen/Winkel vorn (Druck)", "Wagen/Winkel hinten (Druck)"]


def test_genauer_vergleich_und_gleichteile():
    """Der genaue Vergleich (Punkte im Hauptachsensystem) trennt deckungsgleich, gespiegelt und verschieden auch dort,
    wo die Momente nah beieinander liegen (kleine Bohrung außermittig)."""
    from kevcad_kernel.druck.vorschau_geo import gleichteile

    def fast_symmetrisch(loch_y=0.0):
        t = Box(60, 30, 12) - Pos(18, loch_y, 0) * Cylinder(1.6, 30)
        return t + Pos(-20, 0, 8) * Box(8, 8, 4)

    teile = {"a": fast_symmetrisch(5.0), "b": Pos(0, 300, 0) * Rot(0, 0, 180) * fast_symmetrisch(5.0),
             "c": mirror(fast_symmetrisch(5.0), Plane.XZ), "d": fast_symmetrisch(0.0), "e": fast_symmetrisch(-5.0)}
    formen, deckung = {}, {}
    for name, t in teile.items():
        P, T, g = netz(t)
        s, extra = sg.mit_deckung(P, T, g)
        formen[name] = {"signatur": s}
        deckung[name] = extra
    assert sg.deckung(deckung["a"], deckung["b"]) == "gleich"
    assert sg.deckung(deckung["a"], deckung["c"]) == "gespiegelt"
    assert sg.deckung(deckung["a"], deckung["d"]) is None
    gleichteile(formen, deckung)
    gt = {n: (f["gleichteil"]["fid"], f["gleichteil"]["gespiegelt"]) for n, f in formen.items()}
    # e (Bohrung auf der anderen Seite) ist das Spiegelbild von a
    assert gt == {"a": ("a", False), "b": ("a", False), "c": ("a", True), "d": ("d", False), "e": ("a", True)}
