"""Werkstoffdaten der Statik (Strang „Bestand Stufe 2“, PLAN-STATIK.md T6, KATALOG.md „Mechanik“): Festigkeiten für
Holzwerkstoffe, Buntmetalle und alle Druckmaterialien, Reibwert Stahl auf Beton, Auszugkraft von Gewindeeinsätzen und
ihr Nachweis in S0 (Schraubenlast im Druckteil). Jeder Wert mit Quelle und Stand; Schätzungen gekennzeichnet."""

from __future__ import annotations

import json
import tempfile

import numpy as np
import pytest

from kevcad_kernel.catalog import Catalog, builtin_dir, einsatz_groesse, validate_einsatz_auszug
from kevcad_kernel.statik import bewertung, s0
from kevcad_kernel.statik.modell import StatikModell, Teil
from kevcad_kernel.statik.szenario import Last, Szenario
from kevcad_kernel.statik.werkstoff import werkstoff

NEU = ("multiplex-birke", "mdf", "spanplatte", "messing", "kupfer", "abs", "asa", "tpu-95a", "pc-filament", "pa",
       "pa-cf", "pla-cf")


@pytest.fixture(scope="module")
def kat():
    return Catalog(builtin_dir(), tempfile.mkdtemp(prefix="kcw"))


def test_neue_materialien_haben_mechanik_mit_quelle_und_stand(kat):
    assert kat.warnings == []
    for mid in NEU:
        mech = kat.material(mid)["mechanik"]
        assert mech["quelle"].strip() and mech["stand"] == "2026-10", mid
        assert mech.get("annahme"), mid  # Zustand, Dicke, Richtung oder Feuchte steht dabei
        w = werkstoff(kat, mid)
        assert w is not None and w.E > 0 and w.grenze > 0, mid
    # Druckmaterialien: quer zur Schicht wie die Druckregeln (druck/regeln.py)
    from kevcad_kernel.druck.regeln import MATERIALIEN

    for m in kat.printable_materials():
        if m["id"] == "harz-standard":
            continue  # Harzdruck gibt es nicht (kein Drucker), bleibt ohne Mechanik
        mech = m.get("mechanik")
        assert mech, m["id"]
        assert mech["quer_zur_schicht"] == MATERIALIEN[m["id"]].z_festigkeit, m["id"]
        assert mech["e_modul_z"] <= mech["e_modul"] and mech["zugfestigkeit_z"] <= mech["zugfestigkeit"], m["id"]
    # Stichproben gegen die Quellen
    assert (werkstoff(kat, "mdf").biege, werkstoff(kat, "mdf").E) == (20, 2200)          # EN 622-5, 12–19 mm
    assert (werkstoff(kat, "spanplatte").biege, werkstoff(kat, "spanplatte").E) == (11, 1600)  # EN 312 P2
    assert werkstoff(kat, "messing").streckgrenze == 220 and werkstoff(kat, "messing").zug == 430  # R430
    assert werkstoff(kat, "pa").zug == 34.3  # CoPA nass (vorsichtig)


def test_reibwert_stahl_auf_beton(kat):
    for stahl in ("stahl-s235", "edelstahl-1.4301", "stahl-verzinkt"):
        r = kat.reibwert(stahl, "beton")
        assert r["haft"] == 0.2 and r["bereich"] == [0.2, 0.4] and "DIN EN 1993-1-8" in r["quelle"], stahl
    # Gummi bleibt beim eigenen Wert
    assert kat.reibwert("epdm", "beton")["haft"] == 0.6


def test_einsatz_auszug_daten(kat):
    rows = kat.einsatz_auszuege()
    assert {(r["groesse"], r["material"]) for r in rows} == {("M3", "pla"), ("M3", "petg"), ("M6", "pla"),
                                                             ("M6", "petg")}
    for r in rows:
        assert validate_einsatz_auszug(r) == [] and r["stand"] == "2026-10" and r["bedingungen"]
        assert r["quelle"].count("20") >= 1  # Datum der Quelle steht dabei
    # abgelesene Diagrammwerte sind als Schätzung markiert
    assert all(r.get("geschaetzt") for r in rows if r["groesse"] == "M6")
    assert kat.einsatz_auszug("M3", "PET-G")["kraft_n"] == 1167
    assert kat.einsatz_auszug(3.0, "pla")["kraft_n"] == 1400
    assert kat.einsatz_auszug("M4", "pla") is None and kat.einsatz_auszug("M5", "petg") is None  # Lücken
    assert [einsatz_groesse(x) for x in ("M3", "m4", "M3-0.5", 5, "M2,5", "x")] == ["M3", "M4", "M3", "M5", "M2.5",
                                                                                     None]
    assert validate_einsatz_auszug({"groesse": "M3", "material": "pla", "kraft_n": 0})  # ohne Quelle, Kraft 0


def test_eigener_katalog_ersetzt_auszug(tmp_path):
    (tmp_path / "eigene.json").write_text(json.dumps({"version": 1, "einsatz_auszug": [
        {"groesse": "M4", "material": "petg", "kraft_n": 900, "quelle": "eigener Versuch, 22.10.2026", "stand": "2026-10"},
        {"groesse": "M4", "material": "pla", "kraft_n": -1, "quelle": "x"}]}))
    c = Catalog(builtin_dir(), tmp_path)
    assert c.einsatz_auszug("M4", "petg")["ebene"] == "eigen"
    assert c.einsatz_auszug("M4", "pla") is None and any("kraft_n" in w for w in c.warnings)


# ---------------------------------------------------------------------------------------------------------------------
# Nachweis in S0: Lampe hängt mit zwei M-Schrauben in Gewindeeinsätzen an einem Druckteil auf dem Boden


def _teil(name, kg, z, mat=None, druck=False, verbindung=False, d=None):
    return Teil(name, kg, np.array([0.0, 0.0, z + 5]), np.array([-20.0, -20.0, z]), np.array([20.0, 20.0, z + 10]),
                mat, None, None, None, druck, None, False, verbindung, d)


def _modell(groesse: float, material: str) -> StatikModell:
    m = StatikModell()
    m.teile["Halter (Druck)"] = _teil("Halter (Druck)", 0.05, 0.0, material, druck=True)
    m.teile["Lampe"] = _teil("Lampe", 2.0, 100.0)
    mit = []
    for i, x in enumerate((-10.0, 10.0), 1):
        for name in (f"Schrauben/M{groesse:g}x10 {i}", f"Gewindeeinsatz M{groesse:g} {i}"):
            t = _teil(name, 0.002, 100.0, verbindung=True, d=groesse if "Schraube" in name else None)
            t.schwerpunkt = np.array([x, 0.0, 105.0])
            m.teile[name] = t
            mit.append(name)
    m.kanten[frozenset(("Lampe", "Halter (Druck)"))] = {"a": "Lampe", "b": "Halter (Druck)", "verbinde": True,
                                                         "gelenk": False, "kontakt": True}
    m.verbindungen.append({"art": "schraube", "a": "Lampe", "b": "Halter (Druck)", "mit": mit, "zeile": 7})
    return m


def _urteile(kat, groesse, material, kraft_n):
    m = _modell(groesse, material)
    sz = Szenario("Zug", lasten=[Last(["Lampe"], np.array([0.0, 0.0, -kraft_n]))])
    s = s0.rechne(m, sz, kat, rollen=False)
    e = bewertung.bewerte(sz, s, None, [], m)
    # nur die Urteile zum Einsatz (die Schraube selbst kann bei großer Last zusätzlich melden)
    return s["schrauben"][0], [u for u in e["urteile"] if u["text"].startswith("Gewindeeinsatz")], e


@pytest.mark.parametrize("kraft, ampel", [(500.0, None), (1000.0, "gelb"), (3000.0, "rot")])
def test_einsatz_nachweis_m3_petg(kat, kraft, ampel):
    s, ur, e = _urteile(kat, 3, "petg", kraft)
    ein = s["einsatz"]
    zug = (kraft + 2.0 * 9.81) / 2  # Last und Eigengewicht der Lampe auf zwei Schrauben
    assert s["kraft_axial"] == pytest.approx(zug, abs=0.5)
    assert ein["auszug_n"] == 1167 and ein["sicherheit"] == pytest.approx(1167 / zug, rel=0.01)
    assert ein["teil"] == "Gewindeeinsatz M3 1" and "CNC Kitchen" in ein["quelle"]
    if ampel is None:
        assert ur == []  # Sicherheit über 4 (Ziel für Druckteile): nichts zu melden
    else:
        (u,) = ur
        assert u["ampel"] == ampel and u["ziel"] == 4.0 and u["auszug_n"] == 1167
        assert u["text"].startswith("Gewindeeinsatz M3 in Halter (Druck)")
        assert "Auszugkraft 1.167 N" in u["text"] and "mehr Wände und Füllung" in u["loesung"]
        assert e["ampel"] == ampel


def test_einsatz_ohne_belegten_wert_bleibt_grau(kat):
    s, ur, _ = _urteile(kat, 5, "petg", 400.0)
    assert s["einsatz"]["auszug_n"] is None and s["einsatz"]["sicherheit"] is None
    (u,) = ur
    assert u["ampel"] == "grau" and "Auszugkraft für M5 in petg nicht belegt" in u["text"]
    # abgelesene Werte sagen es im Urteil
    s, ur, _ = _urteile(kat, 6, "pla", 8000.0)
    (u,) = ur
    assert u["ampel"] == "rot" and "aus einem Diagramm abgelesen" in u["text"]


def test_ohne_einsatz_wie_bisher(kat):
    m = _modell(3, "petg")
    v = m.verbindungen[0]
    v["mit"] = [n for n in v["mit"] if "Gewindeeinsatz" not in n]
    sz = Szenario("Zug", lasten=[Last(["Lampe"], np.array([0.0, 0.0, -400.0]))])
    s = s0.rechne(m, sz, kat, rollen=False)
    assert "einsatz" not in s["schrauben"][0]
    ur = [u for u in bewertung.bewerte(sz, s, None, [], m)["urteile"] if u["art"] == "schraube"]
    assert len(ur) == 1 and ur[0]["ampel"] == "grau" and "Auszug nicht nachgewiesen" in ur[0]["text"]
