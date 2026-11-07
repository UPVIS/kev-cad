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


# -- I-6 Live-Kopplung (PROTOCOL.md, „I-6 Live-Kopplung“) -------------------------------------------------------------

from kevcad_kernel.kopplung import geraete_text  # noqa: E402
from kevcad_kernel.protocol import (  # noqa: E402
    FAEHIGKEIT_ANSICHT, FUEHRUNG_PAUSE_S, ansicht_beispiele, check_ansicht_message,
)

KAMERA = {"drehung": [0.0, 0.0, 0.0, 1.0], "ziel": [0.0, 0.0, 0.0], "abstand": 400.0, "projektion": "perspective",
          "fov": 30.0, "ortho_hoehe": 200.0}
VOLL = {"kamera": KAMERA, "sicht": {"verborgen": [], "isoliert": None}, "auswahl": {"run": None, "refs": []},
        "darstellung": "shaded_edges", "schnitt": None, "explosion": 0.0}


def _koppel_geraet(sock: str, kennung: str, art: str, name: str) -> FakeApp:
    app = FakeApp(sock, faehigkeiten=[FAEHIGKEIT_ANSICHT], geraet={"id": kennung, "art": art, "name": name})
    app.wait_for(lambda h: h["type"] == "HELLO")
    return app


def _ansicht(app: FakeApp, griff: bool, abstand: float, voll: bool = False) -> None:
    teile = dict(VOLL) if voll else {}
    teile["kamera"] = {**KAMERA, "abstand": abstand}
    app.send({"type": "ANSICHT", "t": time.time(), "griff": griff, "voll": voll, **teile})


def _bekam_ansicht(app: FakeApp, start: int, abstand: float, frist: float = 3.0):
    return app.wait_for(lambda h: h["type"] == "ANSICHT" and h.get("kamera", {}).get("abstand") == abstand,
                        timeout=frist, start=start)


def _geraet(rt, name: str) -> dict:
    return next(g for g in rt.status()["geraete"] if g["name"] == name)


@pytest.fixture()
def paar(env):
    """Zwei Geräte mit ansicht-1 (die Geräte aus ``env`` kennen die Kopplung nicht und bekommen nichts davon)."""
    rt, sock = env["rt"], env["sock"]
    a = _koppel_geraet(sock, "kop-mac", "mac", "Kopplung Mac")
    b = _koppel_geraet(sock, "kop-pad", "ipad", "Kopplung iPad")
    _warten(lambda: len(rt.status()["geraete"]) == 4)
    yield a, b
    a.close()
    b.close()
    _warten(lambda: len(rt.status()["geraete"]) == 2)


def test_geraeteliste_mit_ich_und_ansicht(env, paar):
    rt, alt = env["rt"], env["pad"]
    a, b = paar
    _, _, h, _ = b.wait_for(lambda h: h["type"] == "GERAETE" and len(h["geraete"]) == 4)
    assert check_ansicht_message(h) == []
    ich = [g for g in h["geraete"] if g["ich"]]
    assert [g["name"] for g in ich] == ["Kopplung iPad"] and ich[0]["ansicht"] == "gemeinsam"
    alte = [g for g in h["geraete"] if g["name"] == PAD["name"]]
    assert alte and alte[0]["ansicht"] is None, "Gerät ohne ansicht-1 hat keine Ansicht"
    assert not [h for h in alt.since(0) if h["type"] in ("GERAETE", "ANSICHT", "SPRECHEN_LIVE")]


def test_ansicht_folgt_dem_fuehrenden_geraet_in_beide_richtungen(env, paar):
    rt = env["rt"]
    a, b = paar
    sa, sb = a.mark(), b.mark()
    _ansicht(a, griff=True, abstand=410.0, voll=True)
    _, _, h, _ = _bekam_ansicht(b, sb, 410.0)
    assert h["voll"] is True and h["von"] == next(g["nr"] for g in rt.status()["geraete"] if g["name"] == "Kopplung Mac")
    assert check_ansicht_message(h) == []
    _warten(lambda: _geraet(rt, "Kopplung Mac")["fuehrt"] and _aktiv(rt) == "Kopplung Mac")
    # B bewegt sich ohne neuen Griff, während A führt: zählt nicht (etwa das Nachziehen beim Folgen)
    _ansicht(b, griff=False, abstand=420.0)
    time.sleep(0.3)
    assert not [h for h in a.since(sa) if h["type"] == "ANSICHT"], "Nachzügler des folgenden Geräts ging weiter"
    # B greift selbst zu: der spätere Griff gewinnt, A folgt jetzt B
    _ansicht(b, griff=True, abstand=430.0, voll=True)
    _bekam_ansicht(a, sa, 430.0)
    _warten(lambda: _geraet(rt, "Kopplung iPad")["fuehrt"] and not _geraet(rt, "Kopplung Mac")["fuehrt"])
    _warten(lambda: _aktiv(rt) == "Kopplung iPad")
    # A meldet sich nach einer Pause ohne Griff: Nach FUEHRUNG_PAUSE_S darf es übernehmen
    sb = b.mark()
    time.sleep(FUEHRUNG_PAUSE_S + 0.1)
    _ansicht(a, griff=False, abstand=440.0)
    _bekam_ansicht(b, sb, 440.0)
    _warten(lambda: _geraet(rt, "Kopplung Mac")["fuehrt"])
    _, _, g, _ = b.wait_for(lambda h: h["type"] == "GERAETE" and any(
        e["fuehrt"] and e["name"] == "Kopplung Mac" for e in h["geraete"]), start=sb)
    assert check_ansicht_message(g) == []


def test_eigene_ansicht_teilt_nichts_und_bekommt_den_stand_beim_wechsel(env, paar):
    rt = env["rt"]
    a, b = paar
    _ansicht(a, griff=True, abstand=450.0, voll=True)
    _warten(lambda: _geraet(rt, "Kopplung Mac")["fuehrt"])
    b.send({"type": "ANSICHT_MODUS", "modus": "eigen"})
    _warten(lambda: _geraet(rt, "Kopplung iPad")["ansicht"] == "eigen")
    sa, sb = a.mark(), b.mark()
    _ansicht(a, griff=False, abstand=460.0)
    _ansicht(b, griff=True, abstand=470.0, voll=True)
    time.sleep(0.3)
    assert not [h for h in b.since(sb) if h["type"] == "ANSICHT"], "Eigene Ansicht bekam die gemeinsame"
    assert not [h for h in a.since(sa) if h["type"] == "ANSICHT"], "Eigene Ansicht wurde geteilt"
    # Ansichtsbefehle des Agenten: nicht an ein Gerät in der Eigenen Ansicht, an dem Kevin nicht arbeitet
    a.send({"type": "AKTIV"})
    _warten(lambda: _aktiv(rt) == "Kopplung Mac")
    sa, sb = a.mark(), b.mark()
    assert rt.view_command("view", {"standard": "top"})["ok"]
    a.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "view", start=sa)
    time.sleep(0.2)
    assert not [h for h in b.since(sb) if h["type"] == "VIEW_CMD"]
    b.send({"type": "AKTIV"})  # jetzt arbeitet Kevin dort: der Agent zeigt, wo er hinschaut
    _warten(lambda: _aktiv(rt) == "Kopplung iPad")
    sb = b.mark()
    assert rt.view_command("view", {"standard": "front"})["ok"]
    b.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "view", start=sb)
    # Zurück in die Gemeinsame Ansicht: B bekommt sofort den Stand des führenden Geräts
    sb = b.mark()
    b.send({"type": "ANSICHT_MODUS", "modus": "gemeinsam"})
    _, _, h, _ = _bekam_ansicht(b, sb, 460.0)
    assert h["voll"] is True and check_ansicht_message(h) == []


def test_leisten_und_kacheln_gehen_mit(env, paar):
    a, b = paar
    flaeche = {"kacheln": ["modell", "druck"], "gross": "druck", "aktiv": "druck", "leiste_links": False,
               "leiste_rechts": True, "zeitleiste": False, "zweite_ansicht": "top", "blatt": None}
    sb = b.mark()
    a.send({"type": "ANSICHT", "t": time.time(), "griff": True, "voll": False, "flaeche": flaeche})
    _, _, h, _ = b.wait_for(lambda h: h["type"] == "ANSICHT" and "flaeche" in h, start=sb, timeout=3)
    assert h["flaeche"] == flaeche and check_ansicht_message(h) == []
    # Ein Gerät, das in die Gemeinsame Ansicht wechselt, bekommt die Fläche mit dem Stand
    _ansicht(a, griff=False, abstand=490.0, voll=True)
    b.send({"type": "ANSICHT_MODUS", "modus": "eigen"})
    _warten(lambda: _geraet(env["rt"], "Kopplung iPad")["ansicht"] == "eigen")
    sb = b.mark()
    b.send({"type": "ANSICHT_MODUS", "modus": "gemeinsam"})
    _, _, h, _ = _bekam_ansicht(b, sb, 490.0)
    assert h["voll"] is True and h["flaeche"] == flaeche
    assert check_ansicht_message({"type": "ANSICHT", "t": 1.0, "griff": False, "voll": False,
                                  "flaeche": {**flaeche, "kacheln": ["modell", "fenster"]}})


def test_sprechen_live_geht_an_die_anderen_geraete(env, paar):
    alt = env["pad"]
    a, b = paar
    b.send({"type": "ANSICHT_MODUS", "modus": "eigen"})  # Striche sieht auch ein Gerät in der Eigenen Ansicht
    sa, sb, s_alt = a.mark(), b.mark(), alt.mark()
    a.send({"type": "SPRECHEN_LIVE", "sitzung": "s-1", "strich": {"nr": 1, "punkte": [[0, 0, 0], [5, 0, 0]],
                                                                  "fertig": False}, "zeiger": [5, 0, 0], "text": "hier"})
    _, _, h, _ = b.wait_for(lambda h: h["type"] == "SPRECHEN_LIVE", start=sb, timeout=3)
    assert h["strich"]["punkte"] == [[0, 0, 0], [5, 0, 0]] and isinstance(h["von"], int) and h["text"] == "hier"
    assert check_ansicht_message(h) == []
    a.send({"type": "SPRECHEN_LIVE", "sitzung": "s-1", "ende": True})
    b.wait_for(lambda h: h["type"] == "SPRECHEN_LIVE" and h.get("ende") is True, start=sb, timeout=3)
    time.sleep(0.2)
    assert not [h for h in a.since(sa) if h["type"] == "SPRECHEN_LIVE"], "eigene Striche kamen zurück"
    assert not [h for h in alt.since(s_alt) if h["type"] == "SPRECHEN_LIVE"], "App ohne ansicht-1 bekam Striche"


def test_blick_geht_an_die_anderen(env, paar):
    alt = env["pad"]
    a, b = paar
    sb, s_alt = b.mark(), alt.mark()
    a.send({"type": "BLICK", "kamera": {**KAMERA, "abstand": 333.0}, "seiten": 1.5})
    _, _, h, _ = b.wait_for(lambda h: h["type"] == "BLICK", start=sb, timeout=3)
    assert h["kamera"]["abstand"] == 333.0 and h["seiten"] == 1.5 and isinstance(h["von"], int)
    assert check_ansicht_message(h) == []
    time.sleep(0.2)
    assert not [h for h in alt.since(s_alt) if h["type"] == "BLICK"], "App ohne ansicht-1 bekam den Blick"
    assert check_ansicht_message({"type": "BLICK", "kamera": KAMERA, "seiten": 0})


def test_status_nennt_geraete_und_ansicht(env, paar):
    rt = env["rt"]
    a, _b = paar
    _ansicht(a, griff=True, abstand=480.0, voll=True)
    _warten(lambda: _geraet(rt, "Kopplung Mac")["fuehrt"])
    st = rt.status()
    assert st["kopplung"]["fuehrt"] == _geraet(rt, "Kopplung Mac")["nr"]
    text = geraete_text(st["geraete"])
    assert text and "Kopplung Mac (Mac, aktiv, führt die Gemeinsame Ansicht)" in text
    assert "Kopplung iPad (iPad, Gemeinsame Ansicht)" in text


def test_ansicht_beispiele_und_pruefung():
    for name, kopf, nutz, _richtung in ansicht_beispiele():
        assert check_ansicht_message(kopf, nutz) == [], name
    assert check_ansicht_message({"type": "ANSICHT_MODUS", "modus": "halb"})
    assert check_ansicht_message({"type": "ANSICHT", "t": 1.0, "griff": True, "voll": True, "kamera": KAMERA})
    assert check_ansicht_message({"type": "ANSICHT", "t": 1.0, "griff": False, "voll": False,
                                  "kamera": {**KAMERA, "drehung": [0, 0, 1]}})
    assert check_ansicht_message({"type": "SPRECHEN_LIVE", "sitzung": "s", "strich": {"nr": 1, "punkte": [[0, 0]],
                                                                                    "fertig": True}})
    assert geraete_text([{"nr": 1, "art": "mac", "name": "MacBook", "aktiv": True}]) is None
