"""Bestand je Projekt ohne Laufzeit: Datei und Buchungen, Zuschnitt 1D und 2D, Stückgut, Einkaufsliste (BESTAND.md)."""

import csv
import io
import json
import os
import random
import time
from pathlib import Path

import pytest

from kevcad_kernel.bestand import BestandDatei, BestandError, gebaut_aenderungen, plane, plane_1d, plane_2d, pruefe
from kevcad_kernel.bestand.datei import anwenden, pfade, umkehren, zusammenfassung
from kevcad_kernel.bestand import einkauf as ek
from kevcad_kernel.bestand.text import quellen_zeilen, zuschnitt_kopf
from kevcad_kernel.bom import verschnitt_bilanz, verschnitt_prozent
from kevcad_kernel.bestand.zuschnitt import naeherung_1d

ALFER = {"id": "rohr-alfer-12x1", "art": "rohr", "name": "ALFER-Rundrohr 12 × 1", "masse": {"d": 12, "s": 1},
         "material": "alu-6060", "stangenlaenge": 1000, "preis": {"je_m": 3.9, "quelle": "Baumarkt", "stand": "2026-10"},
         "bezugsquelle": {"url": "https://www.alfer.com/", "name": "ALFER"}}
PLATTE = {"id": "platte-multiplex-birke-18", "art": "platte", "name": "Multiplex Birke 18 mm", "masse": {"s": 18},
          "material": "multiplex-birke", "platte": [2500, 1250], "preis": {"je_m2": 45.0, "stand": "2026-10"}}
MUTTER = {"id": "mutter-iso4032-m4", "art": "mutter", "name": "Sechskantmutter ISO 4032 M4",
          "masse": {"typ": "HexNut", "norm": "iso4032", "groesse": "M4-0.7"}, "material": "stahl-8.8-verzinkt",
          "preis": {"je_stueck": 0.03, "stand": "2026-10"}}
SCHRAUBE = {"id": "schraube-iso7380-m6", "art": "schraube", "name": "Linsenkopfschraube ISO 7380 M6",
            "masse": {"typ": "ButtonHeadScrew", "norm": "iso7380_1", "groesse": "M6-1"}, "material": "stahl-8.8-verzinkt",
            "preis": {"je_stueck": 0.1, "stand": "2026-09"}}
ITEMS = {i["id"]: i for i in (ALFER, PLATTE, MUTTER, SCHRAUBE)}


class Katalog:
    def item(self, iid):
        return ITEMS.get(iid)

    def material(self, mid):
        return None


KAT = Katalog()


def rohr_line(laenge, anzahl, pos=1):
    return {"pos": pos, "art": "rohr", "stock_id": ALFER["id"], "benennung": ALFER["name"], "laenge": float(laenge),
            "anzahl": anzahl, "preis_je": round(3.9 * laenge / 1000, 2), "masse_text": f"{laenge} mm"}


def bom_mit(lines, stangen=None):
    cuts = []
    if any(ln["art"] == "rohr" for ln in lines):
        cuts.append({"stock_id": ALFER["id"], "benennung": ALFER["name"], "stangenlaenge": 1000, "saegeschnitt": 3,
                     "stangen": stangen or [[1]], "verschnitt_prozent": 1.0, "preis_stangen": 3.9})
    return {"run": 7, "lines": lines, "cuts": cuts, "totals": {}, "warnings": []}


KUGELSCHIEBER = [rohr_line(1000, 3, 1), rohr_line(175, 2, 2), rohr_line(120, 4, 3), rohr_line(60, 2, 4)]


def beispiel_bestand(mindestrest=80):
    return {"version": 1, "einstellungen": {"mindestrest_mm": 100, "saegeblatt_mm": 3}, "posten": {
        ALFER["id"]: {"ganze": {"anzahl": 2, "laenge": 1000},
                      "reste": [{"kennung": "R-0001", "laenge": 430, "ort": "Regal 2", "seit": "2026-10-21"},
                                {"kennung": "R-0002", "laenge": 610, "ort": None, "seit": "2026-10-21"},
                                {"kennung": "R-0003", "laenge": 180, "ort": None, "seit": "2026-10-21"}],
                      "mindestrest_mm": mindestrest}}}


def stueck_count(cut):
    return sorted(x for q in cut["quellen"] for x in q["stuecke"])


# ---------------------------------------------------------------------------------------------------------------------
# Zuschnitt 1D


def test_1d_reste_zuerst_beispiel():
    pl = plane(bom_mit(KUGELSCHIEBER), beispiel_bestand(), KAT, stand="2026-10-21T22:00:00")
    cut = pl.bom["cuts"][0]
    # bisherige Felder unverändert, nur der Verschnitt ist nach Definition 2 über die Quellen gerechnet
    assert cut["stangen"] == [[1]] and cut["stangenlaenge"] == 1000
    assert cut["verschnitt_definition"] == "2" and cut["verschnitt_prozent"] == verschnitt_prozent(cut, 80)
    assert stueck_count(cut) == sorted([1000] * 3 + [175] * 2 + [120] * 4 + [60] * 2)
    arts = [q["art"] for q in cut["quellen"]]
    assert arts == sorted(arts, key=["rest", "bestand", "kaufen"].index)  # Reste, Bestand, kaufen
    assert cut["aus_bestand"] == {"reste": 3, "ganze": 2} and cut["kaufen"] == 1
    for q in cut["quellen"]:
        used = sum(q["stuecke"]) + 3 * (len(q["stuecke"]) - 1)
        assert used <= q["laenge"]
        assert q["rest_neu"] == max(0, q["laenge"] - sum(q["stuecke"]) - 3 * len(q["stuecke"]))
        assert q["verschnitt"] == (0 < q["rest_neu"] < 80)
    assert cut["neue_reste"] == [q["rest_neu"] for q in cut["quellen"] if q["rest_neu"] >= 80]
    assert all(r >= 80 for r in cut["neue_reste"])
    assert pl.bom["bestand_stand"] == "2026-10-21T22:00:00" and pl.bom["fehlt"] is True
    einkauf = pl.bom["einkaufsliste"]
    assert einkauf == [{"id": ALFER["id"], "benennung": "ALFER-Rundrohr 12 × 1", "menge": 1,
                        "einheit": "Stange 1.000 mm", "preis_je": 3.9, "preis": 3.9, "link": "https://www.alfer.com/",
                        "link_text": "ALFER", "preis_stand": "2026-10",
                        "hinweis": "Bestand im Projekt reicht nicht: 2 ganze Stangen und 3 Reste verplant"}]
    assert pl.bom["einkauf_summe"] == 3.9 and pl.bom["einkauf_hinweis"] == "Richtpreise, Stand 2026-10"
    v = pl.verbrauch[0]
    assert sorted(v.reste) == ["R-0001", "R-0002", "R-0003"] and v.ganze == 2 and v.neue_reste == cut["neue_reste"]


def test_1d_ohne_bestandsdatei_alles_kaufen():
    pl = plane(bom_mit(KUGELSCHIEBER), None, KAT)
    cut = pl.bom["cuts"][0]
    assert {q["art"] for q in cut["quellen"]} == {"kaufen"} and cut["aus_bestand"] == {"reste": 0, "ganze": 0}
    assert cut["kaufen"] == 4  # 3 × 1000 je eine Stange, der Rest passt auf eine
    assert pl.bom["einkaufsliste"][0]["menge"] == 4 and pl.bom["einkaufsliste"][0]["hinweis"] is None
    assert pl.bom["einkauf_summe"] == 15.6 and pl.bom["bestand_stand"] is None and pl.verbrauch == [
        v for v in pl.verbrauch if v.neue_reste]


def test_1d_kleinster_passender_rest_in_der_naeherung():
    used, zu_lang = naeherung_1d([175], [("R-1", 430), ("R-2", 180), ("R-3", 610)], 1, 1000, 1000, 3)
    assert zu_lang == [] and [(b.quelle.kennung, b.stuecke) for b in used] == [("R-2", [175])]


def test_mindestrest_je_posten_und_einstellung():
    bom = bom_mit([rohr_line(300, 1)])
    best = {"version": 1, "einstellungen": {"mindestrest_mm": 100, "saegeblatt_mm": 3},
            "posten": {ALFER["id"]: {"reste": [{"kennung": "R-0001", "laenge": 395}]}}}
    cut = plane(bom, best, KAT).bom["cuts"][0]
    q = cut["quellen"][0]
    assert q["kennung"] == "R-0001" and q["rest_neu"] == 92 and q["verschnitt"] is True and cut["neue_reste"] == []
    best["posten"][ALFER["id"]]["mindestrest_mm"] = 80
    cut = plane(bom, best, KAT).bom["cuts"][0]
    assert cut["quellen"][0]["verschnitt"] is False and cut["neue_reste"] == [92] and cut["mindestrest"] == 80


def test_saegeblatt_aus_den_einstellungen():
    best = {"version": 1, "einstellungen": {"saegeblatt_mm": 0}, "posten": {}}
    cut = plane(bom_mit([rohr_line(500, 2)], [[500], [500]]), best, KAT).bom["cuts"][0]
    assert cut["kaufen"] == 1 and cut["quellen"][0]["rest_neu"] == 0 and cut["saegeschnitt"] == 0
    assert cut["stangen"] == [[500.0, 500.0]]  # bisherige Felder mit derselben Schnittbreite neu gerechnet


def test_optimierung_besser_als_naeherung_mit_zeitlimit():
    stuecke = [497, 397, 297, 297, 247, 247]
    used, _ = naeherung_1d(stuecke, [], 0, None, 1000, 3)
    assert sum(1 for b in used if b.quelle.art == "kaufen") == 3
    pl = plane_1d(stuecke, [], 0, None, 1000, 3, 100, zeitlimit_s=0.2)
    assert pl.verfahren == "milp" and pl.milp_status == "optimal"
    assert sum(1 for b in pl.belegungen if b.quelle.art == "kaufen") == 2
    assert pl.dauer_ms < 1000
    # großer Fall: das Zeitlimit greift, das Ergebnis bleibt gültig und vollständig
    rnd = random.Random(4)
    big = [rnd.choice([137, 211, 298, 333, 412, 487, 555, 610, 733, 845]) for _ in range(160)]
    t0 = time.perf_counter()
    pl = plane_1d(big, [(f"R-{i:04d}", rnd.randint(150, 900)) for i in range(30)], 8, 6000, 6000, 3, 100,
                  zeitlimit_s=0.2)
    took = (time.perf_counter() - t0) * 1000
    assert took < 1500, took
    assert sorted(x for b in pl.belegungen for x in b.stuecke) == sorted(float(x) for x in big)
    for b in pl.belegungen:
        assert sum(b.stuecke) + 3 * (len(b.stuecke) - 1) <= b.quelle.laenge + 1e-6
    assert len({b.quelle.kennung for b in pl.belegungen if b.quelle.art == "rest"}) == \
        sum(1 for b in pl.belegungen if b.quelle.art == "rest")


def test_zu_lange_stuecke_auf_die_einkaufsliste():
    bom = bom_mit([rohr_line(1200, 1), rohr_line(300, 1)])
    pl = plane(bom, None, KAT)
    einkauf = pl.bom["einkaufsliste"]
    assert [k["einheit"] for k in einkauf] == ["Stange 1.000 mm", "Sonderlänge 1.200 mm"]
    assert "Sonderlänge bestellen oder stoßen" in einkauf[1]["hinweis"] and einkauf[1]["preis"] == 4.68


# ---------------------------------------------------------------------------------------------------------------------
# Platten


def _guillotine(rects, x0, y0, x1, y1):
    """True, wenn sich die Rechtecke durch durchgehende Schnitte trennen lassen."""
    if len(rects) <= 1:
        return True
    for axis in (0, 1):
        cuts = sorted({r[axis] + r[2 + axis] for r in rects})
        for c in cuts:
            a = [r for r in rects if r[axis] + r[2 + axis] <= c + 1e-6]
            b = [r for r in rects if r[axis] >= c - 1e-6]
            if a and b and len(a) + len(b) == len(rects):
                if axis == 0:
                    return _guillotine(a, x0, y0, c, y1) and _guillotine(b, c, y0, x1, y1)
                return _guillotine(a, x0, y0, x1, c) and _guillotine(b, x0, c, x1, y1)
    return False


def test_platten_guillotine_mit_resten_und_saegeblatt():
    stuecke = [(800, 600), (800, 600), (550, 380), (400, 300), (300, 200), (300, 200), (120, 90)]
    pl = plane_2d(stuecke, [("P-0001", 600, 400), ("P-0002", 1300, 700)], 1, (2500, 1250), (2500, 1250), 3, 100)
    placed = []
    for bel in pl.belegungen:
        q = bel.quelle
        rects = []
        for p in bel.stuecke:
            assert 0 <= p.x and 0 <= p.y and p.x + p.b <= q.b + 1e-6 and p.y + p.h <= q.h + 1e-6
            orig = stuecke[p.nr]
            assert (p.b, p.h) == ((orig[1], orig[0]) if p.gedreht else orig)
            rects.append((p.x, p.y, p.b, p.h))
            placed.append(p.nr)
        for i, a in enumerate(rects):  # kein Überlapp, Sägefuge zwischen Stücken
            for b in rects[i + 1:]:
                sep_x = a[0] + a[2] + 3 <= b[0] + 1e-6 or b[0] + b[2] + 3 <= a[0] + 1e-6
                sep_y = a[1] + a[3] + 3 <= b[1] + 1e-6 or b[1] + b[3] + 3 <= a[1] + 1e-6
                assert sep_x or sep_y, (a, b)
        grown = [(x, y, w + 3, h + 3) for x, y, w, h in rects]  # Fuge dazugerechnet
        assert _guillotine(grown, 0, 0, q.b + 3, q.h + 3)
        for r in bel.reste(100):
            assert min(r.b, r.h) >= 100
    assert sorted(placed) == list(range(len(stuecke))) and pl.zu_gross == []
    arts = [bel.quelle.art for bel in pl.belegungen]
    assert "rest" in arts and arts[0] == "rest"  # Reste zuerst
    assert not any(bel.quelle.art == "kaufen" for bel in pl.belegungen)  # passt in Reste und eine Platte
    assert pl.dauer_ms < 1000


def test_platten_in_der_stueckliste():
    lines = [{"pos": 1, "art": "platte", "stock_id": PLATTE["id"], "benennung": PLATTE["name"], "breite": 800.0,
              "tiefe": 600.0, "masse_text": "800 × 600 mm", "anzahl": 5, "flaeche_m2": 0.48, "preis_je": 21.6}]
    best = {"version": 1, "posten": {PLATTE["id"]: {"reste": [{"kennung": "P-0003", "b": 820, "h": 620}]}}}
    pl = plane({"run": 1, "lines": lines, "cuts": [], "totals": {}, "warnings": []}, best, KAT)
    (cut,) = pl.bom["cuts"]
    assert cut["art"] == "platte" and cut["platte"] == {"b": 2500, "h": 1250} and "stangen" not in cut
    assert cut["quellen"][0]["art"] == "rest" and cut["quellen"][0]["kennung"] == "P-0003"
    assert cut["aus_bestand"] == {"reste": 1, "ganze": 0} and cut["kaufen"] == 1
    st = cut["quellen"][1]["stuecke"][0]
    assert set(st) == {"b", "h", "x", "y", "gedreht"} and all(set(r) == {"b", "h", "x", "y"}
                                                                for q in cut["quellen"] for r in q["rest_neu"])
    assert sum(len(q["stuecke"]) for q in cut["quellen"]) == 5
    (k,) = pl.bom["einkaufsliste"]
    assert k["einheit"] == "Platte 2.500 × 1.250 mm" and k["preis_je"] == round(45 * 2.5 * 1.25, 2)
    # ohne Standardformat: Zuschnitte kaufen
    ITEMS["platte-ohne"] = {**PLATTE, "id": "platte-ohne", "platte": None}
    try:
        lines[0]["stock_id"] = "platte-ohne"
        pl = plane({"run": 1, "lines": lines, "cuts": [], "totals": {}, "warnings": []}, None, KAT)
        (k,) = pl.bom["einkaufsliste"]
        assert k["menge"] == 5 and k["einheit"] == "Zuschnitt 800 × 600 mm" and "Zuschnitt" in k["hinweis"]
    finally:
        ITEMS.pop("platte-ohne")


# ---------------------------------------------------------------------------------------------------------------------
# Stückgut und Einkaufsliste


def test_stueckgut_mit_schraubenlaengen():
    lines = [{"pos": 1, "art": "schraube", "stock_id": SCHRAUBE["id"], "benennung": SCHRAUBE["name"], "laenge": 20.0,
              "masse_text": "M6 × 20", "anzahl": 20, "preis_je": 0.1},
             {"pos": 2, "art": "schraube", "stock_id": SCHRAUBE["id"], "benennung": SCHRAUBE["name"], "laenge": 16.0,
              "masse_text": "M6 × 16", "anzahl": 10, "preis_je": 0.1},
             {"pos": 3, "art": "mutter", "stock_id": MUTTER["id"], "benennung": MUTTER["name"], "laenge": None,
              "masse_text": "M4", "anzahl": 14, "preis_je": 0.03}]
    best = {"version": 1, "posten": {SCHRAUBE["id"]: {"stueck": [{"laenge": 16, "anzahl": 40},
                                                                 {"laenge": 20, "anzahl": 12}]},
                                     MUTTER["id"]: {"stueck": [{"anzahl": 10}]}}}
    pl = plane({"run": 2, "lines": lines, "cuts": [], "totals": {}, "warnings": []}, best, KAT)
    sg = {(s["stock_id"], s["laenge"]): (s["anzahl"], s["aus_bestand"], s["kaufen"]) for s in pl.bom["stueckgut"]}
    assert sg == {(SCHRAUBE["id"], 20): (20, 12, 8), (SCHRAUBE["id"], 16): (10, 10, 0), (MUTTER["id"], None): (14, 10, 4)}
    einkauf = {k["benennung"]: k for k in pl.bom["einkaufsliste"]}
    assert set(einkauf) == {"Linsenkopfschraube ISO 7380 M6, Länge 20 mm", MUTTER["name"]}
    m = einkauf[MUTTER["name"]]
    assert (m["menge"], m["einheit"], m["preis"], m["hinweis"]) == (4, "Stück", 0.12,
                                                                    "Bestand im Projekt: 10, gebraucht: 14")
    assert pl.bom["einkauf_summe"] == 0.92
    assert pl.bom["einkauf_hinweis"] == "Richtpreise, Stand 2026-09 bis 2026-10"
    ops = gebaut_aenderungen(pl.verbrauch, best, None, "2026-10-21")
    assert sorted((o["posten"], o["laenge"], o["delta"]) for o in ops) == sorted(
        [(SCHRAUBE["id"], 20, -12), (SCHRAUBE["id"], 16, -10), (MUTTER["id"], None, -10)])
    # Einträge ohne Länge passen zu jeder Schraubenlänge
    best[SCHRAUBE["id"]] = None
    best["posten"][SCHRAUBE["id"]] = {"stueck": [{"anzahl": 25}]}
    sg = {(s["stock_id"], s["laenge"]): s["aus_bestand"] for s in plane(
        {"run": 2, "lines": lines, "cuts": [], "totals": {}, "warnings": []}, best, KAT).bom["stueckgut"]}
    assert sg[(SCHRAUBE["id"], 20)] == 20 and sg[(SCHRAUBE["id"], 16)] == 5


def test_einkaufsliste_text_csv_und_summe(tmp_path):
    lines = KUGELSCHIEBER + [{"pos": 5, "art": "mutter", "stock_id": MUTTER["id"], "benennung": MUTTER["name"],
                              "masse_text": "M4", "anzahl": 4, "preis_je": 0.03}]
    pl = plane(bom_mit(lines), beispiel_bestand(), KAT)
    e = ek.zusammenstellen(pl.bom)
    text = ek.text(e, "Kugelschieber", "21.10.2026")
    assert text.splitlines()[:3] == ["Einkaufsliste Kugelschieber (Stand 21.10.2026)", "", "Lagerware"]
    assert "- [ ] 1 × Stange 1.000 mm: ALFER-Rundrohr 12 × 1, 3,90 € (https://www.alfer.com/)" in text
    assert "- [ ] 4 × Stück: Sechskantmutter ISO 4032 M4, 0,12 €" in text
    assert "\nSumme: ≈ 4,02 €\n\nNormteile abzählen\n- Sechskantmutter ISO 4032 M4: 4 gebraucht, 0 aus Bestand, 4 kaufen" \
        in text
    data = ek.csv(e)
    path = tmp_path / "e.csv"
    path.write_text(data, encoding="utf-8", newline="")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbfGruppe;Menge;") and not raw.startswith(b"\xef\xbb\xbf\xef\xbb\xbf")
    assert raw.endswith(b"\r\n")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:7] == ["Gruppe", "Menge", "Einheit", "Benennung", "Lagerteil", "Preis je (EUR)", "Preis (EUR)"]
    assert rows[1] == ["Lagerware", "1", "Stange 1.000 mm", "ALFER-Rundrohr 12 × 1", ALFER["id"], "3,90", "3,90",
                       "2026-10", "ALFER", "https://www.alfer.com/", rows[1][10]]
    assert ["", "", "", "Summe", "", "", "4,02", "", "", "", ""] in rows
    assert rows[-1][0] == "Normteile abzählen" and rows[-1][10] == "4 gebraucht, 0 aus Bestand, 4 kaufen"
    # nichts zu kaufen
    pl = plane(bom_mit([rohr_line(400, 1)]), beispiel_bestand(), KAT)
    assert pl.bom["einkaufsliste"] == [] and pl.bom["fehlt"] is False and pl.bom["einkauf_summe"] is None
    e = ek.zusammenstellen(pl.bom)
    assert ek.text(e, None) == "Einkaufsliste\nNichts zu kaufen, alles ist im Bestand."
    assert ek.csv(e) == ("\ufeffGruppe;Menge;Einheit;Benennung;Lagerteil;Preis je (EUR);Preis (EUR);Preisstand;"
                         "Bezugsquelle;Link;Hinweis\r\n;;;Summe;;;;;;;\r\n")
    assert ek.zeile_kurz(e) == "Einkaufsliste: nichts zu kaufen, alles aus dem Bestand des Projekts"
    assert quellen_zeilen(pl.bom["cuts"][0]) == ["Rest R-0001 (430 mm): 400; Rest 27 mm Verschnitt"]
    assert ek.dateiname("Kugel/schieber") == "Kugel-schieber-einkaufsliste.csv"


def test_einkaufsliste_mit_zukauf_und_filament_aus_der_stueckliste():
    lines = [rohr_line(400, 1),
             {"pos": 2, "art": "zukaufteil", "stock_id": "alutec-05200", "benennung": "ALUTEC Transportroller 05200",
              "anzahl": 2, "preis_je": 24.99, "preis": 49.98, "hersteller": "ALUTEC", "mpn": "05200",
              "gtin": "4005187052008", "url": "https://www.beispiel-shop.de/p/alutec-05200",
              "preis_stand": "2026-10-21", "eigenteil": False},
             {"pos": 3, "art": "kamerazubehoer", "stock_id": "platte-200pl", "benennung": "Schnellwechselplatte",
              "anzahl": 1, "preis_je": 29.9, "preis": 29.9, "eigenteil": False},
             {"pos": 4, "art": "druckteil", "stock_id": None, "benennung": "Halter", "material": "PETG", "anzahl": 4,
              "kg": 0.048, "preis": 1.2, "eigenteil": False},
             {"pos": 5, "art": "druckteil", "stock_id": None, "benennung": "Clip", "material": "PETG", "anzahl": 1,
              "kg": 0.012, "preis": 0.3, "eigenteil": False},
             {"pos": 6, "art": "eigenteil", "stock_id": None, "benennung": "Kufe", "material": "Stahl", "anzahl": 1,
              "kg": 2.0, "eigenteil": True}]
    pl = plane(bom_mit(lines), beispiel_bestand(), KAT)
    e = ek.zusammenstellen(pl.bom)
    assert [z["gruppe"] for z in e["zeilen"]] == ["Zukaufteile", "Zukaufteile"]
    rolle, platte = e["zukauf"]
    assert (rolle["menge"], rolle["preis"], rolle["link_text"], rolle["hinweis"], rolle["preis_stand"]) == (
        2.0, 49.98, "beispiel-shop.de", "ALUTEC · 05200 · EAN 4005187052008", "2026-10-21")
    assert (platte["link"], platte["hinweis"], platte["preis_stand"]) == (None, None, None)
    assert e["summe"] == pytest.approx(79.88) and e["summe_lager"] is None and e["positionen"] == 2
    assert e["filament"] == [{"werkstoff": "PETG", "material": None, "teile": 5, "gramm": pytest.approx(60.0),
                              "preis": pytest.approx(1.5), "preis_stand": None, "quelle": "stueckliste",
                              "stand": None}]
    text = ek.text(e, "Roller")
    assert "- PETG: 60,0 g für 5 Teile, 1,50 € (Stückliste, Volumen × Dichte)" in text
    assert "- [ ] 1 × Stück: Schnellwechselplatte, 29,90 €" in text
    # Druckvorschau eines anderen Laufs gilt nicht, desselben Laufs schon
    dv = {"run": 7, "stand": "slicer", "summe": {"material": [{"material": "petg", "name": "PETG", "g": 71.25,
                                                               "kosten": 1.21}]},
          "teile": [{"gruppe": "g1", "teile": ["Halter 1", "Halter 2"], "anzahl": 4, "material": "petg"},
                    {"gruppe": "g2", "teile": ["Clip"], "material": "petg"}]}
    assert ek.filament(pl.bom, {**dv, "run": 8})[0]["quelle"] == "stueckliste"
    (f,) = ek.filament(pl.bom, {"druckvorschau": dv})
    assert (f["werkstoff"], f["teile"], f["gramm"], f["preis"], f["stand"]) == ("PETG", 5, 71.25, 1.21, "slicer")
    assert ek.text(ek.zusammenstellen(pl.bom, dv), None).endswith(
        "Filament für Druckteile\n- PETG: 71,3 g für 5 Teile, 1,21 € (Druckvorschau, Bambu Studio)")


def test_verschnitt_definition_2():
    """Sägeschnitte und Reste unter dem Mindestrest, bezogen auf die verplante Länge bzw. Fläche; neue Reste zählen
    nicht. Dieselben Zahlen wie MaterialTests.testVerschnittEinheitlich der App."""
    stange = {"stock_id": "rohr", "art": "stange", "saegeschnitt": 3, "quellen": [
        {"art": "kaufen", "laenge": 1000, "stuecke": [400, 300]},
        {"art": "bestand", "laenge": 1000, "stuecke": [940]}]}
    assert verschnitt_bilanz(stange, 100) == (2000.0, 66.0)
    assert verschnitt_prozent(stange, 100) == 3.3
    # Angabe des Kernels gilt vor dem Mindestrest
    stange["quellen"][0].update({"rest_neu": 294, "verschnitt": True})
    assert verschnitt_bilanz(stange, 100) == (2000.0, 360.0)
    platte = {"stock_id": "platte", "art": "platte", "platte": {"b": 1000, "h": 500}, "quellen": [
        {"art": "kaufen", "b": 1000, "h": 500, "stuecke": [{"b": 400, "h": 500, "x": 0, "y": 0, "gedreht": False}],
         "rest_neu": [{"b": 590, "h": 500, "x": 410, "y": 0}]}]}
    assert verschnitt_prozent(platte, 100) == 1.0
    # ohne Quellen (Zuschnitt ohne Bestand): je Stange gekauft, Standard-Mindestrest 100
    alt = {"stock_id": "rohr", "stangenlaenge": 6000, "saegeschnitt": 3, "stangen": [[882] * 4 + [800] * 3, [800]]}
    assert verschnitt_bilanz(alt) == (12000.0, 75.0) and verschnitt_prozent(alt) == 0.6
    # Rundung wie die App (halbe Werte von der Null weg): 0,25 % → 0,3 %, nicht 0,2 %
    assert verschnitt_prozent({"quellen": [{"laenge": 1000, "stuecke": [997.5], "rest_neu": 0}],
                               "saegeschnitt": 0}, 100) == 0.3
    # im Plan: Rest R-0001 400 + Rest 27 (unter 80) → 3 + 27 von 430 mm
    pl = plane(bom_mit([rohr_line(400, 1)]), beispiel_bestand(), KAT)
    cut = pl.bom["cuts"][0]
    assert cut["verschnitt_prozent"] == 7.0 and cut["verschnitt_definition"] == "2"
    assert pl.bom["verschnitt"] == {"definition": "2", "stangen": 7.0, "platten": None}
    assert zuschnitt_kopf(cut) == "ALFER-Rundrohr 12 × 1: 1 Rest, Verschnitt 7,0 %"


def test_kaputte_bestandsdatei_gibt_hinweis_und_plant_ohne():
    pl = plane(bom_mit([rohr_line(400, 1)]), None, KAT, fehler="bestand.json: kein gültiges JSON")
    assert pl.bom["cuts"][0]["kaufen"] == 1 and pl.bom["fehlt"] is True
    assert any(w.startswith("Bestand: bestand.json: kein gültiges JSON") for w in pl.bom["warnings"])


# ---------------------------------------------------------------------------------------------------------------------
# Datei, Kennungen, Buchungen


def datei(tmp_path, data=None, name="Kugelschieber"):
    proj = tmp_path / name
    proj.mkdir(exist_ok=True)
    d = BestandDatei.fuer_projekt(proj, name, katalog=KAT.item)
    if data is not None:
        d.schreiben(data)
    return d


def test_pfade_je_projekt_und_testvariable(tmp_path, monkeypatch):
    monkeypatch.delenv("KEVCAD_BESTAND_FILE", raising=False)
    p, b = pfade(tmp_path / "A")
    assert p == tmp_path / "A" / "bestand.json" and b == tmp_path / "A" / ".kevcad" / "bestand-buchungen.jsonl"
    monkeypatch.setenv("KEVCAD_BESTAND_FILE", str(tmp_path / "t" / "b.json"))
    p, b = pfade(tmp_path / "A")
    assert p == tmp_path / "t" / "b.json" and b == tmp_path / "t" / "bestand-buchungen.jsonl"


def test_pruefen_mit_klaren_meldungen():
    assert pruefe(beispiel_bestand(), KAT.item) == []
    bad = {"version": 1, "posten": {
        ALFER["id"]: {"ganze": {"anzahl": -1}, "rest": [], "reste": [{"kennung": "X-1", "laenge": 0}]},
        PLATTE["id"]: {"reste": [{"kennung": "R-0009", "laenge": 400}]},
        MUTTER["id"]: {"ganze": {"anzahl": 2}},
        "Gross": {}}}
    errors = pruefe(bad, KAT.item)
    text = "\n".join(errors)
    assert "Posten 'rohr-alfer-12x1': ganze.anzahl muss ≥ 0 sein" in text
    assert "Feld 'rest' unbekannt (erlaubt: ganze, reste, stueck, mindestrest_mm); meinten Sie 'reste'?" in text
    assert "reste[0].laenge muss größer als 0 sein" in text and "kennung fehlt oder hat nicht die Form R-0001" in text
    assert "Plattenreste haben b und h statt laenge" in text
    assert "mutter ist Stückgut; Menge als stueck angeben" in text
    assert "Posten 'Gross': Schlüssel muss eine Katalog-id sein" in text
    dup = beispiel_bestand()
    dup["posten"][PLATTE["id"]] = {"reste": [{"kennung": "P-0001", "b": 1, "h": 1}]}
    dup["posten"][ALFER["id"]]["reste"][1]["kennung"] = "R-0001"
    assert any("Kennung R-0001 steht doppelt" in e for e in pruefe(dup))


def test_atomares_schreiben(tmp_path, monkeypatch):
    d = datei(tmp_path, beispiel_bestand())
    before = d.pfad.read_bytes()
    # ungültig: Datei bleibt, wie sie war
    bad = beispiel_bestand()
    bad["posten"][ALFER["id"]]["ganze"]["anzahl"] = "zwei"
    with pytest.raises(BestandError, match="ganze.anzahl"):
        d.schreiben(bad)
    assert d.pfad.read_bytes() == before
    # Absturz beim Ersetzen: alte Datei bleibt ganz, keine Temp-Dateien
    import kevcad_kernel.bestand.datei as mod

    def kaputt(src, dst):
        raise OSError("Platte voll")

    monkeypatch.setattr(mod.os, "replace", kaputt)
    neu = beispiel_bestand()
    neu["posten"][ALFER["id"]]["ganze"]["anzahl"] = 9
    with pytest.raises(BestandError, match="nicht schreibbar: Platte voll"):
        d.schreiben(neu)
    monkeypatch.undo()
    assert d.pfad.read_bytes() == before and json.loads(before)["posten"][ALFER["id"]]["ganze"]["anzahl"] == 2
    assert [p.name for p in d.pfad.parent.iterdir() if p.name.endswith(".tmp")] == []
    # Buchung, deren Protokoll nicht schreibbar ist, ändert den Bestand nicht
    d.buchungen_pfad.parent.mkdir(parents=True, exist_ok=True)
    d.buchungen_pfad.mkdir()  # ein Ordner statt der Datei
    with pytest.raises(BestandError, match="Buchungsprotokoll"):
        d.buchen("eintrag", [{"op": "ganze", "posten": ALFER["id"], "delta": 1}], von="kevin")
    assert d.pfad.read_bytes() == before


def test_buchen_gebaut_und_rueckgaengig(tmp_path):
    d = datei(tmp_path)
    b1 = d.buchen("eintrag", [{"op": "posten", "posten": ALFER["id"], "vorher": None,
                               "nachher": beispiel_bestand()["posten"][ALFER["id"]]}], von="agent",
                  grund="Kevin: 2 Stangen, Reste 430, 610, 180")
    assert b1["id"] == "B-0001" and b1["zusammenfassung"] == "3 Reste neu (R-0001 430 mm, R-0002 610 mm, " \
                                                              "R-0003 180 mm), 2 ganze Stangen dazu" or \
        b1["zusammenfassung"].startswith("2 ganze Stangen dazu")
    pl = plane(bom_mit(KUGELSCHIEBER), d.lesen(), KAT)
    data = d.lesen()
    ops = gebaut_aenderungen(pl.verbrauch, data, d.kennungen(data), "2026-10-21")
    b2 = d.buchen("gebaut", ops, von="kevin", extra={"run": 7})
    nach = d.lesen()["posten"][ALFER["id"]]
    assert nach["ganze"]["anzahl"] == 0
    neue = pl.bom["cuts"][0]["neue_reste"]
    assert [r["laenge"] for r in nach["reste"]] == neue
    assert [r["kennung"] for r in nach["reste"]] == [f"R-{4 + i:04d}" for i in range(len(neue))]
    assert b2["zusammenfassung"].startswith("3 Reste weg, 2 ganze Stangen weg")
    assert "Rest neu (R-0004 244 mm)" in b2["zusammenfassung"] or "Reste neu (R-0004" in b2["zusammenfassung"]
    # rückgängig: alles wie vorher
    b3 = d.rueckgaengig("B-0002", von="kevin")
    assert b3["art"] == "rueckgaengig" and b3["bezug"] == "B-0002"
    assert d.lesen() == data
    rows = d.buchungen()
    assert [r["id"] for r in rows] == ["B-0003", "B-0002", "B-0001"]
    assert rows[1]["rueckgaengig_durch"] == "B-0003" and rows[0]["rueckgaengig_durch"] is None
    with pytest.raises(BestandError, match="schon rückgängig gemacht"):
        d.rueckgaengig("B-0002")
    # Kennungen werden nicht wiederverwendet, auch wenn die Reste wieder weg sind
    assert d.kennungen().neu(False) == f"R-{4 + len(neue):04d}"
    # Konflikt: Eintrag rückgängig, nachdem der Posten sich geändert hat
    d.buchen("korrektur", [{"op": "ganze", "posten": ALFER["id"], "delta": 1}], von="kevin")
    with pytest.raises(BestandError, match="inzwischen geändert"):
        d.rueckgaengig("B-0001")
    # feine Änderungen lassen sich einzeln umkehren
    op = {"op": "rest_weg", "posten": ALFER["id"], "rest": {"kennung": "R-0002", "laenge": 610}}
    assert umkehren(op)["op"] == "rest_neu" and umkehren(umkehren(op)) == op
    with pytest.raises(BestandError, match="nicht mehr im Bestand"):
        anwenden({"posten": {}}, op)
    assert zusammenfassung([]) == "keine Änderung"


def test_bestand_je_projekt_ohne_einfluss_auf_andere(tmp_path):
    a = datei(tmp_path, beispiel_bestand(), "Kugelschieber")
    b = datei(tmp_path, {"version": 1, "posten": {ALFER["id"]: {"ganze": {"anzahl": 1, "laenge": 1000}}}}, "Regal")
    pa = plane(bom_mit(KUGELSCHIEBER), a.lesen(), KAT)
    pb = plane(bom_mit([rohr_line(400, 2)]), b.lesen(), KAT)
    assert pa.bom["cuts"][0]["aus_bestand"] == {"reste": 3, "ganze": 2}
    assert pb.bom["cuts"][0]["aus_bestand"] == {"reste": 0, "ganze": 1} and pb.bom["fehlt"] is False
    assert not any("Projekt" in (k.get("hinweis") or "") and "Regal" in (k.get("hinweis") or "")
                   for k in pa.bom["einkaufsliste"])
    data = a.lesen()
    a.buchen("gebaut", gebaut_aenderungen(pa.verbrauch, data, a.kennungen(data), "2026-10-21"), von="kevin")
    assert b.lesen()["posten"][ALFER["id"]]["ganze"]["anzahl"] == 1  # das andere Projekt bleibt unberührt
    assert not b.buchungen_pfad.exists() and a.buchungen_pfad.exists()
    assert a.buchungen_pfad == tmp_path / "Kugelschieber" / ".kevcad" / "bestand-buchungen.jsonl"


def test_kaputtes_json_klare_meldung(tmp_path):
    d = datei(tmp_path)
    d.pfad.write_text('{"version": 1, "posten": {', encoding="utf-8")
    with pytest.raises(BestandError, match=r"bestand.json: kein gültiges JSON \(Zeile 1"):
        d.lesen()
    os.remove(d.pfad)
    assert d.lesen()["posten"] == {} and d.stand() is None


def test_halbe_zeile_im_protokoll_wird_uebersprungen(tmp_path):
    d = datei(tmp_path, beispiel_bestand())
    d.buchen("korrektur", [{"op": "ganze", "posten": ALFER["id"], "delta": -1}], von="kevin")
    with open(d.buchungen_pfad, "a", encoding="utf-8") as f:
        f.write('{"id": "B-0002", "zeit": ')
    assert [b["id"] for b in d.buchungen()] == ["B-0001"]
    assert d.buchen("korrektur", [{"op": "ganze", "posten": ALFER["id"], "delta": 1}], von="kevin")["id"] == "B-0002"


def test_beispiel_zahlen_fuer_den_bericht(capsys):
    """Das Beispiel aus dem Auftrag (ALFER 12 × 1, Kugelschieber) mit allen Zahlen."""
    pl = plane(bom_mit(KUGELSCHIEBER), beispiel_bestand(), KAT)
    cut = pl.bom["cuts"][0]
    print("\n".join(quellen_zeilen(cut)))
    print(ek.text(ek.zusammenstellen(pl.bom), "Kugelschieber"))
    print(pl.statistik)
    assert Path(__file__).exists()
