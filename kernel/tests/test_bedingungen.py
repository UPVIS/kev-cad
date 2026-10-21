"""Zwangsbedingungen (PLAN-BEDINGUNGEN.md): Lösen, Prüfen, Freiheitsgrade, Bewegungsraum (B8), Befestigung (B9).

Ohne Unterprozess: die API direkt mit ``sammeln()`` und ``pruefen()``, dazu der Lauf über ``Runner`` im selben Prozess.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
from build123d import Align, Axis, Box, Cylinder, GeomType, Location, Pos, Rot

from kevcad import lager
from kevcad.bedingungen import (
    BedingungsFehler,
    BezugFehler,
    abstand,
    auf,
    bezug,
    boden,
    bohrungen,
    buendig,
    drehgelenk,
    fest,
    gleich,
    in_bohrung,
    konzentrisch,
    min_wand,
    mittig,
    parallel,
    platziere,
    schiebegelenk,
    senkrecht,
    spiel,
    tangential,
    verbinde,
    winkel,
)
from kevcad_kernel.bedingungen import pruefen, sammeln
from kevcad_kernel.bedingungen.geometrie import schraube_daten

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)


def befunde(bericht: dict, pruefung: str | None = None, schwere: str | None = None) -> list[dict]:
    return [b for b in bericht["befunde"] if (pruefung is None or b["pruefung"] == pruefung)
            and (schwere is None or b["schwere"] == schwere)]


def item(bericht: dict, art: str) -> dict:
    return next(i for i in bericht["items"] if i["art"] == art)


def teil(bericht: dict, name: str) -> dict:
    return next(t for t in bericht["teile"] if t["name"] == name)


def schraube_m8(laenge: float = 30):
    return lager.teil("schraube-iso4762-m8").verbauen(laenge=laenge, name="Schraube")


# ---------------------------------------------------------------------------------------------------------------------
# Bezüge


def test_bezug_namen_und_auswahl():
    platte = Box(60, 40, 10, align=UNTEN) - Pos(10, 0, 5) * Cylinder(3, 20) - Pos(-15, 0, 5) * Cylinder(4.5, 20)
    oben = bezug(platte, "oben")
    assert oben.art == "ebene" and np.allclose(oben.d, [0, 0, 1]) and abs(oben.p[2] - 10) < 1e-9
    assert len(oben.flaechen) == 1
    assert np.allclose(bezug(platte, "vorn").d, [0, -1, 0]) and np.allclose(bezug(platte, "rechts").d, [1, 0, 0])
    with pytest.raises(BezugFehler, match="2 Bohrungen"):
        bezug(platte, "bohrung")
    b = bezug(platte, "bohrung", nahe=(-15, 0, 0))
    assert b.art == "achse" and b.innen and abs(b.r - 4.5) < 1e-9 and np.allclose(b.p[:2], [-15, 0])
    assert [round(x.r, 2) for x in bohrungen(platte)] == [4.5, 3.0]
    with pytest.raises(BezugFehler, match="Meinten Sie 'oben'"):
        bezug(platte, "obn")
    eigen = bezug(platte, "Auflage", lambda t: t.faces().sort_by(Axis.Z)[0])
    assert eigen.name == "Auflage" and np.allclose(eigen.d, [0, 0, -1])
    kugel = bezug(Pos(0, 0, 50) * Cylinder(5, 10) + Pos(0, 0, 100) * Box(1, 1, 1), "achse")
    assert kugel.art == "achse" and abs(kugel.r - 5) < 1e-9
    # Kugel hat unten keine ebene Fläche: Hüllebene
    from build123d import Sphere

    assert bezug(Pos(0, 0, 30) * Sphere(10), "unten").form == "huelle"


def test_schraube_daten_lagerteil():
    d = schraube_daten(schraube_m8(30))
    assert d.d == 8 and d.steigung == 1.25 and abs(d.laenge - 30) < 1e-6
    assert np.allclose(d.kopf.p, [0, 0, 0]) and np.allclose(d.achse.d, [0, 0, -1])


# ---------------------------------------------------------------------------------------------------------------------
# Lösen und Prüfen


def test_quader_auf_quader():
    with sammeln() as s:
        tisch = Box(100, 60, 20, align=UNTEN)
        klotz = Pos(13, 7, 50) * Rot(10, 0, 20) * Box(20, 10, 5)
        t0 = time.perf_counter()
        klotz = platziere(klotz, auf((klotz, "unten"), (tisch, "oben")))
        ms = (time.perf_counter() - t0) * 1000
        bb = klotz.bounding_box()
        # kleinste Drehung: um X zurückgekippt, die Drehung um Z bleibt
        assert abs(bb.min.Z - 20) < 1e-6 and abs(bb.max.Z - 25) < 1e-6
        b = pruefen(s, {"Tisch": tisch, "Klotz": klotz})
    assert ms < 200
    assert item(b, "auf")["stand"] == "erfuellt"
    t = teil(b, "Klotz")
    assert t["frei"] == 3 and t["stand"] == "unterbestimmt"
    texte = sorted(f["text"] for f in t["freiheitsgrade"])
    assert texte[1:] == ["Verschiebung entlang X", "Verschiebung entlang Y"] and texte[0].startswith("Drehung um Z")
    (h,) = befunde(b, "freiheitsgrade")
    assert h["schwere"] == "hinweis" and "unterbestimmt" in h["text"]
    assert not befunde(b, schwere="fehler")


def test_verletzung_mit_soll_ist_und_loesung():
    with sammeln() as s:
        tisch = Box(100, 60, 20, align=UNTEN)
        klotz = Pos(0, 0, 22) * Box(20, 10, 5, align=UNTEN)
        auf((klotz, "unten"), (tisch, "oben"))  # nur erklärt, nicht platziert: Klotz schwebt 2 mm
        b = pruefen(s, {"Tisch": tisch, "Klotz": klotz})
    i = item(b, "auf")
    assert i["stand"] == "verletzt" and i["schwere"] == "fehler" and abs(i["abweichung"] - 2) < 1e-9
    (f,) = befunde(b, "bedingung")
    assert f["soll"].startswith("Abstand 0 mm") and "Luft 2 mm" in f["ist"]
    assert "um 2 mm entlang −Z verschieben" in f["loesung"] and f["teile"] == ["Klotz", "Tisch"]
    assert f["ort"] == [0.0, 0.0, 22.0] and f["zeile"] is not None


def test_bezug_wandert_mit_dem_teil():
    """Bezug am Teil vor dem Verschieben; gezeigt wird das verschobene Teil (gleiche Geometrie, andere Lage)."""
    with sammeln() as s:
        tisch = Box(100, 60, 20, align=UNTEN)
        klotz = Box(20, 10, 5, align=UNTEN)
        klotz = platziere(klotz, auf((klotz, "unten"), (tisch, "oben")))
        rig = Pos(500, 0, 0)  # ganze Baugruppe verschoben gezeigt
        b = pruefen(s, {"Tisch": rig * tisch, "Klotz": rig * klotz})
        assert item(b, "auf")["stand"] == "erfuellt"
        b = pruefen(s, {"Tisch": rig * tisch, "Klotz": Pos(0, 0, 1) * rig * klotz})  # nachträglich von Hand bewegt
        assert item(b, "auf")["stand"] == "verletzt"


def test_welle_in_bohrung():
    with sammeln() as s:
        platte = Box(60, 40, 10, align=UNTEN) - Pos(10, 0, 5) * Cylinder(4.5, 20)
        welle = Pos(100, 50, 30) * Rot(30, 40, 0) * Cylinder(4, 50)
        unten = bezug(welle, lambda t: t.faces().filter_by(GeomType.PLANE).sort_by(Axis.Z)[0])
        welle = platziere(welle, konzentrisch((welle, "achse"), (platte, "bohrung")), buendig(unten, (platte, "unten")))
        bb = welle.bounding_box()
        assert abs(bb.min.Z) < 1e-6 and abs(bb.max.Z - 50) < 1e-6 and abs(bb.center().X - 10) < 1e-6
        sp = spiel((welle, "achse"), (platte, "bohrung"), min=0.3)
        b = pruefen(s, {"Platte": platte, "Welle": welle})
    assert all(i["stand"] == "erfuellt" for i in b["items"] if i["art"] != "spiel")
    t = teil(b, "Welle")
    assert t["frei"] == 0 and t["stand"] == "bestimmt"  # Drehung um die eigene Achse ist unkritisch
    assert any(f["unkritisch"] for f in t["freiheitsgrade"])
    i = item(b, "spiel")
    assert i["stand"] == "erfuellt" and "0,5 mm" in i["ist"]
    assert sp.min == 0.3


def test_schraube_in_bohrung_sitzt():
    with sammeln() as s:
        platte = Box(60, 40, 10, align=UNTEN) - Pos(10, 0, 5) * Cylinder(4.5, 20)
        schraube = schraube_m8(30)
        schraube = platziere(schraube, in_bohrung(schraube, bezug(platte, "bohrung")))
        bb = schraube.bounding_box()
        assert abs(bb.max.Z - 18) < 1e-3 and abs(bb.min.Z + 20) < 1e-3  # Kopf (8 hoch) liegt auf z = 10
        b = pruefen(s, {"Platte": platte, "Schraube": schraube})
    i = item(b, "in_bohrung")
    assert i["stand"] == "erfuellt" and i["schraube"]["d"] == 8


def test_schraube_in_zu_kleiner_bohrung():
    with sammeln() as s:
        platte = Box(60, 40, 10, align=UNTEN) - Pos(10, 0, 5) * Cylinder(3, 20)
        schraube = schraube_m8(30)
        schraube = platziere(schraube, in_bohrung(schraube, bezug(platte, "bohrung")))
        b = pruefen(s, {"Platte": platte, "Schraube": schraube})
    (f,) = [f for f in befunde(b, "bedingung") if f["unterart"] == "in_bohrung"]
    assert f["schwere"] == "fehler"
    assert f["soll"] == "Durchgang ≥ Ø 8 mm für M8 (mittel Ø 9 mm)" and f["ist"] == "Ø 6 mm"
    assert "Bohrung auf Ø 9 mm vergrößern" in f["loesung"] and "M5" in f["loesung"]


def test_schraube_versetzt():
    with sammeln() as s:
        platte = Box(60, 40, 10, align=UNTEN) - Pos(10, 0, 5) * Cylinder(4.5, 20)
        schraube = Pos(11.5, 0, 10) * schraube_m8(30)  # von Hand gesetzt, 1,5 mm daneben
        in_bohrung(schraube, bezug(platte, "bohrung"))
        b = pruefen(s, {"Platte": platte, "Schraube": schraube})
    (f,) = [f for f in befunde(b, "bedingung") if f["unterart"] == "in_bohrung"]
    assert f["soll"] == "Schraube mittig in der Bohrung" and f["ist"] == "Versatz 1,5 mm"
    assert "verschieben" in f["loesung"]


def test_schraube_zu_kurz_und_gewinde():
    with sammeln() as s:
        platte = Box(60, 40, 40, align=UNTEN) - Pos(10, 0, 20) * Cylinder(4.5, 50)  # 40 mm Durchgang
        schraube = schraube_m8(30)
        schraube = platziere(schraube, in_bohrung(schraube, bezug(platte, "bohrung")))
        b = pruefen(s, {"Platte": platte, "Schraube": schraube})
    (f,) = [f for f in befunde(b, "bedingung") if f["unterart"] == "in_bohrung"]
    assert "Bohrungslänge" in f["soll"] and "M8 × 48" in f["loesung"]
    with sammeln() as s:
        block = Box(40, 40, 20, align=UNTEN) - Pos(0, 0, 20) * Cylinder(3.4, 24)  # Sackloch 12 tief, Kernloch Ø 6,8
        schraube = schraube_m8(16)
        schraube = platziere(schraube, in_bohrung(schraube, bezug(block, "bohrung"), gewinde=True))
        b = pruefen(s, {"Block": block, "Schraube": schraube})
    (f,) = [f for f in befunde(b) if f["unterart"] == "in_bohrung"]
    assert "Sackloch" in f["soll"] and "kürzer" in f["loesung"]


def test_ueberbestimmt_widerspruch():
    with sammeln() as s:
        tisch = Box(100, 60, 20, align=UNTEN)
        klotz = Pos(0, 0, 40) * Box(20, 10, 5, align=UNTEN)
        b1 = auf((klotz, "unten"), (tisch, "oben"))
        b2 = abstand((klotz, "unten"), (tisch, "oben"), 5)
        klotz = platziere(klotz, b1, b2)
        b = pruefen(s, {"Tisch": tisch, "Klotz": klotz})
    (f,) = befunde(b, "widerspruch")
    assert f["schwere"] == "fehler" and "b1 (auf)" in f["text"] and "b2 (abstand)" in f["text"]
    assert teil(b, "Klotz")["stand"] == "widerspruch"


def test_falsche_bezuege_melden_sich():
    tisch = Box(100, 60, 20, align=UNTEN)
    klotz = Box(20, 10, 5)
    with pytest.raises(BedingungsFehler, match="gebraucht wird eine Ebene"):
        auf((klotz, "achse"), (tisch, "oben"))
    with pytest.raises(BedingungsFehler, match="betrifft das zu platzierende Teil nicht"):
        platziere(klotz, auf((tisch, "unten"), (tisch, "oben")))


def test_bestimmt_mit_drei_bedingungen_und_kleinste_quadrate():
    with sammeln() as s:
        tisch = Box(100, 60, 20, align=UNTEN)
        wand = Pos(0, 30, 0) * Box(100, 2, 80, align=(Align.CENTER, Align.MIN, Align.MIN))
        klotz = Pos(5, -10, 60) * Rot(5, 7, 33) * Box(20, 10, 5)
        klotz = platziere(klotz, auf((klotz, "unten"), (tisch, "oben")), auf((klotz, "hinten"), (wand, "vorn")),
                          abstand((klotz, "links"), (tisch, "links"), 10))
        b = pruefen(s, {"Tisch": tisch, "Wand": wand, "Klotz": klotz})
    assert all(i["stand"] == "erfuellt" for i in b["items"]), [i for i in b["items"] if i["stand"] != "erfuellt"]
    assert teil(b, "Klotz")["frei"] == 0
    bb = klotz.bounding_box()
    assert abs(bb.min.X + 40) < 1e-6 and abs(bb.max.Y - 30) < 1e-6 and abs(bb.min.Z - 20) < 1e-6
    with sammeln() as s:  # Winkel und Tangente gehen über kleinste Quadrate
        rolle = Pos(40, 0, 80) * Rot(0, 0, 10) * (Rot(90, 0, 0) * Cylinder(10, 30))
        rolle = platziere(rolle, tangential((rolle, "achse"), (tisch, "oben")),
                          winkel((rolle, "achse"), (tisch, "vorn"), 90))
        b = pruefen(s, {"Tisch": tisch, "Rolle": rolle})
    assert all(i["stand"] == "erfuellt" for i in b["items"])
    assert abs(rolle.bounding_box().min.Z - 20) < 1e-4


def test_parallel_senkrecht_mittig():
    with sammeln() as s:
        tisch = Box(100, 60, 20, align=UNTEN)
        stab = Pos(30, 20, 50) * Rot(20, 30, 0) * Cylinder(3, 40)
        stab = platziere(stab, senkrecht((stab, "achse"), (tisch, "oben")), mittig((stab, "mitte"), (tisch, "oben"), "xy"))
        b = pruefen(s, {"Tisch": tisch, "Stab": stab})
    assert all(i["stand"] == "erfuellt" for i in b["items"])
    c = stab.bounding_box().center()
    assert abs(c.X) < 1e-6 and abs(c.Y) < 1e-6
    with sammeln() as s:
        p = parallel((Pos(0, 0, 50) * Rot(0, 3, 0) * Box(10, 10, 10), "oben"), (tisch, "oben"))
        b = pruefen(s, {"Tisch": tisch, "Schief": p.a.teil_form})
    i = item(b, "parallel")
    assert i["stand"] == "verletzt" and i["einheit"] == "°" and abs(i["abweichung"] - 3) < 1e-6


# ---------------------------------------------------------------------------------------------------------------------
# Maßbedingungen


def test_spiel_meldet_zu_wenig_luft():
    gehaeuse = Box(50, 50, 30, align=UNTEN) - Pos(0, 0, 2) * Box(46, 46, 30, align=UNTEN)
    with sammeln() as s:
        deckel = Pos(0, 0, 2) * Box(45.8, 45.8, 3, align=UNTEN)  # 0,1 mm je Seite
        spiel(deckel, gehaeuse, min=0.2)
        b = pruefen(s, {"Gehäuse": gehaeuse, "Deckel": deckel.moved(Location((0, 0, 0.1)))})
    i = item(b, "spiel")
    assert i["stand"] == "verletzt" and i["ist"] == "0,1 mm" and abs(i["abweichung"] + 0.1) < 1e-6
    (f,) = befunde(b, "bedingung")
    assert f["soll"] == "≥ 0,2 mm" and "0,1 mm mehr Luft" in f["loesung"]
    with sammeln() as s:
        deckel = Pos(0, 0, 2.3) * Box(45.4, 45.4, 3, align=UNTEN)
        spiel(deckel, gehaeuse, min=0.2)
        assert item(pruefen(s, {"Gehäuse": gehaeuse, "Deckel": deckel}), "spiel")["stand"] == "erfuellt"


def test_gleich_und_min_wand():
    from kevcad_kernel.tessellate import tessellate_shape

    rohr = Cylinder(10, 40) - Cylinder(9.2, 42)  # Wand 0,8
    with sammeln() as s:
        s.params["innen"] = 18.4
        gleich("innen", bezug(rohr, "bohrung"))
        gleich(18.4, 18.5)
        min_wand(rohr, 1.2)
        g = tessellate_shape(rohr).geometry
        b = pruefen(s, {"Rohr": rohr}, netze={"Rohr": (g.positions, g.triangles, g.normals)})
    stände = [i["stand"] for i in b["items"] if i["art"] == "gleich"]
    assert stände == ["erfuellt", "verletzt"]
    i = item(b, "min_wand")
    assert i["stand"] == "verletzt" and abs(float(i["ist"].split()[0].replace(",", ".")) - 0.8) < 0.15


# ---------------------------------------------------------------------------------------------------------------------
# Gelenke und Bewegungsraum (B8)


def _klappe():
    """Klappe (41 mm lang) dreht um eine Achse bei x = −50, z = 15 über einer Grundplatte (Oberkante z = 10); eine
    Stütze bei x = −30 oben (z ≥ 40) liegt im Weg nach oben (ab etwa 50°), die Grundplatte im Weg nach unten."""
    rahmen = Box(100, 20, 10, align=UNTEN) + Pos(-30, 0, 40) * Box(4, 20, 20, align=UNTEN)
    lager_ = Pos(-50, 0, 15) * Rot(90, 0, 0) * Cylinder(3, 20)
    klappe = Pos(-27, 0, 15) * Box(36, 18, 2) + Pos(-50, 0, 15) * Rot(90, 0, 0) * (Cylinder(5, 18) - Cylinder(3.2, 20))
    return rahmen, lager_, klappe


def test_drehgelenk_mit_bereich_und_bewegungsraum():
    rahmen, achse, klappe = _klappe()
    with sammeln() as s:
        g = drehgelenk((klappe, "bohrung"), (achse, "achse"), winkel=0, bereich=(-60, 90), bedienung="finger")
        klappe = platziere(klappe, g)
        b = pruefen(s, {"Rahmen": rahmen, "Achse": achse, "Klappe": klappe})
    i = item(b, "drehgelenk")
    assert i["stand"] == "erfuellt" and i["gelenk"] == "revolute" and i["bereich"] == [-60.0, 90.0]
    assert i["achse"]["d"] in ([0, 1, 0], [0, -1, 0]) or abs(abs(i["achse"]["d"][1]) - 1) < 1e-9
    assert teil(b, "Klappe")["gelenke"] and teil(b, "Klappe")["frei"] == 0
    (bew,) = b["bewegungen"]
    assert bew["art"] == "drehen" and [k["gegen"] for k in bew["kollisionen"]] == ["Rahmen"]
    (k,) = bew["kollisionen"]
    unten, oben = k["bereiche"]
    assert unten[0] == -60 and -20 <= unten[1] <= -5 and 40 <= oben[0] <= 60 and oben[1] < 90
    lo, hi = bew["frei_um_ist"]
    assert -20 <= lo <= 0 <= hi and 30 <= hi <= 50
    stoss = [f for f in befunde(b, "bewegungsraum") if "stößt" in f["text"]]
    assert stoss and stoss[0]["teile"] == ["Klappe", "Rahmen"] and "frei" in stoss[0]["ist"]
    eng = [f for f in befunde(b, "bewegungsraum") if "Platz" in f["text"]]
    assert eng and "Freiraum 15 mm" in eng[0]["text"]  # Finger passen nicht zwischen Klappe und Grundplatte
    assert g.fuer_animation()["art"] == "dreh" and g.fuer_animation()["grenzen"] == (-60.0, 90.0)
    # zweiter Lauf mit gleicher Geometrie: Bewegungsraum aus dem Zwischenspeicher
    with sammeln() as s2:
        rahmen, achse, klappe2 = _klappe()
        g2 = drehgelenk((klappe2, "bohrung"), (achse, "achse"), bereich=(-60, 90), bedienung="finger")
        klappe2 = platziere(klappe2, g2)
        b2 = pruefen(s2, {"Rahmen": rahmen, "Achse": achse, "Klappe": klappe2})
    assert b2["bewegungen"][0]["frei"] == bew["frei"]


def test_gelenkwert_und_joints():
    rahmen, achse, klappe = _klappe()
    with sammeln() as s:
        g = drehgelenk((klappe, "bohrung"), (achse, "achse"), winkel=30, bereich=(0, 120), weg_pruefen=False)
        k30 = platziere(klappe, g)
        b = pruefen(s, {"Achse": achse, "Klappe": k30})
    assert item(b, "drehgelenk")["stand"] == "erfuellt"
    # dasselbe über build123d-Joints: RevoluteJoint am festen Teil, RigidJoint am bewegten
    k = klappe.moved(Location())
    j = g.als_joints(achse, k)
    j.setze(30)
    assert np.allclose([*k.bounding_box().min], [*k30.bounding_box().min], atol=1e-6)
    with sammeln() as s:  # Wert außerhalb des Bereichs
        g = drehgelenk((klappe, "bohrung"), (achse, "achse"), winkel=150, bereich=(0, 120), weg_pruefen=False)
        k150 = platziere(klappe, g)
        b = pruefen(s, {"Achse": achse, "Klappe": k150})
    assert item(b, "drehgelenk")["stand"] == "verletzt"


def test_schiebegelenk():
    schiene = Box(200, 20, 10, align=UNTEN)
    with sammeln() as s:
        wagen = Pos(30, 40, 30) * Box(30, 20, 10, align=UNTEN)
        fuehrung = bezug(schiene, "Führung", Axis((0, 0, 10), (1, 0, 0)))
        unterseite = bezug(wagen, "Führung", Axis((30, 40, 30), (1, 0, 0)))
        g = schiebegelenk(unterseite, fuehrung, weg=50, bereich=(-80, 80))
        wagen = platziere(wagen, g)
        b = pruefen(s, {"Schiene": schiene, "Wagen": wagen})
    assert item(b, "schiebegelenk")["stand"] == "erfuellt"
    assert abs(wagen.bounding_box().center().X - 80) < 1e-6 and abs(wagen.bounding_box().min.Z - 10) < 1e-6
    assert teil(b, "Wagen")["frei"] == 0


# ---------------------------------------------------------------------------------------------------------------------
# Befestigung (B9)


def _zwei_platten(bohrung_unten: float = 4.5):
    oben = Pos(0, 0, 10) * Box(40, 40, 5, align=UNTEN) - Pos(0, 0, 12) * Cylinder(4.5, 10)
    unten = Box(40, 40, 10, align=UNTEN) - Pos(0, 0, 5) * Cylinder(bohrung_unten, 12)
    return oben, unten


def test_verbinde_schraube_mit_mutter():
    oben, unten = _zwei_platten()
    with sammeln() as s:
        schraube = schraube_m8(25)
        schraube = platziere(schraube, in_bohrung(schraube, bezug(oben, "bohrung")))
        mutter = lager.teil("mutter-iso4032-m8").verbauen(name="Mutter")
        mutter = Pos(0, 0, 0) * Rot(180, 0, 0) * mutter  # unter die untere Platte
        mb = mutter.bounding_box()
        mutter = Pos(0, 0, -mb.max.Z) * mutter
        verbinde(oben, unten, art="schraube", mit=[schraube, mutter])
        verbinde(unten, boden, art="aufliegen")
        b = pruefen(s, {"Oben": oben, "Unten": unten, "Schraube": schraube, "Mutter": mutter})
    v = [i for i in b["items"] if i["art"] == "verbinde"]
    assert v[0]["stand"] == "erfuellt", v[0]
    assert teil(b, "Oben")["befestigt"] and teil(b, "Oben")["am_boden"]
    assert not befunde(b, "befestigung", "fehler"), befunde(b, "befestigung")
    with sammeln() as s:  # ohne Mutter
        schraube = schraube_m8(25)
        schraube = platziere(schraube, in_bohrung(schraube, bezug(oben, "bohrung")))
        verbinde(oben, unten, art="schraube", mit=[schraube])
        b = pruefen(s, {"Oben": oben, "Unten": unten, "Schraube": schraube})
    (f,) = [f for f in befunde(b, "befestigung") if f["bedingung"]]
    assert "es fehlt eine Mutter" in f["text"] and f["schwere"] == "fehler"


def test_nicht_befestigt_und_nicht_am_boden():
    with sammeln() as s:
        tisch = Box(100, 60, 20, align=UNTEN)
        a = Pos(0, 0, 100) * Box(10, 10, 10, align=UNTEN)
        bb = Pos(0, 0, 110) * Box(10, 10, 10, align=UNTEN)
        lose = Pos(0, 0, 300) * Box(10, 10, 10, align=UNTEN)
        auf((bb, "unten"), (a, "oben"))  # b auf a, a hängt in der Luft
        konzentrisch((lose, "achse_z"), (tisch, "achse_z"))  # beteiligt, aber keine Befestigung
        b = pruefen(s, {"Tisch": tisch, "A": a, "B": bb, "Lose": lose})
    texte = [f["text"] for f in befunde(b, "befestigung", "fehler")]
    assert any("Lose ist nicht befestigt" in t for t in texte)
    assert any(t.startswith("Nicht am Boden") and "A" in t and "B" in t for t in texte)


def test_modell_ohne_bedingungen_nur_hinweis():
    with sammeln() as s:
        b = pruefen(s, {"A": Box(1, 1, 1), "B": Pos(5, 0, 0) * Box(1, 1, 1)})
    (f,) = b["befunde"]
    assert f["pruefung"] == "befestigung" and f["schwere"] == "hinweis" and f["teile"] == ["A", "B"]
    assert b["summe"]["fehler"] == 0 and b["pruef_ms"] < 50


def test_ohne_angabe_wird_fehler_sobald_verbinde_genutzt():
    """Kevin, 22.10.2026: fehlende Befestigung ist ein Hinweis, bis das Modell verbinde(…) nutzt, danach ein Fehler."""
    tisch = Box(100, 60, 20, align=UNTEN)
    frei = Pos(30, 0, 20) * Box(10, 10, 10, align=UNTEN)
    with sammeln() as s:
        verbinde(tisch, boden, art="aufliegen")
        b = pruefen(s, {"Tisch": tisch, "Frei": frei})
    (f,) = [f for f in befunde(b, "befestigung") if "ohne Angabe" in f["text"]]
    assert f["schwere"] == "fehler" and f["teile"] == ["Frei"]
    with sammeln() as s:  # nur Montagebedingungen, kein verbinde: weiter nur Hinweis
        auf((frei, "unten"), (tisch, "oben"))
        b = pruefen(s, {"Tisch": tisch, "Frei": frei})
    assert not [f for f in befunde(b, "befestigung", "fehler") if "ohne Angabe" in f["text"]]


def test_fest_und_bericht_json():
    with sammeln() as s:
        grund = Box(50, 50, 10, align=UNTEN)
        griff = Pos(0, 0, 10) * Box(10, 10, 30, align=UNTEN)
        fest(griff, grund)
        b = pruefen(s, {"Grund": grund, "Griff": griff})
        assert item(b, "fest")["stand"] == "erfuellt"
        b2 = pruefen(s, {"Grund": grund, "Griff": Pos(1, 0, 0) * griff})
        assert item(b2, "fest")["stand"] == "verletzt"
    from kevcad_kernel.bedingungen.lauf import json_tauglich

    json.dumps(json_tauglich(b))


# ---------------------------------------------------------------------------------------------------------------------
# Lauf (runner.py) mit param-Grenzen


def _lauf(tmp_path: Path, code: str, params: dict | None = None) -> dict:
    from kevcad_kernel.runner import Runner

    model = tmp_path / "model.py"
    model.write_text(code, encoding="utf-8")
    frames: list = []
    r = Runner(lambda h, p=b"": frames.append(h))
    return r.run({"run": 1, "path": str(model), "params": params or {}, "inventar_regel": False})


def test_lauf_param_grenze_und_bericht(tmp_path):
    code = """from build123d import *
from kevcad import param, show
from kevcad.bedingungen import *

wand = param("wand", 2.0, min=1.2)
tisch = Box(100, 60, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
klotz = Box(20, 10, wand)
klotz = platziere(klotz, auf((klotz, "unten"), (tisch, "oben")), mittig((klotz, "mitte"), (tisch, "mitte"), "xy"),
                  parallel((klotz, "vorn"), (tisch, "vorn")))
show(tisch, "Tisch")
show(klotz, "Klotz")
"""
    res = _lauf(tmp_path, code)
    assert res["type"] == "RUN_DONE"
    rep = res["bedingungen"]
    assert rep["summe"]["fehler"] == 0 and rep["summe"]["verletzt"] == 0
    assert next(i for i in rep["items"] if i["art"] == "param")["stand"] == "erfuellt"
    assert next(t for t in rep["teile"] if t["name"] == "Klotz")["frei"] == 0
    json.dumps(rep)
    res = _lauf(tmp_path, code, {"wand": 0.8})
    rep = res["bedingungen"]
    (f,) = [f for f in rep["befunde"] if f["pruefung"] == "parameter"]
    assert f["schwere"] == "fehler" and f["ist"] == "0,8" and f["soll"] == "≥ 1,2" and f["zeile"] == 5
    assert "wand mindestens 1,2" in f["loesung"]
    assert any("Minimum" in w for w in res["warnings"])  # wie bisher


def test_gelenk_fuer_animation(tmp_path):
    """Achse und Grenzen des Gelenks passen zu animation.gelenk (Werte ab der Ruhelage aus model.py)."""
    rahmen, achse, klappe = _klappe()
    g = drehgelenk((klappe, "bohrung"), (achse, "achse"), winkel=10, bereich=(0, 90), weg_pruefen=False)
    platziere(klappe, g)
    a = g.fuer_animation()
    assert a["art"] == "dreh" and a["grenzen"] == (-10.0, 80.0)
    assert np.allclose(a["achse"][0], (-50, 0, 15)) and abs(abs(a["achse"][1][1]) - 1) < 1e-9
    verschoben = g.fuer_animation(lage=Pos(0, 100, 0))
    assert np.allclose(verschoben["achse"][0], (-50, 100, 15))
    code = """from build123d import *
from kevcad import animation, show
import kevcad.bedingungen as bed

unten = (Align.CENTER, Align.CENTER, Align.MIN)
achse = Pos(-50, 0, 15) * Rot(90, 0, 0) * Cylinder(3, 20)
klappe = Pos(-27, 0, 15) * Box(36, 18, 2) + Pos(-50, 0, 15) * Rot(90, 0, 0) * (Cylinder(5, 18) - Cylinder(3.2, 20))
g = bed.drehgelenk((klappe, "bohrung"), (achse, "achse"), bereich=(0, 90), weg_pruefen=False)
klappe = bed.platziere(klappe, g)
show(achse, "Achse")
show(klappe, "Klappe")
anim = animation(2, name="Auf")
anim.gelenk("Klappe", **g.fuer_animation(), werte={0: 0, 2: 60})
"""
    res = _lauf(tmp_path, code)
    assert res["type"] == "RUN_DONE", res.get("error")
    assert res.get("animations") == ["Auf"]


def test_lauf_ohne_bedingungen_kostet_nichts(tmp_path):
    code = "from build123d import *\nfrom kevcad import show\nfor i in range(30):\n" \
           "    show(Pos(i * 20, 0, 0) * Box(10, 10, 10), f'Teil {i}')\n"
    res = _lauf(tmp_path, code)
    assert res["bedingungen"]["pruef_ms"] < 20
    assert res["bedingungen"]["summe"]["gesamt"] == 0


def test_bewegungen_json(tmp_path):
    from kevcad_kernel.bedingungen import Sammlung

    rahmen, achse, klappe = _klappe()
    (tmp_path / "bewegungen.json").write_text(json.dumps([
        {"name": "Klappe", "teile": ["Klappe"], "art": "drehen", "punkt": [-50, 0, 15], "richtung": [0, 1, 0],
         "von": -60, "bis": 60, "schritte": 12}]), encoding="utf-8")
    b = pruefen(Sammlung(), {"Rahmen": rahmen, "Achse": achse, "Klappe": klappe}, projekt=tmp_path)
    (bew,) = b["bewegungen"]
    assert bew["quelle"] == "bewegungen.json" and bew["kollisionen"]
    assert any(f["pruefung"] == "bewegungsraum" and f["schwere"] == "fehler" for f in b["befunde"])
    _ = math
