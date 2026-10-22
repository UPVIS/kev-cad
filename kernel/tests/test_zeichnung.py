"""Zeichnungs-Engine (Phase 6, P6-Z): Projektion, Merkmale, Bemaßung, Bezüge, Bearbeiten, Protokoll — ohne Laufzeit."""

from __future__ import annotations

import time

import numpy as np
import pytest
from build123d import Align, Box, BuildPart, Cylinder, GridLocations, Locations, Pos, Rot, CounterBoreHole, Hole, \
    chamfer, Axis

from kevcad_kernel.protocol import FrameReader, encode_frame, pack_drawing, unpack_polylinien
from kevcad_kernel.zeichnung import bearbeiten, dokument
from kevcad_kernel.zeichnung.merkmale import erkenne, verbindungsmittel
from kevcad_kernel.zeichnung.projektion import EXAKT, projiziere
from kevcad_kernel.zeichnung.szene import Szene, Teil
from kevcad_kernel.zeichnung.zeichner import lies_nutzlast, rechne

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)


def _teil(name, form, kopf=None, katalog=None):
    from kevcad_kernel.zeichnung.projektion import form_schluessel

    bb = form.bounding_box()
    k = {"bbox": {"min": [bb.min.X, bb.min.Y, bb.min.Z], "max": [bb.max.X, bb.max.Y, bb.max.Z]},
         "props": {"mass": form.volume * 2.7e-3}, "material": "Aluminium"}
    k.update(kopf or {})
    return Teil(name, form, form_schluessel(form), k, katalog)


def rohr(laenge=500.0, lagen=(25.0, 250.0, 475.0)):
    """Rohr 12 × 1 senkrecht (wie im Zusammenbau), Querbohrungen Ø4,2 durch beide Wände, Lagen ab dem unteren Ende."""
    r = Cylinder(6, laenge, align=UNTEN) - Pos(0, 0, -1) * Cylinder(5, laenge + 2, align=UNTEN)
    for z in lagen:
        r -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(2.1, 20)
    return Pos(100, 50, 0) * r


ROHR_KOPF = {"stock": {"id": "rohr-alu-12x1.0", "name": "Alurohr 12 × 1,0", "laenge": 500, "gehrung": [0, 0]}}
ROHR_KAT = {"id": "rohr-alu-12x1.0", "art": "rohr", "name": "Alurohr 12 × 1,0"}


def platte():
    p = Box(200, 100, 5, align=(Align.MIN, Align.MIN, Align.MIN))
    p -= [Pos(100 + x, 50 + y, 0) * Cylinder(3.3, 20) for x in (-80, 80) for y in (-30, 30)]
    return p


def druckteil():
    with BuildPart() as bp:
        Box(60, 40, 30, align=UNTEN)
        with Locations((0, 0, 30)):
            with Locations((-15, 0)):
                CounterBoreHole(radius=3.3, counter_bore_radius=5.5, counter_bore_depth=6.4)
            with Locations((15, 0)):
                Hole(radius=3.4, depth=12)  # Kernloch M8
        chamfer(bp.edges().group_by(Axis.Z)[0], length=0.5)
    t = bp.part - Pos(0, 0, 30) * Box(20, 10, 4, align=(Align.CENTER, Align.CENTER, Align.MAX))
    return t


def szene_mit(*teile):
    return Szene({t.name: t for t in teile}, None, {"name": "Probe", "version": "Lauf 1"}, 1)


# ---------------------------------------------------------------------------------------------------------------------
# Projektion
# ---------------------------------------------------------------------------------------------------------------------


def _wuerfel():
    return Box(40, 40, 40, align=(Align.MIN, Align.MIN, Align.MIN)) - Pos(20, 20, 20) * Rot(90, 0, 0) * Cylinder(5, 50)


@pytest.mark.parametrize("exakt", [False, True])
def test_projektion_wuerfel_mit_bohrung(exakt):
    w = _wuerfel()
    vorn = projiziere(w, "vorn", exakt=exakt, cache=None)
    # Vorderansicht: Bohrung als Kreis sichtbar, keine verdeckten Kanten (Rückseite deckt sich mit der Vorderseite)
    assert vorn.rahmen == pytest.approx((0, 0, 40, 40), abs=0.05)
    assert not vorn.linien["verdeckt"]
    pts = np.concatenate(vorn.linien["sichtbar"])
    r = np.hypot(pts[:, 0] - 20, pts[:, 1] - 20)
    assert np.any(np.abs(r - 5) < 0.05)
    assert len(vorn.linien["mitte"]) == 2  # Mittelkreuz
    # Draufsicht: Bohrung verdeckt, zwei Mantellinien bei x = 15 und 25 über die ganze Tiefe
    oben = projiziere(w, "oben", exakt=exakt, cache=None)
    verdeckt = oben.linien["verdeckt"]
    xs = sorted(round(float(pl[:, 0].mean()), 2) for pl in verdeckt)
    assert xs == [15.0, 25.0]
    for pl in verdeckt:
        assert float(np.ptp(pl[:, 1])) == pytest.approx(40, abs=0.05)
    assert len(oben.linien["mitte"]) == 1  # Achse der Bohrung


def test_projektion_kamera_und_je_teil():
    a = Box(10, 10, 10)
    b = Pos(0, 20, 0) * Box(10, 10, 10)  # hinter a (Blick vorn = +y)
    p = projiziere({"A": a, "B": b}, {"richtung": [0, 1, 0], "oben": [0, 0, 1]}, verdeckt=False, je_teil=True,
                   cache=None)
    assert set(p.teile) == {"A", "B"}
    assert p.teile["A"]["sichtbar"] and not p.teile["B"]["sichtbar"]  # B ganz verdeckt
    q = projiziere(a, {"rotation": [0, 0, 0, 1]}, cache=None)  # Kamera blickt entlang −Z
    assert q.blick.d.tolist() == pytest.approx([0, 0, -1])


def test_rost_netz_schnell_und_exakt_mit_budget():
    """RECHERCHE-PHASE6.md 3.2: exakt rund 80 s, Netz 0,02 s. Vorgabe ist das Netz, exakt nur mit Budget."""
    with BuildPart() as p:
        with GridLocations(44.5, 0, 10, 1):
            Cylinder(1.5, 265, rotation=(90, 0, 0))
        with Locations((0, 100, -2.0), (0, -100, -2.0)):
            Cylinder(2.0, 445, rotation=(0, 90, 0))
    t = time.perf_counter()
    netz = projiziere(p.part, "links", cache=None)
    assert time.perf_counter() - t < 5.0
    assert not netz.exakt and netz.linien["sichtbar"]
    assert len(netz.linien["sichtbar"]) < 2000  # zusammengefasst (roh mehrere Tausend Stücke)
    t = time.perf_counter()
    mit_budget = projiziere(p.part, "links", exakt=0.5)
    assert time.perf_counter() - t < 8.0  # Start des Hilfsprozesses + Budget + Netz
    assert not mit_budget.exakt  # Budget überschritten: Netzergebnis
    t = time.perf_counter()
    projiziere(p.part, "links", exakt=0.5)  # gemerkt: kein zweiter Versuch
    assert time.perf_counter() - t < 1.0
    w = projiziere(_wuerfel(), "oben", exakt=5.0)
    assert w.exakt
    EXAKT.schliessen()


# ---------------------------------------------------------------------------------------------------------------------
# Merkmale
# ---------------------------------------------------------------------------------------------------------------------


def test_merkmale_rohr_mit_drei_bohrungen():
    m = erkenne(rohr(), {**ROHR_KOPF, "katalog": ROHR_KAT})
    assert m.system.art == "stange"
    assert m.system.groesse[0] == pytest.approx(500, abs=1e-3)
    bohr = m.von_art("bohrung")
    assert len(bohr) == 3  # Innenseite des Rohrs ist Profil, keine Bohrung
    assert [b.werte["lage_mm"][0] for b in bohr] == pytest.approx([25, 250, 475])
    for b in bohr:
        assert b.werte["d"] == pytest.approx(4.2) and b.werte["durch"] and b.werte["waende"] == 2
        assert b.text == "Ø4,2"
    lb = m.get("lochbild:1")
    assert lb.werte["muster"] == "reihe" and lb.werte["teilung"] == pytest.approx(225) and lb.text == "3× Ø4,2"
    assert m.get("stange").werte["gehrung"] == [0.0, 0.0]


def test_merkmale_platte_mit_lochbild():
    m = erkenne(platte(), {"katalog": {"art": "platte"}})
    assert m.system.art == "platte"
    assert m.system.groesse.tolist() == pytest.approx([200, 5, 100])
    lb = m.get("lochbild:1")
    assert lb.werte["muster"] == "raster" and lb.werte["n"] == 4
    assert sorted(lb.werte["teilungen"]) == pytest.approx([60, 160])


def test_merkmale_druckteil_fase_tasche_senkung_gewinde():
    t = druckteil()
    schraube = Pos(15, 0, 40) * Cylinder(4, 30, align=(Align.CENTER, Align.CENTER, Align.MAX))
    vm = verbindungsmittel("Schraube M8", schraube, {"katalog": {"art": "schraube", "masse": {"groesse": "M8-1.25"}}})
    assert vm is not None and vm["d"] == 8
    m = erkenne(t, {"druckteil": {"material": "petg"}}, umgebung=[vm])
    texte = sorted(x.text for x in m.von_art("bohrung"))
    assert "M8 × 12" in texte  # Kernloch Ø6,8 mit Schraube M8 auf derselben Achse
    gegen = next(x for x in m.von_art("bohrung") if x.werte.get("gegenbohrung"))
    assert gegen.werte["d"] == pytest.approx(6.6) and gegen.werte["gegenbohrung"]["d"] == pytest.approx(11)
    assert gegen.werte["gegenbohrung"]["tiefe"] == pytest.approx(6.4)
    assert gegen.text == "Ø6,6, Senkung Ø11 × 6,4 tief"
    tasche = m.von_art("tasche")
    assert len(tasche) == 1 and tasche[0].werte["tiefe"] == pytest.approx(4)
    assert sorted(tasche[0].werte["ausdehnung"]) == pytest.approx([10, 20])
    fase = m.von_art("fase")
    assert fase and fase[0].werte["a"] == pytest.approx(0.5) and fase[0].werte["text_einzel"] == "0,5 × 45°"


# ---------------------------------------------------------------------------------------------------------------------
# Bemaßung und Blatt
# ---------------------------------------------------------------------------------------------------------------------


def _masse(erg):
    return {m["schluessel"]: m for m in erg.blatt["masse"] if m.get("schluessel")}


def _texte(erg):
    return {m["id"]: m["text"] for m in erg.kopf["masse"]}


def test_bemassung_rohr_laenge_bohrungen_ab_ende():
    t = _teil("Gestell/Rohr", rohr(), ROHR_KOPF, ROHR_KAT)
    erg = rechne(dokument.neu("rohr", "Rohr", "teil", [t.name]), szene_mit(t))
    texte = sorted(_texte(erg).values())
    assert "500" in texte  # Länge
    assert "3× Ø4,2" in texte  # Lochbild als Angabe an einer Bohrung
    assert "25" in texte  # erste Lage ab Ende A
    assert "2 × 225 (= 450)" in texte  # Teilung
    assert not any(t in texte for t in ("6", "12"))  # mittige Bohrungen: keine Querlage
    assert [a["art"] for a in erg.blatt["ansichten"]] == ["vorn"]
    assert "Halbzeug: Alurohr 12 × 1,0" in erg.blatt["allgemein"]
    assert not erg.kopf["pruefung"]


def test_bemassung_platte_lochbild_ab_ecke():
    t = _teil("Platte", platte(), {"stock": {"id": "platte-alu-5", "name": "Aluplatte 5"}},
              {"id": "platte-alu-5", "art": "platte", "name": "Aluplatte 5 mm"})
    erg = rechne(dokument.neu("platte", "Platte", "teil", [t.name]), szene_mit(t))
    texte = set(_texte(erg).values())
    assert {"200", "100", "4× Ø6,6"} <= texte
    lagen = sorted(m["wert"] for m in erg.blatt["masse"] for m in [next(k for k in erg.kopf["masse"]
                                                                           if k["id"] == m["id"])]
                   if m["art"] == "linear" and m["wert"] not in (200.0, 100.0))
    assert lagen == pytest.approx([20, 20, 80, 180])  # Lagen ab der Ecke unten links, nicht symmetrisch
    # drei und mehr Lagen auf einer Achse: steigende Bemaßung
    p2 = platte() - Pos(30, 50, 0) * Cylinder(4, 20)
    t2 = _teil("Platte", p2, {"stock": {"id": "platte-alu-5"}}, {"id": "platte-alu-5", "art": "platte"})
    erg2 = rechne(dokument.neu("platte", "Platte", "teil", [t2.name]), szene_mit(t2))
    werte = sorted(x["wert"] for m in erg2.kopf["masse"] for x in m.get("texte") or [])
    assert werte == pytest.approx([20, 20, 30, 50, 80, 180])
    assert any(a.startswith("t = 5") for a in erg.blatt["allgemein"])


def test_bemassung_druckteil_fase_tasche():
    t = _teil("Halter", druckteil(), {"druckteil": {"material": "petg", "verfahren": "3d-druck"}})
    erg = rechne(dokument.neu("halter", "Halter", "teil", [t.name]), szene_mit(t))
    texte = set(_texte(erg).values())
    assert {"60", "40", "30"} <= texte
    assert "4" in texte  # Taschentiefe
    assert any("0,5 × 45°" in x for x in texte)  # Fase
    assert any(x.startswith("Ø6,6") for x in texte)
    assert "Nicht bemaßte Maße nach 3D-Modell" in erg.blatt["allgemein"]
    sf = erg.blatt["schriftfeld"]
    assert sf["dokumentart"] == "Fertigungszeichnung" and sf["allgemeintoleranz"] == "ISO 2768-m"
    assert sf["blatt_nr"] == 1 and sf["blatt_anzahl"] == 1 and sf["eigentuemer"]


def test_neuzuordnung_nach_laengenaenderung_und_verwaist():
    t = _teil("Gestell/Rohr", rohr(), ROHR_KOPF, ROHR_KAT)
    sz = szene_mit(t)
    erg = rechne(dokument.neu("rohr", "Rohr", "teil", [t.name]), sz)
    # Kevin setzt ein eigenes Maß Ende A → zweite Bohrung und verschiebt das Längenmaß
    blatt, res = bearbeiten.anwenden(erg.blatt, [
        {"op": "mass_neu", "art": "linear", "ansicht": "v1", "richtung": "x",
         "bezuege": [{"merkmal": "seite:x-"}, {"merkmal": "bohrung:2"}], "versatz": -20},
        {"op": "mass_verschieben", "id": _masse(erg)["huelle:x"]["id"], "versatz": -30}], "kevin", erg)
    assert all(r["ok"] for r in res), res
    eigen = res[0]["id"]
    erg2 = rechne(blatt, sz)
    assert _texte(erg2)[eigen] == "250"
    # Rohr wird länger (Bohrungen bleiben ab Ende A)
    t2 = _teil("Gestell/Rohr", rohr(600, (25, 250, 575)), ROHR_KOPF, ROHR_KAT)
    erg3 = rechne(erg2.blatt, szene_mit(t2))
    m3 = {m["id"]: m for m in erg3.blatt["masse"]}
    assert _texte(erg3)[eigen] == "250" and not m3[eigen]["verwaist"]
    laenge = _masse(erg3)["huelle:x"]
    assert _texte(erg3)[laenge["id"]] == "600" and laenge["fest"] and laenge["versatz"] == pytest.approx(-30)
    # Bohrung verschwindet: Kevins Maß wird verwaist, bleibt aber erhalten
    t3 = _teil("Gestell/Rohr", rohr(600, (25,)), ROHR_KOPF, ROHR_KAT)
    erg4 = rechne(erg3.blatt, szene_mit(t3))
    m4 = {m["id"]: m for m in erg4.blatt["masse"]}
    assert m4[eigen]["verwaist"] is True
    assert any(p["pruefung"] == "verwaist" for p in erg4.kopf["pruefung"])


# ---------------------------------------------------------------------------------------------------------------------
# Bearbeiten: alle Operationen
# ---------------------------------------------------------------------------------------------------------------------


def test_alle_bearbeitungs_operationen():
    t = _teil("Halter", druckteil(), {"druckteil": {"material": "petg"}})
    sz = szene_mit(t)
    erg = rechne(dokument.neu("halter", "Halter", "teil", [t.name]), sz)
    auto = _masse(erg)
    breite = auto["huelle:x"]["id"]
    v1 = erg.ansichten["v1"]
    # Klick auf die linke Kante der Vorderansicht und auf die rechte
    links = [float(v1.rahmen.x0), float(v1.rahmen.mitte[1])]
    rechts = [float(v1.rahmen.x1), float(v1.rahmen.mitte[1])]
    ops = [
        {"op": "mass_loeschen", "id": breite},
        {"op": "mass_neu", "art": "linear", "richtung": "x", "bezuege": [{"ansicht": "v1", "punkt": links},
                                                                        {"ansicht": "v1", "punkt": rechts}],
         "versatz": -25, "text": "<> (Kontrolle)"},
        {"op": "mass_aendern", "id": auto["huelle:z"]["id"], "toleranz": "±0,1"},
        {"op": "ansicht_neu", "art": "schnitt", "schnitt": {"von": "v1", "ebene": {"punkt": [15, 20, 15],
                                                                                   "normale": [0, 1, 0]}}},
        {"op": "ansicht_neu", "art": "einzelheit", "einzelheit": {"von": "v1", "mitte": [0, 0], "radius": 6,
                                                                   "faktor": 4}},
        {"op": "notiz", "text": "Grat entfernen", "lage": [40, 40]},
        {"op": "schriftfeld", "feld": "werkstoff", "wert": "PETG schwarz"},
        {"op": "massstab", "wert": "2:1"},
        {"op": "format", "wert": "A3", "ausrichtung": "quer"},
        {"op": "gibt_es_nicht"},
    ]
    blatt, res = bearbeiten.anwenden(erg.blatt, ops, "kevin", erg)
    assert [r["ok"] for r in res] == [True] * 9 + [False]
    erg2 = rechne(blatt, sz)
    b = erg2.blatt
    assert breite not in {m["id"] for m in b["masse"]}
    assert len(b["unterdrueckt"]) == 1 and b["unterdrueckt"][0]["art"] == "linear"
    assert not any(m.get("schluessel") == "huelle:x" for m in b["masse"])  # nicht neu angelegt
    neu = next(m for m in erg2.kopf["masse"] if m["id"] == res[1]["id"])
    assert neu["text"] == "60 (Kontrolle)" and neu["quelle"] == "kevin"
    assert next(m for m in erg2.kopf["masse"] if m["id"] == auto["huelle:z"]["id"])["text"] == "30 ±0,1"
    arten = [a["art"] for a in b["ansichten"]]
    assert "schnitt" in arten and "einzelheit" in arten
    schnitt = next(g for g in erg2.kopf["geometrie"] if g["art"] == "schnitt")
    assert schnitt["linien"]["schraffur"] > 0
    assert b["massstab"] == "2:1" and b["format"] == "A3" and not b["auto"]["massstab"]
    assert b["schriftfeld"]["werkstoff"] == "PETG schwarz" and b["notizen"][0]["text"] == "Grat entfernen"
    # Ansicht verschieben, Notiz und Ansicht löschen, Unterdrückung aufheben, Automatik zurücksetzen
    sid = next(a["id"] for a in b["ansichten"] if a["art"] == "einzelheit")
    blatt, res = bearbeiten.anwenden(b, [
        {"op": "ansicht_verschieben", "id": sid, "lage": [300, 200]},
        {"op": "notiz_loeschen", "id": b["notizen"][0]["id"]},
        {"op": "unterdrueckung_aufheben", "index": 0},
        {"op": "mass_verschieben", "id": res[1]["id"] if False else auto["huelle:z"]["id"], "text_lage": [50, 50]},
    ], "agent", erg2)
    assert all(r["ok"] for r in res), res
    erg3 = rechne(blatt, sz)
    assert any(m.get("schluessel") == "huelle:x" for m in erg3.blatt["masse"])  # wieder da
    assert next(a for a in erg3.blatt["ansichten"] if a["id"] == sid)["lage"] == [300, 200]
    blatt, res = bearbeiten.anwenden(erg3.blatt, [{"op": "ansicht_loeschen", "id": sid},
                                                  {"op": "auto", "masse": True, "zuruecksetzen": True}], "agent", erg3)
    assert all(r["ok"] for r in res)
    erg4 = rechne(blatt, sz)
    assert not erg4.blatt["unterdrueckt"] and sid not in {a["id"] for a in erg4.blatt["ansichten"]}
    assert any(m.get("quelle") == "kevin" for m in erg4.blatt["masse"])  # Kevins Maß bleibt


# ---------------------------------------------------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------------------------------------------------


def test_drawing_rundlauf_protokoll():
    t = _teil("Platte", platte(), {"stock": {"id": "platte-alu-5"}}, {"id": "platte-alu-5", "art": "platte"})
    erg = rechne(dokument.neu("platte", "Platte", "teil", [t.name]), szene_mit(t))
    gruppen = lies_nutzlast(erg.kopf, erg.nutzlast)
    header, payload = pack_drawing(erg.kopf, gruppen, reply_to="a-7", seq=12)
    assert payload == erg.nutzlast
    (h, p), = FrameReader().feed(encode_frame(header, payload))
    assert h["type"] == "DRAWING" and h["reply_to"] == "a-7" and h["linien_reihenfolge"][-2:] == ["nachbar", "bruch"]
    zurueck = unpack_polylinien(h, p)
    assert len(zurueck) == len(h["geometrie"]) and h["geometrie"][-1]["id"] == "blatt"
    for g, z in zip(h["geometrie"], zurueck):
        assert {k: len(v) for k, v in z.items()} == g["linien"]
    m = h["masse"][0]
    assert {"id", "linien", "pfeile", "text", "text_lage", "text_winkel", "wert"} <= set(m)
    assert h["blatt"]["id"] == "platte" and h["blattgroesse"] == [297.0, 210.0]


def test_automatischer_schnitt_bei_innenmerkmalen():
    """Sacklöcher, Senkung und Tasche lägen in der Vorderansicht nur verdeckt: Vorderansicht als Vollschnitt A–A."""
    t = _teil("Halter", druckteil(), {"druckteil": {"material": "petg"}})
    erg = rechne(dokument.neu("halter", "Halter", "teil", [t.name]), szene_mit(t))
    v1 = next(a for a in erg.blatt["ansichten"] if a["id"] == "v1")
    assert v1["art"] == "schnitt" and v1["schnitt"]["von"] == "v2" and v1["schnitt"]["blick"] == "vorn"
    g1 = next(g for g in erg.kopf["geometrie"] if g["id"] == "v1")
    assert g1["linien"]["schraffur"] > 0 and g1["linien"]["verdeckt"] == 0
    g2 = next(g for g in erg.kopf["geometrie"] if g["id"] == "v2")
    assert g2["linien"]["schnitt"] == 1  # Schnittverlauf in der Draufsicht
    assert any(x["text"] == "A–A" for x in erg.kopf["texte"])
    tiefe = next(m for m in erg.blatt["masse"] if str(m.get("schluessel", "")).startswith("tiefe:tasche"))
    assert tiefe["ansicht"] == "v1"
    # Druckteil ohne Innenmerkmale: keine Schnittansicht
    t2 = _teil("Klotz", Box(40, 30, 20, align=UNTEN) - Pos(0, 0, 10) * Cylinder(3, 30), {"druckteil": {}})
    erg2 = rechne(dokument.neu("klotz", "Klotz", "teil", [t2.name]), szene_mit(t2))
    assert not any(a["art"] == "schnitt" for a in erg2.blatt["ansichten"])


def test_bohrungstabelle_bei_vielen_bohrungen():
    p = Box(300, 200, 6, align=(Align.MIN, Align.MIN, Align.MIN))
    p -= [Pos(30 + 80 * i, 30 + 45 * j, 0) * Cylinder(3.3, 20) for i in range(4) for j in range(4)]
    t = _teil("Lochplatte", p, {"stock": {"id": "platte-alu-6"}}, {"id": "platte-alu-6", "art": "platte"})
    erg = rechne(dokument.neu("lochplatte", "Lochplatte", "teil", [t.name]), szene_mit(t))
    koord = [m for m in erg.blatt["masse"] if m["art"] == "koordinaten"]
    assert len(koord) == 1 and len(koord[0]["bezuege"]) == 2 + 16
    grafik = next(m for m in erg.kopf["masse"] if m["id"] == koord[0]["id"])
    assert sorted(x["text"] for x in grafik["texte"])[:2] == ["A1", "A10"] and len(grafik["texte"]) == 16
    texte = [x["text"] for x in erg.kopf["texte"]]
    assert any(x.startswith("Bohrungen (X, Y ab Ecke unten links)") for x in texte) and "A16" in texte
    assert "110" in texte and "30" in texte  # X und Y in der Tabelle
    assert not [b for b in erg.kopf["pruefung"] if b["pruefung"] == "fehlend"]


def _im_zeichenfeld(erg, vid: str) -> None:
    """Ansicht liegt im Zeichenfeld des Blatts und überdeckt das Schriftfeld nicht."""
    from kevcad_kernel.zeichnung import blatt as bl

    W, H = bl.blattgroesse(erg.blatt["format"], erg.blatt["ausrichtung"])
    z, sf = bl.zeichenflaeche(W, H), bl.schriftfeld_rechteck(W, H)
    x0, y0, x1, y1 = next(g for g in erg.kopf["geometrie"] if g["id"] == vid)["rahmen"]
    assert z.x0 <= x0 and x1 <= z.x1 and z.y0 <= y0 and y1 <= z.y1, (x0, y0, x1, y1, z)
    assert not (x0 < sf.x1 and sf.x0 < x1 and y0 < sf.y1 and sf.y0 < y1), "Ansicht überdeckt das Schriftfeld"


def test_feste_ansicht_beim_formatwechsel():
    """Maßstab geändert, Kev CAD wählt ein anderes Format: feste Ansichten wandern anteilig mit und bleiben im
    Zeichenfeld; passt eine dort nicht ohne Schriftfeld zu überdecken, bleibt ein größeres Format mit Hinweis."""
    from kevcad_kernel.zeichnung import blatt as bl

    t = _teil("Halter/Platte", platte())
    sz = szene_mit(t)
    erg = rechne(dokument.neu("platte", "Platte", "teil", [t.name]), sz)
    b, res = bearbeiten.anwenden(erg.blatt, [{"op": "massstab", "wert": "2:1"}], "kevin", erg)
    gross = rechne(b, sz)
    fmt_gross = (gross.blatt["format"], gross.blatt["ausrichtung"])
    assert fmt_gross != ("A4", "quer")
    # 1. passt: Lage anteilig nach A4 quer, ohne Hinweis
    lage = bl.lage_umrechnen([156.0, 123.0], ("A4", "quer"), fmt_gross)
    b, res = bearbeiten.anwenden(gross.blatt, [{"op": "ansicht_verschieben", "id": "v1", "lage": lage}], "kevin", gross)
    erg = rechne(b, sz)
    b, res = bearbeiten.anwenden(erg.blatt, [{"op": "massstab", "wert": "1:1"}], "kevin", erg)
    klein = rechne(b, sz)
    assert (klein.blatt["format"], klein.blatt["ausrichtung"]) == ("A4", "quer")
    v1 = next(a for a in klein.blatt["ansichten"] if a["id"] == "v1")
    assert v1["fest"] and v1["lage"] == pytest.approx(bl.lage_umrechnen(lage, fmt_gross, ("A4", "quer")), abs=0.01)
    _im_zeichenfeld(klein, "v1")
    assert not [h for h in klein.hinweise if "Feste Ansicht" in h]
    # 2. passt nicht: auf A4 überdeckte die mitgenommene Ansicht das Schriftfeld; ein größeres Format bleibt
    lage = [330.0, 220.0] if fmt_gross == ("A2", "quer") else bl.lage_umrechnen([330.0, 220.0], ("A2", "quer"),
                                                                                 fmt_gross)
    b, res = bearbeiten.anwenden(gross.blatt, [{"op": "ansicht_verschieben", "id": "v1", "lage": lage}], "kevin", gross)
    erg = rechne(b, sz)
    b, res = bearbeiten.anwenden(erg.blatt, [{"op": "massstab", "wert": "1:1"}], "kevin", erg)
    klein = rechne(b, sz)
    assert klein.blatt["format"] != "A4"
    assert any("Feste Ansicht v1 passt nicht auf A4 quer" in h for h in klein.hinweise), klein.hinweise
    _im_zeichenfeld(klein, "v1")


def test_feste_ansicht_ausserhalb_wird_ins_zeichenfeld_geklemmt():
    t = _teil("Halter/Platte", platte())
    sz = szene_mit(t)
    erg = rechne(dokument.neu("platte", "Platte", "teil", [t.name]), sz)
    assert erg.blatt["format"] == "A4"
    b, res = bearbeiten.anwenden(erg.blatt, [{"op": "ansicht_verschieben", "id": "v1", "lage": [300, 230]}], "kevin",
                                 erg)
    erg = rechne(b, sz)
    assert erg.blatt["format"] == "A4"
    _im_zeichenfeld(erg, "v1")
    # explizites Format: feste Lagen anteilig mit
    from kevcad_kernel.zeichnung import blatt as bl

    alt = list(next(a for a in erg.blatt["ansichten"] if a["id"] == "v1")["lage"])
    b, res = bearbeiten.anwenden(erg.blatt, [{"op": "format", "wert": "A3", "ausrichtung": "quer"}], "kevin", erg)
    v1 = next(a for a in b["ansichten"] if a["id"] == "v1")
    assert v1["lage"] == pytest.approx(bl.lage_umrechnen(alt, ("A4", "quer"), ("A3", "quer")), abs=0.01)
    _im_zeichenfeld(rechne(b, sz), "v1")


def test_stueckliste_behaelt_katalogbenennungen():
    """Kurznamen nur für Teilenamen aus show() (Druck-, Eigenteile), nie für Katalog- oder Zukaufbenennungen mit „/“
    (Zoll-Schrauben, Profile)."""
    from kevcad_kernel.zeichnung import blatt as bl
    from kevcad_kernel.zeichnung.szene import Szene

    zoll = 'Senkschraube 3/8"-16 UNC × 5/8", 82°, Stahl'
    bom = {"lines": [
        {"pos": 1, "art": "druckteil", "benennung": "Gestell/Halter (Druck)", "anzahl": 1, "material": "PETG",
         "teile": ["Gestell/Halter (Druck)"]},
        {"pos": 2, "art": "schraube", "stock_id": "senkschraube-3-8-16-unc", "benennung": zoll, "anzahl": 1,
         "teile": ["Gestell/Schraube"]},
        {"pos": 3, "art": "zukaufteil", "benennung": "Profil 40/40 B-Typ Nut 8", "anzahl": 1, "teile": []}]}
    assert [z[2] for z in bl.stueckliste_zeilen(bom)] == ["Halter (Druck)", zoll, "Profil 40/40 B-Typ Nut 8"]
    halter = _teil("Gestell/Halter (Druck)", platte(), {"druckteil": {"material": "petg"}})
    schraube = _teil("Gestell/Schraube", Pos(20, 20, 5) * Cylinder(4.76, 15.9, align=UNTEN),
                     {"stock": {"id": "senkschraube-3-8-16-unc"}}, {"id": "senkschraube-3-8-16-unc", "art": "schraube",
                                                                    "name": zoll})
    sz = Szene({halter.name: halter, schraube.name: schraube}, bom, {"name": "Probe", "version": "V1"}, 1)
    erg = rechne(dokument.neu("zusammenbau", "Zusammenbau", "zusammenbau", []), sz)
    texte = [x["text"] for x in erg.kopf["texte"]]
    # die Zelle kürzt zu lange Benennungen am Ende („…“), der Anfang bleibt
    assert any(x.startswith('Senkschraube 3/8"-16 UNC × 5/8"') for x in texte), [x for x in texte if "UNC" in x]
    assert not any(x.startswith('8"') for x in texte)


def test_formatwahl_kleinstes_passendes_format(monkeypatch):
    """Wagen um 700 mm: passt A4 im selben Maßstab wie A3, nimmt Kev CAD A4 (nicht A2 im größeren Maßstab, zwei
    Drittel leer). Eine Größe mehr nur bei kleinem Teil und größerem Maßstab."""
    from kevcad_kernel.zeichnung import blatt as bl
    from kevcad_kernel.zeichnung import zeichner

    wagen = Box(700, 450, 30, align=UNTEN)
    teile = [_teil("Wagen/Rahmen", Pos(0, 0, 120) * wagen)]
    teile += [_teil(f"Wagen/Bein {i + 1}", Pos(x, y, 0) * Box(40, 40, 120, align=UNTEN))
              for i, (x, y) in enumerate([(-320, -190), (320, -190), (-320, 190), (320, 190)])]
    versuche = []
    orig = zeichner._versuch

    def versuch(*a, **kw):
        erg = orig(*a, **kw)
        if erg is not None and not kw.get("erzwingen") and not kw.get("ohne_fest"):
            versuche.append((a[8], a[9], a[10]))
        return erg

    monkeypatch.setattr(zeichner, "_versuch", versuch)
    erg = rechne(dokument.neu("wagen", "Wagen", "baugruppe", ["Wagen"]), szene_mit(*teile))
    rang = zeichner.FORMAT_RANG
    kleinstes = min(rang[f] for f, _, _ in versuche)
    gewaehlt = (erg.blatt["format"], erg.blatt["ausrichtung"], bl.massstab_faktor(erg.blatt["massstab"]))
    assert gewaehlt == ("A4", "hoch", 0.1), (gewaehlt, versuche)  # A3 ginge nur im selben Maßstab, A2 wäre leer
    assert rang[gewaehlt[0]] <= kleinstes + 1, (gewaehlt, versuche)
    if rang[gewaehlt[0]] == kleinstes + 1:  # nur mit größerem Maßstab als auf dem kleinsten Format
        assert gewaehlt[2] > max(s for f, _, s in versuche if rang[f] == kleinstes)
    groesser = [s for f, _, s in versuche if rang[f] == rang[gewaehlt[0]] + 1]
    assert not groesser or max(groesser) > gewaehlt[2] or rang[gewaehlt[0]] == kleinstes

