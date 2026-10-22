"""MCP-Werkzeuge der Referenzen (Phase 4) gegen die Attrappe: Text für Kevin, Aufrufe an den Dienst."""

from __future__ import annotations

import anyio
import pytest
from mcp_testutil import start_server, texts, with_client


@pytest.fixture
def srv():
    server, fake = start_server()
    yield server, fake
    server.stop_thread()


def call(url, name, args=None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_referenz_werkzeuge(srv):
    server, fake = srv
    res = call(server.url, "referenzen")
    text = texts(res)[0]
    assert not res.is_error and text.startswith("2 Referenzen:")
    assert "Netz am Modell angelegt (180.0° um Z)" in text
    assert "Hülle mit Anbauten 180 × 117,3 × 48,4 mm, Grundkörper ohne Anbauten 174 × 102,1 mm" in text

    res = call(server.url, "referenzen", {"name": "IMG_5186", "warten_s": 5})
    text = texts(res)[0]
    assert "tiefe" in text and "103,4" in text and "Hülle mit Anbauten: 180 × 118 × 47,9 mm" in text
    assert "Grundkörper Scarlett/Gehaeuse: 180 × 103,7 × 46,5 mm" in text
    assert "Hinweis: Von Hand nachmessen: gross_h" in text
    assert fake.calls_of("referenzen")[-1] == (("IMG_5186", 5.0), {})

    res = call(server.url, "referenz_video", {"pfad": "/v/IMG_5186.MOV", "masz": {"laenge": 180}, "auflage": True})
    assert not res.is_error and "Object Capture läuft" in texts(res)[0]
    assert fake.calls_of("referenz_video")[-1][0][:4] == ("/v/IMG_5186.MOV", None, {"laenge": 180.0}, True)
    assert call(server.url, "referenz_video", {"pfad": "/v/a.txt"}).is_error
    assert call(server.url, "referenz_video", {"pfad": "/v/a.mov", "einstellung": "super"}).is_error  # Schema

    res = call(server.url, "referenz_vermessen", {"quelle": "IMG_5186", "freie_masse": ["tiefe", "hoehe"],
                                                  "bekannte_masse": {"breite": 180}})
    text = texts(res)[0]
    assert not res.is_error and "Referenz IMG_5186: 8 Bilder" in text and "Maße übernehmen" in text
    assert fake.calls_of("referenz_vermessen")[-1][0][:4] == ("IMG_5186", ["tiefe", "hoehe"], {"breite": 180.0}, 8)

    res = call(server.url, "referenz_fotos", {"pfade": ["/f/a.jpg", "/f/b.jpg"], "name": "Küche"})
    assert "Referenz Küche: 2 Fotos abgelegt" in texts(res)[0]

    res = call(server.url, "referenz_fotoansicht", {"foto": 2, "modus": "differenz"})
    assert not res.is_error and "Überdeckung 93,5 %" in texts(res)[0]
    assert not [c for c in res.content if c.type == "image"]  # ohne bild_zeigen kein Bild
    res = call(server.url, "referenz_fotoansicht", {"bild_zeigen": True})
    assert [c for c in res.content if c.type == "image"]
    assert fake.calls_of("referenz_fotoansicht")[-1][0][-1] is True
