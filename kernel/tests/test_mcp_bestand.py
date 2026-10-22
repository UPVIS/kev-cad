"""MCP-Werkzeuge für den Bestand je Projekt mit der Attrappe über echtes Streamable HTTP (Texte, Pflichtfelder,
Schemas)."""

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


def test_bestand_werkzeuge(srv):
    server, fake = srv
    res = call(server.url, "bestand_liste")
    assert res.is_error is False and texts(res)[0].startswith("Bestand im Projekt „Wandhalter“:")
    assert fake.calls_of("bestand_liste") == [((None,), {})]
    res = call(server.url, "bestand_eintragen", {"id": "rohr-alfer-12x1", "ganze": 2, "reste": [430, 610, 180],
                                                 "grund": "Kevin: 2 Stangen, Reste 430, 610, 180"})
    text = texts(res)[0]
    assert res.is_error is False and text.startswith("Bestand eingetragen (B-0001, eintrag):")
    assert "- ALFER-Rundrohr 12 × 1 (rohr-alfer-12x1): Rest R-0002 (610 mm) dazu" in text
    assert "Kevin jede Änderung nennen" in text and 'buchung_rueckgaengig("B-0001")' in text
    (args, _), = fake.calls_of("bestand_eintragen")
    assert args == ("rohr-alfer-12x1", 2, [430.0, 610.0, 180.0], None, None, None, False,
                    "Kevin: 2 Stangen, Reste 430, 610, 180")
    res = call(server.url, "bestand_eintragen", {"id": "gibtsnicht", "ganze": 1, "grund": "x"})
    assert res.is_error is True and "Bestand nicht eingetragen" in texts(res)[0]
    # ohne grund geht nichts (nur nach Kevins Angabe)
    res = call(server.url, "bestand_eintragen", {"id": "rohr-alfer-12x1", "ganze": 1})
    assert res.is_error is True

    res = call(server.url, "einkaufsliste")
    assert res.is_error is True and "erst run" in texts(res)[0]
    call(server.url, "run")
    res = call(server.url, "einkaufsliste")
    text = texts(res)[0]
    assert "1 × Stange 1.000 mm ALFER-Rundrohr 12 × 1" in text and text.endswith(
        "CSV: /tmp/Kev CAD/Wandhalter/output/Wandhalter-einkaufsliste.csv")
    assert res.structured_content["einkauf_summe"] == 3.9

    res = call(server.url, "gebaut_buchen", {"grund": "Kevin: ist gebaut"})
    text = texts(res)[0]
    assert text.startswith("Gebaut gebucht (B-0002): 2 Reste weg") and 'buchung_rueckgaengig("B-0002")' in text
    assert call(server.url, "gebaut_buchen", {}).is_error is True  # grund ist Pflicht
    # Filament (Strang „Bestand Stufe 2“): ohne id, mit material
    res = call(server.url, "bestand_eintragen", {"material": "petg", "gramm": 640, "spule": "Bambu PETG Basic schwarz",
                                                 "grund": "Kevin: eine angebrochene PETG-Spule, etwa 640 g"})
    assert res.is_error is False and "Filament PETG: Spule S-0001" in texts(res)[0]
    (args, kw) = fake.calls_of("bestand_eintragen")[-1]
    assert args[0] is None and kw == {"material": "petg", "gramm": 640.0, "spule": "Bambu PETG Basic schwarz"}
    res = call(server.url, "gedruckt_buchen", {"grund": "Kevin: Platte 1 ist gedruckt", "platten": [1]})
    text = texts(res)[0]
    assert res.is_error is False and text.startswith("Gedruckt gebucht (B-0004, Platten 1)")
    assert "- PETG: 188,8 g, davon 188,8 g aus S-0001" in text
    assert fake.calls_of("gedruckt_buchen") == [(("Kevin: Platte 1 ist gedruckt", [1], None), {})]
    assert call(server.url, "gedruckt_buchen", {}).is_error is True  # grund ist Pflicht
    res = call(server.url, "buchung_rueckgaengig", {"id": "B-0002"})
    assert texts(res)[0].startswith("Buchung B-0002 rückgängig gemacht (B-0003)")
    res = call(server.url, "buchung_rueckgaengig", {"id": "B-0099"})
    assert res.is_error is True and "Nicht rückgängig gemacht" in texts(res)[0]


def test_bestand_schemas_und_hinweise(srv):
    server, _ = srv
    tools = {t.name: t for t in anyio.run(with_client, server.url, lambda c: c.list_tools()).tools}
    eintragen = tools["bestand_eintragen"]
    # id ist seit Strang „Bestand Stufe 2“ optional: Filament kommt mit material statt id
    assert set(eintragen.input_schema["required"]) == {"grund"}
    assert {"material", "gramm", "spule", "kennung", "spulen_entfernen"} <= set(eintragen.input_schema["properties"])
    assert "ONLY after Kevin stated it" in eintragen.description and "FILAMENT" in eintragen.description
    assert tools["gebaut_buchen"].input_schema["required"] == ["grund"]
    assert tools["gedruckt_buchen"].input_schema["required"] == ["grund"]
    assert "ONLY when Kevin explicitly says he printed" in tools["gedruckt_buchen"].description
    assert "ONLY when Kevin explicitly says" in tools["gebaut_buchen"].description
    assert tools["bestand_liste"].annotations.read_only_hint is True
    assert tools["buchung_rueckgaengig"].input_schema["required"] == ["id"]
    instructions = anyio.run(with_client, server.url, lambda c: _instructions(c))
    assert "Stock on hand and shopping list (Bestand, per project)" in instructions
    assert "`gebaut_buchen` only when Kevin explicitly says" in instructions


async def _instructions(c):
    return c.instructions
