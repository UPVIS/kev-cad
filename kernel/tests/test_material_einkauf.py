"""Strang „Material im Kernel angleichen“: Einkaufsliste und Verschnitt wie der Bereich „Material“ der App.

Die Testdatei ``material`` in fixtures.json (kernel/tools/make_bestand_fixtures.py) ist der Vertrag: Der Swift-Test
``MaterialKernelGleichTests`` rechnet dieselben Werte mit ``MaterialDaten`` und vergleicht byteweise. Hier wird
geprüft, dass die Testdatei zum Kernel passt (sonst neu erzeugen) und dass die Formate wie ``KevFormat`` runden.
"""

import json
import sys
from pathlib import Path

import pytest

from kevcad_kernel import appformat as af
from kevcad_kernel.bestand import einkauf as ek
from kevcad_kernel.protocol import FrameReader

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"
sys.path.insert(0, str(ROOT / "kernel/tools"))

import make_bestand_fixtures as mbf  # noqa: E402


def frame(name: str) -> dict:
    ((header, _),) = FrameReader().feed((FIXTURES / name).read_bytes())
    return header


def test_testdatei_passt_zum_kernel():
    """Die Testdateien der App sind der aktuelle Stand des Kernels (sonst: tools/make_bestand_fixtures.py)."""
    bom, vorschau = mbf.material_nachrichten()
    soll = json.loads((FIXTURES / "fixtures.json").read_text())["material"]
    assert mbf.material_erwartet(bom, vorschau) == soll
    gespeichert = frame("bom_material.frame")
    assert {k: v for k, v in gespeichert.items() if k != "seq"} == {k: v for k, v in bom.items() if k != "seq"}
    assert frame("print_material.frame")["run"] == bom["run"]


def test_beispiel_deckt_alles_ab():
    bom, vorschau = mbf.material_nachrichten()
    e = ek.zusammenstellen(bom, vorschau)
    assert [z["gruppe"] for z in e["zeilen"]] == ["Lagerware"] * 3 + ["Zukaufteile"] * 2
    assert any("Reste verplant" in (z["hinweis"] or "") for z in e["lager"])
    assert any(n["aus_bestand"] and n["kaufen"] for n in e["normteile"])
    assert [bool(z["link"]) for z in e["zukauf"]] == [False, True]
    assert [f["quelle"] for f in e["filament"]] == ["druckvorschau", "druckvorschau"]
    rohr = next(c for c in bom["cuts"] if c["stock_id"] == "rohr-alfer-12x1")
    assert rohr["neue_reste"] and any(q["verschnitt"] for q in rohr["quellen"])
    assert {c["verschnitt_definition"] for c in bom["cuts"]} == {"2"}
    # Summe wie in der App: Lagerware + Zukaufteile, Filament und Normteile zum Abzählen nicht
    assert e["summe"] == pytest.approx(e["summe_lager"] + e["summe_zukauf"])
    assert e["summe_lager"] == bom["einkauf_summe"]


def test_formate_wie_kevformat():
    # Swift rounded(): halbe Werte von der Null weg (Python round: zur geraden Ziffer)
    assert af.zahl(0.25, 1) == "0,3" and af.zahl(-0.25, 1) == "-0,3" and af.zahl(2.5, 0) == "3"
    assert af.zahl(1234.5, 1) == "1.234,5" and af.zahl(1_234_567, 0) == "1.234.567" and af.zahl(-0.04, 1) == "0,0"
    assert af.kompakt(1000) == "1.000" and af.kompakt(33.7) == "33,7" and af.kompakt(47.99999999, 2) == "48"
    assert af.euro(5044.72) == "5.044,72 €" and af.euro(1.2600000000000002) == "1,26 €"
    assert [af.masse_g(g) for g in (7.254, 128.6, 1300, 24500)] == ["7,25 g", "128,6 g", "1,30 kg", "24,5 kg"]
    assert af.anzahl(1, "Teil", "Teile") == "1 Teil" and af.anzahl(12480, "Teil", "Teile") == "12.480 Teile"
    assert af.csv_zahl(4.385) == "4,38" and af.csv_zahl(None) == ""  # wie String(format: "%.2f")
    assert af.csv_feld('Ohne Preis; mit "Zeichen"') == '"Ohne Preis; mit ""Zeichen"""'


def test_lesen_wie_die_decoder_der_app():
    bom = {"run": 3, "lines": [], "einkaufsliste": [
        {"menge": 2, "preis_je": 1.5, "link": "ftp://x.de/a", "benennung": "A"},
        {"id": "b", "link": {"url": "https://www.b.de/x", "name": "B-Shop"}, "preis": 3.0},
        {"id": "c", "bezugsquelle": {"url": "https://c.de", "name": "C"}, "link_text": "C-Laden", "stand": "2026-10"}]}
    a, b, c = ek.zusammenstellen(bom)["lager"]
    assert (a["id"], a["preis"], a["link"], a["einheit"]) == ("position-1", 3.0, None, "Stück")
    assert (b["link"], b["link_text"], b["menge"]) == ("https://www.b.de/x", "B-Shop", 1.0)
    assert (c["link"], c["link_text"], c["preis_stand"]) == ("https://c.de", "C-Laden", "2026-10")
