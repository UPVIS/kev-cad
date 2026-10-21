"""Kernel-Laufzeit mit echtem Rechenprozess und einer Test-App am Unix-Socket (eigene Sockets im Temp-Ordner)."""

import os
import random
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.protocol import FrameReader, encode_frame, unpack_part
from kevcad_kernel.runtime import KernelRuntime

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class FakeApp:
    """Minimale App: verbindet sich, sammelt Rahmen mit Empfangszeit, beantwortet VIEW_CMD und SCREENSHOT_REQ."""

    def __init__(self, path: str, answer: bool = True) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.frames: list[tuple[float, dict, bytes]] = []
        self.cond = threading.Condition()
        self.answer = answer
        self.seq = 0
        self.closed = False
        threading.Thread(target=self._read, daemon=True).start()
        self.send({"type": "HELLO_APP", "app_version": "test", "bundle_id": "de.upvis.kevcad.pytest"})

    def send(self, header: dict, payload: bytes = b"") -> None:
        self.seq += 1
        self.sock.sendall(encode_frame({**header, "seq": self.seq}, payload))

    def _read(self) -> None:
        reader = FrameReader()
        while True:
            try:
                data = self.sock.recv(1 << 16)
            except OSError:
                break
            if not data:
                break
            for h, p in reader.feed(data):
                with self.cond:
                    self.frames.append((time.perf_counter(), h, p))
                    self.cond.notify_all()
                if self.answer and h["type"] == "VIEW_CMD":
                    self.send({"type": "ACK", "reply_to": h["id"], "ok": True, "message": f"{h['cmd']} ok"})
                elif self.answer and h["type"] == "SCREENSHOT_REQ":
                    self.send({"type": "SCREENSHOT_RES", "reply_to": h["id"], "ok": True, "width": h["width"],
                               "height": h["height"], "camera": {"projection": "perspective"}, "mm_per_px": None},
                              PNG)
        self.closed = True

    def wait_for(self, pred, timeout: float = 30.0, start: int = 0):
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                for i, (t, h, p) in enumerate(self.frames[start:], start):
                    if pred(h):
                        return i, t, h, p
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"Rahmen nicht angekommen; bisher: {[h['type'] for _, h, _ in self.frames]}")
                self.cond.wait(left)

    def mark(self) -> int:
        with self.cond:
            return len(self.frames)

    def since(self, start: int) -> list[dict]:
        with self.cond:
            return [h for _, h, _ in self.frames[start:]]

    def close(self) -> None:
        self.sock.close()


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kc", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = KernelRuntime(sock, 47999, auto_run=False, run_timeout_s=60)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    yield {"rt": rt, "app": app, "tmp": tmp, "sock": sock}
    app.close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)
    assert not os.path.exists(sock)


_counter = iter(range(1, 10_000))


def project(env, code: str | None = None, template: str = "empty") -> Path:
    path = env["tmp"] / f"P{next(_counter)}"
    start = env["app"].mark()
    res = env["rt"].project_new(str(path), template)
    assert res["ok"], res
    env["app"].wait_for(lambda h: h["type"] == "PROJECT" and h["name"] == path.name, start=start)
    if code is not None:
        assert env["rt"].model_write(code)["ok"]
    return path


HEAD = "from build123d import *\nfrom kevcad import show, step, param\n"


# ---------------------------------------------------------------------------------------------------------------------


def test_hello_and_no_app_errors(env):
    _, _, hello, _ = env["app"].wait_for(lambda h: h["type"] == "HELLO")
    assert hello["protocol"] == 1 and hello["mcp_port"] == 47999 and hello["build123d"].startswith("0.13")
    assert hello["seq"] == 1
    # ohne App: sofortige, klare Fehlermeldung
    tmp = Path(tempfile.mkdtemp(prefix="kc"))
    rt2 = KernelRuntime(str(tmp / "x.sock"), 0, auto_run=False, start_worker=False)
    try:
        t0 = time.perf_counter()
        assert rt2.view_command("view", {"standard": "iso"}) == {"ok": False, "error": "App nicht verbunden"}
        assert rt2.screenshot() == {"ok": False, "error": "App nicht verbunden"}
        assert time.perf_counter() - t0 < 0.5
        assert rt2.run()["ok"] is False and "Kein Projekt" in rt2.run()["error"]
    finally:
        rt2.close()


def test_example_run_parts_and_frame_order(env):
    rt, app = env["rt"], env["app"]
    project(env, template="example")
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    names = [p["name"] for p in res["parts"]]
    assert names == ["Halter/Grundplatte", "Halter/Lasche", "Rohr"]
    platte = res["parts"][0]
    assert platte["bbox"]["size"] == [60.0, 5.0, 120.0]
    assert platte["material"] == "aluminium" and abs(platte["mass"] - platte["volume"] * 2.7e-3) < 1e-6
    assert res["steps"] == ["Grundplatte", "Bohrungen", "Lasche mit Schelle", "Rohr"]
    assert res["params"]["rohr_d"] == 42.4

    app.wait_for(lambda h: h["type"] == "RUN_END" and h["run"] == res["run"], start=start)
    frames = [h for h in app.since(start) if h["type"] != "STATUS"]
    types = [h["type"] for h in frames]
    assert types[0] == "RUN_START" and types[-1] == "RUN_END"
    assert types == ["RUN_START", "STEP", "PART_UPSERT", "STEP", "PART_UPSERT", "STEP", "PART_UPSERT", "STEP",
                     "PART_UPSERT", "RUN_END"]
    # STEP kommt vor dem Teil, das in diesem Schritt entsteht
    assert frames[1]["text"] == "Grundplatte" and frames[2]["name"] == "Halter/Grundplatte"
    seqs = [h["seq"] for h in app.since(start)]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    end = frames[-1]
    assert end["parts"] == 3 and end["triangles"] == sum(p["triangles"] for p in res["parts"])
    # Teile lassen sich dekodieren und passen zu den Kopfwerten
    for t, h, p in app.frames[start:]:
        if h["type"] == "PART_UPSERT":
            arrays = unpack_part(h, p)
            assert len(arrays["triangles"]) == h["counts"]["tri"]
            assert len(h["faces"]) == h["counts"]["face"] and len(h["edges"]) == h["counts"]["edge"]
            assert arrays["tri_face"].max() == h["counts"]["face"] - 1
            assert np.all(arrays["positions"].min(axis=0) >= np.array(h["bbox"]["min"]) - 0.01)
    # Version abgelegt
    versions = sorted((Path(rt.status()["project"]["path"]) / ".kevcad/versions").glob("*-model.py"))
    assert [v.name for v in versions] == ["0001-model.py"]


def test_show_arrives_before_script_finishes(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "import time\nshow(Box(10, 10, 10), 'Erst')\ntime.sleep(1.5)\nshow(Sphere(4), 'Dann')\n")
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    _, t_part, _, _ = app.wait_for(lambda h: h["type"] == "PART_UPSERT" and h["name"] == "Erst", start=start)
    _, t_end, _, _ = app.wait_for(lambda h: h["type"] == "RUN_END", start=start)
    _, t_start, _, _ = app.wait_for(lambda h: h["type"] == "RUN_START", start=start)
    assert t_end - t_part > 1.2, "erstes Teil kam nicht live"
    assert t_part - t_start < 0.3 + 0.2, "erstes Teil kam zu spät"  # Ziel unter 300 ms (plus Testspielraum)


def test_syntax_error_reports_line(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "\nplatte = Box(10, 20, 30)\nshow(platte, 'Platte')\nx = (1,\n")
    start = app.mark()
    res = rt.run()
    assert res["ok"] is False
    err = res["error"]
    assert err["message"].startswith("SyntaxError") and err["line"] == 6
    assert "> 6 | x = (1," in err["excerpt"] and err["hint"]
    _, _, frame, _ = app.wait_for(lambda h: h["type"] == "RUN_ERROR", start=start)
    assert frame["line"] == 6 and frame["run"] == res["run"]


def test_runtime_error_keeps_last_good_geometry(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "show(Box(10, 10, 10), 'A')\nshow(Box(5, 5, 5), 'B')\n")
    good = rt.run()
    assert good["ok"]
    code = HEAD + "show(Box(10, 10, 12), 'A')\n\nplatte = Boxx(10, 20, 30)\nshow(platte, 'B')\n"
    rt.model_write(code)
    start = app.mark()
    res = rt.run()
    assert res["ok"] is False
    err = res["error"]
    assert err["message"] == "NameError: name 'Boxx' is not defined"
    assert err["line"] == 5 and "> 5 | platte = Boxx(10, 20, 30)" in err["excerpt"]
    assert "Meinten Sie Box" in err["hint"]
    assert "model.py, Zeile 5" in err["traceback"]
    assert "site-packages" not in err["traceback"]
    # B aus dem guten Lauf bleibt stehen, kein PART_REMOVE
    assert {p["name"] for p in rt.parts()} == {"A", "B"}
    assert not [h for h in app.since(start) if h["type"] == "PART_REMOVE"]
    assert rt.status()["last_run"]["ok"] is False


def test_removed_parts_and_same_name_replaces(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "show(Box(1, 1, 1), 'A')\nshow(Box(2, 2, 2), 'B')\n")
    assert rt.run()["ok"]
    rt.model_write(HEAD + "show(Box(1, 1, 1), 'A')\nshow(Box(3, 3, 3), 'A')\n")
    start = app.mark()
    res = rt.run()
    assert [p["name"] for p in res["parts"]] == ["A"]
    assert res["parts"][0]["bbox"]["size"] == [3.0, 3.0, 3.0]
    removes = [h for h in app.since(start) if h["type"] == "PART_REMOVE"]
    assert [h["name"] for h in removes] == ["B"]
    types = [h["type"] for h in app.since(start) if h["type"] != "STATUS"]
    assert types.index("PART_REMOVE") < types.index("RUN_END")


def test_show_variants(env):
    rt = env["rt"]
    code = HEAD + """
with BuildPart() as bp:
    Box(10, 10, 10)
show(bp, "Builder", color="red")
with BuildSketch() as sk:
    Circle(5)
show(sk, "Skizze2D", color=(255, 128, 0))
show(Box(4, 4, 4).edges(), "Kanten", color=(0.1, 0.2, 0.3, 0.5))
a = Box(2, 2, 2); a.label = "Links"; a.color = Color("blue")
b = Pos(5, 0, 0) * Box(2, 2, 2); b.label = "Rechts"
c = Pos(9, 0, 0) * Box(2, 2, 2); c.label = "Rechts"
innen = Compound(label="Innen", children=[Pos(0, 9, 0) * Box(1, 1, 1)])
innen.children[0].label = "Klotz"
show(Compound(label="G", children=[a, b, c, innen]), "Gruppe", material="messing")
show(Box(1, 1, 1), "Falsch", color="nichtfarbe", material="unobtainium")
show(Box(1, 1, 1), "Eiche", material="oak")
"""
    project(env, code)
    res = rt.run()
    assert res["ok"], res.get("error")
    parts = {p["name"]: p for p in res["parts"]}
    assert set(parts) == {"Builder", "Skizze2D", "Kanten", "Gruppe/Links", "Gruppe/Rechts", "Gruppe/Rechts 2",
                          "Gruppe/Innen/Klotz", "Falsch", "Eiche"}
    assert parts["Builder"]["color"] == [1.0, 0.0, 0.0, 1.0]
    assert abs(parts["Skizze2D"]["color"][1] - 128 / 255) < 1e-6 and parts["Skizze2D"]["volume"] == 0
    assert parts["Kanten"]["faces"] == 0 and parts["Kanten"]["edges"] == 12 and parts["Kanten"]["color"][3] == 0.5
    assert parts["Gruppe/Links"]["color"][:3] == [0.0, 0.0, 1.0]  # eigene Farbe des Kindes
    assert parts["Gruppe/Rechts"]["material"] == "messing" and parts["Gruppe/Rechts"]["mass"] > 0
    assert parts["Falsch"]["material"] is None and parts["Falsch"]["mass"] is None
    assert any("nichtfarbe" in w for w in res["warnings"]) and any("unobtainium" in w for w in res["warnings"])
    assert parts["Eiche"]["mass"] is not None


def test_params_override_and_warnings(env):
    rt = env["rt"]
    project(env, HEAD + "b = param('breite', 120, min=10, max=200)\nn = param('anzahl', 3)\n"
                        "for i in range(n):\n    show(Pos(i * 2 * b, 0, 0) * Box(b, 10, 10), f'Teil {i}')\n")
    res = rt.run(params={"breite": 250, "anzahl": 2.0})
    assert res["ok"], res.get("error")
    assert res["params"] == {"breite": 250, "anzahl": 2}
    assert len(res["parts"]) == 2 and res["parts"][0]["bbox"]["size"][0] == 250.0
    assert any("Maximum" in w for w in res["warnings"])
    res = rt.run()  # ohne Vorgaben wieder die Werte aus model.py
    assert res["params"] == {"breite": 120, "anzahl": 3} and len(res["parts"]) == 3


def test_rerun_uses_cache(env):
    rt = env["rt"]
    r = random.uniform(10, 20)  # Formen, die der Zwischenspeicher noch nicht kennt
    code = HEAD + f"""
r = {r!r}
for i in range(6):
    k = fillet(Box(4 * r, 3 * r, 2 * r).edges(), r / 4) - Pos(r, 0, 0) * Sphere(r * 0.8)
    show(Pos(0, i * 5 * r, 0) * k, f"Teil {{i}}")
"""
    project(env, code)
    first = rt.run()
    second = rt.run()
    assert first["ok"] and second["ok"]
    assert first["cached_parts"] == 0 and second["cached_parts"] == 6
    assert second["tess_ms"] < first["tess_ms"] / 5
    assert second["duration_ms"] < first["duration_ms"]
    # Referenzen aus Lauf 1 gelten weiter, weil sich die Formen nicht geändert haben
    m = rt.measure(["Teil 0#f0"], run=first["run"])
    assert m["ok"], m


def test_timeout_restarts_worker(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "show(Box(1, 1, 1), 'Vorher')\nwhile True:\n    pass\n")
    pid = rt.status()["worker"]["pid"]
    start = app.mark()
    t0 = time.perf_counter()
    res = rt.run(timeout_s=3)
    assert time.perf_counter() - t0 < 8
    assert res["ok"] is False and "Zeitlimit" in res["error"]["message"]
    app.wait_for(lambda h: h["type"] == "RUN_ERROR", start=start)
    rt.model_write(HEAD + "show(Box(2, 2, 2), 'Danach')\n")
    res = rt.run()
    assert res["ok"], res.get("error")
    assert rt.status()["worker"]["pid"] != pid
    assert [p["name"] for p in res["parts"]] == ["Danach"]


def test_crash_restarts_worker(env):
    rt = env["rt"]
    project(env, HEAD + "import os\nshow(Box(1, 1, 1), 'A')\n\nos.abort()\n")
    res = rt.run()
    assert res["ok"] is False
    assert "abgestürzt" in res["error"]["message"]
    assert res["error"]["line"] == 6  # aus der faulthandler-Ausgabe (HEAD hat 2 Zeilen)
    rt.model_write(HEAD + "show(Box(2, 2, 2), 'B')\n")
    assert rt.run()["ok"]


def test_execute_namespace_and_sketch(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "platte = Box(10, 20, 30)\nshow(platte, 'Platte')\n")
    assert rt.run()["ok"]
    start = app.mark()
    res = rt.execute("print('Hallo')\nv = platte.volume\nshow(Pos(20, 0, 0) * Box(1, 1, 1), 'Hilfe')\nv * 2")
    assert res["ok"], res
    assert res["stdout"] == "Hallo\n" and res["result"] == "12000.0"
    _, _, part, _ = app.wait_for(lambda h: h["type"] == "PART_UPSERT", start=start)
    assert part["name"] == "Skizze/Hilfe" and part["color"][3] == 0.5
    assert "Skizze/Hilfe" in [p["name"] for p in rt.parts()]
    bad = rt.execute("1 / 0")
    assert bad["ok"] is False and "ZeroDivisionError" in bad["error"]
    # nächster Lauf entfernt die Skizze wieder
    assert [p["name"] for p in rt.run()["parts"]] == ["Platte"]


def test_measure_via_service_and_app(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "show(Box(10, 10, 10), 'A')\nshow(Pos(30, 0, 0) * Box(10, 10, 10), 'B')\n"
                        "show(Cylinder(5, 20), 'Zyl')\n")
    run = rt.run()["run"]
    res = rt.measure(["A", "B"], show=True)
    assert res["ok"] and res["text"] == "Abstand 20,000 mm (dx 20,000)"
    _, _, ann, _ = app.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "annotate")
    assert ann["args"]["kind"] == "dimension" and ann["args"]["text"] == res["text"]
    assert rt.measure(["A#f0", "A#f4"])["values"]["angle"] == 90.0
    assert rt.measure(["Zyl#f0"])["values"]["radius"] == 5.0
    assert rt.measure(["Nix"])["ok"] is False
    # Anfrage aus der App
    start = app.mark()
    app.send({"type": "MEASURE_REQ", "id": "a-1", "refs": ["A#f1", "B#f0"], "run": run, "show": False})
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == "a-1", start=start)
    assert reply["type"] == "MEASURE_RES" and reply["result"]["values"]["plane_distance"] == 20.0
    app.send({"type": "MEASURE_REQ", "id": "a-2", "refs": ["A#f99"], "run": run, "show": False})
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == "a-2", start=start)
    assert reply["type"] == "ERROR" and "6 Flächen" in reply["message"]
    # Auswahl aus der App mit Detailwerten
    app.send({"type": "SELECTION", "run": run, "refs": ["Zyl#f0", "A#e0"]})
    deadline = time.monotonic() + 5
    while rt.selection()["refs"] != ["Zyl#f0", "A#e0"] and time.monotonic() < deadline:
        time.sleep(0.02)
    sel = rt.selection()
    assert sel["run"] == run and sel["details"][0]["values"]["radius"] == 5.0
    assert sel["details"][1]["values"]["length"] == 10.0


def test_view_commands_and_screenshot(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "show(Box(10, 10, 10), 'Halter/A')\nshow(Box(1, 1, 1), 'B')\n")
    assert rt.run()["ok"]
    assert rt.view_command("view", {"standard": "iso", "fit": True}) == {"ok": True, "message": "view ok"}
    assert rt.view_command("focus", {"refs": ["Gibtsnicht"]})["ok"] is False
    assert rt.view_command("visibility", {"mode": "isolate", "refs": ["Halter"]})["ok"]
    vis = {p["name"]: p["visible"] for p in rt.parts()}
    assert vis == {"Halter/A": True, "B": False}
    shot = rt.screenshot(640, 400)
    assert shot["ok"] and shot["png"] == PNG and shot["width"] == 640 and shot["camera"]
    # App antwortet nicht: Zeitlimit
    app.answer = False
    try:
        t0 = time.perf_counter()
        res = rt.view_command("view", {"standard": "top"}, timeout_s=0.5)
        assert res["ok"] is False and "Keine Antwort" in res["error"] and time.perf_counter() - t0 < 2
    finally:
        app.answer = True


def test_export_files(env):
    rt, app = env["rt"], env["app"]
    path = project(env, template="example")
    assert rt.run()["ok"]
    res = rt.export(["step", "stl", "3mf", "glb"])
    assert res["ok"], res
    assert [Path(f).suffix for f in res["files"]] == [".step", ".stl", ".3mf", ".glb"]
    for f in res["files"]:
        assert Path(f).parent == (path / "output").resolve() and Path(f).stat().st_size > 1000
    step_text = Path(res["files"][0]).read_text(errors="replace")
    assert "Grundplatte" in step_text and "Lasche" in step_text
    assert rt.export(["dxf"])["ok"] is False
    # über die App
    start = app.mark()
    app.send({"type": "EXPORT_REQ", "id": "a-9", "formats": ["stl"], "parts": ["Rohr"]})
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == "a-9", start=start, timeout=60)
    assert reply["type"] == "EXPORT_RES" and reply["files"][0].endswith("Wandhalter-Rohr.stl") or \
        reply["files"][0].endswith("-Rohr.stl")


def test_app_requests_project_and_run(env):
    rt, app = env["rt"], env["app"]
    path = env["tmp"] / "AppProjekt"
    start = app.mark()
    app.send({"type": "PROJECT_NEW", "id": "a-20", "path": str(path), "template": "example"})
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == "a-20", start=start)
    assert reply["type"] == "PROJECT" and reply["name"] == "AppProjekt"
    app.send({"type": "PROJECT_OPEN", "id": "a-21", "path": str(env["tmp"] / "gibtsnicht")})
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == "a-21", start=start)
    assert reply["type"] == "ERROR" and "gibt es nicht" in reply["message"]
    app.send({"type": "PROJECT_OPEN", "id": "a-22", "path": str(path)})
    _, _, reply, _ = app.wait_for(lambda h: h.get("reply_to") == "a-22", start=start)
    assert reply["type"] == "PROJECT"
    start = app.mark()
    app.send({"type": "RUN_REQ", "id": "a-23", "params": None, "slow_ms": 0})
    _, _, ack, _ = app.wait_for(lambda h: h.get("reply_to") == "a-23", start=start)
    assert ack["type"] == "ACK" and ack["ok"] is True
    _, _, end, _ = app.wait_for(lambda h: h["type"] == "RUN_END", start=start)
    assert end["parts"] == 3
    rt.wait_idle()


def test_reconnect_gets_snapshot(env):
    rt = env["rt"]
    project(env, HEAD + "show(Box(1, 1, 1), 'A')\nshow(Box(2, 2, 2), 'B')\n")
    assert rt.run()["ok"]
    rt.set_agent_connected(True)
    rt.set_agent_activity("misst Abstand Lasche ↔ Grundplatte")
    second = FakeApp(env["sock"])  # ersetzt die erste Verbindung
    try:
        second.wait_for(lambda h: h["type"] == "AGENT")
        types = [h["type"] for h in second.since(0)]
        assert types[:3] == ["HELLO", "PROJECT", "STATUS"]
        assert [h["name"] for h in second.since(0) if h["type"] == "PART_UPSERT"] == ["A", "B"]
        agent = [h for h in second.since(0) if h["type"] == "AGENT"][-1]
        assert agent["connected"] is True and agent["activity"].startswith("misst")
        deadline = time.monotonic() + 5
        while not env["app"].closed and time.monotonic() < deadline:
            time.sleep(0.02)
        assert env["app"].closed  # alte Verbindung wurde getrennt
    finally:
        rt.set_agent_connected(False)
    env["app"] = second  # folgende Tests benutzen die neue Verbindung
    second.wait_for(lambda h: h["type"] == "AGENT" and h["connected"] is False)


def test_auto_run_on_save(env):
    rt, app = env["rt"], env["app"]
    project(env, HEAD + "show(Box(1, 1, 1), 'A')\n")
    assert rt.run()["ok"]
    rt.configure(auto_run=True)
    try:
        start = app.mark()
        model = Path(rt.status()["project"]["model"])
        model.write_text(HEAD + "show(Box(7, 7, 7), 'Neu')\n")
        _, _, end, _ = app.wait_for(lambda h: h["type"] == "RUN_END", start=start, timeout=15)
        assert end["parts"] == 1
        assert rt.wait_idle(10)
        assert [p["name"] for p in rt.parts()] == ["Neu"]
        # gleicher Inhalt erneut gespeichert: kein weiterer Lauf
        start = app.mark()
        model.write_text(HEAD + "show(Box(7, 7, 7), 'Neu')\n")
        time.sleep(1.0)
        assert not [h for h in app.since(start) if h["type"] == "RUN_START"]
        # Agent schreibt und rechnet selbst: der Auto-Lauf startet keinen zweiten Lauf
        start = app.mark()
        rt.model_write(HEAD + "show(Box(8, 8, 8), 'Agent')\n")
        assert rt.run()["ok"]
        time.sleep(1.0)
        assert len([h for h in app.since(start) if h["type"] == "RUN_START"]) == 1
    finally:
        rt.configure(auto_run=False)


def test_project_errors(env):
    rt = env["rt"]
    assert rt.project_open(str(env["tmp"] / "fehlt"))["ok"] is False
    p = project(env)
    res = rt.project_new(str(p))
    assert res["ok"] is False and "schon" in res["error"]
    assert rt.project_new(str(env["tmp"] / "X"), template="unbekannt")["ok"] is False
    (env["tmp"] / "nur_ordner").mkdir()
    res = rt.project_open(str(env["tmp"] / "nur_ordner"))
    assert res["ok"] is False and "model.py" in res["error"]
    assert rt.model_read()["code"].startswith('"""Neues Modell')
