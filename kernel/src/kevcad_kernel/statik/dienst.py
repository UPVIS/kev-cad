"""Rechenprozess: Statik auf Anfrage der Laufzeit (MCP ``statik`` neu rechnen, ``szenario_rechnen``).

Die Laufzeit schickt einen ``EXEC``-Auftrag mit dem Aufruf ``auftrag(<JSON>)``. Das Ergebnis ist zu groß für den
Rückgabetext von EXEC; es landet als JSON in einer Datei im Temp-Ordner, zurück kommt nur deren Pfad. Die Laufzeit
liest und löscht die Datei (``laufzeit.py``). Gerechnet wird mit dem Modell des letzten geprüften Laufs
(``anbindung.LETZTER``): Körper, Kontakte und Katalog sind schon da, kein neuer Lauf.
"""

from __future__ import annotations

import json
import os
import tempfile
import time


def auftrag(auftrag_json: str) -> str:
    from kevcad_kernel.statik.anbindung import rechne_auftrag

    t0 = time.perf_counter()
    try:
        erg = rechne_auftrag(json.loads(auftrag_json))
    except ValueError as exc:
        erg = {"stand": "failed", "meldung": str(exc)}
    except Exception as exc:  # noqa: BLE001 - als Meldung zurück, nicht als Absturz des Auftrags
        import traceback

        erg = {"stand": "failed", "meldung": f"Statik fehlgeschlagen: {type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc(limit=6)}
    erg["dienst_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    fd, pfad = tempfile.mkstemp(prefix="kevcad-statik-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(erg, f, ensure_ascii=False)
    return pfad


def aufwaermen() -> None:
    """PyNite und scipy laden (beim ersten Import rund 1 s), damit die erste Statik nach einem Lauf schnell ist."""
    try:
        import scipy.sparse.linalg  # noqa: F401
        from Pynite import FEModel3D  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
