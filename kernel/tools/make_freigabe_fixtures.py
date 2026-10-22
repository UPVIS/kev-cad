"""Testdateien für die Freigabe im Projektfenster (Strang „Feinschliff 2“, PROTOCOL.md Abschnitt „Freigabe im
Projektfenster“): FREIGABE_ANFRAGE (Kernel → App) und FREIGABE_GESCHLOSSEN (App → Kernel).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_freigabe_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/freigabe_*.frame und der Abschnitt ``freigabe`` in fixtures.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import check_freigabe_message, encode_frame, freigabe_beispiel  # noqa: E402

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    anfrage, geschlossen = freigabe_beispiel()
    files = []
    for name, header in (("freigabe_anfrage", {**anfrage, "seq": 91}), ("freigabe_geschlossen", geschlossen)):
        assert not check_freigabe_message(header), (name, check_freigabe_message(header))
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, b""))
        files.append({"file": f"{name}.frame", "type": header["type"], "payload_bytes": 0})
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text()) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["freigabe"] = {"frames": files, "anfrage": anfrage, "geschlossen": geschlossen}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"{len(files)} Freigabe-Testdateien nach {ZIEL}")


if __name__ == "__main__":
    main()
