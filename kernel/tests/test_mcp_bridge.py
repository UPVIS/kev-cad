"""stdio-Brücke ``kevcad-mcp`` als Unterprozess gegen einen Kernel-Server mit Attrappe (AP6)."""

from __future__ import annotations

import base64
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from fake_service import PNG, noisy_png
from mcp import Client, StdioServerParameters
from mcp_testutil import BRIDGE_EXE, EXPECTED_TOOLS, FAKE_KERNEL, free_port, port_open, start_server, texts, wait_for

from kevcad_kernel.bridge import BridgeConfig

BIG_PNG = noisy_png()


def bridge_params(port: int, **env: str) -> StdioServerParameters:
    assert BRIDGE_EXE.exists(), f"{BRIDGE_EXE} fehlt (uv sync im Ordner kernel ausführen)"
    return StdioServerParameters(command=str(BRIDGE_EXE), args=[],
                                 env={"KEVCAD_PORT": str(port), "KEVCAD_LAUNCH_CMD": "exit 7", **env})


@pytest.fixture
def srv():
    server, fake = start_server()
    yield server, fake
    server.stop_thread()


def test_bridge_forwards_tools_calls_images_and_errors(srv):
    server, fake = srv

    async def direct(c):
        return (await c.list_tools()).tools, await c.call_tool("run", {"params": {"breite": 99}})

    async def via_bridge(c):
        out = {
            "instructions": c.instructions,
            "info": c.server_info,
            "tools": (await c.list_tools()).tools,
            "run": await c.call_tool("run", {"params": {"breite": 99}}),
            "shot": await c.call_tool("screenshot", {"width": 320, "height": 200}),
            "focus": await c.call_tool("focus", {"refs": ["Halter/Lasche"]}),
        }
        out["connected_during"] = list(fake.connected)
        fake.png = BIG_PNG
        out["big"] = await c.call_tool("screenshot", {"width": 1200, "height": 900})
        fake.fail_run = True
        out["fail"] = await c.call_tool("run", {})
        out["invalid"] = await c.call_tool("measure", {"refs": []})
        out["unknown"] = await c.call_tool("gibtsnicht", {})
        return out

    direct_tools, direct_run = anyio.run(lambda: _with(server.url, direct))
    assert wait_for(lambda: fake.connected == [True, False], 5), fake.connected
    fake.connected.clear()
    r = anyio.run(lambda: _with(bridge_params(server.port), via_bridge))

    assert {t.name for t in r["tools"]} == EXPECTED_TOOLS
    dump = lambda tools: sorted((t.model_dump(by_alias=True, exclude_none=True) for t in tools),  # noqa: E731
                                key=lambda d: d["name"])
    assert dump(r["tools"]) == dump(direct_tools)
    assert r["info"].name == "kevcad"
    assert "show(" in r["instructions"]

    run = r["run"]
    assert run.is_error is False
    # gleiche Inhalte wie direkt (bis auf die Laufnummer)
    assert texts(run)[0] == texts(direct_run)[0].replace("Lauf 1", "Lauf 2")
    assert run.structured_content["parts"] == direct_run.structured_content["parts"]

    shot = r["shot"]
    images = [b for b in shot.content if b.type == "image"]
    assert len(images) == 1 and base64.b64decode(images[0].data) == PNG
    assert "320 × 200 px" in texts(shot)[0]

    assert not r["focus"].is_error
    assert fake.calls_of("view_command")[-1][0] == ("focus", {"refs": ["Halter/Lasche"], "animate": True})

    big = [b for b in r["big"].content if b.type == "image"]
    assert len(BIG_PNG) > 2 * 1024 * 1024  # größer als die 1-MiB-Vorgabe des Pakets für SSE-Ereignisse
    assert len(big) == 1 and base64.b64decode(big[0].data) == BIG_PNG

    assert r["fail"].is_error and "Zeile 12" in texts(r["fail"])[0]
    assert r["invalid"].is_error and "Mindestens eine Referenz" in texts(r["invalid"])[0]
    assert r["unknown"].is_error and "Unknown tool" in texts(r["unknown"])[0]

    # Agent in der App: verbunden, solange die Brücke läuft; getrennt, wenn Claude Code sie beendet
    assert r["connected_during"] == [True]
    assert wait_for(lambda: fake.connected == [True, False], 5), fake.connected


async def _with(target, fn):
    async with Client(target, mode="legacy", cache=None) as c:
        return await fn(c)


def _kill_pidfile(pidfile: Path) -> None:
    try:
        os.kill(int(pidfile.read_text()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


def test_bridge_starts_app_and_reconnects(tmp_path):
    port = free_port()
    pidfile = tmp_path / "pid"
    launch = (f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_KERNEL))} --port {port} "
              f"--pidfile {shlex.quote(str(pidfile))} --project Gestartet >/dev/null 2>&1 &")
    counter = tmp_path / "starts"
    launch = f"echo x >> {shlex.quote(str(counter))}; {launch}"
    assert not port_open(port)

    async def go(c):
        out = {"tools": (await c.list_tools()).tools}
        out["first"] = await c.call_tool("status", {})
        first_pid = pidfile.read_text()
        # App fällt weg
        _kill_pidfile(pidfile)
        assert wait_for(lambda: not port_open(port), 5)
        pidfile.unlink()
        out["second"] = await c.call_tool("status", {})
        out["pids"] = (first_pid, pidfile.read_text())
        return out

    try:
        r = anyio.run(lambda: _with(bridge_params(port, KEVCAD_LAUNCH_CMD=launch, KEVCAD_START_TIMEOUT="30"), go))
    finally:
        _kill_pidfile(pidfile)
    assert {t.name for t in r["tools"]} == EXPECTED_TOOLS
    assert not r["first"].is_error, texts(r["first"])
    assert "Projekt Gestartet" in texts(r["first"])[0]
    assert not r["second"].is_error, texts(r["second"])
    assert "Projekt Gestartet" in texts(r["second"])[0]
    assert r["pids"][0] != r["pids"][1]
    assert counter.read_text().count("x") == 2  # einmal beim Start, einmal nach dem Wegfall


def _start_fake_kernel(port: int, pidfile: Path, project: str) -> None:
    subprocess.Popen([sys.executable, str(FAKE_KERNEL), "--port", str(port), "--pidfile", str(pidfile),
                      "--project", project], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait_for(lambda: port_open(port), 15), f"Ersatz-Kernel {project} startet nicht"


def test_bridge_reconnects_after_kernel_restart(tmp_path):
    # Kernel startet zwischen zwei Aufrufen neu (App neu gestartet): Der neue Kernel kennt die alte Sitzung nicht und
    # antwortet mit 404 „Session not found“. Die Brücke muss neu verbinden, ohne die App zu starten.
    port = free_port()
    pidfile = tmp_path / "pid"
    counter = tmp_path / "starts"
    launch = f"echo x >> {shlex.quote(str(counter))}; exit 7"

    async def go(c):
        out = {"first": await c.call_tool("status", {})}
        _kill_pidfile(pidfile)
        assert wait_for(lambda: not port_open(port), 5)
        _start_fake_kernel(port, pidfile, "Zweiter")
        out["second"] = await c.call_tool("status", {})
        return out

    _start_fake_kernel(port, pidfile, "Erster")
    try:
        r = anyio.run(lambda: _with(bridge_params(port, KEVCAD_LAUNCH_CMD=launch, KEVCAD_START_TIMEOUT="10"), go))
    finally:
        _kill_pidfile(pidfile)
    assert not r["first"].is_error and "Projekt Erster" in texts(r["first"])[0]
    assert not r["second"].is_error, texts(r["second"])
    assert "Projekt Zweiter" in texts(r["second"])[0]
    assert not counter.exists()  # App nie gestartet, der Kernel lief ja


def test_bridge_lazy_start_opens_app_on_first_call(tmp_path):
    port = free_port()
    pidfile = tmp_path / "pid"
    counter = tmp_path / "starts"
    launch = (f"echo x >> {shlex.quote(str(counter))}; {shlex.quote(sys.executable)} {shlex.quote(str(FAKE_KERNEL))} "
              f"--port {port} --pidfile {shlex.quote(str(pidfile))} --project Spaet >/dev/null 2>&1 &")

    async def go(c):
        tools = (await c.list_tools()).tools
        await anyio.sleep(0.5)
        started_before_call = counter.exists()
        res = await c.call_tool("status", {})
        return tools, started_before_call, res

    params = bridge_params(port, KEVCAD_LAUNCH_CMD=launch, KEVCAD_LAUNCH_ON_START="0", KEVCAD_START_TIMEOUT="30")
    try:
        tools, started_before_call, res = anyio.run(lambda: _with(params, go))
    finally:
        _kill_pidfile(pidfile)
    assert {t.name for t in tools} == EXPECTED_TOOLS  # eingebaute Liste, ohne die App zu öffnen
    assert started_before_call is False
    assert not res.is_error and "Projekt Spaet" in texts(res)[0]
    assert counter.read_text().count("x") == 1


def test_bridge_reports_unavailable_app():
    port = free_port()

    async def go(c):
        t0 = time.monotonic()
        tools = (await c.list_tools()).tools
        res = await c.call_tool("status", {})
        return tools, res, time.monotonic() - t0

    params = bridge_params(port, KEVCAD_LAUNCH_CMD="echo 'Anwendung nicht gefunden' >&2; exit 1",
                           KEVCAD_START_TIMEOUT="2", KEVCAD_LIST_WAIT="2")
    tools, res, elapsed = anyio.run(lambda: _with(params, go))
    assert {t.name for t in tools} == EXPECTED_TOOLS  # eingebaute Liste
    assert res.is_error
    text = texts(res)[0]
    assert "Kev CAD läuft nicht – bitte starten" in text and "Anwendung nicht gefunden" in text
    assert elapsed < 10


def test_bridge_config_from_env():
    cfg = BridgeConfig.from_env({"KEVCAD_PORT": "50001", "KEVCAD_BUNDLE_ID": "de.upvis.kevcad.test"})
    assert cfg.url == "http://127.0.0.1:50001/mcp"
    assert cfg.launch_argv == ["open", "-g", "-b", "de.upvis.kevcad.test"]
    assert cfg.start_timeout == 45
    default = BridgeConfig.from_env({})
    assert default.port == 47823 and default.bundle_id == "de.upvis.kevcad"
    assert BridgeConfig.from_env({"KEVCAD_LAUNCH_CMD": "true"}).launch_argv == ["/bin/sh", "-c", "true"]
    assert default.launch_on_start is True
    assert BridgeConfig.from_env({"KEVCAD_LAUNCH_ON_START": "0"}).launch_on_start is False


def test_bridge_read_timeout_covers_longest_tool_wait():
    """Die Brücke darf lange Aufrufe nicht vor dem Werkzeug abbrechen (KevCup, freigabe_anfragen mit warten_s 600)."""
    import re

    from kevcad_kernel import bridge
    from kevcad_kernel.mcp_tools import tools

    quellen = Path(tools.__file__).parent.glob("*.py")
    grenzen = [float(m) for q in quellen for m in re.findall(r"(?:warten_s|timeout_s)\b.*?le=(\d+(?:\.\d+)?)", q.read_text())]
    grenzen.append(tools.RUN_TIMEOUT_MAX_S)
    assert grenzen and bridge.LESEZEIT_S > max(grenzen) + 30
