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
    """Aufruf mit den Namen ab V2-2 (ohne Übersetzung alter Namen)."""
    return anyio.run(lambda: with_client(url, lambda c: c.call_tool(name, args or {}), alt=False))


def neu_client(url: str, fn):
    return anyio.run(lambda: with_client(url, fn, alt=False))


# --------------------------------------------------------------------------------------------------------- Werkzeuge


def test_tool_list_complete_with_schemas(srv):
    server, _ = srv

    async def go(c):
        return (await c.list_tools()).tools, c.instructions, c.server_info

    tools, instructions, info = neu_client(server.url, go)
    by_name = {t.name: t for t in tools}
    assert set(by_name) == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description and len(tool.description) > 20, tool.name
        assert tool.input_schema["type"] == "object", tool.name
        assert tool.title, tool.name
        assert tool.annotations is not None, tool.name
    schema = {n: t.input_schema for n, t in by_name.items()}
    assert schema["projekt"]["required"] == ["pfad"]
    assert "required" not in schema["modell"] and "required" not in schema["measure"]
    assert schema["export"]["required"] == ["formats"]
    assert schema["export"]["properties"]["formats"]["items"]["enum"] == ["step", "stl", "3mf", "glb", "bom_csv",
                                                                      "einkaufsliste_csv", "pdf"]
    assert schema["measure"]["properties"]["show"]["default"] is True
    assert {"top", "front", "iso", "iso_back_left"} <= set(schema["view"]["properties"]["standard"]["enum"])
    assert schema["view"]["properties"]["sichtbarkeit"]["enum"] == ["zeigen", "ausblenden", "isolieren", "alle"]
    assert {"params", "slow_ms", "detail", "titel", "warten_s"} <= set(schema["run"]["properties"])
    assert schema["run"]["properties"]["detail"]["enum"] == ["kurz", "teile", "voll"]
    # veröffentlichte Schemas ohne Ballast: kein title je Feld, optionale Felder ohne null-Alternative
    assert "title" not in schema["run"]["properties"]["titel"]
    assert schema["run"]["properties"]["titel"]["type"] == "string"
    for fach in ("lager", "bestand", "druck", "statik", "topologie", "zeichnung", "bauplan", "referenz", "kamera",
                 "animation", "versionen"):
        assert schema[fach]["required"] == ["aktion"], fach
        assert "hilfe" in schema[fach]["properties"]["aktion"]["enum"], fach
        assert 'aktion="hilfe"' in by_name[fach].description, fach
    assert {"szene", "qualitaet", "auftrag"} <= set(schema["render"]["properties"])  # ohne aktion
    assert by_name["status"].annotations.read_only_hint is True
    assert info.name == "kevcad"
    assert len(instructions) <= 6000
    for needle in ("show(", "step(", "param(", "mm", "katalog", "run(params=", "one run", "select:mcp__kevcad__status",
                   "never send him images", 'lager(aktion="freigabe"'):
        assert needle in instructions, needle


def test_run_returns_compact_summary(srv):
    server, fake = srv
    res = call(server.url, "run", {"params": {"breite": 140}, "slow_ms": 300})
    assert res.is_error is False
    (summary,) = texts(res)  # nur Text, kein JSON-Block mehr
    assert summary.startswith("Lauf 1: 2 Teile (erster Lauf, den du siehst).")
    assert "Parameter: breite=140" in summary and "Baugruppen:" in summary
    assert "- Grundplatte: 1 Teil, 120 × 80 × 5 mm, 128 g" in summary
    assert "Warnung: Lasche: Fläche sehr klein" in summary
    data = res.structured_content
    assert data["ok"] is True and data["run"] == 1 and data["teile"] == 2 and data["kalt"] is True
    assert fake.calls_of("run") == [(({"breite": 140.0}, 300), {})]
    # derselbe Stand noch einmal: nur, dass sich nichts geändert hat
    res = call(server.url, "run", {"params": {"breite": 140}})
    summary = texts(res)[0]
    assert summary.startswith("Lauf 2: 2 Teile, nichts geändert.")
    assert "Baugruppen" not in summary and "Grundplatte" not in summary
    assert "1 bekannte Warnung." in summary
    assert res.structured_content["unveraendert"] == 2


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


def test_ansichten_kevin_returns_png_image(srv):
    server, fake = srv
    res = call(server.url, "ansichten", {"kevin": True, "width": 640, "height": 400})
    assert res.is_error is False
    images = [b for b in res.content if b.type == "image"]
    assert len(images) == 1
    assert images[0].mime_type == "image/png"
    assert base64.b64decode(images[0].data) == PNG
    summary = texts(res)[0]
    assert "640 × 400 px" in summary and "0,125 mm je Pixel" in summary and "Kamera" in summary
    assert res.structured_content["mm_per_px"] == 0.125
    assert fake.calls_of("screenshot") == [((640, 400, "current", None, False), {})]
    call(server.url, "ansichten", {"kevin": True, "overlays": False})
    assert fake.calls_of("screenshot")[-1] == ((1280, 800, "current", None, True), {})


def test_view_combines_commands_in_order(srv):
    server, fake = srv

    async def go(c):
        return [
            await c.call_tool("view", {"standard": "iso", "projection": "orthographic", "fit": True}),
            await c.call_tool("view", {"explode": 0.5, "focus": ["Halter/Lasche#f3"]}),
            await c.call_tool("view", {"sichtbarkeit": "isolieren", "teile": ["Halter/Lasche"]}),
            await c.call_tool("view", {"sichtbarkeit": "alle"}),
            await c.call_tool("view", {"hervorheben": ["Grundplatte#f0"], "farbe": "#FF0000", "beschriftung": "hier"}),
            await c.call_tool("view", {"hervorheben": ["Halter/Lasche"], "dazu": True}),
            await c.call_tool("view", {"schnitt": "y", "schnitt_mm": 12.5}),
            await c.call_tool("view", {"schnitt": "aus"}),
            await c.call_tool("view", {"anmerkung": {"art": "dimension", "punkte": [[0, 0, 0], [0, 0, 42.4]]}}),
            await c.call_tool("view", {"anmerkung": {"art": "label", "punkte": [[1, 2, 3]], "text": "M6", "id": "x1"}}),
            await c.call_tool("view", {"entfernen": ["x1"]}),
            await c.call_tool("view", {"entfernen": True, "standard": "top"}),
            await c.call_tool("view", {"entfernen": "anmerkungen"}),
        ]

    results = neu_client(server.url, go)
    assert all(not r.is_error for r in results), [texts(r) for r in results if r.is_error]
    cmds = [a for a, _ in fake.calls_of("view_command")]
    assert cmds == [
        ("view", {"standard": "iso", "projection": "orthographic", "display": None, "fit": True}),
        ("explode", {"factor": 0.5}),
        ("focus", {"refs": ["Halter/Lasche#f3"], "animate": True}),
        ("visibility", {"mode": "isolate", "refs": ["Halter/Lasche"]}),
        ("visibility", {"mode": "show_all", "refs": []}),
        ("highlight", {"refs": ["Grundplatte#f0"], "color": [1.0, 0.0, 0.0, 1.0], "label": "hier", "clear": True}),
        ("highlight", {"refs": ["Halter/Lasche"], "color": None, "label": None, "clear": False}),
        ("section", {"enabled": True, "offset": 12.5, "axis": "y"}),
        ("section", {"enabled": False, "offset": 0.0, "axis": "z"}),
        ("annotate", {"kind": "dimension", "points": [[0.0, 0.0, 0.0], [0.0, 0.0, 42.4]], "text": "42,4 mm",
                      "id": "agent-1"}),
        ("annotate", {"kind": "label", "points": [[1.0, 2.0, 3.0]], "text": "M6", "id": "x1"}),
        ("clear_annotations", {"ids": ["x1"]}),
        ("highlight", {"refs": [], "color": None, "label": None, "clear": True}),
        ("clear_annotations", {"ids": None}),
        ("view", {"standard": "top", "projection": None, "display": None, "fit": False}),
        ("clear_annotations", {"ids": None}),
    ]
    assert "Kamera auf Halter/Lasche#f3" in texts(results[1])[0] and "Explosion 50 %" in texts(results[1])[0]
    assert len(texts(results[0])) == 1  # kein JSON-Block


def test_invalid_input_is_tool_error(srv):
    server, fake = srv

    async def go(c):
        return [
            await c.call_tool("view", {"focus": []}),
            await c.call_tool("view", {}),
            await c.call_tool("measure", {"refs": ["a", "b", "c"]}),
            await c.call_tool("view", {"anmerkung": {"art": "dimension", "punkte": [[0, 0, 0]]}}),
            await c.call_tool("view", {"hervorheben": ["a"], "farbe": "nichtsfarbe"}),
            await c.call_tool("run", {"slow_ms": -5}),
            await c.call_tool("gibtsnicht", {}),
            await c.call_tool("view", {"sichtbarkeit": "isolieren"}),
            await c.call_tool("view", {"farbe": "rot"}),
            await c.call_tool("run", {"timeout": 400}),
        ]

    results = neu_client(server.url, go)
    assert all(r.is_error for r in results), [texts(r) for r in results]
    assert "Nichts zu tun" in texts(results[0])[0] and "Nichts zu tun" in texts(results[1])[0]
    assert "Höchstens 2" in texts(results[2])[0]
    assert "mindestens 2 Punkte" in texts(results[3])[0]
    assert "Unbekannte Farbe" in texts(results[4])[0]
    assert "sichtbarkeit braucht teile" in texts(results[7])[0]
    assert "farbe und beschriftung gehören zu hervorheben" in texts(results[8])[0]
    assert "timeout" in texts(results[9])[0]  # unbekannte Argumente werden abgelehnt, nicht still verworfen
    assert fake.calls_of("view_command") == [] and fake.calls_of("run") == []


def test_service_errors_become_tool_errors(srv):
    server, fake = srv
    fake.app_connected = False
    fake.raise_in.add("export")

    async def go(c):
        return [
            await c.call_tool("view", {"standard": "top"}),
            await c.call_tool("ansichten", {"kevin": True}),
            await c.call_tool("measure", {"refs": ["Grundplatte#f99"]}),
            await c.call_tool("projekt", {"pfad": "/x/gibtsnicht"}),
            await c.call_tool("execute", {"code": "raise 1/0"}),
            await c.call_tool("export", {"formats": ["step"]}),
        ]

    view, shot, meas, proj, exe, exp = neu_client(server.url, go)
    assert view.is_error and "App nicht verbunden" in texts(view)[0]
    assert shot.is_error and "App nicht verbunden" in texts(shot)[0]
    assert meas.is_error and "Unbekannte Referenz" in texts(meas)[0]
    assert proj.is_error and "Kein Projektordner" in texts(proj)[0]
    assert exe.is_error and "ZeroDivisionError" in texts(exe)[0] and "vorher" in texts(exe)[0]
    assert exp.is_error and "RuntimeError" in texts(exp)[0] and "kaputt" in texts(exp)[0]


def test_core_tools_and_projects(srv, monkeypatch, tmp_path):
    server, fake = srv
    monkeypatch.setenv("KEVCAD_PROJECTS_DIR", str(tmp_path))

    async def go(c):
        return {
            "new": await c.call_tool("projekt", {"pfad": "Wandhalter", "neu": True}),
            "open": await c.call_tool("projekt", {"pfad": "~/Kev/Rohrschelle"}),
            "write": await c.call_tool("modell", {"code": "x = 1\n"}),
            "read": await c.call_tool("modell", {}),
            "parts0": await c.call_tool("parts", {}),
            "run": await c.call_tool("run", {}),
            "parts": await c.call_tool("parts", {}),
            "gruppe": await c.call_tool("parts", {"filter": "Halter"}),
            "status": await c.call_tool("status", {}),
            "auswahl": await c.call_tool("measure", {}),
            "measure": await c.call_tool("measure", {"refs": ["Halter/Lasche#f3", "Grundplatte#f0"]}),
            "execute": await c.call_tool("execute", {"code": "print(platte.volume)"}),
            "export": await c.call_tool("export", {"formats": ["step", "3mf"]}),
            "katalog": await c.call_tool("katalog", {"suche": "40x40x3"}),
        }

    r = neu_client(server.url, go)
    assert all(not v.is_error for v in r.values()), {k: texts(v) for k, v in r.items() if v.is_error}
    assert fake.calls_of("project_new") == [((str(tmp_path / "Wandhalter"), "example"), {})]
    assert fake.calls_of("project_open") == [((os.path.expanduser("~/Kev/Rohrschelle"),), {})]
    assert "x = 1" in texts(r["read"])[0]
    assert r["read"].structured_content["code"] == "x = 1\n"
    assert "Keine Teile" in texts(r["parts0"])[0]
    assert "- Halter/Lasche: 40 × 5 × 50 mm, 24,3 g, aluminium, Mitte (0; 0; 30)" in texts(r["parts"])[0]
    gruppe = texts(r["gruppe"])[0]
    assert gruppe.startswith("1 Teil unter „Halter“:") and "von (-20; -2,5; 5) bis (20; 2,5; 55)" in gruppe
    status = texts(r["status"])[0]
    assert "Projekt Rohrschelle" in status and "Letzter Lauf 1: ok, 2 Teile" in status
    assert "Halter/Lasche#f3: Ebene, 200,000 mm²" in status  # Auswahl mit Werten
    assert "Ansicht:" in status and "Sichtbar: alle 2 Teile" in status
    sel = texts(r["auswahl"])[0]
    assert "2 Elemente" in sel and "Ebene, 200,000 mm²" in sel
    meas = texts(r["measure"])[0]
    assert "Abstand 12,500 mm" in meas and "Punkte: (0; 0; 5) ↔ (0; 0; 17,5)" in meas
    assert fake.calls_of("measure")[-1] == ((["Halter/Lasche#f3", "Grundplatte#f0"], True), {})
    assert "Ausgabe:\n47434.5" in texts(r["execute"])[0] and "Ergebnis: 8" in texts(r["execute"])[0]
    assert r["export"].structured_content["dateien"]["files"][0].endswith(".step")
    assert fake.calls_of("export") == [((["step", "3mf"], None), {})]
    assert "vierkantrohr-en10219-40x40x3" in texts(r["katalog"])[0]
    assert all(len(texts(v)) == 1 for v in r.values())  # nirgends ein JSON-Block


def test_fachwerkzeug_aktion_hilfe_und_fehler(srv):
    server, fake = srv

    async def go(c):
        await c.call_tool("run", {})
        return {
            "pruefung": await c.call_tool("druck", {"aktion": "pruefung"}),
            "daten": await c.call_tool("druck", {"aktion": "pruefung", "daten": True}),
            "hilfe": await c.call_tool("druck", {"aktion": "hilfe", "zu": "export"}),
            "unbekannt": await c.call_tool("druck", {"aktion": "gibtsnicht"}),
            "falsch": await c.call_tool("druck", {"aktion": "export", "falsch": 1}),
            "fehlt": await c.call_tool("lager", {"aktion": "freigabe"}),
            "variante": await c.call_tool("versionen", {"aktion": "variante_anlegen", "name": "Leicht"}),
            "fest": await c.call_tool("versionen", {"aktion": "variante_anlegen", "aktion2": 1}),
            "render": await c.call_tool("render", {"szene": "studio"}),
        }

    r = neu_client(server.url, go)
    assert not r["pruefung"].is_error and len(texts(r["pruefung"])) == 1
    assert len(texts(r["daten"])) == 2 and texts(r["daten"])[1].startswith("{")  # daten=true: JSON-Block dazu
    hilfe = texts(r["hilfe"])[0]
    assert hilfe.startswith('druck(aktion="export", ziel?, platten?, teile?, ohne?, filament?)')
    assert "ALWAYS ASK KEVIN WHICH FILAMENT" in hilfe and "  filament:" in hilfe
    assert r["unbekannt"].is_error and "Vorhanden: pruefung, vorschau" in texts(r["unbekannt"])[0]
    assert r["falsch"].is_error and "falsch: gibt es nicht" in texts(r["falsch"])[0]
    assert "Parameter: ziel?, platten?, teile?, ohne?, filament?" in texts(r["falsch"])[0]
    assert r["fehlt"].is_error and "ids: fehlt" in texts(r["fehlt"])[0]
    assert not r["variante"].is_error and fake.calls_of("variante")[0][0][:2] == ("anlegen", "Leicht")
    assert r["fest"].is_error
    assert not r["render"].is_error and "Rendering R-1" in texts(r["render"])[0]


# ------------------------------------------------------------------------------------------------- Anzeige in der App


def test_activity_is_set_and_cleared(srv):
    server, fake = srv
    call(server.url, "run")
    call(server.url, "measure", {"refs": ["Halter/Lasche#f3", "Grundplatte#f0"]})
    call(server.url, "ansichten", {"kevin": True})
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
