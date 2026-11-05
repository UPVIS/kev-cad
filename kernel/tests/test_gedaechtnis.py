"""Rechengedächtnis (gedaechtnis.py): gleiche Ergebnisse wie build123d direkt, frische Kopien, Historie, Grenzen."""

from __future__ import annotations

import warnings

import pytest
from build123d import (
    Box,
    BuildPart,
    Compound,
    Cylinder,
    Mode,
    Pos,
    Select,
    fillet,
)
from build123d.topology import shape_core

from kevcad_kernel import gedaechtnis as gd
from kevcad_kernel.gedaechtnis import schreiben


@pytest.fixture
def mit_gedaechtnis(monkeypatch):
    monkeypatch.delenv("KEVCAD_GEDAECHTNIS", raising=False)
    gd.entfernen()
    assert gd.installieren()
    gd.lauf_beginn()
    yield gd
    gd.entfernen()


def _faelle():
    """Frische Eingaben je Aufruf: (Name, Funktion ohne Argumente → Form)."""
    return [
        ("schnitt", lambda: Box(40, 40, 10) - Pos(0, 0, 5) * Cylinder(5, 20)),
        ("sackloch", lambda: Box(40, 40, 10) - Pos(0, 0, 3) * Cylinder(5, 10)),
        ("vereinigung", lambda: Box(10, 10, 10) + Pos(5, 5, 5) * Box(10, 10, 10)),
        ("stumpf", lambda: Box(10, 10, 10) + Pos(10, 0, 0) * Box(10, 10, 10)),
        ("schnittmenge", lambda: Box(10, 10, 10) & Pos(5, 5, 5) * Box(10, 10, 10)),
        ("ohne_beruehrung", lambda: Box(10, 10, 10) - Pos(100, 0, 0) * Box(1, 1, 1)),
        ("glue", lambda: Box(10, 10, 10).fuse(Pos(10, 0, 0) * Box(10, 10, 10), glue=True)),
        ("fuzzy", lambda: Box(10, 10, 10).fuse(Pos(10.000001, 0, 0) * Box(10, 10, 10), tol=1e-5)),
        ("mehrere", lambda: Box(30, 30, 5).cut(Pos(-8, 0, 0) * Cylinder(2, 10), Pos(8, 0, 0) * Cylinder(2, 10))),
        ("compound", lambda: Compound([Box(5, 5, 5), Pos(20, 0, 0) * Box(5, 5, 5)]) + Pos(2, 0, 0) * Box(5, 5, 5)),
    ]


def _geometrie(form):
    bb = form.bounding_box()
    return (type(form).__name__, len(form.faces()), len(form.edges()), len(form.vertices()), round(form.volume, 6),
            round(form.area, 6), tuple(round(v, 6) for v in (*bb.min, *bb.max)))


def test_gleiche_ergebnisse_wie_ohne(mit_gedaechtnis):
    """Gleiche Geometrie wie build123d direkt; gemerkt und Treffer Bit für Bit gleich (Modulbeschreibung: gegenüber
    OCCT direkt kann eine Null das Vorzeichen wechseln)."""
    gleich = 0
    for name, f in _faelle():
        gd.entfernen()
        ohne = f()
        assert gd.installieren()
        neu = f()  # gerechnet und gemerkt
        treffer = f()  # aus dem Speicher
        assert gd.statistik()["treffer"] >= 1, name
        assert _geometrie(neu) == _geometrie(ohne), name
        assert schreiben(treffer.wrapped) == schreiben(neu.wrapped), name
        assert neu.label == ohne.label and treffer.color == ohne.color, name
        gleich += schreiben(neu.wrapped) == schreiben(ohne.wrapped)
    assert gleich >= len(_faelle()) - 2  # bitgleich bis auf Nullen mit Vorzeichen (glue, fuzzy)


def test_treffer_ist_frische_kopie(mit_gedaechtnis):
    a = Box(10, 10, 10) - Cylinder(2, 20)
    b = Box(10, 10, 10) - Cylinder(2, 20)
    assert gd.statistik()["treffer"] == 1
    assert schreiben(a.wrapped) == schreiben(b.wrapped)
    assert not a.wrapped.IsPartner(b.wrapped)
    assert not any(f.wrapped.IsPartner(g.wrapped) for f in a.faces() for g in b.faces())


def test_eingaben_bleiben_unveraendert(mit_gedaechtnis):
    a, b = Box(40, 40, 10), Pos(0, 0, 5) * Cylinder(5, 20)
    vorher = (schreiben(a.wrapped), schreiben(b.wrapped), a.wrapped.Free(), b.wrapped.Free())
    _ = a - b
    _ = a - b  # Treffer
    assert (schreiben(a.wrapped), schreiben(b.wrapped), a.wrapped.Free(), b.wrapped.Free()) == vorher


def test_auswahl_last_und_new_wie_ohne(mit_gedaechtnis):
    def zahlen():
        a, b = Box(20, 20, 20), Pos(0, 0, 10) * Cylinder(4, 20)
        r = a + b
        last_e = r.edges(Select.LAST)
        new_f = r.faces(Select.NEW)
        last_f = r.faces(Select.LAST)
        return (len(last_e), round(sum(e.length for e in last_e), 6), len(new_f), len(last_f),
                round(sum(f.area for f in last_f), 6))

    gd.entfernen()
    ohne = zahlen()
    assert gd.installieren()
    assert zahlen() == ohne  # gerechnet: übersetzte Historie
    assert zahlen() == ohne  # Treffer: Historie nachgerechnet
    assert gd.statistik()["treffer"] >= 1


def test_builder_mit_select_last(mit_gedaechtnis):
    def teil():
        with BuildPart() as bp:
            Box(20, 20, 20)
            Cylinder(4, 30, mode=Mode.SUBTRACT)
            fillet(bp.edges(Select.LAST), 1)
        return bp.part

    gd.entfernen()
    ohne = teil()
    assert gd.installieren()
    eins, zwei = teil(), teil()
    assert schreiben(eins.wrapped) == schreiben(ohne.wrapped)
    assert schreiben(zwei.wrapped) == schreiben(ohne.wrapped)
    assert abs(zwei.volume - ohne.volume) < 1e-9


def test_section_und_abkuerzungen_umgangen(mit_gedaechtnis):
    gd.entfernen()
    ohne = Box(10, 10, 10).cut()  # keine Werkzeuge: Abkürzung von build123d
    assert gd.installieren()
    gd.lauf_beginn()
    mit = Box(10, 10, 10).cut()
    assert type(mit) is type(ohne) and schreiben(mit.wrapped) == schreiben(ohne.wrapped)
    assert gd.statistik()["umgangen"] == 1 and gd.statistik()["neu"] == 0


def test_aus_mit_umgebung(monkeypatch):
    gd.entfernen()
    monkeypatch.setenv("KEVCAD_GEDAECHTNIS", "0")
    assert not gd.installieren()
    assert gd.statistik() is None
    assert shape_core.Shape._bool_op is not gd._bool_op


def test_ausnahmen_kommen_durch(mit_gedaechtnis, monkeypatch):
    def kaputt(*_args, **_kwargs):
        raise RuntimeError("OCCT kaputt")

    monkeypatch.setattr(gd, "_rechnen", kaputt)
    with pytest.raises(RuntimeError, match="OCCT kaputt"):
        _ = Box(10, 10, 10) - Cylinder(2, 20)
    assert gd.statistik()["neu"] == 0  # nichts gemerkt


def test_nicht_aufgeraeumt_wird_nicht_gemerkt(mit_gedaechtnis, monkeypatch):
    echt = gd._rechnen

    def ohne_aufraeumen(op, args, tools, aufraeumen, stacklevel):
        erg, hist, _ = echt(op, args, tools, aufraeumen, stacklevel)
        warnings.warn("Boolean operation unable to clean", stacklevel=stacklevel)
        return erg, hist, False

    monkeypatch.setattr(gd, "_rechnen", ohne_aufraeumen)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = Box(10, 10, 10) - Cylinder(2, 20)
    assert any("unable to clean" in str(w.message) for w in caught)
    assert gd.statistik()["nicht_gemerkt"] == 1 and len(gd.SPEICHER) == 0


def test_speicher_begrenzt():
    sp = gd.Speicher(max_bytes=100)
    for i in range(5):
        sp.put(bytes([i]), gd.Eintrag(blob=b"x" * 40, rechnen_ms=1.0, art=object, einstellungen={}, n_args=1,
                                      aufraeumen=True))
    assert len(sp) == 2 and sp.nbytes == 80
    assert sp.get(bytes([0])) is None and sp.get(bytes([4])) is not None


def test_quelle_von_build123d_passt():
    """Schlägt fehl, wenn build123d aktualisiert wurde: dann die Nachbauten in gedaechtnis.py nachziehen."""
    import hashlib
    import inspect

    from build123d.geometry import BoundBox

    gd.entfernen()
    for name, (_, _, original, _) in gd._ziele().items():
        soll = gd.QUELLEN.get(name)
        if soll is not None:
            assert hashlib.sha1(inspect.getsource(original).encode()).hexdigest() == soll, name
    assert hashlib.sha1(inspect.getsource(BoundBox.__init__).encode()).hexdigest() == gd.ABHAENGIG["BoundBox.__init__"]


def test_schnittmenge_und_clean(mit_gedaechtnis):
    """``&`` (intersect mit fester Reihenfolge, clean) gleich wie ohne, LAST/NEW über die aufgeschobene Historie."""
    def teil():
        a = Box(30, 30, 10) + Pos(20, 0, 0) * Box(10, 10, 10)
        b = Pos(5, 0, 0) * Cylinder(12, 20)
        r = a & b
        return r, len(r.faces(Select.LAST)), len(r.edges(Select.NEW))

    gd.entfernen()
    ohne, last_o, new_o = teil()
    assert gd.installieren()
    eins, last_1, new_1 = teil()
    zwei, last_2, new_2 = teil()
    assert _geometrie(eins) == _geometrie(ohne)
    assert schreiben(zwei.wrapped) == schreiben(eins.wrapped)
    assert (last_1, new_1) == (last_o, new_o) and (last_2, new_2) == (last_o, new_o)
    st = gd.statistik()
    assert st["treffer"] >= 2  # Schnittmenge und clean beim zweiten Mal aus dem Speicher


def test_clean_direkt(mit_gedaechtnis):
    def teil():
        return (Box(10, 10, 10) + Pos(10, 0, 0) * Box(10, 10, 10)).clean()

    gd.entfernen()
    ohne = teil()
    assert gd.installieren()
    eins, zwei = teil(), teil()
    assert _geometrie(eins) == _geometrie(ohne) and len(eins.faces()) == len(ohne.faces())
    assert schreiben(zwei.wrapped) == schreiben(eins.wrapped)


def test_volumen_und_abstand(mit_gedaechtnis):
    a = Box(10, 10, 10)
    b = Pos(30, 0, 0) * Box(10, 10, 10)
    v = a.volume
    assert abs(v - 1000.0) < 1e-9 and abs(a.volume - v) == 0.0
    assert gd.statistik()["werte_treffer"] >= 1
    d1 = gd.abstand(a.wrapped, b.wrapped)
    assert d1 is not None and abs(d1[0] - 20.0) < 1e-9
    assert gd.abstand(a.wrapped, b.wrapped) == d1  # gemerkt
    vorher = gd.inhalt(b.wrapped)
    b.move(Pos(10, 0, 0))  # verschiebt an Ort und Stelle: anderer Inhalt, anderer Abstand
    assert gd.inhalt(b.wrapped) != vorher
    d2 = gd.abstand(a.wrapped, b.wrapped)
    assert abs(d2[0] - 30.0) < 1e-9


def test_huellquader(mit_gedaechtnis, monkeypatch):
    """Hüllquader je Inhalt (V2-1): gleich wie build123d (Ecken und Lücke), auch als Treffer; der Treffer entfernt ein
    Netz wie build123d; Toleranz und ``optimal=False`` gehen an build123d; verschoben ist ein anderer Inhalt."""
    from build123d import Torus
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopLoc import TopLoc_Location

    def teil():
        return Pos(3, 4, 5) * Torus(20, 4)

    def werte(bb):
        return (*bb.min, *bb.max, bb.wrapped.GetGap())

    def vernetzt():
        t = teil()
        BRepMesh_IncrementalMesh(t.wrapped, 0.5)
        assert BRep_Tool.Triangulation_s(t.faces()[0].wrapped, TopLoc_Location()) is not None
        return t

    gd.entfernen()
    ohne = werte(teil().bounding_box())
    ohne_tol = werte(teil().bounding_box(tolerance=0.5, optimal=False))
    assert gd.installieren()
    gd.lauf_beginn()
    a, b, c, d, e = teil(), teil(), vernetzt(), vernetzt(), teil()  # Formen zuerst (Torus richtet sich am Hüllquader aus)
    gerechnet: list[int] = []
    echt = gd._original["bounding_box"]
    monkeypatch.setitem(gd._original, "bounding_box", lambda *x: gerechnet.append(1) or echt(*x))
    assert werte(a.bounding_box()) == ohne and len(gerechnet) == 1  # gerechnet und gemerkt
    assert werte(b.bounding_box()) == ohne and len(gerechnet) == 1  # gleicher Inhalt: Treffer
    assert werte(c.bounding_box()) == ohne and len(gerechnet) == 2  # das Netz setzt Flags: eigener Inhalt
    assert werte(d.bounding_box()) == ohne and len(gerechnet) == 2  # Treffer
    assert BRep_Tool.Triangulation_s(d.faces()[0].wrapped, TopLoc_Location()) is None  # wie build123d entfernt
    assert werte(e.bounding_box(tolerance=0.5, optimal=False)) == ohne_tol and len(gerechnet) == 3
    weiter = teil()
    weiter.move(Pos(10, 0, 0))
    bb = weiter.bounding_box()
    assert abs(bb.min.X - (ohne[0] + 10)) < 1e-9 and abs(bb.max.X - (ohne[3] + 10)) < 1e-9
