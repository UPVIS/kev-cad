"""Gedächtnis der Statik (V2-1b): S0 und S1 eines unveränderten Modells nicht noch einmal rechnen.

Der Lauf rechnet die Statik nach jeder Prüfung neu, auch wenn sich nichts geändert hat (Kugelschieber 0,55 s). Hier steht
das Ergebnis von ``anbindung.rechne_gruppen`` je Fingerabdruck der Eingabe:

- alle Statikmodelle mit allen Feldern (ohne die Rechenzeit ``ms``), über ``pickle`` Wert für Wert. Was sich nicht
  serialisieren lässt, bekommt keinen Fingerabdruck und wird gerechnet wie bisher,
- die Szenarien samt der Zuordnung Szenario → Modell,
- der Stand des Katalogs (``Catalog._sig``: Ordner, Dateien, Änderungszeit, Größe; der Katalog lädt genau danach neu),
- je Körper Name, Weltschlüssel (Inhalt der Form samt Netzgenauigkeit), Formschlüssel, Lage, Masse, Volumen und Angaben,
- ``FORMAT``; ändert sich die Rechnung, gilt nichts Altes mehr (zählt ohnehin nur innerhalb eines Rechenprozesses).

Gemerkt wird das ganze Ergebnis samt dem, was ``rechne_alles`` am Modell ändert (Drehfedern an den Anschlüssen, Hinweise);
ein Treffer stellt beides wieder her und liefert eine eigene Kopie. Ergebnisse mit abgefangenen Fehlern (Schnitt, Feder,
Lagersuche, Stabwerk nicht gerechnet) werden nicht gemerkt. Aus mit ``KEVCAD_GEDAECHTNIS=0``, wie das Rechengedächtnis.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import pickle
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

FORMAT = "kc-statik-1"
MAXIMUM = 8  # Modellstände; ein Ergebnis ist rund 2 MB groß
# Spuren abgefangener Fehler im Ergebnis (rechnen.py, feder.py, bewertung.py); solche Ergebnisse gelten nicht als gesichert
FEHLER_SPUREN = (b"nicht gerechnet", b"nicht berechnet", b"Traceback")

_lock = threading.Lock()
_speicher: OrderedDict[bytes, bytes] = OrderedDict()
statistik = {"treffer": 0, "neu": 0, "ohne_schluessel": 0, "nicht_gemerkt": 0}


def an() -> bool:
    return os.environ.get("KEVCAD_GEDAECHTNIS", "1").strip().lower() not in ("0", "aus", "false", "nein", "no")


def leeren() -> None:
    with _lock:
        _speicher.clear()
        statistik.update(treffer=0, neu=0, ohne_schluessel=0, nicht_gemerkt=0)


def _koerper_stand(koerper: dict[str, Any] | None) -> list[tuple]:
    return [(n, k.key, k.form, k.lage.tobytes(), k.masse_g, k.volumen, k.info) for n, k in (koerper or {}).items()]


def _reihen(modelle: dict[str, Any], szen: list[Any], m0: Any) -> list[Any]:
    """Die verschiedenen Modelle, in fester Reihenfolge: das für alle Szenarien, dann die der Szenarien."""
    out = [m0]
    for sz in szen:
        m = modelle.get(sz.name, m0)
        if not any(m is x for x in out):
            out.append(m)
    return out


def fingerabdruck(modelle: dict[str, Any], szen: list[Any], katalog: Any, koerper: dict[str, Any] | None,
                  m0: Any) -> bytes | None:
    """Schlüssel aus allem, was das Ergebnis beeinflusst (Modulbeschreibung); None, wenn etwas nicht erfasst werden kann."""
    sig = getattr(katalog, "_sig", None)
    if katalog is not None and sig is None:
        return None  # Katalog ohne bekannten Stand: lieber rechnen
    reihen = _reihen(modelle, szen, m0)
    zuordnung = [next(i for i, x in enumerate(reihen) if x is modelle.get(sz.name, m0)) for sz in szen]
    try:
        daten = pickle.dumps((FORMAT, [dataclasses.replace(m, ms=0.0) for m in reihen], szen, zuordnung, sig,
                              _koerper_stand(koerper)), protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:  # noqa: BLE001 - was sich nicht serialisieren lässt, hat keinen vollständigen Fingerabdruck
        return None
    return hashlib.blake2b(daten, digest_size=24).digest()


def gemerkt(modelle: dict[str, Any], szen: list[Any], katalog: Any, koerper: dict[str, Any] | None, m0: Any,
            rechnen: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Ergebnis von ``rechnen()`` (``anbindung.rechne_gruppen``) aus dem Gedächtnis oder gerechnet und gemerkt."""
    if not an():
        return rechnen()
    key = fingerabdruck(modelle, szen, katalog, koerper, m0)
    if key is None:
        statistik["ohne_schluessel"] += 1
        return rechnen()
    reihen = _reihen(modelle, szen, m0)
    with _lock:
        blob = _speicher.get(key)
        if blob is not None:
            _speicher.move_to_end(key)
    if blob is not None:
        erg, federn, hinweise = pickle.loads(blob)  # noqa: S301 - selbst geschrieben, nur im Speicher dieses Prozesses
        for m, feder, hinweis in zip(reihen, federn, hinweise):
            for a, f in zip(m.anschluesse, feder):
                a.feder = f
            m.hinweise[:] = hinweis
        statistik["treffer"] += 1
        return erg
    erg = rechnen()
    try:
        blob = pickle.dumps((erg, [[a.feder for a in m.anschluesse] for m in reihen], [list(m.hinweise) for m in reihen]),
                            protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:  # noqa: BLE001 - dann eben nicht merken
        statistik["nicht_gemerkt"] += 1
        return erg
    if any(s in blob for s in FEHLER_SPUREN) or erg.get("stand") not in (None, "done"):
        statistik["nicht_gemerkt"] += 1
        return erg
    with _lock:
        _speicher[key] = blob
        while len(_speicher) > MAXIMUM:
            _speicher.popitem(last=False)
    statistik["neu"] += 1
    return erg
