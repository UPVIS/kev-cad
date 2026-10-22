"""Quelle für fotomess aus einer Scan-Referenz: Bilder mit bekannten Kameras (ARKit), Tiefe (PromptDA), Masken.

Die Auswertung legt in ``<referenz>/capture/`` ``kameras.json`` ab (Kameras im Kev-CAD-System des Scans: Boden
z = 0, Mitte x = y = 0). fotomess legt den Scan dann selbst an das Modell (Drehung um Z und Verschiebung über die
Oberfläche), nimmt die Kameras als feste Startwerte, führt sie nur fein nach und passt die Maße zusätzlich an die
gemessene Tiefe an (``fotomess.scan``). Ergebnis ``messung.json["scan"]["lage"]`` legt Netz und Kameras an das Modell.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.referenz.ablage import CAPTURE, ReferenzFehler


def kameras(ref_ordner: Path) -> dict[str, Any]:
    datei = Path(ref_ordner) / CAPTURE / "kameras.json"
    try:
        return json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReferenzFehler(f"Scan nicht ausgewertet ({datei.name} fehlt): erst scan_importieren abwarten") from exc


def bilder_waehlen(eintraege: list[dict[str, Any]], anzahl: int) -> list[dict[str, Any]]:
    """Bis zu ``anzahl`` Bilder mit Tiefe: Fotos zuerst, dann nach Blickrichtung möglichst verschieden (weitester
    Punkt auf der Einheitskugel um das Objekt)."""
    mit = [e for e in eintraege if e.get("tiefe")]
    if len(mit) <= anzahl:
        return mit

    def richtung(e: dict[str, Any]) -> np.ndarray:
        k = e["kamera"]
        C = -np.asarray(k["R"], float).T @ np.asarray(k["t"], float)
        return C / max(np.linalg.norm(C), 1e-9)

    D = np.array([richtung(e) for e in mit])
    fotos = [i for i, e in enumerate(mit) if e.get("art") == "foto"]
    wahl = fotos[:anzahl] if fotos else [0]
    if len(fotos) > anzahl:  # mehr Fotos als gewünscht: auch unter ihnen nach Richtung
        wahl = [fotos[0]]
        kand = fotos
    else:
        kand = list(range(len(mit)))
    mind = np.min([1 - D[kand] @ D[i] for i in wahl], axis=0)
    while len(wahl) < anzahl:
        j = int(np.argmax(mind))
        if mind[j] <= 1e-6:
            break
        wahl.append(kand[j])
        mind = np.minimum(mind, 1 - D[kand] @ D[kand[j]])
    return [mit[i] for i in sorted(set(wahl))]


def quelle(ref_ordner: Path, anzahl: int) -> dict[str, Any]:
    """Teil des fotomess-Auftrags: ``fotos`` (Pfade), ``maske`` "scan", ``scan`` {kameras, netz, namen}."""
    k = kameras(ref_ordner)
    cap = Path(ref_ordner) / CAPTURE
    wahl = bilder_waehlen(k.get("bilder") or [], max(2, int(anzahl)))
    if len(wahl) < 2:
        raise ReferenzFehler("Der Scan hat zu wenige Bilder mit Tiefe für das Vermessen")
    return {"fotos": [str(cap / e["bild"]) for e in wahl], "maske": "scan",
            "scan": {"kameras": str(cap / "kameras.json"), "netz": str(cap / str(k.get("netz") or "netz_mm.obj")),
                     "namen": [e["name"] for e in wahl]}}


def lage_aus_messung(messung: dict[str, Any]) -> dict[str, Any] | None:
    """``meta["lage"]`` (wie bei Object Capture) aus ``messung["scan"]["lage"]``: A, b bilden den Scan auf das
    Modell ab."""
    sl = (messung.get("scan") or {}).get("lage")
    if not sl or "A" not in sl or "b" not in sl:
        return None
    A = np.asarray(sl["A"], float)
    b = np.asarray(sl["b"], float)
    M = np.eye(4)
    M[:3, :3] = A
    M[:3, 3] = b
    return {"A": A.tolist(), "b": b.tolist(), "matrix": [float(x) for x in M.T.reshape(-1)],
            "drehung_z": round(math.degrees(math.atan2(A[1, 0], A[0, 0])), 2),
            "verschiebung": [round(float(x), 2) for x in b], "massstab": 1.0,
            "rest_mm": sl.get("rest_mm"), "paare": int(sl.get("bilder") or 0),
            "fein": {"rest_mm": sl.get("rest_mm"), "anteil": sl.get("anteil")}, "quelle": "scan"}
