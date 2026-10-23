"""Rechenprozess: Auftrag der Topologieoptimierung aus dem Modell des letzten Laufs (EXEC aus der Laufzeit).

Wie ``statik/dienst.py``: Die Laufzeit schickt ``auftrag(<JSON>)``, das Ergebnis (Ordner und Schlüssel) landet als
JSON in einer Datei im Temp-Ordner, zurück kommt nur deren Pfad; die Laufzeit liest und löscht die Datei.
"""

from __future__ import annotations

import json
import os
import tempfile
import time


def auftrag(auftrag_json: str) -> str:
    t0 = time.perf_counter()
    try:
        from kevcad_kernel.statik.anbindung import LETZTER
        from kevcad_kernel.topologie.auftrag import schreibe

        if LETZTER.modell is None:
            raise ValueError("Noch kein Statikmodell: erst run aufrufen (Lager und Lasten kommen aus der Statik).")
        erg = {"stand": "done", "topologie": schreibe(LETZTER, json.loads(auftrag_json))}
    except ValueError as exc:
        erg = {"stand": "failed", "meldung": str(exc)}
    except Exception as exc:  # noqa: BLE001 - als Meldung zurück, nicht als Absturz des Auftrags
        import traceback

        erg = {"stand": "failed", "meldung": f"Topologie fehlgeschlagen: {type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc(limit=6)}
    erg["dienst_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    fd, pfad = tempfile.mkstemp(prefix="kevcad-topo-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(erg, f, ensure_ascii=False)
    return pfad


def auftrag_datei(pfad: str) -> str:
    """Wie ``auftrag``, der Wunsch kommt als Datei (die Form des Ausgangsteils kann groß sein); die Datei wird
    gelöscht."""
    from pathlib import Path

    p = Path(pfad)
    try:
        text = p.read_text(encoding="utf-8")
    finally:
        try:
            p.unlink()
        except OSError:
            pass
    return auftrag(text)
