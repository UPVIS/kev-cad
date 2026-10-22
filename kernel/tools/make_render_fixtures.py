"""Testdateien für Renderings (PROTOCOL.md, Abschnitt „Phase 7: Renderings“): alle Render-Nachrichten beider Richtungen
und render.json mit den erwarteten Werten für die Swift-Seite.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_render_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/render_*.frame und render.json. Eigene Dateien, damit stream.bin
und fixtures.json unverändert bleiben.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import check_render_message, encode_frame, render_beispiele  # noqa: E402

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    erwartet: dict[str, dict] = {}
    for name, head in render_beispiele():
        fehler = check_render_message(head)
        assert not fehler, (name, fehler)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(head))
        erwartet[name] = {k: v for k, v in head.items() if k != "seq"}
    (ZIEL / "render.json").write_text(json.dumps(erwartet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(erwartet)} Rahmen nach {ZIEL}")


if __name__ == "__main__":
    main()
