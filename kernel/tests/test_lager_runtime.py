"""Phase 2 über die volle Laufzeit (Rechenprozess, Test-App am Socket, Test-Katalog): BOM nach RUN_END, stock an
PART_UPSERT, CATALOG_REQ/SAVE/DELETE, Freigabe von Vorschlägen, Inventar-Regel mit Export-Sperre und SETTINGS, CSV-Export
und die MCP-Werkzeuge über den echten Server."""

import json
import shutil
import tempfile
import time
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import texts, with_client

from kevcad_kernel.protocol import FrameReader
from kevcad_kernel.server import KevcadHTTPServer

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURES = REPO / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"
GESTELL = (REPO / "samples" / "gestell" / "model.py").read_text(encoding="utf-8")
HEAD = "from build123d import *\nfrom kevcad import lager, show, step, param\n"


@pytest.fixture(scope="module")
def p2():
    tmp = Path(tempfile.mkdtemp(prefix="kc2", dir=tempfile.gettempdir()))
    own = tmp / "eigen"
    own.mkdir()
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, own=own)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp, "own": own, "sock": sock}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


_n = iter(range(1, 1000))


def new_project(p2, code: str) -> Path:
    path = p2["tmp"] / f"Q{next(_n)}"
    assert p2["rt"].project_new(str(path), "empty")["ok"]
    assert p2["rt"].model_write(code)["ok"]
    return path


def fixture_header(name: str) -> dict:
    (header, _), = FrameReader().feed((FIXTURES / name).read_bytes())
    return header


def request(app, header: dict, timeout: float = 30):
    start = app.mark()
    app.send(header)
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == header["id"], start=start, timeout=timeout)
    return reply


# ---------------------------------------------------------------------------------------------------------------------


def test_gestell_bom_after_run_end(p2):
    rt, app = p2["rt"], p2["app"]
    new_project(p2, GESTELL)
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    assert res["inventar_verstoesse"] == [] and res["bom"]["totals"]["positionen"] == 5
    _, _, bom, _ = app.wait_for(lambda h: h["type"] == "BOM" and h.get("run") == res["run"], start=start)
    app.wait_for(lambda h: h["type"] == "CONSTRAINTS" and h.get("run") == res["run"], start=start)
    types = [h["type"] for h in app.since(start) if h["type"] not in ("STATUS", "CHECK")]
    assert types[-3:] == ["RUN_END", "BOM", "CONSTRAINTS"]  # CONSTRAINTS: Zwangsbedingungen, additiv
    parts = [h for h in app.since(start) if h["type"] == "PART_UPSERT"]
    bein = next(h for h in parts if h["name"] == "Gestell/Bein vorn links")
    assert bein["stock"] == {"id": "vierkantrohr-en10219-40x40x3", "name": "Vierkantrohr 40 × 40 × 3", "laenge": 842.0,
                             "gehrung": [0.0, 0.0], "material": "stahl-s235", "kg": 2.779, "preis": 6.74}
    assert bein["inventar"] == "ok" and bein["material"] == "Stahl S235"
    # gleiches Format wie die Testdatei der App (bom.frame): alle Felder dort gibt es auch hier
    ref = fixture_header("bom.frame")
    assert set(ref) - {"seq"} <= set(bom)
    for ref_line in ref["lines"]:
        if ref_line["art"] == "eigenteil":
            continue
        mine = next(ln for ln in bom["lines"] if ln["art"] == ref_line["art"])
        assert set(ref_line) <= set(mine), set(ref_line) - set(mine)
        for key in ("laenge", "gehrung", "anzahl", "kg_je", "preis_je", "teile", "eigenteil", "masse_text"):
            assert type(mine[key]) is type(ref_line[key]) or mine[key] is None, key
    assert set(ref["cuts"][0]) <= set(bom["cuts"][0]) and set(ref["totals"]) <= set(bom["totals"])
    (cut,) = [c for c in bom["cuts"] if c.get("art") != "platte"]  # Platten: Zuschnitt mit Bestand (BESTAND.md)
    assert cut["stangen"] == [[842, 842, 842, 842, 800, 800, 600], [600]] and cut["saegeschnitt"] == 3
    # Fassade und BOM_REQ liefern dieselbe Liste
    assert rt.bom() == {"ok": True, **{k: v for k, v in bom.items() if k not in ("type", "seq")}}
    reply = request(app, {"type": "BOM_REQ", "id": "a-1"})
    assert reply["type"] == "BOM" and reply["lines"] == bom["lines"] and reply["run"] == res["run"]
    # neue Verbindung bekommt die Stückliste mit
    second = FakeApp(p2["sock"])
    try:
        second.wait_for(lambda h: h["type"] == "AGENT")
        snap = [h["type"] for h in second.since(0)]
        assert "BOM" in snap and snap.index("BOM") > snap.index("PART_UPSERT")
    finally:
        p2["app"] = second
        app.close()


def test_catalog_messages_and_release(p2):
    rt, app, own = p2["rt"], p2["app"], p2["own"]
    new_project(p2, HEAD + "show(lager.teil('rohr-en10220-42.4x2.0').verbauen(laenge=100, name='R'), 'R')\n")
    cat = request(app, {"type": "CATALOG_REQ", "id": "a-10", "query": None, "art": None})
    assert cat["type"] == "CATALOG" and len(cat["items"]) == 11 and len(cat["materials"]) == 7
    assert cat["arten"][:3] == ["rohr", "vierkantrohr", "rechteckrohr"]
    assert all(i["ebene"] == "mitgeliefert" and i["status"] == "frei" for i in cat["items"])
    ref = fixture_header("catalog.frame")
    assert set(ref) - {"seq"} <= set(cat)
    assert set(ref["items"][0]) <= set(next(i for i in cat["items"] if i["id"] == ref["items"][0]["id"]))
    hit = request(app, {"type": "CATALOG_REQ", "id": "a-11", "query": "40×40×3", "art": "vierkantrohr"})
    assert [i["id"] for i in hit["items"]] == ["vierkantrohr-en10219-40x40x3"]

    # Agent schlägt vor (MCP stock_define): steht im Katalog, lässt sich aber nicht verbauen
    entry = {"id": "rohr-edelstahl-33.7x2.6", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2,6", "norm": "ISO 1127",
             "masse": {"d": 33.7, "s": 2.6}, "material": "edelstahl-1.4301",
             "preis": {"je_m": 14.5, "quelle": "Kevin", "stand": "2026-10"}}
    res = rt.stock_define(entry)
    assert res["ok"] and res["item"]["status"] == "vorgeschlagen" and res["datei"] == str(own / "eigene.json")
    assert res["kg_je_m"] == pytest.approx(2.006, abs=0.005) and res["preis_text"] == "14,50 €/m"
    assert rt.stock_define({**entry, "id": "rohr-en10220-42.4x2.0"})["ok"] is False  # freigegeben: nur Kevin
    bad = rt.stock_define({**entry, "id": "x", "masse": {"d": 33.7}})
    assert bad["ok"] is False and "masse.s fehlt" in bad["error"]
    rt.model_write(HEAD + "show(lager.teil('rohr-edelstahl-33.7x2.6').verbauen(laenge=100, name='R'), 'R')\n")
    run = rt.run()
    assert run["ok"] is False and "wartet auf Kevins Freigabe im Lagerkatalog" in run["error"]["message"]

    # Kevin gibt in der App frei: CATALOG_SAVE mit status "frei"
    item = next(i for i in request(app, {"type": "CATALOG_REQ", "id": "a-12", "query": "33,7x2,6", "art": None})["items"])
    assert item["status"] == "vorgeschlagen" and item["ebene"] == "eigen"
    ack = request(app, {"type": "CATALOG_SAVE", "id": "a-13", "kind": "teil", "entry": {**item, "status": "frei"},
                        "ebene": "eigen"})
    assert ack["type"] == "ACK" and ack["ok"] is True
    stored = json.loads((own / "eigene.json").read_text(encoding="utf-8"))["teile"]
    assert [t["status"] for t in stored] == ["frei"] and "ebene" not in stored[0]
    run = rt.run()
    assert run["ok"], run.get("error")
    assert run["parts"][0]["stock"]["id"] == "rohr-edelstahl-33.7x2.6"
    # ungültig aus der App: ACK mit Fehler
    ack = request(app, {"type": "CATALOG_SAVE", "id": "a-14", "kind": "material", "entry": {"id": "x"},
                        "ebene": "eigen"})
    assert ack["ok"] is False and "dichte fehlt" in ack["message"]
    # Ablehnen bzw. löschen
    ack = request(app, {"type": "CATALOG_DELETE", "id": "a-15", "kind": "teil", "entry_id": "rohr-edelstahl-33.7x2.6",
                        "ebene": "eigen"})
    assert ack["ok"] is True and rt.stock_get("rohr-edelstahl-33.7x2.6")["ok"] is False
    assert rt.catalog_delete("teil", "gibtsnicht")["ok"] is False
    mats = rt.material_list("holz")
    assert [m["id"] for m in mats["materials"]] == ["fichte-kvh", "multiplex-birke"]
    res = rt.material_define({"id": "pla-matt", "name": "PLA matt", "gruppe": "Kunststoff", "dichte": 1.24,
                              "farbe": "#EEEEEE", "druckbar": True})
    assert res["ok"] and res["material"]["status"] == "vorgeschlagen"
    assert rt.catalog_delete("material", "pla-matt")["ok"]


def test_inventory_rule_export_and_settings(p2):
    rt, app = p2["rt"], p2["app"]
    path = new_project(p2, HEAD + "show(Pos(60, 0, 0) * Box(10, 10, 10), 'Klotz')\n"
                                  "show(lager.teil('flach-en10058-40x5').verbauen(laenge=100, name='F'), 'F')\n")
    start = app.mark()
    res = rt.run()
    assert res["ok"] and res["inventar_verstoesse"] == ["Klotz"]
    _, _, end, _ = app.wait_for(lambda h: h["type"] == "RUN_END", start=start)
    assert end["inventar_regel"] is True and end["inventar_verstoesse"] == ["Klotz"]
    klotz = next(h for h in app.since(start) if h["type"] == "PART_UPSERT" and h["name"] == "Klotz")
    assert klotz["inventar"] == "fehlt"
    assert rt.status()["inventar"] == {"regel": True, "verstoesse": ["Klotz"]}
    for fmt in (["step"], ["stl"], ["3mf"], ["bom_csv"], ["glb", "step"]):
        out = rt.export(fmt)
        assert out["ok"] is False and out["error"].startswith("Export verweigert. Inventar-Regel: 1 Teil ist nicht")
    assert rt.export(["glb"])["ok"]  # nur zum Ansehen
    reply = request(app, {"type": "EXPORT_REQ", "id": "a-20", "formats": ["step"], "parts": None})
    assert reply["type"] == "ERROR" and "Inventar-Regel" in reply["message"]
    # Kevin schaltet die Regel für dieses Projekt ab (SETTINGS aus der App)
    start = app.mark()
    app.send({"type": "SETTINGS", "auto_run": False, "slow_ms": 0, "inventar_regel": False})
    _, _, proj, _ = app.wait_for(lambda h: h["type"] == "PROJECT" and h.get("inventar_regel") is False, start=start)
    assert json.loads((path / "kevcad.json").read_text())["inventar_regel"] is False
    res = rt.run()
    assert res["inventar_regel"] is False and res["inventar_verstoesse"] == []
    out = rt.export(["step", "bom_csv"])
    assert out["ok"], out
    csv_file = Path(out["files"][-1])
    assert csv_file.name.endswith("-stueckliste.csv") and csv_file.read_bytes().startswith(b"\xef\xbb\xbf")
    text = csv_file.read_text(encoding="utf-8-sig")
    assert text.startswith("Stückliste;") and "Flachstahl 40 × 5" in text and b"\r\n" in csv_file.read_bytes()
    reply = request(app, {"type": "EXPORT_REQ", "id": "a-21", "formats": ["bom_csv"], "parts": None})
    assert reply["type"] == "EXPORT_RES" and reply["files"][0].endswith("-stueckliste.csv")
    app.send({"type": "SETTINGS", "auto_run": False, "slow_ms": 0, "inventar_regel": True})
    assert rt.wait_idle(10)
    t0 = time.monotonic()
    while json.loads((path / "kevcad.json").read_text()).get("inventar_regel") is not True and time.monotonic() - t0 < 5:
        time.sleep(0.05)
    assert rt.run()["inventar_verstoesse"] == ["Klotz"]


def test_execute_knows_lager(p2):
    rt = p2["rt"]
    new_project(p2, HEAD + "r = lager.teil('rohr-en10220-42.4x2.0')\nshow(r.verbauen(laenge=50, name='R'), 'R')\n")
    assert rt.run()["ok"]
    res = rt.execute("r.kg_je_m, lager.suche('42,4')[0].id")
    assert res["ok"] and res["result"] == "(1.99, 'rohr-en10220-42.4x2.0')"


def test_mcp_tools_against_runtime(p2):
    rt = p2["rt"]
    new_project(p2, GESTELL + "show(Box(5, 5, 5), 'Hilfsklotz')\n")
    server = KevcadHTTPServer(rt, 0)
    server.start_in_thread()
    try:
        async def go(c):
            return {
                "search": await c.call_tool("stock_search", {"query": "vierkantrohr 40x40x3"}),
                "get": await c.call_tool("stock_get", {"id": "rohr-en10220-42.4x2.0"}),
                "run": await c.call_tool("run", {}),
                "bom": await c.call_tool("bom", {}),
                "csv": await c.call_tool("bom", {"format": "csv"}),
                "define": await c.call_tool("stock_define", {"entry": {
                    "id": "flach-edelstahl-30x3", "art": "flach", "name": "Flach Edelstahl 30 × 3",
                    "masse": {"b": 30, "s": 3}, "material": "edelstahl-1.4301"}}),
                "mats": await c.call_tool("material_list", {"query": "kunststoff"}),
                "delete": await c.call_tool("catalog_delete", {"kind": "teil", "id": "flach-edelstahl-30x3"}),
                "export": await c.call_tool("export", {"formats": ["step"]}),
            }

        r = anyio.run(with_client, server.url, go)
    finally:
        server.stop_thread()
    search = texts(r["search"])[0]
    assert "vierkantrohr-en10219-40x40x3" in search and "8,00 €/m" in search and "frei" in search
    assert "Querschnitt 253,8 mm²" in texts(r["get"])[0] and "1,99 kg/m (Tabelle)" in texts(r["get"])[0]
    run = texts(r["run"])[0]
    assert r["run"].is_error and run.startswith("Inventar-Regel: 1 Teil ist nicht aus dem Inventar: Hilfsklotz")
    assert "Stückliste: 5 Positionen, 17 Teile" in run
    bom = texts(r["bom"])[0]
    assert "Zuschnitt (Sägeschnitt 3 mm):" in bom
    assert "kaufen Stange 1 (6.000 mm): 842 + 842 + 842 + 842 + 800 + 800 + 600; neuer Rest" in bom
    assert texts(r["csv"])[0].startswith("Stückliste;")
    define = texts(r["define"])[0]
    assert not r["define"].is_error and "als Vorschlag" in define and "wartet auf Kevins Freigabe im Lagerkatalog" in define
    assert "petg" in texts(r["mats"])[0] and "ja" in texts(r["mats"])[0]
    assert not r["delete"].is_error
    assert r["export"].is_error and "Export verweigert" in texts(r["export"])[0]
