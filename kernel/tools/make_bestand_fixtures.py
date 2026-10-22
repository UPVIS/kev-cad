"""Testdateien für die Bestandsführung (BESTAND.md): BESTAND, BOM mit Zuschnitt aus dem Bestand und Einkaufsliste, ACK
auf GEBAUT_REQ und die Anfragen der App.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_bestand_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/bestand*.frame, bom_bestand.frame, ack_gebaut.frame,
gebaut_req.frame, buchung_rueckgaengig.frame und der Abschnitt ``bestand`` in fixtures.json (erwartete Werte). Eigene
Dateien, damit stream.bin und die Rahmenliste in fixtures.json unverändert bleiben.

Strang „Material im Kernel angleichen“ (22.10.2026): bom_material.frame (Kugelschieber mit Resten, Normteilen,
Zukaufteilen, Kamerazubehör und Druckteilen, geplant mit Bestand), print_material.frame (Druckvorschau desselben Laufs)
und der Abschnitt ``material``: Einkaufsliste als Text und CSV genau so, wie der Kernel sie über MCP und Export liefert,
mit und ohne Druckvorschau, Summen und Verschnitt (Definition 2). Der Swift-Test ``MaterialKernelGleichTests`` rechnet
dieselben Werte mit ``MaterialDaten`` und vergleicht byteweise. Seit Strang „Bestand Stufe 2“ führt das Beispiel
Filament (PETG-Spule mit 120 g, zu wenig: eine Spule kaufen; PLA-Spule mit 310 g reicht), Felder ``filament_bestand``
und ``filament_kauf``.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bestand_beispiel import (  # noqa: E402
    BESTAND,
    BUCHUNGEN,
    FILAMENT_BESTAND,
    SPULEN_BEISPIEL,
    Katalog,
    basis_bom,
    material_bom,
)

from kevcad_kernel.bestand import einkauf as ek  # noqa: E402
from kevcad_kernel.bestand import filament as fl  # noqa: E402
from kevcad_kernel.bestand.datei import Kennungen, hoechste_kennungen, pruefe, zusammenfassung  # noqa: E402
from kevcad_kernel.bestand.planung import plane  # noqa: E402
from kevcad_kernel.protocol import (  # noqa: E402
    check_bestand_message,
    check_druck_message,
    druckvorschau_beispiel,
    encode_frame,
    pack_bestand,
    pack_print_preview,
)

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


MATERIAL_STAND = "22.10.2026"


# Zukaufteile im Bestand (Strang „Feinschliff 2“): ein Transportroller von zweien (Fehlmenge mit Hinweis), die Kamera
# ganz (entfällt auf der Einkaufsliste); die Schnellwechselplatte ohne Link bleibt zu kaufen
MATERIAL_ZUKAUF_BESTAND = {"alutec-05200": {"stueck": [{"anzahl": 1}]},
                           "blackmagic-pocket-6k-pro": {"stueck": [{"anzahl": 1}]}}


def material_nachrichten() -> tuple[dict, dict]:
    """BOM des Kugelschiebers mit allem (Lauf 5, mit Bestand geplant) und die Druckvorschau desselben Laufs."""
    best = copy.deepcopy(BESTAND)
    best["posten"].update(copy.deepcopy(MATERIAL_ZUKAUF_BESTAND))
    best["filament"] = copy.deepcopy(FILAMENT_BESTAND)  # Strang „Bestand Stufe 2“: PETG fehlt, PLA reicht
    planung = plane(material_bom(run=5), best, Katalog(), stand=STAND)
    vorschau = pack_print_preview(druckvorschau_beispiel(run=5), seq=36)
    assert not check_druck_message(vorschau), check_druck_message(vorschau)
    return {"type": "BOM", "seq": 35, **planung.bom}, vorschau


# Strang „Bestand Stufe 2“, App: Spulen im Bereich „Bestand“ und Filament im Dialog „Gebaut“. PETG reicht nicht
# (Rest einer gekauften Spule wird S-0004), PLA hat zwei Spulen (angebrochen und voll), Platte 2 ist schon gedruckt.
SPULEN_APP = SPULEN_BEISPIEL


def bestand_filament_nachricht(seq: int) -> dict:
    """BESTAND mit Spulen und ``gebaut_filament``, gerechnet wie die Laufzeit (Platte 2 als gedruckt gebucht)."""
    best = copy.deepcopy(BESTAND)
    best["filament"] = copy.deepcopy(SPULEN_APP)
    dv = druckvorschau_beispiel(run=5)
    wahl, schon = [1], {2: "B-0005"}
    ops, info = fl.verbrauch_aenderungen(fl.bedarf(dv, 5, wahl), best, Kennungen(hoechste_kennungen(best)),
                                         "2026-10-22", Katalog())
    g = fl.gebaut_vorschau(5, ops, info, best, dv, wahl, schon, None, None,
                           lambda m: (Katalog().material(m) or {}).get("name") or m)
    return pack_bestand(bestand=best, buchungen=[], stand=STAND,
                        datei="/Users/test/Documents/Kev CAD/Kugelschieber/bestand.json", seq=seq, gebaut_filament=g)


SPULE_NEU = {"material": "petg", "gramm": 1000, "gramm_voll": 1000, "name": "Bambu PETG Basic schwarz",
             "hersteller": "Bambu Lab", "farbe": "schwarz", "ort": "Regal 3"}


def material_erwartet(bom: dict, vorschau: dict) -> dict:
    """Was der Kernel liefert: Text und CSV der Einkaufsliste (mit und ohne Druckvorschau), Summen, Verschnitt."""
    mit = ek.zusammenstellen(bom, vorschau, Katalog())
    ohne = ek.zusammenstellen(bom, None, Katalog())
    return {
        "frames": [{"file": "bom_material.frame", "type": "BOM", "payload_bytes": 0},
                   {"file": "print_material.frame", "type": "PRINT_PREVIEW", "payload_bytes": 0}],
        "projekt": "Kugelschieber", "stand": MATERIAL_STAND,
        "text": ek.text(mit, "Kugelschieber", MATERIAL_STAND), "csv": ek.csv(mit),
        "text_ohne_druck": ek.text(ohne, "Kugelschieber", MATERIAL_STAND), "csv_ohne_druck": ek.csv(ohne),
        "positionen": mit["positionen"], "lager": len(mit["lager"]), "zukauf": len(mit["zukauf"]),
        "summe": mit["summe"], "summe_lager": mit["summe_lager"], "summe_zukauf": mit["summe_zukauf"],
        "ohne_preis": mit["ohne_preis"], "normteile": len(mit["normteile"]),
        "zukauf_aus_bestand": [z["stock_id"] for z in mit["zukauf_aus_bestand"]],
        "filament": [{k: f[k] for k in ("werkstoff", "teile", "gramm", "preis", "stand")} for f in mit["filament"]],
        "filament_ohne_druck": [{k: f[k] for k in ("werkstoff", "teile", "gramm", "preis")}
                                for f in ohne["filament"]],
        # Strang „Bestand Stufe 2“: Spulen zum Kaufen (Lagerware) nur gegen die Druckvorschau desselben Laufs
        "filament_bestand": bom.get("filament_bestand"),
        "filament_kauf": [{k: z[k] for k in ("id", "benennung", "menge", "einheit", "preis_je", "preis", "hinweis",
                                             "preis_stand")} for z in mit["filament_kauf"]],
        "filament_kauf_ohne_druck": [z["id"] for z in ohne["filament_kauf"]],
        "verschnitt": {c["stock_id"]: c["verschnitt_prozent"] for c in bom["cuts"]},
        "verschnitt_definition": sorted({c.get("verschnitt_definition") for c in bom["cuts"]}),
        "verschnitt_gesamt": bom["verschnitt"],
        "run_zeile": ek.zeile_kurz(mit),
    }


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
        # Strang „Bestand Stufe 2“: Spulen (Kernel → App mit gebaut_filament, App → Kernel BESTAND_SAVE)
        ("bestand_filament", bestand_filament_nachricht(36)),
        ("bestand_save_spule", {"type": "BESTAND_SAVE", "seq": 46, "id": "a-25", "spule": dict(SPULE_NEU),
                                "anzahl": 2, "grund": "Filament: 2 Spulen PETG"}),
        ("bestand_save_spule_aendern", {"type": "BESTAND_SAVE", "seq": 47, "id": "a-26", "spule_kennung": "S-0001",
                                        "spule": {**SPULE_NEU, "gramm": 310, "ort": ""},
                                        "grund": "Spule S-0001 geändert"}),
        ("bestand_save_spule_entfernen", {"type": "BESTAND_SAVE", "seq": 48, "id": "a-27", "spule_kennung": "S-0003",
                                          "spule": None, "grund": "Spule S-0003 entfernt"}),
        ("bestand_save_filament_fuehren", {"type": "BESTAND_SAVE", "seq": 49, "id": "a-28", "filament_fuehren": True,
                                           "grund": "Filament führen"}),
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
    fil = dict(frames)["bestand_filament"]
    assert not pruefe(fil["bestand"]), pruefe(fil["bestand"])
    g = fil["gebaut_filament"]
    erwartet["filament"] = {
        "spulen": [s["kennung"] for s in fil["bestand"]["filament"]],
        "voll": [s["kennung"] for s in fil["bestand"]["filament"] if s["gramm"] >= s["gramm_voll"]],
        "gebaut": {"run": g["run"], "platten": [[p["nr"], p["gebucht"], p["buchen"]] for p in g["platten"]],
                   "spulen": [[s["kennung"], s["gramm"], s["vorher"], s["nachher"], s["leer"]] for s in g["spulen"]],
                   "neue_spulen": [[s["kennung"], s["gramm"]] for s in g["neue_spulen"]],
                   "gekauft": [[s["material"], s["gramm"]] for s in g["gekauft"]],
                   "materialien": g["materialien"]},
    }
    mat_bom, mat_vorschau = material_nachrichten()
    for name, header in (("bom_material", mat_bom), ("print_material", mat_vorschau)):
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, b""))
    path = ZIEL / "fixtures.json"
    data = json.loads(path.read_text()) if path.exists() else {"protocol": 1, "frames": [], "parts": {}}
    data["bestand"] = erwartet
    data["material"] = material_erwartet(mat_bom, mat_vorschau)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    lines = [f"{len(files)} Bestand-Testdateien nach {ZIEL}",
             f"Rohr: {rohr['aus_bestand']}, kaufen {rohr['kaufen']}, neue Reste {rohr['neue_reste']}",
             f"Einkauf: {[(e['menge'], e['einheit'], e['benennung']) for e in bom['einkaufsliste']]}, "
             f"Summe {bom['einkauf_summe']}"]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
