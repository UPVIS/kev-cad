"""Erzeugt die Testdateien für Referenzen (PROTOCOL.md, „Phase 4: Referenzen“), getrennt von make_fixtures.py.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_referenz_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/

- ref_list.frame, ref_upsert.frame (Netz mit Nutzlast), ref_remove.frame, ref_photos.frame, ref_result.frame
  (Kernel → App) und ref_add.frame, ref_measure_req.frame, ref_apply.frame (App → Kernel)
- referenz_fixtures.json: die Köpfe zum Vergleich, dazu die Zahl der Punkte und Dreiecke des Netzes
"""

from __future__ import annotations

import json
from pathlib import Path

from kevcad_kernel.protocol import check_ref_message, encode_frame, referenz_beispiele, unpack_ref_netz

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    erwartet = {}
    for name, kopf, nutz in referenz_beispiele():
        fehler = check_ref_message(kopf)
        if fehler:
            raise SystemExit(f"{name}: {fehler}")
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(kopf, nutz))
        erwartet[name] = kopf
        if nutz:
            arr = unpack_ref_netz(kopf, nutz)
            erwartet[name + "_nutzlast"] = {"positions": arr["positions"].round(4).tolist(),
                                            "triangles": arr["triangles"].tolist()}
    (ZIEL / "referenz_fixtures.json").write_text(json.dumps(erwartet, indent=1, ensure_ascii=False))
    print(f"{len(referenz_beispiele())} Referenz-Rahmen nach {ZIEL}")


if __name__ == "__main__":
    main()
