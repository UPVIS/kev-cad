"""Experiment Pipeline K2/K3 (PLAN-PIPELINE.md): Gliederung von model.py und Maße ändern ohne Lesen."""

from kevcad_kernel.mcp_tools import modell_quelle as mq

CODE = '''from build123d import *
from kevcad import lager, param, show, step

breite = param("breite", 120)  # Breite der Platte
dicke = param("dicke", 6)
ball = param("ball", 2 * breite)
n = int(param("anzahl", 4))
neg = param("versatz", -3.5)

step("Platte")
show(Box(breite, 80, dicke), "Halter/Platte")
step(f"Bohrungen {n}")
'''


def test_gliederung_nennt_parameter_schritte_und_teile():
    g = mq.gliederung(CODE)
    namen = [p["name"] for p in g["params"]]
    assert namen == ["breite", "dicke", "ball", "anzahl", "versatz"]
    assert g["params"][0] == {"name": "breite", "wert": "120", "zeile": 4, "kommentar": "Breite der Platte"}
    assert [s["zeile"] for s in g["schritte"]] == [10, 12]
    assert g["teile"] == [{"name": "Halter/Platte", "zeile": 11}]
    text = mq.gliederung_text(g, "/p/model.py")
    assert "Z4 breite = 120  # Breite der Platte" in text and len(text) < len(CODE) * 3


def test_setze_aendert_nur_die_vorgaben():
    neu, meldungen, fehler = mq.setze_parameter(CODE, {"breite": 150, "dicke": 8.5, "anzahl": 6, "versatz": 2})
    assert 'param("breite", 150)  # Breite der Platte' in neu
    assert 'param("dicke", 8.5)' in neu and 'int(param("anzahl", 6))' in neu and 'param("versatz", 2)' in neu
    assert neu.count("\n") == CODE.count("\n")
    assert len(meldungen) == 4 and not fehler


def test_setze_meldet_ausdruecke_und_unbekannte():
    neu, meldungen, fehler = mq.setze_parameter(CODE, {"ball": 100, "gibtsnicht": 1})
    assert neu == CODE and not meldungen
    assert any("Ausdruck" in f for f in fehler) and any("gibtsnicht" in f for f in fehler)


def test_setze_mit_umlauten_davor():
    code = 'h = param("höhe", 10)  # Höhe über dem Boden\nb = param("breite", 5)\n'
    neu, meldungen, _ = mq.setze_parameter(code, {"höhe": 12, "breite": 7})
    assert neu == 'h = param("höhe", 12)  # Höhe über dem Boden\nb = param("breite", 7)\n'
