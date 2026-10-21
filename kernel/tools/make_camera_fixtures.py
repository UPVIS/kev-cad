"""Erzeugt die Testdateien für Kameras (PROTOCOL.md, „Phase 5: Kameras“), getrennt von make_fixtures.py.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_camera_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/

- camera_upsert.frame, camera_upsert_b.frame, camera_remove.frame, view_cmd_camera.frame, view_cmd_camera_off.frame,
  screenshot_req_camera.frame
- camera_fixtures.json: erwartete Werte (aus der echten Kamera-Rechnung von kevcad.kamera)
"""

from __future__ import annotations

import json
from pathlib import Path

from kevcad import lager
from kevcad_kernel.protocol import encode_frame

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", blende=2.8, fokus=1500,
                       name="FX6")
    fx6.setzen((250, 0, 235), richtung=(1, 0, 0))
    a = {"type": "CAMERA_UPSERT", "seq": 21, "run": 4, **fx6.nachricht()}
    a["teil"] = "Wagen"
    a["ausblenden"] = ["Kamera FX6/Objektiv"]
    b_cam = lager.kamera("sony-fx6", objektiv="sony-fe-24-105-f4-g-oss", format="dci", brennweite=50,
                         fokus="unendlich", name="B")
    b_cam.setzen((-1000, 800, 1200), blick_auf=(1200, 0, 108), roll=5)
    b = {"type": "CAMERA_UPSERT", "seq": 22, "run": 4, **b_cam.nachricht()}
    frames = {
        "camera_upsert": a,
        "camera_upsert_b": b,
        "camera_remove": {"type": "CAMERA_REMOVE", "seq": 23, "run": 5, "name": "Kamera/B"},
        "view_cmd_camera": {"type": "VIEW_CMD", "seq": 24, "id": "k-7", "cmd": "camera_view",
                            "args": {"name": "Kamera/FX6"}},
        "view_cmd_camera_off": {"type": "VIEW_CMD", "seq": 25, "id": "k-8", "cmd": "camera_view", "args": {"name": None}},
        "screenshot_req_camera": {"type": "SCREENSHOT_REQ", "seq": 26, "id": "k-9", "width": 1920, "height": 1080,
                                  "source": "camera", "view": None, "hide_overlays": True, "camera": "Kamera/FX6"},
    }
    for name, header in frames.items():
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header))
    expected = {name: header for name, header in frames.items()}
    (ZIEL / "camera_fixtures.json").write_text(json.dumps(expected, indent=1, ensure_ascii=False))
    print(f"{len(frames)} Kamera-Rahmen nach {ZIEL}")


if __name__ == "__main__":
    main()
