"""Testdateien für I-8 Datei ans Gerät (PROTOCOL.md, Abschnitt „I-8 Datei ans Gerät“).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_datei_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/datei_*.frame und der Abschnitt ``datei`` in fixtures.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    DATEI_STUECK_MAX, DATEI_STUECK_VORGABE, FAEHIGKEIT_DATEI, check_datei_message, datei_beispiele, encode_frame,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    frames = []
    for name, header, payload, richtung in datei_beispiele():
        probleme = check_datei_message(header, payload)
        assert not probleme, (name, probleme)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, payload))
        frames.append({"file": f"{name}.frame", "type": header["type"], "payload_bytes": len(payload),
                       "richtung": richtung})
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["datei"] = {"frames": frames, "faehigkeit": FAEHIGKEIT_DATEI, "stueck_vorgabe": DATEI_STUECK_VORGABE,
                     "stueck_max": DATEI_STUECK_MAX}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(frames)} Testdateien für I-8 Datei ans Gerät nach {ZIEL}")


if __name__ == "__main__":
    main()
