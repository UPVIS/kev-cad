"""Freigabe im Projektfenster (Strang „Feinschliff 2“, Punkt 2): ``freigabe_anfragen`` öffnet den Dialog in der App
(FREIGABE_ANFRAGE), gibt selbst nichts frei und meldet, was Kevin freigegeben hat (aus dem Katalog), sobald er
entschieden oder den Dialog geschlossen hat (FREIGABE_GESCHLOSSEN). Laufzeit ohne Rechenprozess, Test-App am Socket;
MCP-Text über die Attrappe."""

import json
import shutil
import tempfile
import threading
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.protocol import check_freigabe_message

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"
ROHR = {"id": "rohr-edelstahl-33.7x2.6", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2,6", "norm": "ISO 1127",
        "masse": {"d": 33.7, "s": 2.6}, "material": "edelstahl-1.4301",
        "preis": {"je_m": 14.5, "quelle": "Kevin", "stand": "2026-10"}}
ROHR2 = {**ROHR, "id": "rohr-edelstahl-42.4x2", "name": "Edelstahlrohr 42,4 × 2", "masse": {"d": 42.4, "s": 2}}


@pytest.fixture
def umgebung():
    tmp = Path(tempfile.mkdtemp(prefix="kcf", dir=tempfile.gettempdir())).resolve()
    own = tmp / "eigen"
    own.mkdir()
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, own=own, start_worker=False)
    yield rt, sock
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def kevin(app: FakeApp, freigeben: list[str], schliessen: bool, ergebnis: dict, start: int):
    """Kevin in der App: Dialog öffnen (ACK), gewählte Einträge freigeben wie im Lagerkatalog (CATALOG_SAVE mit status
    frei), auf Wunsch den Dialog schließen."""
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "FREIGABE_ANFRAGE", start=start)
    ergebnis["anfrage"] = h
    app.send({"type": "ACK", "reply_to": h["id"], "ok": True, "message": "Dialog offen"})
    for eid in freigeben:
        entry = {**(ROHR if eid == ROHR["id"] else ROHR2), "status": "frei"}
        start = app.mark()
        app.send({"type": "CATALOG_SAVE", "id": f"a-{eid}", "kind": "teil", "entry": entry, "ebene": "eigen"})
        app.wait_for(lambda m: m["type"] == "ACK" and m.get("reply_to") == f"a-{eid}", start=start)
    if schliessen:
        app.send({"type": "FREIGABE_GESCHLOSSEN", "anfrage": h["anfrage"], "freigegeben": freigeben, "abgelehnt": [],
                  "offen": [e["id"] for e in h["eintraege"] if e["id"] not in freigeben]})


def test_freigabe_ueber_den_dialog(umgebung):
    rt, sock = umgebung
    # ohne App: kein Dialog, nichts passiert
    assert rt.stock_define(ROHR)["ok"] and rt.stock_define(ROHR2)["ok"]
    res = rt.freigabe_anfragen([ROHR["id"]], "x", warten_s=1)
    assert res["ok"] is False and "App nicht verbunden" in res["error"]
    app = FakeApp(sock, answer=False)
    try:
        app.wait_for(lambda h: h["type"] == "HELLO")
        # Unbekannte id: Fehler mit Vorschlag
        res = rt.freigabe_anfragen(["rohr-edelstahl-33.7x2.5"], "x")
        assert res["ok"] is False and "rohr-edelstahl-33.7x2.6" in res["error"]
        # Kevin gibt einen frei und schließt den Dialog
        ergebnis: dict = {}
        t = threading.Thread(target=kevin, args=(app, [ROHR["id"]], True, ergebnis, app.mark()))
        t.start()
        res = rt.freigabe_anfragen([ROHR["id"], ROHR2["id"]], "Für die Führungen", warten_s=20)
        t.join(10)
        h = ergebnis["anfrage"]
        assert not check_freigabe_message(h)
        assert [(e["id"], e["kind"], e["name"]) for e in h["eintraege"]] == [
            (ROHR["id"], "teil", ROHR["name"]), (ROHR2["id"], "teil", ROHR2["name"])]
        assert h["grund"] == "Für die Führungen"
        assert res["ok"] and res["freigegeben"] == [ROHR["id"]] and res["offen"] == [ROHR2["id"]]
        assert res["dialog"] == "geschlossen" and res["abgelehnt"] == []
        assert rt.catalog.item(ROHR["id"])["status"] == "frei"
        # schon frei: kein Dialog
        start = app.mark()
        res = rt.freigabe_anfragen([ROHR["id"]], "x")
        assert res["ok"] and res["dialog"] == "nicht_noetig" and res["schon_frei"] == [ROHR["id"]]
        assert not [m for m in app.since(start) if m["type"] == "FREIGABE_ANFRAGE"]
        # Kevin gibt den zweiten frei, ohne zu schließen: die Anfrage endet, sobald alles entschieden ist
        ergebnis = {}
        t = threading.Thread(target=kevin, args=(app, [ROHR2["id"]], False, ergebnis, app.mark()))
        t.start()
        res = rt.freigabe_anfragen([ROHR2["id"]], "", warten_s=20)
        t.join(10)
        assert res["dialog"] == "entschieden" and res["freigegeben"] == [ROHR2["id"]] and res["offen"] == []
        assert ergebnis["anfrage"]["grund"] is None
        # Zeitlimit: Dialog bleibt offen, nichts ist freigegeben
        assert rt.stock_define({**ROHR2, "id": "rohr-edelstahl-48.3x2"})["ok"]
        ergebnis = {}
        t = threading.Thread(target=kevin, args=(app, [], False, ergebnis, app.mark()))
        t.start()
        res = rt.freigabe_anfragen(["rohr-edelstahl-48.3x2"], "x", warten_s=0.5)
        t.join(10)
        assert res["dialog"] == "offen" and res["offen"] == ["rohr-edelstahl-48.3x2"] and res["freigegeben"] == []
        assert rt.catalog.item("rohr-edelstahl-48.3x2")["status"] == "vorgeschlagen"
    finally:
        app.close()


def test_testdateien_passen_zum_protokoll():
    data = json.loads((FIXTURES / "fixtures.json").read_text())["freigabe"]
    for teil in ("anfrage", "geschlossen"):
        assert not check_freigabe_message(data[teil])
    assert [f["file"] for f in data["frames"]] == ["freigabe_anfrage.frame", "freigabe_geschlossen.frame"]


def call(url, name, args):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args))


def test_mcp_text():
    server, fake = start_server()
    try:
        res = call(server.url, "freigabe_anfragen", {"ids": ["rohr-a", "rohr-offen"], "grund": "Für die Führung"})
        text = texts(res)[0]
        assert res.is_error is False
        assert text.startswith("Freigabe F-0001: Kevin hat freigegeben: rohr-a.")
        assert "Offen: rohr-offen (Kevin hat den Dialog geschlossen)" in text and "Nicht verbauen" in text
        (args, _), = fake.calls_of("freigabe_anfragen")
        assert args == (["rohr-a", "rohr-offen"], "Für die Führung", None)
        res = call(server.url, "freigabe_anfragen", {"ids": ["gibtsnicht"]})
        assert res.is_error is True and texts(res)[0].startswith("Freigabe nicht angefragt")
        tools = {t.name: t for t in anyio.run(with_client, server.url, lambda c: c.list_tools()).tools}
        assert "never releases anything itself" in tools["freigabe_anfragen"].description
        instructions = anyio.run(with_client, server.url, _instructions)
        assert "freigabe_anfragen" in instructions and "never tell him to open the stock catalog" in instructions
    finally:
        server.stop_thread()


async def _instructions(c):
    return c.instructions
