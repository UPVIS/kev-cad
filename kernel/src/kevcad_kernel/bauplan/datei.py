"""Bauplan als Datei: ``<projekt>/dokumente/bauplan.json`` lesen, schreiben, Bestehendes erhalten, bearbeiten.

Erhalten bei jedem neuen Lauf (DOKUMENTE.md): Schritte mit ``fest: true`` bleiben, wie sie sind (nur die Prüfung
wird neu gerechnet); Titel, Text und Hinweise mit ``quelle`` agent oder kevin wandern in den neuen Schritt. Zugeordnet
wird über die ``id`` (aus Abschnitt und Teilen) und, wenn sich Namen geändert haben, über die Teile (mindestens die
Hälfte gemeinsam). Bildeinstellungen mit eigener Quelle bleiben ebenso. Hat jemand Schritte verschoben, gilt die
Reihenfolge des Abschnitts als fest (``reihenfolge: "fest"``).

Bearbeiten (``BAUPLAN_EDIT.ops``, MCP ``bauplan_bearbeiten``): ``text``, ``fest``, ``verschieben``, ``zusammenfassen``,
``teilen``, ``bild``; additiv ``werkzeug`` und ``umfang`` (Teile ausnehmen oder dazunehmen; danach neu erzeugen).
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from kevcad_kernel.bauplan.geruest import sid

DATEI = "bauplan.json"
QUELLEN = ("auto", "agent", "kevin")


def pfad(projekt: str | Path) -> Path:
    return Path(projekt) / "dokumente" / DATEI


def laden(projekt: str | Path | None) -> dict[str, Any] | None:
    if projekt is None:
        return None
    p = pfad(projekt)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def speichern(projekt: str | Path, plan: dict[str, Any]) -> Path:
    """Atomar schreiben (erst Temp-Datei, dann umbenennen)."""
    p = pfad(projekt)
    p.parent.mkdir(parents=True, exist_ok=True)
    daten = json.dumps(plan, ensure_ascii=False, indent=1, default=_json)
    fd, tmp = tempfile.mkstemp(prefix=".bauplan-", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(daten)
        os.replace(tmp, p)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def _json(o: Any) -> Any:
    try:
        import numpy as np

        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.generic):
            return o.item()
    except ImportError:
        pass
    return str(o)


# ---------------------------------------------------------------------------------------------------------------------
# Zusammenführen


def alle_schritte(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(a.get("art"), s) for a in plan.get("abschnitte") or [] for s in a.get("schritte") or []]


def finde(plan: dict[str, Any], schritt_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for a in plan.get("abschnitte") or []:
        for s in a.get("schritte") or []:
            if s.get("id") == schritt_id:
                return a, s
    return None


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def zusammenfuehren(neu: dict[str, Any], alt: dict[str, Any] | None, teile_da: set[str] | None = None) -> dict:
    """Neues Gerüst mit allem, was im alten Bauplan fest ist oder von Agent oder Kevin stammt."""
    if not alt:
        return neu
    out = copy.deepcopy(neu)
    for key in ("umfang",):
        if key in alt:
            out[key] = alt[key]
    alt_abschnitte = {a.get("art"): a for a in alt.get("abschnitte") or []}
    for a in out.get("abschnitte") or []:
        art = a.get("art")
        aa = alt_abschnitte.get(art)
        if aa is None:
            continue
        alte = list(aa.get("schritte") or [])
        nach_id = {s.get("id"): s for s in alte}
        benutzt: set[str] = set()
        ergebnis: list[dict[str, Any]] = []
        for s in a.get("schritte") or []:
            m = nach_id.get(s["id"])
            if m is None or m.get("id") in benutzt:
                kand = [x for x in alte if x.get("id") not in benutzt and (x.get("fest") or x.get("quelle") != "auto")]
                kand.sort(key=lambda x: -_jaccard(x.get("teile") or [], s.get("teile") or []))
                if kand and _jaccard(kand[0].get("teile") or [], s.get("teile") or []) >= 0.5:
                    m = kand[0]
                else:
                    m = None
            if m is None:
                ergebnis.append(s)
                continue
            benutzt.add(m["id"])
            if m.get("fest"):
                f = copy.deepcopy(m)
                f["pruefung"] = []
                fehlend = [t for t in f.get("teile") or [] if teile_da is not None and t not in teile_da]
                f["verwaist"] = bool(fehlend)
                if not f.get("bild") or (f.get("bild") or {}).get("quelle", "auto") == "auto":
                    f["bild"] = s.get("bild")
                ergebnis.append(f)
                continue
            if m.get("quelle") in ("agent", "kevin"):
                for k in ("titel", "text", "hinweise", "quelle"):
                    if k in m:
                        s[k] = m[k]
            if m.get("werkzeug_quelle") in ("agent", "kevin"):
                s["werkzeug"] = m.get("werkzeug") or []
                s["werkzeug_quelle"] = m["werkzeug_quelle"]
            if (m.get("bild") or {}).get("quelle") in ("agent", "kevin"):
                s["bild"] = m["bild"]
            ergebnis.append(s)
        # feste Schritte, die das Gerüst nicht mehr erzeugt: an ihrer alten Stelle behalten
        for i, m in enumerate(alte):
            if m.get("id") in benutzt or not m.get("fest"):
                continue
            f = copy.deepcopy(m)
            f["pruefung"] = []
            f["verwaist"] = bool(teile_da is not None and any(t not in teile_da for t in f.get("teile") or []))
            vorher = next((alte[j]["id"] for j in range(i - 1, -1, -1) if alte[j].get("id") in
                           {x["id"] for x in ergebnis}), None)
            pos = 0 if vorher is None else next(k for k, x in enumerate(ergebnis) if x["id"] == vorher) + 1
            ergebnis.insert(pos, f)
        if aa.get("reihenfolge") == "fest":
            index = {s.get("id"): i for i, s in enumerate(alte)}
            bekannt = [s for s in ergebnis if s["id"] in index]
            bekannt.sort(key=lambda s: index[s["id"]])
            it = iter(bekannt)
            ergebnis = [next(it) if s["id"] in index else s for s in ergebnis]
            a["reihenfolge"] = "fest"
        a["schritte"] = ergebnis
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Bearbeiten


class BearbeitungsFehler(ValueError):
    pass


def bearbeiten(plan: dict[str, Any], ops: list[dict[str, Any]], von: str = "agent") -> tuple[list[str], bool]:
    """Wendet die Operationen an (ändert ``plan``). (Meldungen, neu erzeugen nötig)."""
    if von not in ("agent", "kevin"):
        raise BearbeitungsFehler(f"von {von!r}: agent oder kevin")
    meldungen: list[str] = []
    neu_erzeugen = False
    for op in ops or []:
        art = op.get("op")
        if art == "umfang":
            umfang = dict(plan.get("umfang") or {})
            for k in ("ohne", "mit"):
                if k in op:
                    umfang[k] = [str(x) for x in op.get(k) or []]
            plan["umfang"] = umfang
            neu_erzeugen = True
            meldungen.append("Umfang geändert: " + ", ".join(f"{k} {len(v)}" for k, v in umfang.items()))
            continue
        if art == "vorher":
            a, b = op.get("a"), op.get("b")
            if not a or not b:
                raise BearbeitungsFehler("vorher braucht a und b (Schritt-id oder Teilname)")
            plan.setdefault("vorher", []).append({"a": str(a), "b": str(b), "grund": str(op.get("grund") or ""),
                                                  "quelle": von})
            meldungen.append(f"Reihenfolge {a} vor {b} eingetragen ({von})")
            neu_erzeugen = True
            continue
        if art == "vorher_loeschen":
            liste = plan.get("vorher") or []
            i = op.get("index")
            if not isinstance(i, int) or not 0 <= i < len(liste):
                raise BearbeitungsFehler(f"vorher_loeschen: index {i!r} ungültig (0 bis {len(liste) - 1})")
            weg = liste.pop(i)
            meldungen.append(f"Reihenfolge {weg.get('a')} vor {weg.get('b')} gelöscht")
            continue
        if art == "zusammenfassen":
            ids = list(op.get("schritte") or [])
            if len(ids) < 2:
                raise BearbeitungsFehler("zusammenfassen braucht schritte: [id, id, …]")
            treffer = [finde(plan, i) for i in ids]
            if any(t is None for t in treffer):
                raise BearbeitungsFehler(f"Schritt nicht gefunden: {[i for i, t in zip(ids, treffer) if t is None]}")
            abschnitt = treffer[0][0]
            if any(t[0] is not abschnitt for t in treffer):
                raise BearbeitungsFehler("zusammenfassen nur innerhalb eines Abschnitts")
            erster = treffer[0][1]
            for _, s in treffer[1:]:
                for k in ("teile", "neu", "verbindungsmittel", "werkzeug", "bohrbild", "zuschnitt", "einbau",
                          "hinweise"):
                    erster[k] = list(erster.get(k) or []) + [x for x in s.get(k) or [] if x not in (erster.get(k) or [])]
                abschnitt["schritte"].remove(s)
            erster["titel"] = op.get("titel") or erster["titel"]
            if op.get("text"):
                erster["text"] = op["text"]
            erster["quelle"] = von
            erster["fest"] = True
            meldungen.append(f"{len(ids)} Schritte zu {erster['id']} zusammengefasst (fest)")
            continue
        sid_ = op.get("schritt")
        t = finde(plan, str(sid_)) if sid_ is not None else None
        if t is None:
            raise BearbeitungsFehler(f"Schritt {sid_!r} nicht gefunden")
        abschnitt, s = t
        if art == "text":
            for k in ("titel", "text"):
                if op.get(k) is not None:
                    s[k] = str(op[k])
            if op.get("hinweise") is not None:
                s["hinweise"] = [str(x) for x in op["hinweise"]]
            s["quelle"] = von
            meldungen.append(f"Text von {s['id']} gesetzt")
        elif art == "fest":
            s["fest"] = bool(op.get("wert", True))
            meldungen.append(f"{s['id']} {'fest' if s['fest'] else 'nicht mehr fest'}")
        elif art == "werkzeug":
            s["werkzeug"] = [str(x) for x in op.get("werkzeug") or []]
            s["werkzeug_quelle"] = von
            meldungen.append(f"Werkzeug von {s['id']} gesetzt")
        elif art == "verschieben":
            liste = abschnitt["schritte"]
            liste.remove(s)
            nach = op.get("nach")
            if nach is None or nach == "":
                liste.insert(0, s)
            elif isinstance(nach, int):
                liste.insert(max(0, min(len(liste), nach)), s)
            else:
                idx = next((i for i, x in enumerate(liste) if x.get("id") == nach), None)
                if idx is None:
                    liste.insert(0, s)  # zurück an den Anfang, dann Fehler
                    raise BearbeitungsFehler(f"Schritt {nach!r} (nach) nicht gefunden")
                liste.insert(idx + 1, s)
            abschnitt["reihenfolge"] = "fest"
            meldungen.append(f"{s['id']} verschoben (Reihenfolge des Abschnitts {abschnitt.get('art')} jetzt fest)")
        elif art == "teilen":
            teile = [str(x) for x in op.get("teile") or []]
            if not teile or not set(teile) <= set(s.get("teile") or []):
                raise BearbeitungsFehler("teilen braucht teile: [Teile des Schritts]")
            neu = copy.deepcopy(s)
            neu["id"] = f"{s['id']}-{sid(*sorted(teile))[:4]}"
            neu["teile"] = teile
            neu["neu"] = [x for x in s.get("neu") or [] if x in teile]
            neu["einbau"] = [e for e in s.get("einbau") or [] if set(e.get("teile") or []) & set(teile)]
            neu["titel"] = op.get("titel") or f"{s['titel']} (Teil 2)"
            s["teile"] = [x for x in s.get("teile") or [] if x not in teile]
            s["neu"] = [x for x in s.get("neu") or [] if x not in teile]
            s["einbau"] = [e for e in s.get("einbau") or [] if not set(e.get("teile") or []) & set(teile)]
            for x in (s, neu):
                x["quelle"] = von
                x["fest"] = True
            liste = abschnitt["schritte"]
            liste.insert(liste.index(s) + 1, neu)
            meldungen.append(f"{s['id']} geteilt, neuer Schritt {neu['id']} (beide fest)")
        elif art == "bild":
            bild = dict(s.get("bild") or {})
            for k in ("kamera", "explosion", "pfeile", "hervorheben", "ansicht"):
                if k in op:
                    bild[k] = op[k]
            bild["quelle"] = von
            s["bild"] = bild
            meldungen.append(f"Bild von {s['id']} gesetzt")
        else:
            raise BearbeitungsFehler(f"op {art!r} unbekannt (text, fest, verschieben, zusammenfassen, teilen, bild, "
                                     "werkzeug, umfang, vorher, vorher_loeschen)")
    return meldungen, neu_erzeugen


# ---------------------------------------------------------------------------------------------------------------------
# Zusammenfassung


def zusammenfassung(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Für DOCS: Abschnitte mit Schrittzahl, Schritte gesamt, Probleme (Fehler und Warnungen)."""
    if not plan:
        return None
    abschnitte = [{"art": a.get("art"), "titel": a.get("titel"), "schritte": len(a.get("schritte") or [])}
                  for a in plan.get("abschnitte") or []]
    befunde = [b for _, s in alle_schritte(plan) for b in s.get("pruefung") or []]
    return {"abschnitte": abschnitte, "schritte": sum(a["schritte"] for a in abschnitte),
            "probleme": sum(1 for b in befunde if b.get("schwere") in ("fehler", "warnung")),
            "fehler": sum(1 for b in befunde if b.get("schwere") == "fehler"),
            "hinweise": sum(1 for b in befunde if b.get("schwere") == "hinweis"),
            "run": (plan.get("stand") or {}).get("run")}
