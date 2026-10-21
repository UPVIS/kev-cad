"""Erzeugt die Testdateien für Versionen (PROTOCOL.md, „Versionen“), getrennt von make_fixtures.py (stream.bin bleibt).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_versionen_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/

- versionen.frame: VERSIONEN mit Meilenstein, Gruppe, Variante, ungesicherten Änderungen
- version_vergleich.frame: VERSION_VERGLEICH (aus vergleich.vergleiche) mit zwei Geisterkörpern
- version_bild_req.frame: VERSION_BILD_REQ mit zwei Teilen
- versionen_fixtures.json: erwartete Werte
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from kevcad_kernel.protocol import encode_frame, pack_netze
from kevcad_kernel.versionen.archiv import gruppiere
from kevcad_kernel.versionen.schnappschuss import daten_aus_teilen
from kevcad_kernel.versionen.vergleich import vergleiche, zusammenfassung

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"
T0 = 1_792_576_800  # 2026-10-21 10:00 UTC


def quader(x0: float, x1: float, y0: float = 0, y1: float = 10, z0: float = 0, z1: float = 5) -> dict[str, np.ndarray]:
    """Kleines Netz (zwei Dreiecke der Oberseite plus eine Kante), reicht zum Prüfen der Nutzlast."""
    pos = np.array([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], np.float32)
    return {"positions": pos, "normals": np.tile(np.array([0, 0, 1], np.float32), (4, 1)),
            "triangles": np.array([[0, 1, 2], [0, 2, 3]], np.uint32), "edge_points": pos[:2].copy(),
            "edge_offsets": np.array([0, 2], np.uint32)}


def version(nr: int, ts: int, **kw) -> dict:
    v = {"nr": nr, "commit": f"{nr:07x}abc", "zeit": f"2026-10-21T{10 + (ts - T0) // 3600:02d}:00:00", "ts": ts,
         "wer": "kevin", "wer_text": "Kevin", "sitzung": None, "quelle": "lauf", "titel": "Geändert: model.py",
         "aus": None, "meilenstein": None, "kennzahlen": {"teile": 3, "masse_kg": 1.25, "kosten": 12.4, "fehler": 0,
                                                          "warnungen": 0, "pruefung": ""},
         "params": {"breite": 120}, "pruefung": None, "bild": None, "aktuell": False, "geerbt": False,
         "zweig": "haupt", "dateien": ["model.py"], "nachberechnung": None}
    v.update(kw)
    return v


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    versionen = [
        version(7, T0 + 3000, wer="agent", wer_text="Agent · 3f2a9c", sitzung="3f2a9c1b77", aktuell=True,
                meilenstein={"titel": "Halter fertig", "notiz": "Bohrungen M6 geprüft", "zeit": "2026-10-21T11:00:00",
                             "wer": "agent"},
                bild="/tmp/kevcad-fixture/.kevcad/versionen/bilder/7.png", params={"breite": 140, "hoehe": 80}),
        version(6, T0 + 1500, quelle="wiederherstellen", titel="Wiederhergestellt aus V2", aus=2),
        version(5, T0 + 900),
        version(4, T0 + 700),
        version(3, T0 + 500, kennzahlen=None, nachberechnung="V3 ließ sich nicht neu rechnen: NameError"),
        version(2, T0 + 300, quelle="uebernahme", titel="Vorgeschichte: model.py Stand 2", wer="unbekannt",
                wer_text="Auto-Lauf"),
        version(1, T0, geerbt=True, zweig="haupt", titel="Erster Stand"),
    ]
    gruppen = gruppiere(versionen)
    versionen_msg = {
        "type": "VERSIONEN", "seq": 40, "projekt": "/tmp/kevcad-fixture", "verfuegbar": True, "meldung": None,
        "variante": "v-leicht", "varianten": [
            {"id": "haupt", "name": "Hauptstand", "aktuell": False, "versionen": 6, "letzte": "2026-10-21T10:50:00",
             "letzte_nr": 6, "von": None},
            {"id": "v-leicht", "name": "Leichtbau", "aktuell": True, "versionen": 1, "letzte": "2026-10-21T10:50:00",
             "letzte_nr": 7, "von": 1}],
        "versionen": versionen, "gruppen": gruppen, "anzahl": 7, "meilensteine": 1, "ungesichert": True,
        "reply_to": "a-12",
    }

    def teil(name, key, vol, mn, mx, farbe=(0.5, 0.5, 0.5, 1.0)):
        return (name, key, {"props": {"volume": vol, "area": vol / 2, "mass": vol * 0.0027,
                                      "center": [(a + b) / 2 for a, b in zip(mn, mx)]},
                            "bbox": {"min": list(mn), "max": list(mx)}, "color": list(farbe),
                            "material": "aluminium", "counts": {"tri": 2}})

    bom_a = {"lines": [{"pos": 1, "art": "flach", "stock_id": "flach-40", "benennung": "Flach 40",
                        "masse_text": "120 mm", "anzahl": 1, "preis": 2.0, "teile": ["Platte"]},
                       {"pos": 2, "art": "schraube", "stock_id": "m6", "benennung": "M6", "masse_text": "M6 × 16",
                        "anzahl": 8, "preis": 1.0, "teile": ["Schraube"]}], "totals": {"kg": 1.0, "preis": 3.0}}
    bom_b = {"lines": [{"pos": 1, "art": "flach", "stock_id": "flach-40", "benennung": "Flach 40",
                        "masse_text": "140 mm", "anzahl": 1, "preis": 2.3, "teile": ["Platte"]},
                       {"pos": 2, "art": "platte", "stock_id": "alu-3", "benennung": "Alu 3",
                        "masse_text": "200 × 100 mm", "anzahl": 1, "preis": 4.0, "teile": ["Deckel"]}],
             "totals": {"kg": 1.2, "preis": 6.3}}
    alt = daten_aus_teilen([teil("Platte", "k1", 1000, (0, 0, 0), (20, 10, 5)),
                            teil("Schraube", "k2", 50, (30, 0, 0), (32, 2, 16)),
                            teil("Klotz", "k3", 125, (0, 0, 5), (5, 5, 10))],
                           bom=bom_a, params={"breite": 120}, pruefung={"state": "done", "zaehler": {"fehler": 0},
                                                                         "zusammenfassung": ""})
    neu = daten_aus_teilen([teil("Platte", "k1b", 1400, (0, 0, 0), (28, 10, 5)),
                            teil("Klotz", "k3", 125, (0, 0, 5), (5, 5, 10)),
                            teil("Deckel", "k4", 300, (0, 0, 10), (20, 10, 11))],
                           bom=bom_b, params={"breite": 140, "hoehe": 80},
                           pruefung={"state": "done", "zaehler": {"fehler": 1},
                                     "zusammenfassung": "1 Durchdringung"})
    v = vergleiche(alt, neu)
    koepfe, nutzlast = pack_netze([({"teil": "Platte", "art": "alt"}, quader(0, 20)),
                                   ({"teil": "Schraube", "art": "weg"}, quader(30, 32))])
    vergleich_msg = {
        "type": "VERSION_VERGLEICH", "seq": 41, "reply_to": "a-13",
        "a": {"nr": 5, "titel": "Geändert: model.py", "zeit": "2026-10-21T10:15:00", "wer_text": "Kevin",
              "meilenstein": None, "kennzahlen": alt["kennzahlen"], "commit": "0000005abc"},
        "b": {"nr": None, "titel": "Aktueller Stand", "zeit": None},
        "aktuell": True, "zusammenfassung": zusammenfassung(v), **v,
        "code": {"dateien": [{"pfad": "model.py", "status": "M", "plus": 2, "minus": 1, "binaer": False},
                             {"pfad": "deckel.py", "status": "A", "plus": 4, "minus": 0, "binaer": False}],
                 "diff": "--- a/model.py\n+++ b/model.py\n@@ -1 +1,2 @@\n-breite = 120\n+breite = 140\n+hoehe = 80\n",
                 "gekuerzt": False, "zeilen": 6},
        "hinweise": ["V5 aus dem Zwischenspeicher"], "ms": 37, "geometrie": koepfe,
    }
    bild_koepfe, bild_nutzlast = pack_netze([({"teil": "Platte", "farbe": [0.8, 0.2, 0.1, 1.0]}, quader(0, 20)),
                                             ({"teil": "Klotz", "farbe": [0.2, 0.4, 0.9, 1.0]}, quader(0, 5, 0, 5))])
    bild_msg = {"type": "VERSION_BILD_REQ", "seq": 42, "id": "k-31", "nr": 7, "width": 288, "height": 180,
                "view": "iso", "teile": bild_koepfe}
    frames = {"versionen": (versionen_msg, b""), "version_vergleich": (vergleich_msg, nutzlast),
              "version_bild_req": (bild_msg, bild_nutzlast)}
    for name, (header, payload) in frames.items():
        (ZIEL / f"{name}.frame").write_bytes(encode_frame(header, payload))
    expected = {name: header for name, (header, _) in frames.items()}
    (ZIEL / "versionen_fixtures.json").write_text(json.dumps(expected, indent=1, ensure_ascii=False))
    print(f"{len(frames)} Versionsrahmen nach {ZIEL} (Gruppen: {[g['text'] for g in gruppen]})")


if __name__ == "__main__":
    main()
