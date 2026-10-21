"""MCP-Werkzeuge für Lagerteile, Materialien und Stückliste mit der Attrappe über echtes Streamable HTTP."""

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


def test_run_mentions_bom_and_inventory_violations(srv):
    server, fake = srv
    res = call(server.url, "run")
    assert res.is_error is False
    summary = texts(res)[0]
    assert "Stückliste: 3 Positionen, 7 Teile, 17,04 kg, 39,74 € (Richtpreise, Stand 2026-10)" in summary
    assert "Hinweis Stückliste: Halter: Eigenteil ohne Preis" in summary
    fake.violations = ["Halter/Lasche", "Grundplatte"]
    res = call(server.url, "run")
    assert res.is_error is True
    summary = texts(res)[0]
    assert summary.startswith("Inventar-Regel: 2 Teile sind nicht aus dem Inventar: Halter/Lasche, Grundplatte – "
                              "passendes Lagerteil mit stock_search suchen")
    assert res.structured_content["inventar_verstoesse"] == ["Halter/Lasche", "Grundplatte"]


def test_stock_tools_text(srv):
    server, fake = srv
    res = call(server.url, "stock_search", {"query": "40x40x3", "art": "vierkantrohr"})
    text = texts(res)[0]
    assert text.startswith("1 Lagerteil für „40x40x3“ (art vierkantrohr):")
    rows = text.splitlines()
    assert rows[1].split() == ["id", "Name", "Norm", "Material", "kg/m", "Preis", "Ebene", "Status"]
    assert "vierkantrohr-en10219-40x40x3" in rows[3] and "3,41" in rows[3] and "8,00 €/m" in rows[3]
    assert fake.calls_of("stock_search") == [(("40x40x3", "vierkantrohr"), {})]
    res = call(server.url, "stock_search", {"query": "gibtsnicht"})
    assert res.is_error is False and "Keine Lagerteile" in texts(res)[0]
    res = call(server.url, "stock_get", {"id": "vierkantrohr-en10219-40x40x3"})
    text = texts(res)[0]
    assert "Querschnitt 420,8 mm², 3,41 kg/m (Tabelle), Stange 6000 mm" in text
    assert "Preis: 8,00 €/m (Richtwert, 2026-10)" in text and "lager.teil(" in text
    assert call(server.url, "stock_get", {"id": "x"}).is_error is True
    res = call(server.url, "stock_define", {"entry": {"id": "rohr-x", "art": "rohr", "name": "Rohr", "masse": {"d": 30},
                                                       "material": "stahl-s235"}})
    text = texts(res)[0]
    assert "als Vorschlag im eigenen Katalog" in text and "wartet auf Kevins Freigabe im Lagerkatalog" in text
    res = call(server.url, "stock_define", {"entry": {"id": "rohr-y", "art": "rohr"}, "ebene": "projekt"})
    assert res.is_error is True and "masse.s fehlt" in texts(res)[0]
    assert fake.calls_of("stock_define")[1][0][1] == "projekt"
    tools = {t.name: t for t in anyio.run(with_client, server.url, lambda c: c.list_tools()).tools}
    assert tools["stock_define"].input_schema["properties"]["ebene"]["enum"] == ["eigen", "projekt"]
    assert not [n for n in tools if "inventar" in n or "regel" in n]  # kein Werkzeug schaltet die Inventar-Regel


def test_material_and_delete_tools(srv):
    server, fake = srv
    res = call(server.url, "material_list", {"query": "stahl"})
    text = texts(res)[0]
    assert text.startswith("2 Materialien:") and "stahl-s235" in text and "7,85" in text
    res = call(server.url, "material_define", {"entry": {"id": "eiche", "name": "Eiche", "gruppe": "Holz",
                                                          "dichte": 0.69, "farbe": "#B08850"}})
    assert "als Vorschlag gespeichert" in texts(res)[0] and "Hinweis: preis_stand fehlte" in texts(res)[0]
    res = call(server.url, "catalog_delete", {"kind": "teil", "id": "rohr-x"})
    assert res.is_error is False and "gelöscht" in texts(res)[0]
    assert fake.calls_of("catalog_delete") == [(("teil", "rohr-x", "eigen"), {})]
    assert call(server.url, "catalog_delete", {"kind": "teil", "id": "gibtsnicht"}).is_error is True


def test_bom_tool(srv):
    server, fake = srv
    res = call(server.url, "bom")
    assert res.is_error is True and "erst run" in texts(res)[0]
    call(server.url, "run")
    res = call(server.url, "bom")
    text = texts(res)[0]
    assert text.startswith("Stückliste (Lauf 1): 3 Positionen, 7 Teile, 17,04 kg, 39,74 €")
    assert "Halter (Eigenteil)" in text and "45°/45°" in text
    assert "Vierkantrohr 40 × 40 × 3: 1 Stange à 6.000 mm, Verschnitt 17,2 %, ganze Stangen 48,00 €" in text
    assert "  Stange 1: 842 + 842 + 842 + 842 + 800 + 800 = 4.968 mm, Rest 1.032 mm" in text
    assert "Hinweis: Halter: Eigenteil ohne Preis" in text
    res = call(server.url, "bom", {"format": "csv"})
    csv_text = texts(res)[0]
    assert csv_text.startswith("Stückliste;Lauf 1") and "Zuschnitt" in csv_text and "Summen" in csv_text


def test_status_shows_inventory_rule(srv):
    server, fake = srv
    assert "Inventar-Regel: an (nur Lagerteile und Druckteile)" in texts(call(server.url, "status"))[0]
    fake.violations = ["Klotz"]
    assert "Inventar-Regel: an (nur Lagerteile und Druckteile), 1 Verstoß: Klotz" in texts(call(server.url, "status"))[0]
