"""Zwangsbedingungen über die volle Laufzeit: CONSTRAINTS nach RUN_END, Exportsperre, MCP-Werkzeug bedingungen,
Format wie die Testdatei der App (constraints.frame)."""

import shutil
import tempfile
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import texts, with_client

from kevcad_kernel.protocol import CONSTRAINT_FINDING_FIELDS, CONSTRAINT_ITEM_FIELDS, FrameReader
from kevcad_kernel.server import KevcadHTTPServer

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[1] / "app" / "KevCADCore" / "Tests" / "KevCADCoreTests" / "Fixtures"

MODELL = """from build123d import *
from kevcad import param, show, step
from kevcad.bedingungen import *

luft = param("luft", 0.0)
tisch = Box(100, 60, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
klotz = Box(20, 10, 5)
klotz = platziere(klotz, auf((klotz, "unten"), (tisch, "oben")), mittig((klotz, "mitte"), (tisch, "mitte"), "xy"),
                  parallel((klotz, "vorn"), (tisch, "vorn")))
verbinde(klotz, tisch, art="aufliegen")
verbinde(tisch, boden, art="aufliegen")
show(tisch, "Tisch")
show(Pos(0, 0, luft) * klotz, "Klotz")
"""


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcb", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    proj = tmp / "Bedingungen"
    assert rt.project_new(str(proj), "empty")["ok"]
    assert rt.model_write(MODELL)["ok"]
    assert rt.set_inventory_rule(False)["ok"]  # frei modellierte Teile: nur die Bedingungen sollen den Export sperren
    yield {"rt": rt, "app": app, "tmp": tmp, "sock": sock}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_constraints_nach_run_end_und_exportsperre(env):
    rt, app = env["rt"], env["app"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    kurz = res["bedingungen"]
    assert kurz["summe"]["fehler"] == 0 and kurz["summe"]["verletzt"] == 0, kurz
    _, _, msg, _ = app.wait_for(lambda h: h["type"] == "CONSTRAINTS" and h.get("run") == res["run"], start=start)
    types = [h["type"] for h in app.since(start) if h["type"] != "STATUS"]
    assert types.index("CONSTRAINTS") > types.index("RUN_END")
    # Felder wie in PROTOCOL.md und in der Testdatei der App
    (ref, _), = FrameReader().feed((FIXTURES / "constraints.frame").read_bytes())
    assert set(ref) - {"seq"} <= set(msg)
    for it in msg["items"]:
        assert set(CONSTRAINT_ITEM_FIELDS) <= set(it), it
    klotz = next(t for t in msg["teile"] if t["name"] == "Klotz")
    assert klotz["frei"] == 0 and klotz["befestigt"] and klotz["am_boden"]
    assert rt.constraints()["run"] == res["run"]
    out = rt.export(["stl"])
    assert out["ok"], out

    # von Hand verschoben: Bedingung verletzt, Export gesperrt, neue App bekommt den Bericht mit
    res = rt.run(params={"luft": 2})
    assert res["ok"]
    assert res["bedingungen"]["summe"]["fehler"] >= 1
    befund = next(b for b in res["bedingungen"]["befunde"] if b["pruefung"] == "bedingung")
    assert set(CONSTRAINT_FINDING_FIELDS) <= set(befund)
    assert "Luft 2 mm" in befund["ist"]
    out = rt.export(["stl"])
    assert not out["ok"] and "Export verweigert" in out["error"] and out["bedingungen_befunde"]
    second = FakeApp(env["sock"])
    try:
        second.wait_for(lambda h: h["type"] == "AGENT")
        snap = [h["type"] for h in second.since(0)]
        assert "CONSTRAINTS" in snap and snap.index("CONSTRAINTS") > snap.index("PART_UPSERT")
    finally:
        second.close()


def test_mcp_werkzeug_mit_attrappe():
    from mcp_testutil import start_server

    server, fake = start_server()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        leer = call("bedingungen")
        assert leer.is_error and "erst run" in texts(leer)[0]
        call("run")
        res = call("bedingungen")
        text = texts(res)[0]
        assert res.is_error  # ein Befund mit Schwere fehler
        assert text.startswith("Lauf 1: 2 Bedingungen, 1 erfüllt, 1 verletzt")
        assert "b1 auf: Halter/Lasche.unten auf Grundplatte.oben – verletzt" in text
        assert "→ Halter/Lasche um 2 mm entlang −Z verschieben" in text
        assert "Halter/Lasche: bestimmt, befestigt (aufliegen)" in text
        assert res.structured_content["summe"]["fehler"] == 1
        teil = call("bedingungen", {"part": "Halter/Bolzen", "alle": True})
        assert "b2 konzentrisch" in texts(teil)[0] and "b1 auf" not in texts(teil)[0]
        assert ("constraints", ("Halter/Bolzen",), {}) in fake.calls
    finally:
        server.stop_thread()


def test_mcp_werkzeug_bedingungen(env):
    rt = env["rt"]
    res = rt.run(params={"luft": 2})
    assert res["ok"]
    server = KevcadHTTPServer(rt, 0)
    server.start_in_thread()
    try:
        async def go(client):
            run = await client.call_tool("run", {"params": {"luft": 2}})
            alle = await client.call_tool("bedingungen", {"alle": True})
            teil = await client.call_tool("bedingungen", {"part": "Klotz"})
            falsch = await client.call_tool("bedingungen", {"part": "Gibtsnicht"})
            return run, alle, teil, falsch

        run, alle, teil, falsch = anyio.run(with_client, server.url, go)
    finally:
        server.stop_thread()
    assert run.is_error and "Bedingungen:" in texts(run)[0] and "Luft 2 mm" in texts(run)[0]
    text = texts(alle)[0]
    assert alle.is_error and "Klotz.unten auf Tisch.oben" in text and "verletzt" in text and "Befunde:" in text
    assert "Klotz: bestimmt" in texts(teil)[0]
    assert falsch.is_error
