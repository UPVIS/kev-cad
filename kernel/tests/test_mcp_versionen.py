"""MCP-Werkzeuge der Versionen mit der Attrappe über echtes Streamable HTTP."""

from __future__ import annotations

import anyio
import pytest
from mcp_testutil import start_server, texts, with_client


@pytest.fixture
def srv():
    server, fake = start_server()
    yield server, fake
    server.stop_thread()


def call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_versionen_liste(srv):
    server, fake = srv
    res = call(server.url, "versionen", {"limit": 10})
    assert res.is_error is False
    text = texts(res)[0]
    assert "2 Versionen in Hauptstand, 1 Meilenstein" in text
    assert "V3 · 2026-10-21 14:32 · Agent · 3f2a9c · ★ Halter fertig · 4 Teile, 1,25 kg" in text
    assert "Notiz: Bohrungen M6" in text and "aktuell" in text
    assert res.structured_content["versionen"][0]["meilenstein"] == {"titel": "Halter fertig",
                                                                     "notiz": "Bohrungen M6"}
    assert fake.calls_of("versionen") == [((10, None), {})]


def test_wiederherstellen_meilenstein_variante(srv):
    server, fake = srv
    res = call(server.url, "version_wiederherstellen", {"version": "V2"})
    assert res.is_error is False
    assert "V2 wiederhergestellt als neue Version V4" in texts(res)[0] and "3 Teile" in texts(res)[0]
    bad = call(server.url, "version_wiederherstellen", {"version": "V9"})
    assert bad.is_error is True and "gibt es nicht" in texts(bad)[0]

    res = call(server.url, "meilenstein", {"titel": "Halter fertig", "notiz": "Bohrungen M6"})
    assert "Meilenstein „Halter fertig“ an V3 gesetzt." in texts(res)[0]
    assert fake.calls_of("meilenstein") == [(("Halter fertig", "Bohrungen M6", None), {})]

    res = call(server.url, "variante", {"aktion": "anlegen", "name": "Leicht", "von": "V2"})
    assert "Variante „Leicht“ von V2 angelegt" in texts(res)[0]
    assert fake.calls_of("variante")[-1] == (("anlegen", "Leicht", "V2", None), {})


def test_vergleichen_mit_code(srv):
    server, fake = srv
    res = call(server.url, "versionen_vergleichen", {"a": "V2", "code_zeilen": 5})
    assert res.is_error is False
    text = texts(res)[0]
    assert text.startswith("V2 → aktueller Stand:")
    assert "Parameter hoehe: 120 → 140" in text and "geändert: Grundplatte (Form" in text and "neu: Deckel" in text
    assert "model.py (+1 −1)" in text and "+hoehe = param(\"hoehe\", 140)" in text
    assert "Geisterkörper" in text
    assert fake.calls_of("versionen_vergleichen") == [(("V2", None, True), {})]  # zeigen als Schlüsselwort
    assert "diff" not in res.structured_content["code"]  # der volle Unterschied steht nur im Text
