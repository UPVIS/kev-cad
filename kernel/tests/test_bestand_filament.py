"""Filament im Bestand (Strang „Bestand Stufe 2“, PLAN-BESTAND.md S2, BESTAND.md „Filament“): Spulen eintragen,
Planung (``BOM.filament_bestand``), Einkaufsliste auf ganze Spulen gerundet gegen die Druckvorschau desselben Laufs,
„Gedruckt“ und „Gebaut“ buchen das Filament ab, alles umkehrbar. Ohne Laufzeit: das Mixin mit dem Beispielkatalog,
einer echten Bestandsdatei und einer Druckvorschau wie ``protocol.druckvorschau_beispiel``."""

import copy
import json
import sys
import threading
from pathlib import Path

import pytest

from kevcad_kernel.bestand import einkauf as ek
from kevcad_kernel.bestand import filament as fl
from kevcad_kernel.bestand import plane
from kevcad_kernel.bestand.anbindung import BestandAnbindung
from kevcad_kernel.bestand.datei import BestandDatei, Kennungen, anwenden, hoechste_kennungen, pruefe, umkehren
from kevcad_kernel.protocol import druckvorschau_beispiel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import bestand_beispiel as bb  # noqa: E402


class Projekt:
    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.output_dir = path / "output"


class Katalog(bb.Katalog):
    """Beispielkatalog plus ein nicht druckbares Material und TPU mit eigener Spulengröße."""

    EXTRA = {"tpu-95a": {"id": "tpu-95a", "name": "TPU 95A", "gruppe": "Kunststoff", "dichte": 1.21,
                         "preis_je_kg": 28.0, "preis_stand": "2026-10", "druckbar": True, "spule_g": 750},
             "messing": {"id": "messing", "name": "Messing", "gruppe": "Buntmetall", "dichte": 8.47}}

    def material(self, mid):
        return copy.deepcopy(self.EXTRA[mid]) if mid in self.EXTRA else super().material(mid)

    def find_material(self, name, include_proposed=False):
        key = str(name or "").strip().lower()
        for m in self.EXTRA.values():
            if key in (m["id"], m["name"].lower()):
                return copy.deepcopy(m)
        return super().find_material(name, include_proposed)


class Laufzeit(BestandAnbindung):
    def __init__(self, tmp: Path):
        self._lock = threading.RLock()
        self._project = Projekt(tmp)
        self.catalog = Katalog()
        self._bom = None
        self.gesendet: list[dict] = []
        self._dv_lock = threading.RLock()
        self._dv_vorschau = None
        self._bestand_init()

    def _dv_aktuell(self, warten_s):
        with self._dv_lock:
            return self._dv_vorschau

    def _send_app(self, msg):
        self.gesendet.append(msg)

    def _log(self, text):
        pass

    def rechnen(self, run=5):
        """Wie nach einem Lauf: Stückliste planen, Druckvorschau desselben Laufs."""
        self._bom = self._bestand_bom(bb.material_bom(run=run))
        with self._dv_lock:
            self._dv_vorschau = druckvorschau_beispiel(run=run)
        return self._bom


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.delenv("KEVCAD_BESTAND_FILE", raising=False)
    proj = tmp_path / "Kugelschieber"
    proj.mkdir()
    return Laufzeit(proj)


def spulen(rt):
    return json.loads((rt._project.path / "bestand.json").read_text()).get("filament")


# ---------------------------------------------------------------------------------------------------------------------
# Datei


def test_datei_prueft_spulen():
    ok = {"version": 1, "posten": {}, "filament": copy.deepcopy(bb.FILAMENT_BESTAND)}
    assert pruefe(ok) == []
    assert pruefe({"version": 1, "posten": {}, "filament": []}) == []
    falsch = copy.deepcopy(ok)
    falsch["filament"][1]["kennung"] = "S-0001"
    falsch["filament"].append({"kennung": "R-0001", "material": "petg", "gramm": 10, "farbe": 3, "dicke": 1.75})
    falsch["filament"].append({"kennung": "S-0009", "material": "petg", "gramm": 2000, "gramm_voll": 1000})
    fehler = "\n".join(pruefe(falsch))
    assert "Spule S-0001 steht doppelt" in fehler
    assert "kennung fehlt oder hat nicht die Form S-0001" in fehler
    assert "kennt nur kennung" in fehler and "farbe muss Text sein" in fehler
    assert "mehr als anderthalb volle Spulen" in fehler
    assert "filament muss eine Liste" in pruefe({"version": 1, "filament": {"petg": 3}})[0]


def test_spulen_aendern_umkehren_und_kennungen():
    data = {"version": 1, "posten": {}, "filament": copy.deepcopy(bb.FILAMENT_BESTAND)}
    ops = [{"op": "spule_gramm", "kennung": "S-0001", "material": "petg", "delta": -120},
           {"op": "spule", "kennung": "S-0001", "vorher": {**bb.FILAMENT_BESTAND[0], "gramm": 0}, "nachher": None},
           {"op": "spule", "kennung": "S-0003", "vorher": None,
            "nachher": {"kennung": "S-0003", "material": "petg", "gramm": 931.2, "gramm_voll": 1000}}]
    for op in ops:
        anwenden(data, op)
    assert [s["kennung"] for s in data["filament"]] == ["S-0002", "S-0003"]
    for op in reversed(ops):
        anwenden(data, umkehren(op))
    assert data["filament"] == bb.FILAMENT_BESTAND
    # Kennungen laufen über Bestand und Buchungen weiter (eine leere Spule gibt ihre Nummer nicht frei)
    k = Kennungen(hoechste_kennungen({"filament": []}, [{"aenderungen": ops}]))
    assert k.spule() == "S-0004" and k.neu(False) == "R-0001"
    with pytest.raises(ValueError, match="nur noch 310 g"):
        anwenden(data, {"op": "spule_gramm", "kennung": "S-0002", "delta": -400})


# ---------------------------------------------------------------------------------------------------------------------
# Eintragen


def test_spulen_eintragen_aendern_entfernen(rt):
    res = rt.bestand_eintragen(material="PETG", gramm=640, spule="Bambu PETG Basic schwarz", farbe="schwarz",
                               hersteller="Bambu Lab", ort="Regal 3", grund="Kevin: angebrochene PETG-Spule, 640 g")
    assert res["ok"], res
    assert res["buchung"]["art"] == "eintrag" and res["buchung"]["zusammenfassung"] == "1 Spule neu (S-0001 640 g)"
    assert res["aenderungen_text"] == ["Filament PETG: Spule S-0001 Bambu PETG Basic schwarz, 640 von 1000 g, "
                                       "Regal 3 dazu"]
    (s1,) = spulen(rt)
    assert s1 == {"kennung": "S-0001", "material": "petg", "gramm": 640, "gramm_voll": 1000,
                  "name": "Bambu PETG Basic schwarz", "hersteller": "Bambu Lab", "farbe": "schwarz", "ort": "Regal 3",
                  "seit": s1["seit"]}
    # zwei volle Spulen auf einmal; Spulengröße aus dem Katalog (TPU 750 g)
    res = rt.bestand_eintragen(material="tpu-95a", anzahl=2, grund="Kevin: zwei neue TPU-Spulen")
    assert res["ok"] and [(s["kennung"], s["gramm"], s["gramm_voll"]) for s in spulen(rt)[1:]] == [
        ("S-0002", 750, 750), ("S-0003", 750, 750)]
    # ändern über die Kennung, entfernen
    res = rt.bestand_eintragen(kennung="S-0001", gramm=310.5, ort="Drucker", grund="Kevin: nur noch 310 g")
    assert res["ok"] and res["buchung"]["art"] == "korrektur"
    assert res["aenderungen_text"] == ["Filament PETG: Spule S-0001 640 g → 310,5 g, Ort Regal 3 → Drucker"]
    res = rt.bestand_eintragen(spulen_entfernen=["S-0003"], grund="Kevin: eine TPU-Spule ist weg")
    assert res["ok"] and res["buchung"]["zusammenfassung"] == "1 Spule weg (S-0003)"
    assert [s["kennung"] for s in spulen(rt)] == ["S-0001", "S-0002"]
    # Rückgängig stellt die Spule wieder her; die Kennung wird nicht neu vergeben
    assert rt.buchung_rueckgaengig(res["buchung"]["id"])["ok"]
    assert [s["kennung"] for s in spulen(rt)] == ["S-0001", "S-0002", "S-0003"]
    res = rt.bestand_eintragen(material="petg", gramm=1000, grund="Kevin: neue PETG-Spule")
    assert spulen(rt)[-1]["kennung"] == "S-0004"
    # BESTAND und neue BOM gehen an die App
    assert any(m.get("type") == "BESTAND" for m in rt.gesendet)


@pytest.mark.parametrize("args, fehler", [
    ({"material": "messing", "gramm": 100}, "kein Druckmaterial"),
    ({"material": "gibtsnicht", "gramm": 100}, "gibt es im Katalog nicht"),
    ({"stock_id": "rohr-alfer-12x1", "material": "petg", "gramm": 100}, "nicht beides"),
    ({"kennung": "S-0042", "gramm": 100}, "Spule S-0042 gibt es nicht"),
    ({"gramm": 100}, "Für eine neue Spule material angeben"),
    ({"material": "petg", "gramm": 0}, "gramm muss größer als 0"),
    ({"material": "petg", "anzahl": 0, "gramm": 50}, "anzahl=0"),
    ({"spulen_entfernen": ["S-0001"]}, "Spule S-0001 gibt es nicht"),
    ({"stock_id": "rohr-alfer-12x1", "ort": "Regal 2", "reste": [430]}, "ort gilt hier nur für Filamentspulen"),
])
def test_eintragen_fehler(rt, args, fehler):
    res = rt.bestand_eintragen(grund="x", **args)
    assert res["ok"] is False and fehler in res["error"], res
    assert not (rt._project.path / "bestand.json").exists()


def test_filament_fuehren_ohne_spule(rt):
    res = rt.bestand_eintragen(material="petg", anzahl=0, grund="Kevin: kein Filament für dieses Projekt da")
    assert res["ok"] and res["buchung"]["zusammenfassung"] == "Filament wird geführt"
    assert spulen(rt) == []
    assert "Keine Änderung" in rt.bestand_eintragen(material="petg", anzahl=0, grund="x")["error"]
    text = rt.bestand_liste()["text"]
    assert "Filament:\n- keine Spule (Filament wird geführt" in text
    # ohne Spule: alles Filament der Druckvorschau steht auf der Einkaufsliste
    bom = rt.rechnen()
    e = ek.zusammenstellen(bom, druckvorschau_beispiel(run=5))
    assert [(z["id"], z["menge"], z["einheit"], z["hinweis"]) for z in e["filament_kauf"]] == [
        ("petg", 1.0, "Spule 1.000 g", "Bedarf 188,8 g, kein Filament im Bestand des Projekts"),
        ("pla", 1.0, "Spule 1.000 g", "Bedarf 24,6 g, kein Filament im Bestand des Projekts")]


# ---------------------------------------------------------------------------------------------------------------------
# Planung und Einkaufsliste


def bom_mit(filament, run=5, katalog=None):
    best = copy.deepcopy(bb.BESTAND)
    if filament is not None:
        best["filament"] = copy.deepcopy(filament)
    return plane(bb.material_bom(run=run), best, katalog or Katalog()).bom


def test_planung_nur_wenn_das_projekt_filament_fuehrt():
    assert "filament_bestand" not in bom_mit(None)
    fb = bom_mit(bb.FILAMENT_BESTAND)["filament_bestand"]
    assert [(f["material"], f["gramm"], f["spulen"], f["spule_g"], f["preis_je_spule"]) for f in fb] == [
        ("petg", 120, 1, 1000, 17.0), ("pla", 310, 1, 1000, 17.0)]
    # Spulen eines Materials ohne Druckteil stehen hinten, mit Spulengröße aus dem Katalog
    tpu = bb.FILAMENT_BESTAND + [{"kennung": "S-0003", "material": "tpu-95a", "gramm": 500, "gramm_voll": 750}]
    fb = bom_mit(tpu)["filament_bestand"]
    assert fb[-1] == {"material": "tpu-95a", "name": "TPU 95A", "gramm": 500, "spulen": 1, "kennungen": ["S-0003"],
                      "spule_g": 750, "preis_je_spule": 21.0, "preis_stand": "2026-10"}
    # Einkaufsliste und Summe der Stückliste bleiben ohne Filament (die Druckvorschau kommt später)
    ohne, mit = bom_mit(None), bom_mit(bb.FILAMENT_BESTAND)
    assert mit["einkaufsliste"] == ohne["einkaufsliste"] and mit["einkauf_summe"] == ohne["einkauf_summe"]


def vorschau(petg=188.8, pla=24.6, run=5):
    v = druckvorschau_beispiel(run=run)
    for m in v["summe"]["material"]:
        m["g"] = {"petg": petg, "pla": pla}[m["material"]]
    return v


@pytest.mark.parametrize("petg_bestand, bedarf, spulen_kaufen", [
    (120, 188.8, 1),     # Fehlmenge 68,8 g: eine Spule
    (120, 1188.8, 2),    # 1.068,8 g: zwei Spulen
    (188.8, 188.8, 0),   # genau gedeckt: nichts
    (0, 1000.0, 1),      # genau eine Spule
    (0, 1000.4, 2),      # knapp darüber: zwei
])
def test_spulen_aufrunden(petg_bestand, bedarf, spulen_kaufen):
    fil = [{**bb.FILAMENT_BESTAND[0], "gramm": petg_bestand}, bb.FILAMENT_BESTAND[1]]
    e = ek.zusammenstellen(bom_mit(fil), vorschau(petg=bedarf))
    kauf = {z["id"]: z for z in e["filament_kauf"]}
    assert set(kauf) == ({"petg"} if spulen_kaufen else set())
    if spulen_kaufen:
        z = kauf["petg"]
        assert (z["menge"], z["preis_je"], z["preis"], z["gruppe"]) == (spulen_kaufen, 17.0, 17.0 * spulen_kaufen,
                                                                         "Lagerware")
        assert z in e["lager"] and e["summe_lager"] == pytest.approx(e["lager"][0]["preis"] + e["lager"][1]["preis"]
                                                                     + e["lager"][2]["preis"] + 17.0 * spulen_kaufen)


def test_spulengroesse_aus_dem_katalog():
    fil = [{"kennung": "S-0001", "material": "petg", "gramm": 100, "gramm_voll": 1000}]

    class Klein(Katalog):
        def material(self, mid):
            m = super().material(mid)
            if m and mid == "petg":
                m["spule_g"] = 250
            return m

    e = ek.zusammenstellen(bom_mit(fil, katalog=Klein()), vorschau(petg=600))
    (z,) = [z for z in e["filament_kauf"] if z["id"] == "petg"]
    assert (z["menge"], z["einheit"], z["preis_je"]) == (2.0, "Spule 250 g", 4.25)


def test_ohne_vorschau_desselben_laufs_keine_spulen():
    bom = bom_mit(bb.FILAMENT_BESTAND)
    assert ek.zusammenstellen(bom, None)["filament_kauf"] == []
    assert ek.zusammenstellen(bom, vorschau(run=6))["filament_kauf"] == []  # anderer Lauf
    # ohne Liste filament (Projekt führt kein Filament): wie bisher nur die Information
    e = ek.zusammenstellen(bom_mit(None), vorschau(petg=5000))
    assert e["filament_kauf"] == [] and e["filament_bestand"] is None and len(e["filament"]) == 2


# ---------------------------------------------------------------------------------------------------------------------
# Gedruckt und Gebaut


def test_verbrauch_angebrochene_zuerst_und_rest_einer_gekauften_spule():
    data = {"filament": [
        {"kennung": "S-0001", "material": "petg", "gramm": 1000, "gramm_voll": 1000},
        {"kennung": "S-0002", "material": "petg", "gramm": 80, "gramm_voll": 1000},
        {"kennung": "S-0003", "material": "petg", "gramm": 300, "gramm_voll": 1000},
        {"kennung": "S-0004", "material": "pla", "gramm": 50, "gramm_voll": 1000}]}
    k = Kennungen(hoechste_kennungen(data))
    ops, info = fl.verbrauch_aenderungen({"petg": 500.0}, data, k, "2026-10-22", Katalog())
    # S-0002 (80 g) leer, dann S-0003 (300 g) leer, dann 120 g von der vollen S-0001
    assert [(o["op"], o["kennung"], o.get("delta")) for o in ops] == [
        ("spule_gramm", "S-0002", -80), ("spule", "S-0002", None), ("spule_gramm", "S-0003", -300),
        ("spule", "S-0003", None), ("spule_gramm", "S-0001", -120)]
    assert info == [{"material": "petg", "gramm": 500, "aus_bestand": 500, "gekauft": 0.0,
                     "spulen": ["S-0002", "S-0003", "S-0001"], "neue_spule": None}]
    # Kevin nennt die Spule: die zuerst; reicht der Bestand nicht, bleibt der Rest der gekauften Spule
    k = Kennungen(hoechste_kennungen(data))
    ops, info = fl.verbrauch_aenderungen({"pla": 230.0}, data, k, "2026-10-22", Katalog(), vorzug="S-0004")
    assert [(o["op"], o["kennung"]) for o in ops] == [("spule_gramm", "S-0004"), ("spule", "S-0004"),
                                                       ("spule", "S-0005")]
    assert ops[-1]["nachher"]["gramm"] == 820 and info[0]["gekauft"] == 180 and info[0]["neue_spule"] == "S-0005"
    for op in ops:
        anwenden(data, op)
    assert [(s["kennung"], s["gramm"]) for s in data["filament"] if s["material"] == "pla"] == [("S-0005", 820)]


def test_gedruckt_buchen_je_platte_und_gebaut_bucht_den_rest(rt):
    assert "führt kein Filament" in rt.gedruckt_buchen(grund="x")["error"]
    rt.bestand_eintragen(material="petg", gramm=120, spule="Bambu PETG Basic schwarz", grund="Kevin")
    rt.bestand_eintragen(material="pla", gramm=310, grund="Kevin")
    assert "erst rechnen" in rt.gedruckt_buchen(grund="x")["error"]
    rt.rechnen()
    # Platte 1 (PETG 188,8 g): 120 g aus S-0001, 68,8 g von einer gekauften Spule, Rest 931,2 g als S-0003
    res = rt.gedruckt_buchen(grund="Kevin: Platte 1 ist gedruckt", platten=[1])
    assert res["ok"], res
    b = res["buchung"]
    assert (b["art"], b["platten"], b["filament"], b["filament_ganz"]) == ("gedruckt", [1], {"petg": 188.8}, False)
    assert b["zusammenfassung"] == "120 g Filament verbraucht, 1 Spule leer, 1 Spule neu (S-0003 931,2 g)"
    assert res["filament_text"] == ["PETG: 188,8 g, davon 120 g aus S-0001, 68,8 g von gekauften Spulen (Rest als "
                                    "S-0003)"]
    assert [(s["kennung"], s["material"], s["gramm"]) for s in spulen(rt)] == [("S-0002", "pla", 310),
                                                                              ("S-0003", "petg", 931.2)]
    # dieselbe Platte nicht zweimal; eine Platte, die es nicht gibt, auch nicht
    assert "Schon als gedruckt gebucht: Platte 1" in rt.gedruckt_buchen(grund="x", platten=[1])["error"]
    assert "Platte 7 gibt es in der Druckvorschau nicht" in rt.gedruckt_buchen(grund="x", platten=[7])["error"]
    # Gebaut bucht Stangen, Stückgut und nur noch das Filament von Platte 2 (PLA 24,6 g)
    res = rt.gebaut_buchen(grund="Kevin: ist gebaut")
    assert res["ok"], res
    assert res["buchung"]["platten"] == [2] and res["buchung"]["filament"] == {"pla": 24.6}
    assert res["filament_text"] == ["PLA: 24,6 g, davon 24,6 g aus S-0002"]
    assert dict((s["kennung"], s["gramm"]) for s in spulen(rt))["S-0002"] == 285.4
    # alles gebucht: „gedruckt“ hat nichts mehr
    assert "Filament aller Platten schon gebucht" in rt.gedruckt_buchen(grund="x")["error"]
    # Rückgängig in umgekehrter Reihenfolge stellt die Spulen wieder her
    assert rt.buchung_rueckgaengig(res["buchung"]["id"])["ok"]
    assert rt.buchung_rueckgaengig(b["id"])["ok"]
    assert [(s["kennung"], s["gramm"]) for s in spulen(rt)] == [("S-0001", 120), ("S-0002", 310)]


def test_gebaut_ohne_gedruckt_bucht_die_ganze_vorschau(rt):
    rt.bestand_eintragen(material="petg", gramm=1000, grund="Kevin")
    rt.bestand_eintragen(material="pla", gramm=1000, grund="Kevin")
    rt.rechnen()
    res = rt.gebaut_buchen(grund="Kevin: fertig")
    assert res["ok"] and res["buchung"]["filament_ganz"] is True
    assert res["buchung"]["filament"] == {"petg": 188.8, "pla": 24.6}
    assert [(s["kennung"], s["gramm"]) for s in spulen(rt)] == [("S-0001", 811.2), ("S-0002", 975.4)]
    assert any("Filament PETG: 188,8 g von Spule S-0001 verbraucht" == z for z in res["aenderungen_text"])


def test_gebaut_ohne_filament_wie_bisher(rt):
    """Führt das Projekt kein Filament, bleibt „Gebaut“ wie bisher (nur Stangen, Platten, Stückgut)."""
    datei = BestandDatei.fuer_projekt(rt._project.path, katalog=rt.catalog.item)
    datei.schreiben(copy.deepcopy(bb.BESTAND))
    rt.rechnen()
    res = rt.gebaut_buchen(grund="Kevin")
    assert res["ok"] and "filament" not in res["buchung"] and "filament" not in res


def test_einkaufsliste_ueber_die_laufzeit(rt):
    rt.bestand_eintragen(material="petg", gramm=120, grund="Kevin")
    rt.bestand_eintragen(material="pla", gramm=310, grund="Kevin")
    rt.rechnen()
    res = rt.einkaufsliste()
    assert res["ok"] and [z["id"] for z in res["filament_kauf"]] == ["petg"]
    assert "- [ ] 1 × Spule 1.000 g: Filament PETG, 17,00 €" in res["text"]
    assert "  Bedarf 188,8 g, Bestand im Projekt: 120,0 g (1 Spule)" in res["text"]
    assert [f["material"] for f in res["filament_aus_bestand"] if f["reicht"]] == ["pla"]
    csv = Path(res["csv"]).read_text(encoding="utf-8")
    assert "Lagerware;1;Spule 1.000 g;Filament PETG;petg;17,00;17,00;2026-10;;;" in csv
    text = rt.bestand_liste()["text"]
    assert "- PETG (petg): 120 g auf 1 Spule" in text and "  - S-0001, 120 von 1000 g (seit" in text
    assert rt.bestand_liste("S-0002")["text"].count("  - S-0002") == 1


def test_katalog_prueft_spule_g():
    from kevcad_kernel.catalog import validate_material

    m = {"id": "petg", "name": "PETG", "gruppe": "Kunststoff", "dichte": 1.27, "farbe": "#DCE2E5", "druckbar": True}
    assert validate_material({**m, "spule_g": 750}) == []
    assert "spule_g" in validate_material({**m, "spule_g": 0})[0]
    assert "spule_g" in validate_material({**m, "spule_g": "1 kg"})[0]


# ---------------------------------------------------------------------------------------------------------------------
# App: BESTAND_SAVE mit Spulen und gebaut_filament in BESTAND (Strang „Bestand Stufe 2“, App-Lücken)


def speichern(rt, header):
    rt.gesendet.clear()
    rt._bestand_anfrage({"type": "BESTAND_SAVE", "id": "a-1", "grund": "Kevin in der App", **header})
    (ack,) = [m for m in rt.gesendet if m.get("type") == "ACK"]
    return ack


def test_bestand_save_mit_spulen(rt):
    ack = speichern(rt, {"filament_fuehren": True})
    assert ack["ok"] and ack["buchung"] == "B-0001" and spulen(rt) == []
    assert speichern(rt, {"filament_fuehren": True}) == {"type": "ACK", "reply_to": "a-1", "ok": True,
                                                          "message": "keine Änderung"}
    ack = speichern(rt, {"spule": {"material": "petg", "gramm": 640, "gramm_voll": 1000, "name": "Bambu PETG Basic",
                                   "hersteller": "Bambu Lab", "farbe": "schwarz", "ort": "Regal 3"}, "anzahl": 2})
    assert ack["ok"] and ack["message"] == "2 Spulen neu (S-0001 640 g, S-0002 640 g)"
    assert [(s["kennung"], s["gramm"], s["farbe"]) for s in spulen(rt)] == [("S-0001", 640, "schwarz"),
                                                                           ("S-0002", 640, "schwarz")]
    assert any(m.get("type") == "BESTAND" for m in rt.gesendet)  # danach BESTAND und BOM
    # ändern: alle Felder wie in der App, leere Texte löschen
    ack = speichern(rt, {"spule_kennung": "S-0002", "spule": {"material": "petg", "gramm": 1000, "gramm_voll": 1000,
                                                              "name": "Bambu PETG Basic", "hersteller": "Bambu Lab",
                                                              "farbe": "schwarz", "ort": ""}})
    assert ack["ok"] and ack["message"] == "Spule S-0002: 640 g → 1000 g"
    assert spulen(rt)[1]["ort"] is None and spulen(rt)[1]["gramm"] == 1000
    assert speichern(rt, {"spule_kennung": "S-0002", "spule": spulen(rt)[1]})["message"] == "keine Änderung"
    # entfernen und Fehler mit den Regeln von bestand_eintragen
    ack = speichern(rt, {"spule_kennung": "S-0001", "spule": None})
    assert ack["ok"] and ack["message"] == "1 Spule weg (S-0001)"
    ack = speichern(rt, {"spule": {"material": "messing", "gramm": 10}})
    assert ack["ok"] is False and "kein Druckmaterial" in ack["message"]
    ack = speichern(rt, {"spule": {"material": "petg", "gramm": 10, "dicke": 1.75}})
    assert ack["ok"] is False and "dicke" in ack["message"]
    datei = BestandDatei.fuer_projekt(rt._project.path)
    assert {b["von"] for b in datei.buchungen()} == {"kevin"}
    # Rückgängig wie jede Buchung
    rt._bestand_anfrage({"type": "BUCHUNG_RUECKGAENGIG", "id": "a-2", "buchung": "B-0004"})
    assert [s["kennung"] for s in spulen(rt)] == ["S-0001", "S-0002"]


def test_gebaut_filament_in_bestand(rt):
    assert "gebaut_filament" not in rt._bestand_nachricht()  # Projekt führt kein Filament
    rt.bestand_eintragen(material="petg", gramm=120, spule="Bambu PETG Basic schwarz", grund="Kevin")
    rt.bestand_eintragen(material="pla", gramm=310, grund="Kevin")
    g = rt._bestand_nachricht()["gebaut_filament"]
    assert g["run"] is None and g["hinweis"].startswith("Noch keine Stückliste")
    rt.rechnen()
    g = rt._bestand_nachricht()["gebaut_filament"]
    assert g["run"] == 5 and g["ganz_gebucht"] is None
    assert [(p["nr"], p["gebucht"], p["buchen"]) for p in g["platten"]] == [(1, None, True), (2, None, True)]
    assert g["spulen"] == [
        {"kennung": "S-0001", "material": "petg", "name": "Bambu PETG Basic schwarz", "farbe": None, "gramm": 120,
         "vorher": 120, "nachher": 0, "leer": True},
        {"kennung": "S-0002", "material": "pla", "name": None, "farbe": None, "gramm": 24.6, "vorher": 310,
         "nachher": 285.4, "leer": False}]
    assert g["neue_spulen"] == [{"kennung": "S-0003", "material": "petg", "gramm": 931.2, "gramm_voll": 1000}]
    assert g["gekauft"] == [{"material": "petg", "gramm": 68.8}]
    assert g["materialien"] == {"petg": "PETG", "pla": "PLA"}
    # Platte 1 als gedruckt gebucht: Gebaut nimmt nur noch Platte 2
    assert rt.gedruckt_buchen(grund="Kevin: Platte 1 gedruckt", platten=[1])["ok"]
    g = rt._bestand_nachricht()["gebaut_filament"]
    assert [(p["nr"], p["gebucht"], p["buchen"]) for p in g["platten"]] == [(1, "B-0003", False), (2, None, True)]
    assert [s["kennung"] for s in g["spulen"]] == ["S-0002"] and g["neue_spulen"] == [] and g["gekauft"] == []


def test_neue_druckvorschau_schickt_bestand_nur_bei_aenderung(rt):
    rt.bestand_eintragen(material="petg", gramm=120, grund="Kevin")
    rt.rechnen()
    rt._bestand_nachricht()
    rt.gesendet.clear()
    rt._bestand_vorschau_neu()
    assert rt.gesendet == []  # unverändert: nichts
    with rt._dv_lock:
        rt._dv_vorschau = vorschau(petg=500.0)
    rt._bestand_vorschau_neu()
    (m,) = rt.gesendet
    assert m["type"] == "BESTAND" and m["gebaut_filament"]["spulen"][0]["gramm"] == 120
    # PLA hat keine Spule: alles von gekauften Spulen
    assert m["gebaut_filament"]["gekauft"] == [{"material": "petg", "gramm": 380}, {"material": "pla", "gramm": 24.6}]
