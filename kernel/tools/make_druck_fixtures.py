"""Testdateien für die Druckvorschau (DRUCKVORSCHAU.md): PRINT_PREVIEW (voll, leer, als Antwort), die Anfragen der App
(PRINT_PREVIEW_REQ, PRINT_SETTINGS, PRINT_EXPORT_REQ, auch mit Auswahl ``ohne``) und die Antworten (ACK,
PRINT_EXPORT_RES, auch mit ``weggelassen`` und Objektnamen).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_druck_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/print_*.frame, ack_print_*.frame und der Abschnitt ``druck`` in
fixtures.json (erwartete Werte). Eigene Dateien, damit stream.bin und die Rahmenliste in fixtures.json unverändert
bleiben.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.protocol import (  # noqa: E402
    check_druck_message,
    druckvorschau_beispiel,
    encode_frame,
    pack_print_preview,
    print_export_req,
    print_export_res,
    print_preview_req,
    print_settings,
)

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"
ZIEL_3MF = "/Users/test/Documents/Kev CAD/Kugelschieber/output/Kugelschieber-druck.3mf"


def leere_vorschau(run: int) -> dict:
    """Ohne Druckteile: alles null, Slicer aus."""
    return {"run": run, "stand": "schaetzung", "drucker": "Bambu Lab P1P 0.4",
            "summe": {"platten": 0, "zeit_s": 0, "zeit_mit_wechsel_s": 0, "kosten": 0.0,
                      "kosten_teile": {"filament": 0.0, "strom": 0.0, "risiko": 0.0}, "material": []},
            "platten": [], "teile": [], "hinweise": [],
            "slicer": {"zustand": "aus", "fertig": 0, "gesamt": 0, "meldung": "Keine Druckteile im Modell."},
            "regler": False, "ms": 0.4}


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    voll = druckvorschau_beispiel(run=12)
    frames: list[tuple[str, dict]] = [
        ("print_preview", pack_print_preview(voll, seq=61)),
        ("print_preview_leer", pack_print_preview(leere_vorschau(13), seq=62)),
        ("print_preview_antwort", pack_print_preview({**voll, "slicer": {**voll["slicer"], "zustand": "fertig",
                                                                         "fertig": 4, "meldung": None}},
                                                     reply_to="a-31", seq=63)),
        ("ack_print_settings", {"type": "ACK", "seq": 64, "reply_to": "a-32", "ok": True,
                                "message": "Stangenhalter (Druck): Wände 5, Füllung 30 % (fest)"}),
        ("ack_print_export", {"type": "ACK", "seq": 65, "reply_to": "a-35", "ok": True,
                              "message": "3MF wird geschrieben"}),
        ("print_export_res", print_export_res("a-35", ok=True, pfad=ZIEL_3MF, platten=[1, 2], seq=66,
                                              hinweise=["In Bambu Studio geprüft: 2 Platten, 13 Teile"], ms=1840,
                                              geprueft=True)),
        ("print_export_res_fehler", print_export_res("a-36", ok=False, pfad=None, platten=[], seq=67,
                                                     fehler="Keine Druckteile im Modell.")),
        ("print_export_res_frage", print_export_res(
            "a-39", ok=False, pfad=None, platten=[], seq=79, filament_frage=True,
            fehler="Frag Kevin nach dem Filament, bevor du exportierst (es wurde nichts geschrieben).",
            vorschlaege={"petg": {"zuletzt": "polymaker-polylite-petg-gelb", "spulen": [], "liste": [
                {"id": "polymaker-polylite-petg-gelb", "name": "Polymaker PolyLite PETG gelb (1,75 mm)",
                 "preset": "Polymaker PolyLite PETG gelb (Kev CAD)", "basis": "PolyLite PETG @BBL P1P"}]}})),
        # App → Kernel
        ("print_preview_req", print_preview_req("a-31", seq=71)),
        ("print_settings", print_settings("a-32", gruppe="g1", einstellungen={"waende": 5, "fuellung": 0.3},
                                          seq=72)),
        ("print_settings_zweck", print_settings("a-33", teil="Kugelschieber/Lenksperre (Druck)", zweck="tragend",
                                                seq=73)),
        ("print_settings_zurueck", print_settings("a-34", gruppe="g1", einstellungen={"waende": None},
                                                  zuruecksetzen=False, seq=74)),
        ("print_settings_reset", print_settings("a-37", teil="Kugelschieber/Fangrolle (Druck)", zuruecksetzen=True,
                                                seq=76)),
        ("print_export_req", print_export_req("a-35", platten=[], ziel=ZIEL_3MF, seq=75)),
        # additiv (Strang „Druckexport 2“): Auswahl der Teile, Ergebnis mit weggelassen und Objektnamen
        ("print_export_req_auswahl", print_export_req("a-38", platten=[], ziel=ZIEL_3MF,
                                                      ohne=["Kugelschieber/Lenksperren"],
                                                      filament={"petg": "polymaker-polylite-petg-gelb"}, seq=77)),
        ("print_export_res_auswahl", print_export_res(
            "a-38", ok=True, pfad=ZIEL_3MF, platten=[1], seq=78, ms=1650, geprueft=True,
            hinweise=["Weggelassen: Kugelschieber/Lenksperren/Lenksperre vorn links (Druck) (ohne), "
                      "Kugelschieber/Fangrolle (Druck) (später)."],
            dateien=[{"pfad": ZIEL_3MF, "material": "petg", "filament": "Polymaker PolyLite PETG gelb (Kev CAD)",
                      "platten": [1], "filament_id": "polymaker-polylite-petg-gelb",
                      "filament_basis": "PolyLite PETG @BBL P1P", "abweichungen": [], "filament_quelle": "kevin",
                      "temperaturen": {"duese": 255, "platte": 80, "platte_name": "Textured PEI Plate"},
                      "objekte": ["Kugelschieber/Stangenhalter vorn links (Druck)",
                                  "Kugelschieber/Stangenhalter vorn links (Druck) (2)"]}],
            weggelassen=[{"name": "Kugelschieber/Lenksperren/Lenksperre vorn links (Druck)", "grund": "ohne",
                          "platte": 1, "anzahl": 1},
                         {"name": "Kugelschieber/Fangrolle (Druck)", "grund": "spaeter", "platte": None,
                          "anzahl": 1}],
            leere_platten=[2])),
    ]
    files = []
    for name, header in frames:
        if header["type"] != "ACK":
            fehler = check_druck_message(header)
            assert not fehler, (name, fehler)
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, b""))
        files.append({"file": f"{name}.frame", "type": header["type"], "payload_bytes": 0})

    v = frames[0][1]
    p1 = v["platten"][0]
    t1 = v["teile"][0]
    erwartet = {
        "frames": files,
        "vorschau": {
            "run": v["run"], "stand": v["stand"], "drucker": v["drucker"],
            "summe": {k: v["summe"][k] for k in ("platten", "zeit_s", "zeit_mit_wechsel_s", "kosten")},
            "kosten_teile": v["summe"]["kosten_teile"],
            "material": [{k: m[k] for k in ("material", "g", "m", "kosten", "stand")} for m in v["summe"]["material"]],
            "platten": [{"nr": p["nr"], "zeit_s": p["zeit_s"], "stand": p["stand"], "teile": len(p["teile"]),
                         "auslastung": p["auslastung"], "material": p["material"][0]["material"]}
                        for p in v["platten"]],
            "erstes_plattenteil": {k: p1["teile"][0][k] for k in ("name", "gruppe", "x", "y", "drehung", "umriss")},
            "ersatzteile": [t["name"] for p in v["platten"] for t in p["teile"] if t.get("ersatz")],
            "teile": [{k: t[k] for k in ("gruppe", "name", "anzahl", "material", "zweck", "zweck_geschaetzt", "g",
                                         "zeit_s", "stand", "abweichung")} for t in v["teile"]],
            "erstes_teil": {"einstellungen": t1["einstellungen"], "begruendung": t1["begruendung"],
                            "hinweise": t1["hinweise"], "je_stueck": t1["je_stueck"], "fest": t1["fest"],
                            "fest_von": t1["fest_von"]},
            "fest_von": {t["gruppe"]: t["fest_von"] for t in v["teile"]},
            "hinweise": v["hinweise"],
            "slicer": v["slicer"],
        },
        "leer": {"run": frames[1][1]["run"], "platten": 0, "slicer": frames[1][1]["slicer"]["zustand"]},
        "antwort": {"reply_to": frames[2][1]["reply_to"], "slicer": frames[2][1]["slicer"]["zustand"]},
        "settings": {"gruppe": dict(frames)["print_settings"]["gruppe"],
                     "einstellungen": dict(frames)["print_settings"]["einstellungen"]},
        "export": {"pfad": ZIEL_3MF, "platten": [1, 2]},
        "export_auswahl": {"ohne": ["Kugelschieber/Lenksperren"], "platten": [1], "leere_platten": [2],
                           "weggelassen": 2, "filament": {"petg": "polymaker-polylite-petg-gelb"}},
        "filamente": [{k: f.get(k) for k in ("id", "name", "material", "preset")} for f in v["filamente"]],
        "material_filament_id": {m["material"]: m["filament_id"] for m in v["summe"]["material"]},
    }
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text()) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["druck"] = erwartet
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"{len(files)} Druckvorschau-Testdateien nach {ZIEL}: {v['summe']['platten']} Platten, "
          f"{len(v['teile'])} Gruppen, {v['summe']['kosten']} €")


if __name__ == "__main__":
    main()
