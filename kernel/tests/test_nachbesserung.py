"""Nachbesserungen aus dem Einsatz am Kugelschieber (Kevin, 22.10.2026).

1. ``tools/check_interference.py`` nutzt die eingebaute Prüfung (Gewindeeingriff, ``erlaubt_ueberlappung``).
2. Scheiben und Einsätze in ``verbinde(..., mit=[…])`` gelten nicht als Schraube.
3. Zollgewinde (UNC/UNF) in Gewindeeingriff und Schraubprüfung.
4. ``bedienung="fluegel"`` und Griffraum für Teile, die um ihre eigene Achse gedreht werden.
5. Eindeutige Richtung von ``bezug(..., "bohrung")`` und ``richtung=``.
6. Partner im Gewinde blockieren den Bewegungsraum entlang der Gewindeachse nicht.
7. Zwischenspeicher des Bewegungsraums über Läufe.
8. Kulissenteile (``show(..., kulisse=True)``, ``lager.kulisse``).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
from build123d import Align, Axis, Box, Cylinder, Plane, Polygon, Pos, Rot, extrude

from kevcad import lager
from kevcad.bedingungen import bezug, drehgelenk, in_bohrung, platziere, schiebegelenk, verbinde
from kevcad_kernel import gewinde as gw
from kevcad_kernel.bedingungen import BezugFehler, pruefen, sammeln
from kevcad_kernel.bedingungen import bewegungsraum as br
from kevcad_kernel.bedingungen.geometrie import schraube_daten, verbindungsteil
from kevcad_kernel.pruefung.koerper import koerper_aus_form
from kevcad_kernel.pruefung.kollision import entlang_gewinde, im_gewinde
from kevcad_kernel.pruefung.pruefer import pruefe

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)
OBEN = (Align.CENTER, Align.CENTER, Align.MAX)


def befunde(bericht: dict, pruefung: str | None = None, schwere: str | None = None) -> list[dict]:
    return [b for b in bericht["befunde"] if (pruefung is None or b["pruefung"] == pruefung)
            and (schwere is None or b["schwere"] == schwere)]


def nur_durchdringung(formen: dict) -> dict:
    ks = [koerper_aus_form(n, f) for n, f in formen.items()]
    erg, _ = pruefe(ks, {}, {"pruefungen": ("erklaerungen", "durchdringung")})
    return erg


def scheibe(d_innen: float, d_aussen: float, s: float):
    return Cylinder(d_aussen / 2, s, align=UNTEN) - Cylinder(d_innen / 2, 3 * s)


# ---------------------------------------------------------------------------------------------------------------------
# 1. check_interference.py


TOOLS = Path(__file__).resolve().parents[1] / "tools"

MODELL_EINSATZ = """from build123d import *
from kevcad import show, erlaubt_ueberlappung

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)
block = Box(40, 40, 20, align=UNTEN) - Pos(0, 0, 10) * Cylinder(2.9, 12, align=UNTEN)
show(block, "Block", material="pla")
einsatz = Pos(0, 0, 10) * (Cylinder(2.9, 8.1, align=UNTEN) - Cylinder(1.65, 20))  # Kernloch M4 3,3
show(einsatz, "Gewindeeinsatz M4", material="messing")
show(Pos(0, 0, 11) * Cylinder(2, 20, align=UNTEN), "Gewindestift M4", material="stahl")
show(Pos(30, 0, 0) * Box(10, 10, 10, align=UNTEN), "Stopfen", material="pla")
show(Pos(30, 0, 9) * Box(6, 6, 6, align=UNTEN), "Polster", material="pla")
erlaubt_ueberlappung("Stopfen", "Polster", grund="Presspassung, mit Kevin abgestimmt")
show(Pos(-17, 0, 19) * Box(10, 10, 10, align=UNTEN), "Klotz", material="pla")
"""


@pytest.fixture(scope="module")
def projekt_einsatz():
    tmp = Path(tempfile.mkdtemp(prefix="kcnb", dir=tempfile.gettempdir()))
    p = tmp / "Einsatz"
    p.mkdir()
    (p / "model.py").write_text(MODELL_EINSATZ, encoding="utf-8")
    (p / "kevcad.json").write_text('{"version": 1, "unit": "mm", "inventar_regel": false}', encoding="utf-8")
    yield p
    shutil.rmtree(tmp, ignore_errors=True)


def test_check_interference_nutzt_die_eingebaute_pruefung(projekt_einsatz):
    sys.path.insert(0, str(TOOLS))
    try:
        import check_interference as ci
    finally:
        sys.path.remove(str(TOOLS))
    shapes, pruefung = ci.load_project(projekt_einsatz)
    out = ci.auswerten(pruefung)
    # Gewindestift im Einsatz (Kernloch M4) ist Gewindeeingriff, Stopfen/Polster ist erlaubt, Klotz steckt im Block
    assert [f["teile"] for f in out["durchdringungen"]] == [["Block", "Klotz"]]
    assert out["durchdringungen"][0]["loesung"] and out["durchdringungen"][0]["tiefe_mm"] == pytest.approx(1.0, 1e-3)
    assert len(out["gewinde"]) == 1 and "Gewindeeingriff M4" in out["gewinde"][0]["text"]
    assert [e["teile"] for e in out["erlaubt"]] in ([["Stopfen", "Polster"]], [["Polster", "Stopfen"]])
    # gleiche Befunde wie die Prüfung im Lauf
    lauf = [b["teile"] for b in pruefung["befunde"] if b["art"] == "durchdringung"]
    assert lauf == [f["teile"] for f in out["durchdringungen"]]
    assert set(shapes) >= {"Block", "Gewindeeinsatz M4", "Gewindestift M4"}


# ---------------------------------------------------------------------------------------------------------------------
# 2. Scheiben und Einsätze sind keine Schrauben


def test_verbindungsteil_aus_lagerteil_und_form():
    s = lager.teil("scheibe-iso7089-m8").verbauen(name="Scheibe")
    m = lager.teil("mutter-iso4032-m8").verbauen(name="Mutter")
    sch = lager.teil("schraube-iso4762-m8").verbauen(laenge=20, name="Schraube")
    assert verbindungsteil(s) == "scheibe" and verbindungsteil(m) == "mutter" and verbindungsteil(sch) == "schraube"
    # ohne Lagerteil: Ring mit Bohrung
    assert verbindungsteil(scheibe(6.4, 18, 1.6)) == "scheibe"
    assert verbindungsteil(scheibe(5.0, 8.2, 12.7)) == "ring"  # Gewindeeinsatz M6 als Ring
    assert verbindungsteil(Cylinder(3, 20)) is None  # Schaft ohne Bohrung
    with pytest.raises(BezugFehler, match="Scheibe, keine Schraube"):
        schraube_daten(scheibe(6.4, 18, 1.6))
    with pytest.raises(BezugFehler, match="Ring mit Bohrung"):
        schraube_daten(scheibe(5.0, 8.2, 12.7))


def test_verbinde_mit_selbstgebauter_scheibe_und_einsatz():
    """Halter auf Platte: M6-Schraube von oben durch die Platte (Ø 6,6), Scheibe Ø 18 unter dem Kopf, Gewindeeinsatz
    im Halter. Scheibe und Einsatz sind selbst gebaut (kein Lagerteil); früher galt die Scheibe als Schraube M18."""
    platte = Pos(0, 0, 20) * (Box(60, 60, 5, align=UNTEN) - Cylinder(3.3, 30))
    halter = Box(30, 30, 20, align=UNTEN) - Pos(0, 0, 20) * Cylinder(4.1, 14, align=OBEN)
    einsatz = Pos(0, 0, 20) * (Cylinder(4.1, 12.7, align=OBEN) - Cylinder(2.5, 40))  # Kernloch M6
    sch = lager.teil("schraube-iso4762-m6").verbauen(laenge=16, name="Schraube")
    sch = Pos(0, 0, 26.6) * sch  # Kopf auf der Scheibe (Platte 25, Scheibe 1,6)
    sb = Pos(0, 0, 25) * scheibe(6.4, 18, 1.6)
    with sammeln() as s:
        verbinde(halter, platte, art="schraube", mit=[sch, sb, einsatz])
        verbinde(sb, platte, art="aufliegen")
        verbinde(einsatz, halter, art="formschluss")
        b = pruefen(s, {"Platte": platte, "Halter": halter, "Schraube": sch, "Scheibe": sb, "Einsatz": einsatz})
    texte = [f["text"] for f in befunde(b, "befestigung")]
    assert not any("M18" in t or "zu klein" in t for t in texte), texte
    v = [i for i in b["items"] if i["art"] == "verbinde" and i.get("verbindung") == "schraube"]
    assert v[0]["stand"] == "erfuellt", v[0]
    # Nur Scheibe statt Einsatz: zwei Durchgangsbohrungen, eine Scheibe ist keine Mutter
    with sammeln() as s:
        halter2 = Box(30, 30, 20, align=UNTEN) - Pos(0, 0, 20) * Cylinder(3.3, 50)
        verbinde(halter2, platte, art="schraube", mit=[sch, sb])
        b = pruefen(s, {"Platte": platte, "Halter": halter2, "Schraube": sch, "Scheibe": sb})
    assert any("es fehlt eine Mutter" in f["text"] for f in befunde(b, "befestigung"))


# ---------------------------------------------------------------------------------------------------------------------
# 3. Zollgewinde


def test_gewindetabelle_zoll():
    g = gw.aus_text("3/8\"-16 UNC")
    assert g.d == pytest.approx(9.525) and g.steigung == pytest.approx(25.4 / 16) and g.name == "3/8\"-16 UNC"
    assert g.kernloch == pytest.approx(7.938, abs=1e-3)
    for text, d, tpi in (("1/4-20", 6.35, 20), ("#10-24", 4.826, 24), ("5/16-18", 7.9375, 18), ("1/2-13", 12.7, 13),
                         ("1/4 UNF", 6.35, 28), ("No. 10-32", 4.826, 32), ("3⁄8 Zoll", 9.525, 16)):
        g = gw.aus_text(text)
        assert g is not None and g.d == pytest.approx(d, abs=1e-3) and g.steigung == pytest.approx(25.4 / tpi), text
    assert gw.aus_text("M8-1.25").name == "M8" and gw.aus_text("M4-0.7-8.1").d == 4
    assert gw.aus_text("6") is None and gw.aus_text("") is None
    assert gw.naechstes(9.525).name == "3/8\"-16 UNC" and gw.naechstes(8.0).name == "M8"
    assert gw.naechstes(7.94).name == "5/16\"-18 UNC" and gw.naechstes(6.0).name == "M6"


def test_gewindeeingriff_zoll_erkannt():
    # 3/8"-16 UNC (Ø 9,525) im Kernloch 5/16" (Ø 7,94): Gewindeeingriff, kein Befund
    platte = Box(40, 40, 12, align=UNTEN) - Cylinder(7.94 / 2, 40)
    schraube = Pos(0, 0, -4) * Cylinder(9.525 / 2, 14, align=UNTEN)
    erg = nur_durchdringung({"Kopfplatte": platte, "Senkschraube 3/8": schraube})
    assert erg["befunde"] == [] and len(erg["gewinde"]) == 1
    assert "3/8\"-16 UNC" in erg["gewinde"][0]["text"]
    # 1/4"-20 im Kernloch 5,1
    erg = nur_durchdringung({"Platte": Box(30, 30, 8, align=UNTEN) - Cylinder(2.55, 40),
                             "Stativschraube": Cylinder(3.175, 16)})
    assert erg["befunde"] == [] and "1/4\"-20 UNC" in erg["gewinde"][0]["text"]
    # Helfer für build123d-Formen
    g = im_gewinde(schraube, platte, name_a="Schraube", name_b="Platte")
    assert g is not None and g.gewinde.name == "3/8\"-16 UNC" and g.aussen == "Schraube"


def test_schraubpruefung_zoll():
    schraube = Cylinder(9.525 / 2, 15.875, align=OBEN) + Cylinder(9.525, 4, align=UNTEN)  # Kopf oben
    d = schraube_daten(schraube)
    assert d.bezeichnung == "3/8\"-16 UNC" and d.steigung == pytest.approx(1.5875)
    block = Box(40, 40, 30, align=OBEN) - Pos(0, 0, 0) * Cylinder(7.94 / 2, 40, align=OBEN)
    with sammeln() as s:
        sch = platziere(schraube, in_bohrung(schraube, bezug(block, "bohrung"), gewinde=True))
        b = pruefen(s, {"Block": block, "Schraube": sch})
    ib = [i for i in b["items"] if i["art"] == "in_bohrung"][0]
    assert ib["stand"] == "erfuellt" and "3/8\"-16 UNC" in ib["soll"], ib
    with sammeln() as s:  # Bohrung so groß wie das Gewinde: Befund nennt das Zollgewinde und das Kernloch
        block2 = Box(40, 40, 30, align=OBEN) - Cylinder(5.0, 40, align=OBEN)
        sch = platziere(schraube, in_bohrung(schraube, bezug(block2, "bohrung"), gewinde=True))
        b = pruefen(s, {"Block": block2, "Schraube": sch})
    (f,) = [f for f in befunde(b) if f["unterart"] == "in_bohrung"]
    assert "3/8\"-16 UNC" in f["soll"] and "7,94" in f["soll"]


# ---------------------------------------------------------------------------------------------------------------------
# 4. Flügelmutter: Griffraum statt Kugel um die Spitze


def fluegelmutter():
    """Flügelmutter DIN 315 M4 wie im Kugelschieber: Achse z, Auflage bei z = 0, Flügel längs x."""
    e, h, m, d1, g = 20, 10.5, 4.6, 8, 1.9
    mutter = Cylinder(d1 / 2, m, align=UNTEN)
    for s in (1, -1):
        pts = [(s * (d1 / 2 - 1), 0.5), (s * (e / 2 - 2.5), 1.5), (s * e / 2, 4), (s * e / 2, h - 2.5),
               (s * (e / 2 - 2.5), h), (s * (d1 / 2 - 1), h - 1)]
        fl = extrude(Plane.XZ * Polygon(*pts, align=None), amount=g)
        mutter += Pos(0, -fl.bounding_box().center().Y, 0) * fl
    return mutter - Cylinder(2.05, 3 * h)


def _fluegel_formen(wand: bool = False) -> dict:
    platte = Box(80, 80, 5, align=OBEN) - Cylinder(2.25, 20)
    formen = {"Platte": platte, "Scheibe": scheibe(4.3, 9, 0.8), "Mutter": Pos(0, 0, 0.8) * fluegelmutter(),
              "Stift": Pos(0, 0, -8) * Cylinder(2, 16, align=UNTEN)}
    if wand:
        formen["Wand"] = Pos(17, 0, 0) * Box(4, 40, 30, align=UNTEN)  # 15 mm neben der Achse
    return formen


@pytest.mark.parametrize("bedienung", ["fluegel", "finger"])
def test_fluegelmutter_auf_platte_hat_griffraum(bedienung):
    f = _fluegel_formen()
    with sammeln() as s:
        drehgelenk(bezug(f["Mutter"], "achse"), bezug(f["Stift"], "achse"), bereich=(0, 180), schritte=12,
                   bedienung=bedienung)
        b = pruefen(s, f)
    (bew,) = b["bewegungen"]
    assert bew["griffraum"]["auflage"] == "unten" and bew["griffraum"]["r_spitze"] == pytest.approx(10, abs=0.1)
    assert bew["eng"] == [] and bew["kollisionen"] == [] and not befunde(b, "bewegungsraum"), b["befunde"]


def test_fluegelmutter_mit_wand_daneben():
    f = _fluegel_formen(wand=True)
    with sammeln() as s:
        drehgelenk(bezug(f["Mutter"], "achse"), bezug(f["Stift"], "achse"), bereich=(0, 180), schritte=12,
                   bedienung="fluegel")
        b = pruefen(s, f)
    (bew,) = b["bewegungen"]
    assert bew["kollisionen"] == []  # die Flügel drehen frei …
    (eng,) = bew["eng"]  # … aber Daumen und Zeigefinger haben keinen Platz
    assert eng["gegen"] == "Wand" and eng["min_abstand"] == pytest.approx(5.0, abs=0.1) and eng["griffraum"]
    (fb,) = befunde(b, "bewegungsraum", "fehler")
    assert "kein Griffraum" in fb["text"] and "über der Auflage" in fb["text"] and "nötig 10 mm" in fb["text"]


# ---------------------------------------------------------------------------------------------------------------------
# 5. Richtung aus bohrung


def test_bohrung_richtung_eindeutig():
    sackloch = Box(40, 40, 20, align=UNTEN) - Pos(0, 0, 20) * Cylinder(3, 12, align=OBEN)  # offen nach oben
    b = bezug(sackloch, "bohrung")
    assert np.allclose(b.d, [0, 0, 1])  # aus dem Loch heraus, durch die Öffnung
    sackloch_unten = Box(40, 40, 20, align=UNTEN) - Cylinder(3, 12, align=UNTEN)  # offen nach unten
    assert np.allclose(bezug(sackloch_unten, "bohrung").d, [0, 0, -1])
    quer = Box(40, 20, 20, align=UNTEN) - Pos(0, 0, 10) * Rot(0, 90, 0) * Cylinder(3, 60)  # Durchgang längs x
    assert np.allclose(bezug(quer, "bohrung").d, [1, 0, 0])  # positive Hauptrichtung
    assert np.allclose(bezug(quer, "bohrung", richtung="-x").d, [-1, 0, 0])
    assert np.allclose(bezug(quer, "bohrung", richtung=(-1, 0.1, 0)).d, [-1, 0, 0])
    assert np.allclose(bezug(quer, "achse_x", richtung="-x").d, [-1, 0, 0])
    with pytest.raises(BezugFehler, match="senkrecht"):
        bezug(quer, "bohrung", richtung="+z")


@pytest.mark.parametrize("richtung,vorzeichen", [(None, 1.0), ("-x", -1.0)])
def test_schiebegelenk_bereich_folgt_der_bohrungsrichtung(richtung, vorzeichen):
    """Schieber in einer Führung mit Durchgangsbohrung längs x: Der Bereich (0 … 30) läuft entlang der Richtung des
    festen Bezugs, ohne Angabe +x, mit richtung="-x" nach −x. Ein Anschlag bei +x stößt nur im ersten Fall an."""
    fuehrung = Box(20, 20, 20, align=UNTEN) - Pos(0, 0, 10) * Rot(0, 90, 0) * Cylinder(3, 60)
    stange = Pos(0, 0, 10) * Rot(0, 90, 0) * Cylinder(2.9, 30)  # von x = −15 bis 15
    anschlag = Pos(40, 0, 0) * Box(4, 20, 20, align=UNTEN)
    with sammeln() as s:
        schiebegelenk(bezug(stange, "achse"), bezug(fuehrung, "bohrung", richtung=richtung), bereich=(0, 30),
                      schritte=6)
        b = pruefen(s, {"Führung": fuehrung, "Stange": stange, "Anschlag": anschlag})
    (bew,) = b["bewegungen"]
    assert bew["richtung"][0] == pytest.approx(vorzeichen)
    stoesst = [k["gegen"] for k in bew["kollisionen"]]
    assert stoesst == (["Anschlag"] if vorzeichen > 0 else [])


# ---------------------------------------------------------------------------------------------------------------------
# 6. Gewinde in der Ausgangslage blockiert den Weg entlang der Achse nicht


def _schraube_im_kernloch():
    block = Box(30, 30, 20, align=UNTEN) - Pos(0, 0, 20) * Cylinder(2.5, 15, align=OBEN)  # Kernloch M6, 15 tief
    schraube = Pos(0, 0, 8) * (Cylinder(3, 12, align=UNTEN) + Pos(0, 0, 12) * Cylinder(5, 4, align=UNTEN))
    return block, schraube


def test_helfer_im_gewinde_und_entlang():
    block, schraube = _schraube_im_kernloch()
    g = im_gewinde(schraube, block, name_a="Schraube", name_b="Block")
    assert g is not None and g.gewinde.name == "M6" and np.allclose(np.abs(g.achse), [0, 0, 1])
    assert entlang_gewinde(g, (0, 0, 1)) and entlang_gewinde(g, (0, 0, -1), punkt=(0, 0, 5), drehen=True)
    assert not entlang_gewinde(g, (1, 0, 0)) and not entlang_gewinde(g, (0, 0, 1), punkt=(5, 0, 0), drehen=True)
    assert im_gewinde(Pos(40, 0, 0) * schraube, block) is None and entlang_gewinde(None, (0, 0, 1)) is False


def test_bewegungsraum_schraube_im_gewinde():
    block, schraube = _schraube_im_kernloch()
    achse_fest = bezug(block, "bohrung")
    for gelenk, erwartet in (
            (lambda: drehgelenk(bezug(schraube, "achse"), achse_fest, bereich=(0, 360), schritte=8), []),
            (lambda: schiebegelenk(bezug(schraube, "achse"), achse_fest, bereich=(0, 30), schritte=6), []),
            (lambda: schiebegelenk(bezug(schraube, "achse_x"), bezug(block, "achse_x"), bereich=(0, 10), schritte=5),
             ["Block"])):
        with sammeln() as s:
            gelenk()
            b = pruefen(s, {"Block": block, "Schraube": schraube})
        (bew,) = b["bewegungen"]
        assert [k["gegen"] for k in bew["kollisionen"]] == erwartet, bew
        if not erwartet:
            assert bew["gewinde"][0]["teile"] == ["Schraube", "Block"]


def test_check_motion_schraube_im_gewinde():
    sys.path.insert(0, str(TOOLS))
    try:
        import check_motion as cm
    finally:
        sys.path.remove(str(TOOLS))
    block, schraube = _schraube_im_kernloch()
    shapes = {"Block": block, "Schraube": schraube}
    raus = cm.run_motion(shapes, {"teile": ["Schraube"], "art": "schieben", "richtung": [0, 0, 1], "von": 0,
                                  "bis": 20, "schritte": 4}, 0.001)
    assert raus["kollisionen"] == [] and raus["gewinde"][0]["teile"] == ["Schraube", "Block"]
    quer = cm.run_motion(shapes, {"teile": ["Schraube"], "art": "schieben", "richtung": [1, 0, 0], "von": 0,
                                  "bis": 10, "schritte": 5}, 0.001)
    assert [c["gegen"] for c in quer["kollisionen"]] == ["Block"] and quer["gewinde"] == []


# ---------------------------------------------------------------------------------------------------------------------
# 7. Zwischenspeicher des Bewegungsraums


def _klappen_modell(versatz: float = 0.0):
    rahmen = Box(100, 20, 10, align=UNTEN) + Pos(-30 + versatz, 0, 40) * Box(4, 20, 20, align=UNTEN)
    lager_ = Pos(-50, 0, 15) * Rot(90, 0, 0) * Cylinder(3, 20)
    klappe = Pos(-27, 0, 15) * Box(36, 18, 2) + Pos(-50, 0, 15) * Rot(90, 0, 0) * (Cylinder(5, 18) - Cylinder(3.2, 20))
    zweite = Pos(60, 0, 30) * Box(10, 10, 10, align=UNTEN)
    achse2 = Pos(60, 0, 25) * Cylinder(2, 10)
    return {"Rahmen": rahmen, "Lager": lager_, "Klappe": klappe, "Klotz": zweite, "Achse 2": achse2}


def _b8(formen: dict, schluessel: dict, zeitlimit_s: float = 30.0) -> dict:
    with sammeln() as s:
        drehgelenk(bezug(formen["Klappe"], "bohrung"), bezug(formen["Lager"], "achse"), bereich=(-60, 90),
                   schritte=30)
        drehgelenk(bezug(formen["Klotz"], "achse_z"), bezug(formen["Achse 2"], "achse"), bereich=(0, 90), schritte=9)
        return pruefen(s, formen, schluessel=schluessel, zeitlimit_s=zeitlimit_s)


def test_bewegungsraum_zwischenspeicher_ueber_laeufe():
    br._CACHE.clear()
    br._PAAR_CACHE.clear()
    formen = _klappen_modell()
    sk = {n: f"k-{n}" for n in formen}
    t0 = time.perf_counter()
    b1 = _b8(formen, sk)
    t1 = time.perf_counter() - t0
    assert not any(bw["zwischenspeicher"] for bw in b1["bewegungen"])
    t0 = time.perf_counter()
    b2 = _b8(_klappen_modell(), sk)  # gleicher Stand, neue Objekte (wie ein neuer Lauf)
    t2 = time.perf_counter() - t0
    assert all(bw["zwischenspeicher"] for bw in b2["bewegungen"])
    assert [bw["frei"] for bw in b2["bewegungen"]] == [bw["frei"] for bw in b1["bewegungen"]]
    assert t2 < max(0.05, t1 / 5), (t1, t2)
    # Rahmen geändert: nur das Gelenk der Klappe rechnet neu, der Klotz kommt aus dem Zwischenspeicher
    formen3 = _klappen_modell(versatz=5)
    b3 = _b8(formen3, {**sk, "Rahmen": "k-Rahmen-neu"})
    neu = {bw["teile"][0]: bw["zwischenspeicher"] for bw in b3["bewegungen"]}
    assert neu == {"Klappe": False, "Klotz": True}


def test_bewegungsraum_setzt_nach_zeitlimit_fort():
    br._CACHE.clear()
    br._PAAR_CACHE.clear()
    formen = _klappen_modell()
    sk = {n: f"z-{n}" for n in formen}
    b1 = _b8(formen, sk, zeitlimit_s=0.03)  # bricht ab: kein Ergebnis je Weg, aber die gerechneten Paare bleiben
    assert any("Zeitlimit" in f["text"] for f in b1["befunde"])
    n1 = len(br._PAAR_CACHE)
    _b8(formen, sk, zeitlimit_s=0.03)  # der nächste Lauf setzt fort
    n2 = len(br._PAAR_CACHE)
    assert n2 >= n1 and n2 > 0
    b3 = _b8(formen, sk)
    assert not any(bw["teilweise"] for bw in b3["bewegungen"]) and len(b3["bewegungen"]) == 2
    assert len(br._PAAR_CACHE) >= n2


# ---------------------------------------------------------------------------------------------------------------------
# 8. Kulisse


def test_kulisse_ist_boden_und_braucht_keine_befestigung():
    tisch = Box(400, 400, 50, align=UNTEN)  # Kulisse: Tisch, auf dem das Modell steht
    klotz = Pos(0, 0, 50) * Box(40, 40, 20, align=UNTEN)
    deckel = Pos(0, 0, 70) * Box(40, 40, 5, align=UNTEN)
    with sammeln() as s:
        verbinde(deckel, klotz, art="aufliegen")
        b = pruefen(s, {"Kulisse/Tisch": tisch, "Klotz": klotz, "Deckel": deckel}, kulisse={"Kulisse/Tisch"})
    assert not befunde(b, "befestigung", "fehler"), befunde(b, "befestigung")
    klotz_info = next(t for t in b["teile"] if t["name"] == "Klotz")
    assert klotz_info["am_boden"] and "boden" in klotz_info["verbindungen"]
    with sammeln() as s:  # ohne Kennzeichnung: der Tisch braucht eine Befestigung, der Klotz hängt in der Luft
        verbinde(deckel, klotz, art="aufliegen")
        b = pruefen(s, {"Kulisse/Tisch": tisch, "Klotz": klotz, "Deckel": deckel})
    texte = " ".join(f["text"] for f in befunde(b, "befestigung", "fehler"))
    assert "Kulisse/Tisch" in texte and "Nicht am Boden" in texte


def test_kulisse_in_standsicherheit_und_montage():
    """Ein Winkel auf einem Tisch (Kulisse) kippt: Der Tisch gehört nicht zur Gruppe, er ist der Boden. Ohne
    Kennzeichnung bildeten Tisch und Winkel eine Gruppe mit riesiger Standfläche, und der Tisch wäre ein Einbauschritt."""
    tisch = Box(400, 400, 50, align=UNTEN)
    winkel = Pos(0, 0, 50) * Box(10, 10, 5, align=UNTEN) + Pos(40, 0, 55) * Box(80, 10, 5, align=UNTEN)
    klotz = Pos(-100, 0, 50) * Box(40, 40, 20, align=UNTEN)
    alle = ("erklaerungen", "durchdringung", "stand", "montage")
    ks = [koerper_aus_form("Kulisse/Tisch", tisch, info={"kulisse": True}), koerper_aus_form("Winkel", winkel),
          koerper_aus_form("Klotz", klotz)]
    erg, _ = pruefe(ks, {}, {"pruefungen": alle})
    assert [b["teile"] for b in erg["befunde"] if b["art"] == "kippt"] == [["Winkel"]]
    assert not [b for b in erg["befunde"] if b["art"] == "schwebt"]
    assert erg["stand"]["auf_kulisse"] == ["Klotz", "Winkel"] and erg["stand"]["kulisse"] == ["Kulisse/Tisch"]
    assert not any("Kulisse/Tisch" in s["teile"] for s in erg["montage"]["schritte"])
    ks2 = [koerper_aus_form("Kulisse/Tisch", tisch), koerper_aus_form("Winkel", winkel),
           koerper_aus_form("Klotz", klotz)]
    erg2, _ = pruefe(ks2, {}, {"pruefungen": alle})
    assert not [b for b in erg2["befunde"] if b["art"] == "kippt"]
    assert any("Kulisse/Tisch" in s["teile"] for s in erg2["montage"]["schritte"])


MODELL_KULISSE = """from build123d import *
from kevcad import show, lager

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)
boden = Pos(0, 0, -2) * Box(400, 400, 2, align=UNTEN)
show(boden, "Kulisse/Boden", color="#D9D6CF", material="Beton", kulisse=True)
wand = lager.kulisse(Pos(0, 150, 0) * Box(400, 10, 200, align=UNTEN), "Kulisse/Wand")
show(wand, "Kulisse/Wand")
klotz = lager.druckteil(Pos(0, 0, -1) * Box(40, 40, 20, align=UNTEN), "Klotz", material="petg")
show(klotz, "Klotz")
"""


def test_kulisse_im_lauf(tmp_path):
    from kevcad_kernel.runner import Runner

    model = tmp_path / "model.py"
    model.write_text(MODELL_KULISSE, encoding="utf-8")
    frames: list = []
    r = Runner(lambda h, p=b"": frames.append(h))
    res = r.run({"run": 1, "path": str(model), "params": {}, "inventar_regel": True})
    assert res["type"] == "RUN_DONE", res.get("error")
    assert res["kulisse"] == ["Kulisse/Boden", "Kulisse/Wand"]
    assert res["inventar_verstoesse"] == []  # Kulisse ist kein Verstoß, das Material ist frei
    namen = [ln.get("name") or ln.get("benennung") for ln in res["bom"].get("lines") or []]
    assert not any("Kulisse" in str(n) for n in namen) and any("Klotz" in str(n) for n in namen)
    teile = {f["app"]["name"]: f["app"] for f in frames if f.get("type") == "PART"}
    assert teile["Kulisse/Boden"]["kulisse"] is True and "inventar" not in teile["Kulisse/Boden"]
    assert teile["Kulisse/Wand"]["kulisse"] is True and teile["Klotz"].get("inventar") == "ok"
    assert "kulisse" not in teile["Klotz"]
    # Prüfung nach dem Lauf: der Klotz steckt 1 mm im Boden (Durchdringung bleibt), keine Druckprüfung der Kulisse
    head, _ = r.pruefe(1)
    durch = [b["teile"] for b in head["befunde"] if b["art"] == "durchdringung"]
    assert durch == [["Kulisse/Boden", "Klotz"]] or durch == [["Klotz", "Kulisse/Boden"]]
    assert not any(b["art"].startswith("druck") and any("Kulisse" in t for t in b["teile"]) for b in head["befunde"])
