"""Anbindung der Druckprüfung an die gemeinsame Prüfung (``kevcad_kernel.pruefung``): Prüfer „druck“.

Nach jedem Lauf (im Rechenprozess, nach RUN_DONE wie die anderen Prüfer) prüft ``pruefe`` jedes gezeigte Teil aus
``lager.druckteil(...)`` mit ``pruefe_druckteil`` für Kevins Bambu Lab P1P und gibt die Hinweise als Befunde der
gemeinsamen Prüfung zurück (Arten ``druck_<art>``, ids ``dr1``, ``dr2`` …). Ausrichtung, Begründung und Kennzahlen je
Teil stehen in ``ergebnis["druck"]`` (im CHECK-Kopf als Feld ``druck``, im Laufergebnis gekürzt, vollständig über das
MCP-Werkzeug ``druckpruefung``).

Bezugssystem: Geprüft wird die Form so, wie sie an ``lager.druckteil`` ging (darauf beziehen sich „wie modelliert“
und eine vorgegebene Ausrichtung), ohne Verschiebung. Flächennummern gelten unverändert (gleiche Form), Punkte rechnet
die Anbindung in Weltkoordinaten um, passend zum Viewer.

Schwere im Lauf (``schwere_im_lauf``): „fehler“ (sperrt den Export) nur aus harten Gründen – passt nicht in den
Bauraum des P1P samt Sperrfläche, Harzdruck, Material nur mit gehärteter Düse. Alles andere ist „warnung“ oder
„hinweis“; ein „fehler“ der Druckprüfung aus anderem Grund (etwa eine zu kleine Bohrung) wird zur Warnung.

Zwischenspeicher: je Form ohne Lage (``Koerper.form``), Drehung der Druckteil-Form, Material und Ausrichtung. Ein
unverändertes Teil wird nicht neu geprüft, auch wenn die Baugruppe verschoben wurde oder es mehrfach vorkommt.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

import numpy as np

from kevcad_kernel.pruefung import befund as bf
from kevcad_kernel.pruefung.befund import befund
from kevcad_kernel.pruefung.pruefer import PruefKontext, registriere

PRAEFIX = "druck_"
ZWISCHENSPEICHER_MAX = 512

# Befundarten der Druckprüfung → Text für die Zusammenfassung (Einzahl, Mehrzahl)
ARTEN: dict[str, tuple[str, str]] = {
    "bauraum": ("Druckteil passt nicht in den Bauraum", "Druckteile passen nicht in den Bauraum"),
    "bauraum_knapp": ("Bauraum knapp (Druck)", "Bauraum knapp (Druck)"),
    "material": ("Materialproblem (Druck)", "Materialprobleme (Druck)"),
    "auflage": ("Auflage knapp (Druck)", "Auflagen knapp (Druck)"),
    "bohrung_klein": ("Bohrung zu klein (Druck)", "Bohrungen zu klein (Druck)"),
    "bohrung_mass": ("Bohrungsmaß (Druck)", "Bohrungsmaße (Druck)"),
    "waagrechte_bohrung": ("waagrechte Bohrung (Druck)", "waagrechte Bohrungen (Druck)"),
    "stift": ("dünner Stift (Druck)", "dünne Stifte (Druck)"),
    "bruecke": ("Brücke (Druck)", "Brücken (Druck)"),
    "kragarm": ("Auskragung (Druck)", "Auskragungen (Druck)"),
    "freie_unterseite": ("freie Unterseite (Druck)", "freie Unterseiten (Druck)"),
    "gegenbohrung_unten": ("Gegenbohrung zum Bett (Druck)", "Gegenbohrungen zum Bett (Druck)"),
    "opferschicht": ("Opferschicht (Druck)", "Opferschichten (Druck)"),
    "ueberhang": ("Überhang (Druck)", "Überhänge (Druck)"),
    "rundung_unten": ("Rundung am Bett (Druck)", "Rundungen am Bett (Druck)"),
    "elefantenfuss": ("Elefantenfuß (Druck)", "Elefantenfuß (Druck)"),
    "wand": ("dünne Wand (Druck)", "dünne Wände (Druck)"),
    "verzug": ("Verzugsgefahr (Druck)", "Verzugsgefahr (Druck)"),
    "verzug_ecken": ("Verzug an Ecken (Druck)", "Verzug an Ecken (Druck)"),
    "schichtraster": ("Schichtraster (Druck)", "Schichtraster (Druck)"),
    "ausrichtung": ("Druckausrichtung ungültig", "Druckausrichtungen ungültig"),
    "fehlgeschlagen": ("Druckprüfung fehlgeschlagen", "Druckprüfungen fehlgeschlagen"),
}
for _art, _text in ARTEN.items():
    bf.ART_TEXT.setdefault(PRAEFIX + _art, _text)

# Harte Gründe: diese Befunde der Druckprüfung sind im Lauf Fehler (Export gesperrt)
HARTE_MATERIALGRUENDE = ("harzdruck", "gehaertete_duese")

_SPEICHER: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
STATISTIK = {"treffer": 0, "neu": 0}


def leeren() -> None:
    """Zwischenspeicher leeren (Tests)."""
    _SPEICHER.clear()
    STATISTIK.update(treffer=0, neu=0)


# ---------------------------------------------------------------------------------------------------------------------
# Schwere und Texte


def schwere_im_lauf(h: dict[str, Any]) -> str:
    """Schwere eines Hinweises der Druckprüfung in der gemeinsamen Prüfung (siehe Moduldoku)."""
    art, schwere = h.get("art"), h.get("schwere")
    if art == "bauraum" and schwere == "fehler":
        return "fehler"
    if art == "material" and (h.get("werte") or {}).get("grund") in HARTE_MATERIALGRUENDE:
        return "fehler"
    if schwere == "fehler":
        return "warnung"
    return str(schwere or "hinweis")


def _art_im_lauf(h: dict[str, Any], schwere: str) -> str:
    art = str(h.get("art") or "unbekannt")
    if art == "bauraum" and schwere != "fehler":
        art = "bauraum_knapp"
    return PRAEFIX + art


def _satz(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _flaechen_text(name: str, flaechen: list[int]) -> str:
    if not flaechen:
        return ""
    refs = ", ".join(f"#f{f}" for f in flaechen[:4]) + (f" und {len(flaechen) - 4} weitere" if len(flaechen) > 4
                                                        else "")
    return f" an Fläche {refs}" if len(flaechen) == 1 else f" an den Flächen {refs}"


# ---------------------------------------------------------------------------------------------------------------------
# Lage und Zwischenspeicher


def _drehung(m: Any) -> np.ndarray:
    a = np.asarray(m, dtype=np.float64).reshape(4, 4)
    return a[:3, :3]


def _gedreht(topo: Any, R: np.ndarray) -> Any:
    """Form ohne Verschiebung, nur mit der Drehung R (Lage der Druckteil-Form)."""
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    if np.allclose(R, np.eye(3), atol=1e-12):
        return topo.Located(TopLoc_Location())
    t = gp_Trsf()
    t.SetValues(*(float(R[i, j]) if j < 3 else 0.0 for i in range(3) for j in range(4)))
    return topo.Located(TopLoc_Location(t))


def _ausrichtung_schluessel(a: Any) -> Any:
    if a is None or isinstance(a, (str, int)):
        return a.strip().lower() if isinstance(a, str) else a
    trsf = getattr(getattr(a, "wrapped", None), "Transformation", None)
    if callable(trsf):
        t = trsf()
        return ("rot",) + tuple(round(t.Value(r, s), 9) for r in range(1, 4) for s in range(1, 4))
    return ("vektor",) + tuple(round(float(c), 9) for c in a)


def _ausrichtung_text(a: Any) -> str | None:
    if a is None:
        return None
    if isinstance(a, str):
        return a
    if isinstance(a, int):
        return f"Fläche {a} aufs Bett"
    if callable(getattr(getattr(a, "wrapped", None), "Transformation", None)):
        return "Drehung aus model.py"
    return "Richtung (" + "; ".join(bf.de_num(float(c), 3) for c in a) + ") aufs Bett"


def _pruefe_form(form: Any, material: str, ausrichtung: Any) -> dict[str, Any]:
    from kevcad_kernel.druck.pruefung import pruefe_druckteil

    return pruefe_druckteil(form, material=material, ausrichtung=ausrichtung)


def _ergebnis_fuer(k: Any, material: str, ausrichtung: Any, R: np.ndarray) -> tuple[dict[str, Any], bool, float]:
    """(Ergebnis der Druckprüfung in der Lage der Druckteil-Form ohne Verschiebung, aus dem Zwischenspeicher?, ms)."""
    schluessel = (k.form, tuple(round(float(x), 9) for x in R.ravel()), material, _ausrichtung_schluessel(ausrichtung))
    erg = _SPEICHER.get(schluessel)
    if erg is not None:
        _SPEICHER.move_to_end(schluessel)
        STATISTIK["treffer"] += 1
        return erg, True, 0.0
    t0 = time.perf_counter()
    erg = _pruefe_form(_gedreht(k.shape, R), material, ausrichtung)
    ms = (time.perf_counter() - t0) * 1000
    _SPEICHER[schluessel] = erg
    STATISTIK["neu"] += 1
    while len(_SPEICHER) > ZWISCHENSPEICHER_MAX:
        _SPEICHER.popitem(last=False)
    return erg, False, ms


# ---------------------------------------------------------------------------------------------------------------------
# Abdrücke fremder Teile (Schichtraster)

ABDRUCK_ABSTAND = 1.5  # mm: so nah an einem Lager- oder Zukaufteil gilt eine Fläche als dessen Abdruck (Aussparung)


def _fremde(ctx: PruefKontext, name: str) -> list[Any]:
    """Gezeigte Lager- und Zukaufteile (keine Druckteile, keine Kulisse) außer ``name``."""
    return [k for n, k in ctx.koerper.items()
            if n != name and k.info.get("lager") and not k.info.get("druckteil") and not k.kulisse]


def _abdruck_von(k: Any, flaeche: int, fremde: list[Any]) -> Any | None:
    """Das fremde Teil, dessen Abdruck die Fläche ist (alle Eckpunkte der Fläche näher als ABDRUCK_ABSTAND an ihm),
    oder None."""
    from build123d import Shape
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    faces = getattr(k, "_druck_faces", None)
    if faces is None:
        faces = Shape.cast(k.shape).faces()
        k._druck_faces = faces
    if not 0 <= flaeche < len(faces):
        return None
    ecken = faces[flaeche].vertices()[:16]
    if not ecken:
        return None
    P = np.array([[v.X, v.Y, v.Z] for v in ecken])
    for f in fremde:
        if np.any(P < f.bmin - ABDRUCK_ABSTAND) or np.any(P > f.bmax + ABDRUCK_ABSTAND):
            continue
        nah = True
        for v in ecken:
            d = BRepExtrema_DistShapeShape(v.wrapped, f.shape)
            if not d.IsDone() or d.Value() > ABDRUCK_ABSTAND:
                nah = False
                break
        if nah:
            return f
    return None


def _hoehe_von(k: Any, erg: dict[str, Any], R: np.ndarray) -> Any:
    """Höhe einer Fläche (Mittel ihrer Eckpunkte) über dem Bett in der Druckausrichtung der Prüfung."""
    M = np.asarray((erg.get("ausrichtung") or {}).get("matrix") or np.eye(3), dtype=np.float64)
    lage = np.asarray(k.lage, dtype=np.float64).reshape(4, 4)
    A, t = M @ R @ lage[:3, :3].T, lage[:3, 3]
    zmin = float(((np.asarray(k.pos, dtype=np.float64) - t) @ A[2]).min())

    def hoehe(f: int) -> float:
        P = np.array([[v.X, v.Y, v.Z] for v in k._druck_faces[f].vertices()])
        return float(((P - t) @ A[2]).mean()) - zmin

    return hoehe


def _abdruecke_buendeln(ctx: PruefKontext, name: str, k: Any, befunde: list[dict[str, Any]],
                        hoehe_von: Any = None) -> list[dict[str, Any]]:
    """Schichtraster-Hinweise an Flächen, die Abdrücke fremder Teile sind (Aussparung um ein Lager- oder Zukaufteil),
    je fremdem Teil zu einem Hinweis bündeln: im Modell kaum zu beheben, beim Druck unkritisch (Passung prüfen)."""
    import re

    fremde = _fremde(ctx, name)
    if not fremde:
        return befunde
    out = []
    for b in befunde:
        w = b.get("wert") or {}
        if w.get("druckart") != "schichtraster" or not w.get("flaechen"):
            out.append(b)
            continue
        eigene: list[int] = []
        je_teil: dict[str, list[int]] = {}
        for f in w["flaechen"]:
            try:
                fremd = _abdruck_von(k, int(f), fremde)
            except Exception:  # noqa: BLE001 - im Zweifel bleibt die Fläche ein eigener Hinweis
                fremd = None
            if fremd is None:
                eigene.append(int(f))
            else:
                je_teil.setdefault(fremd.name, []).append(int(f))
        if not je_teil:
            out.append(b)
            continue
        if eigene:
            kopf = b["text"].split(" an den Flächen ")[0].split(" an Fläche ")[0].rstrip(".")
            wert = {**w, "flaechen": eigene}
            if hoehe_von is not None:
                try:
                    hs = sorted({round(hoehe_von(f), 2) for f in eigene})
                    liste = ", ".join(bf.de_num(h, 2) for h in hs[:6]) + (" …" if len(hs) > 6 else "")
                    kopf = re.sub(r"Höhen .*? mm liegen", f"Höhe{'n' if len(hs) != 1 else ''} {liste} mm "
                                                         f"lieg{'en' if len(hs) != 1 else 't'}", kopf, count=1)
                    wert["hoehen"] = hs
                except Exception:  # noqa: BLE001 - dann bleibt der Text mit allen Höhen
                    pass
            out.append({**b, "wert": wert, "text": kopf + _flaechen_text(name, eigene) + "."})
        for fremd, fl in je_teil.items():
            kurz = fremd.rsplit("/", 1)[-1]
            n = len(fl)
            out.append(befund(PRAEFIX + "schichtraster_abdruck", [name], "hinweis",
                              f"{name}: {n} Fläche{'n' if n != 1 else ''} aus der Aussparung für {kurz} "
                              f"lieg{'en' if n != 1 else 't'} nicht im Schichtraster (unkritisch, Passung prüfen)"
                              f"{_flaechen_text(name, fl)}.",
                              "Nichts zu ändern: der Slicer rundet diese Höhen; nach dem Druck die Passung am "
                              f"{kurz} prüfen.",
                              wert={"pruefung": "druck", "druckart": "schichtraster_abdruck", "flaechen": fl,
                                    "abdruck_von": fremd}))
    return out


ARTEN["schichtraster_abdruck"] = ("Abdruck außerhalb des Schichtrasters (Druck)",
                                  "Abdrücke außerhalb des Schichtrasters (Druck)")
bf.ART_TEXT.setdefault(PRAEFIX + "schichtraster_abdruck", ARTEN["schichtraster_abdruck"])


# ---------------------------------------------------------------------------------------------------------------------
# Prüffunktion


def _befunde(name: str, erg: dict[str, Any], welt: Any) -> list[dict[str, Any]]:
    out = []
    for h in erg.get("hinweise") or []:
        schwere = schwere_im_lauf(h)
        flaechen = [int(f) for f in h.get("flaechen") or []]
        ort = welt(h["punkt"]) if h.get("punkt") is not None else None
        text = f"{name}: {_satz(h.get('befund'))[:-1]}{_flaechen_text(name, flaechen)}"
        if ort is not None:
            text += f" bei {bf.punkt(ort)}"
        wert = {"pruefung": "druck", "druckart": h.get("art"), "flaechen": flaechen, **(h.get("werte") or {})}
        if schwere != h.get("schwere"):
            wert["schwere_druckpruefung"] = h.get("schwere")
        out.append(befund(_art_im_lauf(h, schwere), [name], schwere, text + ".", _satz(h.get("abhilfe")), wert=wert,
                          ort=ort))
    return out


def _zaehler(befunde: list[dict[str, Any]]) -> dict[str, int]:
    out = {s: 0 for s in bf.SCHWEREN}
    for b in befunde:
        out[b["schwere"]] += 1
    return out


def _zusammenfassung(zaehler: dict[str, int], erg: dict[str, Any]) -> str:
    worte = {"fehler": ("Fehler", "Fehler"), "warnung": ("Warnung", "Warnungen"), "hinweis": ("Hinweis", "Hinweise")}
    teile = [f"{n} {worte[s][0] if n == 1 else worte[s][1]}" for s, n in zaehler.items() if n]
    return (", ".join(teile) if teile else "druckbar ohne Hinweise") + \
        f" ({erg.get('material_name')}, {erg.get('drucker')})"


def _teil_info(name: str, erg: dict[str, Any], befunde: list[dict[str, Any]], vorgabe: Any, rahmen: str,
               aus_speicher: bool, ms: float) -> dict[str, Any]:
    from kevcad_kernel.druck.pruefung import _richtung_text

    a = erg.get("ausrichtung") or {}
    begr = str(a.get("begruendung") or "")
    fest = str(a.get("festigkeit") or "")
    if fest and begr.endswith(fest):
        begr = begr[: -len(fest)].strip()
    zaehler = _zaehler(befunde)
    kz = erg.get("kennzahlen") or {}
    return {
        "material": erg.get("material"),
        "material_name": erg.get("material_name"),
        "ok": zaehler["fehler"] == 0,
        "zaehler": zaehler,
        "zusammenfassung": _zusammenfassung(zaehler, erg),
        "ausrichtung": {
            "text": _richtung_text(np.asarray(a.get("unten") or [0, 0, -1], dtype=float)),
            "unten": a.get("unten"),
            "drehung": a.get("drehung"),
            "liegt_auf": f"{name}#f{a['liegt_auf']}" if a.get("liegt_auf") is not None else None,
            "automatisch": bool(a.get("automatisch")),
            "vorgabe": _ausrichtung_text(vorgabe),
            "begruendung": begr,
            "bezug": rahmen,
        },
        "kennzahlen": {k: kz.get(k) for k in ("abmessungen_mm", "hoehe_mm", "schichten", "stuetzflaeche_mm2",
                                              "auflageflaeche_mm2", "bauraum_ausnutzung_prozent", "volumen_cm3",
                                              "masse_voll_g", "dreiecke", "laufzeit_ms") if k in kz},
        "zwischenspeicher": aus_speicher,
        "ms": round(ms, 1),
    }


def pruefe(ctx: PruefKontext) -> list[dict[str, Any]]:
    """Prüffunktion „druck“ der gemeinsamen Prüfung (registriert nach „durchdringung“)."""
    t0 = time.perf_counter()
    out: list[dict[str, Any]] = []
    teile: dict[str, Any] = {}
    materialien: dict[str, Any] = {}
    neu = treffer = 0
    for name, k in ctx.koerper.items():
        if not k.info.get("druckteil"):
            continue
        ctx.abbrechen()
        material = str(k.info.get("druck_material") or k.info.get("material_id") or "pla")
        vorgabe = k.info.get("druck_ausrichtung")
        rahmen = k.info.get("druck_rahmen")
        R = _drehung(rahmen) if rahmen is not None else _drehung(k.lage)
        welt_m = np.asarray(k.lage, dtype=np.float64).reshape(4, 4)

        def welt(p: Any, R: np.ndarray = R, M: np.ndarray = welt_m) -> list[float]:
            q = R.T @ np.asarray(p, dtype=np.float64)
            return (M[:3, :3] @ q + M[:3, 3]).tolist()

        if k.info.get("druck_verfahren") == "harzdruck":
            out.append(befund(PRAEFIX + "material", [name], "fehler",
                              f"{name}: Verfahren Harzdruck, aber es gibt keinen Harzdrucker (Bambu Lab P1P druckt "
                              "nur FDM).", "Als FDM-Druckteil (verfahren=\"3d-druck\", PLA oder PETG) konstruieren.",
                              wert={"pruefung": "druck", "druckart": "material", "grund": "harzdruck"}))
        try:
            try:
                erg, aus_speicher, ms = _ergebnis_fuer(k, material, vorgabe, R)
            except ValueError as exc:
                if vorgabe is None:
                    raise
                out.append(befund(PRAEFIX + "ausrichtung", [name], "warnung",
                                  f"{name}: Ausrichtung {_ausrichtung_text(vorgabe)!s} gilt nicht ({exc}); geprüft "
                                  "wurde mit automatischer Ausrichtung.",
                                  "In lager.druckteil(..., ausrichtung=…) eine ebene Fläche, \"-z\", \"+x\" usw. oder "
                                  "None angeben.", wert={"pruefung": "druck", "druckart": "ausrichtung"}))
                vorgabe = None
                erg, aus_speicher, ms = _ergebnis_fuer(k, material, None, R)
        except ValueError as exc:  # unbekanntes Material ohne Druckregeln
            out.append(befund(PRAEFIX + "material", [name], "warnung",
                              f"{name}: keine Druckregeln für Material {material!r} ({exc}).",
                              "Druckbares Material aus dem Katalog nehmen (pla, petg …) oder in druck/regeln.py "
                              "Regeln ergänzen.", wert={"pruefung": "druck", "druckart": "material"}))
            continue
        except Exception as exc:  # noqa: BLE001 - ein Teil darf die übrigen nicht verhindern
            out.append(befund(PRAEFIX + "fehlgeschlagen", [name], "warnung",
                              f"{name}: Druckprüfung fehlgeschlagen ({type(exc).__name__}: {exc}).",
                              "Bitte melden; die übrigen Druckteile sind geprüft.",
                              wert={"pruefung": "druck", "druckart": "fehlgeschlagen"}))
            continue
        neu += int(not aus_speicher)
        treffer += int(aus_speicher)
        bef = _befunde(name, erg, welt)
        if any((b.get("wert") or {}).get("druckart") == "schichtraster" for b in bef):
            bef = _abdruecke_buendeln(ctx, name, k, bef, _hoehe_von(k, erg, R))
        out += bef
        teile[name] = _teil_info(name, erg, bef, vorgabe, "druckteil" if rahmen is not None else "welt",
                                 aus_speicher, ms)
        mid = str(erg.get("material"))
        if mid not in materialien:
            materialien[mid] = {"name": erg.get("material_name"), "druckhinweise": list(erg.get("druckhinweise") or []),
                                "festigkeit": (erg.get("ausrichtung") or {}).get("festigkeit")}
    ms = (time.perf_counter() - t0) * 1000
    ctx.zeiten["druck"] = ms
    if teile or out:
        from kevcad_kernel.druck.regeln import P1P

        ctx.ergebnis["druck"] = {"drucker": P1P.name, "teile": teile, "materialien": materialien,
                                 "neu_geprueft": neu, "aus_zwischenspeicher": treffer, "dauer_ms": round(ms, 1)}
    return out


registriere("druck", pruefe, nach="durchdringung")
