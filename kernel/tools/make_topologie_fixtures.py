"""Testdateien der Topologieoptimierung (PROTOCOL.md, Abschnitt „Topologie“): TOPO fertig und laufend, TOPO_FIELD
für Dichte, Schutzzonen und das Feld nachher, dazu topo.json mit den erwarteten Werten für den Swift-Decoder.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_topologie_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/topo*.frame und topo.json (eigene Dateien, die übrigen
Testdateien bleiben unverändert).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    check_topo_feld,
    check_topo_message,
    encode_frame,
    pack_topo,
    pack_topo_feld,
    topo_beispiel,
    topo_beispiel_feld,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    erwartet: dict = {}
    for name, stand, seq in (("topo", "done", 91), ("topo_laeuft", "laeuft", 92)):
        head = pack_topo(topo_beispiel(stand), run=12, seq=seq)
        fehler = check_topo_message(head)
        assert not fehler, (name, fehler)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(head))
        erwartet[name] = {"run": head["run"], "stand": head["stand"], "auftrag": head["auftrag"], "teil": head["teil"],
                          "fortschritt": head["fortschritt"], "iteration": head["iteration"],
                          "verlauf": len(head.get("verlauf") or []),
                          "behalten": head["einstellungen"]["behalten"],
                          "ersparnis": ((head.get("kennzahlen") or {}).get("ersparnis") or {}).get("volumen_prozent"),
                          "sicherheit_nachher": ((head.get("kennzahlen") or {}).get("nachher") or {}).get("sicherheit"),
                          "ampel_nachher": ((head.get("kennzahlen") or {}).get("nachher") or {}).get("ampel"),
                          "datei": (head.get("ergebnis") or {}).get("datei"),
                          "zonen": len((head.get("schutz") or {}).get("zonen") or [])}
    for art, seq in (("nachher", 93), ("dichte", 94), ("schutz", 95)):
        kopf, felder = topo_beispiel_feld(art)
        head, payload = pack_topo_feld(kopf, felder, seq=seq)
        fehler = check_topo_feld(head, payload)
        assert not fehler, (art, fehler)
        (ZIEL / f"topo_feld_{art}.frame").write_bytes(encode_frame(head, payload))
        erwartet[f"topo_feld_{art}"] = {"art": art, "punkte": head["punkte"], "dreiecke": head["dreiecke"],
                                        "werte": head["werte"], "auftrag": head["auftrag"], "teil": head["teil"],
                                        "iteration": head.get("iteration"), "bytes": len(payload)}
    (ZIEL / "topo.json").write_text(json.dumps(erwartet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(erwartet)} Testdateien nach {ZIEL}")


if __name__ == "__main__":
    main()
