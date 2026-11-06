"""V2-1b „Tempo im Kernel nachziehen“, Prüfung nach dem Lauf. Gedächtnis der Statik (statik/merken.py): Treffer,
Fehltreffer bei jeder geänderten Eingabe, abgeschaltet, Fehler werden nicht gemerkt. Prüfung in Stufen: Zwischenstand,
gleicher Endstand, run sagt, was offen ist, pruefen wartet darauf."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from app_testutil import FakeApp, make_runtime
from test_statik import TISCH, laufe

from kevcad_kernel.catalog import builtin_dir
from kevcad_kernel.pruefung import lauf as pruef_lauf
from kevcad_kernel.runner import Runner
from kevcad_kernel.statik import merken


def _ohne_zeiten(wert):
    """Ergebnis ohne Rechenzeiten (sie gehören nicht zum Inhalt)."""
    if isinstance(wert, dict):
        return {k: _ohne_zeiten(v) for k, v in wert.items() if k not in ("ms", "zeiten_ms")}
    if isinstance(wert, list):
        return [_ohne_zeiten(v) for v in wert]
    return wert


class Lauf:
    """Ein Rechenprozess im Kleinen: ein Runner, mehrere Läufe."""

    def __init__(self, ordner: Path, code: str) -> None:
        self.ordner = ordner
        self.code = code
        (ordner / "kevcad.json").write_text(json.dumps({"version": 1, "inventar_regel": True}))
        (ordner / "model.py").write_text(code, encoding="utf-8")
        self.runner = Runner(lambda h, p=b"": None)
        self.run = 0

    def __call__(self, code: str | None = None, params: dict | None = None) -> dict:
        self.run += 1
        res = self.runner.run({"run": self.run, "path": str(self.ordner / "model.py"), "code": code or self.code,
                               "params": params or {}, "inventar_regel": True,
                               "catalog": {"builtin": str(builtin_dir()), "own": str(self.ordner / "eigen")}})
        assert res["type"] == "RUN_DONE", res.get("error")
        check, _ = self.runner.pruefe(self.run)
        assert check["state"] in ("done", "teilweise"), check
        return check


@pytest.fixture
def speicher(monkeypatch):
    monkeypatch.delenv("KEVCAD_GEDAECHTNIS", raising=False)
    merken.leeren()
    yield merken
    merken.leeren()


def test_treffer_liefert_dasselbe_ergebnis_und_stellt_das_modell_wieder_her(tmp_path, speicher):
    from kevcad_kernel.statik import anbindung

    lauf = Lauf(tmp_path, TISCH)
    erst = lauf()
    assert speicher.statistik["neu"] == 1 and speicher.statistik["treffer"] == 0
    federn = [a.feder for a in anbindung.LETZTER.modell.anschluesse]
    hinweise = list(anbindung.LETZTER.modell.hinweise)
    zweit = lauf()
    assert speicher.statistik["treffer"] == 1 and speicher.statistik["neu"] == 1
    assert _ohne_zeiten(zweit["statik"]) == _ohne_zeiten(erst["statik"])
    assert [b["text"] for b in zweit["befunde"]] == [b["text"] for b in erst["befunde"]]
    # was rechne_alles am Modell ändert, steht auch nach einem Treffer im Modell des Laufs
    assert [a.feder for a in anbindung.LETZTER.modell.anschluesse] == federn
    assert anbindung.LETZTER.modell.hinweise == hinweise
    assert all(a.feder is not None for a in anbindung.LETZTER.modell.anschluesse)


def test_gleicher_stand_trifft_auch_mit_anders_geteilten_objekten(speicher):
    """Ein gleicher Stand aus einem neuen Lauf hat dieselben Werte in neuen Objekten; pickle schreibt geteilte Objekte
    aber als Verweis. Darf nicht zum Fehltreffer werden."""
    text = "Teil " + str(1)
    a = _modell(kulisse={text}, rollend={text})  # dasselbe Objekt in zwei Feldern
    b = _modell(kulisse={"Teil " + str(1)}, rollend={"Teil " + str(1)})
    assert merken.fingerabdruck({}, [], Katalog(), {}, a) == merken.fingerabdruck({}, [], Katalog(), {}, b)


def test_treffer_ist_eine_eigene_kopie(tmp_path, speicher):
    lauf = Lauf(tmp_path, TISCH)
    vorlage = _ohne_zeiten(lauf()["statik"])
    a = lauf()["statik"]
    a["szenarien"][0]["name"] = "verändert"
    a["szenarien"].pop()
    a["aktiv"] = "verändert"
    b = lauf()["statik"]
    assert speicher.statistik["treffer"] == 2
    assert _ohne_zeiten(b) == vorlage


@pytest.mark.parametrize("alt, neu", [
    ("L, B, H = 800, 500, 700", "L, B, H = 800, 500, 720"),  # Geometrie
    ('st.last(["Tisch/Zarge vorn", "Tisch/Zarge hinten"], kg=20)',
     'st.last(["Tisch/Zarge vorn", "Tisch/Zarge hinten"], kg=25)'),  # Szenario
    ('st.szenario("Last 20 kg", beschreibung="20 kg auf den Längszargen")',
     'st.szenario("Last 20 kg", beschreibung="20 kg auf den Längszargen", ziel=3)'),  # Sicherheitsziel
    ('rohr = lager.teil("vierkantrohr-en10219-40x40x3")',
     'rohr = lager.teil("vierkantrohr-en10219-40x40x2")'),  # anderes Lagerteil
])
def test_fehltreffer_bei_geaenderter_eingabe(tmp_path, speicher, alt, neu):
    assert alt in TISCH
    lauf = Lauf(tmp_path, TISCH)
    erst = lauf()
    anders = lauf(TISCH.replace(alt, neu))
    assert speicher.statistik["neu"] == 2 and speicher.statistik["treffer"] == 0
    assert _ohne_zeiten(anders["statik"]) != _ohne_zeiten(erst["statik"])
    lauf(TISCH.replace(alt, neu))  # gleicher Stand wie eben: Treffer, der erste bleibt auch gemerkt
    lauf()
    assert speicher.statistik["treffer"] == 2


def test_fehltreffer_bei_geaendertem_katalog(tmp_path, speicher):
    """Eigener Katalog geändert: Die Statik rechnet mit dem neuen Stand (leichtere Lagerteile, Werkstoffe)."""
    lauf = Lauf(tmp_path, TISCH)
    lauf()
    eigen = tmp_path / "eigen"
    eigen.mkdir(exist_ok=True)
    (eigen / "neu.json").write_text(json.dumps({"format": 1, "materialien": [], "lagerteile": []}), encoding="utf-8")
    lauf()
    assert speicher.statistik["neu"] == 2 and speicher.statistik["treffer"] == 0


def test_abgeschaltet(tmp_path, speicher, monkeypatch):
    monkeypatch.setenv("KEVCAD_GEDAECHTNIS", "0")
    lauf = Lauf(tmp_path, TISCH)
    lauf(), lauf()  # (die Knicklast gerechnet streut etwas: ARPACK startet mit einem Zufallsvektor)
    assert speicher.statistik == {"treffer": 0, "neu": 0, "ohne_schluessel": 0, "nicht_gemerkt": 0}


# -- Grenzen, ohne Rechnung ---------------------------------------------------------------------------------------------


def _modell(**felder):
    from kevcad_kernel.statik.modell import Anschluss, StatikModell

    m = StatikModell(**felder)
    m.anschluesse = [Anschluss(stab="S", t=0.5, art="fest", partner=("boden",), teile=("S", "T"), quelle="Test")]
    return m


class Katalog:
    _sig = ("a", "b")


def Sz(name):  # noqa: N802 - steht für ein Szenario
    return SimpleNamespace(name=name)


def test_fehler_werden_nicht_gemerkt(speicher):
    m = _modell()
    n = [0]

    def rechnen():
        n[0] += 1
        return {"stand": "done", "szenarien": [{"text": "Rahmen: Schnitt nicht gerechnet (RuntimeError)"}]}

    for _ in range(2):
        speicher.gemerkt({}, [], Katalog(), {}, m, rechnen)
    assert n[0] == 2 and speicher.statistik["nicht_gemerkt"] == 2

    def ausnahme():
        raise RuntimeError("Absturz")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            speicher.gemerkt({}, [], Katalog(), {}, _modell(boden_z=1.0), ausnahme)
    assert speicher.statistik["neu"] == 0

    def nicht_fertig():
        n[0] += 1
        return {"stand": "failed", "meldung": "Kein Modell"}

    n[0] = 0
    for _ in range(2):
        speicher.gemerkt({}, [], Katalog(), {}, _modell(boden_z=2.0), nicht_fertig)
    assert n[0] == 2


def test_ohne_vollstaendigen_fingerabdruck_wird_gerechnet(speicher):
    class OhneSig:
        pass

    n = [0]

    def rechnen():
        n[0] += 1
        return {"stand": "done"}

    speicher.gemerkt({}, [], OhneSig(), {}, _modell(), rechnen)
    speicher.gemerkt({}, [], OhneSig(), {}, _modell(), rechnen)
    assert n[0] == 2 and speicher.statistik["ohne_schluessel"] == 2
    # Feld, das sich nicht serialisieren lässt (etwa eine Form oder ein Rückruf)
    m = _modell()
    m.hinweise.append(lambda: None)  # type: ignore[arg-type]
    speicher.gemerkt({}, [], Katalog(), {}, m, rechnen)
    speicher.gemerkt({}, [], Katalog(), {}, m, rechnen)
    assert n[0] == 4 and speicher.statistik["ohne_schluessel"] == 4


def test_fingerabdruck_kennt_jede_eingabe():
    m = _modell()
    basis = merken.fingerabdruck({}, [Sz("a")], Katalog(), {}, m)
    assert basis == merken.fingerabdruck({}, [Sz("a")], Katalog(), {}, _modell())
    assert basis != merken.fingerabdruck({}, [Sz("b")], Katalog(), {}, m)
    assert basis != merken.fingerabdruck({}, [Sz("a")], Katalog(), {}, _modell(boden_z=1.0))
    assert basis != merken.fingerabdruck({}, [Sz("a")], Katalog(), {}, _modell(untergrund="holz"))
    anders = _modell()
    anders.anschluesse[0].t = 0.6
    assert basis != merken.fingerabdruck({}, [Sz("a")], Katalog(), {}, anders)

    class AndererStand(Katalog):
        _sig = ("a", "c")

    assert basis != merken.fingerabdruck({}, [Sz("a")], AndererStand(), {}, m)
    # Rechenzeit gehört nicht dazu
    m.ms = 123.0
    assert basis == merken.fingerabdruck({}, [Sz("a")], Katalog(), {}, m)
    # Körper: Inhalt, Lage, Masse, Angaben
    k = type("K", (), dict(key="k", form="f", lage=np.eye(4), masse_g=1.0, volumen=2.0, info={"art": "rohr"}))()
    mit = merken.fingerabdruck({}, [Sz("a")], Katalog(), {"T": k}, m)
    assert mit != basis
    for feld, wert in (("key", "k2"), ("form", "f2"), ("lage", np.eye(4) * 2), ("masse_g", 3.0), ("volumen", 3.0),
                       ("info", {"art": "platte"})):
        k2 = copy.copy(k)
        setattr(k2, feld, wert)
        assert merken.fingerabdruck({}, [Sz("a")], Katalog(), {"T": k2}, m) != mit, feld
    # Modell je Szenario
    m2 = _modell(boden_z=5.0)
    assert merken.fingerabdruck({"a": m2}, [Sz("a")], Katalog(), {}, m) != basis


def test_speicher_begrenzt(speicher):
    for i in range(speicher.MAXIMUM + 3):
        speicher.gemerkt({}, [], Katalog(), {}, _modell(boden_z=float(i)), lambda: {"stand": "done"})
    assert len(speicher._speicher) == speicher.MAXIMUM
    assert laufe  # Helfer aus test_statik bleibt die gemeinsame Vorlage


# -- Prüfung in Stufen (pruefung/lauf.py) ---------------------------------------------------------------------------------


def _befunde(check: dict) -> list:
    return sorted((b["art"], b["schwere"], tuple(b["teile"]), b["text"]) for b in check.get("befunde") or [])


@pytest.fixture
def stufen(monkeypatch):
    """Stufen wie im Rechenprozess, auch für ein kleines Modell."""
    monkeypatch.setenv("KEVCAD_PRUEF_STUFEN", "1")
    monkeypatch.setattr(pruef_lauf, "KLEIN_TEILE", 1)


class Gestuft(Lauf):
    """Wie ``Lauf``, aber die Prüfung mit Zwischenstand; ``zwischen`` sammelt, was vorab hinausging."""

    def __call__(self, code: str | None = None, params: dict | None = None) -> dict:
        self.run += 1
        res = self.runner.run({"run": self.run, "path": str(self.ordner / "model.py"), "code": code or self.code,
                               "params": params or {}, "inventar_regel": True,
                               "catalog": {"builtin": str(builtin_dir()), "own": str(self.ordner / "eigen")}})
        assert res["type"] == "RUN_DONE", res.get("error")
        self.zwischen: list[dict] = []
        check, _ = self.runner.pruefe(self.run, zwischenstand=lambda kopf, nutz: self.zwischen.append(kopf))
        while check["state"] == "teilweise":
            fertig = self.runner.fertig_rechnen(self.run)
            if fertig is None:
                break
            check = fertig[0]
        return check


def test_zwischenstand_und_gleicher_endstand(tmp_path, stufen):
    """Der Zwischenstand kommt vor Montage und Statik, der Endstand ist derselbe wie am Stück."""
    bezug = Lauf(tmp_path, TISCH)()
    lauf = Gestuft(tmp_path, TISCH)
    end = lauf()
    assert len(lauf.zwischen) == 1
    z = lauf.zwischen[0]
    assert z["state"] == "teilweise" and z["im_hintergrund"] == ["Druck", "Montage", "Statik"], z.get("im_hintergrund")
    assert "montage" not in z and "statik" not in z and "druck" not in z and "stand" in z
    assert z["run"] == lauf.run and "seq" not in z
    assert end["state"] == "done" and "im_hintergrund" not in end
    assert _befunde(end) == _befunde(bezug)
    assert end["zusammenfassung"] == bezug["zusammenfassung"] and end["zaehler"] == bezug["zaehler"]
    assert end["montage"]["schritte"] == bezug["montage"]["schritte"]


def test_zwischenstand_nennt_den_bewegungsraum_nur_mit_wegen(tmp_path, stufen):
    from test_prueftempo import KLAPPEN

    (tmp_path / "model.py").write_text(KLAPPEN, encoding="utf-8")
    r = Runner(lambda h, p=b"": None)
    assert r.run({"run": 1, "path": str(tmp_path / "model.py"), "params": {}, "inventar_regel": False})["type"] == "RUN_DONE"
    zwischen: list[dict] = []
    r.pruefe(1, zwischenstand=lambda k, n: zwischen.append(k))
    assert zwischen and zwischen[0]["im_hintergrund"] == ["Druck", "Montage", "Statik", "Bewegungsraum"]


def test_unveraendert_kein_zwischenstand(tmp_path, stufen):
    lauf = Gestuft(tmp_path, TISCH)
    lauf()
    assert len(lauf.zwischen) == 1
    lauf()
    assert not lauf.zwischen  # alles aus dem Zwischenspeicher: ein CHECK reicht
    lauf(TISCH.replace("L, B, H = 800, 500, 700", "L, B, H = 800, 500, 720"))
    assert len(lauf.zwischen) == 1
    lauf()  # zurück auf einen schon geprüften Stand (Regler hin und her): wieder alles aus dem Zwischenspeicher
    assert not lauf.zwischen


def test_kleines_modell_ohne_zwischenstand(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_PRUEF_STUFEN", "1")
    monkeypatch.setattr(pruef_lauf, "KLEIN_S", 100.0)  # Uhr aus dem Spiel nehmen
    lauf = Gestuft(tmp_path, TISCH)
    assert lauf()["state"] == "done" and not lauf.zwischen


def test_ohne_schalter_keine_stufen(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_PRUEF_STUFEN", "0")
    monkeypatch.setattr(pruef_lauf, "KLEIN_TEILE", 1)
    lauf = Gestuft(tmp_path, TISCH)
    lauf()
    assert not lauf.zwischen


def test_neuer_auftrag_bricht_nach_dem_zwischenstand_ab(tmp_path, stufen):
    from kevcad_kernel.pruefung.pruefer import Abgebrochen

    lauf = Lauf(tmp_path, TISCH)
    r = lauf.runner
    res = r.run({"run": 1, "path": str(tmp_path / "model.py"), "code": TISCH, "params": {}, "inventar_regel": True,
                 "catalog": {"builtin": str(builtin_dir()), "own": str(tmp_path / "eigen")}})
    assert res["type"] == "RUN_DONE"
    zwischen = []

    def abbrechen() -> None:
        if zwischen:
            raise Abgebrochen("neuer Lauf")

    check, _ = r.pruefe(1, abbrechen=abbrechen, zwischenstand=lambda k, n: zwischen.append(k))
    assert zwischen and check["state"] == "cancelled"
    assert r.fertig_rechnen(1) is None  # nichts offen: Das teilweise Ergebnis bleibt das letzte


def test_abwarten_hilft_lesern_einer_spaeteren_pruefung():
    """Bauplan, Druckprüfung und statik() lesen, was erst nach dem Zwischenstand kommt: Sie warten darauf."""
    import threading

    from kevcad_kernel.pruefung.anbindung import PruefStand

    st = PruefStand()
    st.erwarte(7)
    st.fertig({"type": "CHECK", "run": 7, "state": "teilweise", "befunde": [],
               "im_hintergrund": ["Druck", "Statik"]}, b"")
    assert st.warte(7, 0.0)["state"] == "teilweise"  # run nimmt den Zwischenstand
    wartet = []

    def leser() -> None:
        st.abwarten("Statik", 10)
        wartet.append(st.letztes()[0])

    t = threading.Thread(target=leser)
    t.start()
    time.sleep(0.05)
    assert not wartet
    st.fertig({"type": "CHECK", "run": 7, "state": "teilweise", "befunde": [], "druck": {},
               "im_hintergrund": ["Statik"]}, b"")
    st.abwarten("Druck", 0.0)  # Druck ist jetzt da, kein Warten
    time.sleep(0.05)
    assert not wartet  # Statik steht noch aus
    st.fertig({"type": "CHECK", "run": 7, "state": "done", "befunde": [], "statik": {}}, b"")
    t.join(5)
    assert wartet and wartet[0]["state"] == "done"
    st.abwarten("Statik", 0.0)  # nichts mehr offen
    # ein neuerer Lauf bricht das Warten ab
    st.erwarte(8)
    st.fertig({"type": "CHECK", "run": 8, "state": "teilweise", "befunde": [], "im_hintergrund": ["Statik"]}, b"")
    t0 = time.perf_counter()
    th = threading.Thread(target=lambda: st.abwarten("Statik", 10))
    th.start()
    st.fertig({"type": "CHECK", "run": 8, "state": "cancelled"}, b"")
    th.join(5)
    assert not th.is_alive() and time.perf_counter() - t0 < 5


def test_spiel_genau_an_der_grenze_haengt_nicht_an_der_reihenfolge(monkeypatch):
    """Ein Spiel von nominal genau 0,5 mm misst OCCT je nach Reihenfolge knapp darüber oder darunter; die Reihenfolge hängt
    am Formschlüssel und damit etwa am Rechengedächtnis. Gefunden im Kugelschieber (laufrolle_l=90)."""
    from build123d import Box, Pos

    from kevcad_kernel.pruefung import kollision
    from kevcad_kernel.pruefung.befund import BERUEHR_TOL
    from kevcad_kernel.pruefung.koerper import koerper_aus_form

    a = koerper_aus_form("A", Box(10, 10, 10))
    b = koerper_aus_form("B", Pos(10 + BERUEHR_TOL, 0, 0) * Box(10, 10, 10))
    for abstand in (BERUEHR_TOL - 3e-14, BERUEHR_TOL + 3e-14):
        monkeypatch.setattr(kollision, "abstand", lambda _p, _q, d=abstand: d)
        paar = kollision.pruefe_paar(a, b)
        assert paar is not None and paar.kontakt and paar.art == "spiel", abstand
    monkeypatch.setattr(kollision, "abstand", lambda _p, _q: BERUEHR_TOL + 0.01)
    paar = kollision.pruefe_paar(a, b)
    assert paar is None or not paar.kontakt


def test_reihenfolge_der_pruefungen():
    from kevcad_kernel.pruefung import pruefer

    namen = [n for n, _ in pruefer.PRUEFUNGEN]
    assert namen == ["erklaerungen", "durchdringung", "bedingungen", "stand", "druck", "druckvorschau", "gedruckt",
                     "montage", "statik", "bewegungsraum"]


def test_kurzer_text_nennt_was_noch_kommt():
    from kevcad_kernel.pruefung.text import hintergrund_text

    text = hintergrund_text({"im_hintergrund": ["Montage", "Statik", "Bewegungsraum"]})
    assert text.startswith("Montage, Statik und Bewegungsraum rechnen noch im Hintergrund")
    assert "pruefen() wartet darauf" in text and "Gelenk" not in text
    text = hintergrund_text({"im_hintergrund": ["drehgelenk Klappe"]})
    assert text.startswith("Bewegungsraum: 1 Gelenk noch nicht geprüft")
    text = hintergrund_text({"im_hintergrund": ["Statik", "drehgelenk Klappe"]})
    assert text.startswith("Statik rechnet noch") and "1 Gelenk" in text
    assert "nicht vollständig" in hintergrund_text({"im_hintergrund": [], "message": "Fehler"})


def test_zwischenstand_meldet_nichts_als_behoben():
    """Was im Zwischenstand fehlt, ist noch nicht gerechnet: nicht „behoben“, und der Agent kennt es weiter."""
    from kevcad_kernel.mcp_tools.laufbericht import Stand, befund_kennung, befund_schluessel, bericht

    alt = {"art": "statik_festigkeit", "teile": ["Rahmen"], "schwere": "warnung", "text": "Rahmen hält nicht",
           "loesung": "stärker"}
    vorher = Stand(run=1, befunde={befund_schluessel(alt)}, befund_arten={befund_kennung(alt)})
    teil = {"ok": True, "run": 2, "parts": [], "pruefung": {"state": "teilweise", "befunde": [],
                                                            "im_hintergrund": ["Druck", "Montage", "Statik"]}}
    text, data, fehler, stand = bericht(teil, vorher)
    assert data["befunde"]["behoben"] == 0 and "Behoben" not in text and not fehler
    assert "Montage" in text and "pruefen()" in text
    assert befund_schluessel(alt) in stand.befunde
    fertig = {"ok": True, "run": 3, "parts": [], "pruefung": {"state": "done", "befunde": []}}
    _, data, _, _ = bericht(fertig, stand)
    assert data["befunde"]["behoben"] == 1  # erst der Endstand sagt es


def test_app_sieht_offene_pruefungen_als_rechnungen():
    from kevcad_kernel.pruefung.anbindung import check_fuer_app

    kopf = {"type": "CHECK", "im_hintergrund": ["Montage", "drehgelenk Klappe"], "statik_im_hintergrund": ["Ablauf A"]}
    app = check_fuer_app(kopf)
    assert app["im_hintergrund"] == ["drehgelenk Klappe"]
    assert app["statik_im_hintergrund"] == ["Montage", "Ablauf A"]
    assert kopf["im_hintergrund"] == ["Montage", "drehgelenk Klappe"]  # das Original bleibt für den Agenten
    nur_wege = {"type": "CHECK", "im_hintergrund": ["drehgelenk Klappe"]}
    assert check_fuer_app(nur_wege) is nur_wege


def test_gemerkter_weg_zaehlt_auch_nach_dem_zeitlimit(tmp_path, monkeypatch):
    """Nach dem Zeitlimit rechnet der Bewegungsraum nichts mehr, nimmt aber, was er schon weiß: ein unveränderter Lauf
    bleibt dadurch ``done``, auch wenn die Zeit knapp ist."""
    from test_prueftempo import KLAPPEN

    from kevcad_kernel.bedingungen import anbindung

    (tmp_path / "model.py").write_text(KLAPPEN, encoding="utf-8")
    r = Runner(lambda h, p=b"": None)
    msg = {"path": str(tmp_path / "model.py"), "params": {}, "inventar_regel": False}
    assert r.run({**msg, "run": 1})["type"] == "RUN_DONE"
    voll, _ = r.pruefe(1)
    assert voll["state"] == "done" and any(b["art"] == "bewegungsraum" for b in voll["befunde"])
    monkeypatch.setattr(anbindung, "ZEITLIMIT_S", 0.0)
    assert r.run({**msg, "run": 2})["type"] == "RUN_DONE"
    zweit, _ = r.pruefe(2)
    assert zweit["state"] == "done" and _befunde(zweit) == _befunde(voll)


# -- Laufzeit: run wartet kurz, pruefen wartet auf den Rest --------------------------------------------------------------


VIELE = """from build123d import *
from kevcad import show, param
b = param("b", 20)
for i in range(42):
    show(Pos(i * 30, 0, 2.5) * Box(b, 10, 5), f"Platte {i}")
"""


@pytest.fixture(scope="module")
def laufzeit():
    alt = os.environ.get("KEVCAD_PRUEF_STUFEN")
    os.environ["KEVCAD_PRUEF_STUFEN"] = "1"  # der Rechenprozess erbt es beim Start
    tmp = Path(tempfile.mkdtemp(prefix="kcstufen", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    rt = make_runtime(sock)
    rt.run_warten_s = None  # Vorgabe wie für den Agenten
    assert rt.wait_worker_ready(240)
    app = FakeApp(sock)
    app.wait_for(lambda h: h["type"] == "HELLO")
    assert rt.project_new(str(tmp / "Viele"), "empty")["ok"]
    assert rt.model_write(VIELE)["ok"]
    assert rt.set_inventory_rule(False)["ok"]
    assert rt.wait_idle(60)
    yield {"rt": rt, "app": app}
    app.close()
    rt.close()
    os.environ["KEVCAD_PRUEF_STUFEN"] = alt or "0"
    shutil.rmtree(tmp, ignore_errors=True)


def test_lauf_erst_zwischenstand_dann_endstand(laufzeit):
    rt, app = laufzeit["rt"], laufzeit["app"]
    start = app.mark()
    res = rt.run(warten_s=60)
    assert res["ok"], res.get("error")
    assert res["pruefung"]["state"] in ("teilweise", "done")
    _, _, teil, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == res["run"]
                                 and h.get("state") == "teilweise", start=start, timeout=30)
    _, _, done, _ = app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == res["run"]
                                 and h.get("state") == "done", start=start, timeout=60)
    # die App liest offene Prüfungen als Rechnungen, nicht als Gelenke
    assert teil["statik_im_hintergrund"] == ["Druck", "Montage", "Statik"] and not teil["im_hintergrund"]
    assert "im_hintergrund" not in done and "statik_im_hintergrund" not in done
    assert isinstance(done.get("montage"), dict)
    # pruefen wartet und liefert den Endstand
    p = rt.pruefen(endstand=True)
    assert p["ok"] and p["state"] == "done" and p["run"] == res["run"]


def test_lauf_ohne_aenderung_ein_check(laufzeit):
    rt, app = laufzeit["rt"], laufzeit["app"]
    assert rt.run(warten_s=60)["ok"]
    assert rt.wait_idle(60)
    rt.pruefen(endstand=True)
    start = app.mark()
    res = rt.run(warten_s=60)
    assert res["ok"] and res["pruefung"]["state"] == "done", res.get("pruefung")
    app.wait_for(lambda h: h["type"] == "CHECK" and h.get("run") == res["run"] and h.get("state") == "done",
                 start=start, timeout=30)
    assert not [h for h in app.since(start) if h["type"] == "CHECK" and h.get("state") == "teilweise"]


def test_pruefen_wartet_auf_den_rest_nach_kurzem_run(laufzeit):
    """run kehrt zurück, bevor die Prüfung fertig ist, und sagt das; pruefen() liefert danach den Endstand."""
    rt = laufzeit["rt"]
    res = rt.run(params={"b": 21.0}, warten_s=0)
    assert res["ok"] and res["pruefung"]["state"] in ("running", "teilweise", "done"), res.get("pruefung")
    if res["pruefung"]["state"] != "done":
        from kevcad_kernel.mcp_tools.laufbericht import befunde_des_laufs, pruefstand_zeile

        befunde, state, _ = befunde_des_laufs(res)
        assert "pruefen()" in pruefstand_zeile(res, state, befunde)
    p = rt.pruefen(endstand=True)
    assert p["ok"] and p["state"] == "done" and p["run"] == res["run"]


def test_statik_nach_kurzem_run_ist_die_des_laufs(laufzeit):
    """statik() liest, was erst nach dem Zwischenstand kommt: Es wartet darauf statt den Stand des vorigen Laufs zu zeigen."""
    rt = laufzeit["rt"]
    assert rt.run(params={"b": 23.0}, warten_s=60)["ok"]
    rt.pruefen(endstand=True)
    res = rt.run(params={"b": 24.0}, warten_s=0)
    assert res["ok"]
    st = rt.statik()
    assert st["ok"] and st["run"] == res["run"], st


def test_run_warten_nach_der_dauer_des_laufs(laufzeit):
    from kevcad_kernel.runtime import RUN_WARTEN_MIN_S, RUN_WARTEN_S, RUN_ZIEL_S, Job

    rt = laufzeit["rt"]
    job = Job(kind="run", code="", source="agent", timeout_s=1)

    def warten(dauer: float) -> float:
        job.started = time.perf_counter() - dauer
        return rt._run_warten(job)

    assert 1.3 < warten(1.0) <= RUN_ZIEL_S - 1.0  # kurzer Lauf: bis zum Budget (kleine Modelle: ganze Prüfung im Ergebnis)
    assert warten(1.9) < 0.6  # Maßänderung am großen Modell: zusammen unter 2,5 s
    assert warten(2.5) == RUN_WARTEN_MIN_S
    assert 2.3 < warten(8.0) < RUN_WARTEN_S  # langer Lauf: ein Anteil der Laufzeit
    assert warten(60.0) == RUN_WARTEN_S
    rt.run_warten_s = 3.0
    try:
        assert rt._run_warten(job) == 3.0
    finally:
        rt.run_warten_s = None


# -- Start des Kernels -------------------------------------------------------------------------------------------------


def _im_neuen_prozess(code: str) -> None:
    import subprocess
    import sys

    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]


def test_elternprozess_startet_ohne_build123d():
    """Der Kernel öffnet Socket und MCP, ohne build123d zu laden (2 s); das tut er, wenn der Rechenprozess bereit ist."""
    _im_neuen_prozess("""
import sys
import kevcad_kernel.server, kevcad_kernel.runtime
schwer = [m for m in ("build123d", "OCP", "scipy", "sklearn", "pandas") if m in sys.modules]
assert not schwer, schwer
import kevcad_kernel.druck
assert "OCP" not in sys.modules
assert callable(kevcad_kernel.druck.pruefe_druckteil) and kevcad_kernel.druck.SCHWEREN  # auf Abruf
assert "OCP" in sys.modules
""")


def test_build123d_ohne_sklearn_verhaelt_sich_wie_immer():
    _im_neuen_prozess("""
import sys
from kevcad_kernel.schnellstart import build123d_laden
b = build123d_laden()
assert "sklearn" not in sys.modules and "sklearn.cluster" not in sys.modules
assert b.Box(1, 2, 3).volume == 6
from build123d import brep_from_stl
modell = brep_from_stl.DBSCAN(eps=0.5, min_samples=1)  # lädt sklearn beim ersten Aufruf
from sklearn.cluster import DBSCAN  # das echte Paket, nicht der Stellvertreter
assert type(modell) is DBSCAN and "sklearn" in sys.modules
import sklearn
assert sklearn.__version__
""")


def test_nach_sklearn_laedt_build123d_normal():
    _im_neuen_prozess("""
import sklearn.cluster
from kevcad_kernel.schnellstart import build123d_laden
b = build123d_laden()
from build123d import brep_from_stl
import sklearn.cluster as c
assert brep_from_stl.DBSCAN is c.DBSCAN
""")


def test_projekt_oeffnen_wartet_nicht_auf_den_rechenprozess():
    """Bereit heißt: Projekte gehen. Ein Lauf wartet selbst auf den Rechenprozess."""
    tmp = Path(tempfile.mkdtemp(prefix="kcstart", dir=tempfile.gettempdir()))
    rt = make_runtime(str(tmp / "k.sock"))
    try:
        st = rt.status()
        assert st["kernel"] == "ready", st
        assert rt.project_new(str(tmp / "P"), "empty")["ok"]
        assert rt.status()["project"] is not None
        rt.set_inventory_rule(False)
        rt.model_write("from build123d import *\nfrom kevcad import show\nshow(Box(1, 2, 3), 'K')\n")
        res = rt.run()
        assert res["ok"], res.get("error")
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)


# -- Bauplan im Hintergrund: ein neuer Lauf löst ihn ab ------------------------------------------------------------------


def test_halt_bricht_nur_im_block_und_nur_ohne_aktualitaet():
    from kevcad_kernel.bauplan.wege import Ueberholt, halt, nur_solange

    halt()  # außerhalb: nichts
    with nur_solange(lambda: True):
        halt()
    with nur_solange(None):
        halt()
    with pytest.raises(Ueberholt), nur_solange(lambda: False):
        halt()
    halt()  # danach wieder nichts
    assert not issubclass(Ueberholt, Exception)  # „except Exception“ einzelner Teile schluckt ihn nicht


def test_neuer_lauf_loest_den_bauplan_im_hintergrund_ab(monkeypatch):
    """Ein Bauplan im Hintergrund rechnet nur, solange sein Lauf der neueste ist: Er nimmt dem nächsten Lauf sonst die GIL
    (gemessen 2,6 s), und speichern dürfte er ohnehin nichts mehr."""
    import threading

    from kevcad_kernel.bauplan import plan
    from kevcad_kernel.bauplan.wege import halt

    tmp = Path(tempfile.mkdtemp(prefix="kcbp", dir=tempfile.gettempdir()))
    rt = make_runtime(str(tmp / "k.sock"))
    original = plan.erzeuge
    begonnen, beendet = threading.Event(), threading.Event()
    zustand = {"aktiv": False}

    def langsam(ein, alt=None, zeitlimit_s=90.0):
        if zustand["aktiv"]:
            begonnen.set()
            try:
                ende = time.monotonic() + 30
                while time.monotonic() < ende:
                    halt()
                    time.sleep(0.01)
                raise AssertionError("nicht abgelöst")
            finally:
                beendet.set()
        return original(ein, alt, zeitlimit_s)

    monkeypatch.setattr(plan, "erzeuge", langsam)
    try:
        assert rt.wait_worker_ready(240)
        assert rt.project_new(str(tmp / "P"), "empty")["ok"]
        rt.set_inventory_rule(False)
        rt.model_write("from build123d import *\nfrom kevcad import show, param\n"
                       "show(Box(param('b', 20), 10, 5), 'Platte')\n")
        res = rt.run()
        assert res["ok"], res.get("error")
        assert rt.bauplan()["ok"]  # legt den Bauplan an: ab jetzt rechnet er nach jedem Lauf im Hintergrund
        assert rt.wait_idle(60)
        zustand["aktiv"] = True
        assert rt.run(params={"b": 21.0})["ok"]
        assert begonnen.wait(30)
        zustand["aktiv"] = False
        assert rt.run(params={"b": 22.0})["ok"]
        assert beendet.wait(5), "der alte Bauplan rechnet weiter"
        assert rt.wait_idle(60)
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)
