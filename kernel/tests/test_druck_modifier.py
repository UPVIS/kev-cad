"""Modifier um Gewindeeinsätze und Kernlöcher (Strang „Rest Druck“, DRUCKVORSCHAU.md „Druckfertig je Objekt“):
jeder erkannte Einsatz bzw. jedes Kernloch bekommt im Bambu-Projekt einen Zylinder-Modifier mit mehr Wänden und 100 %
Füllung, statt die Wände des ganzen Objekts zu erhöhen; die Begrenzung auf 6 Wände je Objekt gilt dann nicht mehr.

Der Nachweis mit dem echten Bambu Studio (3MF und G-Code) läuft nur, wenn Bambu Studio installiert ist."""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.druck import druckfertig as df
from kevcad_kernel.druck import empfehlung as em
from kevcad_kernel.druck import slicer as sl
from kevcad_kernel.druck import vorschau_geo as vg

BAMBU = Path("/Applications/BambuStudio.app")
MIT_BAMBU = (BAMBU / "Contents/MacOS/BambuStudio").exists()


def _geo(bohrungen, groesse=(30.0, 30.0, 12.0)):
    return {"groesse": list(groesse), "auflage": 900.0, "auflage_pruefung": 900.0, "stuetzflaeche": 0.0,
            "ueberhang_hoehe": 0.0, "oben": 100.0, "ausrichtung_text": "−Z-Seite unten", "bohrungen": bohrungen}


def _bohrung(d, mitte, laenge, achse=(0.0, 0.0, 1.0)):
    return {"d": d, "waagrecht": False, "achse": list(achse), "mitte": list(mitte), "laenge": laenge}


def _pruefung(*ds):
    return {"kennzahlen": {"bohrungen": [{"d": d, "waagrecht": False} for d in ds]}}


def test_einsatz_bekommt_modifier_statt_mehr_waenden():
    """M3-Einsatz (Ø 4,0, Sackloch 6,7 mm von oben): Modifier Ø 11,0 mit 4 Wänden und 100 %, das Objekt bleibt bei
    den Wänden und der Füllung seines Zwecks."""
    geo = _geo([_bohrung(4.0, (5.0, 0.0, 12 - 3.35), 6.7)])
    r = em.empfehle(geo, "petg", "funktion", pruefung=_pruefung(4.0))
    e, mods = r["einstellungen"], r["modifier"]
    assert (e["waende"], e["fuellung"]) == (3, 0.2)
    assert len(mods) == 1
    m = mods[0]
    assert (m["art"], m["groesse"], m["einstellungen"]) == ("einsatz", "M3", {"waende": 4, "fuellung": 1.0})
    assert m["radius"] == pytest.approx(2.0 + 1.6 + 0.42)
    # längs der Achse: Bohrung plus Mindestwand unten, oben am Teil abgeschnitten (z ≤ 12)
    assert m["unten"][2] == pytest.approx(12 - 6.7 - 1.6) and m["oben"][2] == pytest.approx(12.0)
    assert m["unten"][:2] == pytest.approx([5.0, 0.0])
    b = r["begruendung_je"]["modifier"]
    assert "Gewindeeinsatz M3" in b and "4 Wänden und 100 % Füllung" in b and "statt mehr Wände" in b
    assert any("Modifier" in x for x in r["begruendung"])
    # als Bambu-Werte des Modifiers
    assert sl.prozess_einstellungen(m["einstellungen"]) == {"wall_loops": "4", "sparse_infill_density": "100%"}


def test_ohne_obergrenze_von_sechs_waenden():
    """M6 (Mindestwand 3,3 mm) braucht 8 Wände: im Modifier geht das, das Objekt bleibt bei 3."""
    geo = _geo([_bohrung(8.1, (0.0, 0.0, 6.0), 12.0)], groesse=(40.0, 40.0, 12.0))
    r = em.empfehle(geo, "petg", "funktion", pruefung=_pruefung(8.1))
    assert r["einstellungen"]["waende"] == 3
    assert r["modifier"][0]["einstellungen"]["waende"] == 8 > 6
    # nicht unter das Bett: die Bohrung geht durch, der Modifier endet bei z = 0 und z = 12
    assert r["modifier"][0]["unten"][2] == pytest.approx(0.0) and r["modifier"][0]["oben"][2] == pytest.approx(12.0)


def test_kernloch_bekommt_modifier():
    geo = _geo([_bohrung(2.5, (0.0, 0.0, 6.0), 8.0)])
    r = em.empfehle(geo, "pla", "funktion", pruefung=_pruefung(2.5))
    m = r["modifier"][0]
    assert (m["art"], m["groesse"]) == ("kernloch", "M3")
    assert m["einstellungen"]["waende"] == math.ceil(1.75 / 0.42)  # Tubus Ø 6 (2 · d) um Ø 2,5
    assert r["einstellungen"]["waende"] == 3  # nicht mehr 4 für das ganze Objekt


def test_ohne_lage_wie_bisher():
    """Ältere Prüfergebnisse ohne Lage der Bohrung: keine Modifier, Wände des ganzen Objekts (höchstens 6)."""
    r = em.empfehle(_geo([]), "petg", "funktion", pruefung=_pruefung(8.1))
    assert r["modifier"] == [] and r["einstellungen"]["waende"] == 6
    assert "ohne Modifier" in r["begruendung_je"]["waende"]


def test_waagrechte_bohrung_und_passung_ohne_modifier():
    geo = _geo([{**_bohrung(4.0, (0.0, 0.0, 6.0), 20.0, achse=(1.0, 0.0, 0.0)), "waagrecht": True},
                _bohrung(12.2, (5.0, 5.0, 6.0), 12.0)])
    r = em.empfehle(geo, "petg", "funktion", pruefung=_pruefung(4.0, 12.2))
    assert r["modifier"] == []


def test_bohrungen_in_druckkoordinaten():
    """vorschau_geo rechnet die Bohrungen der Prüfung (Form gedreht um R) in Druckkoordinaten um."""
    R = vg.rot_xyz([90, 0, 0])  # die Prüfung sah die Form um X gedreht
    B = np.eye(3)               # Druckausrichtung = Form ohne Drehung
    b = {"d": 4.0, "waagrecht": False, "achse": (R @ np.array([0, 0, 1.0])).tolist(),
         "mitte": (R @ np.array([1.0, 2.0, 3.0])).tolist(), "laenge": 6.0}
    out = vg.bohrungen_druck([b, {"d": 3.0}], B, R, [0.5, 0.5, 0.0])
    assert len(out) == 1
    assert out[0]["achse"] == pytest.approx([0, 0, 1])
    assert out[0]["mitte"] == pytest.approx([0.5, 1.5, 3.0])


def test_zylinder_netz_geschlossen():
    P, T = sl.zylinder_netz([0, 0, 0], [0, 0, 10], 3.0, n=32)
    kanten = {}
    for a, b, c in T:
        for x, y in ((a, b), (b, c), (c, a)):
            kanten[(x, y)] = kanten.get((x, y), 0) + 1
    assert all(kanten.get((y, x)) == 1 for (x, y) in kanten)  # jede Kante genau einmal in Gegenrichtung
    tri = P[T]
    vol = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)
    assert vol == pytest.approx(math.pi * 9 * 10, rel=0.02)


def test_montageliste_mit_modifier(tmp_path):
    """Der Modifier steht in der Montageliste beim Teil (gleicher assemble_index, Typ modifier_part); gedreht wie das
    Teil."""
    teil = tmp_path / "t.stl"
    P = np.array([[-10, -5, 0], [10, -5, 0], [10, 5, 0], [-10, 5, 0], [-10, -5, 5], [10, -5, 5], [10, 5, 5],
                  [-10, 5, 5]], dtype=float)
    T = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                  [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    sl.schreibe_stl(teil, P, T)
    mstl = sl.schreibe_modifier_stl({"unten": [6, 0, 0], "oben": [6, 0, 5], "radius": 2.0, "name": "M"},
                                    tmp_path / "m.stl")
    mt = sl.ModifierTeil(stl=mstl, einstellungen={"waende": 5, "fuellung": 1.0}, name="Gewindeeinsatz M3 (Modifier)")
    liste = json.loads(sl.montageliste([[sl.PlattenObjekt(teil, 100, 100, 0, modifier=[mt]),
                                         sl.PlattenObjekt(teil, 50, 50, 90, modifier=[mt])]], tmp_path).read_text())
    o = liste["plates"][0]["objects"]
    assert [x.get("subtype") for x in o] == [None, "modifier_part", None, "modifier_part"]
    assert o[1]["assemble_index"] == o[0]["assemble_index"] and o[3]["assemble_index"] == o[2]["assemble_index"]
    assert o[1]["print_params"] == {"wall_loops": "5", "sparse_infill_density": "100%"}
    assert (o[1]["pos_x"], o[1]["pos_y"]) == (o[0]["pos_x"], o[0]["pos_y"])
    # gedreht: der Modifier liegt nach der Drehung um 90° bei (0, 6) relativ zur Mitte des Teils
    pm = sl.lies_stl(Path(o[3]["path"])).reshape(-1, 3)
    pt = sl.lies_stl(Path(o[2]["path"])).reshape(-1, 3)
    mitte_t = (pt.min(axis=0) + pt.max(axis=0)) / 2
    mitte_m = (pm.min(axis=0) + pm.max(axis=0)) / 2
    assert (mitte_m - mitte_t)[:2] == pytest.approx([0.0, 6.0], abs=1e-3)


def test_objekte_benennen_mit_modifier(tmp_path):
    """Bambu Studio nennt den Modifier nach der STL-Datei; Kev CAD setzt „Gewindeeinsatz M3 (Modifier)“."""
    cfg = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="3">
    <metadata key="name" value="assemble_1"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value="g1_1"/>
    </part>
    <part id="2" subtype="modifier_part">
      <metadata key="name" value="g1-modifier-1_1"/>
    </part>
  </object>
</config>
"""
    p = tmp_path / "m.3mf"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Metadata/model_settings.config", cfg)
    assert sl.objekte_benennen(p, ["Halter"], [["Gewindeeinsatz M3 (Modifier)"]]) == 1
    with zipfile.ZipFile(p) as z:
        neu = ET.fromstring(z.read("Metadata/model_settings.config"))
    namen = [(t.get("subtype"), t.find("metadata").get("value")) for t in neu.find("object").findall("part")]
    assert namen == [("normal_part", "Halter"), ("modifier_part", "Gewindeeinsatz M3 (Modifier)")]


# ---------------------------------------------------------------------------------------------------------------------
# Nachweis mit Bambu Studio: der Modifier kommt im 3MF und im G-Code an


def _mitte_im_gcode(gcode: str, z: float) -> tuple[float, float]:
    """Mitte der Außenwand einer Schicht im G-Code (Bambu Studio legt das Objekt im G-Code nicht genau an die Stelle
    der Matrix im 3MF; geprüft mit 2.07.01.62: 2 mm in Y daneben)."""
    x = y = 0.0
    zz = 0.0
    xs, ys = [], []
    merkmal = ""
    for zeile in gcode.splitlines():
        if zeile.startswith("; Z_HEIGHT:"):
            zz = float(zeile.split(":")[1])
        elif zeile.startswith("; FEATURE:"):
            merkmal = zeile[10:].strip()
        if not zeile.startswith(("G1 ", "G2 ", "G3 ")):
            continue
        werte = dict(re.findall(r"([XYE])(-?[\d.]+)", zeile.split(";")[0]))
        x, y = float(werte.get("X", x)), float(werte.get("Y", y))
        if abs(zz - z) < 1e-6 and merkmal == "Outer wall" and float(werte.get("E", 0)) > 0:
            xs.append(x)
            ys.append(y)
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def _ring_extrusion(gcode: str, cx: float, cy: float, r0: float, r1: float, z0: float, z1: float) -> float:
    """Extrudierte Länge (E, relativ) von Bewegungen, deren Mitte im Ring r0 < r < r1 um (cx, cy) liegt, in den
    Schichten z0 < z < z1."""
    x = y = z = 0.0
    summe = 0.0
    n = 16  # Abtastpunkte je Bewegung; Bögen (G2/G3 mit I, J) entlang des Bogens
    for zeile in gcode.splitlines():
        if zeile.startswith("; Z_HEIGHT:"):
            z = float(zeile.split(":")[1])
            continue
        if not zeile.startswith(("G1 ", "G0 ", "G2 ", "G3 ")):
            continue
        werte = dict(re.findall(r"([XYZEFIJ])(-?[\d.]+)", zeile.split(";")[0]))
        nx, ny = float(werte.get("X", x)), float(werte.get("Y", y))
        e = float(werte.get("E", 0.0))
        if e > 0 and z0 < z < z1 and not zeile.startswith("G0 "):
            if zeile.startswith(("G2 ", "G3 ")) and ("I" in werte or "J" in werte):
                mx_, my_ = x + float(werte.get("I", 0.0)), y + float(werte.get("J", 0.0))
                r = math.hypot(x - mx_, y - my_)
                w0, w1 = math.atan2(y - my_, x - mx_), math.atan2(ny - my_, nx - mx_)
                if zeile.startswith("G2 "):  # im Uhrzeigersinn
                    w1 = w1 - 2 * math.pi if w1 >= w0 - 1e-9 else w1
                else:
                    w1 = w1 + 2 * math.pi if w1 <= w0 + 1e-9 else w1
                punkte = [(mx_ + r * math.cos(w0 + (w1 - w0) * (i + 0.5) / n),
                           my_ + r * math.sin(w0 + (w1 - w0) * (i + 0.5) / n)) for i in range(n)]
            else:
                punkte = [(x + (nx - x) * (i + 0.5) / n, y + (ny - y) * (i + 0.5) / n) for i in range(n)]
            summe += e / n * sum(1 for px, py in punkte if r0 < math.hypot(px - cx, py - cy) < r1)
        x, y = nx, ny
    return summe


@pytest.mark.skipif(not MIT_BAMBU, reason="Bambu Studio nicht installiert")
def test_modifier_kommt_in_bambu_studio_an(tmp_path, monkeypatch):
    """Block 30 × 30 × 12 mm mit M3-Einsatz-Sackloch: das 3MF trägt den Modifier als modifier_part mit 4 Wänden und
    100 % Füllung, und im G-Code ist der Ring um die Bohrung deutlich voller als ohne Modifier."""
    from build123d import Align, Box, Cylinder, Pos

    monkeypatch.setenv("KEVCAD_BAMBU_APP", str(BAMBU))
    monkeypatch.setenv("KEVCAD_DRUCK_CACHE", str(tmp_path / "cache"))
    sl.index_leeren()
    teil = Box(30, 30, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)) - \
        Pos(5, 0, 12 - 6.7) * Cylinder(2.0, 6.7, align=(Align.CENTER, Align.CENTER, Align.MIN))
    P, T = sl.netz_der_form(teil)
    stl = tmp_path / "block.stl"
    sl.schreibe_stl(stl, P, T)
    r = em.empfehle(_geo([_bohrung(4.0, (5.0, 0.0, 12 - 3.35), 6.7)]), "petg", "funktion", pruefung=_pruefung(4.0))
    e = {k: v for k, v in r["einstellungen"].items() if k != "ausrichtung"}
    m = r["modifier"][0]
    mt = sl.ModifierTeil(stl=sl.schreibe_modifier_stl(m, tmp_path / "mod.stl"), einstellungen=m["einstellungen"],
                         name=m["name"])
    ergebnis = {}
    for art, mods in (("mit", [mt]), ("ohne", [])):
        ziel = tmp_path / f"{art}.3mf"
        o = sl.PlattenObjekt(stl=stl, x=128.0, y=128.0, drehung=0.0, einstellungen=e, name="Block", modifier=mods)
        res = sl.export_3mf([[o]], "Bambu PETG Basic @BBL X1C", ziel, tmp_path / f"bambu-{art}", e,
                            platte="Textured PEI Plate")
        assert res["modifier"] == len(mods)
        aus = tmp_path / f"g-{art}"
        aus.mkdir()
        p = subprocess.run([str(sl.programm()), "--slice", "0", "--outputdir", str(aus), str(ziel)], cwd=str(aus),
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stdout[-500:]
        gcode = next(aus.glob("*.gcode")).read_text(errors="replace")
        # Ring außerhalb der 3 Wände des Objekts (2,0 + 1,26 mm), innerhalb des Modifiers (bis 4,02 mm), unter den
        # Deckschichten
        mx, my = _mitte_im_gcode(gcode, 4.0)  # unter der Bohrung: nur die Außenwand des Blocks
        ergebnis[art] = {"ziel": ziel, "mitte": (mx, my),
                         "ring": _ring_extrusion(gcode, mx + 5.0, my, 3.4, 3.95, 6.0, 10.8)}
    # 3MF: Modifier als Teil des Objekts, benannt, mit den Werten
    with zipfile.ZipFile(ergebnis["mit"]["ziel"]) as z:
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    obj = cfg.find("object")
    teile = obj.findall("part")
    assert [p_.get("subtype") for p_ in teile] == ["normal_part", "modifier_part"]
    werte = {mm.get("key"): mm.get("value") for mm in teile[1].findall("metadata")}
    assert werte["name"] == "Gewindeeinsatz M3 (Modifier)"
    assert (werte["wall_loops"], werte["sparse_infill_density"]) == ("4", "100%")
    matrix = [float(x) for x in werte["matrix"].split()]
    assert (matrix[3], matrix[7]) == pytest.approx((133.0, 128.0), abs=0.05)  # um die Bohrung (x = 5 vom Rand)
    haupt = {mm.get("key"): mm.get("value") for mm in teile[0].findall("metadata")}
    assert haupt["wall_loops"] == "3" and haupt["sparse_infill_density"] == "20%"
    # G-Code: im Ring um die Bohrung deutlich mehr Material (Wände und volle Füllung statt 20 % Gyroid)
    assert ergebnis["mit"]["ring"] > 3 * ergebnis["ohne"]["ring"], ergebnis
    sl.index_leeren()
