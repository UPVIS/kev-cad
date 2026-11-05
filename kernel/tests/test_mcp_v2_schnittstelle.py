"""V2-2 „Schlanke Agenten-Schnittstelle“: Budgets an einem kleinen echten Projekt (Anweisungen, Werkzeugliste,
unveränderter Lauf, Parameteränderung, erster Lauf), Maßänderung ohne Dateiänderung, Lagebild in status."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from kevcad_kernel.mcp_tools import INSTRUCTIONS, TOOL_NAMES
from kevcad_kernel.mcp_tools.kern import KERN_NAMEN
from kevcad_kernel.server import build_server
from mcp import Client

BUDGET_ANWEISUNGEN = 6000
BUDGET_UNVERAENDERT = 1500
BUDGET_PARAMETER = 4000
BUDGET_KALT = 8000
BUDGET_WERKZEUGLISTE = 36000  # Wache gegen schleichendes Wachsen (V2-2: rund 31 500)

CODE = """from build123d import *
from kevcad import show, step, param
b = param("b", 20)
h = param("h", 5)
step("Platten")
for i in range(3):
    show(Pos(i * 40, 0, 0) * Box(b, 10, h, align=(Align.CENTER, Align.CENTER, Align.MIN)), f"Gestell/Platte {i + 1}")
step("Stifte")
for i in range(3):
    show(Pos(i * 40, 30, 0) * Cylinder(3, 8, align=(Align.CENTER, Align.CENTER, Align.MIN)), f"Stifte/Stift {i + 1}")
show(Pos(0, 60, 0) * Box(12, 12, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)), "Klotz")
"""


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kcv22", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    rt.versionen_warten_s = 0.0
    assert rt.wait_worker_ready(240)
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    path = tmp / "Klein"
    assert rt.project_new(str(path), "empty")["ok"]
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    assert rt.model_write(CODE)["ok"]
    assert rt.wait_idle(60)
    yield {"rt": rt, "app": app, "path": path, "mcp": build_server(rt)}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def aufrufe(env, *schritte):
    """Ruft (Werkzeug, Argumente) der Reihe nach im selben Client auf; Rückgabe: Ergebnisse."""

    async def go():
        out = []
        async with Client(env["mcp"], raise_exceptions=True) as c:
            for name, args in schritte:
                out.append(await c.call_tool(name, args))
                if name == "run":
                    env["rt"].wait_idle(60)
        return out

    return anyio.run(go)


def text(res) -> str:
    return "\n".join(b.text for b in res.content if b.type == "text")


def test_budget_anweisungen_und_werkzeugliste(env):
    assert len(INSTRUCTIONS) <= BUDGET_ANWEISUNGEN
    auswahl = re.search(r"select:(\S+)", INSTRUCTIONS).group(1).split(",")
    assert [x.removeprefix("mcp__kevcad__") for x in auswahl] == list(KERN_NAMEN)  # ein ToolSearch-Aufruf

    async def liste():
        async with Client(env["mcp"]) as c:
            return (await c.list_tools()).tools

    tools = anyio.run(liste)
    assert {t.name for t in tools} == set(TOOL_NAMES) and len(tools) <= 25
    roh = json.dumps([t.model_dump(by_alias=True, exclude_none=True, mode="json") for t in tools], ensure_ascii=False,
                     separators=(",", ":"))
    assert len(roh) <= BUDGET_WERKZEUGLISTE, len(roh)


def test_budget_laeufe_und_unterschiede(env):
    kalt, pruef, gleich, param, voll, zurueck = aufrufe(
        env, ("run", {"warten_s": 30}), ("pruefen", {}), ("run", {"warten_s": 30}),
        ("run", {"params": {"b": 30}, "warten_s": 30}), ("run", {"params": {"b": 30}, "detail": "teile"}),
        ("run", {"warten_s": 30}))
    t = text(kalt)
    assert not kalt.is_error, t
    assert len(t) <= BUDGET_KALT
    assert t.startswith("Lauf ") and "7 Teile in 3 Baugruppen (erster Lauf, den du siehst)" in t
    assert "Parameter: b=20, h=5" in t and "- Gestell: 3 Teile" in t
    assert len(kalt.content) == 1  # kein JSON-Block

    t = text(gleich)
    assert len(t) <= BUDGET_UNVERAENDERT, t
    assert "7 Teile, nichts geändert." in t and "Baugruppen" not in t and "Gestell/Platte" not in t

    t = text(param)
    assert len(t) <= BUDGET_PARAMETER, t
    assert "3 geändert, 4 unverändert" in t and "Parameter: b 20 → 30" in t
    assert "- Gestell/Platte 1: 30 × 10 × 5 mm (vorher 20 × 10 × 5 mm)" in t
    assert "Stift" not in t  # unveränderte Teile nur gezählt
    assert param.structured_content["geaendert"] == ["Gestell/Platte 1", "Gestell/Platte 2", "Gestell/Platte 3"]

    t = text(voll)  # gleicher Stand, aber jedes Teil
    assert "nichts geändert" in t and "Alle 7 Teile:" in t and "Stift 3" in t

    t = text(zurueck)  # ohne params gilt wieder der Wert aus model.py
    assert "Parameter: b 30 → 20" in t and "3 geändert" in t


def test_massaenderung_ohne_datei_und_neue_teile(env):
    modell = env["path"] / "model.py"
    vorher = hashlib.sha256(modell.read_bytes()).hexdigest()
    a, = aufrufe(env, ("run", {"params": {"h": 8}}))
    assert hashlib.sha256(modell.read_bytes()).hexdigest() == vorher  # model.py bleibt unberührt
    assert "Parameter: h 5 → 8" in text(a)
    assert "Gestell/Platte 2: 20 × 10 × 8 mm (vorher 20 × 10 × 5 mm)" in text(a)
    unbekannt, = aufrufe(env, ("run", {"params": {"gibtsnicht": 1}}))
    assert "gibtsnicht gibt es nicht als param() in model.py" in text(unbekannt)
    assert env["rt"].model_write(CODE.replace('show(Pos(0, 60, 0) * Box(12, 12, 12',
                                              'show(Pos(0, 90, 0) * Box(4, 4, 4), "Würfel")\n'
                                              'show(Pos(0, 60, 0) * Box(12, 12, 12'))["ok"]
    env["rt"].wait_idle(60)
    neu, = aufrufe(env, ("run", {}))
    t = text(neu)
    assert "1 neu" in t and "- Würfel (neu): 4 × 4 × 4 mm" in t
    assert env["rt"].model_write(CODE)["ok"]
    env["rt"].wait_idle(60)
    weg, = aufrufe(env, ("run", {}))
    assert "1 entfernt" in text(weg) and "Entfernt: Würfel" in text(weg)


def test_status_lagebild(env):
    rt, app = env["rt"], env["app"]
    lauf, = aufrufe(env, ("run", {}))
    run_no = lauf.structured_content["run"]
    app.send({"type": "SELECTION", "run": run_no, "refs": ["Klotz", "Gestell/Platte 1#f0"]})
    import time

    ende = time.monotonic() + 5
    while time.monotonic() < ende and not rt.status()["selection"]["refs"]:
        time.sleep(0.05)
    isoliert, status = aufrufe(env, ("view", {"sichtbarkeit": "isolieren", "teile": ["Klotz"]}), ("status", {}))
    assert not isoliert.is_error, text(isoliert)
    t = text(status)
    assert len(t) <= 1500, t
    assert t.startswith("Projekt Klein (model.py: ") and "Kernel bereit · App verbunden" in t
    assert f"Letzter Lauf {run_no}: ok, 7 Teile in 3 Baugruppen" in t
    assert "Auswahl (Lauf" in t and "- Klotz: " in t and "Gestell/Platte 1#f0: " in t
    assert "Ansicht: perspektivisch" in t  # Kameradaten aus SCREENSHOT_RES
    assert "Sichtbar nur: Klotz (6 ausgeblendet)" in t
    assert status.structured_content["auswahl"] == ["Klotz", "Gestell/Platte 1#f0"]
    aufrufe(env, ("view", {"sichtbarkeit": "alle"}))
