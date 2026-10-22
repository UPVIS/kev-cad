"""Kevins Filamente mit Presets (druck/filamente.py) und das angenommene Filament der Druckvorschau
(druck/filamentwahl.py; DRUCKVORSCHAU.md „Filamente und Presets“). Gegen eine Attrappe der Bambu-Studio-Profile (läuft
ohne Bambu Studio); der Nachweis mit dem echten Bambu Studio (Preset im 3MF, Temperatur im G-Code) steht in
test_druck_slicer.py."""

import json
from pathlib import Path

import pytest

from kevcad_kernel.druck import filamente as fl
from kevcad_kernel.druck import filamentwahl as fw
from kevcad_kernel.druck import slicer as sl
from kevcad_kernel.druck import vorgaben as vg
from kevcad_kernel.druck import vorschau as vs

P1P = ["Bambu Lab P1P 0.4 nozzle", "Bambu Lab P1P 0.6 nozzle", "Bambu Lab P1P 0.8 nozzle"]
POLY = "polymaker-polylite-petg-gelb"
BASIC = "bambu-petg-basic"


def _json(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """Attrappe: System (PolyLite PETG, Bambu PETG Basic, Generic PETG, Bambu PLA Basic, ein A1-Profil, eine
    include-Vorlage) und Kevins Benutzerprofile (Amazon Basics PLA, „PolyLite PETG @BBL P1P - Copy“)."""
    app = tmp_path / "BambuStudio.app"
    f = app / "Contents/Resources/profiles/BBL/filament"
    _json(f / "fdm_filament_common.json", {"name": "fdm_filament_common", "filament_diameter": ["1.75"]})
    _json(f / "fdm_filament_template_direct_dual.json", {"name": "fdm_filament_template_direct_dual",
                                                         "instantiation": "false", "slow_down_min_speed": ["10", "10"],
                                                         "filament_flow_ratio": ["0.95", "0.95"]})
    _json(f / "fdm_filament_pet.json", {"name": "fdm_filament_pet", "inherits": "fdm_filament_common",
                                        "instantiation": "false", "filament_type": ["PETG"],
                                        "nozzle_temperature": ["255"], "textured_plate_temp": ["70"],
                                        "cool_plate_temp": ["0"], "eng_plate_temp": ["70"]})
    _json(f / "fdm_filament_pla.json", {"name": "fdm_filament_pla", "inherits": "fdm_filament_common",
                                        "instantiation": "false", "filament_type": ["PLA"]})
    _json(f / "PolyLite PETG @base.json", {"name": "PolyLite PETG @base", "inherits": "fdm_filament_pet",
                                           "instantiation": "false", "filament_vendor": ["Polymaker"],
                                           "textured_plate_temp": ["70"]})
    _json(f / "PolyLite PETG @BBL P1P.json", {
        "name": "PolyLite PETG @BBL P1P", "inherits": "PolyLite PETG @base", "instantiation": "true",
        "include": ["fdm_filament_template_direct_dual"], "compatible_printers": P1P,
        "nozzle_temperature": ["255", "255"], "nozzle_temperature_initial_layer": ["255", "255"],
        "nozzle_temperature_range_low": ["220"], "nozzle_temperature_range_high": ["270"],
        "textured_plate_temp": ["80"], "textured_plate_temp_initial_layer": ["80"], "hot_plate_temp": ["80"],
        "fan_min_speed": ["40"], "fan_max_speed": ["90"], "filament_max_volumetric_speed": ["11.5", "11.5"]})
    _json(f / "PolyLite PETG @BBL A1.json", {"name": "PolyLite PETG @BBL A1", "inherits": "PolyLite PETG @base",
                                             "instantiation": "true", "compatible_printers": ["Bambu Lab A1 0.4 nozzle"]})
    _json(f / "Bambu PETG Basic @BBL X1C.json", {
        "name": "Bambu PETG Basic @BBL X1C", "inherits": "fdm_filament_pet", "instantiation": "true",
        "filament_vendor": ["Bambu Lab"], "compatible_printers": ["Bambu Lab X1 Carbon 0.4 nozzle", P1P[0]],
        "nozzle_temperature_initial_layer": ["245"]})
    _json(f / "Generic PETG @BBL P1P.json", {"name": "Generic PETG @BBL P1P", "inherits": "fdm_filament_pet",
                                             "instantiation": "true", "filament_vendor": ["Generic"],
                                             "compatible_printers": P1P})
    _json(f / "Bambu PLA Basic @BBL P1P.json", {"name": "Bambu PLA Basic @BBL P1P", "inherits": "fdm_filament_pla",
                                                "instantiation": "true", "filament_vendor": ["Bambu Lab"],
                                                "compatible_printers": P1P, "nozzle_temperature": ["220"],
                                                "textured_plate_temp": ["65"]})
    user = tmp_path / "user"
    _json(user / "123/filament/Amazon Basics PLA.json", {
        "name": "Amazon Basics PLA", "inherits": "Bambu PLA Basic @BBL P1P", "from": "User",
        "nozzle_temperature": ["205"], "textured_plate_temp": ["47"]})
    _json(user / "123/filament/PolyLite PETG @BBL P1P - Copy.json", {
        "name": "PolyLite PETG @BBL P1P - Copy", "inherits": "PolyLite PETG @BBL P1P", "from": "User",
        "nozzle_temperature": ["240", "nil"], "textured_plate_temp": ["75"]})
    monkeypatch.setenv("KEVCAD_BAMBU_APP", str(app))
    monkeypatch.setenv("KEVCAD_BAMBU_USER", str(user))
    monkeypatch.setenv("KEVCAD_FILAMENTE", str(tmp_path / "kevcad" / "filamente.json"))
    sl.index_leeren()
    yield tmp_path
    sl.index_leeren()


def _spule(name, hersteller, gramm=640, kennung="S-0001", material="petg", filament=None) -> dict:
    s = {"kennung": kennung, "material": material, "gramm": gramm, "gramm_voll": 1000, "name": name,
         "hersteller": hersteller}
    if filament:
        s["filament"] = filament
    return s


# ---------------------------------------------------------------------------------------------------------------------
# Liste


def test_startbestand_und_datei(profile):
    """Ohne Datei: Kevins zwei PETG und sein PLA, die Datei wird angelegt; Presets ohne Abweichungen."""
    alle = fl.liste()
    assert [f["id"] for f in alle] == [POLY, BASIC, "amazon-basics-pla"]
    datei = profile / "kevcad" / "filamente.json"
    assert json.loads(datei.read_text())["filamente"][0]["preset"]["basis"] == "PolyLite PETG @BBL P1P"
    poly = fl.finde(POLY)
    assert fl.anzeige(poly) == "Polymaker PolyLite PETG gelb (1,75 mm)"
    assert fl.preset_name(poly) == "Polymaker PolyLite PETG gelb (Kev CAD)"
    assert fl.abweichungen_text(poly) == "keine Abweichungen"
    basic = fl.finde(BASIC)
    assert basic["preset"]["basis"] == "Bambu PETG Basic @BBL X1C" and basic["offen"] == ["farbe"]
    assert [f["id"] for f in fl.liste("petg")] == [POLY, BASIC]
    assert fl.finde("Polymaker PolyLite PETG gelb")["id"] == POLY and fl.finde("PETG") is None  # mehrdeutig
    for f in alle:
        assert fl.pruefe(f) == [], f["id"]
    # Preset im Bambu-Format: aufgelöst (mit include), Name, Elternteil im System
    spec = fl.preset_spec(poly)
    assert spec == {"name": "Polymaker PolyLite PETG gelb (Kev CAD)", "basis": "PolyLite PETG @BBL P1P", "werte": {},
                    "farbe": "#F5C518", "inherits": "PolyLite PETG @BBL P1P"}
    d = sl.filament_profil(spec)
    assert d["filament_settings_id"] == ["Polymaker PolyLite PETG gelb (Kev CAD)"] and d["from"] == "User"
    assert d["nozzle_temperature"] == ["255", "255"] and d["slow_down_min_speed"] == ["10", "10"]  # include
    assert d["filament_colour"] == ["#F5C518"] and "include" not in d
    # Kevins Benutzerprofil als Basis: Elternteil ist das Systemprofil, von dem es erbt
    assert fl.preset_spec(fl.finde("amazon-basics-pla"))["inherits"] == "Bambu PLA Basic @BBL P1P"


def test_abweichungen_mit_quelle(profile):
    """Der Mechanismus für Abweichungen: Bambu-Werte im Format des Basisprofils, Bett nur für Platten mit Temperatur,
    jede Abweichung mit Quelle."""
    f = fl.define({"hersteller": "Test", "produkt": "PETG", "material": "petg", "farbe": "rot",
                   "preset": {"basis": "PolyLite PETG @BBL P1P", "abweichungen": [
                       {"schluessel": "duese", "wert": 238, "quelle": "Kevin, Probedruck 22.10.2026"},
                       {"schluessel": "bett", "wert": 75, "quelle": "Kevin, Probedruck 22.10.2026"},
                       {"schluessel": "luefter_max", "wert": 30, "quelle": "Kevin"}]}})
    assert f["id"] == "test-petg-rot" and fl.preset_name(f) == "Test PETG rot (Kev CAD)"
    spec = fl.preset_spec(f)
    assert spec["werte"]["nozzle_temperature"] == ["238", "238"]
    assert spec["werte"]["textured_plate_temp"] == ["75"] and spec["werte"]["hot_plate_temp"] == ["75"]
    assert "cool_plate_temp" not in spec["werte"]  # PETG druckt nicht auf der Cool Plate (0 °C)
    t = fw.temperaturen(spec)
    assert (t["duese"], t["platte"], t["luefter"]) == (238, 75, [40, 30])
    assert "Düse 238 °C (Kevin, Probedruck 22.10.2026)" in fl.abweichungen_text(f)
    with pytest.raises(fl.FilamentFehler, match="quelle fehlt"):
        fl.define({"hersteller": "Test", "produkt": "PLA", "material": "pla",
                   "preset": {"basis": "Bambu PLA Basic @BBL P1P",
                              "abweichungen": [{"schluessel": "duese", "wert": 210}]}})
    with pytest.raises(fl.FilamentFehler, match="passt laut Bambu Studio nicht"):
        fl.define({"hersteller": "Polymaker", "produkt": "PolyLite PETG", "material": "petg", "farbe": "blau",
                   "preset": {"basis": "PolyLite PETG @BBL A1"}})
    with pytest.raises(fl.FilamentFehler, match="gibt es schon"):
        fl.define({"id": POLY, "hersteller": "Polymaker", "produkt": "PolyLite PETG", "material": "petg",
                   "preset": {"basis": "PolyLite PETG @BBL P1P"}})
    assert fw.basis_vorschlag("Polymaker", "PolyLite PETG", "petg") == "PolyLite PETG @BBL P1P"  # nicht die Kopie
    assert fw.basis_vorschlag("Bambu Lab", "PETG Basic", "petg") == "Bambu PETG Basic @BBL X1C"


# ---------------------------------------------------------------------------------------------------------------------
# Angenommenes Filament der Druckvorschau


def test_reihenfolge_der_annahme(profile):
    """kevcad.json, zuletzt gewählt (druck.json), Spule im Bestand, erstes der Liste, Systemprofil."""
    w = fw.waehle("petg", vs.projekt_einstellungen({}))
    assert (w.filament, w.quelle, w.profil) == (POLY, "standard", "Polymaker PolyLite PETG gelb (Kev CAD)")
    assert w.temperaturen["duese"] == 255 and w.temperaturen["platte"] == 80
    # Spule im Bestand: über Hersteller und Name, oder über ihren Verweis
    w = fw.waehle("petg", vs.projekt_einstellungen({}, [_spule("Bambu PETG Basic schwarz", "Bambu Lab")]))
    assert (w.filament, w.quelle) == (BASIC, "spule")
    assert w.detail == "Spule S-0001 Bambu PETG Basic schwarz (Bambu Lab)"
    w = fw.waehle("petg", vs.projekt_einstellungen({}, [_spule("Rest", None, filament=BASIC)]))
    assert (w.filament, w.quelle) == (BASIC, "spule")
    # zuletzt gewählt geht vor der Spule
    proj = vs.projekt_einstellungen({}, [_spule("Bambu PETG Basic schwarz", "Bambu Lab")], {"petg": POLY})
    w = fw.waehle("petg", proj)
    assert (w.filament, w.quelle) == (POLY, "zuletzt")
    # kevcad.json geht vor (Filament der Liste oder Bambu-Profil)
    w = fw.waehle("petg", vs.projekt_einstellungen({"druck": {"filament": {"petg": BASIC}}}, [], {"petg": POLY}))
    assert (w.filament, w.quelle) == (BASIC, "projekt")
    w = fw.waehle("petg", vs.projekt_einstellungen({"druck": {"filament": {"petg": "Generic PETG"}}}))
    assert (w.profil, w.quelle, w.filament) == ("Generic PETG @BBL P1P", "projekt", None)
    w = fw.waehle("petg", vs.projekt_einstellungen({"druck": {"filament": {"petg": "Gibt es nicht"}}}))
    assert w.quelle == "standard" and any("gibt es weder in der Filamentliste" in v for v in w.verworfen)
    # kein Filament des Materials in der Liste: Systemprofil
    w = fw.waehle("tpu-95a", vs.projekt_einstellungen({}))
    assert w.quelle in ("system", "keins")
    # PLA: Kevins Benutzerprofil als Basis
    p = fw.waehle("pla", vs.projekt_einstellungen({}))
    assert (p.filament, p.temperaturen["duese"], p.temperaturen["platte"]) == ("amazon-basics-pla", 205, 47)


def test_zuletzt_je_projekt_in_druck_json(tmp_path):
    assert vg.filament_zuletzt(tmp_path) == {}
    assert vg.setze_filament(tmp_path, {"petg": POLY}) is True
    assert vg.setze_filament(tmp_path, {"petg": POLY}) is False
    assert vg.filament_zuletzt(tmp_path) == {"petg": POLY}
    d = json.loads((tmp_path / "druck.json").read_text())
    assert d["teile"] == {} and d["filament"]["petg"]["id"] == POLY  # Vorgaben je Teil bleiben unberührt


def test_vorschlaege_zur_rueckfrage(profile):
    v = fw.vorschlaege("petg", POLY, [_spule("Bambu PETG Basic schwarz", "Bambu Lab", 300),
                                      _spule("PolyLite PETG gelb", "Polymaker", 900, "S-0002")])
    assert v["zuletzt"] == POLY
    assert [(s["kennung"], s["filament"]) for s in v["spulen"]] == [("S-0001", BASIC), ("S-0002", POLY)]
    assert [x["id"] for x in v["liste"]] == [POLY, BASIC]
    assert fw.vorschlaege("petg", "amazon-basics-pla", [])["zuletzt"] is None  # anderes Material


def test_ohne_bambu_studio(tmp_path, monkeypatch):
    """Mac mini: nichts zu prüfen; die Liste gilt so, wie sie ist."""
    monkeypatch.setenv("KEVCAD_BAMBU_APP", str(tmp_path / "kein.app"))
    monkeypatch.setenv("KEVCAD_FILAMENTE", str(tmp_path / "filamente.json"))
    sl.index_leeren()
    w = fw.waehle("petg", vs.projekt_einstellungen({}))
    assert (w.filament, w.quelle, w.temperaturen) == (POLY, "standard", None)
    assert w.preset["name"] == "Polymaker PolyLite PETG gelb (Kev CAD)" and w.preset["inherits"] == ""
    assert fw.waehle("asa", vs.projekt_einstellungen({})).profil == "Generic ASA @BBL P1P"
    sl.index_leeren()


def test_vorschau_nennt_angenommenes_filament(profile):
    druck = {"teile": {"Halter": {}}, "vorschau": {"teile": {"Halter": {
        "fid": "f1", "material": "petg", "groesse": [40.0, 20.0, 10.0],
        "umriss": [[-20, -10], [20, -10], [20, 10], [-20, 10]], "umriss_flaeche": 800.0, "volumen": 4000.0,
        "stueck": 1}}, "formen": {"f1": {"form": "a"}}}}

    def info(m):
        return {"dichte": 1.27, "preis_je_kg": 20.0, "name": "PETG"}

    v, gr, _ = vs.baue(1, druck, [], {}, {}, info, filament_zuletzt={"petg": BASIC})
    m = v["summe"]["material"][0]
    assert (m["filament"], m["filament_id"], m["filament_quelle"]) == ("Bambu Lab PETG Basic (Kev CAD)", BASIC,
                                                                       "zuletzt")
    assert m["filament_basis"] == "Bambu PETG Basic @BBL X1C" and m["temperaturen"]["platte"] == 70
    assert v["teile"][0]["profil"]["filament_id"] == BASIC
    assert gr[0].filament_slicer["basis"] == "Bambu PETG Basic @BBL X1C"
    assert [f["id"] for f in v["filamente"]] == [POLY, BASIC]
    from kevcad_kernel.druck.vorschau_text import text

    assert "Filament PETG: „Bambu Lab PETG Basic (Kev CAD)“ (zuletzt gewählt: Bambu Lab PETG Basic (1,75 mm))" \
        in text(v)
    # anderes Filament = anderer Schlüssel (der Slicer rechnet neu)
    _, gr2, _ = vs.baue(1, druck, [], {}, {}, info)
    assert gr2[0].filament_wahl["filament"] == POLY and gr2[0].schluessel != gr[0].schluessel
