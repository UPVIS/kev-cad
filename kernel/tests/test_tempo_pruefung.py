"""V2-1b „Tempo im Kernel nachziehen“, Prüfung nach dem Lauf. Gedächtnis der Statik (statik/merken.py): Treffer,
Fehltreffer bei jeder geänderten Eingabe, abgeschaltet, Fehler werden nicht gemerkt."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_statik import TISCH, laufe

from kevcad_kernel.catalog import builtin_dir
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
