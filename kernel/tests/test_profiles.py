"""Querschnitte der Stangenware: Flächen gegen Tabellenwerte, Fläche der build123d-Kontur gegen die Formel, Gehrung."""

import math

import pytest
from build123d import GeomType

from kevcad_kernel.profiles import bar, default_radius, fastener, flaeche_mm2, kg_je_m, querschnitt

STAHL = {"id": "stahl-s235", "dichte": 7.85}


def kgm(art, masse, mat=STAHL):
    return kg_je_m({"art": art, "masse": masse}, mat)


def test_known_table_values():
    # DIN EN 10220: 42,4 × 2,0 → 1,99 kg/m
    assert kgm("rohr", {"d": 42.4, "s": 2.0}) == pytest.approx(1.99, rel=0.02)
    # DIN EN 10219-2 (kalt gefertigt, Außenradius 2·s): 40 × 40 × 3 → 3,30 kg/m
    assert kgm("vierkantrohr", {"a": 40, "s": 3}) == pytest.approx(3.30, rel=0.02)
    # mit kleinem Eckenradius (r = s, wie viele Händlertabellen): ~3,41 kg/m
    assert kgm("vierkantrohr", {"a": 40, "s": 3, "r": 3}) == pytest.approx(3.41, rel=0.03)
    # EN 10219-2: 60 × 40 × 3 → 4,25 kg/m
    assert kgm("rechteckrohr", {"b": 60, "h": 40, "s": 3}) == pytest.approx(4.25, rel=0.02)
    # Flachstahl 40 × 5 → 1,57 kg/m, Rundstahl Ø 20 → 2,47 kg/m, Vierkant 20 → 3,14 kg/m
    assert kgm("flach", {"b": 40, "s": 5}) == pytest.approx(1.57, rel=0.01)
    assert kgm("rund", {"d": 20}) == pytest.approx(2.47, rel=0.01)
    assert kgm("vierkant", {"a": 20}) == pytest.approx(3.14, rel=0.01)
    # EN 10056-1: L 40 × 40 × 4 (r = 6) → 2,42 kg/m
    assert kgm("winkel", {"a": 40, "b": 40, "s": 4, "r": 6}) == pytest.approx(2.42, rel=0.02)
    # Holz 60 × 80, Fichte 0,47 g/cm³ → 2,26 kg/m
    assert kgm("holz", {"b": 60, "h": 80}, {"dichte": 0.47}) == pytest.approx(2.256, rel=0.001)
    # Nutprofil 40 × 40 leicht: Richtwert ~1,47 kg/m (Aluminium 2,7)
    assert kgm("nutprofil", {"raster": 40, "nut": 8}, {"dichte": 2.7}) == pytest.approx(1.47, rel=0.05)


def test_table_value_wins():
    assert kg_je_m({"art": "vierkantrohr", "masse": {"a": 40, "s": 3}, "kg_je_m": 3.41}, STAHL) == 3.41
    assert kg_je_m({"art": "platte", "masse": {"s": 18}}, STAHL) is None


def test_default_radius():
    assert default_radius(3) == 6 and default_radius(6) == 12 and default_radius(8) == 20


@pytest.mark.parametrize("art, masse", [
    ("rohr", {"d": 42.4, "s": 2.0}), ("vierkantrohr", {"a": 40, "s": 3}), ("vierkantrohr", {"a": 30, "s": 2, "r": 2}),
    ("rechteckrohr", {"b": 60, "h": 40, "s": 3}), ("flach", {"b": 40, "s": 5}), ("rund", {"d": 20}),
    ("vierkant", {"a": 20}), ("winkel", {"a": 50, "b": 30, "s": 5, "r": 7}), ("winkel", {"a": 40, "b": 40, "s": 4}),
    ("u_profil", {"h": 100, "b": 50, "s": 6, "t": 8.5}), ("holz", {"b": 60, "h": 80}),
])
def test_face_matches_formula_and_is_centered(art, masse):
    face = querschnitt(art, masse)
    assert face.is_valid
    assert face.area == pytest.approx(flaeche_mm2(art, masse), rel=1e-6)
    c = face.bounding_box().center()
    assert abs(c.X) < 1e-6 and abs(c.Y) < 1e-6 and abs(c.Z) < 1e-9


@pytest.mark.parametrize("masse", [{"raster": 40, "nut": 8}, {"raster": 20, "nut": 5}, {"raster": 30, "nut": 6},
                                   {"raster": 45, "nut": 10, "variante": "schwer"},
                                   {"raster": 40, "nut": 8, "a": 40, "b": 80}])
def test_nutprofil_contour(masse):
    face = querschnitt("nutprofil", masse)
    assert face.is_valid
    size = face.bounding_box().size
    assert size.X == pytest.approx(masse.get("a", masse["raster"])) and size.Y == pytest.approx(masse.get("b", masse["raster"]))
    # vier Nuten je Feld außen plus Kernbohrung: deutlich weniger als das volle Rechteck
    assert face.area < size.X * size.Y * 0.85
    inner = [w for w in face.inner_wires()]
    cells = round(size.X / masse["raster"]) * round(size.Y / masse["raster"])
    assert len(inner) == cells  # je Feld eine Kernbohrung


def _longest_line(part):
    return max(e.length for e in part.edges() if e.geom_type == GeomType.LINE)


@pytest.mark.parametrize("g", [(0, 0), (45, 45), (0, 45), (30, 0), (-45, -45), (22.5, 60)])
def test_miter_length_at_longest_edge(g):
    face = querschnitt("vierkantrohr", {"a": 40, "s": 3})
    part = bar(face, 800, g)
    assert part.is_valid
    bb = part.bounding_box()
    assert bb.min.Z == pytest.approx(0, abs=1e-6)
    assert bb.size.Z == pytest.approx(800, abs=1e-6)  # Hüllmaß = Zuschnittmaß bei gleichsinniger Gehrung
    assert _longest_line(part) == pytest.approx(800, abs=1e-6)
    # kurze Kante: um 40 · tan(w) je Ende kürzer
    short = 800 - sum(40 * math.tan(math.radians(abs(w))) for w in g)
    shortest = min(e.length for e in part.edges() if e.geom_type == GeomType.LINE
                   and abs(e.tangent_at(0).Z) > 0.999)
    assert shortest == pytest.approx(short, abs=1e-6)


def test_miter_sign_keeps_y_side_long():
    face = querschnitt("flach", {"b": 40, "s": 10})
    plus = bar(face, 500, (45, 45))
    minus = bar(face, 500, (-45, -45))
    top = lambda p: [v for v in p.vertices() if abs(v.Z) < 1e-6]  # noqa: E731
    assert all(abs(v.Y - 5) < 1e-6 for v in top(plus))  # Anfang: nur die +Y-Kante liegt bei z = 0
    assert all(abs(v.Y + 5) < 1e-6 for v in top(minus))


def test_mixed_miter_longest_edge():
    part = bar(querschnitt("rohr", {"d": 42.4, "s": 2}), 600, (30, -30))
    assert _longest_line(part) == pytest.approx(600, abs=1e-6)


def test_too_steep_miter():
    with pytest.raises(ValueError, match="zu steil"):
        bar(querschnitt("vierkantrohr", {"a": 40, "s": 3}), 60, (45, 45))


def test_fasteners():
    screw = fastener("schraube", {"typ": "SocketHeadCapScrew", "norm": "iso4762", "groesse": "M8-1.25"}, 60)
    bb = screw.bounding_box()
    assert bb.min.Z == pytest.approx(-60, abs=1e-3) and bb.size.X == pytest.approx(13.27, abs=0.05)
    nut = fastener("mutter", {"typ": "HexNut", "norm": "iso4032", "groesse": "M8-1.25"})
    assert nut.volume > 0
    washer = fastener("scheibe", {"typ": "PlainWasher", "norm": "iso7089", "groesse": "M8"})
    assert washer.bounding_box().size.Z == pytest.approx(1.6, abs=0.3)
    with pytest.raises(ValueError, match="Länge|laenge"):
        fastener("schraube", {"typ": "SocketHeadCapScrew", "norm": "iso4762", "groesse": "M8-1.25"})
    with pytest.raises(ValueError, match="SocketHeadCapScrew"):
        fastener("schraube", {"typ": "SocketHeadCapScrw", "norm": "iso4762", "groesse": "M8-1.25"}, 20)
