"""Geometrie-Helfer des Bewegungsraums (B2, B3, PLAN-PRUEFUNG-INKREMENTELL.md): Die Wege, die eigene Prozesse rechnen,
kommen genauso heraus wie selbst gerechnet; stirbt ein Helfer, rechnet der Rechenprozess selbst."""

from __future__ import annotations

from typing import Any

import pytest
from build123d import Pos
from kevcad.bedingungen import bezug, drehgelenk
from test_nachbesserung import _fluegel_formen, _klappen_modell

from kevcad_kernel.bedingungen import bewegungsraum as br
from kevcad_kernel.bedingungen import helfer, pruefen, sammeln

FLUECHTIG = ("geprueft_ms", "zwischenspeicher")


def _leeren() -> None:
    for c in (br._CACHE, br._PAAR_CACHE, br._GRIFF_CACHE, br._GEWINDE_CACHE, br._REL_CACHE):
        c.clear()


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setenv(helfer.HELFER_ENV, "2")
    yield helfer.pool()
    if helfer._POOL is not None:
        helfer._POOL.beenden()
        helfer._POOL = None


def _modell() -> tuple[Any, dict, dict]:
    """Klappe und Klotz (Kollisionen) und daneben eine Flügelmutter an einer Wand (Griffraum)."""
    formen = _klappen_modell()
    for n, f in _fluegel_formen(wand=True).items():
        formen[f"F/{n}"] = Pos(0, 200, 0) * f
    with sammeln() as s:
        drehgelenk(bezug(formen["Klappe"], "bohrung"), bezug(formen["Lager"], "achse"), bereich=(-60, 90),
                   schritte=30)
        drehgelenk(bezug(formen["Klotz"], "achse_z"), bezug(formen["Achse 2"], "achse"), bereich=(0, 90), schritte=9)
        drehgelenk(bezug(formen["F/Mutter"], "achse"), bezug(formen["F/Stift"], "achse"), bereich=(0, 180),
                   schritte=12, bedienung="fluegel")
        pruefen(s, formen, bewegungsraum=False)
    return s, formen, {n: f"h-{n}" for n in formen}


def _ohne(xs: list[dict]) -> list[dict]:
    return [{k: v for k, v in x.items() if k not in FLUECHTIG} for x in xs]


def _selbst(s: Any, formen: dict, sk: dict) -> tuple[list, list]:
    _leeren()
    return br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, zeitlimit_s=None)


def test_helfer_rechnen_wie_der_rechenprozess(pool):
    s, formen, sk = _modell()
    erg_l, bef_l = _selbst(s, formen, sk)
    assert any(e["kollisionen"] for e in erg_l) and any(e["eng"] for e in erg_l)
    _leeren()
    v = br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None)
    assert v is not None and sorted(v.daten) == [0, 1, 2]
    assert set(v.auftrag.verteilung.values()) == {0, 1}  # auf beide Helfer verteilt
    erg_h, bef_h = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None,
                                         zeitlimit_s=None, vorlauf=v)
    assert _ohne(erg_h) == _ohne(erg_l) and bef_h == bef_l
    assert len(br._PAAR_CACHE) == 0  # gerechnet haben die Helfer
    # das Ergebnis ist hier gemerkt: derselbe Stand gibt nichts mehr an die Helfer
    assert br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None) is None
    erg2, _ = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, zeitlimit_s=None)
    assert all(e["zwischenspeicher"] for e in erg2) and _ohne(erg2) == _ohne(erg_l)


def test_helfer_tot_dann_selbst_gerechnet(pool):
    s, formen, sk = _modell()
    erg_l, bef_l = _selbst(s, formen, sk)
    _leeren()
    v = br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None)
    assert v is not None
    for h in pool.helfer.values():
        h.proc.kill()
    erg_h, bef_h = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None,
                                         zeitlimit_s=None, vorlauf=v)
    assert _ohne(erg_h) == _ohne(erg_l) and bef_h == bef_l
    # der nächste Auftrag startet neue Helfer
    _leeren()
    v2 = br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None)
    assert v2 is not None and all(h.lebt() for h in pool.helfer.values())
    erg3, _ = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, zeitlimit_s=None,
                                    vorlauf=v2)
    assert _ohne(erg3) == _ohne(erg_l)


def test_neuer_auftrag_ueberholt_den_alten(pool):
    s, formen, sk = _modell()
    erg_l, _ = _selbst(s, formen, sk)
    _leeren()
    v1 = br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None)
    v2 = br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None)
    assert v1 is not None and v2 is not None and pool.aktiv is v2.auftrag
    # der alte Vorlauf bekommt nichts mehr und rechnet selbst; der neue kommt von den Helfern
    erg1, _ = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, zeitlimit_s=None,
                                    vorlauf=v1)
    assert _ohne(erg1) == _ohne(erg_l)
    _leeren()
    erg2, _ = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, zeitlimit_s=None,
                                    vorlauf=v2)
    assert _ohne(erg2) == _ohne(erg_l)


def test_helfer_aus_und_kleines_modell(monkeypatch):
    s, formen, sk = _modell()
    monkeypatch.setenv(helfer.HELFER_ENV, "0")
    assert br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None) is None
    monkeypatch.delenv(helfer.HELFER_ENV)
    _leeren()
    # ohne Vorgabe: kleines Modell (unter 40 Teilen, Bewegungsraum zuletzt schnell) rechnet selbst
    assert br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None) is None


def test_verteilen_bleibt_beim_alten_helfer():
    p = helfer.Pool()
    p.dauer_ms = {"a": 1500, "b": 500, "c": 500, "d": 500}
    p.zuordnung = {"a": 2, "b": 0, "c": 0}
    v = p.verteilen([(0, "a"), (1, "b"), (2, "c"), (3, "d")], 3)
    assert v[0] == 2 and v[1] == 0  # beim alten Helfer
    assert v[2] == 1  # c: Helfer 0 hätte 1000 statt 0 ms, mehr als eine halbe Wegdauer
    assert v[3] in (0, 1)


def test_nur_bereite_helfer_bekommen_arbeit():
    """Ein frisch gestarteter Helfer lädt rund 3 s; solange es bereite gibt, rechnen nur sie."""

    class Attrappe:
        def __init__(self, nr: int, bereit: bool) -> None:
            self.nr, self.bereit = nr, bereit

        def lebt(self) -> bool:
            return True

    p = helfer.Pool()
    p.helfer = {0: Attrappe(0, True), 1: Attrappe(1, False), 2: Attrappe(2, True)}
    assert [h.nr for h in p._helfer_bereit(3)] == [0, 2]
    p.helfer = {0: Attrappe(0, False), 1: Attrappe(1, False)}
    assert [h.nr for h in p._helfer_bereit(2)] == [0, 1]  # noch keiner bereit (erster Auftrag): alle


@pytest.mark.parametrize("helfer_zahl", ["2"])
def test_laufzeit_mit_helfern_gleich_wie_ohne(tmp_path, monkeypatch, helfer_zahl):
    """Über die echte Laufzeit: Der Rechenprozess startet die Helfer selbst; Endstand mit Helfern gleich wie ohne."""
    import shutil
    import tempfile
    from pathlib import Path

    from app_testutil import make_runtime
    from test_prueftempo import KLAPPE_FEHLER

    def endstand(zahl: str) -> list[dict]:
        monkeypatch.setenv(helfer.HELFER_ENV, zahl)
        monkeypatch.setenv("KEVCAD_BEWEGUNGSRAUM_ZEITLIMIT_S", "0")  # sonst rechnet der kleine Fall vorne selbst
        monkeypatch.setenv("KEVCAD_PRUEF_STUFEN", "1")  # der Vorlauf läuft nur mit Stufen (conftest schaltet sie ab)
        tmp = Path(tempfile.mkdtemp(prefix="kcgh", dir=tempfile.gettempdir()))
        rt = make_runtime(str(tmp / "k.sock"))
        try:
            assert rt.wait_worker_ready(240)
            assert rt.project_new(str(tmp / "Klappe"), "empty")["ok"]
            assert rt.model_write(KLAPPE_FEHLER)["ok"]
            assert rt.set_inventory_rule(False)["ok"]
            assert rt.run()["ok"]
            out = rt.pruefen(60, endstand=True)
            assert out["state"] == "done"
            if zahl != "0":  # die Helfer laufen als Kinder des Rechenprozesses
                import psutil

                kinder = psutil.Process(int(rt._worker.info["pid"])).children()
                assert sum("multiprocessing" in " ".join(k.cmdline()) for k in kinder) == int(zahl)
            return [b for b in out["befunde"] if b["art"] == "bewegungsraum"]
        finally:
            rt.close()
            shutil.rmtree(tmp, ignore_errors=True)

    mit = endstand(helfer_zahl)
    assert mit and mit[0]["schwere"] == "fehler" and mit[0]["teile"] == ["Klappe", "Rahmen"]
    assert endstand("0") == mit


def test_leerlauf_beendet_die_helfer_und_der_naechste_lauf_weckt_sie(pool, monkeypatch):
    """Nach der Leerlauffrist ohne Auftrag beendet der Rechenprozess die Helfer (Speicher); ``aufwecken`` (Beginn des
    nächsten Laufs) startet sie wieder, und sie rechnen wie vorher."""
    import time

    monkeypatch.setenv(helfer.LEERLAUF_ENV, "1")
    s, formen, sk = _modell()
    erg_l, _ = _selbst(s, formen, sk)
    _leeren()
    v = br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None)
    erg, _ = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, zeitlimit_s=None,
                                   vorlauf=v)
    assert _ohne(erg) == _ohne(erg_l)
    prozesse = [h.proc for h in pool.helfer.values()]
    ende = time.monotonic() + 10
    while pool.helfer and time.monotonic() < ende:
        time.sleep(0.1)
    assert not pool.helfer and pool.schlafend == 2
    for p in prozesse:
        p.join(5)
        assert not p.is_alive()
    helfer.aufwecken()
    assert len(pool.helfer) == 2 and all(h.lebt() for h in pool.helfer.values())
    _leeren()
    v2 = br.vorlauf(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, boxen=None)
    erg2, _ = br.bewegungen_pruefen(s, dict(s.aufgeloest), formen, schluessel=sk, projekt=None, zeitlimit_s=None,
                                    vorlauf=v2)
    assert _ohne(erg2) == _ohne(erg_l)
    helfer.aufwecken()  # laufen schon: nichts passiert
    assert len(pool.helfer) == 2


def test_leerlauf_wartet_auf_einen_laufenden_auftrag(monkeypatch):
    monkeypatch.setenv(helfer.LEERLAUF_ENV, "600")

    class Attrappe:
        nr, bereit = 0, True

        def lebt(self) -> bool:
            return True

        def beenden(self) -> None:
            self.beendet = True

    p = helfer.Pool()
    h = Attrappe()
    p.helfer = {0: h}
    assert not p.leerlauf_pruefen(p.zuletzt + 599)  # Frist nicht um
    p.aktiv = helfer.Auftrag(p, 1, {0: 0, 1: 0})
    p.aktiv.da[0] = {}
    assert not p.leerlauf_pruefen(p.zuletzt + 601)  # Weg 1 rechnet noch
    p.aktiv.da[1] = {}
    assert p.leerlauf_pruefen(p.zuletzt + 601) and getattr(h, "beendet", False)
    assert not p.helfer and p.schlafend == 1 and p.aktiv is None
