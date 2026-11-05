"""V2-1 „Tempo im Kernel“: run wartet höchstens warten_s auf die Prüfung, der Nachlauf (Versionen, Animationen)
läuft außerhalb des Auftragsfadens, zeiten_ms im Ergebnis und in runs.jsonl."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.mcp_tools import format as fmt

CODE = """from build123d import *
from kevcad import show, param
b = param("b", 20)
show(Box(b, 10, 5), "Platte")
show(Pos(30, 0, 0) * Cylinder(3, 8), "Stift")
"""


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kctempo", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    rt.versionen_warten_s = 0.0  # wie für Kevin und den Agenten: run wartet nicht auf die Version
    assert rt.wait_worker_ready(240)
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


_n = iter(range(1, 1000))


def projekt(env, code: str = CODE) -> Path:
    path = env["tmp"] / f"P{next(_n)}"
    assert env["rt"].project_new(str(path), "empty")["ok"]
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    assert env["rt"].model_write(code)["ok"]
    assert env["rt"].wait_idle(60)
    return path


def test_zeiten_ms_im_ergebnis_und_protokoll(env):
    rt = env["rt"]
    p = projekt(env)
    res = rt.run()
    assert res["ok"], res.get("error")
    z = res["zeiten_ms"]
    for k in ("skript", "modell", "tessellierung", "serialisierung", "bedingungen", "bom", "erstes_teil",
              "letztes_teil", "run_end", "kern", "nachlauf", "zurueck"):
        assert isinstance(z.get(k), (int, float)), k
    assert z["erstes_teil"] <= z["letztes_teil"] <= z["run_end"] <= z["kern"] <= z["zurueck"]
    assert "pruefung" in z
    assert rt.wait_idle(60)
    zeilen = [json.loads(x) for x in (p / ".kevcad" / "log" / "runs.jsonl").read_text().splitlines()]
    lauf = [x for x in zeilen if x.get("run") == res["run"] and "art" not in x]
    assert lauf and lauf[-1]["zeiten_ms"]["skript"] == z["skript"]
    ende = time.monotonic() + 30
    while time.monotonic() < ende:  # die Prüfung schreibt ihre eigene Zeile, sobald sie fertig ist
        zeilen = [json.loads(x) for x in (p / ".kevcad" / "log" / "runs.jsonl").read_text().splitlines()]
        pruef = [x for x in zeilen if x.get("run") == res["run"] and x.get("art") == "pruefung"]
        if pruef:
            break
        time.sleep(0.1)
    assert pruef and pruef[0]["zeiten_ms"]["pruefung"] > 0
    # MCP: zeiten_ms reisen in den Daten mit
    _, data, _ = fmt.run_summary(res)
    assert data["zeiten_ms"] == res["zeiten_ms"]


def test_run_reicht_warten_s_an_die_pruefung(env, monkeypatch):
    rt = env["rt"]
    projekt(env)
    gesehen: list[float] = []
    echt = rt._pruef.warte

    def warte(run, timeout, **kw):
        gesehen.append(timeout)
        return {"type": "CHECK", "run": run, "state": "running", "befunde": [],
                "message": "Prüfung läuft noch im Hintergrund"}

    monkeypatch.setattr(rt._pruef, "warte", warte)
    res = rt.run(warten_s=0)
    assert res["ok"] and res["pruefung"]["state"] == "running"
    text, _, fehler = fmt.run_summary(res)
    assert "läuft noch im Hintergrund" in text and "pruefen(warten=true)" in text and not fehler
    rt.run()
    rt.run(warten_s=10_000)
    assert gesehen == [0.0, 3.0, rt.pruef_warten_s]
    monkeypatch.setattr(rt._pruef, "warte", echt)
    assert rt.wait_idle(60)


def test_pruefung_kommt_nach_und_pruefen_liefert_den_endstand(env):
    rt, app = env["rt"], env["app"]
    projekt(env)
    start = app.mark()
    res = rt.run(warten_s=0)
    assert res["ok"] and res["pruefung"]["state"] in ("running", "done", "teilweise")
    _, _, check, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == res["run"]
                                  and h.get("state") in ("done", "teilweise"), start=start)
    fertig = rt.pruefen(warten_s=60, endstand=True)
    assert fertig["ok"] and fertig["run"] == res["run"] and fertig["state"] == "done"


def test_version_im_hintergrund_und_mit_titel(env):
    rt = env["rt"]
    p = projekt(env)
    res = rt.run()
    assert res["ok"]
    assert "version" in res  # fertig oder {"ausstehend": True}
    assert rt.wait_idle(60)
    vs = rt.versionen()["versionen"]
    assert vs and vs[0]["nr"] >= 1
    (p / "model.py").write_text(CODE.replace("Cylinder(3, 8)", "Cylinder(4, 8)"))
    res = rt.run(titel="Stift dicker")  # mit titel wartet run auf die Version
    assert res["ok"] and res["version"]["neu"] and res["version"]["titel"] == "Stift dicker"
    assert rt.versionen()["versionen"][0]["titel"] == "Stift dicker"


def test_naechster_lauf_wartet_nicht_auf_die_version(env, monkeypatch):
    rt = env["rt"]
    p = projekt(env)
    assert rt.run()["ok"]
    assert rt.wait_idle(60)
    echt = rt._versionen_nach_lauf
    reihenfolge: list[int] = []
    sperre = threading.Lock()

    def langsam(job, result, **kw):
        time.sleep(1.5)
        with sperre:
            reihenfolge.append(job.run)
        return echt(job, result, **kw)

    monkeypatch.setattr(rt, "_versionen_nach_lauf", langsam)
    t0 = time.perf_counter()
    (p / "model.py").write_text(CODE.replace("Box(b, 10, 5)", "Box(b, 12, 5)"))
    r1 = rt.run()
    (p / "model.py").write_text(CODE.replace("Box(b, 10, 5)", "Box(b, 14, 5)"))
    r2 = rt.run()
    dauer = time.perf_counter() - t0
    assert r1["ok"] and r2["ok"]
    assert dauer < 2.6, dauer  # zwei Läufe, ohne zweimal 1,5 s auf die Versionen zu warten
    assert rt.wait_idle(60)
    assert reihenfolge == [r1["run"], r2["run"]]  # Versionen in der Reihenfolge der Läufe
    nrs = [v["nr"] for v in rt.versionen()["versionen"][:2]]
    assert nrs[0] == nrs[1] + 1


def test_animation_folgt_dem_lauf(env):
    rt, app = env["rt"], env["app"]
    projekt(env, CODE + """from kevcad import animation
fahrt = animation(dauer=1, fps=4, name="Fahrt")
fahrt.bewege("Stift", nach=(0, 10, 0), von=0, bis=1)
""")
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    assert res["animationen"][0]["name"] == "Fahrt"  # Zusammenfassung schon im Ergebnis
    assert "Fahrt" in json.dumps(rt.animation_list(), ensure_ascii=False)
    app.wait_for(lambda h: h["type"] == "ANIM_DEF" and h.get("name") == "Fahrt", start=start)
    types = [h["type"] for h in app.since(start) if h["type"] in ("RUN_END", "ANIM_DEF")]
    assert types.index("RUN_END") < types.index("ANIM_DEF")
