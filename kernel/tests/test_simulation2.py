"""Bereich „Simulation“, offene Grenzen geschlossen (PLAN-SIMULATION.md, Zweig ``simulation2``): Lager je Lastfall,
gleitende Lager in beliebiger Richtung (Stabwerk und FEM), gelenkige Lager auf einer Fläche in der FEM (RBE3-artig),
Last auf der ganzen Fläche (gleichmäßig und als Druck), Untergrund je Lastfall im Ablauf, „Grenze suchen“ mit der FEM.
Wo es um Mechanik geht, gegen die Handrechnung.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.simulation import datei as dt
from kevcad_kernel.simulation import kraft as kr
from kevcad_kernel.statik import anbindung
from test_simulation import ROHR, _durchbiegung, _rohr, _sim
from test_statik import laufe, szenario

G = 9.81


# ---------------------------------------------------------------------------------------------------------------------
# Format: Lager je Lastfall, Gleitrichtung, Last auf der ganzen Fläche


def _ort(flaeche: int = 5, a: float = 800.0, n=(0, 0, 1)) -> dict:
    return {"flaeche": flaeche, "punkt": [40, 0, 60], "normale": list(n),
            "signatur": {"t": "plane", "a": a, "n": list(n), "c": [40, 0, 60]}}


def test_format_lager_je_lastfall_und_gleiten():
    doc, m = dt.anwenden(dt.leer(), [
        {"op": "lastfall_neu", "name": "A"}, {"op": "lastfall_neu", "name": "B"},
        {"op": "lager_setzen", "lager": {"teil": "Halter", "art": "fest", "ort": _ort(), "szenarien": ["A"]}},
        {"op": "lager_setzen", "lager": {"teil": "Halter", "art": "gleitend", "ort": _ort(),
                                         "gleiten": {"art": "richtung", "richtung": [0, 2, 0], "quelle": "kante",
                                                     "kante": 7}}},
        {"op": "lager_setzen", "lager": {"teil": "Halter", "art": "gleitend", "ort": {"punkt": [0, 0, 0]},
                                         "gleiten": "-x"}},
    ])
    a1, a2, a3 = doc["lager"]
    assert a1["szenarien"] == ["A"] and "nur in „A“" in m[2]
    assert a2["szenarien"] is None and a2["gleiten"] == {"art": "richtung", "richtung": [0, 1, 0], "quelle": "kante",
                                                        "kante": 7}
    assert a3["gleiten"]["richtung"] == [-1, 0, 0] and a3["gleiten"]["quelle"] == "achse"  # ohne Fläche: Richtung reicht
    # umbenennen folgt, löschen lässt das Lager „in keinem Lastfall“
    doc, _ = dt.anwenden(doc, [{"op": "lastfall_umbenennen", "name": "A", "neu": "A2"}])
    assert doc["lager"][0]["szenarien"] == ["A2"]
    doc, m = dt.anwenden(doc, [{"op": "lastfall_loeschen", "name": "A2"}])
    assert doc["lager"][0]["szenarien"] == [] and "in keinem Lastfall" in m[0]
    # unbekannter Lastfall: abgelehnt, sobald die Szenarien des Laufs bekannt sind
    with pytest.raises(dt.SimulationFehler, match="gibt es nicht"):
        dt.anwenden(doc, [{"op": "lager_setzen", "lager": {"teil": "Halter", "art": "fest", "ort": _ort(),
                                                            "szenarien": ["Zauber"]}}], {"Eigengewicht": {}})
    # gleiten nur für gleitende Lager; ohne Normale und ohne Richtung abgelehnt
    doc2, _ = dt.anwenden(dt.leer(), [{"op": "lager_setzen", "lager": {"teil": "T", "art": "fest", "ort": _ort(),
                                                                       "gleiten": "+x"}}])
    assert "gleiten" not in doc2["lager"][0]
    with pytest.raises(dt.SimulationFehler, match="Gleitrichtung"):
        dt.anwenden(dt.leer(), [{"op": "lager_setzen", "lager": {"teil": "T", "art": "gleitend",
                                                                  "ort": {"punkt": [0, 0, 0]}}}])


def test_format_last_auf_der_ganzen_flaeche():
    # Druck 0,05 N/mm² auf 800 mm², senkrecht in die Fläche: 40 N
    doc, m = dt.anwenden(dt.leer(), [
        {"op": "lastfall_neu", "name": "Druck"},
        {"op": "last_setzen", "lastfall": "Druck", "last": {"teil": "Halter", "ort": _ort(), "verteilung": "flaeche",
                                                           "richtung": {"art": "normale"}, "betrag": 0.05,
                                                           "einheit": "N/mm²"}},
        {"op": "last_setzen", "lastfall": "Druck", "last": {"teil": "Halter", "ort": _ort(), "verteilung": "flaeche",
                                                           "richtung": {"art": "achse", "achse": "+y"},
                                                           "betrag": 30, "einheit": "N"}}])
    l1, l2 = doc["lastfaelle"][0]["lasten"]
    assert l1["einheit"] == "N/mm2" and l1["verteilung"] == "flaeche" and l1["kraft"] == pytest.approx([0, 0, -40])
    assert "N/mm² auf die ganze Fläche = 40 N" in m[1]
    assert l2["kraft"] == pytest.approx([0, 30, 0]) and "auf die ganze Fläche" in m[2]
    with pytest.raises(dt.SimulationFehler, match="senkrecht"):
        dt.anwenden(doc, [{"op": "last_setzen", "lastfall": "Druck", "last": {
            "teil": "Halter", "ort": _ort(), "verteilung": "flaeche", "richtung": {"art": "achse"}, "betrag": 1,
            "einheit": "N/mm2"}}])
    with pytest.raises(dt.SimulationFehler, match="ganze Fläche"):
        dt.anwenden(doc, [{"op": "last_setzen", "lastfall": "Druck", "last": {
            "teil": "Halter", "ort": _ort(), "richtung": {"art": "normale"}, "betrag": 1, "einheit": "N/mm2"}}])
    with pytest.raises(dt.SimulationFehler, match="Fläche anklicken"):
        dt.anwenden(doc, [{"op": "last_setzen", "lastfall": "Druck", "last": {
            "teil": "Halter", "ort": {"punkt": [0, 0, 0]}, "verteilung": "flaeche", "betrag": 1}}])
    assert kr.kraft_aus({"art": "normale", "umkehren": True}, 0.1, "N/mm2", (0, 0, 1), flaeche_mm2=200).tolist() \
        == pytest.approx([0, 0, 20])
    with pytest.raises(kr.KraftFehler, match="Flächeninhalt"):
        kr.kraft_aus({"art": "normale"}, 0.1, "N/mm2", (0, 0, 1))


# ---------------------------------------------------------------------------------------------------------------------
# Gleitendes Lager schräg (Stabwerk) gegen die Handrechnung


def test_gleitendes_lager_schraeg_im_stabwerk(tmp_path):
    """Rohr 21,3 × 2, 1000 mm, links gelenkig, rechts auf einer um α = 30° geneigten Ebene gleitend (Normale
    (−sin α, 0, cos α)), 200 N in der Mitte. Die Lagerkraft rechts steht senkrecht auf der Ebene: R = (F + q L) /
    (2 cos α), waagrecht R sin α, die das gelenkige Lager links aufnimmt. Gerundet auf die nächste Achse (bisher) wäre
    die waagrechte Kraft 0."""
    a = math.radians(30)
    n = (-math.sin(a), 0.0, math.cos(a))
    lager = ('st.lager("Rohr", punkt=(0, 0, 500), art="gelenkig")\n'
             f'st.lager("Rohr", punkt=(1000, 0, 500), art="gleitend", normale={n})')
    check, EI, q, L = _rohr(tmp_path, lager)
    e = szenario(check, "Last")
    k = {x["teil"]: x["kraft"] for x in e["auflager"]}
    V = 200 + q * L
    R = V / (2 * math.cos(a))
    assert k["Lager: M2"] == pytest.approx([-R * math.sin(a), 0, R * math.cos(a)], abs=0.05)
    assert k["Lager: M1"] == pytest.approx([R * math.sin(a), 0, V / 2], abs=0.05)
    # Kraft auf die schräge Ebene steht senkrecht auf ihr
    r = np.asarray(k["Lager: M2"])
    assert abs(float(np.dot(r, [math.cos(a), 0, math.sin(a)]))) < 0.05
    w_hand = 200 * L ** 3 / (48 * EI) + 5 * q * L ** 4 / (384 * EI)
    assert _durchbiegung(e) == pytest.approx(w_hand, rel=0.03)
    # dasselbe als Schiene entlang der Ebene (gleiten = Tangente): hält senkrecht zur Ebene und quer (y)
    lager2 = ('st.lager("Rohr", punkt=(0, 0, 500), art="gelenkig")\n'
              f'st.lager("Rohr", punkt=(1000, 0, 500), art="gleitend", gleiten=({math.cos(a)}, 0, {math.sin(a)}))')
    check2, *_ = _rohr(tmp_path, lager2, run=2)
    k2 = {x["teil"]: x["kraft"] for x in szenario(check2, "Last")["auflager"]}
    assert k2["Lager: M2"] == pytest.approx(k["Lager: M2"], abs=0.05)
    sim = check2["statik"]["simulation"]
    gl = next(x for x in sim["lager"] if x["id"] == "M2")
    assert gl["gleiten"]["quelle"] == "frei" and len(gl["gehalten"]) == 2
    print(f"Gleitend schräg 30°: rechts {np.round(k['Lager: M2'], 2).tolist()} N (Hand "
          f"{[-round(R * math.sin(a), 2), 0, round(R * math.cos(a), 2)]}), links {np.round(k['Lager: M1'], 2).tolist()}")


# ---------------------------------------------------------------------------------------------------------------------
# Lager je Lastfall gegen die Handrechnung

ZWEI_FAELLE = '''
from build123d import *
from kevcad import lager, show
import kevcad.statik as st

rohr = lager.teil("rohr-en10220-21.3x2.0")
show(Pos(0, 0, 500) * Rot(0, 90, 0) * rohr.verbauen(laenge=1000, name="Rohr"), "Rohr")
st.szenario("Kragarm")
st.last("Rohr", kraft=(0, 0, -20), punkt=(1000, 0, 500))
st.szenario("Gestützt")
st.last("Rohr", kraft=(0, 0, -20), punkt=(1000, 0, 500))
'''


def test_lager_je_lastfall(tmp_path):
    """Rohr links fest (alle Lastfälle), rechts ein gleitendes Lager nur im Lastfall „Gestützt“ (aus der App).
    „Kragarm“: w = F L³ / (3 E I) + q L⁴ / (8 E I), keine Kraft rechts. „Gestützt“ (eingespannt und gestützt): die
    Last steht über dem Lager, R_B = F + 3 q L / 8, Durchbiegung fast null."""
    def lager(x: float, art: str, szen=None) -> dict:
        d = {"teil": "Rohr", "art": art, "auf": "punkt", "ort": {"punkt": [x, 0, 500], "normale": [0, 0, 1]}}
        if szen is not None:
            d["szenarien"] = szen
        return d

    _sim(tmp_path, [], [lager(0, "fest"), lager(1000, "gleitend", ["Gestützt"])])
    _, check, _ = laufe(tmp_path, ZWEI_FAELLE, strikt=False)
    st = anbindung.LETZTER
    s = st.modell.staebe["Rohr"]
    EI = float(s.werkstoff.E) * float(s.q.I_lang)
    q = st.modell.teile["Rohr"].masse_kg * G / s.laenge
    L = s.laenge
    krag, gest = szenario(check, "Kragarm"), szenario(check, "Gestützt")
    assert krag["lager_ids"] == ["A1"] and gest["lager_ids"] == ["A1", "A2"]
    assert {a["teil"] for a in krag["auflager"]} == {"Lager: A1"}
    w_krag = 20 * L ** 3 / (3 * EI) + q * L ** 4 / (8 * EI)
    assert _durchbiegung(krag) == pytest.approx(w_krag, rel=0.02)
    rb = next(a for a in gest["auflager"] if a["teil"] == "Lager: A2")["kraft"][2]
    assert rb == pytest.approx(20 + 3 * q * L / 8, rel=0.01)
    assert _durchbiegung(gest) < 0.05 * w_krag
    assert st.modell_fuer("Gestützt") is not st.modell and len(st.modell_fuer("Gestützt").lager_explizit) == 2
    assert len(st.modell_fuer("Kragarm").lager_explizit) == 1
    # STATICS trägt die Lager je Szenario, SIM die Lastfälle des Lagers
    from kevcad_kernel.protocol import check_statics_message, pack_statics

    h = pack_statics(check["statik"], run=1)
    assert not check_statics_message(h)
    assert next(x for x in h["szenarien"] if x["name"] == "Gestützt")["lager"] == ["A1", "A2"]
    sim = check["statik"]["simulation"]
    assert sim["zustand"]["lager"]["A2"]["szenarien"] == ["Gestützt"]
    # ohne Lauf neu rechnen (Lager jetzt für alle): beide Lastfälle gestützt
    doc = dt.lies(tmp_path)
    doc["lager"][1]["szenarien"] = None
    dt.schreibe(tmp_path, doc)
    erg = anbindung.neu_mit_simulation()
    assert all(e["lager_ids"] == ["A1", "A2"] for e in erg["szenarien"])
    assert anbindung.LETZTER.modell_fuer("Kragarm") is anbindung.LETZTER.modell
    print(f"Lager je Lastfall: Kragarm w = {_durchbiegung(krag):.2f} mm (Hand {w_krag:.2f}), gestützt R_B = {rb:.2f} N "
          f"(Hand {20 + 3 * q * L / 8:.2f})")
