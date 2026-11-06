"""Aufbau-Video mit echtem Kernel und Testvariante der App, immer an einer Kopie (für den Mac mini).

Auf Kevins MacBook rendert die laufende App selbst (``animation(aktion="aufbau")``). Ohne zweiten Monitor gehören
Testfenster nicht auf seinen Bildschirm; dieses Skript fährt dasselbe auf dem Mac mini: Kernel im Prozess samt MCP über
HTTP, die App verbindet sich im Hintergrund (``KEVCAD_KERNEL_EXTERNAL=1``), dann ``view`` für die Darstellung und
``animation(aktion="aufbau", …)`` wie im Gespräch. Videos und Zeitplan landen im Zielordner.

    tools/fern.sh testbau abnahme
    tools/fern/aufbau-video.sh "build/Kev CAD Test abnahme.app" "<Projekt>" wunsch.json [Ziel]

Ohne App (``--nur-lauf``) rechnet es nur model.py und nennt die Befunde der Prüfung.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from messen import KATALOG, MCP_PORT, kopieren  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("projekt", help="Projektordner (wird kopiert, nie verändert)")
    ap.add_argument("--app", default=None, help="Testvariante (Kev CAD Test ….app); ohne: nur rechnen")
    ap.add_argument("--wunsch", default=None, help="JSON mit den Argumenten von animation(aktion=\"aufbau\")")
    ap.add_argument("--darstellung", default="material", help="view(display=…) vor dem Rendern")
    ap.add_argument("--ziel", default="aufbau-ergebnis", help="Ordner für Videos und Zeitplan")
    ap.add_argument("--katalog", default=None)
    args = ap.parse_args()

    projekt = Path(args.projekt).expanduser().resolve()
    arbeit, kopie = kopieren(projekt, Path(args.katalog).expanduser() if args.katalog else KATALOG)
    ziel = Path(args.ziel).expanduser().resolve()
    ziel.mkdir(parents=True, exist_ok=True)
    app_pfad = Path(args.app).resolve() if args.app else None
    name = None
    socket = arbeit / "kernel.sock"
    if app_pfad is not None:
        info = plistlib.loads((app_pfad / "Contents/Info.plist").read_bytes())
        bundle_id, name = info["CFBundleIdentifier"], info.get("CFBundleExecutable") or app_pfad.stem
        if ".test" not in bundle_id:
            raise SystemExit(f"{bundle_id}: nur Testvarianten")
        socket = Path.home() / "Library/Application Support" / bundle_id / "kernel.sock"
        socket.parent.mkdir(parents=True, exist_ok=True)

    import anyio
    from kevcad_kernel.runtime import KernelRuntime
    from kevcad_kernel.server import KevcadHTTPServer
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    rt = KernelRuntime(str(socket), MCP_PORT, auto_run=False, run_timeout_s=900, log=lambda line: None)
    server = None
    ausgang = 1
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        server = KevcadHTTPServer(rt, 0).start_in_thread()

        async def werkzeug(name_: str, **argumente) -> tuple[str, bool]:
            http = create_mcp_http_client(headers={"x-claude-code-session-id": "aufbau-fern"})
            async with http:
                async with Client(streamable_http_client(server.url, http_client=http), mode="legacy", cache=None) as c:
                    r = await c.call_tool(name_, argumente)
            return "\n".join(getattr(b, "text", "") for b in r.content), bool(r.is_error)

        def ruf(name_: str, **argumente) -> tuple[str, bool]:
            return anyio.run(lambda: werkzeug(name_, **argumente))

        if app_pfad is not None:
            log = arbeit / "app.log"
            umgebung = ["--env", "KEVCAD_KERNEL_EXTERNAL=1", "--env", f"KEVCAD_PROJECTS_DIR={arbeit}"]
            subprocess.run(["open", "-g", "-n", *umgebung, "--stderr", str(log), str(app_pfad)], check=True)
            ende = time.monotonic() + 30
            while time.monotonic() < ende:
                conn = rt._link.connection
                if conn is not None and not conn.closed and conn.live.gemeldet:
                    break
                time.sleep(0.1)
            else:
                raise SystemExit("App meldet sich nicht")
        res = rt.project_open(str(kopie))
        if not res.get("ok", True):
            raise SystemExit(f"Projekt nicht offen: {res}")
        text, fehler = ruf("run")
        print(text[:6000], flush=True)
        rt.wait_idle(180)
        if fehler:
            return 1
        befund, _ = ruf("pruefen")
        print("\n--- Prüfung ---\n" + befund[:6000], flush=True)
        if args.wunsch is None or app_pfad is None:
            return 0
        wunsch = json.loads(Path(args.wunsch).read_text(encoding="utf-8"))
        if args.darstellung:
            ruf("view", display=args.darstellung)
        text, fehler = ruf("animation", aktion="aufbau", **wunsch)
        print("\n--- Aufbau-Video ---\n" + text[:8000], flush=True)
        if fehler:
            return 1
        quelle = kopie / "output" / "animationen"
        for f in sorted(quelle.glob("*")):
            shutil.copy2(f, ziel / f.name)
            print(f"→ {ziel / f.name}", flush=True)
        ausgang = 0
    finally:
        if name:
            subprocess.run(["pkill", "-x", name], check=False)
            time.sleep(1)
        if server is not None:
            server.stop()
        rt.close()
        shutil.rmtree(arbeit, ignore_errors=True)
    return ausgang


if __name__ == "__main__":
    raise SystemExit(main())
