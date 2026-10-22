"""Empfänger für Kev Scan (SCAN.md, „Übertragung iPhone → Mac“): HTTP auf einem freien Port, Bonjour per ``dns-sd``.

- ``GET /`` -> ``{"dienst": "kevscan", "version": 1, "rechner", "projekt"}``
- ``POST /scan`` mit dem ZIP als Körper, ``Content-Length`` (Pflicht, höchstens 4 GB) und ``X-KevScan-Name``
  (URL-kodiert) -> ``{"ok": true, "id", "ordner"}`` bzw. ``{"ok": false, "fehler"}`` (400, 411, 413, 507, 500).
  Der Körper geht in Blöcken auf die Platte, dann sicher entpackt nach ``<scans>/<datum>_<name>/``.
- Bonjour: ``dns-sd -R <Rechnername> _kevscan._tcp local <port> version=1 variante=…`` als Unterprozess. Ein kleiner
  Wächter (``sh``) beendet ``dns-sd``, sobald der Kernel endet (seine stdin schließt), damit kein Dienst ohne
  Empfänger angemeldet bleibt. Testvarianten melden sich als ``_kevscan-test._tcp`` mit eigenem Namen an, das iPhone
  sucht dort nicht.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from kevcad_kernel.scan import ablage

DIENST = "_kevscan._tcp"
DIENST_TEST = "_kevscan-test._tcp"
BLOCK = 1 << 20


def rechnername() -> str:
    try:
        r = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return socket.gethostname().split(".")[0]


class _Handler(BaseHTTPRequestHandler):
    server_version = "KevCAD-Scan/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002 - Signatur von BaseHTTPRequestHandler
        self.server.empfaenger.log("[scan] " + (fmt % args))  # type: ignore[attr-defined]

    def _antwort(self, code: int, daten: dict[str, Any]) -> None:
        roh = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(roh)
        self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        e: Empfaenger = self.server.empfaenger  # type: ignore[attr-defined]
        if self.path.split("?")[0] not in ("/", ""):
            self._antwort(404, {"ok": False, "fehler": "unbekannter Pfad"})
            return
        self._antwort(200, e.info())

    def do_POST(self) -> None:  # noqa: N802
        e: Empfaenger = self.server.empfaenger  # type: ignore[attr-defined]
        if self.path.split("?")[0] != "/scan":
            self._antwort(404, {"ok": False, "fehler": "unbekannter Pfad (POST /scan)"})
            return
        laenge = self.headers.get("Content-Length")
        if laenge is None or "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self._antwort(411, {"ok": False, "fehler": "Content-Length fehlt"})
            return
        try:
            n = int(laenge)
        except ValueError:
            self._antwort(400, {"ok": False, "fehler": "Content-Length ist keine Zahl"})
            return
        if n <= 0:
            self._antwort(400, {"ok": False, "fehler": "leerer Körper"})
            return
        if n > e.max_bytes:
            self._antwort(413, {"ok": False, "fehler": f"Scan zu groß ({n / 1e9:.2f} GB, höchstens "
                                                       f"{e.max_bytes / 1e9:.1f} GB)"})
            return
        name = urllib.parse.unquote(self.headers.get("X-KevScan-Name") or "").strip() or None
        try:
            ergebnis = e.annehmen(self.rfile, n, name)
        except ablage.ScanFehler as exc:
            self._antwort(getattr(exc, "code", 400), {"ok": False, "fehler": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - Antwort an das iPhone statt Abbruch
            e.log(f"[scan] Empfang fehlgeschlagen: {exc!r}")
            self._antwort(500, {"ok": False, "fehler": f"{type(exc).__name__}: {exc}"})
            return
        self._antwort(200, {"ok": True, **ergebnis})


class _Fehler(ablage.ScanFehler):
    def __init__(self, text: str, code: int) -> None:
        super().__init__(text)
        self.code = code


class Empfaenger:
    """HTTP-Empfänger mit Bonjour-Anmeldung. ``projekt()`` liefert den Namen des offenen Projekts oder None,
    ``bei_empfang(eintrag)`` läuft nach jedem angenommenen Scan in einem eigenen Faden."""

    def __init__(self, ordner: Path, *, port: int = 0, host: str = "0.0.0.0", name: str | None = None,
                 dienst: str = DIENST, txt: dict[str, str] | None = None, bonjour: bool = True,
                 projekt: Callable[[], str | None] | None = None,
                 bei_empfang: Callable[[dict[str, Any]], None] | None = None, log: Callable[[str], None] | None = None,
                 max_bytes: int = ablage.MAX_BYTES) -> None:
        self.ordner = Path(ordner)
        self.host = host
        self.wunsch_port = port
        self.name = name or rechnername()
        self.dienst = dienst
        self.txt = {"version": "1", **(txt or {})}
        self.bonjour = bonjour
        self.projekt = projekt or (lambda: None)
        self.bei_empfang = bei_empfang
        self.log = log or (lambda s: None)
        self.max_bytes = max_bytes
        self._server: ThreadingHTTPServer | None = None
        self._dns: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.empfangen = 0

    @property
    def port(self) -> int | None:
        return self._server.server_address[1] if self._server else None

    def info(self) -> dict[str, Any]:
        return {"dienst": "kevscan", "version": 1, "rechner": self.name, "projekt": self.projekt()}

    def start(self) -> None:
        self.ordner.mkdir(parents=True, exist_ok=True)
        srv = ThreadingHTTPServer((self.host, self.wunsch_port), _Handler)
        srv.daemon_threads = True
        srv.empfaenger = self  # type: ignore[attr-defined]
        self._server = srv
        threading.Thread(target=srv.serve_forever, name="kevcad-scan-http", daemon=True).start()
        self.log(f"[scan] Empfänger auf Port {self.port}, Ablage {self.ordner}")
        if self.bonjour:
            self._anmelden()

    def _anmelden(self) -> None:
        if not shutil.which("dns-sd"):
            self.log("[scan] dns-sd fehlt, keine Bonjour-Anmeldung")
            return
        txt = [f"{k}={v}" for k, v in self.txt.items()]
        # Wächter: dns-sd im Hintergrund, endet mit dem Kernel (stdin geschlossen -> read kehrt zurück -> kill)
        skript = 'dns-sd -R "$1" "$2" local "$3" "${@:4}" >/dev/null 2>&1 & p=$!; read _; kill $p 2>/dev/null'
        try:
            self._dns = subprocess.Popen(["/bin/bash", "-c", skript, "kevscan-bonjour", self.name, self.dienst,
                                          str(self.port), *txt], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
            self.log(f"[scan] Bonjour: {self.name!r} als {self.dienst} auf Port {self.port}")
        except OSError as exc:
            self.log(f"[scan] Bonjour-Anmeldung fehlgeschlagen: {exc!r}")

    def stop(self) -> None:
        if self._dns is not None:
            try:
                if self._dns.stdin:
                    self._dns.stdin.close()
                self._dns.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self._dns.kill()
            self._dns = None
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def annehmen(self, quelle, laenge: int, name: str | None) -> dict[str, Any]:
        """Körper (``laenge`` Byte aus ``quelle``) auf die Platte, prüfen, entpacken. Rückgabe {"id", "ordner"}."""
        self.ordner.mkdir(parents=True, exist_ok=True)
        frei = shutil.disk_usage(self.ordner).free
        if frei < 2 * laenge + 512 * 1024 ** 2:
            raise _Fehler(f"Zu wenig Speicherplatz auf dem Mac ({frei / 1e9:.1f} GB frei, gebraucht etwa "
                          f"{2 * laenge / 1e9:.1f} GB)", 507)
        tmp = self.ordner / f".empfang-{time.time_ns()}.zip"
        t0 = time.monotonic()
        try:
            rest = laenge
            with open(tmp, "wb") as f:
                while rest > 0:
                    block = quelle.read(min(BLOCK, rest))
                    if not block:
                        break
                    f.write(block)
                    rest -= len(block)
            if rest > 0:
                raise _Fehler(f"Übertragung abgebrochen ({laenge - rest} von {laenge} Byte)", 400)
            with self._lock:
                ziel = ablage.aufnehmen(tmp, self.ordner, name, quelle="wlan")
        finally:
            tmp.unlink(missing_ok=True)
        self.empfangen += 1
        dauer = time.monotonic() - t0
        eintrag = ablage.eintrag(ziel) or {"id": ziel.name, "ordner": str(ziel)}
        self.log(f"[scan] Scan empfangen: {eintrag.get('name')} ({laenge / 1e6:.1f} MB in {dauer:.1f} s) -> {ziel}")
        if self.bei_empfang is not None:
            threading.Thread(target=self._melden, args=(eintrag,), daemon=True).start()
        return {"id": ziel.name, "ordner": str(ziel)}

    def _melden(self, eintrag: dict[str, Any]) -> None:
        try:
            self.bei_empfang(eintrag)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            self.log(f"[scan] Mitteilung: {exc!r}")
