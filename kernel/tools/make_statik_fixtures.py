"""Testdateien der Statik (PROTOCOL.md, Abschnitt „Statik“): STATICS voll, als Antwort auf ein Szenario und
fehlgeschlagen, dazu statics.json mit den erwarteten Werten für den Swift-Decoder.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_statik_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/statics*.frame und statics.json (seit Stufe 2 auch
statics_ablauf.frame mit einem Ablauf, seit Stufe 3 statics_festkoerper.frame mit Festkörper und statics_feld.frame,
eine STATICS_FIELD mit Nutzlast). Eigene Dateien, damit stream.bin und fixtures.json unverändert bleiben.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    check_statics_feld,
    check_statics_message,
    encode_frame,
    pack_statics,
    pack_statics_feld,
    statik_beispiel,
    statik_beispiel_ablauf,
    statik_beispiel_feld,
    statik_beispiel_festkoerper,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    voll = statik_beispiel()
    frames = [
        ("statics", pack_statics(voll, run=7, seq=71)),
        ("statics_eigengewicht", pack_statics(voll, run=7, aktiv="Eigengewicht", reply_to="k-12", zeigen=True,
                                              seq=72)),
        ("statics_failed", pack_statics({"stand": "failed", "meldung": "Noch kein Statikmodell: erst run aufrufen.",
                                         "szenarien": []}, run=8, seq=73)),
        # Stufe 2: Szenario mit Ablauf (MuJoCo), Verlauf und Kontaktpfeilen
        ("statics_ablauf", pack_statics(statik_beispiel_ablauf(), run=9, zeigen=True, seq=74)),
        # Stufe 3: Szenario mit Festkörper (gerechnet) und eines, dessen Festkörper noch läuft
        ("statics_festkoerper", pack_statics(statik_beispiel_festkoerper(), run=11, zeigen=True, seq=75)),
    ]
    erwartet = {}
    for name, head in frames:
        fehler = check_statics_message(head)
        assert not fehler, (name, fehler)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(head))
        erwartet[name] = {
            "run": head["run"], "stand": head["stand"], "aktiv": head["aktiv"], "zeigen": head["zeigen"],
            "szenarien": [{"name": e["name"], "ampel": e["ampel"], "urteile": len(e["urteile"]),
                           "teile": [t["name"] for t in e["teile"]], "staebe": [s["name"] for s in e["staebe"]],
                           "sicherheit": e["kennzahlen"].get("sicherheit"), "ueberhoehung": e["ueberhoehung"],
                           **({"ablauf": {"stand": e["ablauf"]["stand"], "animation": e["ablauf"]["animation"],
                                          "bilder": e["ablauf"]["bilder"],
                                          "kippreserve": e["ablauf"]["kennzahlen"].get("kippreserve"),
                                          "pfeile": [len(b) for b in e["ablauf"]["pfeile"]],
                                          "ladung": [x["name"] for x in e["ablauf"]["kennzahlen"].get("ladung") or []]}}
                              if e.get("ablauf") else {}),
                           **({"festkoerper": {"stand": e["festkoerper"]["stand"],
                                               "fortschritt": e["festkoerper"]["fortschritt"],
                                               "teile": [{k: t.get(k) for k in ("teil", "stand", "ampel", "sicherheit",
                                                                                 "feld", "ausrichtung_beste")}
                                                         for t in e["festkoerper"]["teile"]]}}
                              if e.get("festkoerper") else {})}
                          for e in head["szenarien"]],
            "grenzen": len(head["grenzen"]),
        }
    # Stufe 3: STATICS_FIELD (Oberflächennetz mit Ausnutzung, Spannung, Verschiebung)
    kopf, felder = statik_beispiel_feld()
    head, payload = pack_statics_feld(kopf, felder, run=11, seq=76)
    fehler = check_statics_feld(head, payload)
    assert not fehler, fehler
    (ZIEL / "statics_feld.frame").write_bytes(encode_frame(head, payload))
    erwartet["statics_feld"] = {"run": 11, "szenario": kopf["szenario"], "teil": kopf["teil"], "feld": kopf["feld"],
                                "punkte": head["punkte"], "dreiecke": head["dreiecke"],
                                "ueberhoehung": kopf["ueberhoehung"], "payload_bytes": len(payload),
                                "ausnutzung_max": float(felder["ausnutzung"].max()),
                                "verschiebung_1": [float(c) for c in felder["verschiebung"][1]]}
    (ZIEL / "statics.json").write_text(json.dumps(erwartet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(frames) + 1} Rahmen nach {ZIEL}")


if __name__ == "__main__":
    main()
