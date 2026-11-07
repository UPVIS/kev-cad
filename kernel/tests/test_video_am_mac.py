"""I-8 (PLAN-IPAD.md): Videos aus Animationen rechnet immer die Mac-App, auch wenn das iPad das aktive Gerät ist.

Der Kernel schickt ANIM_VIDEO_REQ an einen Mac (das aktive Gerät, wenn es einer ist, sonst den zuletzt verbundenen);
ohne Mac antwortet er mit einem Hinweis. Das iPad holt das fertige Video bei Bedarf über DATEI_REQ."""

import shutil
import tempfile
import threading
import time
from pathlib import Path

from app_testutil import FakeApp, make_runtime

MAC = {"id": "mac-v", "art": "mac", "name": "MacBook (Test)"}
PAD = {"id": "pad-v", "art": "ipad", "name": "iPad (Test)"}


def _warten(pruefung, frist: float = 10.0) -> None:
    ende = time.monotonic() + frist
    while not pruefung():
        assert time.monotonic() < ende, "Bedingung nicht erreicht"
        time.sleep(0.02)


def _anfrage(rt, ergebnis: dict) -> threading.Thread:
    def los():
        ergebnis["antwort"] = rt._request({"type": "ANIM_VIDEO_REQ", "name": "Fahrt", "width": 64, "height": 48,
                                           "fps": 10.0, "kamera": None, "format": "mp4", "path": "/tmp/x.mp4"},
                                          10, an="mac")
    t = threading.Thread(target=los)
    t.start()
    return t


def test_video_geht_an_den_mac_auch_wenn_das_ipad_aktiv_ist():
    tmp = Path(tempfile.mkdtemp(prefix="kcv", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, start_worker=False)
    mac = FakeApp(sock, geraet=MAC)
    pad = FakeApp(sock, geraet=PAD)
    try:
        mac.wait_for(lambda h: h["type"] == "HELLO")
        pad.wait_for(lambda h: h["type"] == "HELLO")
        _warten(lambda: len(rt.status()["geraete"]) == 2)
        pad.send({"type": "AKTIV"})
        _warten(lambda: next(g for g in rt.status()["geraete"] if g["aktiv"])["art"] == "ipad")
        a, b = mac.mark(), pad.mark()
        ergebnis: dict = {}
        t = _anfrage(rt, ergebnis)
        _, _, req, _ = mac.wait_for(lambda h: h["type"] == "ANIM_VIDEO_REQ", start=a)
        mac.send({"type": "ANIM_VIDEO_RES", "reply_to": req["id"], "ok": True, "path": "/tmp/x.mp4", "frames": 11,
                  "ms": 120})
        t.join(10)
        reply, _, fehler = ergebnis["antwort"]
        assert fehler is None and reply["ok"] is True and reply["frames"] == 11
        assert not [h for h in pad.since(b) if h["type"] == "ANIM_VIDEO_REQ"], "Auftrag ging ans iPad"
    finally:
        mac.close()
        pad.close()
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_ohne_mac_ein_hinweis():
    tmp = Path(tempfile.mkdtemp(prefix="kcv", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, start_worker=False)
    pad = FakeApp(sock, geraet=PAD)
    try:
        pad.wait_for(lambda h: h["type"] == "HELLO")
        # Auf die Art warten, nicht nur auf die Zahl: Bis HELLO_APP verarbeitet ist, zählt eine Verbindung ohne `geraet`
        # als Mac (Apps vor I-2), und die Anfrage ginge ans iPad (unter Last auf dem Mini so gesehen, 07.11.2026)
        _warten(lambda: [g["art"] for g in rt.status()["geraete"]] == ["ipad"])
        b = pad.mark()
        ergebnis: dict = {}
        _anfrage(rt, ergebnis).join(10)
        _, _, fehler = ergebnis["antwort"]
        assert fehler and "Kein Mac verbunden" in fehler
        assert not [h for h in pad.since(b) if h["type"] == "ANIM_VIDEO_REQ"]
    finally:
        pad.close()
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_app_ohne_geraet_gilt_als_mac():
    tmp = Path(tempfile.mkdtemp(prefix="kcv", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock, start_worker=False)
    alt = FakeApp(sock)  # App vor I-2, ohne geraet
    try:
        alt.wait_for(lambda h: h["type"] == "HELLO")
        _warten(lambda: rt._link.mac is not None)
    finally:
        alt.close()
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)
