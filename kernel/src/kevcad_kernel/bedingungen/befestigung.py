"""Befestigung ist Pflicht (PLAN-BEDINGUNGEN.md, B9).

Jedes Teil braucht mindestens eine Verbindung zu seinem Gegenstück: ``verbinde(a, b, art=..., mit=[...])``. Die
Prüfung kontrolliert, dass die Verbindung physisch da ist:

- alle Arten: die Teile berühren sich (``aufliegen`` ≤ 0,05 mm, ``kleben`` ≤ 0,2 mm) oder sitzen mit Spielpassung
  (``klemmung``, ``steck``, ``formschluss`` ≤ ``spiel``, Standard 0,5 mm);
- ``schraube``: je Schraube aus ``mit`` eine fluchtende Bohrung in beiden Teilen, der Schaft geht hindurch, der Kopf
  liegt auf (an einem der Teile oder an einer Scheibe aus ``mit``); ist die Bohrung im zweiten Teil kein Gewinde
  (Durchmesser ≥ Nenndurchmesser), braucht es eine Mutter aus ``mit``, die auf der Achse sitzt und anliegt.

Außerdem gelten als Verbindung: Gelenke (Teile berühren sich oder haben Spiel ≤ 0,5 mm), ``in_bohrung`` (Schraube ↔
Teil mit der Bohrung, wenn sie sitzt), ``auf`` mit nach oben zeigender Auflage (Aufliegen) und ``fest`` mit Kontakt.
Am Boden hängen Teile, die die tiefste Ebene der Baugruppe berühren, und Teile mit ``verbinde(teil, boden)``.

Pflichtig sind Teile, die an einer Bedingung beteiligt sind. Teile ganz ohne Bedingungen sammelt ein Befund mit
Schwere „hinweis“, damit bestehende Modelle nicht auf einen Schlag gesperrt sind (Entscheidung offen, siehe Bericht).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .arten import Auf, Fest, Gelenk, InBohrung, Verbindung, _perp
from .geometrie import Bezug, BezugFehler, bohrungen_von, linien_winkel, schraube_daten
from .text import mm

KONTAKT = {"aufliegen": 0.05, "kleben": 0.2}
BODEN_TOL = 0.5


_BOXEN: dict[int, tuple[np.ndarray, np.ndarray]] = {}  # Hüllquader der gezeigten Formen während einer Prüfung


def _bbox(form: Any) -> tuple[np.ndarray, np.ndarray]:
    hit = _BOXEN.get(id(form))
    if hit is not None:
        return hit
    bb = form.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


def _abstand(fa: Any, fb: Any, grenze: float) -> tuple[float, np.ndarray | None]:
    """Kleinster Abstand zweier Formen (Hüllquader-Vorfilter: liegt er über ``grenze``, zählt nur die grobe Zahl)."""
    alo, ahi = _bbox(fa)
    blo, bhi = _bbox(fb)
    gap = np.maximum(0.0, np.maximum(blo - ahi, alo - bhi))
    grob = float(np.linalg.norm(gap))
    if grob > grenze + 1e-6:
        return grob, None
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    d = BRepExtrema_DistShapeShape(fa.wrapped, fb.wrapped)
    if not d.IsDone() or d.NbSolution() == 0:
        return grob, None
    p = d.PointOnShape1(1)
    return float(d.Value()), np.array([p.X(), p.Y(), p.Z()])


def _form(b: Bezug) -> Any:
    return b.form_welt()


def _passende_bohrung(form: Any, achse: Bezug, max_versatz: float = 0.5) -> Bezug | None:
    """Bohrung im Teil, die mit der Schraubenachse fluchtet und axial mit dem Schaft überlappt."""
    try:
        bohrungen = bohrungen_von(form)
    except Exception:  # noqa: BLE001
        return None
    assert achse.d is not None and achse.t is not None
    beste = None
    for b in bohrungen:
        if b.d is None or b.t is None or linien_winkel(b.d, achse.d) > 1.0:
            continue
        versatz = float(np.linalg.norm(_perp(achse.d) @ (b.p - achse.p)))
        if versatz > max_versatz:
            continue
        # axiale Überlappung: Bohrung [b0, b1] gegen Schaft [a0, a1] auf der Schraubenachse
        s = float(np.dot(b.d, achse.d))
        mitte = float(np.dot(b.p - achse.p, achse.d))
        b0, b1 = sorted((mitte + s * b.t[0], mitte + s * b.t[1]))
        if b1 < achse.t[0] - 0.01 or b0 > achse.t[1] + 0.01:
            continue
        if beste is None or (b.r or 0) < (beste.r or 0):
            beste = b
    return beste


def _pruefe_schraube(v: Verbindung, A: Bezug, B: Bezug, mit: list[tuple[Bezug, Any]]) -> list[str]:
    """Probleme einer Schraubverbindung (leer = in Ordnung)."""
    probleme: list[str] = []
    fa, fb = _form(A), _form(B)
    schrauben, rest = [], []
    for bz, form in mit:
        try:
            schrauben.append((bz, form, schraube_daten(form)))
        except BezugFehler:
            rest.append((bz, form))
    if not schrauben:
        return ["in mit=[…] ist keine Schraube (Teil mit zylindrischem Schaft)"]
    for bz, form, daten in schrauben:
        name = bz.teilname or bz.label or "Schraube"
        achse = daten.achse  # liegt schon in der gezeigten Lage (Form aus der Szene)
        ha = _passende_bohrung(fa, achse)
        hb = _passende_bohrung(fb, achse)
        if ha is None:
            probleme.append(f"{name} geht durch keine fluchtende Bohrung in {A.teilname}")
        if hb is None:
            probleme.append(f"{name} geht durch keine fluchtende Bohrung in {B.teilname}")
        if ha is None or hb is None:
            continue
        for h, teil in ((ha, A.teilname), (hb, B.teilname)):
            if (h.r or 0) * 2 < daten.d - (daten.steigung or 0.1 * daten.d) - 0.4:
                probleme.append(f"Bohrung in {teil} (Ø {mm(2 * (h.r or 0), 2)}) ist zu klein für "
                                f"M{daten.d:g}")
        # Kopf liegt auf: Schraube berührt eines der Teile oder eine Scheibe
        kopf_teile = [fa, fb] + [f for _, f in rest]
        if min(_abstand(form, f, 0.05)[0] for f in kopf_teile) > 0.05:
            probleme.append(f"Kopf von {name} liegt nicht auf")
        gewinde_b = (hb.r or 0) * 2 < daten.d - 0.05
        gewinde_a = (ha.r or 0) * 2 < daten.d - 0.05
        if not gewinde_a and not gewinde_b:
            muttern = []
            for mbz, mform in rest:
                for h in bohrungen_von(mform) if hasattr(mform, "faces") else []:
                    if h.d is not None and linien_winkel(h.d, achse.d) < 1.0 and \
                            np.linalg.norm(_perp(achse.d) @ (h.p - achse.p)) < 0.5:
                        muttern.append((mbz, mform))
                        break
            if not muttern:
                probleme.append(f"{name}: beide Bohrungen sind Durchgangsbohrungen, es fehlt eine Mutter in mit=[…] "
                                "(oder ein Gewinde im zweiten Teil)")
            else:
                anliegend = [m for m in muttern if min(_abstand(m[1], f, 0.05)[0] for f in [fa, fb] +
                                                       [r[1] for r in rest if r is not m]) <= 0.05]
                if not anliegend:
                    probleme.append(f"Mutter auf {name} liegt nicht an")
    return probleme


def befestigung_pruefen(sammlung: Any, aufgeloest: dict[str, tuple[Bezug, Bezug]], formen: dict[str, Any],
                        index: Any, beteiligt: dict[str, list[str]], staende: dict[str, dict] | None = None,
                        boxen: dict[str, tuple[np.ndarray, np.ndarray]] | None = None
                        ) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """(Einträge für die Liste, Befunde, Angaben je Teil: befestigt, verbindungen, am_boden)."""
    _BOXEN.clear()
    for n, f in formen.items():
        if boxen and n in boxen:
            _BOXEN[id(f)] = boxen[n]
    try:
        return _befestigung_pruefen(sammlung, aufgeloest, formen, index, beteiligt, staende, boxen)
    finally:
        _BOXEN.clear()


def _befestigung_pruefen(sammlung: Any, aufgeloest: dict[str, tuple[Bezug, Bezug]], formen: dict[str, Any],
                         index: Any, beteiligt: dict[str, list[str]], staende: dict[str, dict] | None,
                         boxen: dict[str, tuple[np.ndarray, np.ndarray]] | None
                         ) -> tuple[list[dict], list[dict], dict[str, dict]]:
    from .arten import Ergebnis
    from .pruefung import _befund, _item, aufloesen, aufloesen_paar

    if not beteiligt and not any(isinstance(v, Verbindung) for v in sammlung.bedingungen):
        # Modell ohne jede Bedingung: ein Sammel-Befund, sonst nichts zu rechnen
        if not formen:
            return [], [], {}
        namen = list(formen)
        liste = ", ".join(namen[:5]) + (" …" if len(namen) > 5 else "")
        return [], [_befund(pruefung="befestigung", teile=namen, schwere="hinweis",
                            text=f"{len(namen)} Teile ohne Angabe, wie sie befestigt sind ({liste})",
                            soll="jedes Teil mit verbinde(…) oder einer Montagebedingung", ist="keine Angabe",
                            loesung="zu jedem Teil die Befestigung konstruieren und mit verbinde(teil, gegenstück, "
                                    "art=…) angeben (Schraube, Klemmung, Steck, Formschluss, Kleben, Aufliegen)",
                            art="ohne_angabe")], {}
    items: list[dict] = []
    befunde: list[dict] = []
    kanten: dict[str, set[str]] = {n: set() for n in formen}
    art_je: dict[str, list[str]] = {n: [] for n in formen}
    am_boden: set[str] = set()
    deklariert: set[str] = set()
    pflicht: set[str] = set(beteiligt)

    def verbinden(a: str | None, b: str | None, art: str) -> None:
        if a and b and a in kanten and b in kanten and a != b:
            kanten[a].add(b)
            kanten[b].add(a)
            art_je[a].append(art)
            art_je[b].append(art)

    # verbinde(...)
    for v in sammlung.bedingungen:
        if not isinstance(v, Verbindung):
            continue
        if index is None:
            continue
        A0, B0, MA = aufloesen_paar(index, v.a, v.b)
        A, B = A0.bezug, B0.bezug
        mit = []
        for m in v.mit:
            mm_, _ = aufloesen(index, m, gegen=MA)
            mit.append((mm_.bezug, _form(mm_.bezug) if mm_.ok else None))
        teile = [n for n in [A.teilname, B.teilname if not B.welt else None] + [m.teilname for m, _ in mit] if n]
        text = v.beschreibung(A, B)
        for t in teile:
            deklariert.add(t)
            pflicht.add(t)
            beteiligt.setdefault(t, []).append(v.id)
        probleme: list[str] = []
        ort = None
        if not (A0.ok and (B0.ok or B.welt)) or any(f is None for _, f in mit):
            erg = Ergebnis("ungeprueft", hinweis=A0.hinweis or B0.hinweis or "Teil aus mit=[…] nicht gefunden")
        else:
            fa = _form(A)
            if B.welt:
                lo, hi = _bbox(fa)
                ecken = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                d = float(np.min((ecken - B.p) @ B.d))
                grenze = KONTAKT.get(v.verbindungsart, v.spiel)
                if d > grenze or d < -0.05:
                    probleme.append(f"{A.teilname} {'steht ' + mm(d) + ' über' if d > 0 else 'steckt ' + mm(-d) + ' in'}"
                                    f" {B.anzeigename()}")
                ort = ecken[int(np.argmin((ecken - B.p) @ B.d))]
            else:
                fb = _form(B)
                grenze = KONTAKT.get(v.verbindungsart, v.spiel)
                d, ort = _abstand(fa, fb, grenze)
                if d > grenze:
                    probleme.append(f"{A.teilname} und {B.teilname} berühren sich nicht ({mm(d)} Abstand, erlaubt "
                                    f"{mm(grenze)})")
                if v.verbindungsart == "schraube":
                    probleme.extend(_pruefe_schraube(v, A, B, mit))
            if probleme:
                erg = Ergebnis("verletzt", f"{v.verbindungsart}: physisch vorhanden", "; ".join(probleme), None, "",
                               ort=ort, punkte=[p for p in [ort] if p is not None],
                               loesung=_tipp(v.verbindungsart))
            else:
                erg = Ergebnis("erfuellt", f"{v.verbindungsart}: physisch vorhanden", "vorhanden", 0.0, "",
                               punkte=[p for p in [ort] if p is not None])
                if B.welt:
                    am_boden.add(A.teilname or "")
                else:
                    verbinden(A.teilname, B.teilname, v.verbindungsart)
                for m, _ in mit:
                    verbinden(m.teilname, A.teilname, v.verbindungsart)
                    verbinden(m.teilname, B.teilname if not B.welt else None, v.verbindungsart)
        item = _item(v, text, teile, erg)
        item["verbindung"] = v.verbindungsart
        items.append(item)
        if erg.stand == "verletzt":
            befunde.append(_befund(pruefung="befestigung", teile=teile, schwere="fehler", text=f"{text}: {erg.ist}",
                                   soll=erg.soll, ist=erg.ist, ort=erg.ort, loesung=erg.loesung, bedingung=v.id,
                                   art=v.verbindungsart, zeile=v.zeile))
        elif erg.stand == "ungeprueft":
            befunde.append(_befund(pruefung="befestigung", teile=teile, schwere="hinweis",
                                   text=f"{text}: nicht geprüft ({erg.hinweis})", bedingung=v.id, zeile=v.zeile))

    # weitere Verbindungen aus Bedingungen
    for c in sammlung.bedingungen:
        if c.id not in aufgeloest or isinstance(c, Verbindung):
            continue
        A, B = aufgeloest[c.id]
        if isinstance(c, Auf) and B.d is not None and float(B.d[2]) > 0.7:
            if B.welt:
                am_boden.add(A.teilname or "")
            elif _stand_ok(staende, c.id):
                verbinden(A.teilname, B.teilname, "aufliegen")
        elif isinstance(c, InBohrung) and _stand_ok(staende, c.id, auch_warnung=True):
            verbinden(A.teilname, B.teilname, "schraube")
        elif isinstance(c, (Gelenk,)) and not isinstance(c, Fest) and A.teilname and B.teilname:
            fa, fb = _form(A), _form(B)
            if fa is not None and fb is not None and _abstand(fa, fb, 0.5)[0] <= 0.5:
                verbinden(A.teilname, B.teilname, c.art)
        elif isinstance(c, Fest) and A.teilname and B.teilname:
            fa, fb = _form(A), _form(B)
            if fa is not None and fb is not None and _abstand(fa, fb, 0.5)[0] <= 0.5:
                verbinden(A.teilname, B.teilname, "fest")

    # Boden: tiefste Ebene der Baugruppe
    if formen:
        boxen = {n: (boxen or {}).get(n) or _bbox(f) for n, f in formen.items()}
        # Boden: z = 0, wenn dort etwas steht, sonst die tiefste Ebene der Baugruppe
        z0 = 0.0 if any(abs(b[0][2]) <= BODEN_TOL for b in boxen.values()) else min(b[0][2] for b in boxen.values())
        for n, (lo, _) in boxen.items():
            if lo[2] <= z0 + BODEN_TOL:
                am_boden.add(n)
    erreicht = set()
    stapel = [n for n in am_boden if n in kanten]
    while stapel:
        n = stapel.pop()
        if n in erreicht:
            continue
        erreicht.add(n)
        stapel.extend(kanten[n] - erreicht)

    teile_info: dict[str, dict] = {}
    ohne, schwebend = [], []
    for n in sorted(pflicht):
        if n not in formen:
            continue
        befestigt = bool(kanten[n]) or n in am_boden
        teile_info[n] = {"befestigt": befestigt, "am_boden": n in erreicht,
                         "verbindungen": sorted(set(art_je[n])) + (["boden"] if n in am_boden else [])}
        if not befestigt and n not in deklariert:
            ohne.append(n)
        elif befestigt and n not in erreicht:
            schwebend.append(n)
    for n in ohne:
        befunde.append(_befund(pruefung="befestigung", teile=[n], schwere="fehler",
                               text=f"{n} ist nicht befestigt: keine Verbindung zu einem Gegenstück",
                               soll="mindestens eine Verbindung (verbinde, Gelenk, in_bohrung, auf)",
                               ist="keine Verbindung", ort=_mitte(formen[n]), loesung=_tipp(None, n)))
    if schwebend:
        gruppe = ", ".join(schwebend[:6]) + (" …" if len(schwebend) > 6 else "")
        befunde.append(_befund(pruefung="befestigung", teile=schwebend, schwere="fehler",
                               text=f"Nicht am Boden: {gruppe} hängen nur untereinander zusammen",
                               soll="alle Teile über Verbindungen am Boden", ist="Gruppe ohne Verbindung zum Boden",
                               ort=_mitte(formen[schwebend[0]]),
                               loesung="die Gruppe mit verbinde(…) an ein Teil hängen, das am Boden steht (oder auf "
                                       "boden stellen)"))
    frei_teile = [n for n in formen if n not in pflicht]
    if frei_teile:
        liste = ", ".join(frei_teile[:5]) + (" …" if len(frei_teile) > 5 else "")
        befunde.append(_befund(pruefung="befestigung", teile=frei_teile, schwere="hinweis",
                               text=f"{len(frei_teile)} Teile ohne Angabe, wie sie befestigt sind ({liste})",
                               soll="jedes Teil mit verbinde(…) oder einer Montagebedingung", ist="keine Angabe",
                               loesung="zu jedem Teil die Befestigung konstruieren und mit verbinde(teil, gegenstück, "
                                       "art=…) angeben (Schraube, Klemmung, Steck, Formschluss, Kleben, Aufliegen)",
                               art="ohne_angabe"))
    return items, befunde, teile_info


def _stand_ok(staende: dict[str, dict] | None, cid: str, auch_warnung: bool = False) -> bool:
    it = (staende or {}).get(cid)
    if it is None:
        return True
    return it["stand"] == "erfuellt" or (auch_warnung and it.get("schwere") == "warnung")


def _mitte(form: Any) -> list[float]:
    lo, hi = _bbox(form)
    return [round(float(c), 2) for c in (lo + hi) / 2]


def _tipp(art: str | None, teil: str | None = None) -> str:
    if art == "schraube":
        return ("fluchtende Bohrungen in beiden Teilen vorsehen (Durchgang ISO 273 bzw. Kernloch), Schraube mit "
                "platziere(schraube, in_bohrung(…)) setzen, bei zwei Durchgangsbohrungen eine Mutter dazu")
    if art in ("klemmung", "steck", "formschluss"):
        return "Teile bis auf Spielpassung (≤ 0,5 mm) zusammenbringen oder die Aufnahme passend aussparen"
    if art in ("aufliegen", "kleben"):
        return "Teil auf die Fläche des Gegenstücks setzen, z. B. platziere(teil, auf(…))"
    return (f"Befestigung für {teil or 'das Teil'} konstruieren (Schraube mit Bohrung und Gewinde oder Mutter, Klemmung, "
            "Steckverbindung, Formschluss, Kleben oder Aufliegen) und mit verbinde(teil, gegenstück, art=…) angeben")
