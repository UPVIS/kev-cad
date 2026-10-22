"""API ``kevcad.lager`` und Stückliste im Rechenprozess (Runner im selben Prozess, Test-Katalog), dazu der Abnahmetest
mit dem Beispiel samples/gestell/model.py."""

from pathlib import Path

import pytest
from build123d import Box, Color, Part, Pos, Rectangle

import kevcad
from kevcad import lager
from kevcad_kernel.catalog import Catalog, builtin_dir
from kevcad_kernel.runner import Runner

HERE = Path(__file__).resolve().parent
TEST_CATALOG = HERE / "katalog_test"
SAMPLE = HERE.parents[1] / "samples" / "gestell" / "model.py"
HEAD = "from build123d import *\nfrom kevcad import lager, show, step, param\n"


@pytest.fixture
def cat(tmp_path):
    c = Catalog(TEST_CATALOG, tmp_path / "eigen", tmp_path)
    kevcad._hooks["catalog"] = lambda: c
    yield c
    kevcad._hooks.clear()


# ---------------------------------------------------------------------------------------------------------- Suchen


def test_teil_by_id_and_by_masse(cat):
    t = lager.teil("rohr-en10220-42.4x2.0")
    assert t.art == "rohr" and t.material_name == "Stahl S235" and t.kg_je_m == 1.99 and t.ebene == "mitgeliefert"
    assert lager.teil("vierkantrohr", a=40, s=3).id == "vierkantrohr-en10219-40x40x3"
    assert lager.teil("rohr", d="42,4", s=2).id == "rohr-en10220-42.4x2.0"
    assert lager.teil("platte", s=18, material="multiplex").id == "platte-multiplex-birke-18"
    assert lager.teil("schraube", norm="iso4762", groesse="M8-1.25").id == "schraube-iso4762-m8"
    assert lager.teil("schraube", groesse="M8").id == "schraube-iso4762-m8"
    assert lager.teil("rohr", d=33.7, s=2).kg_je_m == pytest.approx(1.574, abs=0.005)  # berechnet (Edelstahl 7,9)
    assert "vierkantrohr-en10219-40x40x3" in repr(lager.teil("vierkantrohr", a=40))


def test_teil_errors_with_suggestions(cat):
    with pytest.raises(lager.LagerError, match=r"Kein Lagerteil vierkantrohr mit a=45, s=3\. Ähnlich: "
                                                r"vierkantrohr-en10219-40x40x3"):
        lager.teil("vierkantrohr", a=45, s=3)
    with pytest.raises(lager.LagerError, match="2 Lagerteile passen"):
        lager.teil("rohr", s=2)
    with pytest.raises(lager.LagerError, match="Maß x gibt es für art 'rohr' nicht"):
        lager.teil("rohr", x=3)
    with pytest.raises(lager.LagerError, match="Meinten Sie: 'rohr-en10220-42.4x2.0'"):
        lager.teil("rohr-en10220-42.4x2")
    with pytest.raises(lager.LagerError, match="Material 'stahll'.*'stahl'"):
        lager.teil("rohr", d=42.4, material="stahll")
    with pytest.raises(lager.LagerError, match="Art 'roh' unbekannt"):
        lager.teil("roh", d=42.4)


def test_suche(cat):
    hits = lager.suche("40x40")
    assert [h.id for h in hits] == ["vierkantrohr-en10219-40x40x3", "winkel-en10056-40x40x4",
                                    "nutprofil-40x40-n8-leicht"]
    assert all(isinstance(h, lager.Lagerteil) for h in hits)


# -------------------------------------------------------------------------------------------------------- Verbauen


def test_verbauen_bar(cat):
    registered = []
    kevcad._hooks["lager"] = lambda piece, shape: registered.append((piece, shape))
    rohr = lager.teil("vierkantrohr", a=40, s=3)
    bein = rohr.verbauen(laenge=882, name="Gestell/Bein", gehrung=(0, 45))
    assert isinstance(bein, Part) and bein.label == "Gestell/Bein" and bein.lagerteil is rohr
    assert tuple(round(c, 4) for c in bein.color) == tuple(round(c, 4) for c in Color("#8A9099"))
    bb = bein.bounding_box()
    assert (bb.size.X, bb.size.Y, bb.size.Z) == pytest.approx((40, 40, 882)) and bb.min.Z == pytest.approx(0)
    (piece, shape), = registered
    assert shape is bein and piece.stock_id == rohr.id and piece.laenge == 882 and piece.gehrung == (0, 45)
    assert piece.kg == pytest.approx(3.30 * 0.882) and piece.preis == pytest.approx(8 * 0.882)
    assert piece.stock_info() == {"id": rohr.id, "name": "Vierkantrohr 40 × 40 × 3", "laenge": 882.0,
                                  "gehrung": [0.0, 45.0], "material": "stahl-s235", "kg": 2.911, "preis": 7.06}
    assert rohr.verbauen(300, gehrung=30).label == "Vierkantrohr 40 × 40 × 3"  # ohne Namen: Name des Lagerteils
    flach = lager.teil("flach", b=40, s=5).verbauen(laenge=200, drehung=90)
    assert flach.bounding_box().size.Y == pytest.approx(40)
    with pytest.raises(lager.LagerError, match="laenge in mm"):
        rohr.verbauen(name="x")
    with pytest.raises(lager.LagerError, match="zu steil"):
        rohr.verbauen(laenge=50, gehrung=(45, 45))
    with pytest.raises(lager.LagerError, match="außerhalb"):
        rohr.verbauen(laenge=500, gehrung=(85, 0))
    with pytest.raises(lager.LagerError, match="nicht breite"):
        rohr.verbauen(laenge=500, breite=3)


def test_verbauen_platte_und_kleinteile(cat):
    warnings = []
    kevcad._hooks["warn"] = warnings.append
    platte = lager.teil("platte-multiplex-birke-18")
    deckel = platte.verbauen(breite=800, tiefe=600, name="Deckel")
    bb = deckel.bounding_box()
    assert (bb.min.X, bb.min.Z, bb.size.Z) == pytest.approx((-400, 0, 18))
    form = platte.verbauen(form=Rectangle(500, 400) - Pos(100, 0) * Rectangle(100, 100), name="Form")
    assert form.volume == pytest.approx((500 * 400 - 100 * 100) * 18)
    platte.verbauen(breite=3000, tiefe=1300, name="Riesig")
    assert any("größer als das Standardformat" in w for w in warnings)
    with pytest.raises(lager.LagerError, match="breite und tiefe"):
        platte.verbauen(laenge=800)
    s = lager.teil("schraube-iso4762-m8").verbauen(laenge=60, name="Schrauben/1")
    assert s.bounding_box().min.Z == pytest.approx(-60, abs=0.01) and s.label == "Schrauben/1" and s.material is None
    assert lager.teil("mutter-iso4032-m8").verbauen(name="Mutter").volume > 0
    with pytest.raises(lager.LagerError, match="keine Länge"):
        lager.teil("scheibe-iso7089-m8").verbauen(laenge=3)


# ---------------------------------------------------------------------------------------- Stückliste im Rechenprozess


def run_model(tmp_path, code: str, params=None, regel: bool = True, own=None, builtin=TEST_CATALOG):
    model = tmp_path / "model.py"
    model.write_text(code, encoding="utf-8")
    msgs = []
    runner = Runner(lambda h, p: msgs.append(h))
    res = runner.run({"run": 1, "path": str(model), "code": code, "params": params or {}, "inventar_regel": regel,
                      "catalog": {"builtin": str(builtin), "own": str(own or tmp_path / "eigen")}})
    parts = {h["app"]["name"]: h["app"] for h in msgs if h["type"] == "PART"}
    return res, parts


def test_linking_name_partner_label(tmp_path):
    code = HEAD + """
rohr = lager.teil("vierkantrohr", a=40, s=3)
a = rohr.verbauen(laenge=500, name="A")
show(Pos(100, 0, 0) * a, "A")                    # Name
b = rohr.verbauen(laenge=400, name="Strebe")
show(Pos(200, 0, 0) * b, "Gruppe/Strebe links")  # anderer Name, gleiche Form (verschoben)
c = rohr.verbauen(laenge=300, name="Gebohrt")
c = c - Pos(0, 0, 150) * Rot(90, 0, 0) * Cylinder(4, 60)
show(c, "Rahmen/Gebohrt")                       # anderer Name, gebohrt: label hält
d = rohr.verbauen(laenge=200, name="Kind")
show(Compound(label="Baugruppe", children=[Pos(0, 300, 0) * d]), "BG")   # Kind eines Compound
e = rohr.verbauen(laenge=100, name="Vergessen")   # nie gezeigt
show(Box(40, 40, 100), "Nachgebaut")            # ohne Lagerteil und Material: nicht in der Stückliste
f = rohr.verbauen(laenge=150, name="Verschweisst")
show(f.fuse(Pos(0, 0, 150) * Box(10, 10, 10)), "Schweissteil")  # fuse() behält das label
show(Box(50, 50, 5), "Blech", material="stahl")  # Eigenteil aus Katalogmaterial
show(Box(5, 5, 5), "Klotz")
"""
    res, parts = run_model(tmp_path, code, regel=False)  # ohne Inventar-Regel: Eigenteile wie vor der Regel
    assert res["type"] == "RUN_DONE", res.get("error")
    assert res["inventar_regel"] is False and res["inventar_verstoesse"] == []
    assert all("inventar" not in h for h in parts.values())
    assert parts["A"]["stock"]["laenge"] == 500
    assert parts["Gruppe/Strebe links"]["stock"]["laenge"] == 400
    assert parts["Rahmen/Gebohrt"]["stock"]["laenge"] == 300
    assert parts["BG/Kind"]["stock"]["laenge"] == 200
    assert parts["Schweissteil"]["stock"]["laenge"] == 150
    assert "stock" not in parts["Nachgebaut"] and "stock" not in parts["Blech"]
    assert parts["A"]["material"] == "Stahl S235" and parts["A"]["props"]["mass"] == pytest.approx(
        parts["A"]["props"]["volume"] * 7.85e-3)
    blech = parts["Blech"]
    assert blech["material"] == "stahl" and blech["props"]["mass"] == pytest.approx(50 * 50 * 5 * 7.85e-3)
    assert [round(c, 4) for c in blech["color"]] == [round(c, 4) for c in Color("#8A9099")]
    bom = res["bom"]
    lines = {ln["masse_text"]: ln for ln in bom["lines"]}
    assert lines["500 mm"]["teile"] == ["A"] and lines["400 mm"]["teile"] == ["Gruppe/Strebe links"]
    assert lines["300 mm"]["teile"] == ["Rahmen/Gebohrt"] and lines["200 mm"]["teile"] == ["BG/Kind"]
    assert lines["100 mm"]["teile"] == []
    eigen = [ln for ln in bom["lines"] if ln["eigenteil"]]
    assert [ln["benennung"] for ln in eigen] == ["Blech"] and eigen[0]["preis_je"] == pytest.approx(
        50 * 50 * 5 * 7.85e-6 * 2.4, abs=0.01)
    text = "\n".join(bom["warnings"])
    assert "„Vergessen“" in text and "Klotz" in text and "Nachgebaut" in text and "Verschweisst" not in text


def test_unknown_material_in_show_suggests_catalog(tmp_path):
    res, parts = run_model(tmp_path, HEAD + "show(Box(1, 1, 1), 'X', material='stahl-s253')\n", regel=False)
    assert any("stahl-s235" in w for w in res["warnings"]) and parts["X"]["material"] is None
    res, parts = run_model(tmp_path, HEAD + "show(Box(1, 1, 1), 'X', material='messing')\n", regel=False)
    assert parts["X"]["material"] == "messing" and parts["X"]["props"]["mass"] > 0  # Regel aus: build123d-Namen


def test_lager_error_in_model_points_to_line(tmp_path):
    res, _ = run_model(tmp_path, HEAD + "\nrohr = lager.teil('vierkantrohr', a=45, s=3)\n")
    assert res["type"] == "RUN_FAILED"
    assert res["error"]["line"] == 4 and "Kein Lagerteil vierkantrohr" in res["error"]["message"]
    assert "stock_search" in res["error"]["hint"]


# ------------------------------------------------------------------------------------------------------ Abnahme


def test_acceptance_gestell(tmp_path):
    """Gestell 800 × 600 × 900: 4 Beine, Gehrungsrahmen, Multiplexdeckel, 8 Schrauben M8."""
    res, parts = run_model(tmp_path, SAMPLE.read_text(encoding="utf-8"))
    assert res["type"] == "RUN_DONE", res.get("error")
    assert not res["warnings"]
    assert len(parts) == 4 + 4 + 1 + 8
    lo = [min(p["bbox"]["min"][i] for p in parts.values()) for i in range(3)]
    hi = [max(p["bbox"]["max"][i] for p in parts.values()) for i in range(3)]
    assert lo == pytest.approx([-400, -300, 0]) and hi == pytest.approx([400, 300, 900])
    bom = res["bom"]
    rows = [(ln["benennung"], ln["masse_text"], ln["gehrung"], ln["anzahl"]) for ln in bom["lines"]]
    assert rows == [
        ("Vierkantrohr 40 × 40 × 3", "842 mm", [0.0, 0.0], 4),
        ("Vierkantrohr 40 × 40 × 3", "800 mm", [45.0, 45.0], 2),
        ("Vierkantrohr 40 × 40 × 3", "600 mm", [45.0, 45.0], 2),
        ("Multiplex Birke 18 mm", "800 × 600 mm", [0.0, 0.0], 1),
        ("Zylinderschraube ISO 4762", "M8 × 50", [0.0, 0.0], 8),
    ]
    assert all(ln["teile"] for ln in bom["lines"]) and not bom["warnings"]
    (cut,) = bom["cuts"]
    assert cut["stangen"] == [[842, 842, 842, 842, 800, 800, 600], [600]]
    # Definition 2: 7 Schnitte (Rest 411 mm ist verwertbar) und 1 Schnitt (Rest 5.397 mm): 24 von 12.000 mm
    assert cut["verschnitt_prozent"] == 0.2 and cut["verschnitt_definition"] == "2"
    t = bom["totals"]
    assert t["positionen"] == 5 and t["teile"] == 17 and t["preis_hinweis"] == "Richtpreise, Stand 2026-10"
    assert t["kg"] == pytest.approx(4 * 3.30 * .842 + 2 * 3.30 * .8 + 2 * 3.30 * .6 + 0.48 * 18 * 0.68 + 8 * 0.0238,
                                    abs=0.01)
    assert t["preis"] == pytest.approx(4 * 8 * .842 + 2 * 6.4 + 2 * 4.8 + 21.6 + 8 * 0.32, abs=0.01)
    # quadratisch: Rahmen nur in einer Länge, also 4 Positionen
    res, _ = run_model(tmp_path, SAMPLE.read_text(encoding="utf-8"), params={"breite": 600})
    assert [(ln["masse_text"], ln["anzahl"]) for ln in res["bom"]["lines"]] == [
        ("842 mm", 4), ("600 mm", 4), ("600 × 600 mm", 1), ("M8 × 50", 8)]


@pytest.mark.skipif(not any(builtin_dir().glob("*.json")), reason="mitgelieferter Katalog (K1) fehlt noch")
@pytest.mark.parametrize("sample", ["gestell", "wandhalter"])
def test_samples_run_with_builtin_catalog(tmp_path, sample):
    """Die Beispiele (und damit die Projektvorlage) laufen mit den mitgelieferten Katalogdaten ohne Verstoß."""
    code = (HERE.parents[1] / "samples" / sample / "model.py").read_text(encoding="utf-8")
    res, parts = run_model(tmp_path, code, builtin=builtin_dir())
    assert res["type"] == "RUN_DONE", res.get("error")
    assert res["inventar_verstoesse"] == [] and all(p["inventar"] == "ok" for p in parts.values())
    assert not res["bom"]["warnings"], res["bom"]["warnings"]


# ------------------------------------------------------------------------------------------------- Inventar-Regel


def test_inventory_rule_flags_parts_outside_inventory(tmp_path):
    code = HEAD + """
rohr = lager.teil("vierkantrohr", a=40, s=3)
bein = rohr.verbauen(laenge=500, name="Bein")
show(bein, "Bein")
clip = lager.druckteil(Pos(0, 0, 600) * Box(20, 10, 5), "Clips/Clip 1", material="petg")
show(clip, "Clips/Clip 1")
show(lager.druckteil(Pos(30, 0, 600) * Box(20, 10, 5), "Clips/Clip 2", material="petg-filament"), "Clips/Clip 2")
show(Box(5, 5, 5), "Klotz", material="stahl")
show(Pos(9, 0, 0) * Box(5, 5, 5), "Klotz 2")
"""
    res, parts = run_model(tmp_path, code)
    assert res["type"] == "RUN_DONE", res.get("error")
    assert res["inventar_regel"] is True and res["inventar_verstoesse"] == ["Klotz", "Klotz 2"]
    assert parts["Bein"]["inventar"] == "ok" and parts["Clips/Clip 1"]["inventar"] == "ok"
    assert parts["Klotz"]["inventar"] == "fehlt" and parts["Klotz 2"]["material"] is None
    clip = parts["Clips/Clip 1"]
    assert clip["material"] == "PETG" and "stock" not in clip
    assert clip["druckteil"]["verfahren"] == "3d-druck" and clip["druckteil"]["material"] == "petg"
    assert clip["props"]["mass"] == pytest.approx(1000 * 1.27e-3)
    assert [round(c, 4) for c in clip["color"]] == [round(c, 4) for c in Color("#3A7BD5")]
    bom = res["bom"]
    assert not [ln for ln in bom["lines"] if ln["eigenteil"]]
    (druck,) = [ln for ln in bom["lines"] if ln["art"] == "druckteil"]
    assert druck["anzahl"] == 2 and druck["benennung"] == "Clips/Clip" and druck["stock_id"] is None
    assert druck["kg_je"] == pytest.approx(0.00127, abs=1e-4) and druck["verfahren"] == "3d-druck"
    assert druck["preis_je"] == pytest.approx(0.03, abs=0.005) and druck["masse_text"] == "20 × 10 × 5 mm"
    assert any("Inventar-Regel: 2 Teil(e) nicht aus dem Inventar" in w for w in bom["warnings"])


def test_inventory_rule_materials_only_from_catalog(tmp_path):
    res, _ = run_model(tmp_path, HEAD + "\nshow(Box(1, 1, 1), 'X', material='messing')\n")
    assert res["type"] == "RUN_FAILED" and res["error"]["line"] == 4
    assert "Material 'messing' gibt es im Katalog nicht" in res["error"]["message"]
    assert "material_list" in res["error"]["hint"] or "material_list" in res["error"]["message"]
    res, _ = run_model(tmp_path, HEAD + "show(Box(1, 1, 1), 'X', material='stahl-s253')\n")
    assert res["type"] == "RUN_FAILED" and "stahl-s235" in res["error"]["message"]


def test_druckteil_needs_printable_material(tmp_path, cat):
    with pytest.raises(lager.MaterialError, match="nicht druckbar.*Druckbar: petg"):
        lager.druckteil(Box(10, 10, 10), "X", material="stahl")
    with pytest.raises(lager.LagerError, match="nicht erlaubt"):
        lager.druckteil(Box(10, 10, 10), "X", material="petg", verfahren="fraesen")
    with pytest.raises(lager.LagerError, match="kein Volumen"):
        lager.druckteil(Rectangle(10, 10), "X", material="petg")
    with pytest.raises(lager.MaterialError, match="gibt es im Katalog nicht"):
        lager.druckteil(Box(10, 10, 10), "X", material="pla")
    teil = lager.druckteil(Box(10, 10, 10), "Halter/Clip", material="petg", verfahren="harzdruck")
    assert teil.label == "Halter/Clip" and teil.material is None


def test_proposed_entries_wait_for_release(tmp_path):
    own = tmp_path / "eigen"
    c = Catalog(TEST_CATALOG, own, None)
    rohr = {"id": "rohr-edelstahl-33.7x2.6", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2,6",
            "masse": {"d": 33.7, "s": 2.6},
            "material": "edelstahl-1.4301", "preis": {"je_m": 14.5, "quelle": "Kevin", "stand": "2026-10"}}
    saved, _, _ = c.save("teil", rohr, "eigen", proposal=True)
    assert saved["status"] == "vorgeschlagen" and saved["vorgeschlagen_von"] == "agent"
    assert len(saved["vorgeschlagen_am"]) == 10
    c.save("material", {"id": "pla-matt", "name": "PLA matt", "gruppe": "Kunststoff", "dichte": 1.24,
                        "farbe": "#EEEEEE", "druckbar": True}, proposal=True)
    with pytest.raises(Exception, match="ist freigegeben"):
        c.save("teil", {**rohr, "id": "rohr-en10220-42.4x2.0"}, proposal=True)
    kevcad._hooks["catalog"] = lambda: c
    try:
        with pytest.raises(lager.LagerError, match="wartet auf Kevins Freigabe im Lagerkatalog"):
            lager.teil("rohr-edelstahl-33.7x2.6")
        with pytest.raises(lager.LagerError, match="wartet auf Kevins Freigabe"):
            lager.teil("rohr", d=33.7, s=2.6, material="edelstahl")
        with pytest.raises(lager.MaterialError, match="wartet auf Kevins Freigabe"):
            lager.druckteil(Box(1, 1, 1), "X", material="pla-matt")
        assert "rohr-edelstahl-33.7x2.6" in [h.id for h in lager.suche("33,7")]
        # Kevin gibt in der App frei (CATALOG_SAVE mit status "frei")
        approved = {**c.item("rohr-edelstahl-33.7x2.6"), "status": "frei"}
        saved, _, _ = c.save("teil", approved, "eigen")
        assert saved["status"] == "frei" and "vorgeschlagen_am" not in saved
        assert lager.teil("rohr-edelstahl-33.7x2.6").verbauen(laenge=100).volume > 0
    finally:
        kevcad._hooks.clear()
    # im Lauf: vorgeschlagen ist ein Fehler mit genau diesem Hinweis
    res, _ = run_model(tmp_path, HEAD + "t = lager.druckteil(Box(1, 1, 1), 'X', material='pla-matt')\n", own=own)
    assert res["type"] == "RUN_FAILED" and "wartet auf Kevins Freigabe im Lagerkatalog" in res["error"]["message"]
