"""Phase 6 mit Versionen: Blätter und Bauplan liegen in den Projektdateien, also in den Versionen. Ein Lauf ohne
Änderung darf trotzdem keine neue Version anlegen (die Blätter werden nach jedem Lauf neu zugeordnet und dürfen dabei
nur schreiben, wenn sich etwas ändert)."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.versionen.git import git_verfuegbar

pytestmark = pytest.mark.skipif(not git_verfuegbar()[0], reason="git fehlt")

# Testmodell steht physikalisch korrekt (Prüfung Stufe 2: nichts schwebt, nichts kippt)
CODE = (
    "from build123d import *\nfrom kevcad import show, step, param\n"
    'b = param("b", 60)\n'
    'step("Platte")\n'
    "platte = Box(b, 40, 6) - Pos(b / 2 - 10, 0, 0) * Cylinder(3.3, 6)\n"
    'show(platte, "Halter/Platte")\n'
    'show(Pos(-b / 2 + 8, 0, 3 + 10) * Box(16, 40, 20), "Halter/Wange")\n'
)


@pytest.fixture()
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kp6v", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _projekt(env) -> Path:
    path = env["tmp"] / "P6V"
    start = env["app"].mark()
    res = env["rt"].project_new(str(path), "empty")
    assert res["ok"], res
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    env["app"].wait_for(lambda h: h["type"] == "PROJECT" and h["name"] == path.name, start=start)
    assert env["rt"].model_write(CODE)["ok"]
    return path


def test_lauf_ohne_aenderung_legt_trotz_blaettern_keine_version_an(env):
    rt = env["rt"]
    path = _projekt(env)
    res = rt.run()
    assert res["ok"], res.get("error")
    assert res["version"]["neu"] is True

    blaetter = rt.drawing_create()
    assert blaetter["ok"], blaetter
    assert list((path / "dokumente" / "zeichnungen").glob("*.json")), "keine Blätter geschrieben"

    res = rt.run()  # die neuen Blätter sind eine echte Änderung der Projektdateien
    assert res["ok"], res.get("error")

    for _ in range(2):  # danach: nichts geändert, also keine neue Version
        res = rt.run()
        assert res["ok"], res.get("error")
        assert res["version"]["neu"] is False, res["version"]


def test_bauplan_im_hintergrund_legt_keine_version_je_lauf_an(env):
    rt = env["rt"]
    path = _projekt(env)
    assert rt.run()["ok"]
    plan = rt.bauplan()
    assert plan["ok"], plan
    assert (path / "dokumente" / "bauplan.json").exists()
    assert rt.run()["ok"]  # der neue Bauplan ist eine echte Änderung
    time.sleep(3)  # der Bauplan wird nach jedem Lauf im Hintergrund erneuert
    assert rt.run()["ok"]
    time.sleep(3)
    for _ in range(2):
        res = rt.run()
        assert res["ok"], res.get("error")
        assert res["version"]["neu"] is False, res["version"]
        time.sleep(3)


def test_erster_bauplan_der_app_ist_von_kev_cad(env):
    """BAUPLAN_REQ der App legt den Bauplan beim ersten Mal an: das ist keine Änderung von Kevin. Er wird in die
    aktuelle Version nachgetragen; trägt sie Kevins Meilenstein, führt Kev CAD die nächste Version „Bauplan …“.
    Kevins eigene Bearbeitung bleibt „kevin“."""
    rt, app = env["rt"], env["app"]
    path = _projekt(env)
    assert rt.run()["ok"]
    start = app.mark()
    app.send({"type": "BAUPLAN_REQ", "id": "bp-1"})
    app.wait_for(lambda h: h["type"] == "BAUPLAN" and h.get("reply_to") == "bp-1", timeout=120, start=start)
    assert (path / "dokumente" / "bauplan.json").exists()
    _warte_sauber(rt)  # in V1 nachgetragen, nichts Ungesichertes
    archiv = rt._archiv
    assert archiv.git.datei(archiv.aktuelle().commit, "dokumente/bauplan.json") is not None
    res = _app_lauf(rt)
    assert res["ok"] and res["version"]["neu"] is False and res["version"]["nr"] == 1
    # Mit Kevins Meilenstein darf nichts nachgetragen werden: die nächste Version führt Kev CAD
    (path / "dokumente" / "bauplan.json").unlink()
    assert rt.run()["version"]["neu"] is True  # Bauplan entfernt: eine eigene Version
    start = app.mark()
    app.send({"type": "VERSION_MILESTONE", "id": "ms-1", "version": None, "titel": "Prototyp", "notiz": ""})
    assert app.wait_for(lambda h: h.get("reply_to") == "ms-1", start=start)[2]["ok"]
    start = app.mark()
    app.send({"type": "BAUPLAN_REQ", "id": "bp-2"})
    app.wait_for(lambda h: h["type"] == "BAUPLAN" and h.get("reply_to") == "bp-2", timeout=120, start=start)
    time.sleep(1)
    assert archiv.ungesichert()
    res = _app_lauf(rt)  # Lauf aus der App: Auslöser wäre Kevin
    assert res["version"]["neu"] is True
    v = rt.versionen()["versionen"][0]
    assert v["wer"] == "kevcad" and "Bauplan" in v["titel"], v
    _warte_sauber(rt)
    # Kevins eigene Bearbeitung des Bauplans: seine Version
    plan = rt.bauplan()["bauplan"]
    sid = plan["abschnitte"][0]["schritte"][0]["id"]
    assert rt.bauplan_bearbeiten([{"op": "text", "schritt": sid, "text": "Von Kevin"}], "kevin")["ok"]
    res = _app_lauf(rt)
    assert res["version"]["neu"] is True and rt.versionen()["versionen"][0]["wer"] == "kevin"


def _app_lauf(rt) -> dict:
    """Lauf, den Kevin in der App auslöst (RUN_REQ)."""
    job = rt._submit_run(None, 0, 120, source="app")
    assert job.done.wait(120)
    assert job.result["ok"], job.result
    return job.result


def test_modellaenderung_ergibt_eine_version_mit_blaettern(env):
    """Nach einer Modelländerung landen die neu zugeordneten Blätter in derselben Version, nicht in einer zweiten.
    Unabhängig davon, wann der nächste Lauf kommt: nach der Hintergrundrechnung (hier) oder mitten hinein
    (test_zweiter_lauf_direkt_danach_uebernimmt_das_nachtragen)."""
    rt = env["rt"]
    path = _projekt(env)
    assert rt.run()["ok"]
    assert rt.drawing_create()["ok"]
    assert rt.run()["ok"]
    res = rt.run(params={})  # Ruhezustand
    assert res["ok"]
    rt.model_write(CODE.replace('param("b", 60)', 'param("b", 80)'))
    start = env["app"].mark()
    res = rt.run()
    assert res["ok"] and res["version"]["neu"] is True
    nr = res["version"]["nr"]
    _warte_docs(env, start, res["run"])  # Blätter werden im Hintergrund neu gerechnet …
    _warte_sauber(rt)  # … und in V(nr) nachgetragen
    assert _im_commit(rt, path) and "80" in _masse(rt)
    res = rt.run()
    assert res["ok"]
    assert res["version"]["neu"] is False and res["version"]["nr"] == nr, res["version"]


# ---------------------------------------------------------------------------------------------------------------------
# Hintergrundrechnung, Schriftfeld, Wiederherstellen, Vergleich (P6-V)

BLATT = "zusammenbau"


def _code(b: int) -> str:
    return CODE.replace('param("b", 60)', f'param("b", {b})')


def _warte_docs(env, start: int, run: int) -> None:
    env["app"].wait_for(lambda h: h["type"] == "DOCS" and h.get("run") == run, start=start, timeout=60)


def _warte_sauber(rt, timeout: float = 20.0) -> None:
    """Bis die Hintergrundrechnung nachgetragen ist (keine ungesicherten Änderungen mehr)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not rt._archiv.ungesichert():
            return
        time.sleep(0.1)
    raise AssertionError("Hintergrundrechnung nicht nachgetragen: " + str(rt._archiv.git.status()))


def _lauf(env, **kw) -> dict:
    """Lauf und warten, bis seine Blätter gerechnet und nachgetragen sind."""
    start = env["app"].mark()
    res = env["rt"].run(**kw)
    assert res["ok"], res.get("error")
    _warte_docs(env, start, res["run"])
    _warte_sauber(env["rt"])
    return res


def _mit_blaettern(env) -> tuple[Path, dict]:
    path = _projekt(env)
    assert env["rt"].run()["ok"]
    assert env["rt"].drawing_create()["ok"]
    return path, _lauf(env)


def _schriftfeld(rt) -> list[str]:
    res = rt.drawing(BLATT)
    assert res["ok"], res
    return [t["text"] for t in res["kopf"]["texte"] if t.get("art") == "schriftfeld"]


def _masse(rt) -> list[str]:
    return [m.get("text") for m in rt.drawing(BLATT)["kopf"]["masse"]]


def _im_commit(rt, path: Path) -> bool:
    """Steht das Blatt der Arbeitskopie so in der aktuellen Version?"""
    rel = f"dokumente/zeichnungen/{BLATT}.json"
    return rt._archiv.git.datei(rt._archiv.aktuelle().commit, rel) == (path / rel).read_bytes()


def test_zweiter_lauf_direkt_danach_uebernimmt_das_nachtragen(env):
    """Beginnt der nächste Lauf, bevor die Blätter fertig sind, speichert der alte Hintergrund nicht weiter; der neue
    Lauf (gleicher Stand) trägt in dieselbe Version nach."""
    rt = env["rt"]
    path, _ = _mit_blaettern(env)
    rt.model_write(_code(80))
    res = rt.run()
    assert res["ok"] and res["version"]["neu"] is True
    nr = res["version"]["nr"]
    start = env["app"].mark()
    res2 = rt.run(params={})  # sofort, ohne auf die Blätter zu warten
    assert res2["ok"] and res2["version"]["nr"] == nr and res2["version"]["neu"] is False
    _warte_docs(env, start, res2["run"])
    _warte_sauber(rt)
    assert "80" in _masse(rt)
    assert _im_commit(rt, path)
    res3 = rt.run()
    assert res3["version"]["neu"] is False and res3["version"]["nr"] == nr


def test_reglerlauf_aendert_keine_dokumente(env):
    """Läufe mit überschriebenen Parametern zeigen die Blätter, schreiben sie aber nicht (sonst legte der nächste Lauf
    eine Version für den Reglerstand an)."""
    rt = env["rt"]
    path, res = _mit_blaettern(env)
    nr = res["version"]["nr"]
    ordner = path / "dokumente" / "zeichnungen"
    vorher = {p.name: p.read_bytes() for p in ordner.glob("*.json")}
    start = env["app"].mark()
    res = rt.run(params={"b": 90})
    assert res["ok"]
    _warte_docs(env, start, res["run"])
    assert "90" in _masse(rt)  # die App sieht den Reglerstand
    time.sleep(0.5)
    assert {p.name: p.read_bytes() for p in ordner.glob("*.json")} == vorher
    res = _lauf(env)
    assert res["version"]["neu"] is False and res["version"]["nr"] == nr
    assert "60" in _masse(rt)


def test_schriftfeld_zeigt_version_des_laufs(env):
    rt = env["rt"]
    path, _ = _mit_blaettern(env)
    rt.model_write(_code(80))
    res = _lauf(env)
    nr = res["version"]["nr"]
    assert res["version"]["neu"] is True
    assert f"V{nr}" in _schriftfeld(rt)  # das Blatt der Hintergrundrechnung trägt die Version, zu der es gehört
    datei = json.loads((path / "dokumente" / "zeichnungen" / f"{BLATT}.json").read_text())
    assert datei["schriftfeld"]["version"] is None  # nur dargestellt, nie gespeichert
    assert rt.meilenstein("Prototyp", wer="kevin")["version"] == nr
    assert f"V{nr} „Prototyp“" in _schriftfeld(rt)
    var = rt.variante("anlegen", "Flacher Rand", wer="kevin")
    assert var["ok"], var
    _warte_sauber(rt)
    assert f"V{nr} (Flacher Rand) „Prototyp“" in _schriftfeld(rt)
    rt.model_write(_code(70))
    res = _lauf(env)
    assert res["version"]["neu"] is True
    assert f"V{res['version']['nr']} (Flacher Rand)" in _schriftfeld(rt)
    assert (rt.versionen_info(res["run"]) or {}).get("variante") == "Flacher Rand"


def test_wiederherstellen_ordnet_blaetter_neu_ohne_phantomversion(env):
    """Eine alte Version mit Blättern, die nicht zu ihrem Modell passen (gesichert ohne Lauf): Nach dem Wiederherstellen
    passen Blätter zum Modell, landen in der wiederhergestellten Version, und der nächste Lauf legt keine an."""
    rt = env["rt"]
    path, _ = _mit_blaettern(env)  # Blätter für b = 60
    rt.model_write(_code(70))
    alt = rt.meilenstein("Ohne Blätter", wer="kevin")  # model.py mit b = 70, Blätter noch für 60
    assert alt["ok"], alt
    rt.model_write(_code(80))
    assert _lauf(env)["version"]["neu"] is True
    start = env["app"].mark()
    res = rt.version_wiederherstellen(alt["version"], wer="kevin")
    assert res["ok"] and res["lauf"]["ok"], res
    _warte_docs(env, start, res["lauf"]["run"])
    _warte_sauber(rt)
    assert "70" in _masse(rt)
    akt = rt.versionen(limit=2)["versionen"][0]
    assert akt["nr"] == res["version"] and akt["quelle"] == "wiederherstellen"
    assert akt["titel"] == f"Wiederhergestellt aus V{alt['version']} „Ohne Blätter“"
    assert _im_commit(rt, path)
    for _ in range(2):
        nach = _lauf(env)
        assert nach["version"]["neu"] is False and nach["version"]["nr"] == res["version"]


def test_eigene_blattaenderung_ist_eigene_version_und_vergleich_nennt_dokumente(env):
    rt = env["rt"]
    _, res = _mit_blaettern(env)
    vor = res["version"]["nr"]
    edit = rt.drawing_edit(BLATT, [{"op": "notiz", "text": "Grat entfernen", "lage": [30, 30]}], "kevin")
    assert edit["ok"], edit
    res = _lauf(env)
    assert res["version"]["neu"] is True
    assert res["version"]["titel"] == "Zeichnung Zusammenbau: Notiz neu"
    cmp = rt.versionen_vergleichen(vor, res["version"]["nr"], zeigen=False)
    assert cmp["ok"], cmp
    assert cmp["code"]["dateien"] == []  # Blätter sind kein Code
    assert [e["text"] for e in cmp["dokumente"]] == ["Zeichnung Zusammenbau: Notiz neu"]
    assert "Zeichnung Zusammenbau: Notiz neu" in cmp["zusammenfassung"]
