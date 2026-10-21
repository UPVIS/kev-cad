"""Zukaufteile in model.py (``lager.zukauf``) im Rechenprozess: Ersatzkörper, Skript-Geometrie, Hersteller-STEP (auch in
Zoll und mit Y oben), Zwischenspeicher, Bezugspunkte, Freigabe, Normteil-Umleitung, Stücklistenzeile und PART_UPSERT."""

import json
from pathlib import Path

import pytest
from build123d import Box, Compound, Cylinder, Pos, Rot, export_step

import kevcad
from kevcad import lager
from kevcad_kernel.catalog import Catalog
from kevcad_kernel.runner import Runner
from kevcad_kernel.zukauf import cad as zc

HERE = Path(__file__).resolve().parent
TEST_CATALOG = HERE / "katalog_test"
HEAD = "from build123d import *\nfrom kevcad import lager, show, step, param\n"

WAGEN = {"id": "alutec-05200", "art": "zukaufteil", "name": "ALUTEC Transportroller 05200", "hersteller": "ALUTEC",
         "mpn": "05200", "gtin": "4014688052004", "url": "https://www.beispiel-shop.de/p/alutec-05200",
         "preis": {"je_stueck": 24.99, "waehrung": "EUR", "brutto": True, "stand": "2026-10-21",
                   "quelle": "https://www.beispiel-shop.de/p/alutec-05200"},
         "masse": {"l": 610, "b": 410, "h": 128}, "gewicht": 1800,
         "ersatz": {"form": "quader", "masse": {"l": 610, "b": 410, "h": 128}},
         "bezugspunkte": {"oben": {"pos": [0, 0, 128], "richtung": [0, 0, 1], "hinweis": "Ladefläche"}}}
NUDEL = {"id": "happy-people-77805", "art": "zukaufteil", "name": "Schwimmnudel 77805", "hersteller": "Happy People",
         "mpn": "77805", "gtin": "4008332778051", "masse": {"d": 70, "l": 1600},
         "ersatz": {"form": "zylinder", "masse": {"d": 70, "l": 1600}, "achse": "x"}}


def make_project(tmp_path: Path, teile: list[dict], materialien: list[dict] | None = None) -> Path:
    proj = tmp_path / "Projekt"
    proj.mkdir(exist_ok=True)
    (proj / "katalog.json").write_text(json.dumps({"version": 1, "teile": teile, "materialien": materialien or []},
                                                  ensure_ascii=False), encoding="utf-8")
    return proj


def run_model(proj: Path, code: str, regel: bool = True):
    model = proj / "model.py"
    model.write_text(code, encoding="utf-8")
    msgs = []
    runner = Runner(lambda h, p: msgs.append(h))
    res = runner.run({"run": 1, "path": str(model), "code": code, "params": {}, "inventar_regel": regel,
                      "catalog": {"builtin": str(TEST_CATALOG), "own": str(proj.parent / "eigen")}})
    parts = {h["app"]["name"]: h["app"] for h in msgs if h["type"] == "PART"}
    return res, parts


@pytest.fixture
def cat(tmp_path):
    proj = make_project(tmp_path, [WAGEN, NUDEL, {**WAGEN, "id": "vorschlag-1", "mpn": "1", "gtin": None,
                                                  "status": "vorgeschlagen"}])
    c = Catalog(TEST_CATALOG, tmp_path / "eigen", proj)
    kevcad._hooks["catalog"] = lambda: c
    yield c
    kevcad._hooks.clear()


# ---------------------------------------------------------------------------------------------------------- API


def test_finden_und_fehler(cat):
    w = lager.zukauf("alutec-05200")
    assert w.id == "alutec-05200" and w.cad == "vereinfacht" and w.bezugspunkte == ["oben"]
    assert lager.zukauf(mpn="05200", hersteller="alutec").id == "alutec-05200"
    assert lager.zukauf(gtin="4014688052004").id == "alutec-05200"
    assert lager.zukauf("4008332778051").id == "happy-people-77805"
    with pytest.raises(lager.LagerError, match="vorgeschlagen und wartet auf Kevins Freigabe"):
        lager.zukauf("vorschlag-1")
    with pytest.raises(lager.LagerError, match="Meinten Sie: 'alutec-05200'"):
        lager.zukauf("alutec-0520")
    with pytest.raises(lager.LagerError, match="ist ein Lagerteil"):
        lager.zukauf("rohr-en10220-42.4x2.0")
    with pytest.raises(lager.LagerError, match="ist ein Zukaufteil"):
        lager.teil("alutec-05200")
    with pytest.raises(lager.LagerError, match=r"Normteil.*schraube-iso4762-m8.*lager\.teil"):
        lager.zukauf("ISO 4762 M8x40")
    loc = w.bezugspunkt("oben")
    assert tuple(round(v, 6) for v in loc.position) == (0, 0, 128)
    with pytest.raises(lager.LagerError, match="Bezugspunkt 'unten' gibt es nicht.*vorhanden: oben"):
        w.bezugspunkt("unten")


def test_ersatzkoerper_quader_und_zylinder(cat):
    rw = lager.zukauf("alutec-05200").verbauen("Rollwagen")
    bb = rw.bounding_box()
    assert (round(bb.size.X), round(bb.size.Y), round(bb.size.Z)) == (610, 410, 128)
    assert round(bb.min.Z, 6) == 0 and round(bb.center().X, 6) == 0  # Einbaupunkt Mitte der Unterseite
    nudel = lager.zukauf("happy-people-77805").verbauen("Nudel")
    bb = nudel.bounding_box()
    assert (round(bb.size.X), round(bb.size.Y), round(bb.size.Z)) == (1600, 70, 70) and round(bb.min.Z, 6) == 0


def test_run_ersatz_stueckliste_und_upsert(tmp_path):
    proj = make_project(tmp_path, [WAGEN, NUDEL])
    code = HEAD + """
wagen = lager.zukauf("alutec-05200")
rw = wagen.verbauen("Rollwagen")
show(Pos(0, 0, 0) * rw, "Rollwagen")
nudel = lager.zukauf("happy-people-77805")
for i in range(2):
    show(Pos(0, 500 + 80 * i, 0) * nudel.verbauen(f"Lager/Schwimmnudel {i + 1}"), f"Lager/Schwimmnudel {i + 1}")
"""
    res, parts = run_model(proj, code)
    assert res["type"] == "RUN_DONE", res.get("error")
    assert res["inventar_verstoesse"] == []
    assert set(parts) == {"Rollwagen (vereinfacht)", "Lager/Schwimmnudel 1 (vereinfacht)",
                          "Lager/Schwimmnudel 2 (vereinfacht)"}
    head = parts["Rollwagen (vereinfacht)"]
    assert head["zukauf"] == {"id": "alutec-05200", "hersteller": "ALUTEC", "mpn": "05200", "cad": "vereinfacht",
                              "preis": 24.99, "url": "https://www.beispiel-shop.de/p/alutec-05200"}
    assert head["inventar"] == "ok" and "stock" not in head
    lines = res["bom"]["lines"]
    wagen = next(ln for ln in lines if ln["stock_id"] == "alutec-05200")
    assert wagen["art"] == "zukaufteil" and wagen["anzahl"] == 1 and wagen["preis_je"] == 24.99
    assert wagen["kg"] == 1.8 and wagen["masse_text"] == "610 × 410 × 128 mm"
    assert {k: wagen[k] for k in ("hersteller", "mpn", "gtin", "preis_stand", "preis_brutto", "cad_quelle",
                                  "vereinfacht")} == {
        "hersteller": "ALUTEC", "mpn": "05200", "gtin": "4014688052004", "preis_stand": "2026-10-21",
        "preis_brutto": True, "cad_quelle": "keins", "vereinfacht": True}
    nudeln = next(ln for ln in lines if ln["stock_id"] == "happy-people-77805")
    assert nudeln["anzahl"] == 2 and nudeln["preis"] is None and nudeln["masse_text"] == "Ø 70 × 1.600 mm"
    assert res["bom"]["totals"]["preis_hinweis"].endswith("Zukaufteile zum Shoppreis brutto")


def test_inventar_regel_vorschlag_bricht_ab(tmp_path):
    proj = make_project(tmp_path, [{**WAGEN, "status": "vorgeschlagen"}])
    res, _ = run_model(proj, HEAD + 'show(lager.zukauf("alutec-05200").verbauen("W"), "W")\n')
    assert res["type"] == "RUN_FAILED" and "wartet auf Kevins Freigabe" in res["error"]["message"]
    assert "freizugeben" in res["error"]["hint"]


# ------------------------------------------------------------------------------------------------ Skript-Geometrie


SKRIPT = '''
from build123d import *


def rollwagen(hoehe=128):
    rahmen = Pos(0, 0, hoehe - 30) * Box(610, 410, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    rahmen.label = "Rahmen"
    rahmen.color = Color("#2F6DB5")
    rollen = []
    for i, (x, y) in enumerate([(250, 150), (250, -150), (-250, 150), (-250, -150)]):
        r = Pos(x, y, 0) * Cylinder(20, hoehe - 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
        r.label = f"Rolle {i + 1}"
        rollen.append(r)
    return Compound(children=[rahmen, *rollen], label="Rollwagen")
'''


def test_skript_baugruppe_verschoben_mit_kindern(tmp_path):
    proj = make_project(tmp_path, [{**WAGEN, "cad": {"quelle": "skript", "datei": "rollwagen_05200.py",
                                                     "funktion": "rollwagen"}}])
    (proj / "rollwagen_05200.py").write_text(SKRIPT, encoding="utf-8")
    code = HEAD + """
wagen = lager.zukauf("alutec-05200")
rw = wagen.verbauen("Rollwagen", hoehe=128)
show(Pos(1000, 0, 0) * rw, "Rollwagen")
"""
    res, parts = run_model(proj, code)
    assert res["type"] == "RUN_DONE", res.get("error")
    assert sorted(parts) == ["Rollwagen/Rahmen", "Rollwagen/Rolle 1", "Rollwagen/Rolle 2", "Rollwagen/Rolle 3",
                             "Rollwagen/Rolle 4"]
    rahmen = parts["Rollwagen/Rahmen"]
    assert rahmen["bbox"]["min"][0] == pytest.approx(1000 - 305, abs=0.01)  # Kinder mit verschoben
    assert parts["Rollwagen/Rolle 1"]["bbox"]["min"][0] == pytest.approx(1000 + 230, abs=0.01)
    assert rahmen["zukauf"]["cad"] == "skript" and rahmen["inventar"] == "ok"
    assert rahmen["color"][:3] == pytest.approx([0x2F / 255, 0x6D / 255, 0xB5 / 255], abs=1e-3)
    line, = res["bom"]["lines"]
    assert line["anzahl"] == 1 and len(line["teile"]) == 5 and line["vereinfacht"] is False
    assert line["cad_quelle"] == "skript"


def test_baugruppe_verschoben_gedreht_verschachtelt(tmp_path):
    """Runner ohne Zukaufteil: Kinder einer verschachtelten Baugruppe folgen Pos/Rot und ``located`` (baum.kinder).
    Maßstab für die Zusammenführung mit Phase 5, die denselben Fehler anders behebt."""
    proj = make_project(tmp_path, [])
    code = """from build123d import *
from kevcad import show
a = Box(10, 10, 10)
a.label = "A"
b = Pos(20, 0, 0) * Box(10, 10, 10)
b.label = "B"
g = Compound(children=[b], label="G")
bg = Compound(children=[a, g], label="BG")
show(Pos(100, 0, 0) * Rot(0, 0, 90) * bg, "Gedreht")
c = Compound(children=[Box(4, 4, 4)], label="C")
c.children[0].label = "Klotz"
c2 = c.located(Location((0, 50, 0)))
show(c2, "Gesetzt")
"""
    res, parts = run_model(proj, code, regel=False)
    assert res["type"] == "RUN_DONE", res.get("error")
    assert sorted(parts) == ["Gedreht/A", "Gedreht/G/B", "Gesetzt/Klotz"]
    a, b = parts["Gedreht/A"]["bbox"], parts["Gedreht/G/B"]["bbox"]
    assert a["min"] == pytest.approx([95, -5, -5], abs=1e-6) and a["max"] == pytest.approx([105, 5, 5], abs=1e-6)
    assert b["min"] == pytest.approx([95, 15, -5], abs=1e-6)  # (20, 0, 0) um 90° gedreht, dann +100 in X
    assert parts["Gesetzt/Klotz"]["bbox"]["min"] == pytest.approx([-2, 48, -2], abs=1e-6)


def test_skript_kwargs_nur_bei_skript(cat):
    with pytest.raises(lager.LagerError, match="nur bei Skript-Geometrie"):
        lager.zukauf("alutec-05200").verbauen("W", hoehe=3)


# ---------------------------------------------------------------------------------------------- Hersteller-STEP


def step_wagen(path: Path, *, skala: float = 1.0, y_oben: bool = False) -> Path:
    """Kleine Test-Baugruppe 610 × 410 × 128 (Platte und vier Rollen), wahlweise in Zoll oder mit Y oben."""
    platte = Pos(0, 0, 113) * Box(610, 410, 30)
    platte.label = "Platte"
    rollen = []
    for i, (x, y) in enumerate([(250, 150), (250, -150), (-250, 150), (-250, -150)]):
        r = Pos(x, y, 49) * Cylinder(20, 98)
        r.label = f"Rolle {i + 1}"
        rollen.append(r)
    asm = Compound(children=[platte, *rollen], label="05200")
    if y_oben:
        asm = Rot(-90, 0, 0) * asm  # Z → Y
    if skala != 1.0:
        asm = asm.scale(skala)
    from kevcad_kernel.baum import transformieren

    asm = transformieren(asm)  # Kinder an der echten Lage (für den Export)
    asm.label = "05200"
    export_step(asm, str(path))
    return path


@pytest.mark.parametrize("variante", ["mm", "zoll", "y_oben"])
def test_step_import_korrigiert(tmp_path, variante):
    src = step_wagen(tmp_path / f"wagen-{variante}.step", skala=1 / 25.4 if variante == "zoll" else 1.0,
                     y_oben=variante == "y_oben")
    shape, info = zc.importieren(src, tmp_path / "cache", (610, 410, 128), name="Rollwagen")
    bb = shape.bounding_box()
    assert (round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)) == (610, 410, 128)
    assert sorted(k.label for k in shape.children) == ["Platte", "Rolle_1", "Rolle_2", "Rolle_3", "Rolle_4"]
    text = " ".join(info["hinweise"])
    if variante == "zoll":
        assert info["pruefung"]["skala"] == 25.4 and "in Zoll gespeichert" in text
    elif variante == "y_oben":
        assert info["pruefung"]["drehung"] == "y_oben" and "mit Y nach oben gespeichert" in text
    else:
        assert info["hinweise"] == [] and info["pruefung"]["skala"] == 1.0
    # Zwischenspeicher: zweiter Aufruf aus dem BREP mit gleichem Baum
    zc._memo.clear()
    shape2, info2 = zc.importieren(src, tmp_path / "cache", (610, 410, 128), name="Rollwagen")
    assert info2["cache"] is True and sorted(k.label for k in shape2.children) == sorted(
        k.label for k in shape.children)
    assert (tmp_path / "cache" / f"wagen-{variante}.brep").is_file()


def test_step_passt_nicht(tmp_path):
    src = step_wagen(tmp_path / "w.step")
    with pytest.raises(zc.CadFehler, match=r"passt nicht: Hüllmaß 610 × 410 × 128 mm gegen 300 × 200 × 50 mm"):
        zc.importieren(src, tmp_path / "c", (300, 200, 50), name="Rollwagen")
    shape, info = zc.importieren(src, tmp_path / "c", (300, 200, 50), name="Rollwagen", erzwingen=True)
    assert "erzwingen" in " ".join(info["hinweise"])


def test_run_mit_hersteller_cad(tmp_path):
    proj = make_project(tmp_path, [{**WAGEN, "cad": {"quelle": "download", "datei": "zukauf/alutec-05200/w.step",
                                                     "lizenz": "Herstellerbedingungen", "stand": "2026-10-21"}}])
    (proj / "zukauf" / "alutec-05200").mkdir(parents=True)
    step_wagen(proj / "zukauf" / "alutec-05200" / "w.step", skala=1 / 25.4)
    code = HEAD + """
wagen = lager.zukauf("alutec-05200")
show(Pos(0, 0, 0) * wagen.verbauen("Rollwagen"), "Rollwagen")
show(wagen.bezugspunkt("oben") * wagen.verbauen("Rollwagen 2"), "Rollwagen 2")  # gestapelt
"""
    res, parts = run_model(proj, code)
    assert res["type"] == "RUN_DONE", res.get("error")
    assert parts["Rollwagen 2/Platte"]["bbox"]["max"][2] == pytest.approx(256, abs=0.01)
    assert "Rollwagen/Platte" in parts and parts["Rollwagen/Platte"]["zukauf"]["cad"] == "hersteller"
    assert any("in Zoll gespeichert" in w for w in res["warnings"])
    assert parts["Rollwagen/Platte"]["bbox"]["max"][2] == pytest.approx(128, abs=0.01)
    line = res["bom"]["lines"][0]
    assert line["cad_quelle"] == "download" and line["vereinfacht"] is False and line["anzahl"] == 2
    assert (proj / "zukauf" / "alutec-05200" / "w.brep").is_file()  # Zwischenspeicher im Projekt


def test_hersteller_cad_und_normteil_zwischenspeicher(tmp_path):
    """Zukauf-Import (Zwischenspeicher _memo, gemeinsame OCCT-Formen) und Normteile aus profiles.fastener (flache
    Kopien) im selben Modell, zwei Läufe: jedes Stück eigene Lage und Stücklistenzeile, Vorlagen unverändert."""
    from kevcad_kernel import profiles

    proj = make_project(tmp_path, [{**WAGEN, "cad": {"quelle": "download", "datei": "zukauf/alutec-05200/w.step"}}])
    (proj / "zukauf" / "alutec-05200").mkdir(parents=True)
    step_wagen(proj / "zukauf" / "alutec-05200" / "w.step")
    code = HEAD + """
wagen = lager.zukauf("alutec-05200")
show(wagen.verbauen("Wagen A"), "Wagen A")
show(Pos(1000, 0, 0) * wagen.verbauen("Wagen B"), "Wagen B")
schraube = lager.teil("schraube-iso4762-m8")
for i in range(3):
    show(Pos(-200 + 200 * i, 0, 400) * schraube.verbauen(laenge=40, name=f"Schrauben/M8x40 {i + 1}"),
         f"Schrauben/M8x40 {i + 1}")
"""
    for lauf in (1, 2):
        res, parts = run_model(proj, code)
        assert res["type"] == "RUN_DONE", res.get("error")
        assert parts["Wagen A/Platte"]["bbox"]["min"][0] == pytest.approx(-305, abs=0.01)
        assert parts["Wagen B/Platte"]["bbox"]["min"][0] == pytest.approx(695, abs=0.01), lauf
        xs = sorted(round(parts[f"Schrauben/M8x40 {i}"]["bbox"]["min"][0]) for i in (1, 2, 3))
        assert xs[1] - xs[0] == 200 and xs[2] - xs[1] == 200, (lauf, xs)
        lines = {ln["stock_id"]: ln for ln in res["bom"]["lines"]}
        assert lines["alutec-05200"]["anzahl"] == 2 and lines["alutec-05200"]["vereinfacht"] is False
        assert lines["schraube-iso4762-m8"]["anzahl"] == 3, lines["schraube-iso4762-m8"]
        assert parts["Wagen B/Rolle_1"]["zukauf"]["id"] == "alutec-05200"  # Kind des zweiten Stücks, eindeutig
        teile = lines["alutec-05200"]["teile"]
        assert len(teile) == 10 and teile.count("Wagen B/Rolle_1") == 1, teile
    for vorlage in profiles._FASTENER_CACHE.values():  # Namen und Lage der Vorlagen bleiben unberührt
        assert not str(getattr(vorlage, "label", "") or "").startswith("Schrauben/")
        assert vorlage.location.wrapped.IsIdentity()


def test_cad_datei_fehlt_ersatz(tmp_path):
    proj = make_project(tmp_path, [{**WAGEN, "cad": {"quelle": "download", "datei": "zukauf/x/fehlt.step"}}])
    res, parts = run_model(proj, HEAD + 'show(lager.zukauf("alutec-05200").verbauen("W"), "W")\n')
    assert res["type"] == "RUN_DONE" and "W (vereinfacht)" in parts
    assert any("fehlt" in w for w in res["warnings"])


def test_material_und_einbaupunkt(tmp_path):
    entry = {**WAGEN, "material": "petg", "gewicht": None, "einbaupunkt": {"pos": [0, 0, 128], "richtung": [0, 0, 1]}}
    entry.pop("gewicht")
    proj = make_project(tmp_path, [entry])
    res, parts = run_model(proj, HEAD + 'show(lager.zukauf("alutec-05200").verbauen("W"), "W")\n')
    assert res["type"] == "RUN_DONE", res.get("error")
    head = parts["W (vereinfacht)"]
    assert head["bbox"]["max"][2] == pytest.approx(0, abs=1e-6)  # Einbaupunkt oben auf den Ursprung
    line = res["bom"]["lines"][0]
    assert line["material"] == "PETG" and line["kg"] == pytest.approx(610 * 410 * 128 * 1.27 / 1e6, rel=1e-3)

