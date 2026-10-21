"""MCP-Werkzeuge für Zukaufteile mit der Attrappe über echtes Streamable HTTP: Texte, Parameter, Fehler."""

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


def test_zukauf_anlegen_texte(srv):
    server, fake = srv
    res = call(server.url, "zukauf_anlegen", {"url": "https://shop.example/p/05200",
                                               "felder": {"name": "Rollwagen", "masse": {"l": 610, "b": 410, "h": 128}}})
    text = texts(res)[0]
    assert res.is_error is False and "angelegt (Vorschlag, wartet auf Kevins Freigabe" in text
    assert "Von Kevin bestätigen lassen: Preis" in text and "lager.zukauf('alutec-05200')" in text
    assert fake.calls_of("zukauf_anlegen")[0][0][0] == "https://shop.example/p/05200"
    res = call(server.url, "zukauf_anlegen", {"mpn": "ISO 4762 M6x20"})
    assert res.is_error is False and "Normteil" in texts(res)[0] and "lager.teil(" in texts(res)[0]
    res = call(server.url, "zukauf_anlegen", {"felder": {"name": "ohne Maße"}})
    assert res.is_error is True and "masse fehlt" in texts(res)[0] and "Fehlt oder unsicher: Maße" in texts(res)[0]
    res = call(server.url, "zukauf_anlegen", {})
    assert res.is_error is True and "url, mpn, gtin oder felder" in texts(res)[0]
    tools = {t.name: t for t in anyio.run(with_client, server.url, lambda c: c.list_tools()).tools}
    assert tools["zukauf_anlegen"].input_schema["properties"]["ebene"]["enum"] == ["projekt", "eigen"]
    assert "zukaufteil" in tools["stock_search"].input_schema["properties"]["art"]["anyOf"][0]["enum"]


def test_html_suchen_uebernehmen_liste(srv):
    server, fake = srv
    res = call(server.url, "zukauf_html", {"url": "https://shop.example/p", "html": "<html>…</html>"})
    text = texts(res)[0]
    assert text.startswith("Gelesen aus json-ld:") and "- EAN: 4014688052004" in text
    assert "- Maße: 610 × 410 × 128 mm" in text and "(brutto/netto unklar)" in text
    assert "mit zukauf_anlegen(url, felder=…) anlegen" in text
    assert fake.calls_of("zukauf_html")[0][0] == ("https://shop.example/p", 14, False, "projekt")
    res = call(server.url, "cad_suchen", {"id": "alutec-05200"})
    text = texts(res)[0]
    assert "Links zum Herunterladen" in text and "- TraceParts: ALUTEC 05200: https://www.traceparts.com" in text
    assert 'cad_uebernehmen("alutec-05200")' in text and "TRACEPARTS_API_KEY" in text
    res = call(server.url, "cad_uebernehmen", {"id": "alutec-05200"})
    text = texts(res)[0]
    assert "übernommen" in text and "Hüllmaß 610 × 410 × 128 mm (Katalog 610 × 410 × 128 mm)" in text
    assert "Jetzt run aufrufen" in text
    assert fake.calls_of("cad_uebernehmen")[0][0] == ("alutec-05200", None, 30, False)
    res = call(server.url, "cad_uebernehmen", {"id": "x"})
    assert res.is_error is True and "Keine neue STEP" in texts(res)[0]
    res = call(server.url, "zukauf_liste")
    rows = texts(res)[0].splitlines()
    assert rows[0] == "1 Zukaufteil:" and rows[1].split()[:4] == ["id", "Name", "Hersteller", "Nummer"]
    assert "wartet auf CAD" in rows[3] and "24,99 € brutto" in rows[3]
