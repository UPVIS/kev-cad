"""Rücksicht auf den 16-GB-Mac: speicherhungrige Läufe (parallele build123d-Prozesse, große GPU-Läufe) erst starten,
wenn mindestens 25 % Arbeitsspeicher frei sind (Regel vom 21.10.2026, nach dem Einfrieren am 20.10.)."""
from __future__ import annotations

import re
import subprocess
import time


def speicher_frei():
    """Freier Arbeitsspeicher in Prozent laut memory_pressure (None, wenn nicht ermittelbar)."""
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=20).stdout
        m = re.search(r"free percentage:\s*(\d+)%", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def warte_auf_speicher(min_prozent=25, hoechstens_s=900, protokoll=print):
    t0 = time.time()
    while True:
        frei = speicher_frei()
        if frei is None or frei >= min_prozent:
            return frei
        if time.time() - t0 > hoechstens_s:
            raise RuntimeError(f"nur {frei} % Arbeitsspeicher frei, Lauf nicht gestartet")
        if protokoll:
            protokoll(f"warte: nur {frei} % Arbeitsspeicher frei")
        time.sleep(15)
