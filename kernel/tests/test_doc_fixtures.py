"""Testdateien der Zeichnungs-Nachrichten (tools/make_doc_fixtures.py) passen zum Protokoll und zu fixtures.json."""

from __future__ import annotations

import json
from pathlib import Path

from kevcad_kernel.protocol import FrameReader, unpack_polylinien
from kevcad_kernel.zeichnung.bearbeiten import OPS

FIX = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def _frame(name: str) -> tuple[dict, bytes]:
    (h, p), = FrameReader().feed((FIX / f"{name}.frame").read_bytes())
    return h, p


def test_drawing_frame_passt_zu_fixtures():
    erw = json.loads((FIX / "fixtures.json").read_text())["dokumente"]
    h, p = _frame("drawing")
    d = erw["drawing"]
    assert h["type"] == "DRAWING" and h["reply_to"] == d["reply_to"] and h["blatt"]["id"] == d["blatt_id"]
    assert h["linien_reihenfolge"] == d["linien_reihenfolge"] and len(p) == d["payload_bytes"]
    gruppen = unpack_polylinien(h, p)
    assert [{"id": g["id"], "art": g["art"], "linien": g["linien"]} for g in h["geometrie"]] == d["geometrie"]
    for g, linien in zip(h["geometrie"], gruppen):
        assert {k: len(v) for k, v in linien.items()} == g["linien"]
    erste = next(pl for g in gruppen for art in h["linien_reihenfolge"] for pl in g[art])
    assert [round(float(v), 4) for v in erste[0]] == d["erster_punkt"]
    assert sorted(m["text"] for m in h["masse"]) == d["masstexte"]
    for m in h["masse"]:
        assert {"id", "linien", "pfeile", "text", "text_lage", "text_winkel", "wert", "text_hoehe"} <= set(m)
        for pf in m["pfeile"]:
            assert len(pf["spitze"]) == 2 and pf["polygon"]


def test_rohr_docs_und_bearbeiten():
    erw = json.loads((FIX / "fixtures.json").read_text())["dokumente"]
    h, p = _frame("drawing_tube")
    assert sum(g["linien"]["bruch"] for g in h["geometrie"]) == erw["drawing_tube"]["bruch"] > 0
    assert sorted(m["text"] for m in h["masse"]) == erw["drawing_tube"]["masstexte"]
    docs, _ = _frame("docs")
    assert docs["type"] == "DOCS" and [b["id"] for b in docs["blaetter"]] == erw["docs"]["blaetter"]
    for b in docs["blaetter"]:
        assert {"id", "titel", "inhalt", "format", "verwaiste_masse"} <= set(b)
    req, _ = _frame("drawing_req")
    assert req["type"] == "DRAWING_REQ" and req["blatt"] == "platte"
    edit, _ = _frame("drawing_edit")
    assert edit["type"] == "DRAWING_EDIT" and edit["von"] == "kevin"
    assert [o["op"] for o in edit["ops"]] == erw["drawing_edit"]["ops"]
    assert set(erw["drawing_edit"]["ops"]) <= set(OPS)
