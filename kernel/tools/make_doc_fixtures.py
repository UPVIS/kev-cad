"""Testdateien der Zeichnungs-Nachrichten (DOKUMENTE.md, Protokoll) für die App-Stränge P6-A1/P6-A2.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_doc_fixtures.py   (läuft auch am Ende von make_fixtures.py)
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/

- drawing.frame       DRAWING (Kernel → App) eines echten Blatts: Platte mit Lochbild und Bohrung, gerechnet von der
                      Zeichnungs-Engine, mit Polylinien-Nutzlast
- drawing_tube.frame  DRAWING eines Rohrs mit unterbrochener Ansicht (Linienart bruch) und Bohrungen ab dem Rohrende
- docs.frame          DOCS (Kernel → App)
- drawing_req.frame   DRAWING_REQ (App → Kernel)
- drawing_edit.frame  DRAWING_EDIT (App → Kernel) mit allen Operationen
- fixtures.json       eigener Abschnitt ``dokumente`` mit den erwarteten Werten (der Rest der Datei bleibt)

stream.bin bleibt unverändert.
"""

from __future__ import annotations

import json
from pathlib import Path

from build123d import Align, Box, Cylinder, Pos, Rot

from kevcad_kernel.protocol import docs_message, encode_frame, pack_drawing, unpack_polylinien
from kevcad_kernel.zeichnung import dokument
from kevcad_kernel.zeichnung.projektion import EXAKT, form_schluessel
from kevcad_kernel.zeichnung.szene import Szene, Teil
from kevcad_kernel.zeichnung.zeichner import lies_nutzlast, rechne

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def _teil(name: str, form, kopf: dict, katalog: dict | None) -> Teil:
    bb = form.bounding_box()
    k = {"bbox": {"min": [bb.min.X, bb.min.Y, bb.min.Z], "max": [bb.max.X, bb.max.Y, bb.max.Z]},
         "props": {"mass": round(form.volume * 2.7e-3, 3)}, "material": "Aluminium EN AW-6060", **kopf}
    return Teil(name, form, form_schluessel(form), k, katalog)


def _blatt(teil: Teil, bid: str, titel: str) -> tuple[dict, bytes, dict]:
    szene = Szene({teil.name: teil}, None, {"name": "Testprojekt", "version": "Meilenstein 1"}, 7)
    b = dokument.neu(bid, titel, "teil", [teil.name])
    b["schriftfeld"]["datum"] = "2026-10-22"  # fest, damit die Datei nicht bei jedem Erzeugen anders aussieht
    erg = rechne(b, szene)
    gruppen = lies_nutzlast(erg.kopf, erg.nutzlast)
    kopf = {k: v for k, v in erg.kopf.items() if k != "ms"}
    return kopf, erg.nutzlast, {"gruppen": gruppen, "erg": erg}


def main() -> None:
    from kevcad_kernel.zeichnung import zeichner

    zeichner.EXAKT_BUDGET_S = 0  # Netz: gleiche Testdateien bei jedem Erzeugen (die exakte Rechnung hängt vom Takt ab)
    ZIEL.mkdir(parents=True, exist_ok=True)
    platte = Box(200, 100, 5, align=(Align.MIN, Align.MIN, Align.MIN))
    platte -= [Pos(100 + x, 50 + y, 0) * Cylinder(3.3, 20) for x in (-80, 80) for y in (-30, 30)]
    platte -= Pos(30, 50, 0) * Cylinder(4, 20)
    tp = _teil("Halter/Platte", platte, {"stock": {"id": "platte-alu-5", "name": "Aluplatte 5"}},
               {"id": "platte-alu-5", "art": "platte", "name": "Aluplatte 5 mm"})
    kopf, nutz, info = _blatt(tp, "platte", "Platte")
    header, payload = pack_drawing(kopf, info["gruppen"], reply_to="a-11", seq=31)
    assert payload == nutz
    (ZIEL / "drawing.frame").write_bytes(encode_frame(header, payload))

    rohr = Cylinder(6, 1000, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Pos(0, 0, -1) * Cylinder(
        5, 1002, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for z in (30, 970):
        rohr -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(2.1, 20)
    tr = _teil("Halter/Rohr", rohr, {"stock": {"id": "rohr-alu-12x1.0", "name": "Alurohr 12 × 1,0", "laenge": 1000,
                                               "gehrung": [0, 0]}},
               {"id": "rohr-alu-12x1.0", "art": "rohr", "name": "Alurohr 12 × 1,0"})
    kopf_r, nutz_r, info_r = _blatt(tr, "rohr", "Rohr")
    header_r, payload_r = pack_drawing(kopf_r, info_r["gruppen"], seq=32)
    (ZIEL / "drawing_tube.frame").write_bytes(encode_frame(header_r, payload_r))
    EXAKT.schliessen()

    blaetter = []
    for k in (kopf, kopf_r):
        b = k["blatt"]
        blaetter.append({"id": b["id"], "titel": b["titel"], "inhalt": b["inhalt"], "format": b["format"],
                         "ausrichtung": b["ausrichtung"], "massstab": b["massstab"], "verwaiste_masse": 0,
                         "masse": len(b["masse"]), "stand": k["stand"], "hinweise": [], "pruefung": 0})
    docs = docs_message(7, blaetter, None, seq=33)
    (ZIEL / "docs.frame").write_bytes(encode_frame(docs))
    (ZIEL / "drawing_req.frame").write_bytes(encode_frame({"type": "DRAWING_REQ", "seq": 5, "id": "a-11",
                                                           "blatt": "platte"}))
    ops = [
        {"op": "mass_verschieben", "id": "m1", "versatz": -18.0},
        {"op": "mass_verschieben", "id": "m3", "text_lage": [120.5, 80.25]},
        {"op": "mass_loeschen", "id": "m2"},
        {"op": "mass_neu", "art": "linear", "ansicht": "v1", "richtung": "x", "versatz": 20.0,
         "bezuege": [{"ansicht": "v1", "punkt": [40.0, 100.0]}, {"ansicht": "v1", "punkt": [60.0, 100.0]}]},
        {"op": "ansicht_neu", "art": "iso", "lage": [230.0, 150.0]},
        {"op": "ansicht_verschieben", "id": "v1", "lage": [120.0, 110.0]},
        {"op": "ansicht_loeschen", "id": "v2"},
        {"op": "massstab", "wert": "1:2"},
        {"op": "notiz", "text": "Grat entfernen", "lage": [30.0, 30.0], "zeiger": {"ansicht": "v1",
                                                                                   "punkt": [50.0, 90.0]}},
        {"op": "notiz_loeschen", "id": "n1"},
        {"op": "schriftfeld", "feld": "freigegeben", "wert": "Kevin Schwed"},
        {"op": "auto", "ansichten": True, "masse": True, "zuruecksetzen": False},
        {"op": "unterdrueckung_aufheben", "index": 0},
    ]
    (ZIEL / "drawing_edit.frame").write_bytes(encode_frame({"type": "DRAWING_EDIT", "seq": 6, "id": "a-12",
                                                            "blatt": "platte", "von": "kevin", "ops": ops}))

    gruppen = unpack_polylinien(header, payload)
    erste = next(pl for g in gruppen for art in header["linien_reihenfolge"] for pl in g[art])
    m0 = header["masse"][0]
    erwartet = {
        "drawing": {
            "reply_to": "a-11", "blatt_id": "platte", "format": header["blatt"]["format"],
            "ausrichtung": header["blatt"]["ausrichtung"], "massstab": header["blatt"]["massstab"],
            "blattgroesse": header["blattgroesse"], "linien_reihenfolge": header["linien_reihenfolge"],
            "geometrie": [{"id": g["id"], "art": g["art"], "linien": g["linien"]} for g in header["geometrie"]],
            "payload_bytes": len(payload), "erster_punkt": [round(float(v), 4) for v in erste[0]],
            "masse": len(header["masse"]), "erstes_mass": {k: m0[k] for k in ("id", "text", "wert", "text_winkel")},
            "masstexte": sorted(m["text"] for m in header["masse"]),
            "texte": len(header["texte"]), "gefuellt": len(header["gefuellt"]),
        },
        "drawing_tube": {
            "blatt_id": "rohr", "bruch": sum(g["linien"]["bruch"] for g in header_r["geometrie"]),
            "masstexte": sorted(m["text"] for m in header_r["masse"]), "payload_bytes": len(payload_r),
        },
        "docs": {"run": 7, "blaetter": [b["id"] for b in blaetter]},
        "drawing_edit": {"ops": [o["op"] for o in ops]},
    }
    pfad = ZIEL / "fixtures.json"
    alles = json.loads(pfad.read_text()) if pfad.exists() else {}
    alles["dokumente"] = erwartet
    pfad.write_text(json.dumps(alles, indent=1, ensure_ascii=False))
    print(f"Zeichnungs-Testdateien nach {ZIEL}: {len(header['masse'])} Maße, {len(payload)} Byte Nutzlast")


if __name__ == "__main__":
    main()
