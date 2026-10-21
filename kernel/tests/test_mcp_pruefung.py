"""MCP-Werkzeuge der Prüfung (pruefen, montage_reihenfolge, ansichten) mit der Attrappe."""

from __future__ import annotations

import anyio
import pytest
from mcp_testutil import start_server, with_client


@pytest.fixture
def srv():
    server, fake = start_server()
    yield server, fake
    server.stop_thread()


def call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def textteile(res):
    return [c.text for c in res.content if getattr(c, "type", "") == "text"]


def bilder(res):
    return [c for c in res.content if getattr(c, "type", "") == "image"]


def test_pruefen_ohne_lauf_und_mit_befunden(srv):
    server, fake = srv
    res = call(server.url, "pruefen")
    assert res.is_error and "erst run" in textteile(res)[0]
    call(server.url, "run")
    res = call(server.url, "pruefen")
    assert res.is_error  # offener Fehler
    text = textteile(res)[0]
    assert text.startswith("Prüfung: 1 Durchdringung") and "Lösung: Halter/Lasche um 0,7 mm" in text
    assert "Stand (Boden z = 0):" in text and "Kippwinkel 24,5°" in text
    assert "Montage: 2 Schritte, vollständig" in text
    assert res.structured_content["befunde"][0]["id"] == "du1"
    assert not bilder(res) and not fake.calls_of("ansichten")


def test_pruefen_mit_bildern(srv):
    server, fake = srv
    call(server.url, "run")
    res = call(server.url, "pruefen", {"bilder": True})
    assert len(bilder(res)) == 3  # iso und zwei Richtungen quer zur Trennrichtung
    ((ansichten, w, h), _), = fake.calls_of("ansichten")
    assert (w, h) == (480, 320)
    assert [a["name"] for a in ansichten] == ["du1 iso", "du1 quer 1", "du1 quer 2"]
    for a in ansichten:
        assert a["punkt"] == [0, 5, 2] and a["darstellung"] == "xray" and a["schnittkoerper"] is True
        assert a["hervorheben"] == ["Halter/Lasche", "Halter/Grundplatte"]
    # quer zur Trennrichtung (0, 0, 1): Blick waagrecht
    assert all(abs(a["richtung"][2]) < 1e-9 for a in ansichten[1:])
    assert any(t.startswith("Bild 1: du1 iso") for t in textteile(res))


def test_nahansicht_ohne_schnittkoerper_schattiert():
    from kevcad_kernel.pruefung.dienst import ansicht_fuer_befund

    a = ansicht_fuer_befund({"id": "sc1", "art": "schwebt", "teile": ["Ring"], "ort": [0, 0, 5], "geometrie": None})
    assert [x["name"] for x in a] == ["sc1 iso", "sc1 vorn", "sc1 oben"]
    assert all(x["darstellung"] == "shaded_edges" and x["hervorheben"] == ["Ring"] for x in a)
    assert ansicht_fuer_befund({"id": "x", "teile": ["A"], "ort": None}) == []


def test_montage_reihenfolge(srv):
    server, _ = srv
    call(server.url, "run")
    res = call(server.url, "montage_reihenfolge")
    assert not res.is_error
    text = textteile(res)[0]
    assert text.splitlines() == ["Montagereihenfolge, 2 Schritte (vollständig):",
                                 "1. Halter/Grundplatte – Grundteil", "2. Halter/Lasche – von oben"]


def test_ansichten_mehrere_bilder_in_einem_aufruf(srv):
    server, fake = srv
    res = call(server.url, "ansichten", {})
    assert not res.is_error and len(bilder(res)) == 4
    ((ansichten, w, h), _), = fake.calls_of("ansichten")
    assert [a["standard"] for a in ansichten] == ["iso", "front", "right", "top"] and (w, h) == (640, 400)
    assert all(a["darstellung"] == "shaded_edges" for a in ansichten)
    res = call(server.url, "ansichten", {"views": ["iso"], "richtungen": [[1, 1, -1]], "ziel": ["Halter"],
                                         "darstellung": "xray", "hervorheben": ["Halter/Lasche"], "width": 320,
                                         "height": 200})
    assert len(bilder(res)) == 2
    (ansichten, w, h), _ = fake.calls_of("ansichten")[-1]
    assert ansichten[1]["richtung"] == [1.0, 1.0, -1.0] and ansichten[1]["ziel"] == ["Halter"]
    assert ansichten[0]["hervorheben"] == ["Halter/Lasche"] and (w, h) == (320, 200)
    res = call(server.url, "ansichten", {"views": [], "richtungen": [[0, 0, 0]]})
    assert res.is_error and "[0, 0, 0]" in textteile(res)[0]
    fake.app_connected = False
    res = call(server.url, "ansichten", {"views": ["top"]})
    assert res.is_error and "App nicht verbunden" in textteile(res)[0]
