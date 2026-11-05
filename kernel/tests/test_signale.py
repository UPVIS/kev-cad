"""Der Testprozess und der Kernel ignorieren SIGPIPE. Bibliotheken dürfen das nicht still zurücksetzen: Sonst beendet
ein Schreiben auf einen geschlossenen Socket den Prozess ohne Meldung (voller Testlauf mit Ausgang 141, 05.11.2026)."""

from __future__ import annotations

import subprocess
import sys

PROBE = """
import ctypes, signal
from kevcad_kernel.statik.festkoerper.netz import gmsh_starten


class Aktion(ctypes.Structure):
    _fields_ = [("handler", ctypes.c_void_p), ("mask", ctypes.c_uint32), ("flags", ctypes.c_int)]


gmsh_starten()
aktion = Aktion()
ctypes.CDLL(None).sigaction(int(signal.SIGPIPE), None, ctypes.byref(aktion))
print(aktion.handler)
"""


def test_gmsh_laesst_sigpipe_ignoriert():
    # eigener Prozess: gmsh bleibt danach initialisiert, und die Behandlung gilt je Prozess
    res = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().splitlines()[-1] == "1", "gmsh hat SIGPIPE zurückgesetzt (1 = SIG_IGN)"
