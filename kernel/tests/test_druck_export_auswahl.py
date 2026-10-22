"""Druckexport mit Auswahl und Objektnamen (DRUCKVORSCHAU.md, „Auswahl und Namen im Druckexport“):
``druck_export(…, teile=[…], ohne=[…])`` (druck/auswahl.py), ``lager.druckteil(…, spaeter=True)``, Objektnamen im 3MF
(``slicer.objekt_namen``, ``slicer.objekte_benennen``, ``dreimf.schreibe_3mf``). Ohne Bambu Studio; der Nachweis mit
Bambu Studio steht in test_druck_slicer.py."""

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.druck import anordnen as ao
from kevcad_kernel.druck import auswahl as au
from kevcad_kernel.druck import slicer as sl
from kevcad_kernel.druck.dreimf import schreibe_3mf
from kevcad_kernel.protocol import check_druck_message, print_export_req, print_export_res

HEAD = "from build123d import *\nfrom kevcad import lager, show, param\n"
PETG = "polymaker-polylite-petg-gelb"


# ---------------------------------------------------------------------------------------------------------------------
# Objektnamen


def test_kurzer_name_und_objekt_namen(tmp_path):
    assert sl.kurzer_name("Kugelschieber/Lenksperre links (Druck)") == "Kugelschieber/Lenksperre links (Druck)"
    lang = "Kugelschieber/Fahrwerk/Vorderachse/Halterung/Stangenhalter vorn links (Druck)"
    assert len(lang) > sl.NAME_MAX
    assert sl.kurzer_name(lang) == "Kugelschieber/…/Stangenhalter vorn links (Druck)"
    sehr_lang = "A/" + "x" * 80
    k = sl.kurzer_name(sehr_lang)
    assert len(k) == sl.NAME_MAX and k.endswith("…")
    stl = tmp_path / "a.stl"
    objekte = [sl.PlattenObjekt(stl, 0, 0, 0, name=n) for n in ("Rolle", "Rolle", "Deckel", "Rolle", "")]
    assert sl.objekt_namen(objekte) == ["Rolle", "Rolle (2)", "Deckel", "Rolle (3)", "a"]


MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2">
    <metadata key="name" value="assemble_1"/>
    <metadata face_count="12"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value="g1_1"/>
      <metadata key="matrix" value="1 0 0 60 0 1 0 60 0 0 1 5 0 0 0 1"/>
      <metadata key="wall_loops" value="4"/>
    </part>
  </object>
  <object id="4">
    <metadata key="name" value="assemble_2"/>
    <metadata face_count="12"/>
    <part id="3" subtype="normal_part">
      <metadata key="name" value="g2_d90_0_1"/>
    </part>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
    </model_instance>
  </plate>
</config>
"""


def test_objekte_benennen_setzt_namen_in_model_settings(tmp_path):
    """Wie Bambu Studio nach --load-assemble-list: Objekte „assemble_<n>“; nur model_settings.config ändert sich."""
    p = tmp_path / "bambu.3mf"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("Metadata/model_settings.config", MODEL_SETTINGS)
        z.writestr("Metadata/plate_1.png", b"\x89PNG")
    n = sl.objekte_benennen(p, ["Kugelschieber/Lenksperre links (Druck)", 'Rückwand & "Deckel" <A>'])
    assert n == 2
    with zipfile.ZipFile(p) as z:
        assert z.namelist() == ["3D/3dmodel.model", "Metadata/model_settings.config", "Metadata/plate_1.png"]
        assert z.read("3D/3dmodel.model") == b"<model/>" and z.read("Metadata/plate_1.png") == b"\x89PNG"
        cfg = z.read("Metadata/model_settings.config").decode()
    import xml.etree.ElementTree as ET

    root = ET.fromstring(cfg)
    namen = [[m.get("value") for m in o.findall("metadata") if m.get("key") == "name"] for o in root.findall("object")]
    teile = [[m.get("value") for m in o.find("part").findall("metadata") if m.get("key") == "name"]
             for o in root.findall("object")]
    assert namen == [["Kugelschieber/Lenksperre links (Druck)"], ['Rückwand & "Deckel" <A>']]
    assert teile == namen
    assert 'key="wall_loops" value="4"' in cfg and "assemble_" not in cfg
    # ohne assemble-Namen (schon benannt): nichts zu tun
    assert sl.objekte_benennen(p, ["X", "Y"]) == 0


def _klotz(pfad: Path) -> Path:
    P = np.array([[x, y, z] for z in (0, 10) for y in (-10, 10) for x in (-15, 15)], dtype=float)
    T = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                  [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    sl.schreibe_stl(pfad, P, T)
    return pfad


def test_dreimf_traegt_die_teilnamen(tmp_path):
    stl = _klotz(tmp_path / "g1.stl")
    liste = [sl.PlattenObjekt(stl, 60, 60, 0, name="Kugelschieber/Lenksperre links (Druck)"),
             sl.PlattenObjekt(stl, 160, 60, 90, name="Kugelschieber/Lenksperre links (Druck)"),
             sl.PlattenObjekt(stl, 100, 160, 0, name="Größe & Form")]
    r = schreibe_3mf(tmp_path / "eigen.3mf", [liste], platten_namen=["Platte 2"])
    assert r["namen"] == ["Kugelschieber/Lenksperre links (Druck)", "Kugelschieber/Lenksperre links (Druck) (2)",
                          "Größe & Form"]
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(tmp_path / "eigen.3mf") as z:
        modell = ET.fromstring(z.read("3D/3dmodel.model"))
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    assert [o.get("name") for o in modell.findall(".//m:object", ns)] == r["namen"]
    assert [m.get("value") for o in cfg.findall("object") for m in o.findall("metadata")
            if m.get("key") == "name"] == r["namen"]
    assert [m.get("value") for m in cfg.find("plate").findall("metadata") if m.get("key") == "plater_name"] == \
        ["Platte 2"]


# ---------------------------------------------------------------------------------------------------------------------
# Auswahl (reine Rechnung)


def _stueck(gruppe: str, name: str, ersatz: bool = False) -> ao.Stueck:
    return ao.Stueck(gruppe=gruppe, name=name, material="petg", w=30, h=20,
                     umriss=[[-15, -10], [15, -10], [15, 10], [-15, 10]], flaeche=600, ersatz=ersatz)


def _vorschau():
    """Kugelschieber im Kleinen: 4 Lenksperren (g1), 2 Stangenhalter (g2) auf Platte 1, Deckel ×2 (g3, ein
    Ersatzteil) auf Platte 2, eine Fangrolle später (g4)."""
    ls = [f"Kugelschieber/Lenksperren/Lenksperre {s} (Druck)" for s in ("vorn links", "vorn rechts", "hinten links",
                                                                         "hinten rechts")]
    sh = ["Kugelschieber/Stangenhalter links (Druck)", "Kugelschieber/Stangenhalter rechts (Druck)"]
    gr = [SimpleNamespace(id="g1", name="Lenksperre (Druck)", teile=ls, anzahl=4, spaeter=False),
          SimpleNamespace(id="g2", name="Stangenhalter (Druck)", teile=sh, anzahl=2, spaeter=False),
          SimpleNamespace(id="g3", name="Deckel", teile=["Deckel"], anzahl=2, spaeter=False),
          SimpleNamespace(id="g4", name="Fangrolle (Druck) (später)", teile=["Kugelschieber/Fangrolle (Druck)"],
                          anzahl=1, spaeter=True)]
    p1 = ao.Platte("petg", lagen=[ao.Lage(_stueck("g1", n), 30 + 40 * i, 50, 0) for i, n in enumerate(ls)]
                   + [ao.Lage(_stueck("g2", n), 30 + 40 * i, 120, 90) for i, n in enumerate(sh)])
    p2 = ao.Platte("petg", lagen=[ao.Lage(_stueck("g3", "Deckel"), 40, 40, 0),
                                  ao.Lage(_stueck("g3", "Deckel", ersatz=True), 90, 40, 0)])
    return [(1, "petg", p1), (2, "petg", p2)], gr


def test_auswahl_ohne_praefix_genau_gruppe():
    platten, gr = _vorschau()
    # Baugruppen-Präfix: alle vier Lenksperren; Platte 1 behält die Stangenhalter an ihrer Stelle
    a = au.waehle(platten, gr, ohne=["Kugelschieber/Lenksperren"])
    assert [nr for nr, _, _ in a.platten] == [1, 2]
    p1 = a.platten[0][2]
    assert [(l_.stueck.name, l_.x, l_.y, l_.drehung) for l_ in p1.lagen] == [
        ("Kugelschieber/Stangenhalter links (Druck)", 30, 120, 90),
        ("Kugelschieber/Stangenhalter rechts (Druck)", 70, 120, 90)]
    assert platten[0][2].lagen and len(platten[0][2].lagen) == 6  # Vorschau unverändert
    weg = {(w["name"], w["grund"]) for w in a.weggelassen}
    assert ("Kugelschieber/Lenksperren/Lenksperre vorn links (Druck)", "ohne") in weg and len(weg) == 5
    assert ("Kugelschieber/Fangrolle (Druck)", "spaeter") in weg
    assert a.leere_platten == [] and any("Lücken auf Platte 1" in h for h in a.hinweise)
    # genau ein Teil, Gruppe per id und per Name
    a = au.waehle(platten, gr, ohne=["Kugelschieber/Lenksperren/Lenksperre vorn links (Druck)"])
    assert sum(len(p.lagen) for _, _, p in a.platten) == 7
    for eintrag in ("g1", "Lenksperre (Druck)"):
        a = au.waehle(platten, gr, ohne=[eintrag])
        assert not any("Lenksperre" in n for n in a.teile)
    # Ersatzteile gehen mit ihrem Namen; leere Platte fällt weg
    a = au.waehle(platten, gr, ohne=["Deckel"])
    assert [nr for nr, _, _ in a.platten] == [1] and a.leere_platten == [2]
    assert {"name": "Deckel", "grund": "ohne", "platte": 2, "anzahl": 2} in a.weggelassen
    assert any("Platte 2" in h for h in a.hinweise)


def test_auswahl_teile_und_ohne_ohne_gewinnt():
    platten, gr = _vorschau()
    a = au.waehle(platten, gr, teile=["Kugelschieber"], ohne=["Kugelschieber/Lenksperren/Lenksperre vorn links (Druck)"])
    assert a.teile == ["Kugelschieber/Lenksperren/Lenksperre vorn rechts (Druck)",
                       "Kugelschieber/Lenksperren/Lenksperre hinten links (Druck)",
                       "Kugelschieber/Lenksperren/Lenksperre hinten rechts (Druck)",
                       "Kugelschieber/Stangenhalter links (Druck)", "Kugelschieber/Stangenhalter rechts (Druck)"]
    gruende = {w["name"]: w["grund"] for w in a.weggelassen}
    assert gruende["Kugelschieber/Lenksperren/Lenksperre vorn links (Druck)"] == "ohne"
    assert gruende["Deckel"] == "teile" and a.leere_platten == [2]
    # die Fangrolle (später) liegt unter dem Präfix, wird aber nicht exportiert
    assert gruende["Kugelschieber/Fangrolle (Druck)"] == "spaeter"
    # nur teile
    a = au.waehle(platten, gr, teile=["g3"])
    assert [nr for nr, _, _ in a.platten] == [2] and a.teile == ["Deckel"]
    assert "Weggelassen:" in au.weggelassen_text(a.weggelassen) and "(später)" in au.weggelassen_text(a.weggelassen)


def test_auswahl_fehler_mit_vorschlaegen():
    platten, gr = _vorschau()
    with pytest.raises(au.AuswahlFehler, match="Meintest du") as e:
        au.waehle(platten, gr, ohne=["Kugelschieber/Lenksperre vorn links (Druck)"])
    assert "Lenksperre vorn links" in str(e.value)
    with pytest.raises(au.AuswahlFehler, match="Lenksperre"):
        au.waehle(platten, gr, teile=["lenksperre"])  # Teilwort ohne Treffer: Vorschläge mit dem Wort
    with pytest.raises(au.AuswahlFehler, match="spaeter=True"):
        au.waehle(platten, gr, teile=["Kugelschieber/Fangrolle (Druck)"])
    with pytest.raises(au.AuswahlFehler, match="schon gedruckt"):
        au.waehle(platten, gr, teile=["Halter alt"], gedruckt=["Halter alt"])
    with pytest.raises(au.AuswahlFehler, match="kein Teil zum Drucken"):
        au.waehle(platten, gr, ohne=["Kugelschieber", "Deckel"])
    # später und gedruckt in ohne sind kein Fehler
    a = au.waehle(platten, gr, ohne=["Kugelschieber/Fangrolle (Druck)", "Halter alt"], gedruckt=["Halter alt"])
    assert sum(len(p.lagen) for _, _, p in a.platten) == 8


def test_auswahl_probe_weniger_platten():
    """Bleiben auf zwei Platten nur wenige Teile, sagt ein Hinweis, dass neu angeordnet weniger Platten reichten."""
    platten, gr = _vorschau()
    a = au.waehle(platten, gr, ohne=["Kugelschieber/Lenksperren", "Kugelschieber/Stangenhalter links (Druck)"])
    assert [nr for nr, _, _ in a.platten] == [1, 2]
    assert any("auf 1 statt 2 Platten" in h for h in a.hinweise), a.hinweise


def test_protokoll_auswahl():
    req = print_export_req("a-40", ziel="/x/k.3mf", ohne=["Kugelschieber/Lenksperren"])
    assert req["ohne"] == ["Kugelschieber/Lenksperren"] and "teile" not in req and check_druck_message(req) == []
    assert "ohne" not in print_export_req("a-41")
    assert check_druck_message({**req, "teile": "Deckel"}) == ["teile ist keine Liste von Teilnamen"]
    res = print_export_res("a-40", ok=True, pfad="/x/k.3mf", platten=[1],
                           weggelassen=[{"name": "A", "grund": "ohne", "platte": 1, "anzahl": 1}], leere_platten=[])
    assert check_druck_message(res) == []
    assert check_druck_message({**res, "weggelassen": [{"name": "A", "grund": "weg", "platte": 1, "anzahl": 1}]})


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit: spaeter=True, druck_export mit Auswahl, PRINT_EXPORT_REQ


KUGELSCHIEBER = HEAD + """
sperre = Box(30, 20, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
halter = Box(40, 16, 6, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(3, 20)
nachmessen = param("nachmessen", 1)
for i, seite in enumerate(("vorn links", "vorn rechts", "hinten links", "hinten rechts")):
    show(Pos(i * 50, 0, 0) * lager.druckteil(sperre, "Lenksperre", material="petg", zweck="funktion"),
         f"Kugelschieber/Lenksperren/Lenksperre {seite} (Druck)")
for i, seite in enumerate(("links", "rechts")):
    show(Pos(i * 60, 60, 0) * lager.druckteil(halter, "Stangenhalter", material="petg", zweck="tragend"),
         f"Kugelschieber/Stangenhalter {seite} (Druck)")
show(Pos(0, 120, 0) * lager.druckteil(Cylinder(12, 20, align=(Align.CENTER, Align.CENTER, Align.MIN)), "Fangrolle",
                                       material="petg", spaeter=bool(nachmessen)), "Kugelschieber/Fangrolle (Druck)")
"""


@pytest.fixture(scope="module")
def env():
    alt = {k: os.environ.get(k) for k in ("KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH", "KEVCAD_BAMBU_APP")}
    tmp = Path(tempfile.mkdtemp(prefix="kcda", dir=tempfile.gettempdir()))
    os.environ.update({"KEVCAD_DRUCK_CACHE": str(tmp / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(tmp / "abgleich.json"),
                       "KEVCAD_BAMBU_APP": str(tmp / "kein-bambu.app")})
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)
    for k, v in alt.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _namen_im_3mf(pfad: str) -> list[str]:
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(pfad) as z:
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    return [m.get("value") for o in cfg.findall("object") for m in o.findall("metadata") if m.get("key") == "name"]


def test_laufzeit_spaeter_und_export_mit_auswahl(env):
    rt, app, tmp = env["rt"], env["app"], env["tmp"]
    assert rt.project_new(str(tmp / "Kugelschieber"), "empty")["ok"]
    assert rt.model_write(KUGELSCHIEBER)["ok"]
    res = rt.run()
    assert res["ok"], res
    v = rt.druckvorschau()
    assert v["ok"] and v["run"] == res["run"]
    # spaeter=True: in der Liste (eigene Gruppe, markiert), auf keiner Platte, nicht in der Summe
    teile = {t["name"]: t for t in v["teile"]}
    rolle = teile["Fangrolle (Druck) (später)"]
    assert rolle["spaeter"] is True and rolle["anzahl"] == 1 and rolle["g"] > 0
    auf = [t["name"] for p in v["platten"] for t in p["teile"]]
    assert "Kugelschieber/Fangrolle (Druck)" not in auf and len(auf) == 6
    assert v["spaeter"] == [{"name": "Kugelschieber/Fangrolle (Druck)", "gruppe": rolle["gruppe"], "material": "petg"}]
    assert v["summe"]["material"][0]["g"] == pytest.approx(sum(p["material"][0]["g"] for p in v["platten"]), abs=0.2)
    assert all(not t.get("spaeter") for t in v["teile"] if t["name"] != "Fangrolle (Druck) (später)")
    from kevcad_kernel.druck.vorschau_text import text

    assert "Später drucken" in text(v) and "SPÄTER, auf keiner Platte" in text(v)
    # Export ohne Lenksperren: Stangenhalter bleiben an ihrer Stelle, Objekte heißen wie die Teile
    ex = rt.druck_export(str(tmp / "ohne.3mf"), ohne=["Kugelschieber/Lenksperren"], filament=PETG)
    assert ex["ok"], ex
    assert ex["teile"] == ["Kugelschieber/Stangenhalter links (Druck)", "Kugelschieber/Stangenhalter rechts (Druck)"]
    gruende = {(w["name"], w["grund"]) for w in ex["weggelassen"]}
    assert ("Kugelschieber/Lenksperren/Lenksperre vorn links (Druck)", "ohne") in gruende
    assert ("Kugelschieber/Fangrolle (Druck)", "spaeter") in gruende
    assert ex["hinweise"][0].startswith("Weggelassen:")
    assert ex["druckfertig"] is False  # ohne Bambu Studio nicht geprüft
    assert [o["name"] for o in ex["objekte_einstellungen"]] == ["Stangenhalter (Druck)"] and \
        "naht" in ex["objekte_einstellungen"][0]["begruendung_je"]
    assert _namen_im_3mf(ex["pfad"]) == ex["teile"] == ex["dateien"][0]["objekte"]
    lagen_vorschau = {t["name"]: (t["x"], t["y"]) for p in v["platten"] for t in p["teile"]}
    with zipfile.ZipFile(ex["pfad"]) as z:
        import xml.etree.ElementTree as ET

        modell = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    for item, name in zip(modell.findall(".//m:build/m:item", ns), ex["teile"]):
        x, y = (float(w) for w in item.get("transform").split()[9:11])
        assert (x, y) == pytest.approx(lagen_vorschau[name], abs=0.01), name
    # ohne Auswahl: auch die Fangrolle fehlt (später), mit Hinweis
    alle = rt.druck_export(str(tmp / "alle.3mf"), filament=PETG)
    assert alle["ok"] and len(alle["teile"]) == 6
    assert [w["grund"] for w in alle["weggelassen"]] == ["spaeter"] and "(später)" in alle["hinweise"][0]
    # unbekannter Name: Fehler mit Vorschlag
    falsch = rt.druck_export(ohne=["Kugelschieber/Lenksperre"], filament=PETG)
    assert not falsch["ok"] and "Meintest du" in falsch["fehler"] and "Lenksperren" in falsch["fehler"]
    nichts = rt.druck_export(teile=["Kugelschieber/Fangrolle (Druck)"], filament=PETG)
    assert not nichts["ok"] and "spaeter=True" in nichts["fehler"]
    # App: PRINT_EXPORT_REQ mit ohne
    m = app.mark()
    app.send({**print_export_req("a-50", ziel=str(tmp / "app.3mf"), ohne=["Lenksperre (Druck)"]),
              "filament": {"petg": PETG}})
    _, _, antwort, _ = app.wait_for(lambda h: h["type"] == "PRINT_EXPORT_RES" and h["reply_to"] == "a-50", start=m)
    assert antwort["ok"] and check_druck_message(antwort) == [], antwort
    assert {w["grund"] for w in antwort["weggelassen"]} == {"ohne", "spaeter"}
    assert antwort["dateien"][0]["objekte"] == ex["teile"]
    # spaeter weglassen (Reglerwert) → die Fangrolle kommt auf eine Platte und in den Export
    res2 = rt.run(params={"nachmessen": 0})
    assert res2["ok"]
    v2 = rt.druckvorschau()
    assert "spaeter" not in v2 and "Kugelschieber/Fangrolle (Druck)" in \
        [t["name"] for p in v2["platten"] for t in p["teile"]]


def test_spaeter_und_gedruckt_schliessen_sich_aus(env):
    rt, tmp = env["rt"], env["tmp"]
    assert rt.project_new(str(tmp / "Widerspruch"), "empty")["ok"]
    code = HEAD + 'show(lager.druckteil(Box(10, 10, 5), "X", material="petg", spaeter=True, gedruckt=True), "X")\n'
    assert rt.model_write(code)["ok"]
    res = rt.run()
    assert not res["ok"] and "schließen sich aus" in json.dumps(res, ensure_ascii=False)


def test_spule_verweist_auf_filament_und_rueckfrage(env):
    """Spule mit Verweis auf Kevins Filamentliste (bestand_eintragen(filament=…)); ohne Filament fragt der Export
    nach und schlägt zuletzt gewählt, die Spule und alle PETG der Liste vor."""
    rt, tmp = env["rt"], env["tmp"]
    assert rt.project_new(str(tmp / "Spulen"), "empty")["ok"]
    code = HEAD + 'show(lager.druckteil(Box(30, 20, 5), "Halter", material="petg"), "Halter")\n'
    assert rt.model_write(code)["ok"] and rt.run()["ok"]
    r = rt.bestand_eintragen(filament="bambu-petg-basic", gramm=640, grund="Kevin")
    assert r["ok"], r
    spule = json.loads((tmp / "Spulen" / "bestand.json").read_text())["filament"][0]
    assert (spule["material"], spule["filament"], spule["hersteller"], spule["name"]) == \
        ("petg", "bambu-petg-basic", "Bambu Lab", "PETG Basic")
    assert not rt.bestand_eintragen(filament="gibt-es-nicht", gramm=10)["ok"]
    rt.run()
    v = rt.druckvorschau()
    assert v["summe"]["material"][0]["filament_quelle"] == "spule"
    assert v["summe"]["material"][0]["filament_id"] == "bambu-petg-basic"
    frage = rt.druck_export(str(tmp / "frage.3mf"))
    assert not frage["ok"] and frage["filament_frage"] and "Frag Kevin nach dem Filament" in frage["fehler"]
    vor = frage["vorschlaege"]["petg"]
    assert vor["zuletzt"] is None and vor["spulen"][0]["filament"] == "bambu-petg-basic"
    assert [x["id"] for x in vor["liste"]] == ["polymaker-polylite-petg-gelb", "bambu-petg-basic"]
    falsch = rt.druck_export(filament={"petg": "amazon-basics-pla"})
    assert not falsch["ok"] and "PLA" in falsch["fehler"] and "PETG" in falsch["fehler"]
    ok = rt.druck_export(str(tmp / "basic.3mf"), filament="bambu-petg-basic")
    assert ok["ok"] and ok["filamente"]["petg"]["preset"] == "Bambu Lab PETG Basic (Kev CAD)", ok
    assert ok["dateien"][0]["filament_basis"] == "Bambu PETG Basic @BBL X1C"
    assert rt.druck_export(str(tmp / "x.3mf"))["vorschlaege"]["petg"]["zuletzt"] == "bambu-petg-basic"
    liste = rt.filament_liste("petg")
    assert liste["ok"] and [f["id"] for f in liste["filamente"]] == ["polymaker-polylite-petg-gelb",
                                                                     "bambu-petg-basic"]
    assert liste["zuletzt"] == {"petg": "bambu-petg-basic"} and liste["spulen"][0]["filament"] == "bambu-petg-basic"
