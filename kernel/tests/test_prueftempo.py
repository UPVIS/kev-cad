"""Prüftempo (22.10.2026): Hüllquader-Speicher während model.py, Bewegungsraum im Hintergrund fertig rechnen
(CHECK „teilweise“ → „done“ mit demselben Lauf), pruefen(warten=True), run(timeout_s=…) über MCP.

Gleichheit ist der Maßstab: schneller darf es werden, die Befunde und die Werte in model.py bleiben dieselben."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import anyio
import pytest
from app_testutil import FakeApp, make_runtime
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.runner import Runner

# ---------------------------------------------------------------------------------------------------------------------
# Hüllquader-Speicher


def _bb(shape) -> tuple:
    b = shape.bounding_box()
    return (b.min.X, b.min.Y, b.min.Z, b.max.X, b.max.Y, b.max.Z, b.size.X, b.size.Y, b.size.Z, b.wrapped is None)


def test_huellen_gleiche_werte_und_netz_entfernt():
    from build123d import Box, Cylinder, Pos, Rot, Sphere, Torus
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopLoc import TopLoc_Location

    from kevcad_kernel import huellen

    formen = [Box(10, 20, 30) + Cylinder(5, 50), Torus(40, 8), Rot(13, 27, 41) * (Torus(30, 5) + Sphere(12))]
    lagen = [(0, 0, 0), (1.25, -3.5, 7.125), (100.3, 0, -2)]
    stuecke = [Pos(*v) * f for f in formen for v in lagen]
    ohne = [_bb(s) for s in stuecke]
    with huellen.zwischenspeicher():
        mit = [[_bb(s) for s in stuecke] for _ in range(3)]
        assert huellen.statistik["neu"] == len(stuecke) and huellen.statistik["treffer"] == 2 * len(stuecke)
        # wie build123d: ein Netz an der Form wird auch beim Treffer entfernt
        s = stuecke[0]
        BRepMesh_IncrementalMesh(s.wrapped, 0.1)
        face = s.faces()[0].wrapped
        assert BRep_Tool.Triangulation_s(face, TopLoc_Location()) is not None
        s.bounding_box()
        assert BRep_Tool.Triangulation_s(face, TopLoc_Location()) is None
    assert all(m == ohne for m in mit)
    from build123d import Shape

    assert Shape.bounding_box is huellen._original  # nach dem Lauf wieder aus
    assert huellen._speicher is None


AUSBAU = """from build123d import *
from kevcad import show, step
import math

step("Teile")
platte = Box(200, 100, 10)
stift = Pos(20, 0, 20) * Cylinder(4, 30)
deckel = Pos(0, 0, 60) * Box(60, 60, 4)
show(platte, "Platte"); show(stift, "Stift"); show(deckel, "Deckel")
step("Ausbauweg")
def ueberlappen(a, b):
    pa, pb = a.bounding_box(), b.bounding_box()
    return (pa.min.X < pb.max.X and pb.min.X < pa.max.X and pa.min.Y < pb.max.Y and pb.min.Y < pa.max.Y
            and pa.min.Z < pb.max.Z and pb.min.Z < pa.max.Z)
for name, teil, d in (("Stift", stift, (0, 0, 1)), ("Deckel", deckel, (1, 0, 0))):
    for i in range(1, 12):
        t = Pos(*(c * 6 * i for c in d)) * teil
        for h_name, h in (("Platte", platte), ("Deckel", deckel), ("Stift", stift)):
            if h_name == name:
                continue
            if ueberlappen(t, h):
                print(name, i, h_name, round((t & h).volume, 6), tuple(round(x, 9) for x in t.bounding_box().min))
print("Hülle", tuple(platte.bounding_box().max), tuple(deckel.bounding_box().size))
"""


def test_modell_mit_ausbauweg_gleich_mit_und_ohne_speicher(tmp_path, monkeypatch):
    from kevcad_kernel import huellen

    (tmp_path / "model.py").write_text(AUSBAU, encoding="utf-8")
    msg = {"run": 1, "path": str(tmp_path / "model.py"), "inventar_regel": False}
    mit = Runner(lambda h, p=b"": None).run(msg)
    treffer = huellen.statistik["treffer"]
    monkeypatch.setattr(huellen, "zwischenspeicher", contextlib.nullcontext)
    ohne = Runner(lambda h, p=b"": None).run(msg)
    assert mit["type"] == ohne["type"] == "RUN_DONE", (mit.get("error"), ohne.get("error"))
    assert "Stift" in mit["stdout"] and "Hülle" in mit["stdout"]
    assert mit["stdout"] == ohne["stdout"]
    assert treffer > 20  # die Hindernisse kamen aus dem Speicher


def test_kulisse_nur_nahe_teilkoerper_gleiches_ergebnis(monkeypatch):
    """Kulisse aus vielen Kacheln: die Paarprüfung nimmt nur die nahen Kacheln, das Ergebnis bleibt gleich."""
    import numpy as np
    from build123d import Box, Compound, Cylinder, Pos

    from kevcad_kernel.pruefung import kollision
    from kevcad_kernel.pruefung.koerper import koerper_aus_form

    kacheln = Compound(children=[Pos((i + 0.5) * 100, (j + 0.5) * 100, -1) * Box(100, 100, 2)
                                 for i in range(-3, 3) for j in range(-3, 3)])
    boden = koerper_aus_form("Kulisse/Boden", kacheln, {"kulisse": True})
    teile = [koerper_aus_form("steht", Pos(30, 30, 10) * Box(20, 20, 20)),  # liegt auf einer Kachel
             koerper_aus_form("steckt", Pos(0, 0, 9) * Cylinder(15, 20)),  # 1 mm im Boden, über vier Kacheln
             koerper_aus_form("knapp", Pos(-150, 120, 10.3) * Box(10, 10, 20)),  # 0,3 mm Luft (Spiel)
             koerper_aus_form("weit", Pos(250, -250, 50) * Box(10, 10, 10))]

    def werte(p):
        if p is None:
            return None
        return (p.abstand, round(p.volumen, 6), round(p.tiefe, 6), None if p.ort is None else tuple(np.round(p.ort, 6)))

    mit = [werte(kollision.pruefe_paar(t, boden, kollision.PaarCache())) for t in teile]
    monkeypatch.setattr(kollision, "_nahe_form", lambda k, anderer: k.shape)
    ohne = [werte(kollision.pruefe_paar(t, boden, kollision.PaarCache())) for t in teile]
    assert mit == ohne
    assert mit[0][0] == 0.0 and mit[1][1] > 0 and 0.2 < mit[2][0] < 0.4 and mit[3] is None


# ---------------------------------------------------------------------------------------------------------------------
# Bewegungsraum im Hintergrund fertig rechnen (Rechenprozess im selben Prozess)

KLAPPEN = """from build123d import *
from kevcad import show, param
import kevcad.bedingungen as bed

unten = (Align.CENTER, Align.CENTER, Align.MIN)
rahmen = Box(100, 20, 10, align=unten) + Pos(-30, 0, 40) * Box(4, 20, 20, align=unten)
achse = Pos(-50, 0, 15) * Rot(90, 0, 0) * Cylinder(3, 20)
klappe = Pos(-27, 0, 15) * Box(36, 18, 2) + Pos(-50, 0, 15) * Rot(90, 0, 0) * (Cylinder(5, 18) - Cylinder(3.2, 20))
klappe = bed.platziere(klappe, bed.drehgelenk((klappe, "bohrung"), (achse, "achse"), bereich=(-60, 90)))
achse2 = Pos(50, 0, 15) * Rot(90, 0, 0) * Cylinder(3, 20)
klappe2 = Pos(30, 0, 15) * Box(30, 18, 2) + Pos(50, 0, 15) * Rot(90, 0, 0) * (Cylinder(5, 18) - Cylinder(3.2, 20))
klappe2 = bed.platziere(klappe2, bed.drehgelenk((klappe2, "bohrung"), (achse2, "achse"), bereich=(0, 120)))
show(rahmen, "Rahmen")
show(achse, "Achse")
show(klappe, "Klappe")
show(achse2, "Achse 2")
show(klappe2, "Klappe 2")
"""


def _caches_leeren() -> None:
    from kevcad_kernel.bedingungen import bewegungsraum as bw

    bw._CACHE.clear()
    bw._PAAR_CACHE.clear()
    bw._GEWINDE_CACHE.clear()


def _schluessel(check: dict) -> list:
    return sorted((b["art"], b["schwere"], tuple(b["teile"]), b["text"]) for b in check.get("befunde") or [])


def _lauf(tmp_path: Path, runner: Runner, nr: int = 1, **params) -> dict:
    res = runner.run({"run": nr, "path": str(tmp_path / "model.py"), "params": params, "inventar_regel": False})
    assert res["type"] == "RUN_DONE", res.get("error")
    return res


def test_fertigrechnen_gleich_und_unterbrechbar(tmp_path, monkeypatch):
    from kevcad_kernel.bedingungen import anbindung
    from kevcad_kernel.pruefung.pruefer import Abgebrochen

    (tmp_path / "model.py").write_text(KLAPPEN, encoding="utf-8")
    # Bezug: ein Lauf mit Zeit genug, alles in einem Zug
    _caches_leeren()
    runner = Runner(lambda h, p=b"": None)
    _lauf(tmp_path, runner)
    voll, _ = runner.pruefe(1)
    assert voll["state"] == "done" and "im_hintergrund" not in voll
    weg = [b for b in voll["befunde"] if b["art"] == "bewegungsraum"]
    assert weg and any(b["schwere"] == "fehler" for b in weg), voll["befunde"]

    # ohne Zeit im Lauf: alles offen, teilweise; dann im Hintergrund fertig
    _caches_leeren()
    monkeypatch.setattr(anbindung, "ZEITLIMIT_S", 0.0)
    runner = Runner(lambda h, p=b"": None)
    _lauf(tmp_path, runner, 7)
    teil, nutz = runner.pruefe(7)
    assert teil["state"] == "teilweise", teil
    assert sorted(teil["im_hintergrund"]) == ["drehgelenk Klappe", "drehgelenk Klappe 2"]
    offen = [b for b in teil["befunde"] if b["art"] == "bewegungsraum"]
    assert offen and all(b["schwere"] == "hinweis" and "im Hintergrund fertig gerechnet" in b["text"] for b in offen)
    assert runner.fertig_rechnen(6) is None  # anderer Lauf: nichts offen

    # ein Auftrag geht vor: unterbrechen, dann fortsetzen
    aufrufe = {"n": 0}

    def einmal_unterbrechen() -> None:
        aufrufe["n"] += 1
        if aufrufe["n"] == 2:
            raise Abgebrochen("Auftrag geht vor")

    with pytest.raises(Abgebrochen):
        runner.fertig_rechnen(7, abbrechen=einmal_unterbrechen)
    assert runner._pruef_lauf.offen == 7
    fertig, f_nutz = runner.fertig_rechnen(7, abbrechen=einmal_unterbrechen)
    assert fertig["state"] == "done" and fertig["run"] == 7 and "im_hintergrund" not in fertig
    assert runner.fertig_rechnen(7) is None
    assert _schluessel(fertig) == _schluessel(voll)
    assert fertig["zusammenfassung"] == voll["zusammenfassung"] and fertig["zaehler"] == voll["zaehler"]
    assert "hintergrund" in fertig["statistik"]["zeiten_ms"]
    assert len(f_nutz) == len(nutz)  # Schnittkörper unverändert


def test_fertigrechnen_fehlgeschlagen_bleibt_teilweise(tmp_path, monkeypatch):
    from kevcad_kernel.bedingungen import anbindung
    from kevcad_kernel.pruefung.anbindung import PruefStand

    (tmp_path / "model.py").write_text(KLAPPEN, encoding="utf-8")
    _caches_leeren()
    monkeypatch.setattr(anbindung, "ZEITLIMIT_S", 0.0)
    runner = Runner(lambda h, p=b"": None)
    _lauf(tmp_path, runner, 3)
    teil, _ = runner.pruefe(3)

    def kaputt(abbrechen):
        raise RuntimeError("OCCT")

    runner._pruef_lauf._offen[3]["bewegungsraum"].rechne = kaputt
    kopf, _ = runner.fertig_rechnen(3)
    assert kopf["state"] == "teilweise" and kopf["im_hintergrund"] == [] and "fehlgeschlagen" in kopf["message"]
    assert runner.fertig_rechnen(3) is None
    st = PruefStand()
    st.erwarte(3)
    st.fertig({**teil, "type": "CHECK"}, b"")
    assert st.hintergrund == 3
    st.fertig({**kopf, "type": "CHECK"}, b"")
    assert st.hintergrund is None  # es kommt nichts mehr: wer wartet, bekommt das teilweise Ergebnis
    assert st.warte(3, 1.0, endstand=True)["state"] == "teilweise"


def test_neuer_lauf_verwirft_das_teilweise_ergebnis(tmp_path, monkeypatch):
    from kevcad_kernel.bedingungen import anbindung

    (tmp_path / "model.py").write_text(KLAPPEN, encoding="utf-8")
    _caches_leeren()
    monkeypatch.setattr(anbindung, "ZEITLIMIT_S", 0.0)
    runner = Runner(lambda h, p=b"": None)
    _lauf(tmp_path, runner, 1)
    assert runner.pruefe(1)[0]["state"] == "teilweise"
    _lauf(tmp_path, runner, 2)
    monkeypatch.setattr(anbindung, "ZEITLIMIT_S", 30.0)
    assert runner.pruefe(2)[0]["state"] == "done"
    assert runner.fertig_rechnen(1) is None


# ---------------------------------------------------------------------------------------------------------------------
# PruefStand der Laufzeit


def test_pruefstand_teilweise_und_endstand():
    from kevcad_kernel.pruefung.anbindung import PruefStand

    st = PruefStand()
    assert st.erwarte(5)
    st.fertig({"type": "CHECK", "run": 5, "state": "teilweise", "befunde": [], "im_hintergrund": ["drehgelenk A"]}, b"")
    assert st.hintergrund == 5 and st.erwartet is None
    assert st.warte(5, 0.1)["state"] == "teilweise"  # run wartet nicht auf den Hintergrund
    assert st.kurz()["hintergrund"] == 5
    t0 = time.monotonic()
    assert st.warte(5, 0.3, endstand=True)["state"] == "teilweise"  # Zeitlimit: das teilweise Ergebnis
    assert time.monotonic() - t0 >= 0.25

    def spaeter() -> None:
        time.sleep(0.2)
        st.fertig({"type": "CHECK", "run": 5, "state": "done", "befunde": [{"schwere": "fehler", "art": "x"}]}, b"x")

    threading.Thread(target=spaeter).start()
    out = st.warte(5, 5.0, endstand=True)
    assert out["state"] == "done" and st.hintergrund is None
    assert st.letztes()[1] == b"x"
    assert len(st.offen()[0]) == 1

    # neuer Lauf löst das Fertigrechnen ab: wer auf den Endstand wartet, bekommt das teilweise Ergebnis
    assert st.erwarte(6)
    st.fertig({"type": "CHECK", "run": 6, "state": "teilweise", "befunde": []}, b"")
    assert st.erwarte(7) and st.hintergrund is None
    assert st.warte(6, 1.0, endstand=True)["state"] == "teilweise"


# ---------------------------------------------------------------------------------------------------------------------
# Volle Laufzeit mit Rechenprozess und Test-App


KLAPPE_FEHLER = """from build123d import *
from kevcad import show, param
import kevcad.bedingungen as bed

unten = (Align.CENTER, Align.CENTER, Align.MIN)
rahmen = Box(100, 20, 10, align=unten) + Pos(-30, 0, 40) * Box(4, 20, 20, align=unten)
achse = Pos(-50, 0, 15) * Rot(90, 0, 0) * Cylinder(3, 20)
klappe = Pos(-27, 0, 15) * Box(36, 18, 2) + Pos(-50, 0, 15) * Rot(90, 0, 0) * (Cylinder(5, 18) - Cylinder(3.2, 20))
klappe = bed.platziere(klappe, bed.drehgelenk((klappe, "bohrung"), (achse, "achse"),
                                              bereich=(-60, param("bis", 90))))
show(rahmen, "Rahmen")
show(achse, "Achse")
show(klappe, "Klappe")
"""


@pytest.fixture(scope="module")
def laufzeit():
    tmp = Path(tempfile.mkdtemp(prefix="kcpt", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    alt = os.environ.get("KEVCAD_BEWEGUNGSRAUM_ZEITLIMIT_S")
    # alles im Hintergrund; der Rechenprozess erbt es beim Start (auch bei einem Neustart), deshalb bis zum Ende
    os.environ["KEVCAD_BEWEGUNGSRAUM_ZEITLIMIT_S"] = "0"
    rt = make_runtime(sock)
    assert rt.wait_worker_ready(240), "Rechenprozess nicht bereit"
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    assert rt.project_new(str(tmp / "Klappe"), "empty")["ok"]
    assert rt.model_write(KLAPPE_FEHLER)["ok"]
    assert rt.set_inventory_rule(False)["ok"]
    yield {"rt": rt, "app": app}
    app.close()
    rt.close()
    if alt is None:
        os.environ.pop("KEVCAD_BEWEGUNGSRAUM_ZEITLIMIT_S", None)
    else:
        os.environ["KEVCAD_BEWEGUNGSRAUM_ZEITLIMIT_S"] = alt
    shutil.rmtree(tmp, ignore_errors=True)


def _teilweise_dann_done(app: FakeApp, run: int, start: int) -> tuple[dict, dict]:
    """Die App bekommt für den Lauf erst CHECK teilweise, dann CHECK done (ohne neuen Lauf)."""
    _, t1, teil, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == run
                                  and h.get("state") == "teilweise", start=start)
    _, t2, done, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == run
                                  and h.get("state") == "done", start=start, timeout=60)
    assert t2 >= t1 and "im_hintergrund" not in done
    assert not [h for h in app.since(start) if h["type"] == "RUN_START" and h.get("run") != run]
    return teil, done


def test_hintergrund_mit_fakeapp_erst_teilweise_dann_done(laufzeit):
    from kevcad_kernel.mcp_tools.format import run_summary
    from kevcad_kernel.pruefung.anbindung import fuer_ergebnis

    rt, app = laufzeit["rt"], laufzeit["app"]
    start = app.mark()
    res = rt.run()
    assert res["ok"], res.get("error")
    # run wartet nicht auf den Hintergrund; ist der schneller als run, steht schon der Endstand da
    assert res["pruefung"]["state"] in ("teilweise", "done"), res["pruefung"]
    teil, done = _teilweise_dann_done(app, res["run"], start)
    assert teil["im_hintergrund"] == ["drehgelenk Klappe"]
    text, _, _ = run_summary({**res, "pruefung": fuer_ergebnis(teil)})  # so liest es der Agent bei teilweise
    assert "Bewegungsraum: 1 Gelenk noch nicht geprüft (Zeitlimit), wird im Hintergrund fertig gerechnet" in text
    assert "bedingungen() bzw. pruefen() zeigt den Endstand" in text
    assert not [b for b in teil["befunde"] if b["art"] == "bewegungsraum" and b["schwere"] != "hinweis"]
    weg = [b for b in done["befunde"] if b["art"] == "bewegungsraum"]
    assert weg and weg[0]["schwere"] == "fehler" and weg[0]["teile"] == ["Klappe", "Rahmen"]
    # pruefen(warten) liefert den Endstand, bedingungen() die Befunde des Bewegungsraums
    out = rt.pruefen(30, endstand=True)
    assert out["state"] == "done" and out["run"] == res["run"] and "hintergrund" not in out
    assert any(b["pruefung"] == "bewegungsraum" and b["schwere"] == "fehler" for b in rt.constraints()["befunde"])
    assert not rt.export(["stl"])["ok"]  # der Endstand sperrt den Export


def test_hintergrund_reglerwerte_speichern_nichts(laufzeit):
    rt, app = laufzeit["rt"], laufzeit["app"]
    assert rt.run()["ok"]
    rt.pruefen(30, endstand=True)
    vorher = rt.versionen()
    start = app.mark()
    res = rt.run(params={"bis": 30})
    assert res["ok"], res.get("error")
    _teilweise_dann_done(app, res["run"], start)
    out = rt.pruefen(30, endstand=True)
    assert out["state"] == "done" and out["run"] == res["run"]
    nachher = rt.versionen()
    if vorher.get("ok") and nachher.get("ok"):  # ein Lauf mit Reglerwerten legt keine Version an
        assert [v["nr"] for v in nachher.get("versionen") or []] == [v["nr"] for v in vorher.get("versionen") or []]


# ---------------------------------------------------------------------------------------------------------------------
# MCP: run(timeout_s=…), unbekannte Argumente, pruefen(warten=…)


@pytest.fixture
def srv():
    server, fake = start_server()
    yield server, fake
    server.stop_thread()


def _call(url: str, name: str, args: dict | None = None):
    return anyio.run(with_client, url, lambda c: c.call_tool(name, args or {}))


def test_run_timeout_s_ueber_mcp(srv):
    server, fake = srv
    res = _call(server.url, "run", {"timeout_s": 400})
    assert res.is_error is False
    assert fake.calls_of("run")[-1] == ((None, 0), {"timeout_s": 400.0})
    res = _call(server.url, "run", {"params": {"breite": 140}, "titel": "Breiter", "timeout_s": 900})
    assert fake.calls_of("run")[-1] == (({"breite": 140.0}, 0), {"titel": "Breiter", "timeout_s": 900.0})
    zu_lang = _call(server.url, "run", {"timeout_s": 5000})
    assert zu_lang.is_error and "timeout_s" in texts(zu_lang)[0]
    assert len(fake.calls_of("run")) == 2

    async def schema(c):
        return {t.name: t.input_schema for t in (await c.list_tools()).tools}

    s = anyio.run(with_client, server.url, schema)
    assert s["run"]["properties"]["timeout_s"]["anyOf"][0]["maximum"] == 900
    assert s["run"]["additionalProperties"] is False


def test_unbekannte_argumente_sind_ein_fehler(srv):
    server, fake = srv
    res = _call(server.url, "run", {"timeout": 400})
    assert res.is_error is True
    assert "timeout" in texts(res)[0] and "Extra inputs are not permitted" in texts(res)[0]
    assert fake.calls_of("run") == []
    res = _call(server.url, "parts", {"gibtsnicht": 1})
    assert res.is_error is True


def test_pruefen_wartet_auf_den_endstand(srv):
    server, fake = srv
    _call(server.url, "run")
    _call(server.url, "pruefen")
    assert fake.calls_of("pruefen")[-1][1] == {"endstand": True}
    _call(server.url, "pruefen", {"warten": False})
    assert fake.calls_of("pruefen")[-1][1] == {"endstand": False}


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeitgrenze an einer Kopie von Kevins Kugelschieber (nur lokal)

KUGELSCHIEBER = Path.home() / "Documents" / "Kev CAD" / "Kugelschieber Variante B"
EIGENER_KATALOG = Path.home() / "Library" / "Application Support" / "de.upvis.kevcad" / "katalog"


@pytest.mark.skipif(not (KUGELSCHIEBER / "model.py").is_file(), reason="Kevins Projekt fehlt (nur lokal)")
def test_kugelschieber_montagepruefung_laufzeit(tmp_path):
    from kevcad_kernel import huellen

    ziel = tmp_path / KUGELSCHIEBER.name

    def ignorieren(ordner: str, namen: list[str]) -> list[str]:
        aus = [n for n in namen if n in ("output", "versionen", "versions", "log", "git")]
        return aus + ([n for n in namen if n != "zukauf-status.json"] if Path(ordner).name == ".kevcad" else [])

    shutil.copytree(KUGELSCHIEBER, ziel, ignore=ignorieren)  # Kevins Projekt nur lesen
    katalog = tmp_path / "katalog"
    if EIGENER_KATALOG.is_dir():
        shutil.copytree(EIGENER_KATALOG, katalog)
    else:
        katalog.mkdir()
    runner = Runner(lambda h, p=b"": None)
    t0 = time.perf_counter()
    res = runner.run({"run": 1, "path": str(ziel / "model.py"), "params": {"montage_pruefen": 1},
                      "inventar_regel": True, "catalog": {"builtin": None, "own": str(katalog)}})
    lauf_s = time.perf_counter() - t0
    fehler = str((res.get("error") or {}).get("message") or "")
    if res["type"] != "RUN_DONE" and "wartet auf Kevins Freigabe" in fehler:
        pytest.skip("Kevins Projekt wartet gerade auf eine Freigabe im Lagerkatalog: " + fehler[:120])
    assert res["type"] == "RUN_DONE", res.get("error")
    # der Hüllquader-Speicher trägt: vorher 19.040 Rechnungen von AddOptimal in einem Lauf
    assert huellen.statistik["treffer"] > 5 * huellen.statistik["neu"], huellen.statistik
    t1 = time.perf_counter()
    check, _ = runner.pruefe(1)
    pruef_s = time.perf_counter() - t1
    assert check["state"] in ("done", "teilweise")
    if check["state"] == "teilweise":
        check = runner.fertig_rechnen(1)[0]
    assert check["state"] == "done"
    # vorher 113 s (Abbruch bei 120 s); Grenze mit Luft für einen ausgelasteten Rechner
    assert lauf_s + pruef_s < 90, (lauf_s, pruef_s)
