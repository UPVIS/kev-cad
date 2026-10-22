"""Eigener Rechenprozess für die Nachberechnung alter Versionen (Kennzahlen und Vorschaubild).

Die Nachberechnung läuft im Leerlauf, kann aber für große Modelle Sekunden dauern. Damit Kevins oder des Agenten
nächster Lauf nie darauf warten muss, rechnet sie in einem zweiten, niedriger priorisierten Prozess (gleiches
Programm wie der Rechenprozess der Laufzeit, ``RUN`` mit ``schatten`` und ohne Prüfung). Er startet bei Bedarf und
endet, wenn die Nachberechnung fertig ist.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from kevcad_kernel.worker import WorkerClient

START_TIMEOUT_S = 240.0


class HintergrundRechner:
    def __init__(self, log=None) -> None:
        self._log = log or (lambda s: None)
        self._lock = threading.Lock()  # ein Auftrag zugleich
        self._fertig = threading.Event()
        self._teile: list[tuple[str, str, dict[str, Any], bytes]] = []
        self._final: dict[str, Any] | None = None
        self._run = 0
        self._worker = WorkerClient(self._nachricht, self._ende, log=self._log)

    def _nachricht(self, gen: int, header: dict[str, Any], payload: bytes) -> None:
        kind = header.get("type")
        if header.get("run") != self._run:
            return
        if kind == "PART":
            app_len = int(header.get("app_len", 0))
            self._teile.append((str(header.get("name")), str(header.get("key", "")), dict(header.get("app") or {}),
                                payload[:app_len]))
        elif kind in ("RUN_DONE", "RUN_FAILED"):
            self._final = header
            self._fertig.set()

    def _ende(self, gen: int, code: int | None) -> None:
        if not self._fertig.is_set():
            self._final = {"type": "CRASH", "code": code}
            self._fertig.set()

    def _bereit(self) -> bool:
        if self._worker.ready:
            return True
        self._worker.start()
        if not self._worker.wait_ready(START_TIMEOUT_S):
            return False
        pid = self._worker.info.get("pid")
        try:
            if pid:
                os.setpriority(os.PRIO_PROCESS, int(pid), 10)  # hinter Kevins Läufen
        except (OSError, ValueError):
            pass
        return True

    def rechne(self, *, run: int, path: str, code: str, inventar_regel: bool, deviation: float, angular: float,
               catalog: dict[str, Any], timeout_s: float = 300.0) -> dict[str, Any]:
        """Wie ``_schatten_job`` der Laufzeit: {"ok", "teile", "bom", "params", "ms"} oder {"ok": False, "error"}."""
        with self._lock:
            t0 = time.perf_counter()
            if not self._bereit():
                return {"ok": False, "error": "Hintergrund-Rechenprozess startet nicht"}
            self._teile = []
            self._final = None
            self._run = run
            self._fertig.clear()
            ok = self._worker.send({"type": "RUN", "run": run, "path": path, "code": code, "params": {}, "slow_ms": 0,
                                    "deviation": deviation, "angular": angular, "catalog": catalog,
                                    "inventar_regel": inventar_regel, "pruefen": False, "schatten": True})
            if not ok or not self._fertig.wait(timeout_s):
                self._worker.kill()
                return {"ok": False, "error": "Zeitlimit überschritten"}
            final = self._final or {}
            ms = int((time.perf_counter() - t0) * 1000)
            if final.get("type") != "RUN_DONE":
                e = final.get("error") or {}
                return {"ok": False, "error": e.get("message") or "Lauf fehlgeschlagen", "line": e.get("line"),
                        "ms": ms}
            reihen = {n: i for i, n in enumerate(final.get("shown") or [])}
            letzte = {t[0]: t for t in self._teile}
            teile = sorted((t for n, t in letzte.items() if n in reihen and not n.startswith("Skizze/")),
                           key=lambda t: reihen[t[0]])
            return {"ok": True, "teile": teile, "bom": final.get("bom"), "params": dict(final.get("params") or {}),
                    "ms": ms}

    def stop(self) -> None:
        self._worker.stop(timeout=1.0)  # ein laufender Auftrag endet dabei mit „abgestürzt“
