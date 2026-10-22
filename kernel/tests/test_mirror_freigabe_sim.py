"""Freigabe vom iPhone im Spiegel-Simulator (MIRROR.md, Version 1.1): FREIGABE ohne Miete und nach dem HELLO,
CMD `freigabe` mit Nonce, Ablauf und Anfrage, FREIGABE_ENDE je Eintrag und für die Anfrage, Gegenstelle `--client`."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest
from mirror_testutil import MirrorClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mirror_sim import MirrorSim, freigabe_cmd, https_link, run_client  # noqa: E402

RECORDING = ROOT.parent / "samples" / "mirror-recordings" / "gestell.kcadrec"


@pytest.fixture
def sock_dir():
    d = tempfile.mkdtemp(prefix="kcf", dir="/tmp")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_sim(sock_dir: str, **kw) -> MirrorSim:
    kw.setdefault("quiet", True)
    kw.setdefault("start_full", True)
    kw.setdefault("build_on_watch", False)
    return MirrorSim(os.path.join(sock_dir, "s.sock"), RECORDING, **kw).start()


def hello(sim: MirrorSim) -> MirrorClient:
    c = MirrorClient(sim.socket_path)
    c.hello()
    c.wait_for(lambda h: h["type"] == "HELLO")
    return c


def test_https_only():
    assert https_link("https://x.de/a") == "https://x.de/a"
    assert https_link("http://x.de/a") is None
    assert https_link("javascript:alert(1)") is None
    assert https_link("https://") is None


def test_request_without_lease_and_after_hello(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = hello(sim)
        anfrage = sim.freigabe_anfragen()
        f = c.wait_for(lambda h: h["type"] == "FREIGABE")
        assert f["anfrage_id"] == anfrage and len(f["nonce"]) == 32 and f["prio"] == "zustand"
        assert [e["id"] for e in f["eintraege"]] == ["rohr-alfer-16x1", "alutec-05200", "petg-cf"]
        assert all("path" not in e for e in f["eintraege"]) and "link" not in f["eintraege"][2]
        assert not c.headers("STATE"), "ohne WATCH kein Zustand"
        # Eine später verbundene Gegenstelle bekommt die offene Anfrage gleich nach dem HELLO
        d = hello(sim)
        g = d.wait_for(lambda h: h["type"] == "FREIGABE")
        assert g["nonce"] == f["nonce"]
        c.close()
        d.close()
    finally:
        sim.stop()


def test_decide_from_iphone(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = hello(sim)
        sim.freigabe_anfragen()
        f = c.wait_for(lambda h: h["type"] == "FREIGABE")
        a, n = f["anfrage_id"], f["nonce"]
        # Falsche Nonce, falscher Eintrag, unbekannte Entscheidung
        c.send({**freigabe_cmd("i-1", a, "0" * 32, "petg-cf", "frei"), "prio": "zustand"})
        r = c.wait_for(lambda h: h["type"] == "CMD_RES" and h["reply_to"] == "i-1")
        assert (r["ok"], r["status"]) == (False, "ungueltig")
        c.send({**freigabe_cmd("i-2", a, n, "gibts-nicht", "frei"), "prio": "zustand"})
        assert c.wait_for(lambda h: h.get("reply_to") == "i-2")["status"] == "ungueltig"
        c.send({**freigabe_cmd("i-3", a, n, "petg-cf", "vielleicht"), "prio": "zustand"})
        assert c.wait_for(lambda h: h.get("reply_to") == "i-3")["status"] == "ungueltig"
        # Freigeben und ablehnen
        c.send({**freigabe_cmd("i-4", a, n, "rohr-alfer-16x1", "frei"), "prio": "zustand"})
        r = c.wait_for(lambda h: h.get("reply_to") == "i-4")
        assert (r["ok"], r["status"], r["fehler"]) == (True, "frei", None)
        e = c.wait_for(lambda h: h["type"] == "FREIGABE_ENDE" and h.get("id") == "rohr-alfer-16x1")
        assert (e["grund"], e["ergebnis"]) == ("iphone", "frei")
        # Wiederverwendet: derselbe Eintrag mit derselben Nonce
        c.send({**freigabe_cmd("i-5", a, n, "rohr-alfer-16x1", "frei"), "prio": "zustand"})
        assert c.wait_for(lambda h: h.get("reply_to") == "i-5")["status"] == "verbraucht"
        c.send({**freigabe_cmd("i-6", a, n, "alutec-05200", "abgelehnt"), "prio": "zustand"})
        assert c.wait_for(lambda h: h.get("reply_to") == "i-6")["status"] == "abgelehnt"
        # Der letzte am Mac: Eintrag und Anfrage enden mit grund mac
        sim.freigabe_mac()
        e = c.wait_for(lambda h: h["type"] == "FREIGABE_ENDE" and h.get("id") == "petg-cf")
        assert e["grund"] == "mac"
        ganz = c.wait_for(lambda h: h["type"] == "FREIGABE_ENDE" and "id" not in h)
        assert ganz["grund"] == "mac" and "ergebnis" not in ganz
        c.send({**freigabe_cmd("i-7", a, n, "petg-cf", "frei"), "prio": "zustand"})
        assert c.wait_for(lambda h: h.get("reply_to") == "i-7")["status"] == "beendet"
        c.close()
    finally:
        sim.stop()


def test_expiry_and_replacement(sock_dir):
    sim = make_sim(sock_dir, freigabe_ablauf_s=0.4)
    try:
        c = hello(sim)
        sim.freigabe_anfragen()
        f = c.wait_for(lambda h: h["type"] == "FREIGABE")
        e = c.wait_for(lambda h: h["type"] == "FREIGABE_ENDE", timeout=3)
        assert e["grund"] == "abgelaufen" and e["anfrage_id"] == f["anfrage_id"]
        c.send({**freigabe_cmd("i-1", f["anfrage_id"], f["nonce"], "petg-cf", "frei"), "prio": "zustand"})
        assert c.wait_for(lambda h: h.get("reply_to") == "i-1")["status"] == "abgelaufen"
        sim.freigabe_ablauf_s = 60
        first = sim.freigabe_anfragen()
        second = sim.freigabe_anfragen()
        z = c.wait_for(lambda h: h["type"] == "FREIGABE_ENDE" and h["anfrage_id"] == first)
        assert z["grund"] == "zurueckgezogen"
        assert c.wait_for(lambda h: h["type"] == "FREIGABE" and h["anfrage_id"] == second)
        c.close()
    finally:
        sim.stop()


def test_client_mode_against_simulator(sock_dir, capsys):
    sim = make_sim(sock_dir)
    try:
        threading_timer = __import__("threading").Timer(0.5, sim.freigabe_anfragen)
        threading_timer.start()
        assert run_client(sim.socket_path, "frei", warten_s=10, pruefen=True) == 0
        out = capsys.readouterr().out
        assert "ALLES OK" in out and "falsche Nonce abgewiesen" in out
        assert not sim.freigaben
        time.sleep(0.1)
    finally:
        sim.stop()
