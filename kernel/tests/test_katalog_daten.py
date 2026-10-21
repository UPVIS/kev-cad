"""Prüft die mitgelieferten Katalogdaten (kernel/src/kevcad/katalog/*.json) gegen KATALOG.md.

Nur Standardbibliothek: Die Dateien sind reine Daten und sollen auch ohne build123d prüfbar sein.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

KATALOG = Path(__file__).resolve().parents[1] / "src" / "kevcad" / "katalog"
DATEIEN = sorted(KATALOG.glob("*.json"))

ARTEN = {"rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil", "nutprofil", "holz",
         "platte", "schraube", "mutter", "scheibe"}
STANGENWARE = {"rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil", "nutprofil",
               "holz"}
KLEINTEILE = {"schraube", "mutter", "scheibe"}

# Pflichtmaße je Art (KATALOG.md, "Arten und ihre Maße"); Werte in mm
MASSE_PFLICHT = {
    "rohr": {"d", "s"},
    "vierkantrohr": {"a", "s"},
    "rechteckrohr": {"b", "h", "s"},
    "flach": {"b", "s"},
    "rund": {"d"},
    "vierkant": {"a"},
    "winkel": {"a", "b", "s"},
    "u_profil": {"h", "b", "s", "t"},
    "nutprofil": {"raster", "nut", "variante"},
    "holz": {"b", "h"},
    "platte": {"s"},
    "schraube": {"typ", "norm", "groesse"},
    "mutter": {"typ", "norm", "groesse"},
    "scheibe": {"typ", "norm", "groesse"},
}
MASSE_OPTIONAL = {"vierkantrohr": {"r"}, "rechteckrohr": {"r"}, "winkel": {"r"}, "nutprofil": {"a", "b"}}

# Klassen und Normbezeichner, wie sie bd_warehouse 0.4.0 erwartet (dort per Klasse.types() / Klasse.sizes() geprüft)
BD_WAREHOUSE = {
    "schraube": {
        "SocketHeadCapScrew": {"iso4762"},
        "HexHeadScrew": {"iso4014", "iso4017", "din931"},
        "CounterSunkScrew": {"iso10642", "iso2009", "iso7046", "iso14581", "iso14582"},
        "ButtonHeadScrew": {"iso7380_1"},
        "PanHeadScrew": {"iso1580", "iso14583"},
    },
    "mutter": {"HexNut": {"iso4032", "iso4033", "iso4035"}, "DomedCapNut": {"din1587"},
               "HexNutWithFlange": {"din1665"}, "SquareNut": {"din557"}},
    "scheibe": {"PlainWasher": {"iso7089", "iso7091", "iso7093", "iso7094"}, "ChamferedWasher": {"iso7090"}},
}
# Regelgewinde nach ISO 261 in der Schreibweise von bd_warehouse
REGELGEWINDE = {"M3": "0.5", "M4": "0.7", "M5": "0.8", "M6": "1", "M8": "1.25", "M10": "1.5", "M12": "1.75",
                "M14": "2", "M16": "2", "M20": "2.5", "M24": "3"}

ID_TEIL = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
ID_MATERIAL = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
FARBE = re.compile(r"^#[0-9A-Fa-f]{6}$")
STAND = re.compile(r"^20\d\d-(0[1-9]|1[0-2])$")

TOLERANZ_KG = 0.04


def _laden() -> dict[str, dict]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in DATEIEN}


DATEN = _laden()
MATERIALIEN = [m for d in DATEN.values() for m in d.get("materialien", [])]
TEILE = [t for d in DATEN.values() for t in d.get("teile", [])]
MAT = {m["id"]: m for m in MATERIALIEN}


def _ids(eintraege):
    return [e.get("id", "?") for e in eintraege]


# ---------------------------------------------------------------- Dateien

def test_dateien_vorhanden():
    namen = {p.name for p in DATEIEN}
    erwartet = {"materialien.json", "rohre.json", "hohlprofile.json", "vollprofile.json", "nutprofile.json",
                "holz.json", "platten.json", "verbindungselemente.json"}
    assert erwartet <= namen, f"fehlende Katalogdateien: {sorted(erwartet - namen)}"


@pytest.mark.parametrize("pfad", DATEIEN, ids=lambda p: p.name)
def test_datei_format(pfad):
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    assert isinstance(daten, dict)
    assert daten.get("version") == 1
    assert set(daten) <= {"version", "materialien", "teile"}, f"unbekannte Schlüssel: {set(daten)}"
    for key in ("materialien", "teile"):
        assert isinstance(daten.get(key, []), list)


def test_mengen():
    assert len(MATERIALIEN) >= 25
    assert len(TEILE) >= 300


# ---------------------------------------------------------------- Materialien

def test_material_pflichtfelder():
    for m in MATERIALIEN:
        mid = m.get("id", "?")
        for feld in ("id", "name", "gruppe", "dichte", "farbe"):
            assert feld in m, f"{mid}: Pflichtfeld {feld} fehlt"
        assert ID_MATERIAL.match(m["id"]), f"{mid}: id nur Kleinbuchstaben, Ziffern, Bindestrich, Punkt"
        assert isinstance(m["name"], str) and m["name"].strip()
        assert isinstance(m["gruppe"], str) and m["gruppe"].strip()
        assert isinstance(m["dichte"], (int, float)) and 0.3 <= m["dichte"] <= 9.5, f"{mid}: Dichte in g/cm³"
        assert FARBE.match(m["farbe"]), f"{mid}: farbe als #RRGGBB"
        for feld in ("metallisch", "rauheit"):
            if feld in m:
                assert 0.0 <= m[feld] <= 1.0, f"{mid}: {feld} außerhalb 0…1"
        if "preis_je_kg" in m:
            assert m["preis_je_kg"] > 0, f"{mid}: Preis muss > 0 sein"
            assert m.get("preis_quelle"), f"{mid}: preis_quelle fehlt"
            assert STAND.match(m.get("preis_stand", "")), f"{mid}: preis_stand als JJJJ-MM"
        if "druckbar" in m:
            assert isinstance(m["druckbar"], bool), f"{mid}: druckbar muss true/false sein"


def test_material_ids_eindeutig():
    ids = _ids(MATERIALIEN)
    doppelt = sorted({i for i in ids if ids.count(i) > 1})
    assert not doppelt, f"doppelte Material-ids: {doppelt}"


def test_aliase_klein_und_eindeutig():
    gesehen: dict[str, str] = {}
    for m in MATERIALIEN:
        for alias in m.get("aliase", []):
            assert alias == alias.lower() and alias.strip() == alias, f"{m['id']}: Alias {alias!r} nicht klein"
            assert alias not in gesehen, f"Alias {alias!r} bei {gesehen.get(alias)} und {m['id']}"
            assert alias not in MAT or alias == m["id"], f"Alias {alias!r} ist die id eines anderen Materials"
            gesehen[alias] = m["id"]


def test_kurznamen_finden_material():
    erwartet = {"stahl": "stahl-s235", "steel": "stahl-s235", "edelstahl": "edelstahl-1.4301",
                "v2a": "edelstahl-1.4301", "stainless": "edelstahl-1.4301", "v4a": "edelstahl-1.4404",
                "alu": "alu-6060", "aluminium": "alu-6060", "aluminum": "alu-6060", "messing": "messing",
                "brass": "messing", "holz": "fichte-tanne", "multiplex": "multiplex-birke", "pla": "pla"}
    alias = {a: m["id"] for m in MATERIALIEN for a in m.get("aliase", [])}
    for kurz, mid in erwartet.items():
        assert alias.get(kurz) == mid, f"Alias {kurz!r} sollte auf {mid} zeigen, zeigt auf {alias.get(kurz)}"


def test_druckbare_materialien():
    druckbar = {m["id"] for m in MATERIALIEN if m.get("druckbar") is True}
    assert {"pla", "petg"} <= druckbar, "PLA und PETG müssen druckbar sein"
    for mid in druckbar:
        assert MAT[mid]["gruppe"] == "Kunststoff", f"{mid}: druckbar, aber kein Kunststoff"


# ---------------------------------------------------------------- Lagerteile: Felder

def test_teil_ids_eindeutig_ueber_alle_dateien():
    ids = _ids(TEILE)
    doppelt = sorted({i for i in ids if ids.count(i) > 1})
    assert not doppelt, f"doppelte Teil-ids: {doppelt}"
    ueberschneidung = set(ids) & set(MAT)
    assert not ueberschneidung, f"ids sowohl Teil als auch Material: {sorted(ueberschneidung)}"


def test_teil_pflichtfelder():
    for t in TEILE:
        tid = t.get("id", "?")
        for feld in ("id", "art", "name", "masse", "material"):
            assert feld in t, f"{tid}: Pflichtfeld {feld} fehlt"
        assert ID_TEIL.match(t["id"]), f"{tid}: id nur Kleinbuchstaben, Ziffern, Bindestrich, Punkt"
        assert t["art"] in ARTEN, f"{tid}: unbekannte art {t['art']!r}"
        assert isinstance(t["name"], str) and t["name"].strip()
        assert isinstance(t["masse"], dict) and t["masse"]
        if "norm" in t:
            assert isinstance(t["norm"], str) and t["norm"].strip()
        if "tags" in t:
            assert all(isinstance(x, str) and x == x.lower() and x for x in t["tags"]), f"{tid}: tags klein"
            assert len(set(t["tags"])) == len(t["tags"]), f"{tid}: doppelte tags"


def test_material_existiert():
    for t in TEILE:
        assert t["material"] in MAT, f"{t['id']}: Material {t['material']!r} gibt es nicht"


def test_masse_vollstaendig():
    for t in TEILE:
        art, masse, tid = t["art"], t["masse"], t["id"]
        pflicht = MASSE_PFLICHT[art]
        erlaubt = pflicht | MASSE_OPTIONAL.get(art, set())
        assert pflicht <= set(masse), f"{tid}: masse unvollständig, fehlt {sorted(pflicht - set(masse))}"
        assert set(masse) <= erlaubt, f"{tid}: unbekannte Maße {sorted(set(masse) - erlaubt)}"
        if art in KLEINTEILE:
            assert all(isinstance(masse[k], str) and masse[k] for k in pflicht), f"{tid}: typ/norm/groesse als Text"
            continue
        for key, wert in masse.items():
            if key == "variante":
                continue
            assert isinstance(wert, (int, float)) and not isinstance(wert, bool), f"{tid}: {key} keine Zahl"
            assert wert > 0, f"{tid}: {key} muss > 0 sein"
        if art in ("rohr", "vierkantrohr", "rechteckrohr"):
            innen = min(masse.get(k, math.inf) for k in ("d", "a", "b", "h"))
            assert 2 * masse["s"] < innen, f"{tid}: Wand zu dick"
        if art == "winkel":
            assert masse["s"] < min(masse["a"], masse["b"])
        if art == "u_profil":
            assert 2 * masse["t"] < masse["h"] and masse["s"] < masse["b"]


def test_nutprofil_masse():
    for t in (t for t in TEILE if t["art"] == "nutprofil"):
        m, tid = t["masse"], t["id"]
        assert m["raster"] in (20, 30, 40, 45), f"{tid}: Raster {m['raster']}"
        assert m["nut"] in (5, 6, 8, 10), f"{tid}: Nut {m['nut']}"
        assert m["variante"] in ("leicht", "schwer"), f"{tid}: variante leicht/schwer"
        assert ("a" in m) == ("b" in m), f"{tid}: a und b nur gemeinsam"
        a, b = m.get("a", m["raster"]), m.get("b", m["raster"])
        assert a % m["raster"] == 0 and b % m["raster"] == 0, f"{tid}: a, b Vielfache des Rasters"
        assert "kg_je_m" in t, f"{tid}: Nutprofile brauchen kg_je_m (Herstellerangabe)"
        # Plausibilität: Füllgrad der Hüllfläche bei Systemprofilen etwa 25 … 60 %
        fuellgrad = t["kg_je_m"] / (a * b * MAT[t["material"]]["dichte"] * 1e-3)
        assert 0.25 <= fuellgrad <= 0.6, f"{tid}: Füllgrad {fuellgrad:.2f} unplausibel"


def test_verbindungselemente_passen_zu_bd_warehouse():
    for t in (t for t in TEILE if t["art"] in KLEINTEILE):
        m, tid = t["masse"], t["id"]
        klassen = BD_WAREHOUSE[t["art"]]
        assert m["typ"] in klassen, f"{tid}: Klasse {m['typ']!r} passt nicht zu art {t['art']}"
        assert m["norm"] in klassen[m["typ"]], f"{tid}: {m['typ']} kennt Norm {m['norm']!r} nicht"
        if t["art"] == "scheibe":
            assert re.fullmatch(r"M\d+(\.\d+)?", m["groesse"]), f"{tid}: Scheiben ohne Steigung, z. B. 'M8'"
        else:
            nenn, _, steigung = m["groesse"].partition("-")
            assert REGELGEWINDE.get(nenn) == steigung, f"{tid}: Größe {m['groesse']!r} nicht im Format 'M8-1.25'"
        assert "je_stueck" in t.get("preis", {}), f"{tid}: Kleinteile mit Stückpreis"


def test_platten_format():
    for t in TEILE:
        if t["art"] != "platte":
            assert "platte" not in t, f"{t['id']}: Feld platte nur bei art platte"
            continue
        fmt = t.get("platte")
        assert isinstance(fmt, list) and len(fmt) == 2, f"{t['id']}: platte als [b, h]"
        assert all(isinstance(x, (int, float)) and x > 0 for x in fmt)
        assert "stangenlaenge" not in t, f"{t['id']}: Platten ohne stangenlaenge"
        assert "je_m2" in t.get("preis", {}), f"{t['id']}: Platten mit Preis je m²"


def test_stangenware():
    for t in (t for t in TEILE if t["art"] in STANGENWARE):
        assert isinstance(t.get("stangenlaenge"), int) and 1000 <= t["stangenlaenge"] <= 13000, \
            f"{t['id']}: stangenlaenge in mm"
        assert "je_m" in t.get("preis", {}), f"{t['id']}: Stangenware mit Preis je m"


def test_preise():
    for t in TEILE:
        preis = t.get("preis")
        if preis is None:
            continue
        betraege = {k: v for k, v in preis.items() if k in ("je_m", "je_m2", "je_stueck")}
        assert len(betraege) == 1, f"{t['id']}: genau eine Preisangabe je_m, je_m2 oder je_stueck"
        assert set(preis) <= {"je_m", "je_m2", "je_stueck", "quelle", "stand"}
        for wert in betraege.values():
            assert isinstance(wert, (int, float)) and wert > 0, f"{t['id']}: Preis muss > 0 sein"
        assert preis.get("quelle"), f"{t['id']}: preis.quelle fehlt"
        assert STAND.match(preis.get("stand", "")), f"{t['id']}: preis.stand als JJJJ-MM"


def _fmt(v: float) -> str:
    return (str(int(v)) if v == int(v) else str(v)).replace(".", ",")


def test_namen_deutsch():
    for t in TEILE:
        name, tid = t["name"], t["id"]
        assert not re.search(r"\d\s*[xX]\s*\d", name), f"{tid}: im Namen „ד statt x: {name!r}"
        if t["art"] in KLEINTEILE:
            continue
        assert not re.search(r"\d\.\d", name), f"{tid}: deutsches Komma im Namen: {name!r}"
        for key, wert in t["masse"].items():
            if key in ("raster", "nut", "variante", "r") or (t["art"] == "u_profil" and key != "h"):
                continue
            ganz = _fmt(wert)
            mit_null = f"{wert:.1f}".replace(".", ",")
            assert ganz in name or mit_null in name, f"{tid}: Maß {key}={wert} fehlt im Namen {name!r}"


# ---------------------------------------------------------------- Gewicht gegen Querschnitt

def _hohl(b: float, h: float, s: float, r: float | None) -> float:
    """Fläche eines Hohlprofils mit Außenradius r (Standard nach KATALOG.md) und Innenradius r - s."""
    ro = r if r is not None else (2 * s if s <= 6 else 2.5 * s)
    ri = max(ro - s, 0.0)
    return 2 * s * (b + h - 2 * s) - (4 - math.pi) * (ro ** 2 - ri ** 2)


def querschnitt_mm2(art: str, m: dict) -> float:
    if art == "rohr":
        return math.pi * m["s"] * (m["d"] - m["s"])
    if art == "vierkantrohr":
        return _hohl(m["a"], m["a"], m["s"], m.get("r"))
    if art == "rechteckrohr":
        return _hohl(m["b"], m["h"], m["s"], m.get("r"))
    if art == "flach":
        return m["b"] * m["s"]
    if art == "rund":
        return math.pi / 4 * m["d"] ** 2
    if art == "vierkant":
        return m["a"] ** 2
    if art == "winkel":
        flaeche = m["s"] * (m["a"] + m["b"] - m["s"])
        if "r" in m:  # Wurzelradius r1 füllt Material an, Kantenradius r2 = r1/2 nimmt es an zwei Kanten weg
            flaeche += (1 - math.pi / 4) * (m["r"] ** 2 - 2 * (m["r"] / 2) ** 2)
        return flaeche
    if art == "u_profil":
        return 2 * m["b"] * m["t"] + (m["h"] - 2 * m["t"]) * m["s"]
    raise KeyError(art)


GEPRUEFT = ("rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil")


@pytest.mark.parametrize("teil", [t for t in TEILE if t["art"] in GEPRUEFT and "kg_je_m" in t],
                         ids=lambda t: t["id"])
def test_kg_je_m_passt_zum_querschnitt(teil):
    dichte = MAT[teil["material"]]["dichte"]
    berechnet = querschnitt_mm2(teil["art"], teil["masse"]) * dichte * 1e-3
    abweichung = abs(teil["kg_je_m"] - berechnet) / berechnet
    assert abweichung <= TOLERANZ_KG, \
        f"{teil['id']}: kg_je_m {teil['kg_je_m']} vs. berechnet {berechnet:.3f} ({abweichung:.1%})"


@pytest.mark.parametrize("teil_id, kg", [
    ("rohr-en10220-42.4x2.0", 1.99),         # DIN EN 10220
    ("rohr-en10220-42.4x2.6", 2.55),
    ("vierkantrohr-en10219-40x40x3", 3.30),  # DIN EN 10219-2
    ("vierkantrohr-en10219-100x100x4", 11.7),
    ("rechteckrohr-en10219-60x40x3", 4.25),
    ("flach-en10058-40x5", 1.57),
    ("rund-en10060-10", 0.617),
    ("winkel-en10056-40x40x4", 2.42),        # EN 10056-1
    ("winkel-en10056-60x40x5", 3.76),
    ("upn-100", 10.6),                       # DIN 1026-1
    ("nutprofil-r40-n8-40x40-leicht", 1.74),
])
def test_stichproben_tabellenwerte(teil_id, kg):
    teil = next((t for t in TEILE if t["id"] == teil_id), None)
    assert teil is not None, f"{teil_id} fehlt im Katalog"
    assert teil["kg_je_m"] == pytest.approx(kg, abs=0.006)


def test_vertragsbeispiele_vorhanden():
    """Die ids aus KATALOG.md, PLAN-PHASE2.md und den Protokoll-Testdateien gibt es wirklich."""
    ids = set(_ids(TEILE))
    for tid in ("rohr-en10220-42.4x2.0", "vierkantrohr-en10219-40x40x3", "platte-multiplex-birke-18",
                "schraube-iso4762-m8"):
        assert tid in ids, f"{tid} fehlt"
    assert "multiplex-birke" in MAT and "stahl-s235" in MAT
