"""Claude-Sitzungen für den Spiegel (MIRROR.md, „Sitzungen“): die Brücke reicht CLAUDE_CODE_SESSION_ID im Kopf
weiter, der Kernel führt je Sitzung Tätigkeit und letzten verändernden Aufruf; genau eine Sitzung ist aktiv."""

from __future__ import annotations

import anyio
from fake_service import FakeService
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp_testutil import BRIDGE_EXE, start_server, wait_for

from kevcad_kernel.bridge import BridgeConfig
from kevcad_kernel.mcp_tools.tracking import SessionBoard

A = "aaaaaaaa-0000-4000-8000-00000000000a"
B = "bbbbbbbb-0000-4000-8000-00000000000b"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_board_active_rule():
    pushed: list[list[dict]] = []
    clock = Clock()
    board = SessionBoard(pushed.append, clock=clock, wall=lambda: 1_792_000_000.0 + clock.t)
    board.tool_called(A, mutating=False)
    assert pushed[-1] == [{"session_id": A, "aktiv": False, "seit": pushed[-1][0]["seit"], "taetigkeit": None}]
    board.tool_called(A, mutating=True)
    assert [s["aktiv"] for s in pushed[-1]] == [True]
    assert "zuletzt" in pushed[-1][0]
    clock.t += 5
    t = board.activity_begin(B, "führt model.py aus")
    board.tool_called(B, mutating=True)
    board.activity_end(t)
    snap = pushed[-1]
    assert [(s["session_id"], s["aktiv"]) for s in snap] == [(B, True), (A, False)], "aktive Sitzung vorn"
    assert snap[0]["taetigkeit"] == "führt model.py aus", "Tätigkeit bleibt als zuletzt getan stehen"
    # nur lesende Aufrufe ändern nichts an aktiv
    board.tool_called(A, mutating=False)
    assert pushed[-1][0]["session_id"] == B
    # nach 10 Minuten ohne verändernden Aufruf ist keine Sitzung mehr aktiv
    clock.t += 601
    board.refresh()
    assert [s["aktiv"] for s in pushed[-1]] == [False, False]
    n = len(pushed)
    board.refresh()
    assert len(pushed) == n, "nur Änderungen melden"
    board.set_alive({A})
    assert [s["session_id"] for s in pushed[-1]] == [A]


async def _call(url: str, session: str | None, tool: str, args: dict) -> None:
    http = create_mcp_http_client(headers={"x-claude-code-session-id": session} if session else None)
    async with http:
        async with Client(streamable_http_client(url, http_client=http), mode="legacy", cache=None) as c:
            await c.call_tool(tool, args)


def test_sessions_from_header_via_http():
    server, fake = start_server(FakeService(), grace_s=0.3, poll_s=0.1, idle_s=0.5)
    try:
        url = server.url
        anyio.run(_call, url, A, "status", {})  # nur lesend: dabei, aber nicht aktiv
        assert wait_for(lambda: any(s and s[0]["session_id"] == A for s in fake.sessions), 3), fake.sessions
        assert not any(x["aktiv"] for s in fake.sessions for x in s), "status ist nur lesend"
        anyio.run(_call, url, A, "focus", {"refs": ["Halter/Lasche"]})
        assert wait_for(lambda: any(s and s[0]["aktiv"] and s[0]["session_id"] == A for s in fake.sessions), 3)
        assert any(s and s[0].get("taetigkeit") for s in fake.sessions)
        anyio.run(_call, url, None, "focus", {"refs": ["Halter/Lasche"]})  # ohne Kopf: keine Sitzung
        assert all(x["session_id"] in (A, B) for s in fake.sessions for x in s)
        # Nach dem Ende der Verbindungen fallen die Sitzungen aus der Liste
        assert wait_for(lambda: fake.sessions[-1] == [], 5), fake.sessions[-3:]
    finally:
        server.stop_thread()


def test_bridge_sends_session_header():
    cfg = BridgeConfig.from_env({"CLAUDE_CODE_SESSION_ID": f" {A} "})
    assert cfg.headers == {"x-claude-code-session-id": A}
    assert BridgeConfig.from_env({}).headers == {}

    server, fake = start_server(FakeService())
    try:
        assert BRIDGE_EXE.exists()
        params = StdioServerParameters(command=str(BRIDGE_EXE), args=[], env={
            "KEVCAD_PORT": str(server.port), "KEVCAD_LAUNCH_CMD": "exit 7", "CLAUDE_CODE_SESSION_ID": B})

        async def go() -> None:
            async with Client(params, mode="legacy") as c:
                await c.call_tool("run", {})

        anyio.run(go)
        assert wait_for(lambda: any(s and s[0]["session_id"] == B and s[0]["aktiv"] for s in fake.sessions), 5), \
            fake.sessions
    finally:
        server.stop_thread()
