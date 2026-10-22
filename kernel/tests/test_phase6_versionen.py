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
