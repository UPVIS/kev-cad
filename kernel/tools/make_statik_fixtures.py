"""Testdateien der Statik (PROTOCOL.md, Abschnitt „Statik“): STATICS voll, als Antwort auf ein Szenario und
fehlgeschlagen, dazu statics.json mit den erwarteten Werten für den Swift-Decoder.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_statik_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/statics*.frame und statics.json. Eigene Dateien, damit stream.bin
und fixtures.json unverändert bleiben.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import check_statics_message, encode_frame, pack_statics, statik_beispiel  # noqa: E402

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
                           "sicherheit": e["kennzahlen"].get("sicherheit"), "ueberhoehung": e["ueberhoehung"]}
                          for e in head["szenarien"]],
            "grenzen": len(head["grenzen"]),
        }
    (ZIEL / "statics.json").write_text(json.dumps(erwartet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(frames)} Rahmen nach {ZIEL}")


if __name__ == "__main__":
    main()
