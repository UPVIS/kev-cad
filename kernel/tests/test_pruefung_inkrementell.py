"""Prüfung inkrementell (PLAN-PRUEFUNG-INKREMENTELL.md), A1: Festkörper-FEM direkt nach der Statik.

- Reihenfolge: Statik vor Druckvorschau, gedruckt und Montage ändert weder Befunde noch Montage, Stand und Statik (alte
  gegen neue Reihenfolge an Testmodellen aus test_statik.py, test_festkoerper.py und test_pruefung_stand_montage.py).
- Rechenprozess: direkt nach der Statik ein Zwischenstand mit dem FEM-Auftrag (Ordner mit auftrag.json, Szenarien wie die
  Auswahl der Laufzeit), höchstens einer je Lauf; keiner ohne Teile mit Last.
- Laufzeit: startet den FEM-Prozess aus diesem Auftrag ohne EXEC, genau einmal je Lauf; das CHECK nach der Montage startet
  keinen zweiten; ein neuer Lauf bricht die FEM ab wie bisher; der Ablauf (S2) startet erst mit dem CHECK nach der
  Montage, ein abgebrochener Lauf startet ihn nicht.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from build123d import Box, Pos

from kevcad_kernel.pruefung import pruefer
from kevcad_kernel.pruefung.koerper import koerper_aus_form
from kevcad_kernel.statik.festkoerper import auftrag as fk_auftrag
from test_festkoerper import ECKE, STANGE
from test_statik import HALTER, TURM, laufe

ALT = ("erklaerungen", "durchdringung", "bedingungen", "stand", "druck", "druckvorschau", "gedruckt", "montage", "statik",
       "bewegungsraum")
FLUECHTIG = {"ms", "zeiten_ms", "dauer_ms", "duration_ms", "statistik", "laufzeit_ms", "pruef_ms", "aus_gedaechtnis",
             "aus_zwischenspeicher", "zwischenspeicher", "tests", "neu_gerechnet", "neu_geprueft", "dienst_ms",
             "rechnen_ms", "geprueft_ms",
             # vorbestehend, nicht Teil von A1: Knicken (S1) rechnet eigsh ohne festen Startvektor (Plan, Abschnitt 10)
             "knicken", "knick_stab"}


def _ohne_fluechtiges(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _ohne_fluechtiges(v) for k, v in x.items() if k not in FLUECHTIG}
    if isinstance(x, (list, tuple)):
        return [_ohne_fluechtiges(v) for v in x]
    return x


@pytest.fixture
def reihenfolge():
    """Reihenfolge der Prüfungen setzen und danach zurück."""
    vorher = tuple(n for n, _ in pruefer.PRUEFUNGEN)

    def setzen(r: tuple[str, ...]) -> None:
        pruefer.ordnen(r)

    yield setzen
    pruefer.ordnen(vorher)


def _vergleichbar(check: dict[str, Any]) -> dict[str, Any]:
    return _ohne_fluechtiges({k: check.get(k) for k in ("befunde", "zusammenfassung", "zaehler", "montage", "stand",
                                                        "gewinde", "erlaubt", "druck", "statik")})


@pytest.mark.parametrize("modell", ["halter", "stange", "ecke", "turm"])
def test_reihenfolge_aendert_nichts_an_den_modellen(tmp_path, reihenfolge, modell):
    """Statik vor Druckvorschau, gedruckt und Montage: gleiche Befunde, Montage, Stand, Druck und Statik wie vorher
    (je ein frischer Rechenprozess-Stand; das Gedächtnis der Statik wird dazwischen geleert)."""
    from kevcad_kernel.pruefung.lauf import REIHENFOLGE
    from kevcad_kernel.statik import merken

    code = {"halter": HALTER.replace("AUSRICHTUNG", '"-x"'), "stange": STANGE, "ecke": ECKE, "turm": TURM}[modell]
    assert REIHENFOLGE.index("statik") < REIHENFOLGE.index("montage") < REIHENFOLGE.index("bewegungsraum")
    ergebnisse = []
    for i, r in enumerate((ALT, REIHENFOLGE)):
        reihenfolge(r)
        merken.leeren()
        ordner = tmp_path / f"r{i}"
        ordner.mkdir()
        _, check, _ = laufe(ordner, code, strikt=False)
        ergebnisse.append(_vergleichbar(check))
    assert ergebnisse[0] == ergebnisse[1]


def test_reihenfolge_aendert_nichts_an_stand_und_montage(reihenfolge):
    """Kleine Fälle aus test_pruefung_stand_montage.py (Stand, Montage, Werkzeugzugang) in beiden Reihenfolgen."""
    from build123d import Cylinder

    from kevcad_kernel.pruefung.lauf import REIHENFOLGE

    def k(name, form, **info):
        return koerper_aus_form(name, form, info or None)

    faelle = [
        [k("Platte", Pos(0, 0, 5) * Box(100, 100, 10)), k("Klotz", Pos(0, 0, 30) * Box(20, 20, 20))],
        [k("Boden", Pos(0, 0, 5) * Box(80, 80, 10)), k("Wand", Pos(-35, 0, 40) * Box(10, 80, 60)),
         k("Deckel", Pos(0, 0, 75) * Box(80, 80, 10)), k("Stift", Pos(0, 0, 20) * Cylinder(4, 20))],
        [k("Turm", Pos(0, 0, 100) * Box(20, 20, 200)), k("Fuß", Pos(0, 0, 2) * Box(30, 30, 4))],
    ]
    for ks in faelle:
        erg = []
        for r in (ALT, REIHENFOLGE):
            reihenfolge(r)
            e, geo = pruefer.pruefe(ks)
            erg.append((_vergleichbar(e), [(len(p), len(t)) for p, _, t in geo]))
        assert erg[0] == erg[1]


# ---------------------------------------------------------------------------------------------------------------------
# Rechenprozess: Zwischenstand nach der Statik mit FEM-Auftrag


def _pruefe_mit_stufen(tmp_path: Path, code: str, run: int = 1) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Wie test_statik.laufe, aber mit Zwischenständen (Stufen): Liste der Zwischenstände und das Ergebnis."""
    from kevcad_kernel.catalog import builtin_dir
    from kevcad_kernel.runner import Runner

    (tmp_path / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": False}))
    (tmp_path / "model.py").write_text(code, encoding="utf-8")
    runner = Runner(lambda h, p=b"": None)
    res = runner.run({"run": run, "path": str(tmp_path / "model.py"), "code": code, "params": {},
                      "inventar_regel": False,
                      "catalog": {"builtin": str(builtin_dir()), "own": str(tmp_path / "eigen")}})
    assert res["type"] == "RUN_DONE", res.get("error")
    zwischen: list[dict[str, Any]] = []
    check, _ = runner.pruefe(run, zwischenstand=lambda kopf, nutz: zwischen.append(kopf))
    return zwischen, check


def test_zwischenstand_nach_der_statik_mit_fem_auftrag(tmp_path, monkeypatch):
    from kevcad_kernel.statik.festkoerper.laufzeit import _kandidaten

    monkeypatch.delenv("KEVCAD_PRUEF_STUFEN", raising=False)
    zwischen, check = _pruefe_mit_stufen(tmp_path, HALTER.replace("AUSRICHTUNG", '"-x"'))
    mit = [z for z in zwischen if z.get("festkoerper_auftrag")]
    assert len(mit) == 1, [z.get("im_hintergrund") for z in zwischen]
    z = mit[0]
    job = z["festkoerper_auftrag"]
    try:
        assert z["state"] == "teilweise" and "statik" in z and "montage" not in z
        assert "Statik" not in z["im_hintergrund"] and "Montage" in z["im_hintergrund"]
        assert job["namen"] == _kandidaten(z["statik"]) == ["Haken 2 kg"]
        assert Path(job["auftrag"]).exists() and [f["teil"] for f in job["faelle"]] == ["Wandhalter (Druck)"]
        a = json.loads(Path(job["auftrag"]).read_text(encoding="utf-8"))
        assert [T["name"] for T in a["teile"]] == ["Wandhalter (Druck)"]
        # gleicher Auftrag wie über EXEC (statik.dienst): gleiche Schlüssel der Fälle
        neu = fk_auftrag.schreibe(__import__("kevcad_kernel.statik.anbindung", fromlist=["LETZTER"]).LETZTER,
                                  {"auto": True, "szenarien": job["namen"]})
        try:
            assert [f["schluessel"] for f in neu["faelle"]] == [f["schluessel"] for f in job["faelle"]]
        finally:
            shutil.rmtree(neu["ordner"], ignore_errors=True)
        # das Ergebnis selbst trägt keinen Auftrag, und die Statik ist dieselbe
        assert "festkoerper_auftrag" not in check and check["statik"] == z["statik"]
    finally:
        shutil.rmtree(job["ordner"], ignore_errors=True)


STAPEL = '''
from build123d import *
from kevcad import show

show(Pos(0, 0, 5) * Box(100, 100, 10), "Platte", material="multiplex-birke")
show(Pos(0, 0, 20) * Box(20, 20, 20), "Klotz", material="eiche")
'''


def test_kein_fem_auftrag_ohne_last_und_ohne_stufen(tmp_path, monkeypatch):
    from kevcad_kernel.statik.festkoerper.laufzeit import _kandidaten

    monkeypatch.delenv("KEVCAD_PRUEF_STUFEN", raising=False)
    zwischen, check = _pruefe_mit_stufen(tmp_path, STAPEL)  # keine Last: kein Kandidat der FEM
    assert _kandidaten(check.get("statik")) == []
    assert not [z for z in zwischen if z.get("festkoerper_auftrag")]
    monkeypatch.setenv("KEVCAD_PRUEF_STUFEN", "0")
    (tmp_path / "b").mkdir()
    zwischen, _ = _pruefe_mit_stufen(tmp_path / "b", HALTER.replace("AUSRICHTUNG", '"-x"'))
    assert zwischen == []  # ohne Stufen wie bisher: die Laufzeit startet den Festkörper nach dem Ergebnis


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit: FEM aus dem Auftrag des Rechenprozesses


@pytest.fixture(scope="module")
def rt():
    from app_testutil import make_runtime

    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="kcpi", dir=tempfile.gettempdir()))
    os.environ["KEVCAD_FESTKOERPER_CACHE"] = str(tmp / "fem-cache")
    r = make_runtime(str(tmp / "k.sock"))
    assert r.wait_worker_ready(240), "Rechenprozess nicht bereit"
    yield r
    r.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _statik(run: int, mit_ablauf: bool = False) -> dict[str, Any]:
    """Statik eines Laufs mit einem Szenario, in dem ein Teil als Kragträger nachgewiesen ist (Kandidat der FEM)."""
    sz: dict[str, Any] = {"lasten": [{"teil": "Halter", "kraft": [0, 0, -20]}]}
    if mit_ablauf:
        sz["ablauf"] = {"geschwindigkeit": 1.0}
    return {"szenarien": [{"name": "Haken", "ampel": "gelb", "szenario": sz, "kennzahlen": {},
                           "bauteile": [{"teil": "Halter", "sicherheit": 1.5, "ziel": 2.0}], "urteile": []}],
            "grenzen": []}


def _job(tmp: Path, namen: list[str]) -> dict[str, Any]:
    ordner = tmp / f"fem-{time.time_ns()}"
    ordner.mkdir()
    (ordner / "auftrag.json").write_text(json.dumps({"version": 1, "teile": []}), encoding="utf-8")
    return {"ordner": str(ordner), "auftrag": str(ordner / "auftrag.json"), "run": 0, "namen": namen,
            "faelle": [{"id": "0.0", "szenario": n, "teil": "Halter", "schluessel": "x", "ziel": 2.0} for n in namen],
            "nicht": [], "ms": 1.0}


def _check(run: int, state: str, statik: dict[str, Any] | None = None, job: dict[str, Any] | None = None,
           offen: list[str] | None = None) -> dict[str, Any]:
    app: dict[str, Any] = {"run": run, "state": state, "befunde": [], "geometrie": [], "zaehler": {}, "zusammenfassung": ""}
    if statik is not None:
        app["statik"] = statik
    if job is not None:
        app["festkoerper_auftrag"] = job
    if offen is not None:
        app["im_hintergrund"] = offen
    return {"type": "CHECK_DONE", "run": run, "app": app, "app_len": 0}


class _FemAttrappe:
    """Statt des FEM-Prozesses: ein ``sleep``, den der Abbruch der Laufzeit beendet (wie den echten)."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self.aufrufe: list[dict[str, Any]] = []
        self.laeuft = threading.Event()

    def __call__(self, job: dict[str, Any], fortschritt: Any, timeout_s: float = 60.0) -> dict[str, Any]:
        from kevcad_kernel.statik.festkoerper.laufzeit import Abgebrochen

        z = self.rt._fk
        p = subprocess.Popen(["sleep", "30"], start_new_session=True)
        z["proc"] = p
        self.aufrufe.append({"job": job, "pid": p.pid})
        self.laeuft.set()
        try:
            p.wait(timeout=40)
        finally:
            z["proc"] = None
        if z.get("abbruch"):
            raise Abgebrochen("abgebrochen")
        return {"faelle": []}


def test_laufzeit_startet_fem_aus_dem_auftrag_genau_einmal(rt, tmp_path, monkeypatch):
    fem = _FemAttrappe(rt)
    execs: list[Any] = []
    monkeypatch.setattr(rt, "_fk_prozess", fem)
    monkeypatch.setattr(rt, "_fk_exec", lambda *a, **kw: execs.append(a) or {})
    monkeypatch.setattr(rt, "_s4_auftraege", lambda namen: [])
    dyn: list[Any] = []
    monkeypatch.setattr(rt, "_dynamik_hintergrund", lambda namen, run: dyn.append((tuple(namen), run)))
    gen = rt._worker.generation
    run = 9001
    with rt._lock:
        rt._lauf_start[run] = time.perf_counter()
    rt._pruef.erwarte(run)
    job = _job(tmp_path, ["Haken"])
    rt._on_worker_message(gen, _check(run, "teilweise", offen=["Druck", "Montage", "Statik", "Bewegungsraum"]), b"")
    rt._on_worker_message(gen, _check(run, "teilweise", _statik(run, mit_ablauf=True), job,
                                      offen=["Montage", "Bewegungsraum"]), b"")
    assert fem.laeuft.wait(10)
    assert len(fem.aufrufe) == 1 and fem.aufrufe[0]["job"]["ordner"] == job["ordner"] and not execs
    # der Ablauf ist markiert (zählt als offen), startet aber erst mit dem CHECK nach der Montage
    with rt._lock:
        e = rt._statik_voll["szenarien"][0]
    assert (e.get("ablauf") or {}).get("stand") == "laeuft" and not dyn
    # ein CHECK eines Schattenlaufs der Versionen dazwischen ändert daran nichts
    rt._on_worker_message(gen, _check(1_000_000_777, "done"), b"")
    assert not dyn
    rt._on_worker_message(gen, _check(run, "done", _statik(run, mit_ablauf=True)), b"")
    time.sleep(0.3)
    assert len(fem.aufrufe) == 1 and not execs  # kein zweiter FEM-Prozess für denselben Lauf
    assert dyn == [(("Haken",), run)]
    # neuer Lauf: sein Ergebnis mit Statik bricht die laufende FEM ab (wie bisher), der Ordner des Auftrags ist weg
    run2 = run + 1
    with rt._lock:
        rt._lauf_start[run2] = time.perf_counter()
    rt._pruef.erwarte(run2)
    alter_pid = fem.aufrufe[0]["pid"]
    fem.laeuft.clear()
    rt._on_worker_message(gen, _check(run2, "teilweise", _statik(run2), _job(tmp_path, ["Haken"]),
                                      offen=["Montage", "Bewegungsraum"]), b"")
    assert fem.laeuft.wait(10) and len(fem.aufrufe) == 2
    for _ in range(50):
        if not Path(job["ordner"]).exists():
            break
        time.sleep(0.1)
    assert not Path(job["ordner"]).exists()
    with pytest.raises(ProcessLookupError):
        os.kill(alter_pid, 0)
    rt.festigkeit_abbrechen()


def test_abgebrochener_lauf_startet_den_ablauf_nicht(rt, tmp_path, monkeypatch):
    fem = _FemAttrappe(rt)
    monkeypatch.setattr(rt, "_fk_prozess", fem)
    monkeypatch.setattr(rt, "_fk_exec", lambda *a, **kw: pytest.fail("kein EXEC erwartet"))
    monkeypatch.setattr(rt, "_s4_auftraege", lambda namen: [])
    dyn: list[Any] = []
    monkeypatch.setattr(rt, "_dynamik_hintergrund", lambda namen, run: dyn.append((tuple(namen), run)))
    gen = rt._worker.generation
    run = 9101
    with rt._lock:
        rt._lauf_start[run] = time.perf_counter()
    rt._pruef.erwarte(run)
    rt._on_worker_message(gen, _check(run, "teilweise", _statik(run, mit_ablauf=True), _job(tmp_path, ["Haken"]),
                                      offen=["Montage", "Bewegungsraum"]), b"")
    assert fem.laeuft.wait(10)
    rt._on_worker_message(gen, _check(run, "cancelled"), b"")  # neuer Lauf während der Montage
    time.sleep(0.3)
    assert dyn == []
    rt.festigkeit_abbrechen()


def test_auftrag_eines_ueberholten_laufs_wird_verworfen(rt, tmp_path, monkeypatch):
    """Kommt ein FEM-Auftrag zu einem Lauf, dessen Statik die Laufzeit schon hat (zweites CHECK) oder zu einem
    Schattenlauf, startet nichts und der Ordner ist weg."""
    fem = _FemAttrappe(rt)
    monkeypatch.setattr(rt, "_fk_prozess", fem)
    gen = rt._worker.generation
    job = _job(tmp_path, ["Haken"])
    rt._on_worker_message(gen, _check(1_000_000_123, "teilweise", _statik(1_000_000_123), job,
                                      offen=["Montage"]), b"")
    assert not Path(job["ordner"]).exists() and not fem.aufrufe
