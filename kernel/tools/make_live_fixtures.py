"""Testdateien für V2-5 Live (PROTOCOL.md, Abschnitt „V2-5 Live“): Fähigkeiten, PART_SAME, WIE_ZUVOR, IN_ARBEIT,
Agentenspur, Lagebild, Live-Maße, Versionsbild aus der Szene.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_live_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/live_*.frame und der Abschnitt ``live`` in fixtures.json
(nicht in stream.bin: dort bleiben die Rahmen, auf die sich die App-Tests verlassen).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    KERNEL_FAEHIGKEITEN, LIVE_FELDER, LIVE_NACHRICHTEN, TEIL_INHALTE, WIE_ZUVOR_ARTEN, WIE_ZUVOR_BASEN,
    check_live_message, encode_frame, live_beispiele, netz_bytes, wie_zuvor_aufbauen,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    frames = []
    koepfe: dict[str, dict] = {}
    for name, header, payload, richtung in live_beispiele():
        probleme = check_live_message(header, payload)
        assert not probleme, (name, probleme)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, payload))
        frames.append({"file": f"{name}.frame", "type": header["type"], "payload_bytes": len(payload),
                       "richtung": richtung})
        koepfe[name] = header
    wz = koepfe["live_wie_zuvor"]
    aufgebaut = wie_zuvor_aufbauen(wz, koepfe["live_check_basis"])
    bild = koepfe["live_version_bild_req"]
    live = {
        "frames": frames,
        "kernel_faehigkeiten": list(KERNEL_FAEHIGKEITEN),
        "nachrichten": dict(LIVE_NACHRICHTEN),
        "felder": [{"type": t, "feld": f, "faehigkeit": k} for (t, f), k in LIVE_FELDER.items()],
        "wie_zuvor_arten": list(WIE_ZUVOR_ARTEN),
        "wie_zuvor_basen": WIE_ZUVOR_BASEN,
        "teil_inhalte": TEIL_INHALTE,
        # erwartete Werte für die Tests beider Seiten
        "part_upsert_inhalt": koepfe["live_part_upsert"]["inhalt"],
        "wie_zuvor": {"basis_file": "live_check_basis.frame", "file": "live_wie_zuvor.frame", "ergebnis": aufgebaut},
        "version_bild": {"aus_szene": [k["teil"] for k in bild["teile"] if k.get("aus_szene")],
                         "mit_netz": [k["teil"] for k in bild["teile"] if not k.get("aus_szene")],
                         "payload_bytes": sum(netz_bytes(k) for k in bild["teile"])},
        "spur_ids": [s["id"] for s in koepfe["live_agent_spur"]["schritte"]],
    }
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["live"] = live
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(frames)} Testdateien für V2-5 Live nach {ZIEL}")


if __name__ == "__main__":
    main()
