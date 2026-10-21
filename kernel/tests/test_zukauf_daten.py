"""Zukaufteile ohne build123d: Shop-Auswertung der Beispielseiten (JSON-LD, Microdata, Open Graph), Einträge prüfen
und zusammensetzen, Maße und Preise aus Text, Normteil-Erkennung, Bezugspunkte, Katalog mit art "zukaufteil"."""

import json
from pathlib import Path

import pytest

from kevcad_kernel.bezugspunkte import pruefen_punkt
from kevcad_kernel.catalog import Catalog, CatalogError
from kevcad_kernel.zukauf import eintrag as ze
from kevcad_kernel.zukauf.normteile import erkennen, umleiten
from kevcad_kernel.zukauf.shopdaten import auswerten

HERE = Path(__file__).resolve().parent
DATEN = HERE / "zukauf_testdaten"
TEST_CATALOG = HERE / "katalog_test"


def seite(name: str) -> str:
    return (DATEN / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- Shop-Seiten


def test_jsonld_baumarkt():
    res = auswerten(seite("obi_muster.html"), "https://www.baumarkt-muster.example/p/7654321")
    f = res["felder"]
    assert res["quellen"] == ["json-ld"] and res["zu_pruefen"] == []
    assert f["hersteller"] == "ALUTEC" and f["mpn"] == "05200" and f["gtin"] == "4014688052004"
    assert f["shop_nr"] == "7654321" and f["bild"].endswith("05200-1.jpg")
    assert f["preis"] == {"je_stueck": 24.99, "waehrung": "EUR", "brutto": True}
    assert f["masse"] == {"l": 610.0, "b": 410.0, "h": 128.0} and f["gewicht"] == 1800.0
    entry, notes = ze.entwurf({k: v for k, v in f.items() if k != "beschreibung"}, url=f["url"])
    assert entry["id"] == "alutec-05200" and entry["ersatz"] == {"form": "quader",
                                                                 "masse": {"l": 610.0, "b": 410.0, "h": 128.0}}
    assert entry["preis"]["quelle"] == f["url"] and entry["preis"]["stand"] == ze.heute()
    assert ze.validate_zukauf(entry) == [] and notes == []


def test_microdata_hersteller():
    res = auswerten(seite("igus_muster.html"), "https://www.kunststoff-muster.example/gfm")
    f = res["felder"]
    assert res["quellen"] == ["microdata"]
    assert f["hersteller"] == "igus" and f["mpn"] == "GFM-1012-10" and "gtin" not in f
    assert f["preis"] == {"je_stueck": 0.86, "waehrung": "EUR", "brutto": False}
    assert f["masse"]["d"] == 18.0  # größter Außendurchmesser, nicht der Innendurchmesser
    assert "Maße aus dem Seitentext gelesen: bitte prüfen" in res["hinweise"]


def test_opengraph_industrie():
    res = auswerten(seite("mcmaster_muster.html"), None)
    f = res["felder"]
    assert res["quellen"] == ["opengraph"]
    assert f["shop_nr"] == "91251A540" and f["url"] == "https://www.industrial-muster.example/91251A540/"
    assert f["masse"] == {"l": 25.4, "d": 9.525}  # Zoll in mm
    assert "Hersteller" in res["zu_pruefen"] and "Preis" in res["zu_pruefen"]


def test_ohne_strukturierte_daten():
    res = auswerten(seite("ohne_daten.html"), "https://x.example/deckel")
    assert res["quellen"] == [] and res["felder"]["masse"] == {"l": 600.0, "b": 400.0, "h": 20.0}
    assert res["felder"]["name"] == "Deckel 05090"
    assert any("Keine strukturierten Produktdaten" in h for h in res["hinweise"])
    assert auswerten("", None)["hinweise"] == ["Kein HTML übergeben"]


# ------------------------------------------------------------------------------------------------- Text und Zahlen


@pytest.mark.parametrize("text, masse", [
    ("Maße (L x B x H): 61 x 41 x 12,8 cm", {"l": 610, "b": 410, "h": 128}),
    ("610 × 410 × 128 mm", {"l": 610, "b": 410, "h": 128}),
    ("Ø 70 x 1600 mm", {"d": 70, "l": 1600}),
    ("Länge: 1.600 mm, Durchmesser 70 mm", {"l": 1600, "d": 70}),
    ('1/4"-20 Thread, 1" Long, diameter 0.375 in', {"l": 25.4, "d": 9.525}),
    ("Höhe ca. 12,8 cm inkl. Rollen", {"h": 128}),
    ("Paket mit 3 x 2 Stück", {}),
])
def test_masse_aus_text(text, masse):
    assert ze.masse_aus_text(text) == pytest.approx(masse)


def test_zahlen_preise_gtin():
    assert ze.laenge_mm("12,8 cm") == 128 and ze.laenge_mm('1/4"') == pytest.approx(6.35)
    assert ze.laenge_mm("1.600 mm") == 1600 and ze.laenge_mm("1.6 m") == 1600
    assert ze.gewicht_g("1,8 kg") == 1800 and ze.gewicht_g("640 g") == 640 and ze.gewicht_g("14 lb") == \
        pytest.approx(6350.3, rel=1e-4)
    assert ze.preis_aus_text("24,99 €") == (24.99, "EUR") and ze.preis_aus_text("EUR 1.299,00") == (1299.0, "EUR")
    assert ze.preis_aus_text("$12.50") == (12.5, "USD")
    assert ze.gtin_ok("4014688052004") and not ze.gtin_ok("4014688052005") and ze.gtin_ok("4008332778051")
    assert ze.gtin_ok("4005187052008") and not ze.gtin_ok("4005187052009")  # Beispiel aus KATALOG.md
    assert ze.make_id("Happy People", "77805") == "happy-people-77805"
    assert ze.make_id(None, None, "4014688052004") == "gtin-4014688052004"
    assert ze.eingabe_art("https://x.example/p") == "url" and ze.eingabe_art("4014688052004") == "gtin"
    assert ze.eingabe_art("05200") == "mpn"


def test_entwurf_aus_dialog_und_text():
    entry, notes = ze.entwurf({"marke": "ALUTEC", "artikelnummer": 5200, "ean": "4014-6880-52004",
                               "masse": "61 x 41 x 12,8 cm", "preis": "24,99 €", "gewicht": "1,8 kg",
                               "titel": "Transportroller"})
    assert entry["hersteller"] == "ALUTEC" and entry["mpn"] == "5200" and entry["gtin"] == "4014688052004"
    assert entry["masse"] == {"l": 610, "b": 410, "h": 128} and entry["gewicht"] == 1800
    assert entry["preis"]["je_stueck"] == 24.99 and entry["preis"]["waehrung"] == "EUR"
    assert any("brutto oder netto" in n for n in notes) and ze.zu_pruefen(entry) == ["Preis brutto oder netto"]
    assert ze.validate_zukauf(entry) == []


def test_validate_meldet_alles():
    errors = ze.validate_zukauf({"id": "X Y", "art": "zukaufteil", "gtin": "4014688052005", "masse": {"l": 1},
                                 "preis": {"je_stueck": -1, "brutto": "ja", "stand": "21.10.2026"},
                                 "cad": {"quelle": "skript", "datei": "/abs/pfad.py"},
                                 "ersatz": {"form": "kugel"}, "bezugspunkte": {"oben": {"pos": [0, 0]}}})
    text = "\n".join(errors)
    for part in ("id nur aus Kleinbuchstaben", "name fehlt", "mpn (Herstellernummer) fehlt", "Prüfziffer stimmt nicht",
                 "masse braucht l, b und h", "preis.je_stueck", "preis.brutto", "preis.stand", "cad.funktion fehlt",
                 "nicht absolut", "ersatz.form", "pos als [x, y, z]"):
        assert part in text, part


def test_bezugspunkte_pruefen():
    assert pruefen_punkt({"pos": [0, 0, 1], "richtung": [0, 1, 0], "hinweis": "x"}, "P") == []
    assert pruefen_punkt({"pos": [0, 0, 1], "richtung": [0, 0, 0]}, "P") == ["P: richtung darf nicht [0, 0, 0] sein"]
    assert "parallel" in pruefen_punkt({"richtung": [0, 0, 1], "x_richtung": [0, 0, 2]}, "P")[0]


# ------------------------------------------------------------------------------------------------------ Normteile


@pytest.mark.parametrize("text, art, norm, groesse, laenge, werkstoff", [
    ("ISO 4762 M6×20", "schraube", "iso4762", "M6", 20, None),
    ("Zylinderschraube DIN 912 M8 x 40 A2", "schraube", "iso4762", "M8", 40, "a2"),
    ("Sechskantmutter DIN 934 M10", "mutter", "iso4032", "M10", None, None),
    ("Unterlegscheibe DIN 125 M6 Edelstahl", "scheibe", "iso7089", "M6", None, "a2"),
    ("ISO 4762 M8-1.25x30", "schraube", "iso4762", "M8", 30, None),
])
def test_normteil_erkennen(text, art, norm, groesse, laenge, werkstoff):
    info = erkennen(text)
    assert (info["art"], info["norm"], info["groesse"], info["laenge"], info["werkstoff"]) == (
        art, norm, groesse, laenge, werkstoff)


def test_normteil_umleiten():
    cat = Catalog(TEST_CATALOG, Path("/nicht/da"), None)
    assert erkennen("ALUTEC 05200") is None and umleiten("Transportroller 05200", cat) is None
    red = umleiten("ISO 4762 M8x40", cat)
    assert red["stock_id"] == "schraube-iso4762-m8" and "laenge=40" in red["beispiel"]
    assert "kein Download nötig" in red["text"].replace("Kein Zukaufteil und kein Download nötig", "kein Download nötig")
    red = umleiten("DIN 912 M5x16", cat)  # fehlt im Test-Katalog, gibt es in bd_warehouse
    assert red["stock_id"] is None and red["vorschlag"]["masse"] == {"typ": "SocketHeadCapScrew", "norm": "iso4762",
                                                                     "groesse": "M5-0.8"}
    assert "stock_define" in red["text"]


# --------------------------------------------------------------------------------------------- Katalog-Ebenen


def test_katalog_zukaufteil_laden_und_vorschlag(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    good = {"id": "alutec-05200", "art": "zukaufteil", "name": "Rollwagen", "hersteller": "ALUTEC", "mpn": "05200",
            "masse": {"l": 610, "b": 410, "h": 128}}
    bad = {"id": "kaputt", "art": "zukaufteil", "name": "Kaputt", "masse": {"l": 1}}
    (proj / "katalog.json").write_text(json.dumps({"version": 1, "teile": [good, bad]}), encoding="utf-8")
    cat = Catalog(TEST_CATALOG, tmp_path / "eigen", proj)
    it = cat.item("alutec-05200")
    assert it["ebene"] == "projekt" and it["status"] == "frei"
    assert cat.item("kaputt") is None and any("kaputt" in w for w in cat.warnings)
    assert not any("Material None" in w for w in cat.warnings)  # Material ist bei Zukaufteilen optional
    hits, _ = cat.search("alutec 05200")
    assert [h["id"] for h in hits] == ["alutec-05200"]
    # Vorschlag von Claude in den eigenen Katalog, Freigabe durch Kevin
    saved, path, _ = cat.save("teil", {**good, "id": "alutec-05090", "mpn": "05090"}, "eigen", proposal=True)
    assert saved["status"] == "vorgeschlagen" and path.name == "eigene.json"
    with pytest.raises(CatalogError, match="freigegeben"):
        cat.save("teil", good, "projekt", proposal=True)
    saved, _, _ = cat.save("teil", {**saved, "status": "frei"}, "eigen")
    assert cat.item("alutec-05090")["status"] == "frei"
    with pytest.raises(CatalogError, match="Material 'gibtsnicht' gibt es im Katalog nicht"):
        cat.save("teil", {**good, "id": "x-1", "material": "gibtsnicht"}, "projekt")
