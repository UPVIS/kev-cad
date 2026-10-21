"""Spiegel-Simulator (tools/mirror_sim.py) gegen MIRROR.md: Handschlag, Miete, voller Stand, Netze, Live-Aufbau,
Befehle, Vorrang, Kamera latest-only, Neustart mit neuer Epoche."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

import pytest
from mirror_testutil import MirrorClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mirror_sim import MirrorSim  # noqa: E402

RECORDING = ROOT.parent / "samples" / "mirror-recordings" / "gestell.kcadrec"


@pytest.fixture
def sock_dir():
    d = tempfile.mkdtemp(prefix="kcs", dir="/tmp")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_sim(sock_dir: str, **kw) -> MirrorSim:
    kw.setdefault("quiet", True)
    kw.setdefault("start_full", True)
    kw.setdefault("build_on_watch", False)
    return MirrorSim(os.path.join(sock_dir, "s.sock"), RECORDING, **kw).start()


def watched(sim: MirrorSim) -> MirrorClient:
    c = MirrorClient(sim.socket_path)
    c.hello()
    c.wait_for(lambda h: h["type"] == "HELLO")
    c.watch()
    c.wait_for(lambda h: h["type"] == "STATE")
    c.wait_for(lambda h: h["type"] == "SCENE" and h["seite"] == h["seiten"] - 1)
    return c


def test_socket_rights_and_handshake(sock_dir):
    sim = make_sim(sock_dir)
    try:
        assert stat.S_IMODE(os.stat(sim.socket_path).st_mode) == 0o600
        c = MirrorClient(sim.socket_path)
        c.hello()
        h = c.wait_for(lambda h: h["type"] == "HELLO")
        assert h["version"] == 1 and len(h["epoche"]) == 16 and h["features"] == ["kcad-mesh-1"]
        assert h["project"]["name"] == "gestell" and h["prio"] == "zustand" and h["seq"] == 1
        assert h["agents"][0]["aktiv"] is True
        # Ohne Miete nur HELLO und AGENTS
        sim.next_selection()
        sim.toggle_second_agent()
        a = c.wait_for(lambda h: h["type"] == "AGENTS")
        assert [x["aktiv"] for x in a["agents"]].count(True) == 1 and len(a["agents"]) == 2
        time.sleep(0.2)
        assert {h["type"] for h in c.headers()} == {"HELLO", "AGENTS"}
        c.close()
    finally:
        sim.stop()


def test_full_state_meshes_and_limits(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = watched(sim)
        parts = c.scene_parts()
        assert len(parts) == 17
        scene = c.headers("SCENE")[0]
        assert scene["project"] == {"name": "gestell"}, "kein Pfad in SCENE"
        state = c.headers("STATE")[0]
        for key in ("kamera", "auswahl", "verborgen", "isoliert", "hervorgehoben", "darstellung", "schnitt", "masse",
                    "befunde", "lauf"):
            assert key in state
        hashes = c.request_missing()
        assert c.wait_until(lambda: all(h in c.meshes for h in hashes), timeout=10)
        assert c.mesh_errors == []
        for _, h, p in c.frames:
            assert len(json.dumps(h, ensure_ascii=False).encode()) <= 16 * 1024
            assert len(p) <= 64 * 1024
        seqs = [h["seq"] for h in c.headers()]
        assert seqs == list(range(1, len(seqs) + 1))
        c.close()
    finally:
        sim.stop()


def test_live_build_in_kernel_order(sock_dir):
    sim = make_sim(sock_dir, start_full=False, speed=20)
    try:
        c = watched(sim)
        assert c.scene_parts() == []
        start = c.mark()
        sim.build()
        c.wait_for(lambda h: h["type"] == "STATE_DELTA" and "lauf" in h and not h["lauf"]["laeuft"], start=start)
        recorded = [h["name"] for h, _ in sim.frames if h["type"] == "PART_UPSERT"]
        # Das Ende des Laufs (zustand) darf die letzten Teile (szene) überholen
        assert c.wait_until(lambda: len(c.headers("PART")) == len(recorded))
        assert [h["name"] for h in c.headers("PART")] == recorded
        deltas = c.headers("STATE_DELTA")
        assert deltas[0]["lauf"]["laeuft"] is True and deltas[0]["auswahl"] == {"run": 1, "refs": []}
        assert all(d["quelle"] == "agent" for d in deltas)
        revs = [d["rev"] for d in deltas]
        assert revs == sorted(revs)
        c.close()
    finally:
        sim.stop()


def test_commands_answer_and_echo(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = watched(sim)
        names = [p["name"] for p in c.scene_parts()]
        c.cmd("i1", "auswahl", refs=[names[0]], run=1, modus="setzen")
        r = c.wait_for(lambda h: h["type"] == "CMD_RES" and h["reply_to"] == "i1")
        assert r["ok"] is True and r["fehler"] is None
        d = c.wait_for(lambda h: h["type"] == "STATE_DELTA" and "auswahl" in h)
        assert d["quelle"] == "iphone" and d["auswahl"]["refs"] == [names[0]]

        c.cmd("i2", "sichtbarkeit", mode="isolate", refs=["Gestell"])
        r = c.wait_for(lambda h: h.get("reply_to") == "i2")
        assert r["ok"] is True
        d = c.wait_for(lambda h: h["type"] == "STATE_DELTA" and h.get("isoliert"))
        assert all(n.startswith("Gestell/") for n in d["isoliert"]) and "Deckel" in d["verborgen"]

        start = c.mark()
        c.cmd("i3", "sichtbarkeit", mode="show_all", refs=[])
        d = c.wait_for(lambda h: h["type"] == "STATE_DELTA" and "isoliert" in h, start=start)
        assert d["isoliert"] is None and d["verborgen"] == []

        start = c.mark()
        cam = dict(sim.view["kamera"], distance=1234.0)
        c.cmd("i4", "kamera", kamera=cam)
        k = c.wait_for(lambda h: h["type"] == "CAMERA", start=start)
        assert k["quelle"] == "iphone" and k["kamera"]["distance"] == 1234.0
        time.sleep(0.1)
        assert not any(h.get("reply_to") == "i4" for h in c.headers("CMD_RES")), "kamera ohne CMD_RES"

        for cid, op, args in (("i5", "darstellung", {"display": "glas"}), ("i6", "zaubern", {}),
                              ("i7", "ansicht", {"standard": "schraeg"})):
            c.cmd(cid, op, **args)
            r = c.wait_for(lambda h, cid=cid: h.get("reply_to") == cid)
            assert r["ok"] is False and r["fehler"]

        c.cmd("i8", "ansicht", standard="top", projection="orthographic")
        assert c.wait_for(lambda h: h.get("reply_to") == "i8")["ok"] is True
        k = c.wait_for(lambda h: h["type"] == "CAMERA" and h["kamera"]["ortho"])
        assert k["kamera"]["rotation"] == [0.0, 0.0, 0.0, 1.0]
        c.close()
    finally:
        sim.stop()


def test_state_overtakes_meshes(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = watched(sim)
        c.pause_reading()  # Socketpuffer laufen voll: der Schreibfaden hängt im ersten Netzblock
        hashes = sorted({p["hash"] for p in c.scene_parts()})
        c.send({"type": "MESH_REQ", "prio": "zustand", "hashes": hashes})
        time.sleep(0.3)
        start = c.mark()
        sim.next_selection()
        time.sleep(0.1)
        c.resume_reading()
        c.wait_until(lambda: all(h in c.meshes for h in hashes), timeout=10)
        later = [h["type"] for h in c.headers()[start:]]
        assert "STATE_DELTA" in later
        before = later[:later.index("STATE_DELTA")].count("MESH")
        assert before <= 2, f"{before} Netzblöcke vor dem Zustand"
        assert later.count("MESH") > before
        c.close()
    finally:
        sim.stop()


def test_camera_latest_only_and_rate(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = watched(sim)
        start = c.mark()
        sim.orbit(seconds=1.0, rate=200)
        time.sleep(0.15)
        timed = [(t, h) for t, h, _ in c.frames[start:] if h["type"] == "CAMERA"]
        cams = [h for _, h in timed]
        rate = (len(timed) - 1) / (timed[-1][0] - timed[0][0])
        assert len(cams) >= 20 and rate <= 44, (len(cams), rate)
        assert cams[-1]["kamera"] == sim.view["kamera"], "der letzte Stand kommt an"
        revs = [h["rev"] for h in cams]
        assert revs == sorted(revs)
        c.close()
    finally:
        sim.stop()


def test_lease_expires_and_unwatch(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = MirrorClient(sim.socket_path)
        c.hello()
        c.watch(dauer_s=0.3)
        c.wait_for(lambda h: h["type"] == "STATE")
        time.sleep(0.5)
        start = c.mark()
        sim.next_selection()
        time.sleep(0.2)
        assert c.headers()[start:] == []
        c.watch(dauer_s=30)
        c.wait_for(lambda h: h["type"] == "STATE", start=start)
        c.send({"type": "UNWATCH", "prio": "zustand"})
        time.sleep(0.2)
        start = c.mark()
        sim.next_selection()
        time.sleep(0.2)
        assert c.headers()[start:] == []
        c.close()
    finally:
        sim.stop()


def test_restart_brings_new_epoch(sock_dir):
    sim = make_sim(sock_dir)
    try:
        c = watched(sim)
        old = c.headers("HELLO")[0]["epoche"]
        sim.restart(pause_s=0.2)
        assert c.closed.wait(2)
        c2 = MirrorClient(sim.socket_path)
        c2.hello()
        h = c2.wait_for(lambda h: h["type"] == "HELLO")
        assert h["epoche"] != old
        c2.watch()
        s = c2.wait_for(lambda h: h["type"] == "STATE")
        assert s["epoche"] == h["epoche"]
        c2.close()
    finally:
        sim.stop()
