"""Beispiel für die Bestandsführung (BESTAND.md): Kugelschieber aus ALFER-Rohr 12 × 1 mit Resten, Multiplexplatten und
Muttern. Gemeinsame Daten für make_bestand_fixtures.py (Testdateien der App) und fake_kernel.py --bestand.

Kommt ohne build123d aus: die Stückliste entsteht mit ``build_bom`` aus ``Piece``-Zeilen wie im echten Lauf.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kevcad_kernel.bom import Piece, ShownPart, build_bom, piece_values  # noqa: E402

MATERIALIEN = {
    "alu-6060": {"id": "alu-6060", "name": "Aluminium EN AW-6060", "gruppe": "Aluminium", "dichte": 2.7,
                 "farbe": "#C4C8CC", "preis_je_kg": 8.5, "preis_stand": "2026-10"},
    "multiplex-birke": {"id": "multiplex-birke", "name": "Multiplex Birke", "gruppe": "Holzwerkstoff", "dichte": 0.68,
                        "farbe": "#D9C29A"},
    "stahl-8.8-verzinkt": {"id": "stahl-8.8-verzinkt", "name": "Stahl 8.8 verzinkt", "gruppe": "Stahl",
                           "dichte": 7.85, "farbe": "#A9AEB3"},
}

TEILE = {
    "rohr-alfer-12x1": {"id": "rohr-alfer-12x1", "art": "rohr", "name": "ALFER-Rundrohr 12 × 1",
                        "norm": "ALFER 01023, eloxiert", "masse": {"d": 12, "s": 1}, "material": "alu-6060",
                        "kg_je_m": 0.093, "stangenlaenge": 1000,
                        "preis": {"je_m": 3.9, "quelle": "Baumarkt", "stand": "2026-10"},
                        "bezugsquelle": {"url": "https://www.alfer.com/", "name": "ALFER"}},
    "platte-multiplex-birke-18": {"id": "platte-multiplex-birke-18", "art": "platte", "name": "Multiplex Birke 18 mm",
                                  "masse": {"s": 18}, "material": "multiplex-birke", "platte": [2500, 1250],
                                  "preis": {"je_m2": 45.0, "quelle": "Richtwert", "stand": "2026-10"}},
    "mutter-din315-m4": {"id": "mutter-din315-m4", "art": "mutter", "name": "Flügelmutter DIN 315 M4",
                         "masse": {"typ": "HexNut", "norm": "iso4032", "groesse": "M4-0.7"},
                         "material": "stahl-8.8-verzinkt",
                         "preis": {"je_stueck": 0.12, "quelle": "Richtwert", "stand": "2026-10"}},
    "schraube-iso7380-m6": {"id": "schraube-iso7380-m6", "art": "schraube", "name": "Linsenkopfschraube ISO 7380 M6",
                            "masse": {"typ": "ButtonHeadScrew", "norm": "iso7380_1", "groesse": "M6-1"},
                            "material": "stahl-8.8-verzinkt",
                            "preis": {"je_stueck": 0.09, "quelle": "Richtwert", "stand": "2026-10"}},
}


class Katalog:
    """Kleiner Katalog im Speicher (item/material wie ``kevcad_kernel.catalog.Catalog``)."""

    def __init__(self, teile: dict[str, Any] | None = None) -> None:
        self.teile = copy.deepcopy(teile or TEILE)

    def item(self, iid: str) -> dict[str, Any] | None:
        it = self.teile.get(iid)
        return copy.deepcopy(it) if it else None

    def material(self, mid: str) -> dict[str, Any] | None:
        m = MATERIALIEN.get(mid)
        return copy.deepcopy(m) if m else None

    def item_ids(self) -> list[str]:
        return list(self.teile)

    def search(self, query: str, art: str | None = None, limit: int | None = 30):
        hits = [t for t in self.teile.values() if query.lower() in (t["id"] + " " + t["name"]).lower()]
        return hits[:limit], len(hits)


# Bestand des Projekts „Kugelschieber“ (Kevins Angabe vom 21.10.2026 als Beispiel)
BESTAND: dict[str, Any] = {
    "version": 1,
    "einstellungen": {"mindestrest_mm": 100, "saegeblatt_mm": 3},
    "posten": {
        "rohr-alfer-12x1": {
            "ganze": {"anzahl": 2, "laenge": 1000},
            "reste": [{"kennung": "R-0001", "laenge": 430, "ort": "Regal 2", "seit": "2026-10-21"},
                      {"kennung": "R-0002", "laenge": 610, "ort": None, "seit": "2026-10-21"},
                      {"kennung": "R-0003", "laenge": 180, "ort": None, "seit": "2026-10-21"}],
            "mindestrest_mm": 80,
        },
        "platte-multiplex-birke-18": {
            "ganze": {"anzahl": 1, "b": 2500, "h": 1250},
            "reste": [{"kennung": "P-0001", "b": 600, "h": 400, "ort": None, "seit": "2026-10-20"}],
        },
        "schraube-iso7380-m6": {"stueck": [{"laenge": 16, "anzahl": 40}, {"laenge": 20, "anzahl": 12}]},
        "mutter-din315-m4": {"stueck": [{"anzahl": 10}]},
    },
}

# Stücke des Kugelschiebers: (Lagerteil, Name, Länge bzw. (Breite, Tiefe), Anzahl)
STUECKE: list[tuple[str, str, Any, int]] = [
    ("rohr-alfer-12x1", "Schieber/Führungsrohr", 1000, 3),
    ("rohr-alfer-12x1", "Schieber/Querrohr", 175, 2),
    ("rohr-alfer-12x1", "Schieber/Abstandsrohr", 120, 4),
    ("rohr-alfer-12x1", "Schieber/Anschlag", 60, 2),
    ("platte-multiplex-birke-18", "Grundplatte", (800, 600), 1),
    ("platte-multiplex-birke-18", "Seitenteil", (550, 380), 2),
    ("schraube-iso7380-m6", "Schrauben/M6x20", 20, 16),
    ("mutter-din315-m4", "Muttern/Flügelmutter M4", None, 14),
]


def basis_bom(run: int = 5, stuecke: list[tuple[str, str, Any, int]] | None = None,
              katalog: Katalog | None = None) -> dict[str, Any]:
    """Stückliste wie nach einem Lauf (``build_bom``), ohne Bestand."""
    kat = katalog or Katalog()
    pieces: list[Piece] = []
    parts: list[ShownPart] = []
    for sid, name, mass, n in stuecke or STUECKE:
        item = kat.item(sid)
        assert item is not None, sid
        mat = kat.material(item["material"])
        for i in range(n):
            pname = f"{name} {i + 1}"
            kw: dict[str, Any] = {}
            if item["art"] == "platte":
                b, t = mass
                kw = {"breite": float(b), "tiefe": float(t), "flaeche_m2": b * t / 1e6}
                v = piece_values(item, mat, flaeche_m2=b * t / 1e6)
            elif item["art"] in ("schraube", "mutter", "scheibe"):
                kw = {"groesse": item["masse"]["groesse"], "laenge": float(mass) if mass else None}
                v = piece_values(item, mat, volume_mm3=500.0)
            else:
                kw = {"laenge": float(mass), "stangenlaenge": item.get("stangenlaenge")}
                v = piece_values(item, mat, laenge=float(mass))
            p = Piece(seq=0, name=pname, stock_id=sid, art=item["art"], benennung=item["name"], norm=item.get("norm"),
                      material_id=item["material"], material_name=(mat or {}).get("name"), **kw, **v)
            p.seq = len(pieces) + 1
            pieces.append(p)
            parts.append(ShownPart(name=pname, pieces=[p.seq]))
    return {"run": run, **build_bom(pieces, parts, inventar_regel=True)}


BUCHUNGEN: list[dict[str, Any]] = [
    {"id": "B-0001", "zeit": "2026-10-21T21:40:00", "art": "eintrag", "projekt": "Kugelschieber",
     "aenderungen": [{"op": "posten", "posten": "rohr-alfer-12x1", "vorher": None,
                      "nachher": BESTAND["posten"]["rohr-alfer-12x1"]}],
     "von": "agent", "grund": "Kevin: ALFER-Rohr 12 × 1: 2 ganze Stangen, Reste 430, 610 und 180 mm"},
    {"id": "B-0002", "zeit": "2026-10-21T21:45:00", "art": "korrektur", "projekt": "Kugelschieber",
     "aenderungen": [{"op": "einstellungen", "vorher": {"mindestrest_mm": 120, "saegeblatt_mm": 3},
                      "nachher": {"mindestrest_mm": 100, "saegeblatt_mm": 3}}],
     "von": "kevin", "grund": ""},
]
