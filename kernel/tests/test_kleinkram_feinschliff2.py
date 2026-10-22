"""Strang „Feinschliff 2“, Punkt 6 (Kleinkram): kein doppelter Punkt im Druckerstatus, Ersatz-Kernel mit Verschnitt
nach Definition 2."""

import importlib.util
from pathlib import Path

from kevcad_kernel.drucker.bericht import status_text


def test_druckerstatus_ohne_doppelten_punkt():
    st = {"konfiguriert": False, "verbindung": "aus",
          "meldung": "Kein Drucker eingestellt (Drucker-Einstellungen). Weg A geht trotzdem.", "drucker": None,
          "wege": {"a": {"moeglich": True}, "b": {"moeglich": False, "grund": "keine Verbindung"}},
          "auftrag": {"auftrag": "j-1", "von": "agent", "weg": "a", "platten": [1], "zustand": "fertig",
                      "meldung": "In Bambu Studio geöffnet."}}
    text = status_text(st)
    assert "Status: aus – Kein Drucker eingestellt (Drucker-Einstellungen). Weg A geht trotzdem.\n" in text
    assert ".." not in text
    assert "Status: verbunden (nur lesend)." in status_text({"verbindung": "verbunden"})


def test_ersatz_kernel_verschnitt_definition_2():
    pfad = Path(__file__).resolve().parents[1] / "tools" / "fake_kernel.py"
    spec = importlib.util.spec_from_file_location("fake_kernel_f2", pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    k = mod.FakeKernel.__new__(mod.FakeKernel)
    k.current = ["Gestell/Bein vorn links", "Halter/Bolzen"]
    k.inventar_regel = True
    bom = k.bom(1)
    assert [c["verschnitt_definition"] for c in bom["cuts"]] == ["2", "2"]
    assert [c["verschnitt_prozent"] for c in bom["cuts"]] == [0.1, 0.1]  # nur der Sägeschnitt, der Rest ist verwertbar
    assert bom["verschnitt"] == {"definition": "2", "stangen": 0.1, "platten": None}
