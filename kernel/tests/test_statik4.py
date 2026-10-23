"""Statik Stufe 4 (PLAN-STATIK.md, „Stand Stufe 4“): CalculiX für Kontakt, Plastizität, Traglast und Beulen.

Bausteine (ohne CalculiX): Einrichtung und Meldung ohne Platte, Deck (Orientierung, Flächen), Ergebnisleser,
Protokoll (STATICS mit Stufe 4, STATICS_FIELD mit Zusatzwerten), Urteile, Klemmschrauben, model.py-API.

Nachweise (mit CalculiX, sonst übersprungen), gegen Handrechnung bzw. Literatur:

- S4 linear gleich S3 (Wandhalter PETG stehend gedruckt, quer zur Schicht weicher): Orientierung und Spannungen;
- Reibschluss: Block, mit 1000 N geklemmt, auf starrer Platte, Querkraft steigt: Rutschgrenze μ · F_k;
- Kragbalken S235 ideal plastisch: Traglast gegen M_pl = Rp0,2 · W_pl, Fließgelenk an der Einspannung, bleibende
  Verformung nach Entlasten;
- Hertz: Kugel R 20 auf ebenem Block (PLA), Druck p0 = 3 F / (2 π a²) und Radius a = (3 F R / (4 E*))^(1/3);
- Beulen: Kragstütze 10 × 10 × 300 mm, F_k = π² E I / (4 L²).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from kevcad_kernel.protocol import (
    STATIK_FELD_ZUSATZ,
    check_statics_feld,
    check_statics_message,
    pack_statics,
    pack_statics_feld,
    statik_beispiel_feld_s4,
    statik_beispiel_s4,
    statik_kurz,
    unpack_statics_feld,
)
from kevcad_kernel.statik.ccx import installation

PROZESS = [sys.executable, "-m", "kevcad_kernel.statik.ccx.prozess"]
CCX = installation.finde()
mit_ccx = pytest.mark.skipif(not CCX["ok"], reason=f"CalculiX fehlt: {CCX.get('meldung')}")


@pytest.fixture(autouse=True)
def eigener_speicher(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_FESTKOERPER_CACHE", str(tmp_path / "fem-cache"))


def _brep(form, pfad: Path) -> str:
    from OCP.BRepTools import BRepTools

    BRepTools.Write_s(form.wrapped, str(pfad))
    return str(pfad)


def _ebene(pfad: Path, z: float, a: float = 1000.0) -> str:
    np.savez(pfad, pos=np.array([[-a, -a, z], [a, -a, z], [a, a, z], [-a, a, z]], float),
             tri=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64))
    return str(pfad)


def _wand_x(pfad: Path, x: float, a: float = 1000.0) -> str:
    np.savez(pfad, pos=np.array([[x, -a, -a], [x, a, -a], [x, a, a], [x, -a, a]], float),
             tri=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64))
    return str(pfad)


STAHL = {"id": "stahl-s235", "name": "Stahl S235", "E": 210000.0, "nu": 0.3, "E_z": None, "f": 235.0, "q": None,
         "gruppe": "Stahl", "streckgrenze": 235.0, "zug": 360.0}
PLA = {"id": "pla", "name": "PLA", "E": 2580.0, "nu": 0.36, "E_z": None, "f": 35.0, "q": 0.5, "gruppe": "Kunststoff",
       "streckgrenze": None, "zug": 35.0}


def _teil(name: str, brep: str, w: dict, volumen: float, bmin, bmax, nachbarn: dict, faelle: list, **kw) -> dict:
    return {"id": 0, "name": name, "brep": brep, "schluessel_teil": name + json.dumps(kw.get("h_mm")),
            "volumen": volumen, "masse_kg": 0.0, "werkstoff": w, "druckteil": False, "schicht": None,
            "ausrichtungen": {}, "bmin": list(bmin), "bmax": list(bmax), "nachbarn": nachbarn, "fliess": None,
            "verbindungen": {}, "koerper": {}, "klemmungen": [], "faelle": faelle, **kw}


def _rechne(tmp: Path, T: dict, optionen: dict) -> tuple[dict, float]:
    auftrag = {"version": 1, "fein": False, "verfahren": "ccx", "teile": [T], "optionen": optionen}
    a = tmp / "auftrag.json"
    a.write_text(json.dumps(auftrag), encoding="utf-8")
    t0 = time.perf_counter()
    r = subprocess.run(PROZESS + [str(a), str(tmp / "ergebnis.json")], capture_output=True, text=True, timeout=1800)
    dauer = time.perf_counter() - t0
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads((tmp / "ergebnis.json").read_text())
    f = out["faelle"][0]
    assert f["stand"] == "done", f
    return f, dauer


# ---------------------------------------------------------------------------------------------------------------------
# Bausteine


def test_einrichtung_ohne_platte_meldet_klar(monkeypatch, tmp_path):
    monkeypatch.delenv("KEVCAD_CCX", raising=False)
    monkeypatch.setenv("KEVCAD_CALCULIX_DIR", "/Volumes/Kev CAD Probe nicht da/#PROGRAMME_DO-NOT-DELETE#/calculix")
    f = installation.finde()
    assert not f["ok"] and not f["einrichtbar"]
    assert f["meldung"] == "CalculiX nicht verfügbar (externe Platte Kev CAD Probe nicht da nicht angeschlossen)"
    # einrichten legt nie einen Ordner unter /Volumes an und scheitert nicht
    assert installation.sicherstellen()["ok"] is False
    assert not Path("/Volumes/Kev CAD Probe nicht da").exists()
    # Standard ist die externe Platte, einstellbar über die Einstellung
    monkeypatch.delenv("KEVCAD_CALCULIX_DIR")
    monkeypatch.setattr(installation, "EINSTELLUNG", tmp_path / "calculix.json")
    assert installation.ordner() == installation.STANDARD
    assert "UPVIS ULTRA" in str(installation.STANDARD) and "#PROGRAMME_DO-NOT-DELETE#" in str(installation.STANDARD)
    (tmp_path / "calculix.json").write_text(json.dumps({"ordner": str(tmp_path / "cx")}))
    assert installation.ordner() == tmp_path / "cx"
    f = installation.finde()
    assert not f["ok"] and f["einrichtbar"] and "noch nicht eingerichtet" in f["meldung"]
    # Programm direkt
    monkeypatch.setenv("KEVCAD_CCX", str(tmp_path / "fehlt"))
    assert not installation.finde()["ok"]


@mit_ccx
def test_installation_probe_und_liesmich():
    f = installation.finde()
    assert installation.version(f["ccx"]).startswith("2.")
    assert installation.probe(f["ccx"])["ok"]
    if installation.ordner() == installation.STANDARD:
        text = (installation.STANDARD / "LIESMICH.txt").read_text(encoding="utf-8")
        assert "NICHT LÖSCHEN" in text and "GPL" in text and "kevcad_kernel.statik.ccx.installation" in text


def test_deck_orientierung_flaechen_und_eingabe(tmp_path):
    from kevcad_kernel.statik.ccx.deck import Deck, Koerper, Kontakt, Schritt

    kn = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], float)
    mitten = np.array([(kn[a] + kn[b]) / 2 for a, b in ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))])
    alle = np.vstack([kn, mitten])
    el = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]])
    links = el[:, [1, 0, 2, 3, 4, 6, 5, 8, 7, 9]]  # negativ orientiert
    k = Koerper("A", alle, links.copy(), {"E": 1000.0, "nu": 0.3})
    assert np.array_equal(k.elemente, el)  # zurückgedreht, Mitten mitgetauscht
    # Fläche ohne Ecke 4 ist S1, ohne Ecke 1 ist S3
    assert k.flaechen(np.array([0, 0]), np.array([[0, 1, 2], [1, 2, 3]])).tolist() == [1, 3]
    d = Deck()
    d.add(k)
    d.add(Koerper("B", alle + [0, 0, 20], el.copy(), {"E": 1000.0, "nu": 0.3, "plastisch": [(10, 0), (12, 0.1)]}))
    d.fest.append(d.global_knoten(0, np.array([0, 1, 2])))
    d.fest_richtung.append((d.global_knoten(1, np.array([3])), (3,)))
    d.federn.append((d.global_knoten(1, np.arange(10)), 0.01))
    d.kontakte.append(Kontakt("C0", (0, np.array([0]), np.array([3])), (1, np.array([0]), np.array([1])), 0.3,
                              2000.0, 40.0))
    F = np.zeros((d.knotenzahl, 3))
    F[13, 2] = -5.0
    d.schritte += [Schritt("last", F), Schritt("beulen", F, art="beulen")]
    d.ausgabe_knoten = d.global_knoten(0, np.arange(4))
    d.schreibe(str(tmp_path / "m.inp"))
    text = (tmp_path / "m.inp").read_text()
    for teil in ("*ELEMENT, TYPE=C3D10, ELSET=K1", "*PLASTIC", "*CONTACT PAIR, INTERACTION=C0I, TYPE=SURFACE TO "
                 "SURFACE", "*FRICTION\n0.3, 40", "*ELEMENT, TYPE=SPRING1", "*BUCKLE", "14, 3, -5",
                 "*NODE FILE, FREQUENCY=1, NSET=AUSGABE", "FEST, 1, 3", "14, 3, 3"):
        assert teil in text, teil


def test_frd_leser(tmp_path):
    from kevcad_kernel.statik.ccx import frd

    p = tmp_path / "x.frd"
    p.write_text("    1C\n    2C                             3                                     1\n"
                 "  100CL  101 1.00000E+00           3                     0    1           1\n"
                 " -4  DISP        4    1\n -5  D1          1    2    1    0\n"
                 " -1         1 1.00000E-01-2.00000E-01 3.00000E-01\n"
                 " -1         3 0.00000E+00 0.00000E+00-1.50000E+00\n -3\n"
                 "  100CL  102 2.00000E+00           3                     0    2           1\n"
                 " -4  PE          1    1\n -5  PE          1    1    0    0\n -1         2 4.00000E-03\n -3\n"
                 " -4  DISP        4    1\n -1         1 1.0", encoding="latin-1")  # letzter Block abgebrochen
    ink = frd.lies_frd(str(p))
    assert [i["zeit"] for i in ink] == [1.0, 2.0] and list(ink[1]["bloecke"]) == ["PE"]
    U = frd.feld(ink[0], "DISP", 3, 3)
    assert U[0].tolist() == pytest.approx([0.1, -0.2, 0.3]) and U[2, 2] == pytest.approx(-1.5) and not U[1].any()
    assert frd.feld(ink[1], "PE", 3, 1)[1, 0] == pytest.approx(0.004)
    dat = tmp_path / "x.dat"
    dat.write_text("\n     B U C K L I N G   F A C T O R   O U T P U T\n\n MODE NO       BUCKLING\n"
                   "                    FACTOR\n\n      1   0.4803261E+01\n      2   0.4803415E+01\n\n")
    assert frd.beulfaktoren(str(dat)) == pytest.approx([4.803261, 4.803415])


def test_fliesskurven():
    from kevcad_kernel.statik.ccx.auftrag import fliesskurve

    s = fliesskurve({"E": 210000.0, "streckgrenze": 235.0, "zug": 360.0}, "Stahl", False, True)
    assert s["kurve"][0] == (235.0, 0.0) and s["kurve"][1][0] == 360.0 and s["grenzdehnung"] == 0.05
    assert fliesskurve({"E": 210000.0, "streckgrenze": 235.0, "zug": 360.0}, "Stahl", False, True,
                       verfestigung=False)["kurve"] == [(235.0, 0.0), (235.0, 1.0)]
    d = fliesskurve({"E": 2580.0, "f": 35.0, "zug": 35.0, "q": 0.5}, "", True, False)
    assert d["fy"] == pytest.approx(17.5) and "Drucklage unbekannt" in d["modell"]
    assert fliesskurve({"E": 2580.0, "f": 35.0, "zug": 35.0, "q": 0.5}, "", True, True)["fy"] == 35.0
    assert fliesskurve({"E": 11000.0, "f": 40.0}, "Holz", False, True) is None  # spröde: keine Plastizität


def test_protokoll_s4_und_zusatzfeld():
    b = statik_beispiel_s4()
    head = pack_statics(b, run=12)
    assert not check_statics_message(head)
    e = next(x for x in head["szenarien"] if x["name"] == "Haken 2 kg (Kontakt)")
    t = e["festkoerper"]["teile"][0]
    assert t["verfahren"] == "ccx" and t["traglast"]["faktor"] == 6.2 and t["kontakt"]["paare"][0]["mit"] == "Wand"
    kurz = statik_kurz(b)
    assert next(x for x in kurz["szenarien"] if x["name"] == "Haken 2 kg (Kontakt)")["festkoerper"]["teile"][0][
        "ampel"] == "gelb"
    kopf, felder = statik_beispiel_feld_s4()
    h, p = pack_statics_feld(kopf, felder, run=12)
    assert not check_statics_feld(h, p) and h["zusatz"] == list(STATIK_FELD_ZUSATZ) and h["verfahren"] == "ccx"
    u = unpack_statics_feld(h, p)
    assert float(u["kontaktdruck"].max()) == pytest.approx(6.5) and float(u["plast_dehnung"].max()) == pytest.approx(
        0.004)
    assert check_statics_feld(h, p + b"\0\0\0\0")  # Länge stimmt nicht
    assert check_statics_feld({**h, "zusatz": ["unbekannt", "plast_dehnung", "klaffen", "schlupf"]}, p)
    # ohne Zusatz unverändert wie Stufe 3
    h3, p3 = pack_statics_feld({k: v for k, v in kopf.items() if k != "zusatz"},
                               {k: felder[k] for k in ("punkte", "dreiecke", "ausnutzung", "spannung", "verschiebung")},
                               run=12)
    assert "zusatz" not in h3 and len(p3) == len(p) - 4 * 4 * len(felder["punkte"])


def test_urteil_s4_ampel_und_texte():
    from kevcad_kernel.statik.ccx.urteil import loesung, teil_kurz, zeilen
    from kevcad_kernel.statik.festkoerper.urteil import urteil_fuer

    r = {"stand": "done", "teil": "Halter (Druck)", "ziel": 4.0, "sicherheit": 6.0, "sicherheit_last": 1.9,
         "spannung_max": 17.0, "kriterium": "mises", "ort": [1, 2, 3], "q": 0.5, "verfahren": "ccx",
         "plastisch": {"dehnung_max": 0.006, "bleibend_mm": 0.2, "fliesst": True, "grenzdehnung": 0.02,
                       "modell": "Druckteil …"},
         "traglast": {"faktor": 6.0, "kriterium": "dehnung", "text": "Grenzdehnung", "lastfaktor_max": 12.0,
                      "erreicht": 6.1},
         "kontakt": {"paare": [{"mit": "Gruppe/Rohr", "druck_max": 12.0, "anteil_traegt": 0.4, "klaffen_max_mm": 0.05,
                                "schlupf_max_mm": 0.0, "reibwert": 0.3}],
                     "klemmungen": [{"schraube": "Sterngriff", "kraft_n": 720.0, "quelle": "handfest"}]}}
    t = teil_kurz(r)
    assert t["ampel"] == "gelb"  # Traglast 6 > Ziel 4, aber es fließt schon unter der Last
    assert "Traglast beim 6-Fachen der Last (Grenzdehnung)" in t["text"] and "klafft bis 0,05 mm" in t["text"]
    assert any("Klemmkraft 720 N" in z for z in zeilen(t))
    r2 = {**r, "rutscht": True, "plastisch": None}
    t2 = teil_kurz(r2)
    assert t2["ampel"] == "rot" and "rutscht" in t2["text"] and loesung(t2).startswith("Klemmkraft erhöhen")
    u = urteil_fuer(t2)
    assert u["art"] == "festkoerper" and u["loesung"].startswith("Klemmkraft erhöhen")


def test_model_py_kontakt_und_festigkeit():
    import kevcad
    import kevcad.statik as st

    gesehen = []
    alt = kevcad._hooks.get("pruefung")
    kevcad._hooks["pruefung"] = lambda art, d: gesehen.append((art, d))
    try:
        st.kontakt("Halter", "Rohr", reibwert=0.25, klemmkraft=500)
        st.festigkeit("Halter", plastisch=True)
        with pytest.raises(ValueError):
            st.kontakt("Halter", None)
        with pytest.raises(ValueError):
            st.kontakt("Halter", "Rohr", reibwert=-1)
    finally:
        if alt is None:
            kevcad._hooks.pop("pruefung", None)
        else:
            kevcad._hooks["pruefung"] = alt
    k = gesehen[0][1]
    assert k["was"] == "kontakt" and k["teile"] == ["Halter"] and k["gegen"] == ["Rohr"] and k["klemmkraft"] == 500
    f = gesehen[1][1]
    assert f["was"] == "festigkeit" and f["plastisch"] and f["kontakt"] and f["traglast"] is None


# ---------------------------------------------------------------------------------------------------------------------
# Nachweise mit CalculiX


@mit_ccx
def test_reibschluss_rutschgrenze(tmp_path):
    """Block 20 × 20 × 10 mm (Stahl) auf starrer Platte, Klemmkraft F_k = 1000 N über Scheibe und Mutter unter der
    Platte, Querkraft 100 N in halber Höhe: Rutschen bei λ = μ F_k / F_q = 3,0 (μ = 0,3)."""
    from build123d import Box, Pos

    blk = _brep(Pos(0, 0, 5) * Box(20, 20, 10), tmp_path / "block.brep")
    platte = _brep(Pos(0, 0, -5) * Box(40, 40, 10), tmp_path / "platte.brep")
    np.savez(tmp_path / "scheibe.npz", pos=np.array([[-6, -6, 10], [6, -6, 10], [6, 6, 10], [-6, 6, 10]], float),
             tri=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64))
    mu, Fk, Fq = 0.3, 1000.0, 100.0
    T = _teil("Block", blk, STAHL, 4000.0, (-10, -10, 0), (10, 10, 10),
              {"Platte": {"datei": _ebene(tmp_path / "platte.npz", 0.0, 20), "tol": 0.3, "schluessel": "p"},
               "Scheibe": {"datei": str(tmp_path / "scheibe.npz"), "tol": 0.3, "schluessel": "s"},
               "Mutter": {"datei": _ebene(tmp_path / "mutter.npz", -10.0, 6), "tol": 0.3, "schluessel": "m"}},
              [{"id": "0.0", "szenario": "Schub", "teil": "Block", "ziel": 2.0, "lager": ["Platte"],
                "lasten": [{"kraft": [Fq, 0, 0], "moment": None, "punkt": [-10, 0, 5], "quelle": "Querkraft"}],
                "feld": [0, 0, 0], "schluessel": "reib"}], h_mm=3.0,
              verbindungen={"Platte": {"art": "kontakt", "quelle": "Test", "reibwert": mu, "reibwert_quelle": "Test",
                                       "spiel": None}},
              koerper={"Platte": {"brep": platte, "rolle": "lager", "werkstoff": None, "fliess": None,
                                  "box": [[-20, -20, -10], [20, 20, 0]], "schluessel": "platte", "groesse": 40.0}},
              klemmungen=[{"schraube": "Schraube", "kopf": ["Scheibe"], "mutter": ["Mutter"], "kraft": Fk, "d": 6.0,
                           "quelle": "Test"}])
    r, dauer = _rechne(tmp_path, T, {"kontakt": True, "plastisch": False, "traglast": True, "beulen": False})
    p = r["kontakt"]["paare"][0]
    assert p["kraft_n"] == pytest.approx(Fk, rel=0.25)  # Knotenflächen grob, die Summe genau prüft die Traglast
    assert r["kontakt"]["klemmungen"][0]["achse"] == pytest.approx([0, 0, -1], abs=1e-6)
    tr = r["traglast"]
    assert tr["kriterium"] == "rutschen"
    assert tr["faktor"] == pytest.approx(mu * Fk / Fq, rel=0.02)
    assert not r["rutscht"] and r["sicherheit"] == tr["faktor"]
    print(f"Reibschluss: Rutschgrenze {tr['faktor']:.3f} (Hand {mu * Fk / Fq:.3f}), {r['netz']}, {dauer:.1f} s")


@mit_ccx
def test_kragbalken_plastisch_traglast_und_fliessgelenk(tmp_path):
    """Kragbalken S235 10 × 10 mm, 100 mm bis zur Last, ideal plastisch, F = 500 N (über der Fließlast 391,7 N):
    fließt an der Einspannung, bleibt nach Entlasten verbogen; Traglast gegen F_pl = Rp0,2 · b h² / 4 / L = 587,5 N."""
    from build123d import Box, Pos

    from kevcad_kernel.statik.ccx.auftrag import fliesskurve

    L, F = 100.0, 500.0
    brep = _brep(Pos(L / 2, 0, 0) * Box(L, 10, 10), tmp_path / "balken.brep")
    T = _teil("Balken", brep, STAHL, L * 100, (0, -5, -5), (L, 5, 5),
              {"Wand": {"datei": _wand_x(tmp_path / "wand.npz", 0.0), "tol": 0.3, "schluessel": "w"}},
              [{"id": "0.0", "szenario": "Last", "teil": "Balken", "ziel": 2.0, "lager": ["Wand"],
                "lasten": [{"kraft": [0, 0, -F], "moment": None, "punkt": [L, 0, 0], "quelle": "Last"}],
                "feld": [0, 0, 0], "schluessel": "plast"}], h_mm=3.0,
              fliess=fliesskurve(STAHL, "Stahl", False, True, verfestigung=False))
    r, dauer = _rechne(tmp_path, T, {"kontakt": False, "plastisch": True, "traglast": True, "beulen": False})
    pl = r["plastisch"]
    assert pl["fliesst"] and pl["dehnung_max"] > 1e-4 and pl["ort"][0] < 3.5  # Fließgelenk an der Einspannung
    assert pl["bleibend_mm"] > 0.01  # bleibt verbogen
    F_pl = 235.0 * 10 * 10 ** 2 / 4 / L
    tr = r["traglast"]
    assert tr["kriterium"] in ("dehnung", "kollaps")
    verhaeltnis = tr["faktor"] * F / F_pl
    # Tetraeder zweiter Ordnung versteifen voll plastisch, die starre Einspannung behindert die Querdehnung: einige
    # Prozent über der Balkenrechnung (PLAN-STATIK.md, Stand Stufe 4)
    assert 1.0 <= verhaeltnis <= 1.15, verhaeltnis
    print(f"Kragbalken: Traglast {tr['faktor'] * F:.1f} N gegen M_pl/L {F_pl:.1f} N ({verhaeltnis - 1:+.1%}), "
          f"plastische Dehnung bei 500 N {pl['dehnung_max']:.4f} bei {pl['ort']}, bleibend {pl['bleibend_mm']:.3f} mm, "
          f"{dauer:.1f} s")


@mit_ccx
def test_beulen_kragstuetze_euler(tmp_path):
    """Stütze 10 × 10 × 300 mm, unten eingespannt, 1000 N Druck oben: F_k = π² E I / (4 L²) = 4 798 N."""
    from build123d import Box, Pos

    L = 300.0
    brep = _brep(Pos(0, 0, L / 2) * Box(10, 10, L), tmp_path / "stuetze.brep")
    T = _teil("Stütze", brep, STAHL, 100 * L, (-5, -5, 0), (5, 5, L),
              {"Boden": {"datei": _ebene(tmp_path / "boden.npz", 0.0), "tol": 0.3, "schluessel": "b"}},
              [{"id": "0.0", "szenario": "Druck", "teil": "Stütze", "ziel": 2.0, "lager": ["Boden"],
                "lasten": [{"kraft": [0, 0, -1000.0], "moment": None, "punkt": [0, 0, L], "quelle": "Last"}],
                "feld": [0, 0, 0], "schluessel": "beulen"}], h_mm=5.0)
    r, dauer = _rechne(tmp_path, T, {"kontakt": False, "plastisch": False, "traglast": False, "beulen": True})
    F_k = math.pi ** 2 * 210000.0 * (10 ** 4 / 12) / (4 * L ** 2)
    assert r["beulen"]["faktor"] * 1000.0 == pytest.approx(F_k, rel=0.02)
    assert r["sicherheit"] == pytest.approx(r["beulen"]["faktor"])  # Beulen maßgebend (Spannung 10 N/mm²)
    print(f"Beulen: F_k {r['beulen']['faktor'] * 1000:.0f} N gegen Euler {F_k:.0f} N, {dauer:.1f} s")


def _hertz_annaeherung(F: float, R: float, E: float, nu: float, h: float) -> tuple[float, float, float, float]:
    """Hertz Kugel auf Ebene (gleiche Werkstoffe): (a, p0, δ = a² / R, Annäherung zweier Punkte auf der Achse je in
    der Tiefe h unter der Berührung, aus der Spannung auf der Achse im Halbraum, Johnson 1985, Gl. 3.45)."""
    from scipy.integrate import quad

    Es = E / (2 * (1 - nu ** 2))
    a = (3 * F * R / (4 * Es)) ** (1 / 3)
    p0 = 3 * F / (2 * math.pi * a ** 2)

    def eps_z(z: float) -> float:
        zz = z / a
        sz = -p0 / (1 + zz ** 2)
        sr = p0 * (-(1 + nu) * (1 - zz * math.atan(1 / zz)) + 0.5 / (1 + zz ** 2)) if zz > 0 else -p0 * (1 + 2 * nu) / 2
        return (sz - 2 * nu * sr) / E

    halb = -quad(eps_z, 0.0, h, limit=200)[0]
    return a, p0, a ** 2 / R, 2 * halb


def test_hertz_handrechnung_halbraum():
    """Die Annäherung zweier tief liegender Punkte geht gegen δ = a² / R (Halbraum)."""
    a, p0, delta, weit = _hertz_annaeherung(1000.0, 20.0, 2580.0, 0.36, 1e5)
    assert a == pytest.approx(2.163, abs=1e-3) and p0 == pytest.approx(102.05, abs=0.05)
    assert weit == pytest.approx(delta, rel=0.01)
    assert _hertz_annaeherung(1000.0, 20.0, 2580.0, 0.36, 2 * a)[3] < delta


@mit_ccx
def test_hertz_kugel_auf_platte(tmp_path, monkeypatch):
    """Kugelkappe R 20 mm (6 mm hoch) mit 1000 N auf einen Block 30 × 30 × 10 mm, beide PLA, reibungsfrei, Netz an der
    Berührung örtlich verfeinert: Druckverlauf p0 √(1 − r²/a²) gegen Hertz (p0 und a aus einer Ausgleichsgeraden von
    p² über r²), Kraft aus dem Druck, Annäherung zweier Punkte auf der Achse in der Tiefe 2 a."""
    import shutil

    from build123d import Align, Box, Pos, Sphere

    from kevcad_kernel.pruefung.kollision import vernetzen
    from kevcad_kernel.statik.ccx import frd

    R, HK, F, hf = 20.0, 6.0, 1000.0, float(os.environ.get("KEVCAD_HERTZ_H", "0.7"))
    E, nu = PLA["E"], PLA["nu"]
    a_h, p0_h, delta_h, _ = _hertz_annaeherung(F, R, E, nu, 1.0)
    kugel = Pos(0, 0, R) * Sphere(R) - Pos(0, 0, HK) * Box(3 * R, 3 * R, 2 * R,
                                                           align=(Align.CENTER, Align.CENTER, Align.MIN))
    pos, _, tri = vernetzen(kugel.wrapped, 0.02)
    np.savez(tmp_path / "kugel.npz", pos=np.asarray(pos, float), tri=np.asarray(tri, dtype=np.int64))
    ver = [{"punkt": [0, 0, 0], "radius": 2.0 * a_h, "h": hf, "aussen": 3.5 * a_h}]
    T = _teil("Block", _brep(Pos(0, 0, -5) * Box(30, 30, 10), tmp_path / "block.brep"), PLA, 9000.0,
              (-15, -15, -10), (15, 15, 0),
              {"Boden": {"datei": _ebene(tmp_path / "boden.npz", -10.0), "tol": 0.3, "schluessel": "b"},
               "Kugel": {"datei": str(tmp_path / "kugel.npz"), "tol": 0.3, "schluessel": "k"}},
              [{"id": "0.0", "szenario": "Hertz", "teil": "Block", "ziel": 2.0, "lager": ["Boden"],
                "lasten": [{"kraft": [0, 0, -F], "moment": None, "punkt": [0, 0, HK], "kontakt_mit": "Kugel",
                            "quelle": "Kugel"}], "feld": [0, 0, 0], "schluessel": "hertz"}],
              h_mm=3.0, verfeinern=ver,
              verbindungen={"Kugel": {"art": "kontakt", "quelle": "Test", "reibwert": 0.0, "reibwert_quelle": "Test",
                                      "spiel": None}},
              koerper={"Kugel": {"brep": _brep(kugel, tmp_path / "kugel.brep"), "rolle": "last",
                                 "werkstoff": dict(PLA), "fliess": None, "box": [[-R, -R, -1], [R, R, HK]],
                                 "schluessel": "kugel", "groesse": 2 * R, "verfeinern": ver, "h_mm": 3.0}})
    monkeypatch.setenv("KEVCAD_CCX_BEHALTEN", "1")
    auftrag = {"version": 1, "fein": False, "verfahren": "ccx", "teile": [T],
               "optionen": {"kontakt": True, "plastisch": False, "traglast": False, "beulen": False}}
    (tmp_path / "auftrag.json").write_text(json.dumps(auftrag), encoding="utf-8")
    t0 = time.perf_counter()
    lauf = subprocess.run(PROZESS + [str(tmp_path / "auftrag.json"), str(tmp_path / "ergebnis.json")],
                          capture_output=True, text=True, timeout=1800)
    dauer = time.perf_counter() - t0
    assert lauf.returncode == 0, lauf.stderr[-2000:]
    r = json.loads((tmp_path / "ergebnis.json").read_text())["faelle"][0]
    assert r["stand"] == "done", r
    ordner = next(Path(json.loads(z)["text"].split("Arbeitsordner ", 1)[1]) for z in lauf.stdout.splitlines()
                  if "Arbeitsordner" in z)
    try:
        assert not r["rutscht"] and r["federn"][0]["anteil"] < 0.01  # die Halte-Federn tragen fast nichts
        with np.load(r["feld"]) as z:
            P, p = z["punkte"].astype(float), z["kontaktdruck"].astype(float)
        oben = np.abs(P[:, 2]) < 1e-6
        rr = np.hypot(P[:, 0], P[:, 1])
        sel = oben & (p > 0.3 * p.max())
        steigung, achse = np.polyfit(rr[sel] ** 2, p[sel] ** 2, 1)
        p0, a = math.sqrt(achse), math.sqrt(-achse / steigung)
        assert p0 == pytest.approx(p0_h, rel=0.10) and a == pytest.approx(a_h, rel=0.08)
        # Kraft aus dem Druck (Knotenflächen) gleich der Last
        assert r["kontakt"]["paare"][0]["kraft_n"] == pytest.approx(F, rel=0.08)
        # Abplattung: Annäherung zweier Punkte auf der Achse in der Tiefe 2 a gegen den Halbraum
        kn = []
        an = False
        for zeile in (ordner / "last.inp").read_text().splitlines():
            if zeile.startswith("*NODE"):
                an = True
                continue
            if an and zeile.startswith("*"):
                break
            if an:
                kn.append([float(x) for x in zeile.split(",")[1:]])
        kn = np.asarray(kn)
        ink = frd.lies_frd(str(ordner / "last.frd"), ("DISP",))
        U = frd.feld(ink[-1], "DISP", len(kn), 3)
        tiefe = 2.0 * a_h
        n_teil = int(r["netz"]["knoten"])  # Ecken des Blocks zuerst, die Kugel hinter allen Knoten des Blocks
        ausgabe = np.where(np.any(U != 0, axis=1))[0]
        block = ausgabe[ausgabe < n_teil]
        kugel_kn = ausgabe[ausgabe >= n_teil]
        ib = block[np.argmin(np.linalg.norm(kn[block] - [0, 0, -tiefe], axis=1))]
        ik = kugel_kn[np.argmin(np.linalg.norm(kn[kugel_kn] - [0, 0, tiefe], axis=1))]
        annaeherung = -float(U[ik, 2] - U[ib, 2])
        soll = 0.5 * (_hertz_annaeherung(F, R, E, nu, abs(kn[ib, 2]))[3]
                      + _hertz_annaeherung(F, R, E, nu, abs(kn[ik, 2]))[3])
    finally:
        shutil.rmtree(ordner, ignore_errors=True)
    assert annaeherung == pytest.approx(soll, rel=0.12)
    print(f"Hertz (h {hf} mm): p0 {p0:.1f} gegen {p0_h:.1f} N/mm² ({p0 / p0_h - 1:+.1%}), a {a:.3f} gegen {a_h:.3f} mm "
          f"({a / a_h - 1:+.1%}), Kraft aus dem Druck {r['kontakt']['paare'][0]['kraft_n']:.0f} N, Annäherung auf 2a "
          f"{annaeherung:.4f} gegen {soll:.4f} mm ({annaeherung / soll - 1:+.1%}), δ Hertz {delta_h:.4f} mm, "
          f"{r['netz']}, {dauer:.1f} s")
