"""Die build123d-Rezepte aus skill/kev-cad/3d-druck.md laufen und bestehen die eigene Druckprüfung.

Ausgeführt wird jeder ```python-Block, der mit ``# Rezept:`` beginnt, in Dateireihenfolge in einem Namensraum.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kevcad_kernel.druck import pruefe_druckteil

DOKU = Path(__file__).resolve().parents[2] / "skill" / "kev-cad" / "3d-druck.md"


@pytest.fixture(scope="module")
def ns() -> dict:
    if not DOKU.exists():
        pytest.skip("skill/kev-cad/3d-druck.md fehlt")
    bloecke = re.findall(r"```python\n(# Rezept:.*?)```", DOKU.read_text(encoding="utf-8"), flags=re.S)
    assert len(bloecke) >= 10, "Rezeptblöcke nicht gefunden"
    namensraum: dict = {}
    for b in bloecke:
        exec(compile(b, f"3d-druck.md:{b.splitlines()[0]}", "exec"), namensraum)   # noqa: S102 - eigene Doku
    return namensraum


def arten(r, *schweren):
    return [h["art"] for h in r["hinweise"] if not schweren or h["schwere"] in schweren]


def test_beispiel_halter_ohne_fehler_und_warnungen(ns):
    r = pruefe_druckteil(ns["halter"], "petg")
    assert arten(r, "fehler", "warnung") == [], [h["text"] for h in r["hinweise"]]
    assert r["ausrichtung"]["unten"] == [0.0, 0.0, -1.0]


def test_tropfenbohrung(ns):
    Box, Pos, Rot, UNTEN = ns["Box"], ns["Pos"], ns["Rot"], ns["UNTEN"]
    for werkzeug in (ns["tropfenbohrung"](5.3, 30), ns["tropfenbohrung"](5.3, 30, kappe=0.0)):
        teil = Box(30, 20, 15, align=UNTEN) - Pos(0, 0, 7.6) * werkzeug
        assert "waagrechte_bohrung" not in arten(pruefe_druckteil(teil, "petg", "-z"))
    quer = Box(20, 30, 15, align=UNTEN) - Pos(0, 0, 7.6) * Rot(0, 0, 90) * ns["tropfenbohrung"](5.3, 30)
    assert "waagrechte_bohrung" not in arten(pruefe_druckteil(quer, "petg", "-z"))
    rund = Box(30, 20, 15, align=UNTEN) - Pos(0, 0, 7.6) * Rot(90, 0, 0) * ns["Cylinder"](2.65, 30)
    assert "waagrechte_bohrung" in arten(pruefe_druckteil(rund, "petg", "-z"))   # Gegenprobe


def test_bettfase(ns):
    Box, UNTEN = ns["Box"], ns["UNTEN"]
    roh = ns["fillet"](Box(40, 30, 10, align=UNTEN).edges().filter_by(ns["Axis"].Z), 4) - ns["Cylinder"](3.3, 30)
    assert "elefantenfuss" in arten(pruefe_druckteil(roh, "petg", "-z"))
    assert pruefe_druckteil(ns["bettfase"](roh), "petg", "-z")["hinweise"] == []


def test_passung_und_einsatz(ns):
    assert ns["bohrung_fuer"](5, "spiel") == pytest.approx(5.3)
    assert ns["bohrung_fuer"](8, "press") == pytest.approx(8.0)
    w = ns["einsatz_tasche"]("M3", entlastung=0)
    bb = w.bounding_box()
    assert bb.size.X == pytest.approx(4.2) and bb.min.Z == pytest.approx(-6.8) and bb.max.Z == pytest.approx(1)
    assert ns["einsatz_tasche"]("M3").bounding_box().min.Z == pytest.approx(-10.8, abs=0.02)  # Entlastung 4 mm
    Box, Pos, UNTEN = ns["Box"], ns["Pos"], ns["UNTEN"]
    flach = Box(20, 20, 16, align=UNTEN) - Pos(0, 0, 16) * ns["einsatz_tasche"]("M3", entlastung=0)
    assert "einsatz_sackloch" in arten(pruefe_druckteil(flach, "petg", "-z"), "warnung")
    gut = Box(20, 20, 16, align=UNTEN) - Pos(0, 0, 16) * ns["einsatz_tasche"]("M3")
    assert "einsatz_sackloch" not in arten(pruefe_druckteil(gut, "petg", "-z"))
    dom = ns["einsatz_dom"]("M3", 10)
    assert dom.bounding_box().size.X == pytest.approx(4.6 + 2 * 1.6)


def test_mutterntasche(ns):
    Box, Pos, Cyl, UNTEN = ns["Box"], ns["Pos"], ns["Cylinder"], ns["UNTEN"]
    offen = Box(20, 20, 8, align=UNTEN) - Pos(0, 0, 8) * ns["mutter_tasche"]("M3") - Cyl(1.7, 30)
    r = pruefe_druckteil(ns["bettfase"](offen), "petg", "-z")
    assert r["hinweise"] == [], [h["text"] for h in r["hinweise"]]
    w = ns["mutter_tasche"]("M3", fase=0)
    assert w.bounding_box().size.Y == pytest.approx(5.8, abs=1e-3)       # Schlüsselweite + 0,3 (Flachseiten ⟂ Y)
    seitlich = Box(20, 20, 8, align=UNTEN) - Pos(0, 0, 5) * ns["mutter_tasche"]("M3", fase=0, schlitz=12)
    seitlich -= Pos(0, 0, -1) * Cyl(1.7, 3.4, align=UNTEN)
    seitlich -= Pos(0, 0, 5.2) * Cyl(1.7, 5, align=UNTEN)
    r2 = pruefe_druckteil(seitlich, "petg", "-z")
    assert "opferschicht" in arten(r2) and not arten(r2, "fehler", "warnung")


@pytest.mark.parametrize("art", ["opfer", "bruecke"])
def test_gegenbohrung(ns, art):
    teil = ns["Box"](30, 30, 10, align=ns["UNTEN"]) - ns["gegenbohrung_unten"](3.4, 6.5, 3.4, 20, art=art)
    r = pruefe_druckteil(teil, "petg", "-z")
    assert not arten(r, "fehler", "warnung"), [h["text"] for h in r["hinweise"]]
    assert ("opferschicht" in arten(r)) == (art == "opfer")


def test_schnapphaken(ns):
    haken, y = ns["schnapphaken"](15, 2, 6, "petg")
    assert haken.is_valid and y == pytest.approx(0.67 * 0.025 * 15 ** 2 / 2)
    r = pruefe_druckteil(haken, "petg", "-z")
    assert not arten(r, "fehler", "warnung")
    haken_pla, y_pla = ns["schnapphaken"](15, 2, 6, "pla", oft_loesen=True)
    assert y_pla == pytest.approx(0.67 * 0.015 * 0.6 * 225 / 2)


def test_teilung_mit_passstiften(ns):
    gross = ns["Box"](80, 60, 300, align=ns["UNTEN"])
    assert not pruefe_druckteil(gross, "petg", "-z")["ok"]
    unten, oben = ns["teilen"](gross, 150, [(-20, 0), (20, 0)])
    for teil in (unten, oben):
        r = pruefe_druckteil(teil, "petg", "-z")
        assert r["ok"] and not arten(r, "fehler", "warnung"), [h["text"] for h in r["hinweise"]]
        assert len([f for f in teil.faces() if f.geom_type == ns["GeomType"].CYLINDER]) >= 2
    assert ns["z_raster"](2.5) in (2.4, 2.6)
