"""V2-5 Live im Kernel (PROTOCOL.md, Abschnitt „V2-5 Live“): Weiche je Verbindung, Delta, WIE_ZUVOR, IN_ARBEIT,
Agentenspur, Lagebild, Live-Maße. Erst die Weiche allein, dann Läufe mit Rechenprozess und App-Attrappe."""

from __future__ import annotations

import collections
import json
import shutil
import tempfile
import time
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel.live import Agentenspur, LiveVerbindung
from kevcad_kernel.protocol import (
    KERNEL_FAEHIGKEITEN, TEIL_INHALTE, WIE_ZUVOR_ARTEN, WIE_ZUVOR_BASEN, encode_frame, kanonisch, pack_check,
    unpack_netze, wie_zuvor_aufbauen,
)

ALLE = list(KERNEL_FAEHIGKEITEN)
NEU = {"PART_SAME", "WIE_ZUVOR", "IN_ARBEIT", "AGENT_SPUR", "AGENT_SCHRITT", "LAGE_REQ"}


# =====================================================================================================================
# Was eine App mit delta-1 aus den Rahmen macht (zum Prüfen des Kernels)
# =====================================================================================================================


class AppSicht:
    """Teile (Name → gezeigter (inhalt, run)), die letzten Inhalte je Teil und Basen für WIE_ZUVOR, wie eine App mit
    delta-1 sie führt (PROTOCOL.md)."""

    def __init__(self) -> None:
        self.teile: dict[str, tuple[str | None, int]] = {}
        self.inhalte: dict[str, list[str]] = {}
        self.reihenfolge: list[str] = []
        self.basen: dict[str, collections.deque] = {}
        self.letzte: dict[str, dict] = {}
        self.anfragen: list[list[str]] = []  # PARTS_REQ, die die App schicken müsste

    def verarbeite(self, h: dict, p: bytes) -> dict:
        if h["type"] == "WIE_ZUVOR":
            basis = next((b for b in self.basen.get(h["art"], ()) if b[0] == h["basis"]), None)
            assert basis is not None, f"Basis {h['basis']} von {h['art']} fehlt der App"
            h, p = wie_zuvor_aufbauen(h, basis[1]), basis[2]
        t = h["type"]
        if t in WIE_ZUVOR_ARTEN and not h.get("reply_to"):
            dq = self.basen.setdefault(t, collections.deque(maxlen=WIE_ZUVOR_BASEN))
            dq.append((h["seq"], {k: v for k, v in h.items() if k != "seq"}, p))
            self.letzte[t] = h
        if t == "PART_UPSERT":
            if h["name"] not in self.teile:
                self.reihenfolge.append(h["name"])
            self.teile[h["name"]] = (h.get("inhalt"), h["run"])
            self._zeige(h["name"], h.get("inhalt"))
        elif t == "PART_SAME":
            if h["inhalt"] not in self.inhalte.get(h["name"], ()):
                self.anfragen.append([h["name"]])
            else:
                self.teile[h["name"]] = (h["inhalt"], h["run"])
                self._zeige(h["name"], h["inhalt"])
        elif t == "PART_REMOVE":
            self.teile.pop(h["name"], None)
            self.inhalte.pop(h["name"], None)
            if h["name"] in self.reihenfolge:
                self.reihenfolge.remove(h["name"])
        elif t == "RUN_END" and "teile" in h:
            for n in list(self.teile):
                if n not in h["teile"]:
                    del self.teile[n]
                    self.inhalte.pop(n, None)
            self.reihenfolge = [n for n in self.reihenfolge if n in self.teile]
        return h

    def _zeige(self, name: str, inhalt: str | None) -> None:
        if not inhalt:
            self.inhalte.pop(name, None)
            return
        liste = self.inhalte.setdefault(name, [])
        if inhalt in liste:
            liste.remove(inhalt)
        liste.append(inhalt)
        del liste[:-TEIL_INHALTE]


# =====================================================================================================================
# Weiche allein
# =====================================================================================================================


def _teil(name: str, run: int, inhalt: str, **extra) -> tuple[dict, bytes]:
    return {"type": "PART_UPSERT", "run": run, "name": name, "color": [1, 1, 1, 1], "inhalt": inhalt,
            "counts": {"vert": 0}, **extra}, b"\x00" * 64


def _durch(lv: LiveVerbindung, rahmen: list[tuple[dict, bytes]], start: int = 1) -> list[tuple[dict, bytes, int]]:
    out = []
    seq = start
    for h, p in rahmen:
        r = lv.filtern(h, p, seq)
        if r is not None:
            out.append((r[0], r[1], seq))
            seq += 1
    return out


def test_weiche_ohne_faehigkeit_wie_bisher():
    lv = LiveVerbindung()
    lv.melden([])
    h, p = _teil("A", 1, "aaaaaaaaaaaaaaaa")
    out = _durch(lv, [({"type": "RUN_START", "run": 1}, b""), (h, p),
                      ({"type": "RUN_END", "run": 1, "teile": ["A"]}, b""),
                      ({"type": "RUN_START", "run": 2}, b""), (h | {"run": 2}, p)])
    assert [x[0]["type"] for x in out] == ["RUN_START", "PART_UPSERT", "RUN_END", "RUN_START", "PART_UPSERT"]
    assert all("inhalt" not in x[0] and "teile" not in x[0] and "delta" not in x[0] for x in out)
    assert out[1][1] == p and h["inhalt"] == "aaaaaaaaaaaaaaaa", "der Kopf des Aufrufers bleibt unverändert"
    for art in NEU:
        assert lv.filtern({"type": art, "run": 1, "name": "A", "inhalt": "a" * 16}, b"", 9) is None
    check, _ = pack_check(run=1, state="done", ergebnis={"dauer_ms": 1.0})
    assert lv.filtern(check, b"", 10)[0] is check, "ältere App: keine WIE_ZUVOR, keine Basen"
    assert lv.filtern({**check, "run": 2}, b"", 11)[0]["type"] == "CHECK"
    assert not lv.basen


def test_weiche_delta_teile():
    lv = LiveVerbindung()
    lv.melden(["delta-1"])
    a, b = "a" * 16, "b" * 16
    out = _durch(lv, [({"type": "RUN_START", "run": 1}, b""), _teil("A", 1, a), _teil("B", 1, b),
                      ({"type": "RUN_START", "run": 2}, b""), _teil("A", 2, a), _teil("B", 2, "c" * 16),
                      ({"type": "PART_REMOVE", "run": 2, "name": "A"}, b""),
                      ({"type": "RUN_END", "run": 2, "teile": ["B"]}, b""),
                      ({"type": "RUN_START", "run": 3}, b""), _teil("A", 3, a)])
    typen = [x[0]["type"] for x in out]
    assert typen == ["RUN_START", "PART_UPSERT", "PART_UPSERT", "RUN_START", "PART_SAME", "PART_UPSERT",
                     "PART_REMOVE", "RUN_END", "RUN_START", "PART_UPSERT"]
    assert out[0][0]["delta"] is True and out[4][0] == {"type": "PART_SAME", "run": 2, "name": "A", "inhalt": a}
    assert out[4][1] == b"" and out[1][0]["inhalt"] == a and out[7][0]["teile"] == ["B"]
    # PARTS_REQ: vergessene Teile gehen wieder vollständig
    lv.vergessen(["A"])
    assert lv.filtern(_teil("A", 3, a)[0], b"", 20)[0]["type"] == "PART_UPSERT"
    assert lv.filtern(_teil("A", 3, a)[0], b"", 21)[0]["type"] == "PART_SAME"
    # Teil aus einem Lauf ohne delta (Verbindung mitten im Lauf): vollständig
    lv.delta_lauf = None
    assert lv.filtern(_teil("A", 3, a)[0], b"", 22)[0]["type"] == "PART_UPSERT"


def test_weiche_wechselnde_inhalte_und_anfangsstand():
    """Ein Teil, das model.py in einem Lauf mehrmals zeigt (Kugelschieber: Rollwagen/Rahmen dreimal), kostet ab dem
    zweiten Lauf nichts mehr; ein fünfter Inhalt verdrängt den ältesten. Vor HELLO_APP bleibt inhalt drin."""
    lv = LiveVerbindung()
    h, p = _teil("R", 0, "0" * 16)
    assert lv.filtern(h, p, 1)[0]["inhalt"] == "0" * 16, "Anfangsstand vor HELLO_APP: mit inhalt"
    lv.melden(["delta-1"])
    a, b, c, d, e = ("a" * 16, "b" * 16, "c" * 16, "d" * 16, "e" * 16)
    rahmen = [({"type": "RUN_START", "run": 1}, b"")] + [_teil("R", 1, x) for x in (a, b, c)] + \
             [({"type": "RUN_START", "run": 2}, b"")] + [_teil("R", 2, x) for x in (a, b, c)]
    typen = [x[0]["type"] for x in _durch(lv, rahmen, start=2)]
    assert typen == ["RUN_START"] + ["PART_UPSERT"] * 3 + ["RUN_START"] + ["PART_SAME"] * 3
    assert lv.teile["R"] == ["0" * 16, a, b, c]
    rahmen = [({"type": "RUN_START", "run": 3}, b""), _teil("R", 3, d), _teil("R", 3, e), _teil("R", 3, "0" * 16),
              _teil("R", 3, a)]
    typen = [x[0]["type"] for x in _durch(lv, rahmen, start=20)]
    assert typen == ["RUN_START", "PART_UPSERT", "PART_UPSERT", "PART_UPSERT", "PART_UPSERT"], "ältester verdrängt"
    assert lv.teile["R"] == [d, e, "0" * 16, a] and len(lv.teile["R"]) == TEIL_INHALTE
    lv.filtern({"type": "PART_REMOVE", "run": 3, "name": "R"}, b"", 30)
    assert "R" not in lv.teile


def test_weiche_felder_animation_projekt():
    lv = LiveVerbindung()
    lv.melden(["delta-1"])
    feld = {"type": "STATICS_FIELD", "run": 1, "szenario": "S", "teil": "T", "feld": "k1"}
    assert lv.filtern(feld, b"x", 1) is not None
    assert lv.filtern({**feld, "run": 2}, b"x", 2) is None, "gleicher Schlüssel: nicht noch einmal"
    assert lv.filtern({**feld, "run": 3, "feld": "k2"}, b"y", 3) is not None
    assert lv.filtern({**feld, "run": 4, "feld": "k1"}, b"x", 3) is None, "zurück zu k1: die App hat es noch"
    for i, k in enumerate(("k3", "k4", "k5")):
        assert lv.filtern({**feld, "run": 5 + i, "feld": k}, b"z", 3) is not None
    assert lv.filtern({**feld, "run": 9, "feld": "k2"}, b"y", 3) is not None, "k2 ist verdrängt (4 je Paar)"
    assert lv.filtern({**feld, "teil": "U"}, b"x", 4) is not None, "anderes Paar"
    assert lv.filtern({"type": "PROJECT", "path": "/a"}, b"", 5) is not None
    assert lv.filtern({"type": "PROJECT", "path": "/b"}, b"", 6) is not None
    assert lv.filtern({**feld, "feld": "k2", "run": 9}, b"y", 7) is not None, "nach Projektwechsel neu"
    anim = {"type": "ANIM_DEF", "run": 1, "name": "Fahrt", "dauer": 1.0}
    koll = {"type": "ANIM_COLLISIONS", "run": 1, "name": "Fahrt", "kollisionen": []}
    assert lv.filtern(anim, b"m" * 48, 8) is not None
    assert lv.filtern(koll, b"", 9) is not None
    assert lv.filtern({**anim, "run": 2}, b"m" * 48, 10) is None
    assert lv.filtern({**koll, "run": 2}, b"", 11) is None
    assert lv.filtern({**koll, "run": 2, "reply_to": "a-1"}, b"", 12) is not None, "Antwort geht immer"
    assert lv.filtern({**anim, "run": 3}, b"n" * 48, 13) is not None, "neue Bewegung"
    assert lv.filtern({**koll, "run": 3}, b"", 14) is not None, "nach neuem ANIM_DEF kommen die Kollisionen neu"
    assert lv.filtern({"type": "ANIM_REMOVE", "name": "Fahrt"}, b"", 15) is not None
    assert lv.filtern({**anim, "run": 4}, b"n" * 48, 16) is not None, "nach ANIM_REMOVE neu"


def _check(run: int, dauer: float, **extra) -> dict:
    befunde = [{"id": f"b{i}", "art": "hinweis", "teile": ["A", "B"], "schwere": "hinweis", "text": "x" * 80,
                "ort": [i, 0, 0]} for i in range(40)]
    h, _ = pack_check(run=run, state="done", ergebnis={"dauer_ms": dauer, "befunde": befunde,
                                                       "zusammenfassung": "40 Hinweise"})
    h.pop("seq")
    return {**h, **extra}


def test_weiche_wie_zuvor_und_aufbau():
    lv = LiveVerbindung()
    lv.melden(["delta-1"])
    sicht = AppSicht()
    rahmen = [(_check(1, 900.0), b""), (_check(2, 910.5), b""), (_check(3, 911.0, statik={"ms": 5}), b""),
              (_check(4, 912.0), b"geometrie"), (_check(5, 913.0), b"geometrie")]
    out = _durch(lv, rahmen, start=40)
    typen = [x[0]["type"] for x in out]
    assert typen == ["CHECK", "WIE_ZUVOR", "WIE_ZUVOR", "CHECK", "WIE_ZUVOR"], "andere Nutzlast: vollständig"
    for h, p, seq in out:
        neu = sicht.verarbeite({**h, "seq": seq}, p)
        assert neu["type"] == "CHECK"
    assert sicht.letzte["CHECK"]["run"] == 5 and sicht.letzte["CHECK"]["duration_ms"] == 913.0
    assert out[1][0]["basis"] == 40 and len(encode_frame(out[1][0])) < 200
    # Probe: Typwechsel in sonst gleichen Teilen geht vollständig
    kopf = _check(6, 913.0)
    kopf["befunde"][3]["ort"] = [3.0, 0, 0]  # vorher 3 (Ganzzahl)
    h, p = lv.filtern({**kopf, "duration_ms": 913.0}, b"geometrie", 50)
    assert h["type"] in ("CHECK", "WIE_ZUVOR")
    gebaut = sicht.verarbeite({**h, "seq": 50}, p)
    assert kanonisch({k: v for k, v in gebaut.items() if k != "seq"}) == kanonisch({**kopf, "duration_ms": 913.0})
    # Fenster: nie eine Basis, die die App schon vergessen hat
    for i in range(20):
        h, p = lv.filtern(_check(7 + i, 900.0 + (i % 3)), b"", 60 + i)
        sicht.verarbeite({**h, "seq": 60 + i}, p)
    # NOCHMAL: die neueste vollständig
    kopf, nutz = lv.neueste("CHECK")
    assert kopf["run"] == 26 and kopf["type"] == "CHECK"
    h, _ = lv.filtern(kopf, nutz, 99, vollstaendig=True)
    assert h["type"] == "CHECK"
    assert lv.filtern({**_check(8, 1.0), "reply_to": "a-3"}, b"", 100)[0]["type"] == "CHECK", "Antworten voll"


def test_weiche_versionsbild_aus_der_szene():
    from kevcad_kernel.protocol import pack_netze

    import numpy as np

    lv = LiveVerbindung()
    lv.melden(["delta-1"])
    lv.filtern(*_teil("A", 1, "a" * 16), 1)
    netz = {"positions": np.zeros((3, 3), np.float32), "normals": np.zeros((3, 3), np.float32),
            "triangles": np.array([[0, 1, 2]], np.uint32), "edge_points": np.zeros((2, 3), np.float32),
            "edge_offsets": np.array([0, 2], np.uint32)}
    koepfe, nutz = pack_netze([({"teil": "A", "farbe": [1, 1, 1, 1], "inhalt": "a" * 16}, netz),
                               ({"teil": "B", "farbe": [1, 1, 1, 1], "inhalt": "b" * 16}, netz),
                               ({"teil": "C", "farbe": [1, 1, 1, 1]}, netz)])
    h, p = lv.filtern({"type": "VERSION_BILD_REQ", "id": "k-1", "nr": 3, "teile": koepfe}, nutz, 2)
    assert [k.get("aus_szene", False) for k in h["teile"]] == [True, False, False]
    assert "vert" not in h["teile"][0] and len(p) == len(nutz) * 2 // 3
    netze = unpack_netze(h["teile"], p)
    assert netze[0] is None and netze[1]["triangles"].tolist() == [[0, 1, 2]]
    alt = LiveVerbindung()
    alt.melden([])
    h, p = alt.filtern({"type": "VERSION_BILD_REQ", "id": "k-1", "nr": 3, "teile": koepfe}, nutz, 1)
    assert p == nutz and all("inhalt" not in k and not k.get("aus_szene") for k in h["teile"])


def test_agentenspur_haelt_50_und_ergaenzt():
    spur = Agentenspur()
    assert spur.aktualisieren({"id": "x", "text": "ohne Werkzeug"}) is None
    s = spur.aktualisieren({"id": "s-1", "werkzeug": "run", "beginn": 100.0, "stand": "laeuft", "absicht": "a" * 300})
    assert s["stand"] == "laeuft" and len(s["absicht"]) == 200
    spur.aktualisieren({"id": "s-1", "text": "führt model.py aus"})
    spur.aktualisieren({"id": "s-1", "text": "zweiter Text"})
    s = spur.aktualisieren({"id": "s-1", "stand": "fehler", "fehler": "Zeile 3: kaputt\nmehr", "ende": 101.5})
    assert s["text"] == "führt model.py aus" and s["fehler"] == "Zeile 3: kaputt" and s["dauer_ms"] == 1500.0
    for i in range(60):
        spur.aktualisieren({"id": f"s-{i + 2}", "werkzeug": "status", "stand": "ok"})
    liste = spur.liste()
    assert len(liste) == 50 and liste[-1]["id"] == "s-61" and liste[0]["id"] == "s-12"


def test_mcp_huelle_liest_anfrage_und_antwort():
    from kevcad_kernel.mcp_tools.tracking import ergebnis_aus_antwort, werkzeug_aus_anfrage

    anfrage = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                          "params": {"name": "run", "arguments": {"params": {"b": 2}, "absicht": "Breite testen"}}})
    koerper, aufruf = werkzeug_aus_anfrage(anfrage.encode())
    assert aufruf == {"name": "run", "absicht": "Breite testen"}
    assert json.loads(koerper)["params"]["arguments"] == {"params": {"b": 2}}, "absicht ist heraus"
    ohne = b'{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"status","arguments":{}}}'
    koerper, aufruf = werkzeug_aus_anfrage(ohne)
    assert koerper is ohne and aufruf == {"name": "status", "absicht": None}
    assert werkzeug_aus_anfrage(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}')[1] is None
    assert werkzeug_aus_anfrage(b"kein json mit \"tools/call\"")[1] is None
    ok = json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"content": [{"type": "text", "text": "fertig"}],
                                                          "isError": False}}).encode()
    assert ergebnis_aus_antwort(200, ok, ok[-1024:], len(ok)) == (True, None)
    fehler = json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"content": [{"type": "text", "text": "kaputt"}],
                                                              "isError": True}}).encode()
    assert ergebnis_aus_antwort(200, fehler, fehler[-1024:], len(fehler)) == (False, "kaputt")
    rpc = json.dumps({"jsonrpc": "2.0", "id": 7, "error": {"code": -32602, "message": "Unknown tool"}}).encode()
    assert ergebnis_aus_antwort(200, rpc, rpc, len(rpc)) == (False, "Unknown tool")
    gross = json.dumps({"jsonrpc": "2.0", "id": 7, "result": {
        "content": [{"type": "text", "text": "Bild fehlt"}, {"type": "image", "data": "A" * 100_000}],
        "isError": True}}).encode()
    assert ergebnis_aus_antwort(200, gross[:65536], gross[-1024:], len(gross)) == (False, "Bild fehlt")
    assert ergebnis_aus_antwort(500, b"", b"", 0) == (False, "HTTP 500")
    assert ergebnis_aus_antwort(None, b"", b"", 0)[0] is False, "ohne Antwort: kein ok"


# =====================================================================================================================
# Läufe mit Rechenprozess
# =====================================================================================================================

CODE = """from build123d import *
from kevcad import show, param
b = param("b", 20)
show(Box(b, 10, 5), "Platte")
show(Pos(30, 0, 0) * Cylinder(3, 8), "Stift")
"""

CODE_LANGSAM = """from build123d import *
from kevcad import show, param
import time
b = param("b", 20)
show(Box(b, 10, 5), "Platte")
time.sleep(0.9)
show(Pos(30, 0, 0) * Cylinder(3, 8), "Stift")
"""

LAGE = {"zeit": 1793452991.2, "ms": 1.5,
        "kamera": {"position": [0.0, -500.0, 300.0], "ziel": [0.0, 0.0, 0.0], "richtung": [0.0, 0.857, -0.514],
                   "oben": [0.0, 0.514, 0.857], "abstand": 583.1, "projektion": "perspective", "fov": 30.0,
                   "ortho_hoehe": None, "ansicht": None, "durch": None},
        "viewport": {"breite": 800, "hoehe": 600}, "sichtbar": ["Platte", "Stift"], "verborgen": [],
        "isoliert": None, "auswahl": {"run": 1, "refs": ["Platte#f0"]},
        "maus": {"teil": "Stift", "ref": "Stift#f1", "punkt": [30.0, 3.0, 4.0], "normale": [0.0, 1.0, 0.0],
                 "bild": [420, 300]},
        "darstellung": "shaded_edges", "schnitt": None, "explosion": 0.0, "animation": None}


@pytest.fixture(scope="module")
def env():
    tmp = Path(tempfile.mkdtemp(prefix="kclive", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240)
    e = {"rt": rt, "tmp": tmp, "sock": sock, "app": None}
    yield e
    if e["app"] is not None:
        e["app"].close()
    rt.close()
    shutil.rmtree(tmp, ignore_errors=True)


def verbinden(env, faehigkeiten: list[str] | None = ALLE, **kw) -> FakeApp:
    if env["app"] is not None:
        env["app"].close()
    app = FakeApp(env["sock"], faehigkeiten=faehigkeiten, **kw)
    app.wait_for(lambda h: h["type"] == "HELLO")
    rt = env["rt"]
    ende = time.monotonic() + 10
    while time.monotonic() < ende:  # bis die Laufzeit HELLO_APP verarbeitet hat
        conn = rt._link.connection
        if conn is not None and conn.live.gemeldet:
            break
        time.sleep(0.01)
    env["app"] = app
    return app


_n = iter(range(1, 1000))


def projekt(env, code: str = CODE) -> Path:
    path = env["tmp"] / f"P{next(_n)}"
    assert env["rt"].project_new(str(path), "empty")["ok"]
    settings = json.loads((path / "kevcad.json").read_text())
    (path / "kevcad.json").write_text(json.dumps({**settings, "inventar_regel": False}))
    assert env["rt"].model_write(code)["ok"]
    assert env["rt"].wait_idle(60)
    return path


def lauf(env, **kw) -> dict:
    rt = env["rt"]
    res = rt.run(**kw)
    assert res["ok"], res.get("error")
    assert rt.wait_idle(60)
    return res


def check_fertig(app: FakeApp, run: int, start: int = 0) -> None:
    app.wait_for(lambda h: h["type"] in ("CHECK", "WIE_ZUVOR") and h.get("art", "CHECK") == "CHECK"
                 and (h.get("run") == run or any(p == ["run"] and v == run for p, v in h.get("setzen", []))),
                 30, start)


def rahmen(app: FakeApp, start: int) -> list[tuple[dict, bytes]]:
    with app.cond:
        return [(h, p) for _, h, p in app.frames[start:]]


def test_ohne_faehigkeit_alles_wie_bisher(env):
    app = verbinden(env, faehigkeiten=None)
    hello = next(h for _, h, _ in app.frames if h["type"] == "HELLO")
    assert hello["faehigkeiten"] == ALLE
    projekt(env)
    lauf(env)
    m = app.mark()
    r2 = lauf(env)
    r3 = lauf(env, params={"b": 25})
    time.sleep(0.5)
    frames = rahmen(app, m)
    typen = [h["type"] for h, _ in frames]
    assert typen.count("PART_UPSERT") == 4, typen
    assert not set(typen) & NEU, set(typen) & NEU
    for h, _ in frames:
        assert "inhalt" not in h and "delta" not in h, h["type"]
        if h["type"] == "RUN_END":
            assert "teile" not in h
        if h["type"] == "VERSION_BILD_REQ":
            assert all("inhalt" not in k and "aus_szene" not in k for k in h["teile"])
        if h["type"] == "VIEW_CMD":
            assert h["args"].get("art") != "param", "ältere App: kein Live-Maß"
    assert {"CHECK", "BOM", "CONSTRAINTS", "RUN_END"} <= set(typen)
    assert r3["run"] == r2["run"] + 1


def test_delta_unveraenderter_lauf(env):
    rt = env["rt"]
    app = verbinden(env)
    projekt(env)
    r1 = lauf(env)
    check_fertig(app, r1["run"])
    m = app.mark()
    r2 = lauf(env)
    check_fertig(app, r2["run"], m)
    time.sleep(0.5)
    frames = rahmen(app, m)
    typen = [h["type"] for h, _ in frames]
    assert "PART_UPSERT" not in typen, typen
    same = [h for h, _ in frames if h["type"] == "PART_SAME"]
    assert [h["name"] for h in same] == ["Platte", "Stift"] and all(h["run"] == r2["run"] for h in same)
    start = next(h for h, _ in frames if h["type"] == "RUN_START")
    ende = next(h for h, _ in frames if h["type"] == "RUN_END")
    assert start["delta"] is True and ende["teile"] == ["Platte", "Stift"]
    assert "WIE_ZUVOR" in typen
    assert "STATICS_FIELD" not in typen and "ANIM_DEF" not in typen
    # die App kann alles aufbauen und hat danach denselben Stand wie der Kernel
    sicht = AppSicht()
    with app.cond:
        alle = [(h, p) for _, h, p in app.frames]
    for h, p in alle:
        sicht.verarbeite(h, p)
    assert not sicht.anfragen
    assert sicht.reihenfolge == ["Platte", "Stift"]
    assert {n: i for n, (i, _) in sicht.teile.items()} == {r.name: r.header["inhalt"] for r in rt.scene.records()}
    assert all(run == r2["run"] for _, run in sicht.teile.values())
    bom = {k: v for k, v in sicht.letzte["BOM"].items() if k not in ("type", "seq")}
    assert kanonisch(bom) == kanonisch(rt._bom) and bom["run"] == r2["run"]
    check, _ = rt._pruef.letztes()
    assert kanonisch({k: v for k, v in sicht.letzte["CHECK"].items() if k != "seq"}) == \
        kanonisch({k: v for k, v in check.items() if k != "seq"})
    groesse = sum(len(encode_frame(h, p)) for h, p in frames)
    assert groesse < 20_000, f"{groesse} Byte für einen unveränderten Lauf"


def test_delta_geaenderte_und_entfernte_teile_und_live_mass(env):
    rt = env["rt"]
    app = verbinden(env)
    projekt(env)
    lauf(env)
    m = app.mark()
    r = lauf(env, params={"b": 25})
    time.sleep(0.3)
    frames = rahmen(app, m)
    teile = [(h["type"], h["name"]) for h, _ in frames if h["type"] in ("PART_UPSERT", "PART_SAME")]
    assert teile == [("PART_UPSERT", "Platte"), ("PART_SAME", "Stift")]
    view = [h for h, _ in frames if h["type"] == "VIEW_CMD"]
    marke = next(h for h in view if h["cmd"] == "annotate" and h["args"].get("art") == "param")
    assert marke["args"]["text"] == "b 20 → 25 mm" and marke["args"]["dauer_s"] == 4.0
    hervor = next(h for h in view if h["cmd"] == "highlight")
    assert hervor["args"]["refs"] == ["Platte"] and hervor["args"]["id"] == marke["args"]["id"]
    assert hervor["args"]["dauer_s"] == 4.0 and hervor["args"]["clear"] is False
    punkt = marke["args"]["points"][0]
    platte = rt.scene.get("Platte").bbox
    assert punkt[2] > platte["max"][2] and platte["min"][0] < punkt[0] < platte["max"][0], "über dem Teil"
    # Teil entfernt
    assert rt.model_write(CODE.replace('show(Pos(30, 0, 0) * Cylinder(3, 8), "Stift")\n', ""))["ok"]
    m = app.mark()
    r2 = lauf(env)
    frames = rahmen(app, m)
    assert ("PART_REMOVE", "Stift") in [(h["type"], h.get("name")) for h, _ in frames]
    ende = next(h for h, _ in frames if h["type"] == "RUN_END")
    assert ende["teile"] == ["Platte"] and r2["run"] == r["run"] + 1


def test_parts_req_und_nochmal(env):
    app = verbinden(env)
    projekt(env)
    lauf(env)
    m = app.mark()
    app.send({"type": "PARTS_REQ", "teile": ["Platte", "Gibts/nicht"]})
    _, _, h, p = app.wait_for(lambda h: h["type"] == "PART_UPSERT" and h["name"] == "Platte", 10, m)
    assert len(p) > 0 and h["inhalt"]
    app.wait_for(lambda h: h["type"] == "PART_REMOVE" and h["name"] == "Gibts/nicht", 10, m)
    m = app.mark()
    app.send({"type": "NOCHMAL", "art": "BOM"})
    _, _, h, _ = app.wait_for(lambda h: h["type"] in ("BOM", "WIE_ZUVOR"), 10, m)
    assert h["type"] == "BOM", "NOCHMAL: vollständig"


def test_katalog_mit_stand(env):
    app = verbinden(env)
    m = app.mark()
    app.send({"type": "CATALOG_REQ", "id": "a-1", "query": None, "art": None})
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "CATALOG" and h.get("reply_to") == "a-1", 10, m)
    assert "items" in h and h["stand"] and not h.get("unveraendert")
    voll = len(json.dumps(h))
    m = app.mark()
    app.send({"type": "CATALOG_REQ", "id": "a-2", "query": None, "art": None, "stand": h["stand"]})
    _, _, k, _ = app.wait_for(lambda h: h["type"] == "CATALOG" and h.get("reply_to") == "a-2", 10, m)
    assert k["unveraendert"] is True and k["stand"] == h["stand"] and "items" not in k
    assert len(json.dumps(k)) < voll
    m = app.mark()
    app.send({"type": "CATALOG_REQ", "id": "a-3", "query": None, "art": None, "stand": "veraltet"})
    _, _, k, _ = app.wait_for(lambda h: h["type"] == "CATALOG" and h.get("reply_to") == "a-3", 10, m)
    assert "items" in k and not k.get("unveraendert")


def test_in_arbeit(env):
    app = verbinden(env)
    projekt(env, CODE_LANGSAM)
    lauf(env)
    m = app.mark()
    r = lauf(env)
    frames = [h for h, _ in rahmen(app, m)]
    arbeit = [h for h in frames if h["type"] == "IN_ARBEIT"]
    stift = [h for h in arbeit if h["teil"] == "Stift"]
    assert stift and stift[0]["nach"] == "Platte" and stift[0]["run"] == r["run"], arbeit
    folge = [(h["type"], h.get("name") or h.get("teil")) for h in frames
             if h["type"] in ("PART_SAME", "PART_UPSERT", "IN_ARBEIT")]
    i = folge.index(("IN_ARBEIT", "Stift"))
    assert ("PART_SAME", "Platte") in folge[:i] and ("PART_SAME", "Stift") in folge[i:]
    assert len(stift) == 1, "nur einmal je erwartetem Teil"
    # ältere App: kein IN_ARBEIT
    app = verbinden(env, faehigkeiten=["delta-1"])
    m = app.mark()
    lauf(env)
    assert not [h for h, _ in rahmen(app, m) if h["type"] == "IN_ARBEIT"]


def test_versionsbild_aus_der_szene(env):
    app = verbinden(env)
    projekt(env)
    m = app.mark()
    lauf(env)
    _, _, h, p = app.wait_for(lambda h: h["type"] == "VERSION_BILD_REQ", 30, m)
    assert h["teile"] and all(k.get("aus_szene") for k in h["teile"]) and p == b""
    assert {k["teil"] for k in h["teile"]} == {"Platte", "Stift"}
    # ältere App: Netze wie bisher
    app = verbinden(env, faehigkeiten=None)
    m = app.mark()
    assert env["rt"].model_write(CODE.replace("20)", "21)"))["ok"]
    lauf(env)
    _, _, h, p = app.wait_for(lambda h: h["type"] == "VERSION_BILD_REQ", 30, m)
    assert all("vert" in k and "inhalt" not in k for k in h["teile"]) and len(p) > 0


def test_dauer_s_bei_aelteren_apps(env):
    rt = env["rt"]
    app = verbinden(env, faehigkeiten=None)
    m = app.mark()
    res = rt.view_command("annotate", {"kind": "label", "points": [[0, 0, 0]], "text": "2 cm vom Rand",
                                       "dauer_s": 0.3})
    assert res["ok"]
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "annotate", 5, m)
    aid = h["args"]["id"]
    app.wait_for(lambda h: h["type"] == "VIEW_CMD" and h["cmd"] == "clear_annotations"
                 and h["args"]["ids"] == [aid], 5, m)
    app = verbinden(env)
    m = app.mark()
    assert rt.view_command("annotate", {"kind": "label", "points": [[0, 0, 0]], "text": "x", "dauer_s": 0.2})["ok"]
    time.sleep(0.6)
    assert not [h for h, _ in rahmen(app, m) if h["type"] == "VIEW_CMD" and h["cmd"] == "clear_annotations"]


def test_lagebild(env):
    rt = env["rt"]
    verbinden(env, lage=LAGE)
    t0 = time.perf_counter()
    res = rt.lagebild()
    assert res["ok"] and res["quelle"] == "app" and res["kamera"] == LAGE["kamera"]
    assert res["maus"]["teil"] == "Stift" and res["auswahl"]["refs"] == ["Platte#f0"]
    assert time.perf_counter() - t0 < 0.2 and res["antwort_ms"] < 200
    # Antwort zu spät: der Kernel liefert nach 0,2 s, was er weiß, und merkt sich die späte Antwort
    spaet = {**LAGE, "kamera": {**LAGE["kamera"], "abstand": 999.0}}
    verbinden(env, lage=spaet, lage_verzoegerung_s=0.5)
    t0 = time.perf_counter()
    res = rt.lagebild()
    dauer = time.perf_counter() - t0
    assert res["quelle"] == "kernel" and "keine Antwort" in res["grund"] and 0.15 < dauer < 0.45, (res, dauer)
    assert "auswahl" in res and res["sichtbar"] is None
    time.sleep(0.6)
    res = rt.lagebild(0.05)
    assert res["quelle"] == "kernel" and res["kamera"]["abstand"] == 999.0 and res["kamera_alter_s"] is not None
    # App ohne lage-1: sofort, ohne zu warten
    verbinden(env, faehigkeiten=["delta-1"])
    t0 = time.perf_counter()
    res = rt.lagebild()
    assert res["quelle"] == "kernel" and "lage-1" in res["grund"] and time.perf_counter() - t0 < 0.05


def test_agentenspur_dienst(env):
    rt = env["rt"]
    rt.agent_schritt({"id": "t-1", "werkzeug": "status", "stand": "ok", "beginn": time.time()})
    app = verbinden(env)
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "AGENT_SPUR", 5)
    assert "t-1" in [s["id"] for s in h["schritte"]]
    m = app.mark()
    rt.agent_schritt({"id": "t-2", "werkzeug": "run", "absicht": "Breite testen", "sitzung": "abc",
                      "beginn": time.time(), "stand": "laeuft"})
    rt.agent_schritt({"id": "t-2", "text": "führt model.py aus"})
    rt.agent_schritt({"id": "t-2", "stand": "ok", "ende": time.time() + 0.25})
    _, _, h, _ = app.wait_for(lambda h: h["type"] == "AGENT_SCHRITT" and h["schritt"]["stand"] == "ok", 5, m)
    s = h["schritt"]
    assert s["text"] == "führt model.py aus" and s["absicht"] == "Breite testen" and s["dauer_ms"] >= 200
    assert rt.agentenspur()[-1]["id"] == "t-2"
    app = verbinden(env, faehigkeiten=["delta-1"])
    m = app.mark()
    rt.agent_schritt({"id": "t-3", "werkzeug": "status", "stand": "ok"})
    time.sleep(0.2)
    assert not [h for h, _ in rahmen(app, m) if h["type"].startswith("AGENT_S")]


async def _werkzeug(url: str, sitzung: str, name: str, args: dict):
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    http = create_mcp_http_client(headers={"x-claude-code-session-id": sitzung})
    async with http:
        async with Client(streamable_http_client(url, http_client=http), mode="legacy", cache=None) as c:
            return await c.call_tool(name, args)


def test_agentenspur_ueber_mcp(env):
    from kevcad_kernel.server import KevcadHTTPServer

    rt = env["rt"]
    app = verbinden(env)
    projekt(env)
    server = KevcadHTTPServer(rt, 0).start_in_thread()
    try:
        m = app.mark()
        res = anyio.run(_werkzeug, server.url, "sitzung-a", "status", {"absicht": "Stand ansehen"})
        assert not res.is_error, "absicht nimmt jedes Werkzeug an"
        res = anyio.run(_werkzeug, server.url, "sitzung-a", "measure", {"refs": ["Gibts/nicht"]})
        assert res.is_error
        lauf_res = anyio.run(_werkzeug, server.url, "sitzung-a", "run", {"absicht": "einmal rechnen"})
        ende = time.monotonic() + 10
        while time.monotonic() < ende:
            spur = {s["werkzeug"]: s for s in rt.agentenspur()[-3:]}
            if all(spur.get(w, {}).get("stand") in ("ok", "fehler") for w in ("status", "measure", "run")) \
                    and "phasen" in spur.get("run", {}):
                break
            time.sleep(0.05)
        assert spur["status"]["stand"] == "ok" and spur["status"]["absicht"] == "Stand ansehen"
        assert spur["status"]["sitzung"] == "sitzung-a" and spur["status"]["text"] == "schaut auf den Stand"
        assert spur["measure"]["stand"] == "fehler" and "Gibts/nicht" in spur["measure"]["fehler"]
        assert spur["run"]["phasen"]["run"] >= 1 and spur["run"]["absicht"] == "einmal rechnen"
        assert spur["run"]["dauer_ms"] > 0 and spur["run"]["text"]
        # run meldet Befunde der Prüfung als Fehler (das Testmodell schwebt): die Spur spiegelt das Ergebnis
        assert spur["run"]["stand"] == ("fehler" if lauf_res.is_error else "ok")
        schritte = [h["schritt"] for h, _ in rahmen(app, m) if h["type"] == "AGENT_SCHRITT"]
        status = [s for s in schritte if s["werkzeug"] == "status"]
        assert [s["stand"] for s in status][0] == "laeuft" and status[-1]["stand"] == "ok"
    finally:
        server.stop_thread()
