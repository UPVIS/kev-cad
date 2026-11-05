"""V2-5 Live, Protokoll (PROTOCOL.md, Abschnitt „V2-5 Live“): Testdateien, Inhaltsschlüssel, Strukturpatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kevcad_kernel import protocol as p

FIXTURES = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def test_testdateien_passen_zum_protokoll():
    """Jede Datei ist genau der Rahmen aus live_beispiele, besteht die Prüfung und steht in fixtures.json."""
    live = json.loads((FIXTURES / "fixtures.json").read_text())["live"]
    beispiele = {name: (h, pl, r) for name, h, pl, r in p.live_beispiele()}
    assert [f["file"] for f in live["frames"]] == [f"{n}.frame" for n in beispiele]
    for info in live["frames"]:
        daten = (FIXTURES / info["file"]).read_bytes()
        (header, payload), = p.FrameReader().feed(daten)
        name = info["file"].removesuffix(".frame")
        h, pl, richtung = beispiele[name]
        assert daten == p.encode_frame(h, pl), f"{info['file']} veraltet: make_live_fixtures.py laufen lassen"
        assert header["type"] == info["type"] and len(payload) == info["payload_bytes"]
        assert info["richtung"] == richtung
        assert not p.check_live_message(header, payload), (info["file"], p.check_live_message(header, payload))
    assert live["kernel_faehigkeiten"] == list(p.KERNEL_FAEHIGKEITEN)
    assert set(live["nachrichten"].values()) <= set(p.KERNEL_FAEHIGKEITEN)


def test_wie_zuvor_aus_den_testdateien():
    live = json.loads((FIXTURES / "fixtures.json").read_text())["live"]
    (basis, _), = p.FrameReader().feed((FIXTURES / live["wie_zuvor"]["basis_file"]).read_bytes())
    (wz, nutz), = p.FrameReader().feed((FIXTURES / live["wie_zuvor"]["file"]).read_bytes())
    assert wz["basis"] == basis["seq"] and not nutz
    neu = p.wie_zuvor_aufbauen(wz, basis)
    assert neu == live["wie_zuvor"]["ergebnis"]
    assert neu["type"] == "CHECK" and neu["seq"] == wz["seq"] and neu["run"] == basis["run"] + 1
    assert neu["befunde"] == basis["befunde"]


def test_versionsbild_aus_der_szene():
    live = json.loads((FIXTURES / "fixtures.json").read_text())["live"]
    (kopf, nutz), = p.FrameReader().feed((FIXTURES / "live_version_bild_req.frame").read_bytes())
    netze = p.unpack_netze(kopf["teile"], nutz)
    assert [k["teil"] for k, n in zip(kopf["teile"], netze) if n is None] == live["version_bild"]["aus_szene"]
    assert len(nutz) == live["version_bild"]["payload_bytes"]


def _kopf(**extra):
    return {"type": "PART_UPSERT", "seq": 3, "run": 2, "name": "T", "color": [1, 0, 0, 1], "material": "pla",
            "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}, "props": {"volume": 1.0, "area": 6.0, "center": [0.5] * 3},
            "counts": {"vert": 3}, "faces": [{"t": "plane", "a": 1.0}], "edges": [], "transform": None, **extra}


def test_inhalt_schluessel():
    k = "abc:0.1:0.2"
    a = p.inhalt_schluessel(k, _kopf())
    assert len(a) == 16 and set(a) <= set("0123456789abcdef")
    # Laufnummer, seq, faces, edges und ein alter Schlüssel zählen nicht
    assert p.inhalt_schluessel(k, _kopf(run=9, seq=99, faces=[], edges=[{"t": "line"}], inhalt="x")) == a
    # Farbe, Material, Masse, Lager, Druck, Kulisse zählen
    assert p.inhalt_schluessel(k, _kopf(color=[0, 1, 0, 1])) != a
    assert p.inhalt_schluessel(k, _kopf(material="petg")) != a
    assert p.inhalt_schluessel(k, _kopf(props={"volume": 1.0, "area": 6.0, "center": [0.5] * 3, "mass": 1.2})) != a
    assert p.inhalt_schluessel(k, _kopf(kulisse=True)) != a
    assert p.inhalt_schluessel(k, _kopf(stock={"id": "rohr-12"})) != a
    # andere Form (Tessellierungs-Schlüssel) zählt
    assert p.inhalt_schluessel("abd:0.1:0.2", _kopf()) != a
    # ohne Tessellierungs-Schlüssel zählen Nutzlast und Flächenliste
    b = p.inhalt_schluessel("", _kopf(), b"\x00" * 12)
    assert b != p.inhalt_schluessel("", _kopf(), b"\x01" * 12)
    assert b != p.inhalt_schluessel("", _kopf(faces=[]), b"\x00" * 12)


def test_strukturpatch_und_aufbau():
    alt = {"run": 2, "ms": 12.5, "befunde": [{"id": "a", "text": "x"}, {"id": "b"}], "liste": [1, 2],
           "statik": {"szenarien": [{"name": "S", "kennzahlen": {"knicken": 3.0}}]}, "weg": 1}
    neu = {"run": 3, "ms": 12.5, "befunde": [{"id": "a", "text": "y"}, {"id": "b"}], "liste": [1, 2, 3],
           "statik": {"szenarien": [{"name": "S", "kennzahlen": {"knicken": 4.5}}]}, "dazu": None}
    setzen, weg = p.strukturpatch(alt, neu)
    assert [pfad for pfad, _ in setzen] == [["run"], ["befunde", 0, "text"], ["liste"],
                                            ["statik", "szenarien", 0, "kennzahlen", "knicken"], ["dazu"]]
    assert weg == [["weg"]]
    assert p.kanonisch(p.patch_anwenden(alt, setzen, weg)) == p.kanonisch(neu)
    assert alt["run"] == 2, "die Basis bleibt unverändert"
    assert p.strukturpatch(alt, alt) == ([], [])
    assert p.strukturpatch(alt, neu, grenze=20) is None, "zu groß: None"
    # Typwechsel an einer Blattstelle wird gesetzt, wenn der Patch dort hinabsteigt ...
    s, _ = p.strukturpatch({"a": 1, "b": 2}, {"a": 1.0, "b": 3})
    assert s == [[["a"], 1.0], [["b"], 3]]
    s, _ = p.strukturpatch({"a": True, "b": 2}, {"a": 1, "b": 3})
    assert s == [[["a"], 1], [["b"], 3]]
    # ... in sonst gleichen Teilen nicht (Python: 1 == 1.0 == True); das fängt die Probe der Weiche (live.py)
    alt, neu = {"a": 1}, {"a": 1.0}
    s, w = p.strukturpatch(alt, neu)
    assert p.kanonisch(p.patch_anwenden(alt, s, w)) != p.kanonisch(neu)


@pytest.mark.parametrize("setzen,weg", [
    ([[["fehlt", "x"], 1]], []),
    ([[["liste", 5], 1]], []),
    ([[[], 1]], []),
    ([], [["fehlt"]]),
    ([[["liste", "0"], 1]], []),
])
def test_patch_anwenden_lehnt_falsche_pfade_ab(setzen, weg):
    with pytest.raises(ValueError):
        p.patch_anwenden({"liste": [1, 2], "a": {}}, setzen, weg)


def test_pruefung_findet_fehler():
    assert p.check_live_message({"type": "PART_SAME", "run": 1, "name": "T", "inhalt": "zu-kurz"})
    assert p.check_live_message({"type": "WIE_ZUVOR", "art": "PART_UPSERT", "basis": 3, "setzen": [], "weg": []})
    assert p.check_live_message({"type": "WIE_ZUVOR", "art": "BOM", "basis": 3, "setzen": [[["a"]]], "weg": []})
    assert p.check_live_message({"type": "AGENT_SCHRITT", "schritt": {"id": "s-1", "werkzeug": "run",
                                                                      "stand": "ok", "beginn": 1.0}})
    assert p.check_live_message({"type": "VIEW_CMD", "cmd": "annotate", "args": {"dauer_s": 0}})
    assert p.check_live_message({"type": "LAGE", "reply_to": "k-1", "zeit": 1.0, "kamera": {"position": [0, 0, 0]},
                                 "sichtbar": [], "verborgen": [], "isoliert": None, "auswahl": {"refs": []},
                                 "maus": None})
    kopf = {"type": "VERSION_BILD_REQ", "teile": [{"teil": "A", "farbe": [1, 1, 1, 1], "vert": 1, "tri": 0,
                                                   "epts": 0, "edge": 0}]}
    assert not p.check_live_message(kopf, b"\x00" * 28)
    assert p.check_live_message(kopf, b"\x00" * 27)
