"""Misst, wie viel die MCP-Schnittstelle von Kev CAD einem Agenten zu lesen gibt (Paket V2-2).

Statisch (ohne Kernel): Anweisungen des Servers, Werkzeugliste (``tools/list`` so, wie sie über die Leitung geht) und
der Skill ``kev-cad``. Mit Projekt zusätzlich typische Antworten an einer Kopie: ``status``, ``run`` kalt, unverändert
und mit Parameteränderung, Teile, Messen, Prüfen, Stückliste. Dafür läuft die echte Laufzeit mit Rechenprozess und
einer App-Attrappe am Socket; der MCP-Server hängt ohne HTTP direkt am Client (gleiche Ergebnisse wie über HTTP).

Aufruf (aus dem Repo, mit der Umgebung des Kernels):

    kernel/.venv/bin/python -u kernel/tools/schnittstelle_messen.py                 # nur statisch
    kernel/.venv/bin/python -u kernel/tools/schnittstelle_messen.py \
        "$HOME/Documents/Kev CAD/Kugelschieber Variante B" --param laufrolle_l=90 --json messung.json

Projekt und Katalog werden wie in ``messen.py`` in einen Temp-Ordner kopiert; Kevins Dateien bleiben unberührt.
Gezählt wird in Zeichen; Tokens grob als Zeichen / 4. „Text“ ist, was das Modell in Claude Code liest (die
Textblöcke des Ergebnisses), „strukturiert“ das Feld ``structuredContent`` (geht mit über die Leitung).
Das Werkzeug erkennt selbst, ob der Server die alten Werkzeugnamen (vor V2-2) oder die neuen hat.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
REPO = HIER.parent.parent
MCP_PORT = 47995  # nur die Zahl in HELLO; nie 47823/47824 (Kevins App)


def tokens(zeichen: int) -> int:
    return round(zeichen / 4)


class Platzhalter:
    """Dienst ohne Kernel: jede Methode gibt None zurück (für die Werkzeugliste reicht das)."""

    def __getattr__(self, name: str) -> Any:
        return lambda *a, **k: None


# ---------------------------------------------------------------------------------------------------------------------
# Statisch


def skill_zeichen(ordner: Path | None = None) -> dict[str, Any]:
    ordner = ordner or REPO / "skill" / "kev-cad"
    dateien = {p.name: len(p.read_text(encoding="utf-8")) for p in sorted(ordner.rglob("*.md"))}
    return {"SKILL.md": dateien.get("SKILL.md", 0), "dateien": dateien, "gesamt": sum(dateien.values())}


async def werkzeugliste(mcp: Any) -> dict[str, Any]:
    from mcp_types import ListToolsResult

    tools = await mcp.list_tools()
    liste = ListToolsResult(tools=tools)
    text = json.dumps(liste.model_dump(by_alias=True, exclude_none=True, mode="json"), ensure_ascii=False,
                      separators=(",", ":"))
    je = sorted(((len(json.dumps(t.model_dump(by_alias=True, exclude_none=True, mode="json"), ensure_ascii=False,
                                 separators=(",", ":"))), t.name) for t in tools), reverse=True)
    return {"anzahl": len(tools), "zeichen": len(text), "namen": sorted(t.name for t in tools),
            "groesste": [{"name": n, "zeichen": z} for z, n in je[:8]]}


def leitung() -> dict[str, Any]:
    """initialize und tools/list roh über HTTP (Antwortkörper in Zeichen), wie sie ein Client bekommt."""
    import urllib.request

    from kevcad_kernel.server import KevcadHTTPServer

    server = KevcadHTTPServer(Platzhalter(), 0).start_in_thread()  # type: ignore[arg-type]

    def post(nachricht: dict, kopf: dict) -> tuple[str, dict]:
        req = urllib.request.Request(server.url, data=json.dumps(nachricht).encode(), method="POST",
                                     headers={"Accept": "application/json, text/event-stream",
                                              "Content-Type": "application/json", **kopf})
        with urllib.request.urlopen(req, timeout=30) as antwort:
            return antwort.read().decode("utf-8"), dict(antwort.headers)

    try:
        init, h = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "schnittstelle-messen", "version": "1"}}}, {})
        sitzung = next((v for k, v in h.items() if k.lower() == "mcp-session-id"), None)
        kopf = {"mcp-protocol-version": "2025-06-18", **({"mcp-session-id": sitzung} if sitzung else {})}
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, kopf)
        liste, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, kopf)
        return {"initialize": len(init), "tools_list": len(liste)}
    finally:
        server.stop_thread()


def statisch(skill: Path | None = None) -> dict[str, Any]:
    import anyio

    from kevcad_kernel.mcp_tools import INSTRUCTIONS
    from kevcad_kernel.server import build_server

    mcp = build_server(Platzhalter())  # type: ignore[arg-type]
    liste = anyio.run(werkzeugliste, mcp)
    try:
        roh = leitung()
    except Exception as exc:  # noqa: BLE001 - Messung ohne HTTP ist trotzdem brauchbar
        roh = {"fehler": f"{type(exc).__name__}: {exc}"}
    return {"anweisungen": len(INSTRUCTIONS), "werkzeugliste": liste, "leitung": roh, "skill": skill_zeichen(skill)}


# ---------------------------------------------------------------------------------------------------------------------
# App-Attrappe mit Kamera (für status)


class App:
    """Minimale App am Socket: sammelt Rahmen, beantwortet VIEW_CMD, Bildanfragen (mit Kameradaten wie die echte App)
    und Vorschaubilder der Versionen."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    KAMERA = {"projection": "perspective", "view": "iso", "position": [1450.0, -1450.0, 1180.0],
              "target": [310.0, 0.0, 180.0], "up": [0.0, 0.0, 1.0], "direction": [-0.6, 0.6, -0.52],
              "distance": 2100.0, "fov_deg": 35.0, "ortho_height_mm": None}

    def __init__(self, pfad: str) -> None:
        from kevcad_kernel.protocol import encode_frame

        self._encode = encode_frame
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(pfad)
        self.frames: list[tuple[float, dict]] = []
        self.cond = threading.Condition()
        self.seq = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._lesen, daemon=True).start()
        self.senden({"type": "HELLO_APP", "app_version": "schnittstelle-messen", "bundle_id": "de.upvis.kevcad.messen"})

    def senden(self, kopf: dict, nutz: bytes = b"") -> None:
        with self._lock:
            self.seq += 1
            self.sock.sendall(self._encode({**kopf, "seq": self.seq}, nutz))

    def _lesen(self) -> None:
        from kevcad_kernel.protocol import FrameReader

        leser = FrameReader()
        while True:
            try:
                data = self.sock.recv(1 << 20)
            except OSError:
                break
            if not data:
                break
            for h, _p in leser.feed(data):
                with self.cond:
                    self.frames.append((time.perf_counter(), h))
                    self.cond.notify_all()
                art = h.get("type")
                if art == "VIEW_CMD":
                    self.senden({"type": "ACK", "reply_to": h["id"], "ok": True})
                elif art in ("SCREENSHOT_REQ", "VERSION_BILD_REQ"):
                    self.senden({"type": "SCREENSHOT_RES", "reply_to": h["id"], "ok": True,
                                 "width": h.get("width", 1), "height": h.get("height", 1),
                                 "camera": dict(self.KAMERA), "mm_per_px": None}, self.PNG)

    def marke(self) -> int:
        with self.cond:
            return len(self.frames)

    def warte(self, pred, timeout: float, start: int = 0) -> dict | None:
        ende = time.monotonic() + timeout
        with self.cond:
            while True:
                for _t, h in self.frames[start:]:
                    if pred(h):
                        return h
                rest = ende - time.monotonic()
                if rest <= 0:
                    return None
                self.cond.wait(min(rest, 0.5))

    def schliessen(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------------------------------
# Antworten


def vermessen(res: Any, dauer_s: float) -> dict[str, Any]:
    """Größen eines CallToolResult: Text (liest das Modell), Bilder, strukturiert, gesamt."""
    text = 0
    bilder = 0
    for block in res.content or []:
        art = getattr(block, "type", None)
        if art == "text":
            text += len(block.text)
        elif art == "image":
            bilder += 1
    struktur = res.structured_content
    s = len(json.dumps(struktur, ensure_ascii=False, separators=(",", ":"))) if struktur is not None else 0
    gesamt = len(json.dumps(res.model_dump(by_alias=True, exclude_none=True, mode="json"), ensure_ascii=False,
                            separators=(",", ":")))
    erster = next((b.text for b in res.content or [] if getattr(b, "type", None) == "text"), "")
    return {"text": text, "tokens": tokens(text), "bilder": bilder, "strukturiert": s, "gesamt": gesamt,
            "fehler": bool(res.is_error), "dauer_s": round(dauer_s, 2), "anfang": erster[:160]}


def szenarien(namen: set[str], param: tuple[str, float], teile: list[str]) -> list[tuple[str, str, dict]]:
    """(Bezeichnung, Werkzeug, Argumente) je Fassung der Schnittstelle."""
    neu = "projekt" in namen  # V2-2
    pname, pwert = param
    a, b = (teile + ["?", "?"])[:2]
    out = [
        ("run kalt", "run", {}),
        ("run unverändert", "run", {}),
        (f"run Parameter {pname}={pwert:g}", "run", {"params": {pname: pwert}}),
        ("status nach den Läufen", "status", {}),
        ("Teile (alle)", "parts", {}),
        ("Messen, ein Teil", "measure", {"refs": [a], "show": False}),
        ("Messen, zwei Teile", "measure", {"refs": [a, b], "show": False}),
        ("Prüfen", "pruefen", {}),
        ("Stückliste", "parts" if neu else "bom", {"stueckliste": True} if neu else {}),
    ]
    if neu:
        out.insert(4, (f"run Parameter {pname}={pwert:g}, detail teile", "run",
                       {"params": {pname: pwert}, "detail": "teile"}))
    return out


async def antworten(rt: Any, app: App, kopie: Path, args: argparse.Namespace) -> list[dict[str, Any]]:
    from mcp import Client

    from kevcad_kernel.server import build_server

    mcp = build_server(rt)
    ergebnisse: list[dict[str, Any]] = []
    pname, _, pwert = args.param.partition("=")
    param = (pname, float(pwert))
    async with Client(mcp, raise_exceptions=True) as client:
        namen = {t.name for t in (await client.list_tools()).tools}
        neu = "projekt" in namen

        async def aufruf(bez: str, werkzeug: str, argumente: dict) -> Any:
            start = app.marke()
            t0 = time.perf_counter()
            res = await client.call_tool(werkzeug, argumente)
            e = {"was": bez, "werkzeug": werkzeug, "argumente": argumente, **vermessen(res, time.perf_counter() - t0)}
            ergebnisse.append(e)
            print(f"{bez}: Text {e['text']} Zeichen (~{e['tokens']} Tokens), strukturiert {e['strukturiert']}, "
                  f"gesamt {e['gesamt']}, {e['dauer_s']} s" + (" [isError]" if e["fehler"] else ""), flush=True)
            if werkzeug == "run":  # Prüfung dieses Laufs abwarten, damit sich die Messungen nicht überlagern
                run = (rt.status().get("last_run") or {}).get("run")
                h = app.warte(lambda h: h.get("type") == "CHECK" and h.get("run") == run
                              and h.get("state") in ("done", "failed"), args.pruef_max_s, start)
                if h is None:
                    print(f"  Prüfung von Lauf {run} nicht fertig nach {args.pruef_max_s} s", flush=True)
                rt.wait_idle(120)
                time.sleep(0.5)
            return res

        if neu:
            await aufruf("status ohne Projekt", "status", {})
            await aufruf("Projekt öffnen", "projekt", {"pfad": str(kopie)})
        else:
            await aufruf("status ohne Projekt", "status", {})
            await aufruf("Projekt öffnen", "project_open", {"path": str(kopie)})
        rt.wait_idle(60)
        teile: list[str] = []
        for bez, werkzeug, argumente in szenarien(namen, param, teile):
            if werkzeug == "measure":
                if not teile:
                    teile.extend(sorted(p["name"] for p in rt.parts())[:2])
                argumente = {**argumente, "refs": teile[:len(argumente["refs"])]}
            await aufruf(bez, werkzeug, argumente)
    return ergebnisse


def dynamisch(args: argparse.Namespace) -> dict[str, Any]:
    import anyio

    sys.path.insert(0, str(HIER))
    from messen import KATALOG, kopieren  # gleiche Kopie wie messen.py (Katalog, Druck-Zwischenspeicher umgelenkt)

    projekt = Path(args.projekt).expanduser().resolve()
    if not (projekt / "model.py").is_file():
        raise SystemExit(f"{projekt}: kein Kev-CAD-Projekt (model.py fehlt)")
    arbeit, kopie = kopieren(projekt, Path(args.katalog).expanduser() if args.katalog else KATALOG)
    from kevcad_kernel.runtime import KernelRuntime

    rt = KernelRuntime(str(arbeit / "k.sock"), MCP_PORT, auto_run=False, run_timeout_s=900,
                       log=(lambda line: None) if not args.log else None)
    app = None
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        app = App(str(arbeit / "k.sock"))
        app.warte(lambda h: h.get("type") == "HELLO", 10)
        ergebnisse = anyio.run(antworten, rt, app, kopie, args)
    finally:
        if app is not None:
            app.schliessen()
        rt.close()
        if not args.behalten:
            shutil.rmtree(arbeit, ignore_errors=True)
        else:
            print(f"Arbeitsordner: {arbeit}")
    return {"projekt": str(projekt), "param": args.param, "antworten": ergebnisse}


# ---------------------------------------------------------------------------------------------------------------------
# Ausgabe


def z(n: int | float) -> str:
    """Ganze Zahl mit Punkt als Tausendertrenner."""
    return f"{int(round(n)):,}".replace(",", ".")


def bericht(st: dict[str, Any], dyn: dict[str, Any] | None) -> str:
    wl = st["werkzeugliste"]
    roh = st.get("leitung") or {}
    zeilen = [
        "| Was | Zeichen | Tokens (≈ Zeichen/4) |",
        "|---|---:|---:|",
        f"| Anweisungen des Servers | {z(st['anweisungen'])} | {z(tokens(st['anweisungen']))} |",
        f"| tools/list ({wl['anzahl']} Werkzeuge, JSON kompakt) | {z(wl['zeichen'])} | {z(tokens(wl['zeichen']))} |",
    ]
    if roh.get("tools_list"):
        zeilen.append(f"| tools/list über HTTP (Antwortkörper) | {z(roh['tools_list'])} | {z(tokens(roh['tools_list']))} |")
        zeilen.append(f"| initialize über HTTP (mit Anweisungen) | {z(roh['initialize'])} | {z(tokens(roh['initialize']))} |")
    zeilen += [
        f"| Skill SKILL.md | {z(st['skill']['SKILL.md'])} | {z(tokens(st['skill']['SKILL.md']))} |",
        f"| Skill gesamt ({len(st['skill']['dateien'])} Dateien) | {z(st['skill']['gesamt'])} | "
        f"{z(tokens(st['skill']['gesamt']))} |",
        "",
        "Größte Werkzeuge (Zeichen): " + ", ".join(f"{g['name']} {z(g['zeichen'])}" for g in wl["groesste"]),
    ]
    if dyn:
        zeilen += ["", "| Antwort | Werkzeug | Text (liest das Modell) | Tokens | strukturiert | gesamt | Dauer |",
                   "|---|---|---:|---:|---:|---:|---:|"]
        for e in dyn["antworten"]:
            zeilen.append(f"| {e['was']} | `{e['werkzeug']}` | {z(e['text'])} | {z(e['tokens'])} | "
                          f"{z(e['strukturiert'])} | {z(e['gesamt'])} | {str(e['dauer_s']).replace('.', ',')} s"
                          + (" (isError)" if e["fehler"] else "") + " |")
    return "\n".join(zeilen)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("projekt", nargs="?", default=None, help="Projektordner (wird kopiert, nie verändert)")
    ap.add_argument("--param", default="laufrolle_l=90", help="Parameteränderung für den dritten Lauf, NAME=WERT")
    ap.add_argument("--katalog", default=None, help="eigener Katalog (Vorgabe: Kevins Katalog, wird kopiert)")
    ap.add_argument("--pruef-max-s", type=float, default=600.0, help="so lange höchstens auf jede Prüfung warten")
    ap.add_argument("--json", default=None, help="Ergebnisse zusätzlich als JSON-Datei")
    ap.add_argument("--skill", default=None, help="Ordner des Skills (Vorgabe: skill/kev-cad dieses Repos)")
    ap.add_argument("--log", action="store_true", help="Meldungen der Laufzeit auf stderr")
    ap.add_argument("--behalten", action="store_true", help="Arbeitsordner nicht löschen")
    args = ap.parse_args(argv)
    os.environ.setdefault("KEVCAD_PROJECTS_DIR", "/tmp/kcschnittstelle-projekte")  # bloße Namen nie zu Kevin
    st = statisch(Path(args.skill).expanduser() if args.skill else None)
    dyn = dynamisch(args) if args.projekt else None
    print()
    print(bericht(st, dyn))
    if args.json:
        Path(args.json).write_text(json.dumps({"statisch": st, "dynamisch": dyn}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
