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
