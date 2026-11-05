"""Testdateien für V2-6 Sprach-Feedback (PROTOCOL.md, Abschnitt „V2-6 Sprach-Feedback“).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_feedback_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/feedback_*.frame, feedback_beispiel.json und der Abschnitt
``feedback`` in fixtures.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    FEEDBACK_FORMAT, FEEDBACK_NACHRICHTEN, FEEDBACK_ZEIGEWOERTER, check_feedback_message, check_feedback_paket,
    encode_frame, feedback_beispiel, feedback_beispiele,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    frames = []
    for name, header, payload, richtung in feedback_beispiele():
        probleme = check_feedback_message(header, payload)
        assert not probleme, (name, probleme)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, payload))
        frames.append({"file": f"{name}.frame", "type": header["type"], "richtung": richtung})
    paket = feedback_beispiel()
    probleme = check_feedback_paket(paket)
    assert not probleme, probleme
    (ZIEL / "feedback_beispiel.json").write_text(json.dumps(paket, indent=1, ensure_ascii=False), encoding="utf-8")
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text()) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["feedback"] = {"frames": frames, "format": FEEDBACK_FORMAT, "nachrichten": list(FEEDBACK_NACHRICHTEN),
                        "zeigewoerter": list(FEEDBACK_ZEIGEWOERTER), "paket": "feedback_beispiel.json"}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"{len(frames)} Testdateien für V2-6 Sprach-Feedback nach {ZIEL}")


if __name__ == "__main__":
    main()
