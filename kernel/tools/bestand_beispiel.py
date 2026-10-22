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
        m = MATERIALIEN.get(mid) or FILAMENT.get(mid)
        return copy.deepcopy(m) if m else None

    def find_material(self, name: str, include_proposed: bool = False) -> dict[str, Any] | None:
        """Nach id oder Name (Groß- und Kleinschreibung egal), wie ``Catalog.find_material``."""
        key = str(name or "").strip().lower()
        for m in list(MATERIALIEN.values()) + list(FILAMENT.values()):
            if key in (m["id"], m["name"].lower()):
                return copy.deepcopy(m)
        return None

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
    pieces, parts = _lagerstuecke(stuecke or STUECKE, katalog or Katalog())
    return {"run": run, **build_bom(pieces, parts, inventar_regel=True)}


# Strang „Material im Kernel angleichen“ (22.10.2026): derselbe Kugelschieber mit Zukaufteilen, Kamerazubehör ohne
# Zukauf-Angaben und Druckteilen wie in der Druckvorschau ``protocol.druckvorschau_beispiel`` (gleiche Teilnamen)
ZUKAUF = {"hersteller": "ALUTEC", "mpn": "05200", "gtin": "4005187052008",
          "url": "https://www.beispiel-shop.de/p/alutec-05200", "bild": "https://www.beispiel-shop.de/bilder/05200.jpg",
          "masse_text": "610 × 410 × 128 mm", "preis_brutto": True, "cad": "vereinfacht", "cad_quelle": "keins"}
FILAMENT = {"petg": {"id": "petg", "name": "PETG", "gruppe": "Kunststoff", "dichte": 1.27, "preis_je_kg": 17.0,
                     "preis_stand": "2026-10", "druckbar": True},
            "pla": {"id": "pla", "name": "PLA", "gruppe": "Kunststoff", "dichte": 1.24, "preis_je_kg": 17.0,
                    "preis_stand": "2026-10", "druckbar": True}}
# Spulen für den Ersatz-Kernel (--filament) und den Selbsttest der App: PETG reicht nicht, PLA hat zwei Spulen
SPULEN_BEISPIEL: list[dict[str, Any]] = [
    {"kennung": "S-0001", "material": "petg", "gramm": 120, "gramm_voll": 1000, "name": "Bambu PETG Basic schwarz",
     "hersteller": "Bambu Lab", "farbe": "schwarz", "ort": "Regal 3", "seit": "2026-10-22"},
    {"kennung": "S-0002", "material": "pla", "gramm": 310, "gramm_voll": 1000, "name": "Amazon Basics PLA weiß",
     "hersteller": "Amazon Basics", "farbe": "weiß", "ort": None, "seit": "2026-10-22"},
    {"kennung": "S-0003", "material": "pla", "gramm": 1000, "gramm_voll": 1000, "name": None,
     "hersteller": "Amazon Basics", "farbe": "weiß", "ort": "Schrank", "seit": "2026-10-22"},
]
# Filament im Bestand (Strang „Bestand Stufe 2“): PETG reicht nicht (eine Spule kaufen), PLA reicht
FILAMENT_BESTAND: list[dict[str, Any]] = [
    {"kennung": "S-0001", "material": "petg", "gramm": 120, "gramm_voll": 1000, "name": "Bambu PETG Basic schwarz",
     "hersteller": "Bambu Lab", "farbe": "schwarz", "ort": "Regal 3", "seit": "2026-10-22"},
    {"kennung": "S-0002", "material": "pla", "gramm": 310, "gramm_voll": 1000, "name": "Amazon Basics PLA weiß",
     "hersteller": "Amazon Basics", "farbe": "weiß", "ort": None, "seit": "2026-10-22"},
]
# (Name, Material, Volumen mm³, Hüllmaß)
DRUCKTEILE = [
    *[(f"Kugelschieber/Stangenhalter {o} (Druck)", "petg", 9200.0, [40.0, 24.0, 18.0])
      for o in ("vorn links", "vorn rechts", "hinten links", "hinten rechts")],
    ("Kugelschieber/Fangrolle (Druck)", "petg", 15800.0, [36.0, 36.0, 22.0]),
    ("Kugelschieber/Lenksperre (Druck)", "petg", 6100.0, [52.0, 20.0, 12.0]),
    *[(f"Kugelschieber/Abdeckkappe {i} (Druck)", "pla", 2600.0, [16.0, 16.0, 9.0]) for i in range(1, 7)],
]


def material_bom(run: int = 5, katalog: Katalog | None = None) -> dict[str, Any]:
    """Kugelschieber mit Resten, Normteilen, Zukaufteilen, Kamera und Druckteilen (Stückliste ohne Bestand)."""
    pieces, parts = _lagerstuecke(STUECKE, katalog or Katalog())

    def neu(p: Piece) -> None:
        p.seq = len(pieces) + 1
        pieces.append(p)
        parts.append(ShownPart(name=p.name, pieces=[p.seq]))

    for i in range(2):
        neu(Piece(seq=0, name=f"Kugelschieber/Transportroller {i + 1}", stock_id="alutec-05200", art="zukaufteil",
                  benennung="ALUTEC Transportroller 05200", kg=1.8, preis=24.99, preis_stand="2026-10-21",
                  zukauf=dict(ZUKAUF)))
    neu(Piece(seq=0, name="Kamera/Schnellwechselplatte", stock_id="manfrotto-200pl-pro", art="kamerazubehoer",
              benennung="Manfrotto Schnellwechselplatte 200PL-PRO", groesse="1/4\"-20", kg=0.07, preis=29.9,
              preis_stand="2026-10"))
    # Strang „Feinschliff 2“: eine Kamera, die Kevin hat (ganz aus dem Bestand, entfällt auf der Einkaufsliste)
    neu(Piece(seq=0, name="Kamera/Blackmagic Pocket 6K Pro", stock_id="blackmagic-pocket-6k-pro", art="kamera",
              benennung="Blackmagic Pocket Cinema Camera 6K Pro", kg=1.24, preis=1990.0, preis_stand="2026-10"))
    for name, mid, vol, size in DRUCKTEILE:
        m = FILAMENT[mid]
        kg = vol * m["dichte"] / 1e6
        neu(Piece(seq=0, name=name, stock_id=None, art="druckteil", benennung=name, material_id=mid,
                  material_name=m["name"], verfahren="3d-druck", volume=vol, size=list(size), kg=kg,
                  preis=kg * m["preis_je_kg"], preis_stand=m["preis_stand"]))
    return {"run": run, **build_bom(pieces, parts, inventar_regel=True)}


def _lagerstuecke(stuecke: list[tuple[str, str, Any, int]], kat: Katalog) -> tuple[list[Piece], list[ShownPart]]:
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
    return pieces, parts


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
