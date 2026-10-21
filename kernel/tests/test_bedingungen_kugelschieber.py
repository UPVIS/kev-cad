"""Abnahme der Zwangsbedingungen am Kugelschieber (samples/kugelschieber-bedingungen, Kopie von Kevins Projekt):
der Rahmen sitzt über auf/konzentrisch auf den Lenkrollen; ändert sich die Rollenhöhe, folgt er, und die Prüfung bleibt
grün. Läuft im selben Prozess (Runner), etwa 5 s je Lauf."""

from pathlib import Path

import pytest

from kevcad_kernel.runner import Runner

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "kugelschieber-bedingungen" / "model.py"


@pytest.mark.parametrize("rolle_h", [120, 115])
def test_rahmen_folgt_der_rollenhoehe(rolle_h):
    runner = Runner(lambda h, p=b"": None)
    res = runner.run({"run": 1, "path": str(SAMPLE), "params": {"rolle_h": rolle_h}, "inventar_regel": False})
    assert res["type"] == "RUN_DONE", res.get("error")
    rep = res["bedingungen"]
    fehler = [b["text"] for b in rep["befunde"] if b["schwere"] == "fehler"]
    # Das Beispiel nutzt verbinde(…) nur am Rahmen; seit Kevins Entscheidung (22.10.2026) ist jede fehlende
    # Befestigungsangabe dann ein Fehler. Sonst darf nichts fehlschlagen.
    assert [t for t in fehler if "ohne Angabe" not in t] == [], fehler
    assert any("ohne Angabe" in t for t in fehler)
    assert rep["summe"]["verletzt"] == 0 and rep["summe"]["ungeprueft"] == 0
    rahmen = runner.ns["rahmen"]
    assert abs(runner.ns["rahmen_unten"] - rolle_h) < 1e-6
    assert abs(rahmen.bounding_box().min.Z - rolle_h) < 1e-6
    teil = next(t for t in rep["teile"] if t["name"] == "Rollwagen/Rahmen")
    assert teil["stand"] == "bestimmt" and teil["frei"] == 0 and teil["befestigt"] and teil["am_boden"]
    auf = next(i for i in rep["items"] if i["art"] == "auf")
    assert auf["teile"] == ["Rollwagen/Rahmen", "Rollwagen/Lenkrolle 1/Gabel"]
    assert rep["loese_ms"] < 100
