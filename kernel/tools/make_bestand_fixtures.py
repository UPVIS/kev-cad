"""Testdateien für die Bestandsführung (BESTAND.md): BESTAND, BOM mit Zuschnitt aus dem Bestand und Einkaufsliste, ACK
auf GEBAUT_REQ und die Anfragen der App.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_bestand_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/bestand*.frame, bom_bestand.frame, ack_gebaut.frame,
gebaut_req.frame, buchung_rueckgaengig.frame und der Abschnitt ``bestand`` in fixtures.json (erwartete Werte). Eigene
Dateien, damit stream.bin und die Rahmenliste in fixtures.json unverändert bleiben.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bestand_beispiel import BESTAND, BUCHUNGEN, Katalog, basis_bom  # noqa: E402

from kevcad_kernel.bestand.datei import zusammenfassung  # noqa: E402
from kevcad_kernel.bestand.planung import plane  # noqa: E402
from kevcad_kernel.protocol import check_bestand_message, encode_frame, pack_bestand  # noqa: E402

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"
STAND = "2026-10-21T21:45:00"


def bestand_nachricht(seq: int) -> dict:
    buchungen = []
    for b in reversed(BUCHUNGEN):  # neueste zuerst
        buchungen.append({**b, "zusammenfassung": zusammenfassung(b["aenderungen"]), "rueckgaengig_durch": None})
    return pack_bestand(bestand=copy.deepcopy(BESTAND), buchungen=buchungen, stand=STAND,
                        datei="/Users/test/Documents/Kev CAD/Kugelschieber/bestand.json", seq=seq)


def bom_nachricht(seq: int) -> dict:
    planung = plane(basis_bom(run=5), BESTAND, Katalog(), stand=STAND)
    return {"type": "BOM", "seq": seq, **planung.bom}


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[str, dict]] = [
        ("bestand", bestand_nachricht(31)),
        ("bestand_leer", pack_bestand(bestand=None, buchungen=[], stand=None, seq=32)),
        ("bom_bestand", bom_nachricht(33)),
        ("ack_gebaut", {"type": "ACK", "seq": 34, "reply_to": "a-21", "ok": True,
                        "message": "3 Reste weg, 2 ganze Stangen weg, 1 Rest neu (R-0004 244 mm)",
                        "buchung": "B-0003"}),
        # App → Kernel
        ("bestand_req", {"type": "BESTAND_REQ", "seq": 41, "id": "a-20"}),
        ("bestand_save", {"type": "BESTAND_SAVE", "seq": 42, "id": "a-22", "posten_id": "rohr-alfer-12x1",
                          "posten": {"ganze": {"anzahl": 3, "laenge": 1000},
                                     "reste": [{"kennung": "R-0001", "laenge": 430, "ort": "Regal 2",
                                                "seit": "2026-10-21"},
                                               {"laenge": 250, "ort": None}]},
                          "grund": "+1 Stange, Rest 250 mm"}),
        ("bestand_save_einstellungen", {"type": "BESTAND_SAVE", "seq": 43, "id": "a-23",
                                        "einstellungen": {"mindestrest_mm": 80, "saegeblatt_mm": 2.5}, "grund": ""}),
        ("gebaut_req", {"type": "GEBAUT_REQ", "seq": 44, "id": "a-21", "run": 5}),
        ("buchung_rueckgaengig", {"type": "BUCHUNG_RUECKGAENGIG", "seq": 45, "id": "a-24", "buchung": "B-0003"}),
    ]
    files = []
    for name, header in frames:
        if header["type"] != "BOM" and header["type"] != "ACK":
            assert not check_bestand_message(header), (name, check_bestand_message(header))
        data = encode_frame(header, b"")
        (ZIEL / f"{name}.frame").write_bytes(data)
        files.append({"file": f"{name}.frame", "type": header["type"], "payload_bytes": 0})

    bom = frames[2][1]
    rohr = next(c for c in bom["cuts"] if c["stock_id"] == "rohr-alfer-12x1")
    platte = next(c for c in bom["cuts"] if c.get("art") == "platte")
    erwartet = {
        "frames": files,
        "bestand": {
            "posten": sorted(BESTAND["posten"]),
            "reste_rohr": [r["kennung"] for r in BESTAND["posten"]["rohr-alfer-12x1"]["reste"]],
            "buchungen": [b["id"] for b in frames[0][1]["buchungen"]],
            "zusammenfassung_erste": frames[0][1]["buchungen"][0]["zusammenfassung"],
            "stand": STAND,
        },
        "bom": {
            "run": bom["run"],
            "rohr": {"quellen": [{k: q[k] for k in ("art", "kennung", "laenge", "stuecke", "rest_neu", "verschnitt")}
                                 for q in rohr["quellen"]],
                     "neue_reste": rohr["neue_reste"], "aus_bestand": rohr["aus_bestand"], "kaufen": rohr["kaufen"],
                     "stangen": rohr["stangen"]},
            "platte": {"platte": platte["platte"], "quellen": len(platte["quellen"]),
                       "stuecke": sum(len(q["stuecke"]) for q in platte["quellen"]),
                       "erste_quelle": {k: platte["quellen"][0][k] for k in ("art", "kennung", "b", "h")},
                       "erstes_stueck": platte["quellen"][0]["stuecke"][0],
                       "neue_reste": platte["neue_reste"], "kaufen": platte["kaufen"]},
            "einkaufsliste": [{k: e[k] for k in ("id", "menge", "einheit", "preis_je", "preis", "link")}
                              for e in bom["einkaufsliste"]],
            "einkauf_summe": bom["einkauf_summe"],
            "fehlt": bom["fehlt"],
            "bestand_stand": bom["bestand_stand"],
            "stueckgut": [{k: s[k] for k in ("stock_id", "laenge", "anzahl", "aus_bestand", "kaufen")}
                          for s in bom["stueckgut"]],
        },
    }
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text()) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["bestand"] = erwartet
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    lines = [f"{len(files)} Bestand-Testdateien nach {ZIEL}",
             f"Rohr: {rohr['aus_bestand']}, kaufen {rohr['kaufen']}, neue Reste {rohr['neue_reste']}",
             f"Einkauf: {[(e['menge'], e['einheit'], e['benennung']) for e in bom['einkaufsliste']]}, "
             f"Summe {bom['einkauf_summe']}"]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
