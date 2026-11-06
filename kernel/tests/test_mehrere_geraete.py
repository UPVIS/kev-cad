"""I-2 (PLAN-IPAD.md): Der Kernel bedient mehrere Geräte zugleich (Mac-App und iPad über die Mac-App).

Zustand geht an alle, Antworten an die fragende Verbindung, gezielte Anfragen (Bild, Lagebild) an das aktive Gerät,
Ansichtsbefehle an alle. Trennt sich ein Gerät, laufen die anderen weiter."""

import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest
from app_testutil import FakeApp, make_runtime

MAC = {"id": "mac-test", "art": "mac", "name": "MacBook (Test)"}
PAD = {"id": "pad-test", "art": "ipad", "name": "iPad (Test)"}


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kc", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    mac = FakeApp(sock, geraet=MAC)
    mac.wait_for(lambda h: h["type"] == "HELLO")
    pad = FakeApp(sock, geraet=PAD)
    pad.wait_for(lambda h: h["type"] == "HELLO")
    _warten(lambda: len(rt.status()["geraete"]) == 2)
    res = rt.project_new(str(tmp / "Projekt"), "example")
    assert res["ok"], res
    yield {"rt": rt, "mac": mac, "pad": pad, "tmp": tmp, "sock": sock}
    mac.close()
    pad.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def _warten(pruefung, frist: float = 10.0) -> None:
    ende = time.monotonic() + frist
    while not pruefung():
        assert time.monotonic() < ende, "Bedingung nicht erreicht"
        time.sleep(0.02)


def _aktiv(rt) -> str | None:
    return next((g["name"] for g in rt.status()["geraete"] if g["aktiv"]), None)


def test_beide_geraete_bekommen_projekt_und_teile(env):
    rt, mac, pad = env["rt"], env["mac"], env["pad"]
    for app in (mac, pad):
        app.wait_for(lambda h: h["type"] == "PROJECT" and h["name"] == "Projekt")
    a, b = mac.mark(), pad.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    for app, start in ((mac, a), (pad, b)):
        app.wait_for(lambda h: h["type"] == "PART_UPSERT" and h["name"] == "Rohr", start=start)
        app.wait_for(lambda h: h["type"] == "RUN_END", start=start)
    geraete = rt.status()["geraete"]
    assert [g["art"] for g in geraete] == ["mac", "ipad"] and rt.status()["app_connected"] is True


def test_antwort_nur_an_die_fragende_app(env):
    mac, pad = env["mac"], env["pad"]
    a, b = mac.mark(), pad.mark()
    pad.send({"type": "BOM_REQ", "id": "bom-1"})
    pad.wait_for(lambda h: h["type"] == "BOM" and h.get("reply_to") == "bom-1", start=b)
    time.sleep(0.3)
    assert not [h for h in mac.since(a) if h["type"] == "BOM"], "Antwort ging auch an den Mac"


def test_projekt_wechsel_als_antwort_erreicht_alle(env):
    mac, pad = env["mac"], env["pad"]
    pfad = str(env["tmp"] / "Projekt")
    a, b = mac.mark(), pad.mark()
    mac.send({"type": "PROJECT_OPEN", "id": "auf-1", "path": pfad})
    mac.wait_for(lambda h: h["type"] == "PROJECT" and h.get("reply_to") == "auf-1", start=a)
    _, _, h, _ = pad.wait_for(lambda h: h["type"] == "PROJECT", start=b)
    assert "reply_to" not in h and h["name"] == "Projekt"


def test_bild_kommt_vom_aktiven_geraet(env):
    rt, mac, pad = env["rt"], env["mac"], env["pad"]
    mac.send({"type": "SELECTION", "run": 0, "refs": []})  # Kevin arbeitet am Mac
    _warten(lambda: _aktiv(rt) == MAC["name"])
    a, b = mac.mark(), pad.mark()
    assert rt.screenshot(64, 48)["ok"]
    assert [h for h in mac.since(a) if h["type"] == "SCREENSHOT_REQ"]
    assert not [h for h in pad.since(b) if h["type"] == "SCREENSHOT_REQ"]

    pad.send({"type": "AKTIV"})  # jetzt am iPad
    _warten(lambda: _aktiv(rt) == PAD["name"])
    a, b = mac.mark(), pad.mark()
    assert rt.screenshot(64, 48)["ok"]
    assert [h for h in pad.since(b) if h["type"] == "SCREENSHOT_REQ"]
    assert not [h for h in mac.since(a) if h["type"] == "SCREENSHOT_REQ"]


def test_ansicht_geht_an_alle_geraete(env):
    rt, mac, pad = env["rt"], env["mac"], env["pad"]
    a, b = mac.mark(), pad.mark()
    assert rt.view_command("view", {"standard": "iso"})["ok"]
    for app, start in ((mac, a), (pad, b)):
        app.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "view", start=start)


def test_trennen_beendet_nur_anfragen_an_dieses_geraet(env):
    rt, mac, sock = env["rt"], env["mac"], env["sock"]
    stumm = FakeApp(sock, answer=False, geraet={"id": "stumm", "art": "ipad", "name": "stummes iPad"})
    stumm.wait_for(lambda h: h["type"] == "HELLO")
    stumm.send({"type": "AKTIV"})
    _warten(lambda: _aktiv(rt) == "stummes iPad")
    ergebnis: dict = {}
    t = threading.Thread(target=lambda: ergebnis.update(rt.screenshot(64, 48, timeout_s=20)))
    t.start()
    stumm.wait_for(lambda h: h["type"] == "SCREENSHOT_REQ")
    t0 = time.monotonic()
    stumm.close()
    t.join(10)
    assert ergebnis == {"ok": False, "error": "App-Verbindung getrennt"}
    assert time.monotonic() - t0 < 5
    # der Mac bleibt verbunden und wird wieder aktiv
    _warten(lambda: len(rt.status()["geraete"]) == 2)
    assert rt.status()["app_connected"] is True
    mac.send({"type": "AKTIV"})
    _warten(lambda: _aktiv(rt) == MAC["name"])
    assert rt.screenshot(64, 48)["ok"]


def test_gleiches_geraet_ersetzt_alte_verbindung(env):
    rt, sock = env["rt"], env["sock"]
    erste = FakeApp(sock, geraet={"id": "pad-neu", "art": "ipad", "name": "iPad neu"})
    erste.wait_for(lambda h: h["type"] == "HELLO")
    _warten(lambda: len(rt.status()["geraete"]) == 3)
    zweite = FakeApp(sock, geraet={"id": "pad-neu", "art": "ipad", "name": "iPad neu"})
    zweite.wait_for(lambda h: h["type"] == "HELLO")
    _warten(lambda: erste.closed)
    _warten(lambda: len(rt.status()["geraete"]) == 3)
    zweite.close()
    _warten(lambda: len(rt.status()["geraete"]) == 2)


def test_vorgaben_beim_verbinden_ueberschreiben_nicht(env):
    rt, mac, pad = env["rt"], env["mac"], env["pad"]
    mac.send({"type": "SETTINGS", "auto_run": False, "slow_ms": 0})
    _warten(lambda: rt.status()["settings"].get("auto_run") is False)
    pad.send({"type": "SETTINGS", "auto_run": True, "slow_ms": 0, "anlass": "start"})
    time.sleep(0.3)
    assert rt.status()["settings"].get("auto_run") is False, "Vorgabe des neuen Geräts hat überschrieben"
    pad.send({"type": "SETTINGS", "auto_run": True, "slow_ms": 0})  # Kevin ändert es am iPad selbst
    _warten(lambda: rt.status()["settings"].get("auto_run") is True)
    mac.send({"type": "SETTINGS", "auto_run": False, "slow_ms": 0})
    _warten(lambda: rt.status()["settings"].get("auto_run") is False)
