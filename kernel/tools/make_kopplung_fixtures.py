"""Testdateien für I-6 Live-Kopplung (PROTOCOL.md, Abschnitt „I-6 Live-Kopplung“).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_kopplung_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/ansicht_*.frame, geraete.frame, sprechen_live_*.frame und der
Abschnitt ``kopplung`` in fixtures.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    ANSICHT_APP_NACHRICHTEN, ANSICHT_FLAECHE_FELDER, ANSICHT_JE_S, ANSICHT_KAMERA_FELDER, ANSICHT_MODI, ANSICHT_TEILE,
    ANSICHT_TEILE_VOLL, FAEHIGKEIT_ANSICHT,
    FUEHRUNG_PAUSE_S, SPRECHEN_LIVE_JE_S, ansicht_beispiele, check_ansicht_message, encode_frame,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    frames = []
    for name, header, payload, richtung in ansicht_beispiele():
        probleme = check_ansicht_message(header, payload)
        assert not probleme, (name, probleme)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, payload))
        frames.append({"file": f"{name}.frame", "type": header["type"], "richtung": richtung})
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["kopplung"] = {"frames": frames, "faehigkeit": FAEHIGKEIT_ANSICHT, "modi": list(ANSICHT_MODI),
                        "nachrichten": list(ANSICHT_APP_NACHRICHTEN), "teile": list(ANSICHT_TEILE), "teile_voll": list(ANSICHT_TEILE_VOLL),
                        "flaeche_felder": list(ANSICHT_FLAECHE_FELDER),
                        "kamera_felder": list(ANSICHT_KAMERA_FELDER), "fuehrung_pause_s": FUEHRUNG_PAUSE_S,
                        "ansicht_je_s": ANSICHT_JE_S, "sprechen_live_je_s": SPRECHEN_LIVE_JE_S}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(frames)} Testdateien für I-6 Live-Kopplung nach {ZIEL}")


if __name__ == "__main__":
    main()
