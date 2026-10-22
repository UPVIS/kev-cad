"""Tests der Druckprüfung (kevcad_kernel.druck): eigene Testformen, je ein typischer Konstruktionsfehler."""

from __future__ import annotations

import math
import time

import pytest
from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    Circle,
    Compound,
    Cylinder,
    GeomType,
    Plane,
    Polygon,
    Pos,
    Rot,
    Sphere,
    chamfer,
    extrude,
    fillet,
)
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from kevcad_kernel.druck import (
    MATERIALIEN,
    P1P,
    SCHWEREN,
    als_warnungen,
    einsatz,
    kernloch,
    material,
    muttertasche,
    pruefe_druckteil,
    schnapp_auslenkung,
)

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)


# ---------------------------------------------------------------------------------------------------------------------
# Testformen
# ---------------------------------------------------------------------------------------------------------------------


def winkel_60():
    """Winkel: senkrechte Wand, darüber ein Arm, dessen Unterseite 60° von der Senkrechten überhängt."""
    t = math.tan(math.radians(60))
    pts = [(0, 0), (10, 0), (10, 10), (10 + 15 * t, 25), (10 + 15 * t, 30), (0, 30)]
    return extrude(Plane.XZ * Polygon(*pts, align=None), amount=-20)


def kasten_06():
    """Offener Kasten 40 × 30 × 20 mit 0,6-mm-Wänden und 1,2-mm-Boden."""
    aussen = Box(40, 30, 20, align=UNTEN)
    return aussen - Pos(0, 0, 1.2) * Box(38.8, 28.8, 20, align=UNTEN)


def bohrung_5():
    """Block mit waagrechter Ø5-Bohrung entlang Y."""
    return Box(30, 20, 15, align=UNTEN) - Pos(0, 0, 7.6) * Rot(90, 0, 0) * Cylinder(2.5, 30)


def tropfen_5():
    """Wie bohrung_5, aber als Tropfenform mit 45°-Spitze nach oben."""
    r = 2.5
    q = r / math.sqrt(2)
    profil = Circle(r) + Polygon((-q, q), (0, r * math.sqrt(2)), (q, q), (0, 0), align=None)
    return Box(30, 20, 15, align=UNTEN) - extrude(Plane.XZ * Pos(0, 7.6) * profil, amount=30, both=True)


def gutes_teil():
    """Block mit Bettfase, verrundeten Ecken und oberen Kanten, Durchgangsbohrung M6 (6,6) mit Fase unten."""
    b = Box(40, 30, 15, align=UNTEN)
    b = fillet(b.edges().filter_by(Axis.Z), 3)
    b = chamfer(b.edges().group_by(Axis.Z)[0], 0.5)
    b = fillet(b.edges().group_by(Axis.Z)[-1], 1)
    b -= Cylinder(3.3, 40)
    unten = b.edges().filter_by(GeomType.CIRCLE).filter_by(lambda e: abs(e.radius - 3.3) < 1e-6).group_by(Axis.Z)[0]
    return chamfer(unten, 0.4)


def senkung_unten(opfer: bool = False):
    """Zylinderkopf-Senkung Ø11 × 3,4 von der Bettseite, Bohrung Ø6,6; optional mit Opferschicht."""
    b = Box(30, 30, 10, align=UNTEN)
    b -= Pos(0, 0, -1) * Cylinder(5.5, 4.4, align=UNTEN)
    return b - Pos(0, 0, 3.4 + (0.2 if opfer else -0.5)) * Cylinder(3.3, 20, align=UNTEN)


def kanaele():
    """Zwei waagrechte Kanäle: 8 mm (überbrückbar) und 24 mm (zu lang für PETG)."""
    b = Box(60, 30, 12, align=UNTEN)
    b -= Pos(-18, 0, 2) * Box(8, 50, 6, align=UNTEN)
    return b - Pos(10, 0, 2) * Box(24, 50, 6, align=UNTEN)


def t_profil():
    return Box(6, 20, 20, align=UNTEN) + Pos(0, 0, 20) * Box(30, 20, 4, align=UNTEN)


# ---------------------------------------------------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------------------------------------------------


def arten(r, schwere=None):
    return [h["art"] for h in r["hinweise"] if schwere is None or h["schwere"] == schwere]


def finde(r, art):
    treffer = [h for h in r["hinweise"] if h["art"] == art]
    assert treffer, f"kein Hinweis {art}: {[(h['art'], h['befund']) for h in r['hinweise']]}"
    return treffer[0]


def abstand_zur_flaeche(form, index, punkt):
    from build123d import Vector
    return form.faces()[index].distance_to(Vector(*punkt))


# ---------------------------------------------------------------------------------------------------------------------
# Die fünf Pflichtfälle
# ---------------------------------------------------------------------------------------------------------------------


def test_winkel_60_grad_ueberhang():
    form = winkel_60()
    r = pruefe_druckteil(form, "petg", ausrichtung="-z")
    h = finde(r, "ueberhang")
    assert h["schwere"] == "warnung"
    assert h["werte"]["winkel"] == pytest.approx(60, abs=1)
    assert h["werte"]["flaeche_mm2"] == pytest.approx(30 * 20 * math.sin(math.radians(60)), rel=0.02)
    n = form.faces()[h["flaeche"]].normal_at()
    assert n.Z == pytest.approx(-math.sin(math.radians(60)), abs=1e-3)   # die schräge Unterseite
    assert abstand_zur_flaeche(form, h["flaeche"], h["punkt"]) < 0.5
    assert r["kennzahlen"]["stuetzflaeche_mm2"] > 500
    assert "abschrägen" in h["text"] and h["text"].startswith("Überhang")


def test_winkel_60_bei_pla_noch_ohne_stuetze():
    r = pruefe_druckteil(winkel_60(), "pla", ausrichtung="-z")
    assert "ueberhang" not in arten(r)   # PLA auf dem P1P: bis 60° (Stützenschwelle 30° vom Waagrechten)


def test_winkel_automatisch_ohne_stuetze():
    form = winkel_60()
    r = pruefe_druckteil(form, "petg")
    a = r["ausrichtung"]
    assert a["automatisch"] and r["kennzahlen"]["stuetzflaeche_mm2"] == 0
    assert "ueberhang" not in arten(r)
    assert a["liegt_auf"] is not None and "Stützfläche" in a["begruendung"]
    # Die Drehung legt genau diese Fläche aufs Bett
    gedreht = Rot(*a["drehung"]) * form
    unten = gedreht.faces().sort_by(Axis.Z)[0]
    assert unten.normal_at().Z == pytest.approx(-1, abs=1e-6)
    assert unten.area == pytest.approx(form.faces()[a["liegt_auf"]].area, rel=1e-6)
    # gedreht und „wie modelliert“ geprüft: ebenfalls ohne Überhang
    assert "ueberhang" not in arten(pruefe_druckteil(gedreht, "petg", ausrichtung="-z"))


def test_kasten_mit_06_wand():
    form = kasten_06()
    r = pruefe_druckteil(form, "petg")
    assert r["ausrichtung"]["unten"] == [0.0, 0.0, -1.0]   # Öffnung oben bleibt
    h = finde(r, "wand")
    assert h["schwere"] == "warnung"
    assert h["werte"]["dicke"] == pytest.approx(0.6, abs=0.05)
    assert len(h["flaechen"]) >= 8                          # 4 Außen- und 4 Innenwände
    assert abstand_zur_flaeche(form, h["flaeche"], h["punkt"]) < 0.1 or any(
        abstand_zur_flaeche(form, f, h["punkt"]) < 0.1 for f in h["flaechen"])
    assert "0,83" in h["abhilfe"] and "2 Bahnen" in h["abhilfe"]


def test_waagrechte_bohrung_5():
    form = bohrung_5()
    r = pruefe_druckteil(form, "petg", ausrichtung="-z")
    h = finde(r, "waagrechte_bohrung")
    assert h["schwere"] == "warnung"
    assert h["werte"]["durchmesser"] == pytest.approx(5.0)
    assert "Tropfenform" in h["abhilfe"]
    assert form.faces()[h["flaeche"]].geom_type == GeomType.CYLINDER
    assert h["punkt"][2] > 7.6 + 2.0                           # oben in der Bohrung
    assert "bohrung_mass" in arten(r, "hinweis")               # Ø 5,0 ist ein Nennmaß


def test_waagrechte_bohrung_automatisch_senkrecht():
    r = pruefe_druckteil(bohrung_5(), "petg")
    assert "waagrechte_bohrung" not in arten(r)
    assert abs(r["ausrichtung"]["unten"][1]) == pytest.approx(1.0)     # auf die Y-Seite gelegt
    assert "waagrechte Bohrungen von 1 auf 0" in r["ausrichtung"]["begruendung"]


def test_tropfenform_wird_nicht_bemaengelt():
    r = pruefe_druckteil(tropfen_5(), "petg", ausrichtung="-z")
    assert "waagrechte_bohrung" not in arten(r) and "ueberhang" not in arten(r)


def test_teil_groesser_als_bauraum():
    r = pruefe_druckteil(Box(400, 60, 30, align=UNTEN), "petg")
    h = finde(r, "bauraum")
    assert h["schwere"] == "fehler" and not r["ok"]
    assert "256" in h["befund"] and "teilen" in h["abhilfe"]
    assert r["kennzahlen"]["bauraum_ausnutzung_prozent"] > 100


def test_teil_passt_nur_diagonal():
    r = pruefe_druckteil(Box(300, 40, 20, align=UNTEN), "petg")
    assert r["ok"]
    h = finde(r, "bauraum")
    assert h["schwere"] == "hinweis" and "diagonal" in h["befund"]


def test_gutes_teil_ohne_hinweise():
    r = pruefe_druckteil(gutes_teil(), "petg")
    assert r["hinweise"] == [], [h["text"] for h in r["hinweise"]]
    assert r["ok"] and r["zusammenfassung"].startswith("druckbar ohne Hinweise")
    assert r["ausrichtung"]["unten"] == [0.0, 0.0, -1.0] and r["ausrichtung"]["drehung"] == [0.0, 0.0, 0.0]
    k = r["kennzahlen"]
    assert k["hoehe_mm"] == pytest.approx(15) and k["schichten"] == 75 and k["stuetzflaeche_mm2"] == 0
    assert k["auflageflaeche_mm2"] > 900 and k["masse_voll_g"] > 0


# ---------------------------------------------------------------------------------------------------------------------
# Weitere Regeln
# ---------------------------------------------------------------------------------------------------------------------


def test_gegenbohrung_von_unten_und_opferschicht():
    r = pruefe_druckteil(senkung_unten(), "petg", ausrichtung="-z")
    h = finde(r, "gegenbohrung_unten")
    assert h["schwere"] == "warnung" and h["werte"]["laenge"] == pytest.approx(2.2, abs=0.3)
    assert "Opferschicht" in h["abhilfe"]
    r2 = pruefe_druckteil(senkung_unten(opfer=True), "petg", ausrichtung="-z")
    assert "gegenbohrung_unten" not in arten(r2)
    assert "opferschicht" in arten(r2, "hinweis") and "wand" not in arten(r2)


def test_bruecken():
    r = pruefe_druckteil(kanaele(), "petg", ausrichtung="-z")
    bruecken = [h for h in r["hinweise"] if h["art"] == "bruecke"]
    assert len(bruecken) == 1                                     # 8 mm ist unkritisch
    assert bruecken[0]["schwere"] == "warnung"
    assert bruecken[0]["werte"]["spannweite"] == pytest.approx(24, abs=1.5)
    # PLA darf weiter (bis ca. 30 mm): nur noch ein Hinweis
    r2 = pruefe_druckteil(kanaele(), "pla", ausrichtung="-z")
    assert [h["schwere"] for h in r2["hinweise"] if h["art"] == "bruecke"] == ["hinweis"]


def test_kragarm():
    r = pruefe_druckteil(t_profil(), "petg", ausrichtung="-z")
    krag = [h for h in r["hinweise"] if h["art"] == "kragarm"]
    assert len(krag) == 2 and all(h["werte"]["laenge"] == pytest.approx(12, abs=0.6) for h in krag)


def test_rundung_an_der_bettkante():
    form = fillet(Box(40, 30, 10, align=UNTEN).edges().group_by(Axis.Z)[0], 3)
    h = finde(pruefe_druckteil(form, "petg", ausrichtung="-z"), "rundung_unten")
    assert h["schwere"] == "warnung" and h["werte"]["radius"] == pytest.approx(3)
    assert "Fase" in h["abhilfe"]


def test_elefantenfuss_bei_scharfer_unterkante():
    h = finde(pruefe_druckteil(Box(20, 20, 10, align=UNTEN), "pla"), "elefantenfuss")
    assert h["schwere"] == "hinweis" and h["werte"]["kantenlaenge"] == pytest.approx(80, rel=0.01)


def test_verzug_abs_aber_nicht_pla():
    platte = Box(150, 80, 4, align=UNTEN)
    r = pruefe_druckteil(platte, "abs")
    assert finde(r, "verzug")["schwere"] == "warnung"
    assert finde(r, "verzug_ecken")["werte"]["anzahl"] == 4
    r2 = pruefe_druckteil(fillet(platte.edges().filter_by(Axis.Z), 5), "abs")
    assert "verzug_ecken" not in arten(r2)
    assert not {"verzug", "verzug_ecken"} & set(arten(pruefe_druckteil(platte, "pla")))


def test_kleine_bohrung_stift_und_schichtraster():
    b = Box(30, 20, 2.5, align=UNTEN)
    b -= Pos(-8, 0, 0) * Cylinder(0.75, 10)
    b += Pos(8, 0, 2.4) * Cylinder(0.9, 8, align=UNTEN)
    r = pruefe_druckteil(b, "pla", ausrichtung="-z")
    assert finde(r, "bohrung_klein")["schwere"] == "warnung"
    s = finde(r, "stift")
    assert s["schwere"] == "warnung" and "Schichten" in s["befund"]
    z = finde(r, "schichtraster")
    assert 2.5 in z["werte"]["hoehen"] and "2,40" in z["abhilfe"]
    assert "bohrung_mass" not in arten(r)                          # schon als zu klein gemeldet


def test_winzige_bohrung_ist_fehler():
    r = pruefe_druckteil(Box(10, 10, 5, align=UNTEN) - Cylinder(0.4, 20), "pla")
    assert finde(r, "bohrung_klein")["schwere"] == "fehler" and not r["ok"]


def test_kugel_liegt_auf_einem_punkt():
    r = pruefe_druckteil(Sphere(15), "pla")
    assert finde(r, "auflage")["schwere"] == "warnung"
    assert finde(r, "ueberhang")["werte"]["winkel"] > 75


def test_keil_meldet_keine_duenne_wand():
    keil = extrude(Plane.XZ * Polygon((0, 0), (30, 0), (30, 17.32), align=None), amount=-20)
    assert "wand" not in arten(pruefe_druckteil(keil, "pla", ausrichtung="-z"))


def test_duenne_waagrechte_platte():
    r = pruefe_druckteil(Box(30, 30, 0.2, align=UNTEN) + Box(4, 4, 6, align=UNTEN), "pla", ausrichtung="-z")
    h = finde(r, "wand")
    assert h["schwere"] == "warnung" and "1 Schicht" in h["befund"]


def test_kein_harzdruck():
    r = pruefe_druckteil(Box(20, 20, 10, align=UNTEN), "harz")
    assert r["material"] == "harz-standard" and not r["ok"]
    assert finde(r, "material")["schwere"] == "fehler" and "P1P" in finde(r, "material")["befund"]
    assert "elefantenfuss" not in arten(r) and r["kennzahlen"]["bauraum_ausnutzung_prozent"] is None


def test_material_passt_zum_offenen_p1p():
    teil = gutes_teil()
    for mat in ("pla", "petg", "tpu"):
        assert "material" not in arten(pruefe_druckteil(teil, mat))
    for mat in ("abs", "asa", "pc-filament", "pa"):
        h = finde(pruefe_druckteil(teil, mat), "material")
        assert h["schwere"] == "warnung" and "Einhausung" in h["abhilfe"] and "PLA oder PETG" in h["abhilfe"]
    duese = [h for h in pruefe_druckteil(teil, "pla-cf")["hinweise"] if h["art"] == "material"]
    assert len(duese) == 1 and "gehärtete Düse" in duese[0]["befund"]
    assert len([h for h in pruefe_druckteil(teil, "pa-cf")["hinweise"] if h["art"] == "material"]) == 2


def test_sperrbereich_und_druckhoehe():
    # 250 × 240 passt auf 256 × 256, aber nicht neben den Sperrbereich 18 × 28 vorne links
    r = pruefe_druckteil(Box(250, 240, 10, align=UNTEN), "pla", "-z")
    assert finde(r, "bauraum")["schwere"] == "fehler" and "gesperrt" in finde(r, "bauraum")["befund"]
    assert pruefe_druckteil(Box(236, 240, 10, align=UNTEN), "pla", "-z")["ok"]       # rechts daneben frei
    r2 = pruefe_druckteil(Box(40, 40, 253, align=UNTEN), "pla", "-z")
    assert finde(r2, "bauraum")["schwere"] == "fehler" and "zu hoch" in finde(r2, "bauraum")["befund"]


# ---------------------------------------------------------------------------------------------------------------------
# Eingaben, Ausgabe, Nebenwirkungen
# ---------------------------------------------------------------------------------------------------------------------


def test_ausrichtung_als_rot_vektor_flaeche_gleich():
    b = Box(30, 20, 10, align=UNTEN) - Pos(0, 0, 5) * Rot(90, 0, 0) * Cylinder(3, 30)
    r1 = pruefe_druckteil(b, "petg", Rot(90, 0, 0))
    r2 = pruefe_druckteil(b, "petg", (0, -1, 0))
    r3 = pruefe_druckteil(b, "petg", "-y")
    r4 = pruefe_druckteil(b, "petg", r1["ausrichtung"]["liegt_auf"])
    assert r1["ausrichtung"]["unten"] == r2["ausrichtung"]["unten"] == r3["ausrichtung"]["unten"] \
        == r4["ausrichtung"]["unten"] == [0.0, -1.0, 0.0]
    assert not r1["ausrichtung"]["automatisch"]
    with pytest.raises(ValueError):
        pruefe_druckteil(b, "petg", "schräg")


def test_eingabeformen_und_material():
    with BuildPart() as bp:
        Box(20, 20, 10)
    assert pruefe_druckteil(bp, "nylon")["material"] == "pa"
    zwei = Compound([Box(20, 20, 10, align=UNTEN), Pos(40, 0, 0) * Box(20, 20, 10, align=UNTEN)])
    assert pruefe_druckteil(zwei, "PLA")["kennzahlen"]["auflageflaeche_mm2"] == pytest.approx(800)
    with pytest.raises(ValueError, match="Unbekanntes Druckmaterial"):
        pruefe_druckteil(Box(10, 10, 10), "stahl")
    assert {m for m in MATERIALIEN} == {"pla", "pla-cf", "petg", "abs", "asa", "pc-filament", "pa", "pa-cf",
                                        "tpu-95a", "harz-standard"}


def test_hinweisformat_und_warnungen():
    form = bohrung_5()
    r = pruefe_druckteil(form, "petg", ausrichtung="-z")
    n = len(form.faces())
    for h in r["hinweise"]:
        assert h["schwere"] in SCHWEREN
        assert h["text"] == f"{h['befund']}. Abhilfe: {h['abhilfe']}."
        assert h["flaeche"] is None or 0 <= h["flaeche"] < n
        assert all(0 <= f < n for f in h["flaechen"])
        assert h["punkt"] is None or len(h["punkt"]) == 3
    zeilen = als_warnungen(r)
    assert zeilen and zeilen[0].startswith("Druck Warnung: waagrechte Bohrung") and "#f" in zeilen[0]
    assert len(als_warnungen(r, mit_hinweisen=True)) == len(r["hinweise"])
    assert r["druckhinweise"] and any("Düse" in z for z in r["druckhinweise"])


def test_ergebnis_ist_json():
    import json
    for form in (bohrung_5(), senkung_unten(), Sphere(10)):
        for mat in ("petg", "abs", "harz"):
            json.dumps(pruefe_druckteil(form, mat), allow_nan=False)


def test_originalform_bleibt_unvernetzt():
    form = gutes_teil()
    pruefe_druckteil(form, "petg")
    loc = TopLoc_Location()
    assert all(BRep_Tool.Triangulation_s(TopoDS.Face(f.wrapped), loc) is None for f in form.faces())


# ---------------------------------------------------------------------------------------------------------------------
# Regeltabellen
# ---------------------------------------------------------------------------------------------------------------------


def test_regeltabellen():
    assert P1P.bauraum == (256.0, 256.0, 250.0) and P1P.sperrflaeche == (18.0, 28.0)
    assert P1P.linienbreite == 0.42 and P1P.bett_max == 100 and not P1P.geschlossen and not P1P.duese_gehaertet
    assert P1P.wandstaerke(2) == pytest.approx(0.827, abs=0.005)
    assert P1P.wandstaerke(3) == pytest.approx(1.234, abs=0.005)
    assert P1P.z_mass(2.5) in (2.4, 2.6) and P1P.ueberhang_grenze == 60
    assert material("Amazon Basics PLA").id == "pla" and "205" in material("pla").duese_temp
    assert {m.id for m in MATERIALIEN.values() if m.einhausung} == {"abs", "asa", "pc-filament", "pa", "pa-cf"}
    e = einsatz("M3")
    assert e["bohrung"] == 4.0 and e["tiefe"] == pytest.approx(6.7)
    assert einsatz("M4", hersteller="cnc-kitchen")["bohrung"] == 5.7
    m = muttertasche("M3")
    assert m["sw"] == pytest.approx(5.8) and m["eck"] == pytest.approx(5.8 / math.cos(math.radians(30)))
    assert kernloch("M3", "pla")["kernloch"] == 2.57
    assert kernloch("M4", "abs")["kernloch"] == pytest.approx(3.2)
    # Bayer: y = 0,67 · ε · l² / h, PETG 2,5 %
    assert schnapp_auslenkung(15, 2, "petg") == pytest.approx(0.67 * 0.025 * 225 / 2)
    with pytest.raises(ValueError):
        schnapp_auslenkung(15, 2, "tpu")
    assert material("Nylon").id == "pa"


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit
# ---------------------------------------------------------------------------------------------------------------------


def gehaeuse():
    """Typisches Druckteil: Gehäuse 120 × 80 × 20 mit Rippen, Domen und einer waagrechten Bohrung."""
    b = Box(120, 80, 20, align=UNTEN)
    b = fillet(b.edges().filter_by(Axis.Z), 6)
    b -= Pos(0, 0, 2) * Box(110, 70, 30, align=UNTEN)
    for x in range(-50, 51, 10):
        b += Pos(x, 0, 1) * Box(1.6, 70, 12, align=UNTEN)
    for x in (-45, -15, 15, 45):
        for y in (-25, 25):
            b += Pos(x, y, 1) * Cylinder(4, 15, align=UNTEN)
            b -= Pos(x, y, 6) * Cylinder(2, 15, align=UNTEN)
    return b - Pos(0, -40, 12) * Rot(90, 0, 0) * Cylinder(3, 20)


def test_laufzeit(capsys):
    faelle = {"Winkel 60°": winkel_60(), "Kasten 0,6": kasten_06(), "Bohrung Ø5": bohrung_5(),
              "gutes Teil": gutes_teil(), "Kanäle": kanaele(), "Gehäuse 120×80": gehaeuse()}
    pruefe_druckteil(Box(10, 10, 10), "petg")   # Aufwärmen (Importe, OCCT)
    zeilen = []
    for name, form in faelle.items():
        t = time.perf_counter()
        r = pruefe_druckteil(form, "petg")
        ms = (time.perf_counter() - t) * 1000
        zeilen.append(f"{name:16s} {ms:7.1f} ms  {r['kennzahlen']['dreiecke']:6d} Dreiecke  {r['zusammenfassung']}")
        assert ms < 1000, f"{name}: {ms:.0f} ms"
    with capsys.disabled():
        print("\nLaufzeit Druckprüfung (automatische Ausrichtung):\n  " + "\n  ".join(zeilen))
