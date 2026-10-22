"""Druckvorschau mit Bambu Studio (DRUCKVORSCHAU.md): Profile, Slicen einer Gruppe, Abgleich, genaue Anordnung,
Platten und 3MF-Export als Bambu-Projekt (nachgeslict wie in der Vorschau). Nur mit /Applications/BambuStudio.app
(auf dem Mac mini übersprungen)."""

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.druck import slicer as sl

BAMBU = Path("/Applications/BambuStudio.app")  # conftest.py schaltet Bambu Studio für alle anderen Tests ab
pytestmark = pytest.mark.skipif(not (BAMBU / "Contents/MacOS/BambuStudio").exists(),
                                reason="Bambu Studio nicht installiert")


@pytest.fixture(autouse=True)
def mit_bambu(monkeypatch):
    monkeypatch.setenv("KEVCAD_BAMBU_APP", str(BAMBU))
    yield

HEAD = "from build123d import *\nfrom kevcad import lager, show, param\n"
CODE = HEAD + """
winkel = Box(40, 20, 4, align=(Align.MIN, Align.MIN, Align.MIN)) + Box(4, 20, 30, align=(Align.MIN, Align.MIN, Align.MIN))
winkel -= Pos(20, 10, 0) * Cylinder(2.5, 10)
for i in range(4):
    show(Pos(i * 60, 0, 0) * lager.druckteil(winkel, f"Winkel {i}", material="petg", zweck="tragend"), f"Halter/Winkel {i}")
show(Pos(0, 80, 0) * lager.druckteil(Box(30, 30, 6), "Deckel", material="petg", zweck="zier", anzahl=2), "Deckel")
"""


def test_profile_aufgeloest():
    assert sl.filament_name("petg") == "Bambu PETG Basic @BBL X1C"
    assert sl.filament_name("pla") in ("Amazon Basics PLA", "Bambu PLA Basic @BBL P1P")
    assert sl.prozess_name(0.16) == "0.16mm Optimal @BBL P1P"
    name, p = sl.prozess_profil({"schicht_mm": 0.2, "waende": 4, "fuellung": 0.25, "muster": "gyroid",
                                 "stuetzen": "baum", "brim": True})
    assert name == "0.20mm Standard @BBL P1P" and "inherits" not in p
    assert (p["wall_loops"], p["sparse_infill_density"], p["sparse_infill_pattern"]) == ("4", "25%", "gyroid")
    assert (p["enable_support"], p["support_type"], p["brim_type"]) == ("1", "tree(auto)", "outer_only")
    m = sl.maschinen_profil()
    assert m["printable_area"] == ["0x0", "256x0", "256x256", "0x256"] and m["bed_exclude_area"][2] == "18x28"
    assert sl.version()


def test_filamentprofile_passen_zum_p1p():
    """Jedes Material bekommt ein Profil, dessen compatible_printers (mit Vererbung) den P1P 0.4 nennt; ein Wunsch
    für einen anderen Drucker wird übergangen (Bambu Studio markierte ihn in der Oberfläche als unpassend)."""
    for m in sl.FILAMENTE:
        name = sl.filament_name(m)
        cp = sl.profil("filament", name).get("compatible_printers") or []
        assert sl.MASCHINE in cp, (m, name)
    assert sl.filament_name("petg", "Generic PETG") == "Generic PETG @BBL P1P"
    assert not sl.kompatibel("Bambu PETG Basic @BBL A1M 0.4 nozzle")
    assert sl.filament_name("petg", "Bambu PETG Basic @BBL A1M 0.4 nozzle") == "Bambu PETG Basic @BBL X1C"
    assert all(sl.kompatibel(n) for n in sl._filament_suche("petg", "p1p-0.4"))


def test_druckplatte(tmp_path):
    """Die Kommandozeile nimmt sonst die Cool Plate, und PETG bricht dort ab; Standard ist die Texturplatte."""
    assert sl.platte_name(None) == "Textured PEI Plate"
    assert sl.platte_name("glatt") == "High Temp Plate" and sl.platte_name("Cool Plate") == "Cool Plate"
    with pytest.raises(sl.SlicerFehler):
        sl.platte_name("Glasplatte")
    assert not sl.platte_passt("Bambu PETG Basic @BBL X1C", "Cool Plate")
    assert sl.platte_passt("Bambu PETG Basic @BBL X1C", "Textured PEI Plate")
    _, p = sl.prozess_profil({"schicht_mm": 0.2})
    assert p["curr_bed_type"] == "Textured PEI Plate"
    stl = tmp_path / "klotz.stl"
    import numpy as np

    P = np.array([[x, y, z] for z in (0, 10) for y in (-10, 10) for x in (-15, 15)], dtype=float)
    T = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                  [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    sl.schreibe_stl(stl, P, T)
    ok = sl.slice_teil(stl, {"schicht_mm": 0.2}, "Bambu PETG Basic @BBL X1C", tmp_path / "a")
    assert ok["zeit_s"] > 0
    with pytest.raises(sl.SlicerFehler, match="plate"):
        sl.slice_teil(stl, {"schicht_mm": 0.2}, "Bambu PETG Basic @BBL X1C", tmp_path / "b", platte="Cool Plate")


def test_selbst_geschriebenes_3mf_laedt_in_bambu_studio(tmp_path, monkeypatch):
    """Rückfall ohne Bambu Studio: das eigene 3MF (eine Platte) lädt und slict in Bambu Studio mit allen Teilen."""
    import numpy as np

    from kevcad_kernel.druck.dreimf import schreibe_3mf

    monkeypatch.setenv("KEVCAD_DRUCK_CACHE", str(tmp_path / "cache"))
    stl = tmp_path / "klotz.stl"
    P = np.array([[x, y, z] for z in (0, 10) for y in (-10, 10) for x in (-15, 15)], dtype=float)
    T = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                  [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    sl.schreibe_stl(stl, P, T)
    liste = [sl.PlattenObjekt(stl, 60, 60, 0, name="A"), sl.PlattenObjekt(stl, 160, 60, 90, name="B")]
    r = schreibe_3mf(tmp_path / "eigen.3mf", [liste])
    assert r["objekte"] == 2
    assert sl.pruefe_3mf(tmp_path / "eigen.3mf", tmp_path / "info") == 2
    pr = sl.schreibe_profile(tmp_path / "s", {"schicht_mm": 0.2}, ["Bambu PETG Basic @BBL X1C"])
    res = sl.ausfuehren([*sl._profil_args(pr), "--slice", "0", str(tmp_path / "eigen.3mf")], tmp_path / "s")
    for g in (tmp_path / "s").glob("*.gcode"):
        g.unlink()
    assert [o["name"] for o in res["sliced_plates"][0]["objects"]] == ["A", "B"]


def _gcode_temperaturen(pfad: str | Path, aus: Path) -> tuple[dict, list[int], list[str]]:
    """3MF slicen wie beim Öffnen in Bambu Studio; (result.json, Düsentemperaturen aus M104/M109 im G-Code ohne 0 und
    die 75 °C des Vorprogramms, Kopfzeilen mit filament_settings_id/nozzle_temperature/textured_plate_temp)."""
    import re

    aus.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(sl.programm()), "--slice", "0", "--outputdir", str(aus), str(pfad)], cwd=str(aus),
                       capture_output=True, text=True, timeout=300)
    ergebnis = json.loads((aus / "result.json").read_text())
    assert r.returncode == 0, ergebnis.get("error_string")
    temps: list[int] = []
    kopf: list[str] = []
    for g in sorted(aus.glob("*.gcode")):
        t = g.read_text(errors="replace")
        temps += [int(x) for x in re.findall(r"^M10[49] S(\d+)", t, flags=re.M) if int(x) not in (0, 75)]
        kopf += re.findall(r"^; (?:filament_settings_id|nozzle_temperature|textured_plate_temp) = .*", t, flags=re.M)
        g.unlink()
    return ergebnis, temps, kopf


def test_filament_preset_im_3mf_und_gcode(tmp_path, monkeypatch):
    """Gegen das installierte Bambu Studio (Kevins Benutzerprofile nur gelesen): Das Preset eines Filaments der Liste
    geht vollständig und sprechend benannt ins Bambu-Projekt (filament_settings_id, inherits_group = Systemprofil)
    und seine Temperatur kommt mit --slice 0 im G-Code an: PolyLite PETG ohne Abweichungen 255 °C, ein Testfilament
    mit belegter Abweichung 238 °C. Dazu der P1P-Start-G-Code aus der include-Vorlage."""
    import numpy as np

    from kevcad_kernel.druck import filamente as fl
    from kevcad_kernel.druck import filamentwahl as fw
    from kevcad_kernel.druck import vorschau as vs

    monkeypatch.setenv("KEVCAD_DRUCK_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("KEVCAD_FILAMENTE", str(tmp_path / "filamente.json"))
    sl.index_leeren()
    for f in fl.liste():  # Startbestand passt zum P1P 0.4 (Amazon Basics PLA nur, wenn Kevins Profil da ist)
        if f["id"] != "amazon-basics-pla" or sl.profil_vorhanden("filament", "Amazon Basics PLA"):
            assert fl.pruefe(f) == [], f["id"]
    spule = {"kennung": "S-0001", "material": "petg", "gramm": 900, "gramm_voll": 1000, "name": "PolyLite PETG gelb",
             "hersteller": "Polymaker"}
    w = fw.waehle("petg", vs.projekt_einstellungen({}, [spule]))
    assert (w.filament, w.quelle, w.basis) == ("polymaker-polylite-petg-gelb", "spule", "PolyLite PETG @BBL P1P")
    assert (w.temperaturen["duese"], w.temperaturen["platte"], w.temperaturen["hersteller"]) == (255, 80, "Polymaker")
    assert fw.basis_vorschlag("Polymaker", "PolyLite PETG", "petg") == "PolyLite PETG @BBL P1P"  # nicht Kevins Kopie
    assert fw.basis_vorschlag("Bambu Lab", "PETG Basic", "petg") == "Bambu PETG Basic @BBL X1C"
    test = fl.define({"id": "test-petg", "hersteller": "Test", "produkt": "PETG", "material": "petg", "farbe": "rot",
                      "farbe_hex": "#CC2222", "preset": {"basis": "PolyLite PETG @BBL P1P", "abweichungen": [
                          {"schluessel": "duese", "wert": 238, "quelle": "Test des Mechanismus (kein echtes Filament)"},
                          {"schluessel": "duese_erste_schicht", "wert": 238, "quelle": "Test"}]}})
    P = np.array([[x, y, z] for z in (0, 10) for y in (-10, 10) for x in (-15, 15)], dtype=float)
    T = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                  [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    stl = tmp_path / "klotz.stl"
    sl.schreibe_stl(stl, P, T)
    for f, duese in ((fl.finde("polymaker-polylite-petg-gelb"), 255), (test, 238)):
        spec = fl.preset_spec(f)
        res = sl.export_3mf([[sl.PlattenObjekt(stl, 128, 128, 0, name="Klotz")]], spec, tmp_path / f"{f['id']}.3mf",
                            tmp_path / f"a-{f['id']}")
        with zipfile.ZipFile(res["pfad"]) as z:
            ps = json.loads(z.read("Metadata/project_settings.config"))
        assert ps["filament_settings_id"] == [fl.preset_name(f)]
        assert ps["inherits_group"][1] == "PolyLite PETG @BBL P1P"  # Projekt-Preset mit diesem Elternteil
        assert ps["nozzle_temperature"][0] == str(duese) and ps["filament_colour"] == [spec["farbe"]]
        assert ps["machine_start_gcode"].startswith(";===== machine: P1P")  # include-Vorlage, nicht der allgemeine
        ergebnis, temps, kopf = _gcode_temperaturen(res["pfad"], tmp_path / f"g-{f['id']}")
        # 250 °C heizt das P1P-Vorprogramm zum Abwischen, 140 °C beim Nivellieren, Düse − 20 °C zum Reinigen
        assert temps and max(t for t in temps if t != 250) == duese and duese - 20 in temps, temps
        assert duese in temps and f'; filament_settings_id = "{fl.preset_name(f)}"' in kopf, kopf


def _nachslicen(pfad: str | Path, aus: Path) -> dict:
    """Ein 3MF so slicen, wie Kevin es in Bambu Studio öffnet (Projekt-Einstellungen aus der Datei); result.json."""
    aus.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(sl.programm()), "--slice", "0", "--min-save", "--outputdir", str(aus), str(pfad)],
                       cwd=str(aus), capture_output=True, text=True, timeout=300)
    for g in aus.glob("*.gcode"):
        g.unlink()
    ergebnis = json.loads((aus / "result.json").read_text())
    assert r.returncode == 0, ergebnis.get("error_string")
    return ergebnis


def _namen_lagen(pfad: str | Path) -> dict[str, tuple[int, float, float]]:
    """Objektname → (Platte, x, y) aus Metadata/model_settings.config (dort liest Bambu Studio die Namen; die Lage aus
    der Matrix des Teils). Bambu Studio schreibt die Objekte nicht immer in der Reihenfolge der Montageliste, deshalb
    nach Lage vergleichen. Prüft auch, dass Objekt- und Teilname gleich sind und kein „assemble_…“ übrig ist."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(pfad) as z:
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    platte_von = {}
    for pl in cfg.findall("plate"):
        nr = int(next(m.get("value") for m in pl.findall("metadata") if m.get("key") == "plater_id"))
        for inst in pl.findall("model_instance"):
            platte_von[next(m.get("value") for m in inst.findall("metadata") if m.get("key") == "object_id")] = nr
    out = {}
    for o in cfg.findall("object"):
        name = next(m.get("value") for m in o.findall("metadata") if m.get("key") == "name")
        part = o.find("part")
        teil = next(m.get("value") for m in part.findall("metadata") if m.get("key") == "name")
        mat = next(m.get("value") for m in part.findall("metadata") if m.get("key") == "matrix").split()
        assert teil == name and not name.startswith("assemble_"), (name, teil)
        assert name not in out, f"{name} doppelt"
        out[name] = (platte_von[o.get("id")], round(float(mat[3]), 1), round(float(mat[7]), 1))
    return out


def test_export_3mf_traegt_die_teilnamen(tmp_path, monkeypatch):
    """Bambu Studio nennt die Objekte einer Montageliste „assemble_1“ …; nach dem Export tragen sie die Teilnamen
    (auch Umlaute, Sonderzeichen, gekürzt, Wiederholungen gezählt), das 3MF lädt (pruefe_3mf) und slict, und der
    Slicer meldet die Objekte unter diesen Namen. Platten mit Lücken (Teile weggelassen) laden und slicen auch."""
    import numpy as np

    monkeypatch.setenv("KEVCAD_DRUCK_CACHE", str(tmp_path / "cache"))
    P = np.array([[x, y, z] for z in (0, 10) for y in (-10, 10) for x in (-15, 15)], dtype=float)
    T = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                  [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    stl = tmp_path / "g1.stl"
    sl.schreibe_stl(stl, P, T)
    lang = "Kugelschieber/Fahrwerk/Vorderachse/Halterung/Stangenhalter vorn links (Druck)"
    platten = [[sl.PlattenObjekt(stl, 40, 60, 0, name="Kugelschieber/Lenksperre links (Druck)"),
                sl.PlattenObjekt(stl, 200, 200, 90, name="Rückwand & \"Größe\" <1>")],   # Lücke dazwischen
               [sl.PlattenObjekt(stl, 128, 128, 0, name=lang),
                sl.PlattenObjekt(stl, 60, 200, 0, name="Deckel"),
                sl.PlattenObjekt(stl, 200, 60, 0, name="Deckel")]]
    res = sl.export_3mf(platten, "Bambu PETG Basic @BBL X1C", tmp_path / "namen.3mf", tmp_path / "arbeit",
                        platten_namen=["Platte 2", "Platte 3"])
    erwartet = ["Kugelschieber/Lenksperre links (Druck)", "Rückwand & \"Größe\" <1>",
                "Kugelschieber/…/Stangenhalter vorn links (Druck)", "Deckel", "Deckel (2)"]
    assert res["geprueft"] and res["objekte"] == 5 and res["namen"] == erwartet and res["benannt"] == 5
    lagen = [(1, 40.0, 60.0), (1, 200.0, 200.0), (2, 128.0, 128.0), (2, 60.0, 200.0), (2, 200.0, 60.0)]
    assert _namen_lagen(res["pfad"]) == dict(zip(erwartet, lagen))
    ergebnis = _nachslicen(res["pfad"], tmp_path / "aus")
    assert [sorted(o["name"] for o in p["objects"]) for p in ergebnis["sliced_plates"]] == \
        [sorted(erwartet[:2]), sorted(erwartet[2:])]
    assert all(p["total_predication"] > 0 for p in ergebnis["sliced_plates"])
    with zipfile.ZipFile(res["pfad"]) as z:
        cfg = z.read("Metadata/model_settings.config").decode()
    assert 'value="Platte 2"' in cfg and 'value="Platte 3"' in cfg and "assemble_" not in cfg


@pytest.fixture(scope="module")
def env():
    alt = {k: os.environ.get(k) for k in ("KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH", "KEVCAD_BAMBU_APP")}
    tmp = Path(tempfile.mkdtemp(prefix="kcds", dir=tempfile.gettempdir()))
    os.environ.update({"KEVCAD_DRUCK_CACHE": str(tmp / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(tmp / "abgleich.json"),
                       "KEVCAD_BAMBU_APP": str(BAMBU)})
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


def test_slicer_im_hintergrund_und_export(env):
    rt, app, tmp = env["rt"], env["app"], env["tmp"]
    assert rt.project_new(str(tmp / "Slicer"), "empty")["ok"]
    assert rt.model_write(CODE)["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    _, _, erst, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h["run"] == res["run"], start=start)
    assert erst["stand"] == "schaetzung" and erst["slicer"]["zustand"] in ("wartet", "rechnet")
    _, _, v, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h["slicer"]["zustand"] in ("fertig", "fehler"),
                              start=start, timeout=300)
    assert v["slicer"]["zustand"] == "fertig" and v["slicer"]["meldung"] is None, v["slicer"]
    assert v["stand"] == "slicer" and v["slicer"]["version"]
    for t in v["teile"]:
        assert t["stand"] == "slicer" and t["abweichung"] is not None and abs(t["abweichung"]) < 0.35, t
    assert all(p["anordnung"] == "slicer" and p["stand"] == "slicer" for p in v["platten"])
    assert sum(len(p["teile"]) for p in v["platten"]) == 6
    ab = json.loads((tmp / "abgleich.json").read_text())
    assert any(k.endswith("|petg") for k in ab["faktoren"])
    # Zwischenspeicher: gleicher Stand noch einmal, sofort aus dem Speicher
    start = app.mark()
    res2 = rt.run()
    _, _, v2, _ = app.wait_for(lambda h: h["type"] == "PRINT_PREVIEW" and h["run"] == res2["run"]
                               and h["slicer"]["zustand"] == "fertig", start=start, timeout=60)
    assert v2["summe"]["zeit_s"] == v["summe"]["zeit_s"]
    # Ohne Filament schreibt der Export nichts und verlangt die Rückfrage an Kevin
    frage = rt.druck_export(str(tmp / "ohne-filament.3mf"))
    assert not frage["ok"] and frage["filament_frage"] and "Frag Kevin nach dem Filament" in frage["fehler"]
    assert [x["id"] for x in frage["vorschlaege"]["petg"]["liste"]] == ["polymaker-polylite-petg-gelb",
                                                                         "bambu-petg-basic"]
    assert not (tmp / "ohne-filament.3mf").exists()
    # 3MF als Bambu-Projekt: nachgeslict wie in der Vorschau
    ex = rt.druck_export(str(tmp / "platten.3mf"), filament={"petg": "polymaker-polylite-petg-gelb"})
    assert ex["ok"] and ex["geprueft"] and ex["fehler"] is None and ex["pfade"] == [ex["pfad"]], ex
    with zipfile.ZipFile(ex["pfad"]) as z:
        ps = json.loads(z.read("Metadata/project_settings.config"))
        einst = z.read("Metadata/model_settings.config").decode()
    assert ps["printer_settings_id"] == "Bambu Lab P1P 0.4 nozzle"
    # Das gewählte Filament: Preset „Polymaker PolyLite PETG gelb (Kev CAD)“ auf Basis „PolyLite PETG @BBL P1P“
    assert ps["filament_settings_id"] == ["Polymaker PolyLite PETG gelb (Kev CAD)"]
    assert ps["inherits_group"][1] == "PolyLite PETG @BBL P1P"
    assert ps["nozzle_temperature"][0] == "255" and ps["textured_plate_temp"] == ["80"]
    m_petg = v2["summe"]["material"][0]  # die Vorschau nahm vorher das erste PETG der Liste an
    assert (m_petg["filament_id"], m_petg["filament_quelle"]) == ("polymaker-polylite-petg-gelb", "standard")
    assert m_petg["temperaturen"]["duese"] == 255 and m_petg["temperaturen"]["platte"] == 80
    d0 = ex["dateien"][0]
    assert (d0["filament"], d0["filament_id"], d0["filament_basis"], d0["filament_quelle"], d0["abweichungen"]) == \
        ("Polymaker PolyLite PETG gelb (Kev CAD)", "polymaker-polylite-petg-gelb", "PolyLite PETG @BBL P1P", "kevin",
         [])
    assert ex["filamente"]["petg"]["temperaturen"]["platte"] == 80
    assert any("Filament Polymaker PolyLite PETG gelb (1,75 mm)" in h and "keine Abweichungen" in h
               and "Düse 255 °C, Texturplatte 80 °C" in h for h in ex["hinweise"]), ex["hinweise"]
    # zuletzt gewählt (druck.json): Annahme der Vorschau und Vorschlag der nächsten Rückfrage
    assert json.loads((tmp / "Slicer" / "druck.json").read_text())["filament"]["petg"]["id"] == \
        "polymaker-polylite-petg-gelb"
    assert ps["curr_bed_type"] == "Textured PEI Plate"  # sonst nimmt die Kommandozeile Cool Plate, PETG bricht ab
    assert v["einstellungen"]["platte"] == "Textured PEI Plate"
    assert 'key="wall_loops" value="4"' in einst and 'key="sparse_infill_pattern" value="gyroid"' in einst
    aus = tmp / "nachgeslict"
    aus.mkdir()
    r = subprocess.run([str(sl.programm()), "--slice", "0", "--min-save", "--outputdir", str(aus), ex["pfad"]],
                       cwd=str(aus), capture_output=True, text=True, timeout=180)
    for g in aus.glob("*.gcode"):
        g.unlink()
    ergebnis = json.loads((aus / "result.json").read_text())
    assert r.returncode == 0, ergebnis.get("error_string")
    zeiten = [p["total_predication"] for p in ergebnis["sliced_plates"]]
    assert len(zeiten) == len(v["platten"])
    for p, z in zip(v["platten"], zeiten):
        assert abs(z / p["zeit_s"] - 1) < 0.02, (p["zeit_s"], z)
    # Objektnamen: die Teilnamen statt „assemble_…“, in Bambu Studio und im Slicer-Ergebnis (Platten der Vorschau, aus
    # der exportiert wurde: v2; welches von gleichen Teilen wo liegt, kann von Lauf zu Lauf wechseln)
    erwartet = sl.objekt_namen([sl.PlattenObjekt(Path("x.stl"), 0, 0, 0, name=t["name"])
                                for p in v2["platten"] for t in p["teile"]])
    namen_lagen = _namen_lagen(ex["pfad"])
    lagen_v2 = [(p["nr"], t["x"], t["y"]) for p in v2["platten"] for t in p["teile"]]
    assert ex["dateien"][0]["objekte"] == erwartet and set(namen_lagen) == set(erwartet)
    for name, (nr, x, y) in zip(erwartet, lagen_v2):  # jedes Objekt heißt wie das Teil an seiner Stelle
        assert namen_lagen[name][0] == nr and namen_lagen[name][1:] == pytest.approx((x, y), abs=0.6), name
    assert sorted(o["name"] for p in ergebnis["sliced_plates"] for o in p["objects"]) == sorted(erwartet)
    assert "Halter/Winkel 0" in erwartet and "Deckel (2)" in erwartet
    # Auswahl: ohne Winkel 0 und die Deckel; die übrigen Winkel bleiben an ihrer Stelle, laden und slicen
    ex3 = rt.druck_export(str(tmp / "auswahl.3mf"), ohne=["Halter/Winkel 0", "Deckel"],
                          filament="polymaker-polylite-petg-gelb")
    assert ex3["ok"] and ex3["geprueft"], ex3
    assert sorted(ex3["teile"]) == ["Halter/Winkel 1", "Halter/Winkel 2", "Halter/Winkel 3"]
    assert {(w["name"], w["grund"], w["anzahl"]) for w in ex3["weggelassen"]} == {("Halter/Winkel 0", "ohne", 1),
                                                                                 ("Deckel", "ohne", 2)}
    e3 = _nachslicen(ex3["pfad"], tmp / "auswahl")
    assert sorted(o["name"] for p in e3["sliced_plates"] for o in p["objects"]) == sorted(ex3["teile"])
    assert set(_namen_lagen(ex3["pfad"])) == set(ex3["teile"])
    assert e3["sliced_plates"][0]["total_predication"] < zeiten[0]
    # Spule im Bestand: Vorschlag der Rückfrage (zuletzt gewählt und die Spule mit ihrem Filament)
    (tmp / "Slicer" / "bestand.json").write_text(json.dumps({
        "version": 1, "einstellungen": {}, "posten": {},
        "filament": [{"kennung": "S-0001", "material": "petg", "gramm": 640, "gramm_voll": 1000,
                      "name": "Bambu PETG Basic", "hersteller": "Bambu Lab"}]}))
    rt.run()
    assert rt.druckvorschau()["summe"]["material"][0]["filament_quelle"] == "zuletzt"
    frage = rt.druck_export(str(tmp / "x.3mf"))
    vor = frage["vorschlaege"]["petg"]
    assert vor["zuletzt"] == "polymaker-polylite-petg-gelb" and vor["spulen"][0]["filament"] == "bambu-petg-basic"
    # kevcad.json druck.platte überschreibt die Platte (gleicher Schlüssel wie Phase 8)
    einst = tmp / "Slicer" / "kevcad.json"
    d = json.loads(einst.read_text())
    d["druck"] = {"platte": "glatt"}
    einst.write_text(json.dumps(d))
    ex2 = rt.druck_export(str(tmp / "glatt.3mf"), filament="polymaker-polylite-petg-gelb")
    assert ex2["ok"], ex2
    with zipfile.ZipFile(ex2["pfad"]) as z:
        assert json.loads(z.read("Metadata/project_settings.config"))["curr_bed_type"] == "High Temp Plate"
    assert any("High Temp Plate" in h for h in ex2["hinweise"])
    d["druck"] = {"platte": "cool"}
    einst.write_text(json.dumps(d))
    rt.run()
    v3 = rt.druckvorschau()
    assert v3["einstellungen"]["platte"] == "Cool Plate"
    assert any(h["art"] == "platte" and h["schwere"] == "fehler" for h in v3["hinweise"]), v3["hinweise"]
