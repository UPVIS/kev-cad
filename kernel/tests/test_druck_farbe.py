"""Farbe je Druckteil (Strang „Rest Druck“): ``lager.druckteil(…, farbe=…)``; Druckvorschau, Platten, Export und
Filamentwahl je Material und Farbe. Ohne Farbe bleibt alles wie bisher. Ohne Bambu Studio (der Export schreibt dann
je Platte eine Datei); Bedarf, Bestand und Einkaufsliste je Farbe prüfen test_bestand_filament.py und
test_material_einkauf.py."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from app_testutil import make_runtime

from kevcad_kernel.druck import anordnen as ao
from kevcad_kernel.protocol import check_druck_message, pack_print_preview

HEAD = "from build123d import *\nfrom kevcad import lager, show\n"


def _stueck(gruppe, farbe, w=100.0, h=100.0):
    return ao.Stueck(gruppe=gruppe, name=gruppe, material="petg", w=w, h=h,
                     umriss=[[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]], flaeche=w * h,
                     farbe=farbe)


def test_anordnen_je_farbe_und_ohne_farbe_fuellt_auf():
    """Zwei Farben: je Farbe eigene Platten; ein Teil ohne Farbe kommt auf eine Platte mit Platz (keine neue)."""
    platten = ao.anordne([_stueck("gelb1", "gelb"), _stueck("schwarz1", "schwarz"), _stueck("frei", None, 60, 60)])
    assert [p.farbe for p in platten] == ["gelb", "schwarz"]
    assert [sorted(l_.stueck.gruppe for l_ in p.lagen) for p in platten] == [["frei", "gelb1"], ["schwarz1"]]
    # eine Farbe: wie bisher alles zusammen, die Platte trägt die Farbe
    platten = ao.anordne([_stueck("a", "gelb", 50, 50), _stueck("b", None, 50, 50)])
    assert len(platten) == 1 and platten[0].farbe == "gelb"
    # ohne Farben wie bisher
    platten = ao.anordne([_stueck("a", None, 50, 50), _stueck("b", None, 50, 50)])
    assert len(platten) == 1 and platten[0].farbe is None


MODELL = HEAD + """
for i in range(2):
    show(Pos(60 * i, 0, 0) * lager.druckteil(Box(40, 30, 10), f"Halter gelb {i + 1}", material="petg",
                                             zweck="funktion", ausrichtung="-z", farbe="Gelb"), f"Teile/Halter gelb {i + 1}")
show(Pos(0, 60, 0) * lager.druckteil(Box(40, 30, 10), "Halter schwarz", material="petg", zweck="funktion",
                                     ausrichtung="-z", farbe="schwarz"), "Teile/Halter schwarz")
show(Pos(60, 60, 0) * lager.druckteil(Box(20, 20, 6), "Deckel", material="petg", zweck="funktion",
                                      ausrichtung="-z"), "Teile/Deckel")
"""


@pytest.fixture(scope="module")
def env():
    alt = {k: os.environ.get(k) for k in ("KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH", "KEVCAD_BAMBU_APP")}
    tmp = Path(tempfile.mkdtemp(prefix="kcfa", dir=tempfile.gettempdir()))
    os.environ.update({"KEVCAD_DRUCK_CACHE": str(tmp / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(tmp / "abgleich.json"),
                       "KEVCAD_BAMBU_APP": str(tmp / "kein-bambu.app")})
    rt = make_runtime(str(tmp / "k.sock"))
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    assert rt.project_new(str(tmp / "Farben"), "empty")["ok"]
    assert rt.model_write(MODELL)["ok"]
    res = rt.run()
    assert res["ok"], res
    yield {"rt": rt, "tmp": tmp}
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)
    for k, v in alt.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_vorschau_je_farbe(env):
    v = env["rt"].druckvorschau(detail=True)
    assert not check_druck_message(pack_print_preview(v))
    farbe = {t["name"]: t.get("farbe") for t in v["teile"]}
    assert farbe == {"Halter gelb": "gelb", "Halter schwarz": "schwarz", "Deckel": None}
    assert [(p.get("farbe"), p["klasse"]) for p in v["platten"]] == [("gelb", "petg/gelb"),
                                                                     ("schwarz", "petg/schwarz")]
    # der Deckel ohne Farbe liegt mit auf einer Platte (keine eigene)
    assert sum(len(p["teile"]) for p in v["platten"]) == 4
    m = v["summe"]["material"][0]
    assert [f["farbe"] for f in m["farben"]] == ["gelb", "schwarz"]
    assert sum(f["g"] for f in m["farben"]) == pytest.approx(m["g"], abs=0.2)
    # Stückliste: eigene Zeile je Farbe
    bom = env["rt"].bom()
    zeilen = [ln for ln in bom.get("lines") or [] if ln.get("art") == "druckteil"]
    assert {ln.get("farbe") for ln in zeilen} == {"gelb", "schwarz", None}


def test_export_fragt_je_farbe_und_schreibt_je_farbe(env):
    rt, tmp = env["rt"], env["tmp"]
    frage = rt.druck_export(str(tmp / "f.3mf"))
    assert not frage["ok"] and frage["filament_frage"]
    assert set(frage["vorschlaege"]) == {"petg/gelb", "petg/schwarz"}
    assert frage["vorschlaege"]["petg/gelb"]["liste"][0]["id"] == "polymaker-polylite-petg-gelb"  # Farbe passt zuerst
    # ein Material-Schlüssel reicht bei zwei Farben nicht
    r = rt.druck_export(str(tmp / "f.3mf"), filament={"petg": "bambu-petg-basic"})
    assert not r["ok"] and "mehreren Farben" in r["fehler"]
    # als Liste: gelbes Filament zur gelben Platte; ein Filament ohne Farbe passt keiner Farbe eindeutig
    r = rt.druck_export(str(tmp / "f.3mf"), filament=["polymaker-polylite-petg-gelb", "bambu-petg-basic"])
    assert not r["ok"] and "passt zu keiner Farbe" in r["fehler"]
    r = rt.druck_export(str(tmp / "f.3mf"), filament={"petg/gelb": "polymaker-polylite-petg-gelb",
                                                      "petg/schwarz": "bambu-petg-basic"})
    assert r["ok"], r
    assert [(d.get("klasse"), Path(d["pfad"]).name) for d in r["dateien"]] == [
        ("petg/gelb", "f-petg-gelb.3mf"), ("petg/schwarz", "f-petg-schwarz.3mf")]
    assert set(r["filamente"]) == {"petg/gelb", "petg/schwarz"}
    assert any("je Farbe ein Bambu-Projekt" in h for h in r["hinweise"])
    assert any(h.startswith("PETG gelb: Filament") for h in r["hinweise"])
    # zuletzt gewählt je Klasse (Vorbelegung im Dialog „Drucken …“)
    v = rt.druckvorschau()
    assert v["filament_zuletzt"]["petg/gelb"] == "polymaker-polylite-petg-gelb"
    # nur die gelbe Platte (wie der Dialog „Drucken …“): Kennung der Klasse wie in der Vorschau, oder das Material
    gelb = [p["nr"] for p in v["platten"] if p["klasse"] == "petg/gelb"]
    r = rt.druck_export(str(tmp / "g.3mf"), platten=gelb, filament={"petg/gelb": "polymaker-polylite-petg-gelb"})
    assert r["ok"] and [Path(d["pfad"]).name for d in r["dateien"]] == ["g.3mf"], r
    r = rt.druck_export(str(tmp / "g.3mf"), platten=gelb, filament={"petg": "polymaker-polylite-petg-gelb"})
    assert r["ok"], r


def test_farbe_aus_filamentliste_und_fehler(env):
    rt = env["rt"]
    m = HEAD + ('show(lager.druckteil(Box(10, 10, 5), "Klotz", material="petg", ausrichtung="-z", '
                'farbe="polymaker-polylite-petg-gelb"), "Klotz")\n')
    assert rt.model_write(m)["ok"]
    assert rt.run()["ok"]
    assert [t.get("farbe") for t in rt.druckvorschau()["teile"]] == ["gelb"]
    m = HEAD + ('show(lager.druckteil(Box(10, 10, 5), "Klotz", material="petg", ausrichtung="-z", '
                'farbe=12), "Klotz")\n')
    assert rt.model_write(m)["ok"]
    res = rt.run()
    assert not res["ok"] and "farbe ist ein kurzer Text" in str(res)
    assert rt.model_write(MODELL)["ok"]
    assert rt.run()["ok"]
