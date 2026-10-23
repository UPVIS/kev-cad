"""Bereich „Simulation“ (PLAN-SIMULATION.md): vom Klick zur Kraft, simulation.json (Operationen, Laden und
Zusammenführen mit model.py, Zuordnung nach Modelländerungen), Lager-API ``st.lager`` und Lager aus der App gegen die
Handrechnung (Balken auf zwei Stützen, beidseitig eingespannt, Kragarm; Halter an einer Lagerfläche im Bauteil-Nachweis
und in der FEM), „Grenze suchen“, Nachrichten SIM und SIM_JOB, MCP.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.protocol import (
    check_sim_app,
    check_sim_job,
    check_sim_message,
    pack_sim,
    pack_sim_job,
    sim_beispiel,
    sim_job_beispiel,
)
from kevcad_kernel.simulation import datei as dt
from kevcad_kernel.simulation import kraft as kr
from kevcad_kernel.statik import anbindung
from test_statik import laufe, szenario

G = 9.81

# ---------------------------------------------------------------------------------------------------------------------
# Vom Klick zur Kraft


def test_kraft_aus_klick_normale_achse_frei_kg():
    # Klick auf die Oberseite (Normale +z): „entlang der Normale“ drückt in das Teil hinein
    F = kr.kraft_aus({"art": "normale"}, 100, "N", normale=(0, 0, 1))
    assert F.tolist() == pytest.approx([0, 0, -100])
    F = kr.kraft_aus({"art": "normale", "umkehren": True}, 100, "N", normale=(0, 0, 2))
    assert F.tolist() == pytest.approx([0, 0, 100])  # zieht; Normale wird normiert
    # Seitenfläche, schräge Normale
    F = kr.kraft_aus({"art": "normale"}, 10, "N", normale=(1, 1, 0))
    assert F.tolist() == pytest.approx([-10 / math.sqrt(2), -10 / math.sqrt(2), 0])
    # Achse und Masse: 30 kg nach unten
    F = kr.kraft_aus({"art": "achse", "achse": "-z"}, 30, "kg")
    assert F.tolist() == pytest.approx([0, 0, -30 * G])
    assert kr.kraft_aus(None, 2, "kg").tolist() == pytest.approx([0, 0, -2 * G])  # kg ohne Richtung: nach unten
    # frei: Vektor oder Winkel (Azimut, Höhe), hin und zurück
    F = kr.kraft_aus({"art": "frei", "vektor": [3, 4, 0]}, 50, "N")
    assert F.tolist() == pytest.approx([30, 40, 0])
    F = kr.kraft_aus({"art": "frei", "azimut": 90, "hoehe": -45}, 10, "N")
    assert F.tolist() == pytest.approx([0, 10 / math.sqrt(2), -10 / math.sqrt(2)], abs=1e-9)
    assert kr.winkel_aus([0, 1, -1]) == pytest.approx((90.0, -45.0))
    # Fehler mit verständlichem Text
    with pytest.raises(kr.KraftFehler, match="angeklickte Fläche"):
        kr.kraft_aus({"art": "normale"}, 10, "N", normale=None)
    with pytest.raises(kr.KraftFehler, match="größer als 0"):
        kr.kraft_aus({"art": "achse", "achse": "+x"}, 0, "N")
    with pytest.raises(kr.KraftFehler, match="Achse"):
        kr.kraft_aus({"art": "achse", "achse": "q"}, 1, "N")


# ---------------------------------------------------------------------------------------------------------------------
# simulation.json: Operationen und Datei


def _ort_oben() -> dict:
    return {"flaeche": 5, "punkt": [40, 0, 104], "normale": [0, 0, 1],
            "signatur": {"t": "plane", "a": 1600.0, "n": [0, 0, 1], "c": [40, 0, 104]}}


def test_datei_operationen_und_stand(tmp_path):
    doc = dt.lies(tmp_path)
    assert doc["stand"] == 0 and doc["lastfaelle"] == []
    doc, m = dt.anwenden(doc, [
        {"op": "lastfall_neu", "name": "Aufstützen", "neigung": {"grad": 5, "richtung": "y"}},
        {"op": "last_setzen", "lastfall": "Aufstützen",
         "last": {"teil": "Halter", "ort": _ort_oben(), "richtung": {"art": "normale"}, "betrag": 30, "einheit": "kg"}},
        {"op": "lager_setzen", "lager": {"teil": "Halter", "art": "gleitend", "ort": _ort_oben()}},
        {"op": "abgeleitet", "id": "boden:Fuß", "aktiv": False},
        {"op": "topologie", "teil": "Halter", "einstellungen": {"behalten": 0.42, "bohrungen": False,
                                                                "schutz": [{"art": "index", "index": 7}]}},
    ])
    l = doc["lastfaelle"][0]
    assert l["neigung"] == {"grad": 5.0, "richtung": "+y"} and l["art"] == "statisch"
    last = l["lasten"][0]
    assert last["id"] == "L1" and last["kraft"] == pytest.approx([0, 0, -30 * G])
    assert doc["lager"][0]["id"] == "A1" and doc["lager"][0]["auf"] == "flaeche"
    assert doc["abgeleitet_aus"] == ["boden:Fuß"]
    assert doc["topologie"]["Halter"]["schutz"] == [{"art": "index", "index": 7}]
    assert "Last L1 auf Halter" in m[1]
    # kopieren, umbenennen (Topologie folgt), ändern, löschen
    doc["topologie"]["Halter"]["szenario"] = "Aufstützen"
    doc, _ = dt.anwenden(doc, [{"op": "lastfall_kopieren", "von": "Aufstützen", "name": "Aufstützen 2"},
                               {"op": "lastfall_umbenennen", "name": "Aufstützen", "neu": "Aufstützen 30 kg"},
                               {"op": "lastfall_setzen", "name": "Aufstützen 2",
                                "felder": {"fahrt": {"geschwindigkeit": 1, "bremsen": "abrupt"}, "art": "dynamisch"}},
                               {"op": "last_loeschen", "lastfall": "Aufstützen 2", "id": "L1"}])
    assert [x["name"] for x in doc["lastfaelle"]] == ["Aufstützen 30 kg", "Aufstützen 2"]
    assert doc["topologie"]["Halter"]["szenario"] == "Aufstützen 30 kg"
    assert doc["lastfaelle"][1]["fahrt"]["bremsen"] == "abrupt" and doc["lastfaelle"][1]["lasten"] == []
    assert doc["lastfaelle"][1]["kopie_von"] == "Aufstützen"
    # ein Fehler verwirft alles (nichts halb angewandt)
    vorher = json.dumps(doc, sort_keys=True)
    with pytest.raises(dt.SimulationFehler, match="gibt es schon"):
        dt.anwenden(doc, [{"op": "lastfall_neu", "name": "Neu"}, {"op": "lastfall_neu", "name": "Neu"}])
    with pytest.raises(dt.SimulationFehler, match="gleitendes Lager"):
        dt.anwenden(doc, [{"op": "lager_setzen", "lager": {"teil": "Halter", "art": "gleitend",
                                                            "ort": {"punkt": [0, 0, 0]}}}])
    assert json.dumps(doc, sort_keys=True) == vorher
    # schreiben und lesen: Stand zählt hoch, Datei liegt neben model.py
    d1 = dt.schreibe(tmp_path, doc)
    d2 = dt.schreibe(tmp_path, dt.lies(tmp_path), von="agent")
    assert (d1["stand"], d2["stand"]) == (1, 2) and dt.lies(tmp_path)["von"] == "agent"
    assert dt.lies(tmp_path)["lastfaelle"] == doc["lastfaelle"]
    # kaputte Datei: leer mit Fehlertext
    (tmp_path / "simulation.json").write_text("{kaputt")
    assert "nicht lesbar" in dt.lies(tmp_path)["fehler"]


def test_kopie_eines_szenarios_aus_model_py():
    from kevcad_kernel.statik.szenario import szenario_aus

    kurz = szenario_aus({"name": "Bremsen aus 1 m/s", "geschwindigkeit": 1, "bremsen": "abrupt",
                         "neigung": {"grad": 4, "richtung": "-y"},
                         "lasten": [{"teil": "Ball", "kg": 6}, {"teil": "Rohr", "kraft": [100, 0, 0],
                                                                "punkt": [1, 2, 3], "gegen": "Ball"}]},
                        "modell").kurz()
    doc, m = dt.anwenden(dt.leer(), [{"op": "lastfall_kopieren", "von": "Bremsen aus 1 m/s",
                                      "name": "Bremsen (App)"}], {"Bremsen aus 1 m/s": kurz})
    l = doc["lastfaelle"][0]
    assert l["kopie_von"] == "Bremsen aus 1 m/s" and l["art"] == "dynamisch"
    assert l["fahrt"]["geschwindigkeit"] == 1 and l["fahrt"]["bremsen"] == "abrupt"
    assert l["neigung"] == {"grad": 4.0, "richtung": "-y"}
    assert l["lasten"][0]["einheit"] == "kg" and l["lasten"][0]["kraft"] == pytest.approx([0, 0, -6 * G])
    assert l["lasten"][1]["gegen"] == "Ball" and l["lasten"][1]["kraft"] == pytest.approx([100, 0, 0])
    assert l["lasten"][1]["ort"]["punkt"] == [1, 2, 3]


# ---------------------------------------------------------------------------------------------------------------------
# Laden und Zusammenführen mit model.py

ZUSAMMEN = '''
from build123d import *
from kevcad import lager, show, befestigt
import kevcad.statik as st

show(Pos(-5, 0, 100) * Box(10, 200, 200), "Kulisse/Wand", kulisse=True)
arm = Pos(40, 0, 100) * Box(80, 20, 8)
show(lager.druckteil(arm, "Halter", material="petg", ausrichtung="-z"), "Halter", material="petg")
befestigt("Halter", grund="an die Wand geschraubt")
st.szenario("Aufstützen")
st.last("Halter", kraft=(0, 0, -10), punkt=(70, 0, 104))
st.szenario("Nur model.py")
st.last("Halter", kraft=(0, 0, -5), punkt=(70, 0, 104))
'''


def _sim(tmp: Path, lastfaelle: list[dict], lager: list[dict] | None = None, aus: list[str] | None = None) -> None:
    doc = dt.leer()
    ops = []
    for l in lastfaelle:
        ops.append({"op": "lastfall_neu", **{k: v for k, v in l.items() if k != "lasten"}})
        for x in l.get("lasten") or []:
            ops.append({"op": "last_setzen", "lastfall": l["name"], "last": x})
    for x in lager or []:
        ops.append({"op": "lager_setzen", "lager": x})
    for a in aus or []:
        ops.append({"op": "abgeleitet", "id": a, "aktiv": False})
    doc, _ = dt.anwenden(doc, ops)
    dt.schreibe(tmp, doc)


def test_laden_und_zusammenfuehren(tmp_path):
    """App-Lastfälle kommen bei jedem Lauf dazu; gleicher Name wie in model.py: die App gewinnt, mit Hinweis."""
    _sim(tmp_path, [{"name": "Aufstützen", "lasten": [{"teil": "Halter", "ort": {"punkt": [70, 0, 104]},
                                                        "richtung": {"art": "achse", "achse": "-z"},
                                                        "betrag": 3, "einheit": "kg"}]},
                    {"name": "Nur App", "art": "dynamisch", "beschleunigung": [-2, 0, 0]}])
    _, check, _ = laufe(tmp_path, ZUSAMMEN, strikt=False)
    namen = [e["name"] for e in check["statik"]["szenarien"]]
    assert {"Eigengewicht", "Aufstützen", "Nur model.py", "Nur App"} <= set(namen)
    assert namen.count("Aufstützen") == 1
    e = szenario(check, "Aufstützen")
    assert e["szenario"]["quelle"] == "app"
    assert e["lasten"][0]["kraft"] == pytest.approx([0, 0, -3 * G]) and e["lasten"][0]["id"] == "L1"
    assert szenario(check, "Nur model.py")["szenario"]["quelle"] == "modell"
    assert szenario(check, "Nur App")["szenario"]["art"] == "dynamisch"
    sim = check["statik"]["simulation"]
    assert any("ersetzt den gleichnamigen aus model.py" in h for h in sim["hinweise"])
    assert sim["ersetzt"][0]["name"] == "Aufstützen" and sim["zustand"]["lasten"]["L1"]["zustand"] == "ok"
    # Kurzfassung im CHECK und STATICS kennen die Quelle
    from kevcad_kernel.protocol import check_statics_message, pack_statics

    h = pack_statics(check["statik"], run=1)
    assert not check_statics_message(h)
    assert next(x for x in h["szenarien"] if x["name"] == "Aufstützen")["quelle"] == "app"
    # Ohne Lauf neu rechnen (App ändert simulation.json): neuer Lastfall ist sofort da
    _sim(tmp_path, [{"name": "Später", "lasten": [{"teil": "Halter", "ort": {"punkt": [70, 0, 104]},
                                                    "richtung": {"art": "achse", "achse": "-z"}, "betrag": 50}]}])
    erg = anbindung.neu_mit_simulation()
    assert "Später" in [x["name"] for x in erg["szenarien"]] and "Nur App" not in [x["name"] for x in erg["szenarien"]]
    assert any(s.name == "Später" for s in anbindung.LETZTER.szenarien)


# ---------------------------------------------------------------------------------------------------------------------
# Zuordnung nach Modelländerungen

BLOCK = '''
from build123d import *
from kevcad import lager, show

show(lager.druckteil(FORM, "Block", material="petg"), "Block", material="petg")
'''


def _flaeche(k, n) -> int:
    return next(i for i, f in enumerate(k.flaechen) if f.get("t") == "plane"
                and np.allclose(f.get("n") or [0, 0, 0], n, atol=1e-6))


def test_zuordnung_nach_modellaenderung(tmp_path):
    from kevcad_kernel.simulation import zuordnung

    _, _, runner = laufe(tmp_path, BLOCK.replace("FORM", "Pos(0, 0, 10) * Box(40, 30, 20)"), strikt=False)
    k = anbindung.LETZTER.koerper["Block"]
    i = _flaeche(k, [0, 0, 1])
    ort = {"flaeche": i, "punkt": [10, 5, 20], "normale": [0, 0, 1], "signatur": dict(k.flaechen[i])}
    doc = {"lastfaelle": [{"name": "Druck", "lasten": [{"id": "L1", "teil": "Block", "ort": ort,
                                                        "richtung": {"art": "normale"}, "betrag": 100, "einheit": "N"}]}],
           "lager": [{"id": "A1", "teil": "Block", "art": "fest", "auf": "flaeche",
                      "ort": {"flaeche": _flaeche(k, [0, 0, -1]),
                              "signatur": dict(k.flaechen[_flaeche(k, [0, 0, -1])])}}]}
    v = zuordnung.vorbereiten(doc, anbindung.LETZTER.koerper)
    assert v.zustand["lasten"]["L1"]["zustand"] == "ok" and v.szenarien[0]["lasten"][0]["kraft"] == [0, 0, -100]
    assert v.lager[0].netz is not None and len(v.lager[0].netz[1]) >= 2
    # 1. höher: Oberseite wandert um 10 mm nach oben (gleiche Nummer), der Punkt wandert mit
    laufe(tmp_path, BLOCK.replace("FORM", "Pos(0, 0, 15) * Box(40, 30, 30)"), run=2, strikt=False)
    v = zuordnung.vorbereiten(doc, anbindung.LETZTER.koerper)
    z = v.zustand["lasten"]["L1"]
    assert z["zustand"] == "ok" and z["punkt"] == pytest.approx([10, 5, 30])
    # 2. Bohrung und Fase: andere Flächennummern, Oberseite neu zugeordnet
    form = ("Pos(0, 0, 10) * Box(40, 30, 20) - Pos(-12, 0, 10) * Cylinder(4, 20)")
    laufe(tmp_path, BLOCK.replace("FORM", f"chamfer(({form}).edges().group_by(Axis.X)[0], 2)"), run=3, strikt=False)
    k3 = anbindung.LETZTER.koerper["Block"]
    v = zuordnung.vorbereiten(doc, anbindung.LETZTER.koerper)
    z = v.zustand["lasten"]["L1"]
    oben = _flaeche(k3, [0, 0, 1])
    assert z["zustand"] in ("ok", "neu") and z["flaeche"] == oben
    if oben != i:
        assert z["zustand"] == "neu" and f"Fläche {i} → {oben}" in z["text"]
    assert v.szenarien[0]["lasten"][0]["kraft"] == pytest.approx([0, 0, -100])
    # 3. Zylinder statt Quader: keine ebene Oberseite in der Nähe mehr → nicht mehr zuordenbar, zählt nicht mit
    laufe(tmp_path, BLOCK.replace("FORM", "Pos(0, 0, 10) * Sphere(15)"), run=4, strikt=False)
    v = zuordnung.vorbereiten(doc, anbindung.LETZTER.koerper)
    assert v.zustand["lasten"]["L1"]["zustand"] == "fehlt" and v.szenarien[0]["lasten"] == []
    assert "passt zu keiner Fläche" in v.zustand["lasten"]["L1"]["text"]
    assert v.zustand["lager"]["A1"]["zustand"] == "fehlt" and v.lager == []
    assert "nicht mehr zuordenbar" in v.hinweise[0]
    # 4. Teil umbenannt: über den letzten Namensteil gefunden
    doc2 = {"lastfaelle": [{"name": "Druck", "lasten": [{"id": "L1", "teil": "Alt/Block", "ort": {},
                                                         "richtung": {"art": "achse"}, "betrag": 1}]}]}
    v = zuordnung.vorbereiten(doc2, anbindung.LETZTER.koerper)
    assert v.zustand["lasten"]["L1"]["zustand"] == "neu" and "Block" in v.zustand["lasten"]["L1"]["text"]
    runner  # noqa: B018


# ---------------------------------------------------------------------------------------------------------------------
# Lager-API gegen die Handrechnung

ROHR = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

rohr = lager.teil("rohr-en10220-21.3x2.0")
show(Pos(0, 0, 500) * Rot(0, 90, 0) * rohr.verbauen(laenge=1000, name="Rohr"), "Rohr")
LAGER
st.szenario("Last")
st.last("Rohr", kraft=(0, 0, -FKRAFT), punkt=(XLAST, 0, 500))
'''


def _durchbiegung(e: dict, name: str = "Rohr") -> float:
    s = next(s for s in e["staebe"] if s["name"] == name)
    return max(abs(v[2]) for v in s["verschiebung"])


def _rohr(tmp: Path, lager: str, F: float = 200.0, x: float = 500.0, run: int = 1) -> tuple[dict, float, float, float]:
    _, check, _ = laufe(tmp, ROHR.replace("LAGER", lager).replace("FKRAFT", str(F)).replace("XLAST", str(x)),
                        run=run, strikt=False)
    s = anbindung.LETZTER.modell.staebe["Rohr"]
    EI = float(s.werkstoff.E) * float(s.q.I_lang)
    q = anbindung.LETZTER.modell.teile["Rohr"].masse_kg * G / s.laenge
    return check, EI, q, s.laenge


def test_lager_zwei_stuetzen_gelenkig_und_gleitend(tmp_path):
    """Rohr 1000 mm frei im Raum, ``st.lager`` gelenkig am linken Ende und gleitend (hält nur senkrecht) am rechten:
    Träger auf zwei Stützen. Handrechnung w = F L³ / (48 E I) + 5 q L⁴ / (384 E I), je Lager die halbe Last."""
    lager = ('st.lager("Rohr", punkt=(0, 0, 500), art="gelenkig")\n'
             'st.lager("Rohr", punkt=(1000, 0, 500), art="gleitend", normale=(0, 0, 1))')
    check, EI, q, L = _rohr(tmp_path, lager)
    e = szenario(check, "Last")
    w_hand = 200 * L ** 3 / (48 * EI) + 5 * q * L ** 4 / (384 * EI)
    assert _durchbiegung(e) == pytest.approx(w_hand, rel=0.02)
    lager_kraft = {a["teil"]: a["kraft"] for a in e["auflager"]}
    assert set(lager_kraft) == {"Lager: M1", "Lager: M2"}
    R = 200 / 2 + q * L / 2
    assert lager_kraft["Lager: M1"][2] == pytest.approx(R, rel=0.01)
    assert lager_kraft["Lager: M2"][2] == pytest.approx(R, rel=0.01)
    assert {a["art"] for a in e["auflager"]} == {"gelenkig", "gleitend"}
    # gleitend hält nicht längs: eine Kraft längs des Rohrs nimmt allein das gelenkige Lager
    check2, *_ = _rohr(tmp_path, lager + '\nst.szenario("Längs")\nst.last("Rohr", kraft=(50, 0, 0), '
                                          'punkt=(500, 0, 500))', run=2)
    e2 = szenario(check2, "Längs")
    kx = {a["teil"]: a["kraft"][0] for a in e2["auflager"]}
    assert kx["Lager: M1"] == pytest.approx(-50, abs=0.5) and kx["Lager: M2"] == pytest.approx(0, abs=0.5)
    print(f"Zwei Stützen: w = {_durchbiegung(e):.3f} mm (Hand {w_hand:.3f}), R = {lager_kraft['Lager: M1'][2]:.2f} N")


def test_lager_aus_der_app_beidseitig_fest_und_kragarm(tmp_path):
    """Dieselben Lager aus simulation.json (App): beidseitig fest w = F L³ / (192 E I) + q L⁴ / (384 E I); nur links
    fest (Kragarm), Last an der Spitze: w = F L³ / (3 E I) + q L⁴ / (8 E I)."""
    def punkt(x: float) -> dict:
        return {"teil": "Rohr", "art": "fest", "auf": "punkt", "ort": {"punkt": [x, 0, 500]}}

    _sim(tmp_path, [], [punkt(0), punkt(1000)])
    check, EI, q, L = _rohr(tmp_path, "")
    e = szenario(check, "Last")
    w_hand = 200 * L ** 3 / (192 * EI) + q * L ** 4 / (384 * EI)
    assert _durchbiegung(e) == pytest.approx(w_hand, rel=0.02)
    assert check["statik"]["simulation"]["zustand"]["lager"]["A1"]["zustand"] == "ok"
    _sim(tmp_path, [], [punkt(0)])
    check, EI, q, L = _rohr(tmp_path, "", F=20.0, x=1000.0, run=2)
    w_hand = 20 * L ** 3 / (3 * EI) + q * L ** 4 / (8 * EI)
    assert _durchbiegung(szenario(check, "Last")) == pytest.approx(w_hand, rel=0.02)
    print(f"Kragarm: w = {_durchbiegung(szenario(check, 'Last')):.2f} mm (Hand {w_hand:.2f})")


HALTER_LAGER = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

arm = Pos(40, 0, 100) * Box(80, 20, 8)
show(lager.druckteil(arm, "Wandhalter (Druck)", material="petg", ausrichtung="-x"), "Wandhalter (Druck)",
     material="petg")
st.lager("Wandhalter (Druck)", flaeche=arm.faces().sort_by(Axis.X)[0], art=ART)
st.szenario("Haken 2 kg")
st.last("Wandhalter (Druck)", kraft=(0, 0, -20), punkt=(78, 0, 100))
'''


def test_lager_an_flaeche_bauteil_und_festkoerper(tmp_path, monkeypatch):
    """Wandhalter ohne Wand, nur mit ``st.lager`` an der Stirnfläche (x = 0): Kragträger S0 und Festkörper-FEM halten
    ihn dort wie an der Wand; Handrechnung der Schichtfuge q f / (M / W) wie in test_festkoerper."""
    from test_festkoerper import _auftrag_und_prozess, mechanik

    monkeypatch.setenv("KEVCAD_FESTKOERPER_CACHE", str(tmp_path / "fem-cache"))
    _, check, _ = laufe(tmp_path, HALTER_LAGER.replace("ART", '"fest"'))
    e = szenario(check, "Haken 2 kg")
    b = next(b for b in e["bauteile"] if b["teil"] == "Wandhalter (Druck)")
    assert b["nachbarn"] == ["Lager: M1"]
    me = mechanik("petg")
    q, f = float(me["quer_zur_schicht"]), float(me["zugfestigkeit"])
    s_hand = q * f / (20.0 * 78.0 / (20 * 8 ** 2 / 6))
    assert b["sicherheit"] == pytest.approx(s_hand, rel=0.15)
    assert not (e.get("s0") or {}).get("kippen")  # gelagert: kippt nicht
    a, out, _ = _auftrag_und_prozess(tmp_path, {"auto": True})
    r = out["faelle"][0]
    assert r["stand"] == "done", r
    assert r["lager"] == ["Lager: M1"] and r["lagerflaeche_mm2"] == pytest.approx(160, rel=0.05)
    assert r["sicherheit"] == pytest.approx(s_hand, rel=0.08)
    print(f"Halter an Lagerfläche: S0 {b['sicherheit']:.2f}, FEM {r['sicherheit']:.2f}, Hand {s_hand:.2f}")
    # nur gleitend: längs der Fläche nicht gehalten
    laufe(tmp_path, HALTER_LAGER.replace("ART", '"gleitend"'), run=2)
    _, out, _ = _auftrag_und_prozess(tmp_path, {"auto": True})
    assert out["faelle"][0]["stand"] == "failed" and "nur gleitende Lager" in out["faelle"][0]["meldung"]


def test_abgeleitetes_lager_ausschalten(tmp_path):
    """Ein Rohr, das auf dem Boden liegt, ist abgeleitet gelagert (boden:Rohr); ausgeschaltet trägt nur das
    ausdrückliche Lager."""
    code = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

rohr = lager.teil("rohr-en10220-21.3x2.0")
show(Pos(0, 0, 10.65) * Rot(0, 90, 0) * rohr.verbauen(laenge=1000, name="Rohr"), "Rohr")
st.szenario("Last")
st.last("Rohr", kraft=(0, 0, -100), punkt=(500, 0, 10.65))
'''
    _, check, _ = laufe(tmp_path, code, strikt=False)
    ab = check["statik"]["simulation"]["abgeleitet"]
    assert any(a["id"] == "boden:Rohr" and a["aktiv"] for a in ab)
    assert any(a["teil"] == "Boden" for a in szenario(check, "Last")["auflager"])
    _sim(tmp_path, [], [{"teil": "Rohr", "art": "fest", "auf": "punkt", "ort": {"punkt": [0, 0, 10.65]}}],
         aus=["boden:Rohr"])
    _, check, _ = laufe(tmp_path, code, run=2, strikt=False)
    e = szenario(check, "Last")
    assert {a["teil"] for a in e["auflager"]} == {"Lager: A1"}
    assert next(a for a in check["statik"]["simulation"]["abgeleitet"] if a["id"] == "boden:Rohr")["aktiv"] is False


# ---------------------------------------------------------------------------------------------------------------------
# Grenze suchen


def test_grenze_last_und_neigung(tmp_path):
    from kevcad_kernel.simulation.grenze import suche
    from kevcad_kernel.statik.rechnen import rechne_alles

    lager = ('st.lager("Rohr", punkt=(0, 0, 500), art="gelenkig")\n'
             'st.lager("Rohr", punkt=(1000, 0, 500), art="gleitend", normale=(0, 0, 1))')
    _rohr(tmp_path, lager, F=200.0)
    g = suche(anbindung.LETZTER, "Last", "last")
    ziel = next(w for w in g["werte"] if w["kriterium"] == "Ziel-Sicherheit")
    bruch = next(w for w in g["werte"] if w["kriterium"].startswith("Bruch"))
    assert ziel["grenze"] < bruch["grenze"] and g["rechnungen"] < 120
    # Probe: bei λ ist die Ausnutzung 1 (Sicherheit = Ziel)
    import copy

    sz = copy.deepcopy(next(s for s in anbindung.LETZTER.szenarien if s.name == "Last"))
    for l in sz.lasten:
        l.kraft = np.asarray(l.kraft) * ziel["grenze"]
    e = rechne_alles(anbindung.LETZTER.modell, [sz], anbindung.LETZTER.katalog, anbindung.LETZTER.koerper,
                     alternativen=False)["szenarien"][0]
    assert max(t["ausnutzung"] for t in e["teile"]) == pytest.approx(1.0, abs=0.01)
    assert "fachen" in g["text"]
    # Neigung: Klotz auf dem Boden kippt bei atan(b/2 / h) (Schwerpunkt mittig)
    code = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

show(Pos(0, 0, 100) * Box(40, 40, 200), "Klotz", material="eiche")
st.szenario("Schräge")
st.neigung(1, "+x")
'''
    laufe(tmp_path, code, run=3, strikt=False)
    g = suche(anbindung.LETZTER, "Schräge", "neigung")
    kipp = next(w for w in g["werte"] if w["kriterium"] == "Kippen")
    assert kipp["grenze"] == pytest.approx(math.degrees(math.atan(20 / 100)), abs=0.3)


# ---------------------------------------------------------------------------------------------------------------------
# Nachrichten


def test_nachrichten_sim_und_job():
    h = pack_sim(sim_beispiel(), reply_to="r1")
    assert not check_sim_message(h) and h["reply_to"] == "r1"
    kaputt = json.loads(json.dumps(h))
    kaputt["lastfaelle"][0]["lasten"][0]["zustand"] = "vielleicht"
    assert check_sim_message(kaputt)
    for st in ("done", "laeuft"):
        assert not check_sim_job(pack_sim_job(sim_job_beispiel(st)))
    assert not check_sim_app({"type": "SIM_EDIT", "ops": [{"op": "lastfall_neu", "name": "x"}]})
    assert check_sim_app({"type": "SIM_EDIT", "ops": [{"op": "zaubern"}]})
    assert check_sim_app({"type": "SIM_RUN", "was": "grenze", "grenze": "farbe"})
    assert not check_sim_app({"type": "SIM_RUN", "was": "grenze", "grenze": "neigung", "lastfall": "x"})


def test_fixtures_aktuell():
    """Die Testdateien der App entsprechen dem Generator."""
    r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "tools/make_simulation_fixtures.py"),
                        "--pruefen"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit: SIM_EDIT, SIM, STATICS, SIM_RUN, SIM_JOB


@pytest.fixture(scope="module")
def env():
    import os
    import tempfile

    from app_testutil import FakeApp, make_runtime

    tmp = Path(tempfile.mkdtemp(prefix="kcsim", dir=tempfile.gettempdir()))
    os.environ["KEVCAD_FESTKOERPER_CACHE"] = str(tmp / "fem-cache")
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_laufzeit_sim_edit_und_auftraege(env):
    from test_festkoerper import _projekt_mit_petg

    rt, app = env["rt"], env["app"]
    pfad = env["tmp"] / "Halter"
    _projekt_mit_petg(rt, pfad)
    assert rt.model_write(HALTER_LAGER.replace("ART", '"fest"'))["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], (res.get("error"), res.get("warnings"))
    _, _, sim, _ = app.wait_for(lambda h: h["type"] == "SIM", start=start, timeout=60)
    assert not check_sim_message(sim) and sim["lastfaelle"] == []
    assert sim["modell_lager"][0]["id"] == "M1" and sim["modell_lager"][0]["art"] == "fest"
    # Kevin legt in der App ein Lager und einen Lastfall mit einer Kraft an (SIM_EDIT): ACK, STATICS, SIM
    start = app.mark()
    app.send({"type": "SIM_EDIT", "seq": 1, "id": "e1", "basis": sim["stand"], "ops": [
        {"op": "lager_setzen", "lager": {"teil": "Wandhalter (Druck)", "art": "gelenkig", "auf": "punkt",
                                         "ort": {"punkt": [0, 0, 100]}}},
        {"op": "lastfall_neu", "name": "Aufstützen"},
        {"op": "last_setzen", "lastfall": "Aufstützen",
         "last": {"teil": "Wandhalter (Druck)", "ort": {"punkt": [70, 0, 104], "normale": [0, 0, 1]},
                  "richtung": {"art": "normale"}, "betrag": 1, "einheit": "kg"}}]})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "e1", start=start, timeout=60)
    assert ack["ok"], ack
    _, _, st, _ = app.wait_for(lambda h: h["type"] == "STATICS" and any(
        e["name"] == "Aufstützen" for e in h["szenarien"]), start=start, timeout=60)
    e = next(e for e in st["szenarien"] if e["name"] == "Aufstützen")
    assert e["quelle"] == "app" and e["lasten"][0]["id"] == "L1"
    assert e["lasten"][0]["kraft"] == pytest.approx([0, 0, -G], abs=0.01)
    _, _, sim2, _ = app.wait_for(lambda h: h["type"] == "SIM" and h["stand"] > sim["stand"], start=start, timeout=30)
    assert not check_sim_message(sim2)
    assert sim2["lastfaelle"][0]["name"] == "Aufstützen" and len(sim2["lager"]) == 1
    assert sim2["lastfaelle"][0]["lasten"][0]["zustand"] == "ok" and sim2["lastfaelle"][0]["gerechnet"]
    assert json.loads((pfad / "simulation.json").read_text())["stand"] == sim2["stand"]
    # veralteter Stand: abgelehnt
    start = app.mark()
    app.send({"type": "SIM_EDIT", "seq": 2, "id": "e2", "basis": 0, "ops": [{"op": "lastfall_neu", "name": "X"}]})
    _, _, ack, _ = app.wait_for(lambda h: h["type"] == "ACK" and h.get("reply_to") == "e2", start=start, timeout=30)
    assert not ack["ok"] and "inzwischen geändert" in ack["message"]
    # Grenze suchen (SIM_RUN): SIM_JOB läuft, dann fertig mit Ergebnis
    start = app.mark()
    app.send({"type": "SIM_RUN", "seq": 3, "id": "r1", "was": "grenze", "grenze": "last", "lastfall": "Aufstützen"})
    _, _, job, _ = app.wait_for(lambda h: h["type"] == "SIM_JOB" and h["stand"] != "laeuft", start=start, timeout=120)
    assert not check_sim_job(job) and job["stand"] == "done", job
    assert job["ergebnis"]["werte"] and "fachen" in job["text"]
    # MCP-Sicht: dieselben Daten, ändern wie die App
    liste = rt.simulation_liste()
    assert liste["ok"] and liste["lastfaelle"][0]["lasten"][0]["zustand"] == "ok"
    res = rt.simulation_aendern([{"op": "lastfall_kopieren", "von": "Eigengewicht", "name": "Eigengewicht (App)"}])
    assert res["ok"] and res["gerechnet"], res
    assert rt.statik("Eigengewicht (App)")["ok"]
    # Rechnen per Knopf (S0, S1), wartend wie MCP
    r = rt.simulation_rechnen("rechnen", warten=True)
    assert r["ok"] and r["auftrag"] >= 2
    # Versionen: simulation.json gehört zum Projekt (nicht ausgeschlossen)
    from kevcad_kernel.versionen.git import AUSSCHLUSS

    assert "simulation.json" not in AUSSCHLUSS
    time.sleep(0.2)


def test_mcp_simulation():
    import anyio
    from mcp_testutil import start_server, with_client

    server, fake = start_server()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        res = call("simulation_liste")
        assert not res.is_error and "Lastfälle aus der App" in res.content[0].text
        res = call("simulation_aendern", {"ops": [{"op": "lastfall_neu", "name": "A"}]})
        assert not res.is_error and "lastfall_neu ausgeführt" in res.content[0].text
        res = call("simulation_rechnen", {"was": "grenze", "lastfall": "A", "grenze": "last"})
        assert not res.is_error and "1,24-fachen" in res.content[0].text
        aufruf = next(a for n, a, _ in fake.calls if n == "simulation_rechnen")
        assert aufruf == ("grenze", "A", None, False, "last")
        assert next(a for n, a, _ in fake.calls if n == "simulation_aendern")[0] == [{"op": "lastfall_neu", "name": "A"}]
    finally:
        server.stop()
