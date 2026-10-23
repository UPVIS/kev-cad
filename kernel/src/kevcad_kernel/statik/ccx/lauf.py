"""CalculiX als eigenen Prozess starten, Fortschritt mitlesen, bei Kollaps oder Abbruch beenden.

ccx schreibt seine Meldungen zeilenweise (über ein Pseudo-Terminal, sonst puffert es in großen Blöcken). Gelesen
werden der Schritt (``STEP n``), das Inkrement (``increment n attempt m``), die erreichte Zeit (``actual total time``)
und die größte Verschiebungsänderung einer Iteration (``largest increment of disp``). ``stopp`` (Rückruf mit dem
Zustand) entscheidet, ob ccx beendet wird, etwa wenn die Traglast offensichtlich überschritten ist (die
Verschiebungen laufen davon); die bis dahin geschriebenen Ergebnisse bleiben lesbar.
"""

from __future__ import annotations

import os
import pty
import re
import select
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from kevcad_kernel.statik.ccx import installation

R_STEP = re.compile(r"^\s*STEP\s+(\d+)")
R_INC = re.compile(r"increment\s+(\d+)\s+attempt\s+(\d+)")
R_TOTAL = re.compile(r"actual total time=\s*([0-9.eE+-]+)")
R_DISP = re.compile(r"largest increment of disp=\s*([0-9.eE+-]+)")


def rechne(ordner: str | Path, name: str, schritte: int, fortschritt: Callable[[float, str], None] | None = None,
           stopp: Callable[[dict[str, Any]], str | None] | None = None, timeout_s: float = 600.0,
           faeden: int = 4) -> dict[str, Any]:
    """``ccx -i name`` in ``ordner``. Rückgabe: {"code", "ms", "gestoppt" (Grund oder None), "fehler" (Zeilen mit
    *ERROR), "warnungen", "inkremente", "zeit" (erreichte Gesamtzeit), "log" (letzte Zeilen)}."""
    inst = installation.finde()
    if not inst["ok"]:
        raise RuntimeError(inst["meldung"])
    ccx = inst["ccx"]
    t0 = time.perf_counter()
    master, slave = pty.openpty()
    proc = subprocess.Popen([ccx, "-i", name], cwd=str(ordner), stdout=slave, stderr=slave, stdin=subprocess.DEVNULL,
                            env=installation.umgebung(ccx, faeden), start_new_session=True)
    os.close(slave)
    zustand: dict[str, Any] = {"schritt": 0, "inkremente": 0, "zeit": 0.0, "disp_max": 0.0, "iterationen": 0,
                               "schritte": schritte}
    fehler: list[str] = []
    warnungen: list[str] = []
    log: list[str] = []
    gestoppt: str | None = None
    rest = ""
    zuletzt = 0.0

    def beenden() -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass

    try:
        while True:
            if time.perf_counter() - t0 > timeout_s:
                gestoppt = f"Zeitgrenze {timeout_s:g} s"
                beenden()
                break
            r, _, _ = select.select([master], [], [], 0.5)
            if not r:
                if proc.poll() is not None:
                    break
                continue
            try:
                daten = os.read(master, 65536)
            except OSError:
                break
            if not daten:
                break
            rest += daten.decode("latin-1")
            *zeilen, rest = rest.split("\n")
            for z in zeilen:
                z = z.rstrip("\r")
                if not z.strip():
                    continue
                log.append(z)
                del log[:-60]
                if "*ERROR" in z:
                    fehler.append(z.strip())
                elif "*WARNING" in z:
                    if len(warnungen) < 20:
                        warnungen.append(z.strip())
                m = R_STEP.match(z)
                if m:
                    zustand["schritt"] = int(m.group(1))
                    continue
                m = R_INC.search(z)
                if m:
                    zustand["iterationen"] = 0
                    continue
                m = R_DISP.search(z)
                if m:
                    zustand["disp_max"] = max(zustand["disp_max"], float(m.group(1)))
                    zustand["disp_letzt"] = float(m.group(1))
                    zustand["iterationen"] += 1
                    continue
                m = R_TOTAL.search(z)
                if m:
                    zustand["zeit"] = float(m.group(1))
                    zustand["inkremente"] += 1
                    jetzt = time.perf_counter()
                    if fortschritt is not None and jetzt - zuletzt > 0.25:
                        zuletzt = jetzt
                        fortschritt(min(1.0, zustand["zeit"] / max(schritte, 1)),
                                    f"Schritt {zustand['schritt']}, Inkrement {zustand['inkremente']}")
                    if stopp is not None:
                        grund = stopp(zustand)
                        if grund:
                            gestoppt = grund
                            beenden()
                            break
            if gestoppt:
                break
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            beenden()
            proc.wait(timeout=30)
        os.close(master)
    return {"code": proc.returncode, "ms": round((time.perf_counter() - t0) * 1000, 1), "gestoppt": gestoppt,
            "fehler": fehler[:10], "warnungen": warnungen, "inkremente": zustand["inkremente"],
            "zeit": zustand["zeit"], "log": log[-25:]}
