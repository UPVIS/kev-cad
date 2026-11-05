"""V2-2: knappes Laufergebnis (mcp_tools/laufbericht.py) ohne Kernel: Teile neu, geändert, entfernt; Befunde neu,
bekannt, geändert, behoben (auch solange die Prüfung noch läuft); Inventar-Regel; Fehler bleiben vollständig."""

from __future__ import annotations

import copy

from kevcad_kernel.mcp_tools.laufbericht import MAX_TEILE, Gedaechtnis, bericht


def teil(name, lo=(0, 0, 0), hi=(10, 10, 10), mass=10.0, key=None, **extra):
    return {"name": name, "bbox": {"min": list(lo), "max": list(hi)}, "volume": 1000.0, "mass": mass,
            "material": "petg", "faces": 6, "edges": 12, "key": key or f"{name}-{lo}-{hi}", **extra}


def lauf(nr, parts, *, befunde=None, state="done", params=None, **extra):
    res = {"ok": True, "run": nr, "parts": parts, "params": params or {}, "warnings": [],
           "zeiten_ms": {"skript": 900.0, "run_end": 1000.0, "zurueck": 1500.0}}
    if state is not None:
        res["pruefung"] = {"state": state, "befunde": befunde or []}
    res.update(extra)
    return res


DURCH = {"art": "durchdringung", "teile": ["A", "B"], "schwere": "fehler",
         "text": "A und B durchdringen sich: 12,5 mm³, Tiefe etwa 0,5 mm.", "loesung": "A um 0,7 mm in +Z verschieben."}
WARN = {"art": "druck_ueberhang", "teile": ["C"], "schwere": "warnung", "text": "C: Überhang 60° an #f3",
        "loesung": "Fase statt Rundung."}


def test_erster_lauf_baugruppen_und_parameter():
    parts = [teil("Gestell/Bein 1"), teil("Gestell/Bein 2", (20, 0, 0), (30, 10, 10)), teil("Platte", mass=500)]
    text, data, fehler, stand = bericht(lauf(1, parts, params={"b": 20}), None)
    assert text.startswith("Lauf 1: 3 Teile in 2 Baugruppen (erster Lauf, den du siehst).")
    assert "Parameter: b=20" in text and "- Gestell: 2 Teile, 30 × 10 × 10 mm, 20 g" in text
    assert "Prüfung fertig: keine." in text and "Zeiten: Modell 0,9 s, im Viewer 1 s, Antwort 1,5 s" in text
    assert not fehler and data["kalt"] is True and stand.teile.keys() == {"Gestell/Bein 1", "Gestell/Bein 2", "Platte"}


def test_teile_neu_geaendert_entfernt_mit_unterschied():
    a = [teil("A"), teil("B"), teil("C", key="c1"), teil("D")]
    _, _, _, st = bericht(lauf(1, a), None)
    b = [teil("A", (0, 0, 0), (10, 10, 12), mass=12.0), teil("B", (5, 0, 0), (15, 10, 10)), teil("C", key="c2"),
         teil("E", (50, 0, 0), (60, 4, 4), mass=1.0)]
    text, data, _, _ = bericht(lauf(2, b), st)
    assert text.startswith("Lauf 2: 4 Teile, 1 neu, 3 geändert, 1 entfernt, 0 unverändert.")
    assert "- A: 10 × 10 × 12 mm (vorher 10 × 10 × 10 mm), 12 g (+2 g)" in text
    assert "- B: 10 × 10 × 10 mm, verschoben um (5; 0; 0)" in text
    assert "- C: 10 × 10 × 10 mm, Form geändert, Hüllmaß gleich" in text  # Formschlüssel anders, Maße gleich
    assert "- E (neu): 10 × 4 × 4 mm, 1 g, petg" in text and "Entfernt: D" in text
    assert data["neu"] == ["E"] and data["geaendert"] == ["A", "B", "C"] and data["entfernt"] == ["D"]


def test_viele_geaenderte_teile_je_baugruppe():
    a = [teil(f"Rahmen/Teil {i}") for i in range(MAX_TEILE + 5)]
    _, _, _, st = bericht(lauf(1, a), None)
    b = [teil(f"Rahmen/Teil {i}", (1, 0, 0), (11, 10, 10)) for i in range(MAX_TEILE + 5)]
    text, _, _, _ = bericht(lauf(2, b), st)
    assert f"- Rahmen: {MAX_TEILE + 5} geändert, 0 neu" in text and "Rahmen/Teil 3:" not in text


def test_befunde_neu_bekannt_geaendert_behoben():
    parts = [teil("A"), teil("B"), teil("C")]
    text, _, fehler, st = bericht(lauf(1, parts, befunde=[DURCH, WARN]), None)
    assert "Neue Befunde (1 Fehler, 1 Warnung):" in text and "Lösung: A um 0,7 mm in +Z verschieben." in text
    assert fehler is True
    text, data, fehler, st = bericht(lauf(2, parts, befunde=[DURCH, WARN]), st)
    assert "Neue" not in text and "Lösung" not in text
    assert "Bekannte Befunde unverändert: 1 Fehler, 1 Warnung – die Fehler sind weiter offen" in text
    assert fehler is True and data["befunde"]["bekannt"] == 2
    # Prüfung läuft noch: nichts als behoben melden, Bekanntes bleibt bekannt
    text, _, fehler, st = bericht(lauf(3, parts, state="running"), st)
    assert "Behoben" not in text and "Prüfung läuft noch im Hintergrund" in text and fehler is False
    # Wert geändert: als geändert gezeigt
    anders = {**DURCH, "text": "A und B durchdringen sich: 3,1 mm³, Tiefe etwa 0,2 mm."}
    text, _, fehler, st = bericht(lauf(4, parts, befunde=[anders, WARN]), st)
    assert "Neue oder geänderte Befunde (1 Fehler):" in text and "3,1 mm³" in text and "Überhang" not in text
    assert "Behoben" not in text  # geändert ist nicht behoben
    # behoben
    text, _, fehler, st = bericht(lauf(5, parts, befunde=[WARN]), st)
    assert "Behoben seit dem letzten Lauf: 1 Befund." in text and fehler is False
    assert "Bekannte Befunde unverändert: 1 Warnung." in text


def test_gleichartige_befunde_zusammengefasst():
    viele = []
    for i, name in enumerate(["H1", "H1", "H2", "H3", "H4"]):
        viele.append({"art": "druck_einsatz_sackloch", "teile": [name], "schwere": "warnung",
                      "text": f"{name}: Einsatz M6 im Sackloch an #f{20 + i}", "loesung": "Entlastungsbohrung Ø 6,6."})
    text, _, _, _ = bericht(lauf(1, [teil("H1")], befunde=viele + [WARN]), None)
    assert text.count("Lösung: Entlastungsbohrung") == 1
    assert "Ebenso 4× bei: H1, H2, H3, H4" in text and "C: Überhang" in text


def test_inventar_regel_vorn_dann_gezaehlt():
    res = lauf(1, [teil("A"), teil("B")], inventar_verstoesse=["A"])
    text, data, fehler, st = bericht(res, None)
    assert fehler is True and text.splitlines()[1].startswith("Inventar-Regel: 1 Teil ist nicht aus dem Inventar: A")
    text, _, fehler, _ = bericht(copy.deepcopy(res) | {"run": 2}, st)
    assert fehler is True and "Inventar-Regel: 1 bekannter Verstoß weiter offen (A)." in text
    assert data["inventar_verstoesse"] == ["A"]


def test_fehler_bleibt_vollstaendig_und_aendert_das_gedaechtnis_nicht():
    err = {"ok": False, "run": 3, "error": {"message": "NameError: platt", "line": 12, "excerpt": "12 | show(platt)",
                                            "hint": "Tippfehler?"}}
    text, data, fehler, stand = bericht(err, None)
    assert fehler is True and stand is None
    assert "fehlgeschlagen in Zeile 12" in text and "show(platt)" in text and "Hinweis: Tippfehler?" in text


def test_gedaechtnis_je_sitzung_und_pruefen():
    g = Gedaechtnis(max_sitzungen=2)
    _, _, _, st = bericht(lauf(1, [teil("A")], state="running"), None)
    g.merken("s1", st)
    g.befunde_gesehen("s1", [WARN])
    text, _, _, _ = bericht(lauf(2, [teil("A")], befunde=[WARN]), g.holen("s1"))
    assert "Neue Befunde" not in text and "Bekannte Befunde unverändert: 1 Warnung." in text
    g.merken("s2", st)
    g.merken("s3", st)
    assert g.holen("s1") is None and g.holen("s3") is not None  # älteste Sitzung fällt heraus
    g.vergessen("s3")
    assert g.holen("s3") is None
