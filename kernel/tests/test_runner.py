"""Hilfsfunktionen des Rechenprozesses (runner.py) ohne Unterprozess: Farben, Materialien, show()-Zerlegung,
Fehlerauszug und Hinweise."""

import pytest
from build123d import Box, BuildPart, Compound, Pos

from kevcad_kernel.runner import excerpt, hint_for, parse_color, resolve_material, split_parts


def test_parse_color():
    assert parse_color("#FF0000") == (1.0, 0.0, 0.0, 1.0)
    assert parse_color("red") == (1.0, 0.0, 0.0, 1.0)
    assert parse_color((255, 0, 0)) == (1.0, 0.0, 0.0, 1.0)
    assert parse_color((0.1, 0.2, 0.3, 0.5)) == (0.1, 0.2, 0.3, 0.5)
    with pytest.raises(ValueError, match="unbekannt"):
        parse_color("nichtfarbe")


@pytest.mark.parametrize("name, grade", [
    ("aluminium", "Alu_G6061_T6"), ("Aluminium", "Alu_G6061_T6"), ("aluminum", "Alu_G6061_T6"),
    ("Stahl", "MildSteel_PLAIN_CARBON_GENERIC"), ("Edelstahl", "Stainless_G304_ANNEALED"),
    ("Messing", "Brass_C360_HALF_HARD"), ("Kupfer", "Copper_C110_ANNEALED"), ("Holz", "Hardwood_GENERIC"),
    ("Buche", "Hardwood_BEECH"), ("Eiche", "Hardwood_OAK"), ("PLA", "PLA_GENERIC"), ("PETG", "PETG_GENERIC"),
    ("ABS", "ABS_GENERIC"),
])
def test_material_aliases(name, grade):
    fm, shown = resolve_material(name)
    assert fm.material.name == grade and fm.material.density > 0
    assert shown == name  # angezeigt wird der Name aus model.py


def test_unknown_material_suggests():
    with pytest.raises(ValueError, match="Meinten Sie"):
        resolve_material("aluminim")


def test_split_parts():
    a = Box(1, 1, 1)
    a.label = "A"
    b = Pos(3, 0, 0) * Box(1, 1, 1)
    b.label = "A"
    inner = Compound(label="Innen", children=[Pos(0, 5, 0) * Box(1, 1, 1)])
    inner.children[0].label = "Klotz"
    names = [n for n, _, _ in split_parts(Compound(label="G", children=[a, b, inner]), "Gruppe")]
    assert names == ["Gruppe/A", "Gruppe/A 2", "Gruppe/Innen/Klotz"]
    with BuildPart() as bp:
        Box(2, 2, 2)
    (name, shape, child), = split_parts(bp, "Teil")
    assert name == "Teil" and not child and abs(shape.volume - 8) < 1e-9
    (name, shape, _), = split_parts(Box(1, 1, 1).edges(), "Kanten")
    assert len(shape.edges()) == 12
    with pytest.raises(TypeError, match="keine build123d-Form"):
        split_parts(42, "Zahl")


def test_excerpt_and_hints():
    code = "a = 1\nb = 2\nc = Boxx(3)\nd = 4\ne = 5\nf = 6\ng = 7\n"
    ex = excerpt(code, 3)
    assert ex.splitlines() == ["  1 | a = 1", "  2 | b = 2", "> 3 | c = Boxx(3)", "  4 | d = 4", "  5 | e = 5",
                               "  6 | f = 6"]
    try:
        eval("Boxx", {})
    except NameError as exc:
        assert "Meinten Sie Box" in hint_for(exc, {})
    assert "Division durch null" in hint_for(ZeroDivisionError("x"))
    assert hint_for(KeyError("x")) == ""


def test_sample_matches_template():
    from pathlib import Path

    from kevcad_kernel.project import EXAMPLE_MODEL

    sample = Path(__file__).resolve().parents[2] / "samples/wandhalter/model.py"
    assert sample.read_text(encoding="utf-8") == EXAMPLE_MODEL
