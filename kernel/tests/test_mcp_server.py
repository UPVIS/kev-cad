"""MCP-Server mit Attrappe über echtes Streamable HTTP und den MCP-Client des Pakets (AP6)."""

from __future__ import annotations

import base64
import json
import os
import signal
import socket
import subprocess
import sys
import time

import anyio
import pytest
from fake_service import PNG
from mcp_testutil import (
    EXPECTED_TOOLS,
    FAKE_KERNEL,
    free_port,
    port_open,
    start_server,
    texts,
    wait_for,
    with_client,
)

import kevcad_kernel.server as server_mod


@pytest.fixture
def srv():
    server, fake = start_server()
    yield server, fake
    server.stop_thread()


def call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


# --------------------------------------------------------------------------------------------------------- Werkzeuge


def test_tool_list_complete_with_schemas(srv):
    server, _ = srv

    async def go(c):
        return (await c.list_tools()).tools, c.instructions, c.server_info

    tools, instructions, info = anyio.run(with_client, server.url, go)
    by_name = {t.name: t for t in tools}
    assert set(by_name) == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description and len(tool.description) > 20, tool.name
        assert tool.input_schema["type"] == "object", tool.name
        assert tool.title, tool.name
        assert tool.annotations is not None, tool.name
    schema = {n: t.input_schema for n, t in by_name.items()}
    assert schema["project_open"]["required"] == ["path"]
    assert schema["model_write"]["required"] == ["code"]
    assert schema["measure"]["required"] == ["refs"]
    assert set(schema["annotate"]["required"]) == {"kind", "points"}
    assert schema["export"]["required"] == ["formats"]
    assert schema["export"]["properties"]["formats"]["items"]["enum"] == ["step", "stl", "3mf", "glb", "bom_csv",
                                                                      "einkaufsliste_csv"]
    assert schema["screenshot"]["properties"]["width"]["default"] == 1280
    assert schema["screenshot"]["properties"]["height"]["default"] == 800
    assert schema["measure"]["properties"]["show"]["default"] is True
    std = schema["view"]["properties"]["standard"]["anyOf"][0]["enum"]
    assert {"top", "front", "iso", "iso_back_left"} <= set(std)
    assert schema["visibility"]["properties"]["mode"]["enum"] == ["show", "hide", "isolate", "show_all"]
    assert "params" in schema["run"]["properties"] and "slow_ms" in schema["run"]["properties"]
    assert by_name["status"].annotations.read_only_hint is True
    assert info.name == "kevcad"
    for needle in ("show(", "step(", "param(", "mm", "screenshot", "measure", "selection", "one run"):
        assert needle in instructions, needle


def test_run_returns_summary_and_data(srv):
    server, fake = srv
    res = call(server.url, "run", {"params": {"breite": 140}, "slow_ms": 300})
    assert res.is_error is False
    summary, data_text = texts(res)
    assert "Lauf 1 fertig" in summary and "2 Teile" in summary
    assert "Grundplatte: 120 × 80 × 5 mm" in summary and "Lasche" in summary
    assert "128,1 g" in summary and "Warnung" in summary
    data = res.structured_content
    assert json.loads(data_text) == data
    assert data["ok"] is True and data["run"] == 1
    assert [p["name"] for p in data["parts"]] == ["Grundplatte", "Halter/Lasche"]
    assert data["parts"][0]["size"] == [120.0, 80.0, 5.0]
    assert data["parts"][0]["mass"] == pytest.approx(128.07)
    assert data["params"] == {"breite": 140}
    assert fake.calls_of("run") == [(({"breite": 140.0}, 300), {})]


def test_run_error_is_tool_error_with_line(srv):
    server, fake = srv
    fake.fail_run = True
    res = call(server.url, "run")
    assert res.is_error is True
    summary = texts(res)[0]
    assert "Zeile 12" in summary and "NameError" in summary
    assert "show(platt" in summary  # Auszug
    assert "Hinweis: Tippfehler" in summary
    assert res.structured_content["error"]["line"] == 12


def test_screenshot_returns_png_image(srv):
    server, fake = srv
    res = call(server.url, "screenshot", {"width": 640, "height": 400})
    assert res.is_error is False
    images = [b for b in res.content if b.type == "image"]
    assert len(images) == 1
    assert images[0].mime_type == "image/png"
    assert base64.b64decode(images[0].data) == PNG
    summary = texts(res)[0]
    assert "640 × 400 px" in summary and "0,125 mm je Pixel" in summary and "Kamera" in summary
    assert res.structured_content["mm_per_px"] == 0.125
    assert fake.calls_of("screenshot") == [((640, 400, "current", None, False), {})]
    # Standardansicht geht automatisch offscreen, Kevins Kamera bleibt stehen
    call(server.url, "screenshot", {"view": "front"})
    assert fake.calls_of("screenshot")[-1] == ((1280, 800, "offscreen", "front", False), {})


def test_view_commands_send_protocol_args(srv):
    server, fake = srv
    url = server.url

    async def go(c):
        out = []
        out.append(await c.call_tool("view", {"standard": "iso", "projection": "orthographic", "fit": True}))
        out.append(await c.call_tool("view", {"explode": 0.5}))
        out.append(await c.call_tool("focus", {"refs": ["Halter/Lasche#f3"]}))
        out.append(await c.call_tool("visibility", {"mode": "isolate", "refs": ["Halter/Lasche"]}))
        out.append(await c.call_tool("visibility", {"mode": "show_all"}))
        out.append(await c.call_tool("highlight", {"refs": ["Grundplatte#f0"], "color": "#FF0000", "label": "hier"}))
        out.append(await c.call_tool("section", {"enabled": True, "axis": "y", "offset": 12.5}))
        out.append(await c.call_tool("section", {"enabled": False}))
        out.append(await c.call_tool("annotate", {"kind": "dimension", "points": [[0, 0, 0], [0, 0, 42.4]]}))
        out.append(await c.call_tool("annotate", {"kind": "label", "points": [[1, 2, 3]], "text": "M6", "id": "x1"}))
        out.append(await c.call_tool("clear_annotations", {"ids": ["x1"]}))
        out.append(await c.call_tool("clear_annotations", {}))
        return out

    results = anyio.run(with_client, url, go)
    assert all(not r.is_error for r in results), [texts(r) for r in results if r.is_error]
    cmds = [a for a, _ in fake.calls_of("view_command")]
    assert cmds == [
        ("view", {"standard": "iso", "projection": "orthographic", "display": None, "fit": True}),
        ("explode", {"factor": 0.5}),
        ("focus", {"refs": ["Halter/Lasche#f3"], "animate": True}),
        ("visibility", {"mode": "isolate", "refs": ["Halter/Lasche"]}),
        ("visibility", {"mode": "show_all", "refs": []}),
        ("highlight", {"refs": ["Grundplatte#f0"], "color": [1.0, 0.0, 0.0, 1.0], "label": "hier", "clear": True}),
        ("section", {"enabled": True, "offset": 12.5, "axis": "y"}),
        ("section", {"enabled": False, "offset": 0.0, "axis": "z"}),
        ("annotate", {"kind": "dimension", "points": [[0.0, 0.0, 0.0], [0.0, 0.0, 42.4]], "text": "42,4 mm",
                      "id": "agent-1"}),
        ("annotate", {"kind": "label", "points": [[1.0, 2.0, 3.0]], "text": "M6", "id": "x1"}),
        ("clear_annotations", {"ids": ["x1"]}),
        ("clear_annotations", {"ids": None}),
    ]
    assert results[8].structured_content["id"] == "agent-1"
    assert "Kamera auf Halter/Lasche#f3" in texts(results[2])[0]


def test_invalid_input_is_tool_error(srv):
    server, fake = srv

    async def go(c):
        return [
            await c.call_tool("focus", {"refs": []}),
            await c.call_tool("view", {}),
            await c.call_tool("measure", {"refs": ["a", "b", "c"]}),
            await c.call_tool("annotate", {"kind": "dimension", "points": [[0, 0, 0]]}),
            await c.call_tool("highlight", {"refs": ["a"], "color": "nichtsfarbe"}),
            await c.call_tool("run", {"slow_ms": -5}),
            await c.call_tool("gibtsnicht", {}),
        ]

    results = anyio.run(with_client, server.url, go)
    assert all(r.is_error for r in results)
    assert "Mindestens eine Referenz" in texts(results[0])[0]
    assert "Nichts zu tun" in texts(results[1])[0]
    assert "Höchstens 2" in texts(results[2])[0]
    assert "mindestens 2 Punkte" in texts(results[3])[0]
    assert "Unbekannte Farbe" in texts(results[4])[0]
    assert fake.calls_of("view_command") == [] and fake.calls_of("run") == []


def test_service_errors_become_tool_errors(srv):
    server, fake = srv
    fake.app_connected = False
    fake.raise_in.add("export")

    async def go(c):
        return [
            await c.call_tool("view", {"standard": "top"}),
            await c.call_tool("screenshot", {}),
            await c.call_tool("measure", {"refs": ["Grundplatte#f99"]}),
            await c.call_tool("project_open", {"path": "/x/gibtsnicht"}),
            await c.call_tool("execute", {"code": "raise 1/0"}),
            await c.call_tool("export", {"formats": ["step"]}),
        ]

    view, shot, meas, proj, exe, exp = anyio.run(with_client, server.url, go)
    assert view.is_error and "App nicht verbunden" in texts(view)[0]
    assert shot.is_error and "App nicht verbunden" in texts(shot)[0]
    assert meas.is_error and "Unbekannte Referenz" in texts(meas)[0]
    assert proj.is_error and "Kein Projektordner" in texts(proj)[0]
    assert exe.is_error and "ZeroDivisionError" in texts(exe)[0] and "vorher" in texts(exe)[0]
    assert exp.is_error and "RuntimeError" in texts(exp)[0] and "kaputt" in texts(exp)[0]


def test_read_tools_and_projects(srv, monkeypatch, tmp_path):
    server, fake = srv
    monkeypatch.setenv("KEVCAD_PROJECTS_DIR", str(tmp_path))

    async def go(c):
        return {
            "new": await c.call_tool("project_new", {"path": "Wandhalter"}),
            "open": await c.call_tool("project_open", {"path": "~/Kev/Rohrschelle"}),
            "write": await c.call_tool("model_write", {"code": "x = 1\n"}),
            "read": await c.call_tool("model_read", {}),
            "parts0": await c.call_tool("parts", {}),
            "run": await c.call_tool("run", {}),
            "parts": await c.call_tool("parts", {}),
            "status": await c.call_tool("status", {}),
            "selection": await c.call_tool("selection", {}),
            "measure": await c.call_tool("measure", {"refs": ["Halter/Lasche#f3", "Grundplatte#f0"]}),
            "execute": await c.call_tool("execute", {"code": "print(platte.volume)"}),
            "export": await c.call_tool("export", {"formats": ["step", "3mf"]}),
        }

    r = anyio.run(with_client, server.url, go)
    assert all(not v.is_error for v in r.values()), {k: texts(v) for k, v in r.items() if v.is_error}
    assert fake.calls_of("project_new") == [((str(tmp_path / "Wandhalter"), "example"), {})]
    assert fake.calls_of("project_open") == [((os.path.expanduser("~/Kev/Rohrschelle"),), {})]
    assert "x = 1" in texts(r["read"])[0]
    assert r["read"].structured_content["code"] == "x = 1\n"
    assert "Keine Teile" in texts(r["parts0"])[0]
    assert len(r["parts"].structured_content["parts"]) == 2
    assert "Halter/" in texts(r["parts"])[0]
    status = texts(r["status"])[0]
    assert "Projekt Rohrschelle" in status and "Letzter Lauf 1" in status and "Halter/Lasche#f3" in status
    sel = texts(r["selection"])[0]
    assert "2 Elemente" in sel and "Ebene, 200,000 mm²" in sel
    assert "Abstand 12,500 mm" in texts(r["measure"])[0]
    assert fake.calls_of("measure") == [((["Halter/Lasche#f3", "Grundplatte#f0"], True), {})]
    assert "Ausgabe:\n47434.5" in texts(r["execute"])[0] and "Ergebnis: 8" in texts(r["execute"])[0]
    assert r["export"].structured_content["files"][0].endswith(".step")
    assert fake.calls_of("export") == [((["step", "3mf"], None), {})]


# ------------------------------------------------------------------------------------------------- Anzeige in der App


def test_activity_is_set_and_cleared(srv):
    server, fake = srv
    call(server.url, "run")
    call(server.url, "measure", {"refs": ["Halter/Lasche#f3", "Grundplatte#f0"]})
    call(server.url, "screenshot")
    assert fake.activity == [
        "führt model.py aus", None,
        "misst Abstand Halter/Lasche#f3 ↔ Grundplatte#f0", None,
        "macht ein Bild der Ansicht", None,
    ]


def test_parallel_calls_do_not_block(srv):
    server, fake = srv
    fake.delays["run"] = 1.0
    timings: dict[str, float] = {}

    async def go(c):
        t0 = time.perf_counter()

        async def slow(i):
            await c.call_tool("run", {})
            timings[f"run{i}"] = time.perf_counter() - t0

        async def quick():
            await anyio.sleep(0.2)
            t1 = time.perf_counter()
            await c.call_tool("status", {})
            timings["status"] = time.perf_counter() - t1
            timings["activity_during"] = fake.activity[-1]

        async with anyio.create_task_group() as tg:
            tg.start_soon(slow, 1)
            tg.start_soon(slow, 2)
            tg.start_soon(quick)
        timings["total"] = time.perf_counter() - t0

    anyio.run(with_client, server.url, go)
    assert timings["status"] < 0.5, timings
    assert timings["total"] < 1.8, timings
    # während der Läufe zeigt die App wieder "führt model.py aus", am Ende nichts mehr
    assert timings["activity_during"] == "führt model.py aus"
    assert fake.activity[-1] is None
    assert "schaut auf den Stand" in fake.activity


def test_agent_connected_follows_sessions(srv):
    server, fake = srv

    async def go(c):
        await c.call_tool("status", {})
        assert wait_for(lambda: fake.connected == [True], 3)

    anyio.run(with_client, server.url, go)
    assert wait_for(lambda: fake.connected == [True, False], 3), fake.connected
    assert server.tracker.session_count == 0


def test_agent_disconnect_detected_when_client_dies():
    server, fake = start_server(grace_s=0.5, poll_s=0.1)
    try:
        script = (
            "import anyio, sys\n"
            "from mcp import Client\n"
            "async def main():\n"
            "    async with Client(sys.argv[1], mode='legacy') as c:\n"
            "        await c.list_tools()\n"
            "        print('ready', flush=True)\n"
            "        await anyio.sleep(60)\n"
            "anyio.run(main)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", script, server.url], stdout=subprocess.PIPE, text=True)
        try:
            assert proc.stdout.readline().strip() == "ready"
            assert wait_for(lambda: fake.connected == [True], 3), fake.connected
            time.sleep(1.0)  # GET-Strom offen: bleibt verbunden, auch nach der Schonfrist
            assert fake.connected == [True]
        finally:
            proc.kill()  # wie ein Absturz: kein DELETE
            proc.wait()
        assert wait_for(lambda: fake.connected == [True, False], 5), fake.connected
    finally:
        server.stop_thread()


def test_stateless_clients_count_as_connected():
    server, fake = start_server(stateless_s=0.5, poll_s=0.1)
    try:
        anyio.run(with_client, server.url, lambda c: c.call_tool("status", {}), "auto")
        assert wait_for(lambda: fake.connected[:1] == [True], 3), fake.connected
        assert wait_for(lambda: fake.connected == [True, False], 3), fake.connected
    finally:
        server.stop_thread()


# ------------------------------------------------------------------------------------------------- serve() und Signale


def test_serve_closes_service_on_sigterm(tmp_path):
    port = free_port()
    marker = tmp_path / "marker"
    proc = subprocess.Popen([sys.executable, str(FAKE_KERNEL), "--port", str(port), "--via-serve",
                             "--marker", str(marker), "--project", "Signaltest"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        assert wait_for(lambda: port_open(port), 20), "Server kam nicht hoch"
        res = anyio.run(with_client, f"http://127.0.0.1:{port}/mcp", lambda c: c.call_tool("status", {}))
        assert "Projekt Signaltest" in texts(res)[0]
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(15)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert code == 0, proc.stderr.read()
    assert marker.read_text() == "closed"


def test_serve_reports_busy_port(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]

        def boom(*a, **k):
            raise AssertionError("Laufzeit darf bei belegtem Port nicht starten")

        monkeypatch.setattr(server_mod, "create_service", boom)
        assert server_mod.serve("/tmp/unbenutzt.sock", port) == 2


def test_color_and_number_helpers(monkeypatch):
    from kevcad_kernel.mcp_tools import format as fmt
    from kevcad_kernel.mcp_tools.tools import parse_color, resolve_project_path

    monkeypatch.delenv("KEVCAD_PROJECTS_DIR", raising=False)
    assert fmt.num(47434.5, 1) == "47 434,5"
    assert fmt.num(9000.0, 1) == "9000"
    assert fmt.num(-0.0001) == "0"
    assert fmt.num(12.5) == "12,5"
    assert parse_color("#FFFFFF") == [1.0, 1.0, 1.0, 1.0]
    assert parse_color("#000") == [0.0, 0.0, 0.0, 1.0]
    assert parse_color([0.5, 0.25, 0]) == [0.5, 0.25, 0.0, 1.0]
    assert parse_color("rot")[3] == 1.0
    assert resolve_project_path("/abs/Projekt") == "/abs/Projekt"
    assert resolve_project_path("Neu") == os.path.expanduser("~/Documents/Kev CAD/Neu")
    assert resolve_project_path("~/x/Y") == os.path.expanduser("~/x/Y")
