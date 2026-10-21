"""Testdateien für die Nachricht CHECK (Prüfung, PROTOCOL.md Abschnitt „Prüfung“).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_pruef_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/check_done.frame, check_running.frame und check.json (erwartete
Werte). Eigene Dateien, damit die übrigen Testdateien und stream.bin unverändert bleiben.
"""

from __future__ import annotations

import json
from pathlib import Path

from build123d import Box, Pos

from kevcad_kernel.protocol import encode_frame, pack_check, unpack_check
from kevcad_kernel.pruefung.koerper import koerper_aus_form
from kevcad_kernel.pruefung.pruefer import pruefe

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    teile = [koerper_aus_form("Halter/Block A", Box(10, 10, 10)),
             koerper_aus_form("Halter/Block B", Pos(8, 0, 0) * Box(10, 10, 10)),
             koerper_aus_form("Deckel", Pos(0, 0, 10) * Box(10, 10, 10))]
    erg, geo = pruefe(teile, {}, {"pruefungen": ("erklaerungen", "durchdringung")})
    erg["dauer_ms"] = 12.5  # fest, damit die Datei nicht bei jedem Erzeugen anders aussieht
    header, payload = pack_check(run=3, state="done", ergebnis=erg, geometrie=geo, seq=21)
    (ZIEL / "check_done.frame").write_bytes(encode_frame(header, payload))
    laeuft, _ = pack_check(run=4, state="running", seq=22)
    (ZIEL / "check_running.frame").write_bytes(encode_frame(laeuft, b""))
    (g,) = unpack_check(header, payload)
    erwartet = {
        "run": 3,
        "zusammenfassung": header["zusammenfassung"],
        "zaehler": header["zaehler"],
        "befunde": [{k: b[k] for k in ("id", "art", "teile", "schwere", "ort", "geometrie")} for b in header["befunde"]],
        "volumen": header["befunde"][0]["wert"]["volumen"],
        "geometrie": header["geometrie"],
        "payload_bytes": len(payload),
        "erste_position": [round(float(x), 4) for x in g["positions"][0]],
    }
    (ZIEL / "check.json").write_text(json.dumps(erwartet, indent=1, ensure_ascii=False))
    print(f"CHECK-Testdateien nach {ZIEL}: {header['zusammenfassung']}, {len(payload)} Byte Nutzlast")


if __name__ == "__main__":
    main()
