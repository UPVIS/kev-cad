"""Stückliste ohne Rechenprozess: Zusammenfassen, Gehrung, Zuschnitt, Eigenteile, Summen, CSV."""

import csv
import io

import pytest

from kevcad_kernel.bom import (
    Piece,
    ShownPart,
    build_bom,
    canonical_gehrung,
    cut_lines,
    de_num,
    first_fit_decreasing,
    piece_values,
    to_csv,
)
from kevcad_kernel.mcp_tools.format import bom_text

ROHR = {"id": "vkr-40", "art": "vierkantrohr", "name": "Vierkantrohr 40 × 40 × 3", "masse": {"a": 40, "s": 3},
        "material": "stahl", "kg_je_m": 3.41, "stangenlaenge": 6000, "preis": {"je_m": 8.0, "stand": "2026-10"}}
STAHL = {"id": "stahl", "name": "Stahl S235", "dichte": 7.85, "preis_je_kg": 2.4, "preis_stand": "2026-09"}


def bar_piece(seq, name, laenge, gehrung=(0, 0), item=ROHR, **kw):
    v = piece_values(item, STAHL, laenge=laenge)
    return Piece(seq=seq, name=name, stock_id=item["id"], art=item["art"], benennung=item["name"],
                 material_id="stahl", material_name="Stahl S235", laenge=laenge, gehrung=gehrung,
                 stangenlaenge=item.get("stangenlaenge"), **v, **kw)


def shown(name, pieces=(), **kw):
    return ShownPart(name=name, pieces=list(pieces), **kw)


def test_numbers():
    assert de_num(5394) == "5.394" and de_num(882.5) == "882,5" and de_num(0.25, 2) == "0,25"
    assert de_num(12000, group=False) == "12000" and de_num(-3) == "-3"


def test_canonical_gehrung():
    assert canonical_gehrung((45, 0)) == (0, 45) == canonical_gehrung((0, -45)) == canonical_gehrung((-45, 0))
    assert canonical_gehrung((45, 45)) == (45, 45) == canonical_gehrung((-45, -45))
    assert canonical_gehrung((45, -45)) == (-45, 45)
    assert canonical_gehrung((30, 45)) == (30, 45) == canonical_gehrung((45, 30))


def test_piece_values():
    v = piece_values(ROHR, STAHL, laenge=882)
    assert v["kg"] == pytest.approx(3.41 * 0.882) and v["preis"] == pytest.approx(7.056)
    platte = {"id": "p", "art": "platte", "masse": {"s": 18}, "preis": {"je_m2": 45}}
    v = piece_values(platte, {"dichte": 0.683}, flaeche_m2=0.48)
    assert v["kg"] == pytest.approx(5.9, abs=0.01) and v["preis"] == pytest.approx(21.6)
    # ohne Preis am Lagerteil: Materialpreis je kg
    v = piece_values({**ROHR, "preis": None}, STAHL, laenge=1000)
    assert v["preis"] == pytest.approx(3.41 * 2.4) and v["preis_stand"] == "2026-09"
    v = piece_values({"id": "s", "art": "schraube", "masse": {}, "preis": {"je_stueck": 0.32}}, STAHL,
                     volume_mm3=3558.6)
    assert v["kg"] == pytest.approx(0.0279, abs=1e-4) and v["preis"] == 0.32


def test_first_fit_decreasing():
    bars, too_long = first_fit_decreasing([800, 882, 882, 800, 882, 882, 600, 600, 7000], 6000, 3)
    assert too_long == [7000]
    assert bars == [[882, 882, 882, 882, 800, 800, 600], [600]]
    # Sägeschnitt zählt: 3 × 2000 passt nicht auf 6000
    bars, _ = first_fit_decreasing([2000, 2000, 2000], 6000, 3)
    assert bars == [[2000, 2000], [2000]]
    bars, _ = first_fit_decreasing([1997, 1997, 1997], 6000, 3)
    assert bars == [[1997, 1997, 1997]]  # 5.991 + 2 Schnitte = 5.997


def test_merge_lines_and_cuts():
    pieces = [bar_piece(i + 1, f"Bein {i + 1}", 882) for i in range(4)]
    pieces += [bar_piece(5, "Rahmen hinten", 800, (45, 45)), bar_piece(6, "Rahmen vorn", 800.2, (-45, -45)),
               bar_piece(7, "Strebe", 800, (0, 45)), bar_piece(8, "Strebe 2", 800, (45, 0)),
               bar_piece(9, "Lang", 6500)]
    parts = [shown(p.name, [p.seq]) for p in pieces]
    bom = build_bom(pieces, parts)
    lines = bom["lines"]
    assert [(ln["laenge"], ln["gehrung"], ln["anzahl"]) for ln in lines] == [
        (6500.0, [0.0, 0.0], 1), (882.0, [0.0, 0.0], 4), (800.0, [45.0, 45.0], 2), (800.0, [0.0, 45.0], 2)]
    beine = lines[1]
    assert beine["teile"] == ["Bein 1", "Bein 2", "Bein 3", "Bein 4"] and beine["masse_text"] == "882 mm"
    assert beine["kg_je"] == pytest.approx(3.008, abs=1e-3) and beine["kg"] == pytest.approx(12.030, abs=1e-3)
    assert beine["preis_je"] == 7.06 and beine["preis"] == pytest.approx(28.22, abs=0.01)
    (cut,) = bom["cuts"]
    assert cut["stangenlaenge"] == 6000 and cut["saegeschnitt"] == 3 and cut["zu_lang"] == [6500.0]
    assert cut["stangen"] == [[882.0, 882.0, 882.0, 882.0, 800.0, 800.0, 800.0], [800.0]]  # 5.928 + 6 Schnitte
    # Definition 2: Stange 1 mit 7 Schnitten und 51 mm Rest unter dem Mindestrest (72 mm), Stange 2 ein Schnitt (3 mm)
    assert cut["verschnitt_prozent"] == pytest.approx(75 / 12000 * 100, abs=0.05) == 0.6
    assert cut["verschnitt_definition"] == "2" and bom["verschnitt"]["stangen"] == 0.6
    assert any("länger als die Stange" in w for w in bom["warnings"])
    assert cut_lines(cut)[0] == "Stange 1: 882 + 882 + 882 + 882 + 800 + 800 + 800 = 5.928 mm, Rest 72 mm"
    totals = bom["totals"]
    assert totals["positionen"] == 4 and totals["teile"] == 9
    assert totals["preis"] == pytest.approx(sum(ln["preis"] for ln in lines), abs=0.001)
    assert totals["preis_hinweis"] == "Richtpreise, Stand 2026-10"


def test_unlinked_piece_and_eigenteile():
    pieces = [bar_piece(1, "Bein", 500)]
    parts = [
        shown("Bein gebohrt", material="Stahl S235"),  # nicht verknüpft, hat Material: Eigenteil
        shown("Konsole 1", material="aluminium", volume=36000, mass_g=97.2, size=[60, 5, 120]),
        shown("Konsole 2", material="aluminium", volume=36000.01, mass_g=97.2, size=[5, 120, 60]),
        shown("Blech", material="Stahl S235", material_id="stahl", material_name="Stahl S235", preis_je_kg=2.4,
              preis_stand="2026-08", volume=100000, mass_g=785, size=[100, 100, 10]),
        shown("Hilfsklotz"),  # ohne Material: nicht in der Stückliste
    ]
    bom = build_bom(pieces, parts)
    lines = bom["lines"]
    assert lines[0]["teile"] == [] and lines[0]["stock_id"] == "vkr-40"
    own = [ln for ln in lines if ln["eigenteil"]]
    konsole = next(ln for ln in own if ln["benennung"] == "Konsole")
    assert konsole["anzahl"] == 2 and konsole["teile"] == ["Konsole 1", "Konsole 2"]
    assert konsole["kg_je"] == pytest.approx(0.0972) and konsole["preis"] is None and konsole["stock_id"] is None
    assert konsole["masse_text"] == "60 × 5 × 120 mm" and konsole["art"] == "eigenteil"
    blech = next(ln for ln in own if ln["benennung"] == "Blech")
    assert blech["preis_je"] == pytest.approx(1.88, abs=0.01) and blech["material"] == "Stahl S235"
    w = "\n".join(bom["warnings"])
    assert "„Bein“" in w and "keinem gezeigten Teil zugeordnet" in w
    assert "Hilfsklotz" in w and "Konsole 1: Eigenteil ohne Preis" in w
    assert bom["totals"]["preis_hinweis"] == "Richtpreise, Stand 2026-08 bis 2026-10"


def test_platten_und_kleinteile():
    platte = {"id": "mpx-18", "art": "platte", "name": "Multiplex 18", "masse": {"s": 18},
              "preis": {"je_m2": 45, "stand": "2026-10"}}
    mpx = {"dichte": 0.68}
    pieces = []
    for i, (b, t) in enumerate([(800, 600), (600, 800), (400, 300)], 1):
        v = piece_values(platte, mpx, flaeche_m2=b * t / 1e6)
        pieces.append(Piece(seq=i, name=f"Platte {i}", stock_id="mpx-18", art="platte", benennung="Multiplex 18",
                            breite=b, tiefe=t, flaeche_m2=b * t / 1e6, **v))
    screw = {"id": "m8", "art": "schraube", "name": "ISO 4762", "masse": {}, "preis": {"je_stueck": 0.32}}
    for i in range(3):
        v = piece_values(screw, {"dichte": 7.85}, volume_mm3=3000)
        pieces.append(Piece(seq=10 + i, name=f"S {i}", stock_id="m8", art="schraube", benennung="ISO 4762",
                            laenge=60 if i < 2 else 40, groesse="M8-1.25", **v))
    bom = build_bom(pieces, [shown(p.name, [p.seq]) for p in pieces])
    lines = bom["lines"]
    assert [(ln["masse_text"], ln["anzahl"]) for ln in lines] == [
        ("800 × 600 mm", 2), ("400 × 300 mm", 1), ("M8 × 60", 2), ("M8 × 40", 1)]
    assert lines[0]["flaeche_m2"] == 0.48 and lines[0]["laenge"] is None and lines[0]["preis_je"] == 21.6
    assert lines[2]["preis"] == 0.64 and lines[2]["laenge"] == 60
    assert bom["cuts"] == []


def test_csv_export():
    pieces = [bar_piece(1, "Bein", 882), bar_piece(2, "Bein 2", 882)]
    bom = {"run": 3, **build_bom(pieces, [shown("Bein", [1]), shown("Bein 2", [2])])}
    text = to_csv(bom, "Gestell")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[0] == ["Stückliste", "Gestell", "Lauf 3"]
    assert rows[1][:4] == ["Pos", "Art", "Benennung", "Norm"]
    line = rows[2]
    assert line[0] == "1" and line[1] == "Vierkantrohr" and line[6] == "882" and line[8] == "2"
    assert line[9] == "3,008" and line[12] == "14,11"  # deutsche Zahlen
    i = rows.index(["Zuschnitt"])
    assert rows[i + 2][4] == "882 + 882" and rows[i + 2][6] == "4236"
    j = rows.index(["Summen"])
    assert rows[j + 1] == ["Positionen", "1"] and rows[j + 4] == ["Materialkosten (€)", "14,11"]
    assert text.endswith("\r\n")
    # als Datei mit BOM (Excel erkennt UTF-8)
    assert to_csv(bom).encode("utf-8-sig").startswith(b"\xef\xbb\xbf")


def test_bom_text_table():
    pieces = [bar_piece(i, f"Bein {i}", 882) for i in range(1, 5)] + [bar_piece(5, "Rahmen", 800, (45, 45))]
    bom = {"run": 2, **build_bom(pieces, [shown(p.name, [p.seq]) for p in pieces])}
    text = bom_text(bom)
    assert text.startswith("Stückliste (Lauf 2): 2 Positionen, 5 Teile, ")
    assert "Vierkantrohr 40 × 40 × 3" in text and "45°/45°" in text
    assert "Zuschnitt (Sägeschnitt 3 mm):" in text and "Stange 1: 882 + 882 + 882 + 882 + 800 = 4.328 mm, Rest 1.672 mm" in text
    rows = [r for r in text.splitlines() if r.strip().startswith(("1 ", "2 "))]
    assert len(rows) == 2 and len({len(r) for r in rows}) == 1  # ausgerichtet
