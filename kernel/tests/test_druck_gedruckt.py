"""Bereits gedruckte Teile (Strang „Feinschliff 2“, Punkt 7): ``lager.druckteil(…, gedruckt=True)`` fällt aus
Druckvorschau, Filament und Druckschritt heraus, die Form wird in gedruckt.json festgeschrieben, eine spätere
Änderung meldet die Prüfung (``gedruckt_geaendert``, Warnung), ``neu_drucken=True`` schreibt die neue Form fest."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kevcad_kernel.bestand import einkauf as ek
from kevcad_kernel.catalog import Catalog, builtin_dir
from kevcad_kernel.druck import gedruckt as gd
from kevcad_kernel.druck import vorschau as vs
from kevcad_kernel.runner import Runner

KOPF = "from build123d import *\nfrom kevcad import lager, show, param\n"


def modell(rolle_d=30.0, neu_drucken=False, gedruckt=True):
    return KOPF + f"""
rolle = Cylinder({rolle_d / 2}, 40, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(4, 50)
show(lager.druckteil(rolle, "Fangrolle (Druck)", material="petg", gedruckt={gedruckt}, neu_drucken={neu_drucken}),
     "Kugelschieber/Fangrolle (Druck)")
halter = Box(40, 20, 6, align=(Align.CENTER, Align.CENTER, Align.MIN))
show(Pos(80, 0, 0) * lager.druckteil(halter, "Halter (Druck)", material="petg"), "Kugelschieber/Halter (Druck)")
"""


@pytest.fixture(autouse=True)
def ablage(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_DRUCK_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("KEVCAD_DRUCK_ABGLEICH", str(tmp_path / "abgleich.json"))
    monkeypatch.setenv("KEVCAD_BAMBU_APP", str(tmp_path / "kein-bambu.app"))


class Laufzeit(gd.GedrucktAnbindung):
    def __init__(self, projekt: Path):
        self._project = SimpleNamespace(path=projekt)
        self.log: list[str] = []

    def _log(self, text):
        self.log.append(text)


def laufe(runner: Runner, projekt: Path, code: str, run: int):
    (projekt / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": True}))
    model = projekt / "model.py"
    model.write_text(code, encoding="utf-8")
    res = runner.run({"run": run, "path": str(model), "code": code, "params": {}, "inventar_regel": True,
                      "catalog": {"builtin": str(builtin_dir()), "own": str(projekt / "eigen")}})
    assert res["type"] == "RUN_DONE", res.get("error")
    check, _ = runner.pruefe(run)
    assert check["state"] == "done", check
    return res, check


def test_gedruckt_festschreiben_ausschliessen_und_warnen(tmp_path):
    runner = Runner(lambda h, p=b"": None)
    rt = Laufzeit(tmp_path)
    name = "Kugelschieber/Fangrolle (Druck)"

    # 1. Erster Lauf: Form wird festgeschrieben, keine Druckbefunde, nicht in der Vorschau
    res, check = laufe(runner, tmp_path, modell(), 1)
    stand = check["druck"]["gedruckt"]
    assert stand[name]["status"] == "neu" and stand[name]["eintrag"]["signatur"]["v"] > 0
    assert check["druck"]["teile"][name]["gedruckt"] is True
    assert not [b for b in check["befunde"] if name in b["teile"] and b["art"].startswith("druck")]
    rt._gedruckt_check(check)
    datei = json.loads((tmp_path / "gedruckt.json").read_text())
    assert list(datei["teile"]) == [name] and datei["teile"][name]["material"] == "petg"
    v, gr, _ = vs.baue(1, check["druck"], check["befunde"], {}, {}, Catalog().material)
    assert [t["name"] for t in v["teile"]] == ["Halter (Druck)"]
    assert v["gedruckt"] == [{"name": name, "material": "petg", "form": "neu", "unterschiede": [], "seit": None}]
    assert all(t["name"] != name for p in v["platten"] for t in p["teile"])
    del res

    # 2. Gleiche Form: gleich, keine Warnung
    _, check = laufe(runner, tmp_path, modell(), 2)
    assert check["druck"]["gedruckt"][name]["status"] == "gleich"
    assert not [b for b in check["befunde"] if b["art"] == "gedruckt_geaendert"]

    # 3. Form geändert: Warnung (kein Fehler) mit den Unterschieden
    _, check = laufe(runner, tmp_path, modell(rolle_d=32.0), 3)
    (b,) = [b for b in check["befunde"] if b["art"] == "gedruckt_geaendert"]
    assert b["schwere"] == "warnung" and b["teile"] == [name]
    assert b["text"].startswith("Fangrolle ist als gedruckt markiert, die Form hat sich geändert (Volumen +")
    assert "Neu drucken" in b["loesung"] and "neu_drucken=True" in b["loesung"]
    rt._gedruckt_check(check)
    assert json.loads((tmp_path / "gedruckt.json").read_text()) == datei, "geänderte Form schreibt nichts fest"
    v, _, _ = vs.baue(3, check["druck"], check["befunde"], {}, {}, Catalog().material)
    assert v["gedruckt"][0]["form"] == "geaendert" and v["gedruckt"][0]["unterschiede"][0].startswith("Volumen +")

    # 4. neu_drucken: neue Form festschreiben, keine Warnung; danach gleich
    _, check = laufe(runner, tmp_path, modell(rolle_d=32.0, neu_drucken=True), 4)
    assert check["druck"]["gedruckt"][name]["status"] == "neu_drucken"
    assert not [b for b in check["befunde"] if b["art"] == "gedruckt_geaendert"]
    rt._gedruckt_check(check)
    neu = json.loads((tmp_path / "gedruckt.json").read_text())
    assert neu["teile"][name]["signatur"]["v"] > datei["teile"][name]["signatur"]["v"]
    _, check = laufe(runner, tmp_path, modell(rolle_d=32.0), 5)
    assert check["druck"]["gedruckt"][name]["status"] == "gleich"

    # 5. Eintrag gelöscht: wieder neu
    (tmp_path / "gedruckt.json").unlink()
    _, check = laufe(runner, tmp_path, modell(rolle_d=32.0), 6)
    assert check["druck"]["gedruckt"][name]["status"] == "neu"

    # 6. Nicht mehr gedruckt: wieder in der Vorschau
    _, check = laufe(runner, tmp_path, modell(gedruckt=False), 7)
    v, _, _ = vs.baue(7, check["druck"], check["befunde"], {}, {}, Catalog().material)
    assert sorted(t["name"] for t in v["teile"]) == ["Fangrolle (Druck)", "Halter (Druck)"] and "gedruckt" not in v


def test_stueckliste_und_filament(tmp_path):
    from kevcad_kernel.bom import Piece, ShownPart, build_bom

    def stueck(seq, name, gedruckt):
        return Piece(seq=seq, name=name, stock_id=None, art="druckteil", benennung=name, material_id="petg",
                     material_name="PETG", kg=0.05, preis=0.85, verfahren="3d-druck", volume=39000.0,
                     size=[30.0, 30.0, 40.0], gedruckt=gedruckt)

    pieces = [stueck(1, "Rolle 1", True), stueck(2, "Rolle 2", False)]
    bom = build_bom(pieces, [ShownPart(name="Rolle 1", pieces=[1]), ShownPart(name="Rolle 2", pieces=[2])],
                    inventar_regel=True)
    zeilen = [ln for ln in bom["lines"] if ln["art"] == "druckteil"]
    assert len(zeilen) == 2, "gedruckt und zu drucken getrennt"
    assert [ln.get("gedruckt", False) for ln in zeilen].count(True) == 1
    assert pieces[0].druck_info()["gedruckt"] is True and "gedruckt" not in pieces[1].druck_info()
    (f,) = ek.filament({"run": 1, **bom})
    assert f["teile"] == 1 and f["gramm"] == pytest.approx(50.0)


def test_neu_drucken_nur_mit_gedruckt(tmp_path):
    runner = Runner(lambda h, p=b"": None)
    code = KOPF + 'show(lager.druckteil(Box(10, 10, 10), "W", material="petg", neu_drucken=True), "W")\n'
    model = tmp_path / "model.py"
    model.write_text(code)
    res = runner.run({"run": 1, "path": str(model), "code": code, "params": {}, "inventar_regel": True,
                      "catalog": {"builtin": str(builtin_dir()), "own": str(tmp_path / "eigen")}})
    assert res["type"] != "RUN_DONE" and "nur zusammen mit gedruckt=True" in json.dumps(res, ensure_ascii=False)


def test_geaendert_texte_und_versionen():
    alt = {"v": 1000.0, "a": 600.0, "m": [10.0, 8.0, 5.0], "g": [10, 10, 10], "k": [], "e": True}
    assert gd.geaendert(alt, dict(alt)) == []
    assert gd.geaendert(alt, {**alt, "v": 1030.0}) == ["Volumen +3,0 %"]
    assert gd.geaendert(alt, {**alt, "g": [10, 10, 12]}) == ["Maße 10 × 10 × 10 → 10 × 10 × 12 mm"]
    assert gd.geaendert(alt, {**alt, "m": [10.0, 8.2, 5.0]}) == ["Form innen geändert (Verteilung, Bohrungen oder "
                                                                 "Taschen)"]
    # gedruckt.json gehört zu den Versionen (nicht ausgeschlossen wie bestand.json)
    from kevcad_kernel.versionen.git import AUSSCHLUSS

    assert "gedruckt.json" not in AUSSCHLUSS and "/bestand.json" in AUSSCHLUSS


def test_bauplan_ohne_druckschritt_fuer_gedruckte():
    from build123d import Box

    from kevcad_kernel.bauplan.eingang import BTeil, Eingang
    from kevcad_kernel.bauplan.geruest import drucken
    from kevcad_kernel.pruefung.koerper import koerper_aus_form

    def teil(name, gedruckt):
        k = koerper_aus_form(name, Box(20, 20, 10))
        return BTeil(name=name, rolle="druck", koerper=k,
                     kopf={"druckteil": {"material": "petg", "kg": 0.004, **({"gedruckt": True} if gedruckt else {})}})

    teile = {t.name: t for t in (teil("Rolle (Druck)", True), teil("Halter (Druck)", False))}
    bom = {"lines": [{"art": "druckteil", "anzahl": 1, "teile": ["Rolle (Druck)"], "gedruckt": True},
                     {"art": "druckteil", "anzahl": 1, "teile": ["Halter (Druck)"]}]}
    ein = Eingang(titel="T", run=1, projekt=None, teile=teile, bom=bom, bedingungen=None, check=None,
                  verbindungen=[], gewinde=[], erlaubt=set(), durchdringend=set(), hat_verbinde=False)
    schritte = drucken(ein)
    assert [s["teile"] for s in schritte] == [["Halter (Druck)"]]
