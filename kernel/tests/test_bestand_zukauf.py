"""Zukaufteile als Stückgut im Bestand (Strang „Feinschliff 2“, Punkt 1): ``bestand_eintragen`` mit ``stueck`` für
Zukaufteile, Kameras und Objektive, Abgleich in der Planung (``BOM.zukauf_bestand``), Einkaufsliste ohne das, was Kevin
hat, und „Gebaut“ zieht es ab. Ohne Laufzeit: das Mixin mit kleinem Katalog und echter Bestandsdatei."""

import threading
from pathlib import Path

import pytest

from kevcad_kernel.bestand import einkauf as ek
from kevcad_kernel.bestand import gebaut_aenderungen, plane
from kevcad_kernel.bestand.anbindung import BestandAnbindung

# Die Arten aus Kevins Katalog, an denen der Fehler gemeldet wurde (Variante B des Kugelschiebers)
ZUKAUF = {
    "senkschraube-3-8-16-unc-1-2": {"art": "zukaufteil", "name": "Senkschraube 3/8\"-16 UNC × 1/2\""},
    "blackmagic-pocket-6k-pro": {"art": "kamera", "name": "Blackmagic Pocket Cinema Camera 6K Pro"},
    "sigma-18-35-f1.8-art-ef": {"art": "objektiv", "name": "Sigma 18-35 mm F1.8 DC HSM Art (EF)"},
    "alutec-05200": {"art": "zukaufteil", "name": "ALUTEC Transportroller 05200"},
    "manfrotto-mvh502ah": {"art": "zukaufteil", "name": "Manfrotto MVH502AH"},
    "bowlingball-usbc": {"art": "zukaufteil", "name": "Bowlingball USBC"},
    "rig-platte": {"art": "kamerazubehoer", "name": "Schnellwechselplatte"},
}
ITEMS = {k: {"id": k, **v} for k, v in ZUKAUF.items()}
ITEMS["rohr-alfer-12x1"] = {"id": "rohr-alfer-12x1", "art": "rohr", "name": "ALFER-Rundrohr 12 × 1",
                            "masse": {"d": 12, "s": 1}, "stangenlaenge": 1000, "preis": {"je_m": 3.9}}
ITEMS["mutter-iso4032-m4"] = {"id": "mutter-iso4032-m4", "art": "mutter", "name": "Sechskantmutter M4"}


class Katalog:
    def item(self, iid):
        return ITEMS.get(iid)

    def material(self, mid):
        return None

    def item_ids(self):
        return list(ITEMS)

    def search(self, q, limit=3):
        return [], 0


class Projekt:
    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.output_dir = path / "output"


class Laufzeit(BestandAnbindung):
    def __init__(self, tmp: Path):
        self._lock = threading.RLock()
        self._project = Projekt(tmp)
        self.catalog = Katalog()
        self._bom = None
        self.gesendet: list[dict] = []
        self._bestand_init()

    def _send_app(self, msg):
        self.gesendet.append(msg)

    def _log(self, text):
        pass


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.delenv("KEVCAD_BESTAND_FILE", raising=False)
    proj = tmp_path / "Kugelschieber"
    proj.mkdir()
    return Laufzeit(proj)


@pytest.mark.parametrize("sid", sorted(ZUKAUF))
def test_zukaufteile_mit_stueck_eintragen(rt, sid):
    res = rt.bestand_eintragen(sid, stueck=1, grund="Kevin: habe ich")
    assert res["ok"], res
    assert res["posten"] == {"stueck": [{"anzahl": 1}]}
    assert res["aenderungen_text"] and "1 Stück" in " ".join(res["aenderungen_text"])
    # ganze bleibt falsch, aber mit einer Meldung, die zu stueck passt
    res = rt.bestand_eintragen(sid, ganze=1, grund="Kevin: habe ich")
    assert res["ok"] is False and "Stückgut: Menge mit stueck angeben" in res["error"]


def test_lagerware_bleibt_ganze_und_reste(rt):
    res = rt.bestand_eintragen("rohr-alfer-12x1", stueck=1, grund="x")
    assert res["ok"] is False and "ganzen und Resten" in res["error"]
    assert rt.bestand_eintragen("rohr-alfer-12x1", ganze=1, grund="x")["ok"]
    assert rt.bestand_eintragen("mutter-iso4032-m4", stueck=10, grund="x")["ok"]


def zukauf_line(pos, sid, anzahl, preis_je=None, **extra):
    return {"pos": pos, "art": ITEMS[sid]["art"], "stock_id": sid, "benennung": ITEMS[sid]["name"], "anzahl": anzahl,
            "preis_je": preis_je, "preis": preis_je * anzahl if preis_je is not None else None, "eigenteil": False,
            **extra}


LINES = [zukauf_line(1, "alutec-05200", 4, 24.99, hersteller="ALUTEC", mpn="05200"),
         zukauf_line(2, "blackmagic-pocket-6k-pro", 1, 1990.0),
         zukauf_line(3, "sigma-18-35-f1.8-art-ef", 1, 699.0),
         zukauf_line(4, "bowlingball-usbc", 1, 89.9),
         zukauf_line(5, "manfrotto-mvh502ah", 1, None),
         zukauf_line(6, "senkschraube-3-8-16-unc-1-2", 2, 0.8)]


def bom(lines=LINES):
    return {"run": 3, "lines": [dict(ln) for ln in lines], "cuts": [], "totals": {}, "warnings": []}


def test_planung_und_einkaufsliste_mit_zukaufteilen_im_bestand():
    best = {"version": 1, "posten": {"alutec-05200": {"stueck": [{"anzahl": 1}]},
                                     "blackmagic-pocket-6k-pro": {"stueck": [{"anzahl": 1}]},
                                     "sigma-18-35-f1.8-art-ef": {"stueck": [{"anzahl": 1}]},
                                     "manfrotto-mvh502ah": {"stueck": [{"anzahl": 2}]},
                                     "senkschraube-3-8-16-unc-1-2": {"stueck": [{"anzahl": 2}]}}}
    pl = plane(bom(), best, Katalog())
    zb = {z["stock_id"]: (z["anzahl"], z["aus_bestand"], z["kaufen"]) for z in pl.bom["zukauf_bestand"]}
    assert zb == {"alutec-05200": (4, 1, 3), "blackmagic-pocket-6k-pro": (1, 1, 0), "sigma-18-35-f1.8-art-ef": (1, 1, 0),
                  "bowlingball-usbc": (1, 0, 1), "manfrotto-mvh502ah": (1, 1, 0),
                  "senkschraube-3-8-16-unc-1-2": (2, 2, 0)}
    # Zukaufteile bleiben in ihrer Gruppe, nicht unter Lagerware oder Normteilen
    assert pl.bom["einkaufsliste"] == [] and pl.bom["stueckgut"] == []
    e = ek.zusammenstellen(pl.bom)
    assert [(z["id"], z["menge"], z["preis"]) for z in e["zukauf"]] == [
        ("alutec-05200", 3.0, pytest.approx(74.97)), ("bowlingball-usbc", 1.0, 89.9)]
    assert e["zukauf"][0]["hinweis"] == "ALUTEC · 05200 · Bestand im Projekt: 1, gebraucht: 4"
    assert e["zukauf"][1]["hinweis"] is None
    assert [z["stock_id"] for z in e["zukauf_aus_bestand"]] == [
        "alutec-05200", "blackmagic-pocket-6k-pro", "sigma-18-35-f1.8-art-ef", "manfrotto-mvh502ah",
        "senkschraube-3-8-16-unc-1-2"]
    assert e["summe"] == pytest.approx(74.97 + 89.9) and e["positionen"] == 2
    text = ek.text(e, "Kugelschieber", "22.10.2026")
    assert "- [ ] 3 × Stück: ALUTEC Transportroller 05200, 74,97 €\n  ALUTEC · 05200 · Bestand im Projekt: 1, gebraucht: 4" \
        in text
    assert "Blackmagic" not in text and "Sigma" not in text
    # „Gebaut“ zieht die verplanten Zukaufteile ab
    ops = gebaut_aenderungen(pl.verbrauch, best, None, "2026-10-22")
    assert sorted((o["posten"], o["delta"]) for o in ops) == sorted(
        [("alutec-05200", -1), ("blackmagic-pocket-6k-pro", -1), ("sigma-18-35-f1.8-art-ef", -1),
         ("manfrotto-mvh502ah", -1), ("senkschraube-3-8-16-unc-1-2", -2)])


def test_ohne_bestand_alles_kaufen_und_ohne_feld_wie_bisher():
    pl = plane(bom(), None, Katalog())
    assert all(z["aus_bestand"] == 0 for z in pl.bom["zukauf_bestand"])
    e = ek.zusammenstellen(pl.bom)
    assert [z["menge"] for z in e["zukauf"]] == [4.0, 1.0, 1.0, 1.0, 1.0, 2.0] and e["zukauf_aus_bestand"] == []
    alt = bom()  # älterer Kernel ohne zukauf_bestand: die ganze Anzahl
    assert [z["menge"] for z in ek.zusammenstellen(alt)["zukauf"]] == [4.0, 1.0, 1.0, 1.0, 1.0, 2.0]


def test_ueber_die_laufzeit_eintragen_und_einkaufsliste(rt):
    for sid, n in (("blackmagic-pocket-6k-pro", 1), ("alutec-05200", 2)):
        assert rt.bestand_eintragen(sid, stueck=n, grund=f"Kevin: {n} vorhanden")["ok"]
    rt._bom = rt._bestand_bom(bom())
    res = rt.einkaufsliste()
    assert res["ok"], res
    assert [(z["id"], z["menge"]) for z in res["zukauf"]] == [
        ("alutec-05200", 2.0), ("sigma-18-35-f1.8-art-ef", 1.0), ("bowlingball-usbc", 1.0),
        ("manfrotto-mvh502ah", 1.0), ("senkschraube-3-8-16-unc-1-2", 2.0)]
    assert [z["stock_id"] for z in res["zukauf_aus_bestand"]] == ["alutec-05200", "blackmagic-pocket-6k-pro"]
    assert "Blackmagic" not in res["text"]
    assert Path(res["csv"]).exists()
