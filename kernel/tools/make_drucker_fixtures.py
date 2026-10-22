"""Testdateien für Drucken (Phase 8, DRUCKVORSCHAU.md „Drucken (Phase 8)“): PRINTER_STATUS (druckt, leer, ohne
Drucker, als Antwort), PRINT_JOB_RES, PRINT_JOB_ASK und die Anfragen der App (PRINTER_CONFIG, PRINTER_STATUS_REQ,
PRINT_JOB_REQ, PRINT_CONTROL) samt ACK.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_drucker_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/printer_*.frame, print_job_*.frame, print_control*.frame,
ack_printer_*.frame und der Abschnitt ``drucker`` in fixtures.json. Keine echten Zugangsdaten, keine echte
Seriennummer: alles Beispielwerte.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    check_drucker_message,
    drucker_status_beispiel,
    encode_frame,
    print_control,
    print_job_req,
    printer_config,
    printer_status,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"
DATEI = "/Users/test/Documents/Kev CAD/Kugelschieber/output/Kugelschieber-platten.gcode.3mf"


def ohne_drucker() -> dict:
    from kevcad_kernel.drucker.sperre import ANLEITUNG_WEG_B

    return {"konfiguriert": False, "verbindung": "aus",
            "meldung": "Kein Drucker eingestellt (Drucker-Einstellungen). Weg A geht trotzdem.", "drucker": None,
            "weg": "a", "wege": {"a": {"moeglich": True, "grund": None},
                                 "b": {"moeglich": False, "grund": "Keine Verbindung zum Drucker (IP, Seriennummer, "
                                       "Zugangscode und „Status lesen“ nötig).", "anleitung": list(ANLEITUNG_WEG_B)}},
            "steuern": False, "druck": None, "temperaturen": None, "fehler": [], "kamera": False, "gefunden": [],
            "auftrag": None, "aktualisiert": 1792655000.0}


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    druckt = drucker_status_beispiel(druckt=True)
    leer = drucker_status_beispiel(druckt=False)
    leer["auftrag"] = {"auftrag": "j-4", "zustand": "slict", "weg": "a", "platten": [2], "fortschritt": None,
                       "meldung": "Bambu Studio slict die Platten …", "datei": None, "von": "agent"}
    eintrag = {"id": "p1p", "name": "P1P Werkstatt", "modell": "C11", "ip": "192.168.178.40", "weg": "a",
               "status_lesen": True, "schluesselbund": {"dienst": "de.upvis.kevcad.drucker", "konto": "p1p"}}
    frames: list[tuple[str, dict]] = [
        ("printer_status", printer_status(druckt, seq=81)),
        ("printer_status_bereit", printer_status(leer, seq=82)),
        ("printer_status_ohne", printer_status(ohne_drucker(), seq=83)),
        ("printer_status_antwort", printer_status(druckt, reply_to="a-41", seq=84)),
        ("print_job_res", {"type": "PRINT_JOB_RES", "seq": 85, "reply_to": "a-43", "ok": True, "auftrag": "j-3",
                           "weg": "a", "schritt": "geoeffnet", "datei": DATEI, "platten": [1, 2], "fehler": None,
                           "hinweise": ["Platte 2: Teile ragen über die Sperrfläche hinaus"], "ms": 18240,
                           "ergebnis": {"datei": DATEI, "version": "02.07.01.62", "ms": 17900,
                                        "aus_zwischenspeicher": False, "hinweise": [],
                                        "platten": [{"nr": 1, "zeit_s": 22100, "g": 301.2, "m": 99.6,
                                                     "material": "PETG"},
                                                    {"nr": 2, "zeit_s": 5480, "g": 24.6, "m": 8.2,
                                                     "material": "PLA"}]}}),
        ("print_job_res_vorbereitet", {"type": "PRINT_JOB_RES", "seq": 86, "reply_to": "a-42", "ok": True,
                                       "auftrag": "j-3", "weg": "a", "schritt": "vorbereitet",
                                       "datei": "/Users/test/Library/Caches/de.upvis.kevcad/drucker/3f2a/"
                                                "Kugelschieber-platten.gcode.3mf",
                                       "platten": [1, 2], "fehler": None, "hinweise": [], "ms": 17900}),
        ("print_job_res_fehler", {"type": "PRINT_JOB_RES", "seq": 87, "reply_to": "a-44", "ok": False,
                                  "auftrag": "j-5", "weg": "b", "schritt": None, "datei": None, "platten": [1],
                                  "fehler": "Weg A ist eingestellt: Kev CAD steuert den Drucker nicht, das geht nur in "
                                            "Bambu Studio oder Bambu Handy.", "hinweise": [], "ms": 2}),
        ("print_job_ask", {"type": "PRINT_JOB_ASK", "seq": 88, "id": "k-9", "auftrag": "j-6", "platten": [1],
                           "weg": "a", "von": "agent", "grund": "Kevin möchte die Halter jetzt drucken."}),
        ("ack_printer_config", {"type": "ACK", "seq": 89, "reply_to": "a-40", "ok": True,
                                "message": "Drucker P1P Werkstatt eingestellt (Weg A)"}),
        ("ack_print_control_gesperrt", {"type": "ACK", "seq": 90, "reply_to": "a-45", "ok": False,
                                        "message": "Weg A ist eingestellt: Kev CAD steuert den Drucker nicht, das geht "
                                                   "nur in Bambu Studio oder Bambu Handy."}),
        # App → Kernel
        ("printer_config", printer_config("a-40", eintrag, seq=91)),
        ("printer_config_leer", printer_config("a-46", None, seq=92)),
        ("printer_status_req", {"type": "PRINTER_STATUS_REQ", "seq": 93, "id": "a-41"}),
        ("print_job_req", print_job_req("a-42", platten=[], weg="a", bestaetigt=False, seq=94)),
        ("print_job_req_bestaetigt", print_job_req("a-43", platten=[1, 2], weg="a", bestaetigt=True, auftrag="j-3",
                                                   seq=95)),
        ("print_job_req_b", print_job_req("a-44", platten=[1], weg="b", bestaetigt=True,
                                          optionen={"bett_nivellieren": True, "flussrate": True, "zeitraffer": False,
                                                    "spule": "extern"}, seq=96)),
        ("print_control", print_control("a-45", "pause", seq=97)),
        ("print_control_verwerfen", print_control("a-47", "verwerfen", auftrag="j-6", seq=98)),
    ]
    files = []
    for name, header in frames:
        if header["type"] != "ACK":
            fehler = check_drucker_message(header)
            assert not fehler, (name, fehler)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, b""))
        files.append({"file": f"{name}.frame", "type": header["type"], "payload_bytes": 0})

    erwartet = {
        "frames": files,
        "status": {k: druckt[k] for k in ("konfiguriert", "verbindung", "weg", "steuern", "kamera")},
        "drucker": druckt["drucker"],
        "druck": druckt["druck"],
        "temperaturen": druckt["temperaturen"],
        "fehler": druckt["fehler"],
        "wege": {"a": druckt["wege"]["a"]["moeglich"], "b": druckt["wege"]["b"]["moeglich"],
                 "b_grund": druckt["wege"]["b"]["grund"], "anleitung": len(druckt["wege"]["b"]["anleitung"])},
        "gefunden": druckt["gefunden"],
        "auftrag": druckt["auftrag"],
        "bereit": {"zustand": leer["druck"]["zustand"], "auftrag": leer["auftrag"]["zustand"],
                   "von": leer["auftrag"]["von"]},
        "ohne": {"konfiguriert": False, "verbindung": "aus"},
        "job_res": {"auftrag": "j-3", "schritt": "geoeffnet", "datei": DATEI, "platten": [1, 2], "ms": 18240},
        "ask": {"auftrag": "j-6", "platten": [1], "weg": "a", "von": "agent",
                "grund": "Kevin möchte die Halter jetzt drucken."},
        "config": eintrag,
    }
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text()) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["drucker"] = erwartet
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"{len(files)} Drucker-Testdateien nach {ZIEL}")


if __name__ == "__main__":
    main()
