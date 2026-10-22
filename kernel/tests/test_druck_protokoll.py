"""Druckvorschau: Nachrichten (DRUCKVORSCHAU.md, protocol.py) und Testdateien für die App."""

import json
from pathlib import Path

import pytest

from kevcad_kernel.protocol import (
    DRUCK_EINSTELLUNGEN,
    FrameReader,
    check_druck_message,
    druckvorschau_beispiel,
    pack_print_preview,
    print_export_req,
    print_settings,
)

FIX = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def test_beispiel_ist_vollstaendig_und_stimmig():
    v = druckvorschau_beispiel()
    h = pack_print_preview(v, seq=3)
    assert check_druck_message(h) == []
    s = v["summe"]
    assert s["platten"] == len(v["platten"])
    assert s["zeit_s"] == sum(p["zeit_s"] for p in v["platten"])
    assert s["zeit_mit_wechsel_s"] == s["zeit_s"] + (s["platten"] - 1) * 120
    assert abs(s["kosten"] - sum(s["kosten_teile"].values())) < 0.011
    assert abs(sum(m["g"] for m in s["material"]) - sum(t["g"] for t in v["teile"])) < 0.2
    for t in v["teile"]:
        assert set(DRUCK_EINSTELLUNGEN) <= set(t["einstellungen"])
        auf_platten = sum(1 for p in v["platten"] for x in p["teile"] if x["gruppe"] == t["gruppe"])
        assert auf_platten == t["anzahl"]
    json.dumps(h, allow_nan=False)


def test_pruefung_findet_fehler():
    v = druckvorschau_beispiel()
    del v["teile"][0]["einstellungen"]["muster"]
    v["slicer"]["zustand"] = "kaputt"
    fehler = check_druck_message(pack_print_preview(v))
    assert "teile[0].einstellungen.muster" in fehler
    assert any("slicer.zustand" in f for f in fehler)
    assert check_druck_message({"type": "PRINT_SETTINGS", "id": "x"}) == [
        "teil oder gruppe", "einstellungen, zweck oder zuruecksetzen"]
    assert check_druck_message(print_settings("x", gruppe="g1", einstellungen={"farbe": 1})) == [
        "einstellungen.farbe unbekannt"]
    assert check_druck_message(print_settings("x", teil="A", zweck="schoen")) == ["zweck 'schoen' unbekannt"]
    assert check_druck_message(print_export_req("x")) == []


@pytest.mark.skipif(not (FIX / "print_preview.frame").exists(), reason="Testdateien fehlen")
def test_testdateien_lesen_und_pruefen():
    data = json.loads((FIX / "fixtures.json").read_text())["druck"]
    for f in data["frames"]:
        frames = FrameReader().feed((FIX / f["file"]).read_bytes())
        assert len(frames) == 1
        header, payload = frames[0]
        assert header["type"] == f["type"] and payload == b""
        if header["type"] != "ACK":
            assert check_druck_message(header) == [], f["file"]
    voll = FrameReader().feed((FIX / "print_preview.frame").read_bytes())[0][0]
    assert voll["summe"]["platten"] == data["vorschau"]["summe"]["platten"]
    assert voll["teile"][0]["einstellungen"] == data["vorschau"]["erstes_teil"]["einstellungen"]
