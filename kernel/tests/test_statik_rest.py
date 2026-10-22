"""Statik, Restpunkte (PLAN-STATIK.md, Zweig „rest-statik-render“, T33 und T34): Gelenk mit Bereich, das frei läuft
(``frei=True``), in Stabwerk und Ablauf; Befunde aus Ablauf (S2) und Festkörper (S3) nachträglich in der Prüfung
(CHECK „teilweise“ → „done“).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.statik import anbindung
from kevcad_kernel.statik.dynamik import ablauf as ab
from kevcad_kernel.statik.dynamik import mjcf, prozess, szene
from test_statik import laufe, szenario
from test_statik_nach import SCHLITTEN, _verbinder

# ---------------------------------------------------------------------------------------------------------------------
# Gelenk mit Bereich, frei laufend (T33)


def test_schiebegelenk_mit_bereich_frei_laeuft_im_stabwerk(tmp_path):
    """Derselbe Schlitten wie im Kugelschieber-Befund, aber mit frei=True: die Führung hält längs nichts, die ganze
    Kraft geht über den geklemmten Schlitten (wie ohne Bereich). Ohne frei bleibt es bei 50 / 50 (T30)."""
    _, check, _ = laufe(tmp_path, SCHLITTEN.replace("BEREICH", "(-100, 50), frei=True"), strikt=False)
    m = anbindung.LETZTER.modell
    arten = {a.teile[1]: (a.art, a.quelle) for a in m.anschluesse if a.stab.startswith("Seitenstange")}
    art, quelle = arten["Schlitten links (Druck)"]
    assert art == "schiebe" and "frei" in quelle and "festgestellt" not in quelle
    e = szenario(check, "Ball drückt 100 N")
    e0 = szenario(check, "Eigengewicht")
    links = _verbinder(e, e0, "Schlitten links (Druck)", "Querstange")
    rechts = _verbinder(e, e0, "Schlitten rechts (Druck)", "Querstange")
    assert abs(links[0]) < 0.5 and rechts[0] == pytest.approx(100.0, abs=0.5)
    # im Bericht der Bedingungen steht der Schalter
    from kevcad_kernel.bedingungen import anbindung as bed

    gel = [c for c in bed.STAND.sammlung.bedingungen if getattr(c, "art", "") == "schiebegelenk"]
    assert gel and gel[0].info()["frei"] is True and gel[0].frei


def test_frei_nur_als_wahrheitswert(tmp_path):
    from kevcad_kernel.bedingungen.arten import BedingungsFehler
    from kevcad.bedingungen import schiebegelenk

    with pytest.raises(BedingungsFehler, match="frei"):
        schiebegelenk((0, 0, 0), (0, 0, 0), frei="ja")


# Kommode auf dem Boden mit einer Schublade, die frei auf einer Schiene läuft (0 bis 80 mm heraus). Beim abrupten
# Bremsen aus 1 m/s fährt die Schublade nach vorn bis an den Anschlag; festgestellt bliebe sie stehen.
KOMMODE = '''
from build123d import *
from kevcad import show
from kevcad.bedingungen import schiebegelenk, bezug
MAT = "multiplex-birke"
show(Pos(0, 0, 150) * Box(400, 300, 300), "Kommode/Korpus", material=MAT)
show(Pos(0, 0, 310) * Box(300, 200, 20), "Kommode/Schublade", material=MAT)
achse = Axis((0, 0, 300), (1, 0, 0))
schiebegelenk(bezug("Kommode/Schublade", "Achse", achse), bezug("Kommode/Korpus", "Achse", achse),
              bereich=(0, 80)FREI)
'''


def _schublade_weg(tmp_path: Path, frei: bool) -> tuple[dict, float, float]:
    laufe(tmp_path, KOMMODE.replace("FREI", ", frei=True" if frei else ""), strikt=False)
    meta, felder = szene.baue(anbindung.LETZTER, {"run": 1})
    formen = mjcf.formen_je_teil(meta, felder, {})
    abl, f = prozess.rechne_szenario(meta, formen, {"name": "Bremsen", "geschwindigkeit": 1.0, "bremsen": "abrupt",
                                                    "suche": False})
    assert abl["stand"] == "done", abl
    teile = json.loads(bytes(f["teile"]).decode())
    L = np.asarray(f["lagen"], float)
    i_s, i_k = teile.index("Kommode/Schublade"), teile.index("Kommode/Korpus")
    c = np.array([0.0, 0.0, 310.0, 1.0])  # Mitte der Schublade
    # Weg der Schublade gegenüber dem Korpus in Fahrtrichtung (mm), im System des Korpus
    rel = np.array([(np.linalg.inv(L[k, i_k]) @ L[k, i_s] @ c)[0] for k in range(len(L))])
    return meta, float(rel.max()), float(rel[-1])


def test_schublade_frei_faehrt_bis_zum_anschlag(tmp_path):
    meta, weg_max, weg_ende = _schublade_weg(tmp_path, frei=True)
    k = next(k for k in meta["koerper"] if "Kommode/Schublade" in k["teile"])
    assert k["art"] == "schiebe" and k["gelenk"]["grenzen"] == [0.0, 80.0] and "frei" in k["gelenk"]["quelle"]
    import mujoco

    _, felder = szene.baue(anbindung.LETZTER, {"run": 1})
    mo = ab.baue_modell(meta, mjcf.formen_je_teil(meta, felder, {}))
    j = mujoco.mj_name2id(mo.model, mujoco.mjtObj.mjOBJ_JOINT, f"j_{k['id']}")
    assert j >= 0 and mo.model.jnt_limited[j] and np.allclose(mo.model.jnt_range[j], [0.0, 0.08])
    # fährt bis an den Anschlag (gedämpft, federt nicht zurück) und bleibt dort; die Lagerreibung hält sie
    assert 75.0 < weg_ende <= 81.0 and weg_max <= 83.0, (weg_max, weg_ende)
    print(f"Schublade frei: größter Weg {weg_max:.1f} mm, am Ende {weg_ende:.1f} mm (Anschlag 80 mm)")


def test_schublade_festgestellt_bleibt(tmp_path):
    meta, weg_max, _ = _schublade_weg(tmp_path, frei=False)
    k = next(k for k in meta["koerper"] if "Kommode/Schublade" in k["teile"])
    assert "Kommode/Korpus" in k["teile"]  # ein Körper: Gelenk mit Bereich festgestellt (T15, T30)
    assert abs(weg_max) < 0.5


# ---------------------------------------------------------------------------------------------------------------------
# Befunde aus Ablauf (S2) und Festkörper (S3) in der Prüfung (T34)


@pytest.fixture(scope="module")
def env():
    import os

    from app_testutil import FakeApp, make_runtime

    tmp = Path(tempfile.mkdtemp(prefix="kcsr", dir=tempfile.gettempdir()))
    os.environ["KEVCAD_FESTKOERPER_CACHE"] = str(tmp / "fem-cache")
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _checks(app, start: int, run: int) -> list[dict]:
    return [h for h in app.since(start) if h["type"] == "CHECK" and h.get("run") == run]


def test_festkoerper_befund_kommt_nachtraeglich_in_die_pruefung(env):
    """Wandhalter quer zur Schicht: run kommt sofort mit der Prüfung „teilweise“ zurück (Festkörper rechnet im
    Hintergrund), danach folgt dasselbe CHECK mit „done“, in dem der Befund statik_festkoerper den Kragträger
    (statik_bauteil) desselben Teils ersetzt; der Export bleibt frei (T10)."""
    from test_festkoerper import _projekt_mit_petg
    from test_statik import HALTER

    from kevcad_kernel.pruefung.text import pruef_text

    rt, app = env["rt"], env["app"]
    _projekt_mit_petg(rt, env["tmp"] / "Halter")
    assert rt.model_write(HALTER.replace("AUSRICHTUNG", '"-x"'))["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    pr = res["pruefung"]
    assert pr["state"] == "teilweise", pr
    assert any(x.startswith("Festkörper „Haken 2 kg“") for x in pr["statik_im_hintergrund"]), pr
    assert not pr.get("im_hintergrund")  # kein Bewegungsraum offen
    vorher = {b["art"] for b in pr["befunde"]}
    assert "statik_bauteil" in vorher and "statik_festkoerper" not in vorher  # Kragträger S0 bis dahin
    text, offen = pruef_text(pr)
    assert "Statik: Festkörper „Haken 2 kg“" in text and "rechnet im Hintergrund" in text and not offen
    assert "Bewegungsraum" not in text
    # nachträglich: CHECK done mit dem Befund aus dem Festkörper
    _, _, fertig, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == res["run"]
                                   and h["state"] == "done", start=start, timeout=180)
    arten = [b["art"] for b in fertig["befunde"]]
    assert "statik_festkoerper" in arten and "statik_bauteil" not in arten, arten
    b = next(b for b in fertig["befunde"] if b["art"] == "statik_festkoerper")
    assert b["schwere"] == "warnung" and b["teile"] == ["Wandhalter (Druck)"] and b["wert"]["pruefung"] == "statik"
    assert "Bauteil hält nicht (FEM)" in fertig["zusammenfassung"]
    assert len({b["id"] for b in fertig["befunde"]}) == len(fertig["befunde"])  # neu nummeriert, eindeutig
    assert "statik_im_hintergrund" not in fertig
    # an die App: running, teilweise, done; der Fortschritt allein schickt kein weiteres CHECK
    zustaende = [c["state"] for c in _checks(app, start, res["run"])]
    assert zustaende[0] == "running" and "teilweise" in zustaende and zustaende[-1] == "done"
    assert len(zustaende) <= 4, zustaende
    # pruefen und status sehen den Endstand, die Export-Sperre kennt keinen Statik-Befund
    p = rt.pruefen(warten_s=10, endstand=True)
    assert p["state"] == "done" and "statik_hintergrund" not in p
    assert rt._pruef.offen(warten_s=0) == ([], False)
    assert rt.status()["pruefung"]["state"] == "done"


def test_ablauf_befund_kommt_nachtraeglich_und_neuer_lauf_raeumt_auf(env):
    """Ablauf aus model.py (S2): erst „teilweise“ mit Ablauf im Hintergrund, dann der Befund statik_dyn_kippen
    (Warnung). Ein neuer Lauf ohne Ablauf ist sofort fertig."""
    from test_dynamik import WAGEN

    rt, app = env["rt"], env["app"]
    assert rt.project_new(str(env["tmp"] / "Wagen"), "empty")["ok"]
    assert rt.model_write(WAGEN + 'st.szenario("Bremsen aus 1 m/s", geschwindigkeit=1, bremsen="abrupt")\n')["ok"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res
    pr = res["pruefung"]
    assert pr["state"] == "teilweise" and "Ablauf „Bremsen aus 1 m/s“" in pr["statik_im_hintergrund"], pr
    _, _, fertig, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == res["run"]
                                   and h["state"] == "done", start=start, timeout=240)
    dyn = [b for b in fertig["befunde"] if b["art"].startswith("statik_dyn_")]
    assert any(b["art"] == "statik_dyn_kippen" and b["schwere"] == "warnung" for b in dyn), fertig["befunde"]
    assert not any(b["art"] == "statik_kippen" and b["wert"].get("szenario") == "Bremsen aus 1 m/s"
                   for b in fertig["befunde"])  # Kippen beurteilt der Ablauf
    kurz = {e["name"]: e for e in fertig["statik"]["szenarien"]}
    assert kurz["Bremsen aus 1 m/s"]["ampel"] == "rot"
    # neuer Lauf ohne Ablauf: done ohne Hintergrund
    assert rt.model_write(WAGEN)["ok"]
    res2 = rt.run()
    assert res2["ok"] and res2["pruefung"]["state"] == "done", res2["pruefung"].get("statik_im_hintergrund")
    assert rt._pruef.statik_hintergrund is None
