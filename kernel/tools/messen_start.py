"""Misst den Start des Kernels, wie ihn die App erlebt: Prozess starten, verbinden, auf „bereit“ warten, nach 0,35 s ein
leeres Projekt anlegen (OBERFLAECHE.md, Abschnitt 3) und über MCP fragen, bis ``status`` es nennt. Alles auf Temp-Ordnern.

    kernel/.venv/bin/python -u kernel/tools/messen_start.py [--wiederholen 3] [--json datei.json]

Spalten in Sekunden ab dem Start des Prozesses: Socket offen, „bereit“ (STATUS), Projekt offen (PROJECT), MCP antwortet,
``status`` nennt das Projekt, erster Lauf im leeren Projekt fertig (der Auto-Lauf nach dem Öffnen; er wartet auf den
Rechenprozess).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from messen import AppAttrappe  # noqa: E402

APP_WARTET_S = 0.35  # so lange wartet die App nach „bereit“, bevor sie den Entwurf anlegt


def freier_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Mcp:
    """Kleiner MCP-Client über HTTP (Streamable HTTP mit JSON-Antworten)."""

    def __init__(self, port: int) -> None:
        self.url = f"http://127.0.0.1:{port}/mcp"
        self.sitzung: str | None = None
        self.n = 0

    def _post(self, daten: dict) -> dict | None:
        kopf = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sitzung:
            kopf["mcp-session-id"] = self.sitzung
        req = urllib.request.Request(self.url, json.dumps(daten).encode(), kopf)
        with urllib.request.urlopen(req, timeout=30) as r:
            self.sitzung = r.headers.get("mcp-session-id") or self.sitzung
            text = r.read().decode()
        return json.loads(text) if text.strip() else None

    def anmelden(self) -> None:
        self.n += 1
        self._post({"jsonrpc": "2.0", "id": self.n, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "messen", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def werkzeug(self, name: str, argumente: dict | None = None) -> dict:
        self.n += 1
        return self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                           "params": {"name": name, "arguments": argumente or {}}}) or {}


def einmal() -> dict:
    arbeit = Path(tempfile.mkdtemp(prefix="kcstart-", dir="/tmp"))
    sock, port = str(arbeit / "k.sock"), freier_port()
    env = {**os.environ, "KEVCAD_CATALOG_DIR": str(arbeit / "katalog"), "KEVCAD_DRUCKER_SSDP": "0",
           "KEVCAD_DRUCK_CACHE": str(arbeit / "druck"), "KEVCAD_FESTKOERPER_CACHE": str(arbeit / "fk"),
           "KEVCAD_FILAMENTE": str(arbeit / "filamente.json"), "KEVCAD_BAMBU_APP": str(arbeit / "kein.app")}
    (arbeit / "katalog").mkdir()
    t0 = time.perf_counter()
    proc = subprocess.Popen([sys.executable, "-m", "kevcad_kernel.cli", "serve", "--socket", sock, "--port", str(port)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out: dict = {}

    def s() -> float:
        return round(time.perf_counter() - t0, 3)

    app = None
    try:
        while not os.path.exists(sock):
            time.sleep(0.005)
            if time.perf_counter() - t0 > 60:
                raise SystemExit("Socket kommt nicht")
        out["socket"] = s()
        for _ in range(2000):
            try:
                app = AppAttrappe(sock, ["delta-1"])
                break
            except OSError:
                time.sleep(0.005)
        bereit = app.warte(lambda h: h.get("type") == "STATUS" and h.get("state") == "ready", 60)
        if bereit is None:
            raise SystemExit("Kernel wird nicht bereit")
        out["bereit"] = round(bereit[0] - t0, 3)
        out["bereit_text"] = bereit[1].get("message")
        time.sleep(max(0.0, bereit[0] + APP_WARTET_S - time.perf_counter()))
        marke = app.marke()
        app.senden({"type": "PROJECT_NEW", "id": "start", "path": str(arbeit / "Neues Projekt"), "template": "empty"})
        projekt = app.warte(lambda h: h.get("type") == "PROJECT", 30, marke)
        out["projekt"] = round(projekt[0] - t0, 3) if projekt else None
        mcp = Mcp(port)
        while True:
            try:
                mcp.anmelden()
                break
            except OSError:
                time.sleep(0.01)
                if time.perf_counter() - t0 > 60:
                    raise SystemExit("MCP antwortet nicht") from None
        out["mcp"] = s()
        while True:
            antwort = json.dumps(mcp.werkzeug("status"), ensure_ascii=False)
            if "Neues Projekt" in antwort:
                out["status_projekt"] = s()
                break
            if time.perf_counter() - t0 > 60:
                raise SystemExit("status nennt kein Projekt: " + antwort[:400])
            time.sleep(0.01)
        ende = app.warte(lambda h: h.get("type") in ("RUN_END", "RUN_ERROR"), 60)
        out["erster_lauf"] = round(ende[0] - t0, 3) if ende else None
    finally:
        if app is not None:
            app.schliessen()
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(arbeit, ignore_errors=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--wiederholen", type=int, default=3)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    ergebnisse = []
    print("| Socket | bereit | Projekt | MCP | status nennt Projekt | erster Lauf |")
    print("|---|---|---|---|---|---|")
    for _ in range(args.wiederholen):
        e = einmal()
        ergebnisse.append(e)
        print("| " + " | ".join(str(e.get(k)) for k in ("socket", "bereit", "projekt", "mcp", "status_projekt",
                                                        "erster_lauf")) + " |", flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(ergebnisse, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
