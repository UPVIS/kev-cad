"""Katalog: Ebenen zusammenführen, entfernt, Prüfen mit deutschen Meldungen, Suche, Speichern, Löschen, Neu laden."""

import json
import os
import time
from pathlib import Path

import pytest

from kevcad_kernel.catalog import Catalog, CatalogError, own_dir, validate_item, validate_material

TEST_CATALOG = Path(__file__).resolve().parent / "katalog_test"

STAHL = {"id": "stahl-s235", "name": "Stahl S235", "gruppe": "Stahl", "dichte": 7.85, "farbe": "#8A9099",
         "aliase": ["stahl"]}
ROHR = {"id": "rohr-x", "art": "rohr", "name": "Rohr 42,4 × 2,0", "masse": {"d": 42.4, "s": 2.0},
        "material": "stahl-s235", "preis": {"je_m": 4.8, "quelle": "Richtwert", "stand": "2026-10"}}


def write(path: Path, materialien=None, teile=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1}
    if materialien is not None:
        data["materialien"] = materialien
    if teile is not None:
        data["teile"] = teile
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def levels(tmp_path):
    builtin, own, project = tmp_path / "builtin", tmp_path / "eigen", tmp_path / "projekt"
    for d in (builtin, own, project):
        d.mkdir()
    write(builtin / "a.json", [STAHL], [ROHR, {**ROHR, "id": "rohr-weg", "name": "Rohr weg"}])
    return builtin, own, project


def test_levels_override_and_entfernt(levels):
    builtin, own, project = levels
    cat = Catalog(builtin, own, project)
    assert {i["id"] for i in cat.items()} == {"rohr-x", "rohr-weg"}
    assert cat.item("rohr-x")["ebene"] == "mitgeliefert"
    # eigener Katalog: gleicher id ersetzt ganz, entfernt blendet aus
    write(own / "eigene.json", [], [{**ROHR, "name": "Rohr eigen", "preis": {"je_m": 5.5}},
                                    {"id": "rohr-weg", "entfernt": True}])
    item = cat.item("rohr-x")
    assert item["name"] == "Rohr eigen" and item["ebene"] == "eigen" and item["preis"] == {"je_m": 5.5}
    assert cat.item("rohr-weg") is None
    # Projekt überschreibt beide
    write(project / "katalog.json", [{**STAHL, "dichte": 7.9}], [{**ROHR, "name": "Rohr Projekt"}])
    assert cat.item("rohr-x")["name"] == "Rohr Projekt" and cat.item("rohr-x")["ebene"] == "projekt"
    assert cat.material("stahl-s235")["dichte"] == 7.9
    # Projekt gewechselt: Projektebene weg
    cat.set_project(None)
    assert cat.item("rohr-x")["ebene"] == "eigen"


def test_invalid_entries_are_skipped_with_warning(levels):
    builtin, own, project = levels
    write(own / "kaputt.json", [{"id": "x", "name": "X"}], [{"id": "Y Rohr", "art": "rohr"}])
    (own / "nichtjson.json").write_text("{kein json", encoding="utf-8")
    cat = Catalog(builtin, own, project)
    ids = {i["id"] for i in cat.items()}
    assert "Y Rohr" not in ids and cat.material("x") is None
    text = "\n".join(cat.warnings)
    assert "kein gültiges JSON" in text and "dichte fehlt" in text and "übersprungen" in text


def test_reload_on_file_change(levels):
    builtin, own, project = levels
    cat = Catalog(builtin, own, project)
    assert cat.item("rohr-neu") is None
    write(own / "eigene.json", [], [{**ROHR, "id": "rohr-neu"}])
    assert cat.item("rohr-neu") is not None
    time.sleep(0.01)
    write(own / "eigene.json", [], [{**ROHR, "id": "rohr-neu", "name": "geändert"}])
    os.utime(own / "eigene.json", ns=(time.time_ns(), time.time_ns() + 10_000_000))
    assert cat.item("rohr-neu")["name"] == "geändert"


def test_validation_messages():
    assert validate_material(STAHL) == []
    errs = validate_material({"id": "Stahl X", "name": "", "dichte": 78.5, "farbe": "grau"})
    text = "\n".join(errs)
    assert "Kleinbuchstaben" in text and "Vorschlag: 'stahl-x'" in text
    assert "dichte 78.5" in text and "farbe" in text and "gruppe" in text
    assert validate_item(ROHR, {"stahl-s235"}) == []
    errs = validate_item({"id": "rohr-1", "art": "rohrr", "name": "R", "masse": {}, "material": "stahl-s253"},
                         {"stahl-s235"})
    text = "\n".join(errs)
    assert "meinten Sie 'rohr'" in text and "meinten Sie 'stahl-s235'" in text
    errs = validate_item({**ROHR, "masse": {"d": 10, "s": 6}}, {"stahl-s235"})
    assert any("zu dick" in e for e in errs)
    errs = validate_item({**ROHR, "masse": {"d": 42.4, "s": 2, "x": 1}}, {"stahl-s235"})
    assert any("kennt für art 'rohr' nur d, s" in e for e in errs)
    errs = validate_item({**ROHR, "preis": {"je_m": -1, "stand": "Oktober"}}, None)
    assert any("≥ 0" in e for e in errs) and any("JJJJ-MM" in e for e in errs)
    nut = {"id": "n", "art": "nutprofil", "name": "N", "material": "m",
           "masse": {"raster": 40, "nut": 8, "a": 40, "b": 70, "variante": "mittel"}}
    text = "\n".join(validate_item(nut, None))
    assert "kein Vielfaches" in text and "variante" in text
    schraube = {"id": "s", "art": "schraube", "name": "S", "material": "m",
                "masse": {"typ": "SocketHeadCapScrew", "norm": "iso4762", "groesse": "M8"}}
    text = "\n".join(validate_item(schraube, None))
    assert "Meinten Sie 'M8-1.25'" in text
    assert validate_item({**schraube, "masse": {**schraube["masse"], "groesse": "M8-1.25"}}, None) == []
    text = "\n".join(validate_item({**schraube, "masse": {**schraube["masse"], "typ": "Zylinderschraube"}}, None))
    assert "keine bd_warehouse-Klasse" in text


def test_search():
    cat = Catalog(TEST_CATALOG, TEST_CATALOG / "gibtsnicht", None)
    ids = lambda q, **kw: [i["id"] for i in cat.search(q, **kw)[0]]  # noqa: E731
    assert ids("40x40x3")[0] == "vierkantrohr-en10219-40x40x3"
    assert ids("40×40×3")[0] == "vierkantrohr-en10219-40x40x3"
    assert ids("Vierkantrohr 40")[0] == "vierkantrohr-en10219-40x40x3"
    assert ids("quadratrohr") == ["vierkantrohr-en10219-40x40x3"]
    assert ids("42,4") == ["rohr-en10220-42.4x2.0"] == ids("42.4x2")
    assert ids("edelstahl rohr 33,7") == ["rohr-iso1127-33.7x2"]
    assert ids("edelstahlrohr") == ["rohr-iso1127-33.7x2"]
    assert ids("m8") == ["schraube-iso4762-m8", "mutter-iso4032-m8", "scheibe-iso7089-m8"]
    assert ids("m8x60") == ["schraube-iso4762-m8"] or "schraube-iso4762-m8" in ids("m8x60")
    assert ids("multiplex 18") == ["platte-multiplex-birke-18"]
    assert ids("kantholz") == ["kvh-60x80"] and ids("80x60") == ["kvh-60x80"]
    assert ids("40", art="nutprofil") == ["nutprofil-40x40-n8-leicht"]
    assert ids("rohr-en10220-42.4x2.0")[0] == "rohr-en10220-42.4x2.0"
    assert ids("gibtsnicht") == []
    items, total = cat.search("", limit=3)
    assert len(items) == 3 and total == 11
    assert [m["id"] for m in cat.search_materials("holz")] == ["fichte-kvh", "multiplex-birke"]


def test_find_material_by_alias_and_name():
    cat = Catalog(TEST_CATALOG, TEST_CATALOG / "gibtsnicht", None)
    assert cat.find_material("stahl")["id"] == "stahl-s235"
    assert cat.find_material("Stahl S235")["id"] == "stahl-s235"
    assert cat.find_material("V2A")["id"] == "edelstahl-1.4301"
    assert cat.find_material("multiplex_birke")["id"] == "multiplex-birke"
    assert cat.find_material("aluminium") is None
    assert "stahl-s235" in cat.material_suggestions("stahl-s253")


def test_save_and_delete_own_level(levels, tmp_path):
    builtin, own, project = levels
    cat = Catalog(builtin, own, project)
    entry = {"id": "rohr-edelstahl-33.7x2", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2",
             "masse": {"d": 33.7, "s": 2}, "material": "stahl-s235", "preis": {"je_m": 14.5}, "ebene": "eigen"}
    saved, path, notes = cat.save("teil", entry, "eigen")
    assert path == own / "eigene.json" and saved["ebene"] == "eigen"
    data = json.loads(path.read_text(encoding="utf-8"))
    stored = data["teile"][0]
    assert "ebene" not in stored and stored["preis"]["quelle"] == "eigene Angabe" and len(stored["preis"]["stand"]) == 7
    assert any("stand fehlte" in n for n in notes)
    assert cat.item("rohr-edelstahl-33.7x2")["ebene"] == "eigen"
    # ersetzen in derselben Datei
    saved, path2, notes = cat.save("teil", {**entry, "preis": {"je_m": 15, "quelle": "Kevin", "stand": "2026-10"}})
    assert path2 == path and "ersetzt" in notes[0]
    assert len(json.loads(path.read_text(encoding="utf-8"))["teile"]) == 1
    # überschreibt ein mitgeliefertes Teil
    saved, _, notes = cat.save("teil", {**ROHR, "name": "Rohr billiger"})
    assert "mitgeliefert" in notes[0] and cat.item("rohr-x")["name"] == "Rohr billiger"
    # ungültig: alle Fehler auf einmal
    with pytest.raises(CatalogError) as err:
        cat.save("teil", {"id": "x", "art": "rohr", "name": "X", "masse": {"d": 10}, "material": "holz"})
    assert "masse.s fehlt" in str(err.value) and "Material 'holz'" in str(err.value)
    with pytest.raises(CatalogError, match="nicht beschreibbar"):
        cat.save("teil", ROHR, "mitgeliefert")
    # löschen: eigenes Teil weg, mitgeliefertes gilt wieder
    _, msg = cat.delete("teil", "rohr-x", "eigen")
    assert "gilt wieder" in msg and cat.item("rohr-x")["name"] == "Rohr 42,4 × 2,0"
    # mitgeliefertes Teil ausblenden
    _, msg = cat.delete("teil", "rohr-weg", "eigen")
    assert "ausgeblendet" in msg and cat.item("rohr-weg") is None
    with pytest.raises(CatalogError, match="gibt es nicht"):
        cat.delete("teil", "rohr-gibtsnicht")
    # Material
    saved, _, notes = cat.save("material", {"id": "eiche", "name": "Eiche", "gruppe": "Holz", "dichte": 0.69,
                                            "farbe": "#B08850", "preis_je_kg": 3.2, "aliase": ["Eiche massiv"]})
    assert cat.find_material("eiche massiv")["id"] == "eiche" and any("preis_stand" in n for n in notes)
    cat.delete("material", "eiche")
    assert cat.material("eiche") is None


def test_save_project_level(levels):
    builtin, own, project = levels
    cat = Catalog(builtin, own, None)
    with pytest.raises(CatalogError, match="Kein Projekt"):
        cat.save("teil", {**ROHR, "id": "rohr-p"}, "projekt")
    cat.set_project(project)
    _, path, _ = cat.save("teil", {**ROHR, "id": "rohr-p"}, "projekt")
    assert path == project / "katalog.json" and cat.item("rohr-p")["ebene"] == "projekt"
    cat.delete("teil", "rohr-p", "projekt")
    assert cat.item("rohr-p") is None


def test_own_dir_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("KEVCAD_CATALOG_DIR", str(tmp_path / "k"))
    assert own_dir("/irgendwo/de.upvis.kevcad/kernel.sock") == tmp_path / "k"
    monkeypatch.delenv("KEVCAD_CATALOG_DIR")
    app = tmp_path / "de.upvis.kevcad.test.k2"
    app.mkdir()
    assert own_dir(str(app / "kernel.sock")) == app.resolve() / "katalog"
    assert own_dir(str(tmp_path / "k.sock")).parts[-3:] == ("Application Support", "de.upvis.kevcad", "katalog")
