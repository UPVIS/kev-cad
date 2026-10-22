"""Testdateien für den Bauplan (DOKUMENTE.md, Protokoll: BAUPLAN_REQ, BAUPLAN, BAUPLAN_EDIT, BAUPLAN_PRUEFEN, DOCS).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_bauplan_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/bauplan*.frame, docs_bauplan.frame (DOCS mit Bauplan; docs.frame
gehört den Zeichnungen) und der Abschnitt „bauplan“ in fixtures.json (erwartete Werte für die Decoder der App). Eigene Dateien, die übrigen Testdateien bleiben unverändert.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from kevcad_kernel.protocol import (BAUPLAN_LINIEN, bauplan_beispiel, docs_message, encode_frame, pack_bauplan,
                                    unpack_bauplan)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def bilder() -> list[dict]:
    """Zwei Strichbilder im Feld 180 × 120 mm: Grundteil (nur sichtbar) und Deckel (neu, Pfeil)."""
    quadrat = np.array([[40.0, 20.0], [140.0, 20.0], [140.0, 70.0], [40.0, 70.0], [40.0, 20.0]])
    deckel = np.array([[40.0, 80.0], [140.0, 80.0], [140.0, 95.0], [40.0, 95.0], [40.0, 80.0]])
    return [
        {"schritt": "m-1g", "rahmen": [0.0, 0.0, 180.0, 120.0], "massstab": 0.25,
         "linien": {"sichtbar": [quadrat], "duenn": [np.array([[90.0, 20.0], [90.0, 70.0]])]}},
        {"schritt": "m-2", "rahmen": [0.0, 0.0, 180.0, 120.0], "massstab": 0.25,
         "linien": {"sichtbar": [quadrat], "neu": [deckel],
                    "pfeil": [np.array([[90.0, 110.0], [90.0, 97.0]]),
                              np.array([[88.2, 101.0], [90.0, 97.0], [91.8, 101.0]])]}},
    ]


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    plan = bauplan_beispiel()
    header, payload = pack_bauplan(plan, bilder(), run=3, reply_to="a-7", stand=plan["stand"], seq=31)
    (ZIEL / "bauplan.frame").write_bytes(encode_frame(header, payload))
    docs = docs_message(3, [], {"abschnitte": [{"art": a["art"], "titel": a["titel"], "schritte": len(a["schritte"])}
                                               for a in plan["abschnitte"]],
                                "schritte": 5, "probleme": 1, "fehler": 1, "hinweise": 0, "run": 3}, seq=32)
    (ZIEL / "docs_bauplan.frame").write_bytes(encode_frame(docs))
    anfragen = {
        "bauplan_req.frame": {"type": "BAUPLAN_REQ", "seq": 5, "id": "a-7"},
        "bauplan_edit.frame": {"type": "BAUPLAN_EDIT", "seq": 6, "id": "a-8", "von": "kevin",
                               "ops": [{"op": "text", "schritt": "m-2", "titel": "Deckel aufsetzen",
                                        "text": "Deckel auflegen, Schraube von oben eindrehen."},
                                       {"op": "fest", "schritt": "m-2", "wert": True},
                                       {"op": "verschieben", "schritt": "m-2", "nach": "m-1g"},
                                       {"op": "bild", "schritt": "m-2",
                                        "explosion": {"Halter/Deckel": [0.0, 0.0, 40.0]}}]},
        "bauplan_pruefen.frame": {"type": "BAUPLAN_PRUEFEN", "seq": 7, "id": "a-9", "schritt": None},
    }
    for name, h in anfragen.items():
        (ZIEL / name).write_bytes(encode_frame(h))
    zurueck = unpack_bauplan(header, payload)
    erwartet = {
        "linien_reihenfolge": list(BAUPLAN_LINIEN),
        "feld": header["feld"],
        "run": 3,
        "reply_to": "a-7",
        "abschnitte": [a["art"] for a in plan["abschnitte"]],
        "schritte_je_abschnitt": [len(a["schritte"]) for a in plan["abschnitte"]],
        "montage_ids": [s["id"] for s in plan["abschnitte"][4]["schritte"]],
        "befund": {k: plan["abschnitte"][4]["schritte"][1]["pruefung"][0][k] for k in ("id", "art", "schwere",
                                                                                         "schritt")},
        "bilder": [{"schritt": b["schritt"], "linien": b["linien"]} for b in header["bilder"]],
        "erster_pfeil": [[round(float(x), 3) for x in p] for p in zurueck[1]["linien"]["pfeil"][0]],
        "payload_bytes": len(payload),
        "vorher": len(plan["vorher"]),
        "docs": {"schritte": 5, "probleme": 1},
        "frames": ["bauplan.frame", "docs_bauplan.frame", *anfragen],
    }
    fx = ZIEL / "fixtures.json"
    daten = json.loads(fx.read_text()) if fx.exists() else {}
    daten["bauplan"] = erwartet
    fx.write_text(json.dumps(daten, indent=1, ensure_ascii=False))
    print(f"Bauplan-Testdateien nach {ZIEL}: {len(payload)} Byte Nutzlast, {len(header['bilder'])} Bilder")


if __name__ == "__main__":
    main()
