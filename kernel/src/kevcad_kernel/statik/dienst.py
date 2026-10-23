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
        a = json.loads(auftrag_json)
        nur_anhang = a.get("szene") is not None or a.get("festkoerper") is not None
        if a.get("simulation"):  # Simulation: simulation.json geändert, alles mit dem letzten Modell neu
            from kevcad_kernel.statik.anbindung import neu_mit_simulation

            erg = neu_mit_simulation()
        elif a.get("grenze"):  # Simulation: „Grenze suchen“ (Last, Neigung) mit S0 und S1
            from kevcad_kernel.simulation.grenze import suche
            from kevcad_kernel.statik.anbindung import LETZTER

            g = a["grenze"]
            erg = {"stand": "done", "grenze": suche(LETZTER, str(g.get("lastfall")), str(g.get("art")),
                                                    set(g["ohne"]) if g.get("ohne") is not None else None,
                                                    set(g["nur"]) if g.get("nur") is not None else None)}
        elif a.get("grenze_fem"):  # Simulation: „Grenze suchen“ mit der FEM, Auftrag für den FEM-Prozess
            from kevcad_kernel.simulation.grenze import fem_auftrag
            from kevcad_kernel.statik.anbindung import LETZTER

            g = a["grenze_fem"]
            erg = {"stand": "done", "festkoerper": fem_auftrag(
                LETZTER, str(g.get("lastfall")), str(g.get("art")), g.get("werte"), g.get("teile"),
                bool(g.get("fein")), bool(g.get("grenze", True)))}
        else:
            erg = rechne_auftrag(a) if (a.get("szenario") or a.get("neu") or not nur_anhang) else {"stand": "done"}
        if a.get("szene") is not None and erg.get("stand") == "done":
            erg.update(szene_schreiben(a["szene"]))
        if a.get("festkoerper") is not None and erg.get("stand") == "done":
            erg.update(festkoerper_schreiben(a["festkoerper"]))
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


def szene_schreiben(auftrag: dict) -> dict:
    """Szene für den Ablauf (S2) aus dem Modell des letzten Laufs als Datei (``statik/dynamik/szene.py``); die
    Laufzeit gibt sie an den Ablauf-Prozess weiter und löscht sie danach."""
    from kevcad_kernel.statik.anbindung import LETZTER
    from kevcad_kernel.statik.dynamik.szene import baue, schreibe

    if LETZTER.modell is None:
        raise ValueError("Noch kein Statikmodell: erst run aufrufen.")
    meta, felder = baue(LETZTER, {**auftrag, "run": LETZTER.run})
    fd, pfad = tempfile.mkstemp(prefix="kevcad-szene-", suffix=".npz")
    os.close(fd)
    schreibe(meta, felder, pfad)
    return {"szene_datei": pfad, "szene_run": LETZTER.run, "szene_ms": meta.get("ms"),
            "szene_koerper": len(meta["koerper"]), "antrieb": meta.get("antrieb")}


def festkoerper_schreiben(wunsch: dict) -> dict:
    """Aufträge für den Festkörper (S3) aus dem Modell des letzten Laufs als Ordner (``statik/festkoerper/auftrag.py``);
    die Laufzeit gibt ihn an den FEM-Prozess weiter und löscht ihn danach."""
    from kevcad_kernel.statik.anbindung import LETZTER
    from kevcad_kernel.statik.festkoerper.auftrag import schreibe

    if LETZTER.modell is None:
        raise ValueError("Noch kein Statikmodell: erst run aufrufen.")
    return {"festkoerper": schreibe(LETZTER, wunsch)}


def aufwaermen() -> None:
    """PyNite und scipy laden (beim ersten Import rund 1 s), damit die erste Statik nach einem Lauf schnell ist."""
    try:
        import scipy.sparse.linalg  # noqa: F401
        from Pynite import FEModel3D  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
