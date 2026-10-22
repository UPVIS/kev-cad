"""Reihenfolgen „a vor b“ (DOKUMENTE.md 1.1, Liste ``vorher`` auf oberster Ebene des Bauplans).

- **Auto** (``quelle: "auto"``) aus der erzeugten Montagefolge: ein Teil kommt vor dem Teil, an dem es nicht befestigt
  ist, das aber sonst seinen Einführweg versperrt („Weg“), und das Gegenstück kommt vor dem Teil, das daran befestigt
  wird („Befestigung“, aus ``verbinde`` und Gelenken). Abgeleitet aus der Folge des Gerüsts, bevor feste Schritte und
  verschobene Reihenfolgen übernommen werden; so fällt ein Verschieben gegen eine solche Regel auf.
- **Agent und Kevin** tragen Reihenfolgen ein, wenn mehrere Folgen gleichwertig sind; sie bleiben bei jedem Lauf
  erhalten und ordnen die Montage danach.
- Ein Verstoß (b steht vor a) ist ein Befund ``reihenfolge``.

``a`` und ``b`` sind Schritt-ids oder Teilnamen (dann zählt der Schritt, der das Teil einbaut).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from kevcad_kernel.bauplan.simulation import montage_schritte


def _ebenen(plan: dict[str, Any]) -> dict[Any, list[dict[str, Any]]]:
    out: dict[Any, list[dict[str, Any]]] = {}
    for s in montage_schritte(plan):
        out.setdefault(s.get("baugruppe"), []).append(s)
    return out


def ableiten(ein: Any, wp: Any, plan: dict[str, Any], max_eintraege: int = 400) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    gesehen: set[tuple[str, str]] = set()

    def neu(a: dict, b: dict, grund: str, teile: list[str]) -> None:
        key = (a["id"], b["id"])
        if key in gesehen or a["id"] == b["id"] or len(out) >= max_eintraege:
            return
        gesehen.add(key)
        out.append({"a": a["id"], "b": b["id"], "grund": grund, "quelle": "auto", "teile": teile})

    for _, schritte in _ebenen(plan).items():
        wo: dict[str, int] = {}
        for i, s in enumerate(schritte):
            for t in s.get("neu") or []:
                wo[t] = i
        for i, s in enumerate(schritte):
            neu_s = set(s.get("neu") or [])
            # Befestigung: Gegenstück früher
            for v in ein.verbindungen:
                if v.quelle not in ("verbinde", "gelenk") or v.b is None:
                    continue
                for teil, gegen in ((v.a, v.b), (v.b, v.a)):
                    if teil in neu_s and gegen in wo and wo[gegen] < i:
                        neu(schritte[wo[gegen]], s, f"{teil.rsplit('/', 1)[-1]} wird an {gegen.rsplit('/', 1)[-1]} "
                                                   f"befestigt ({v.art})", [gegen, teil])
            # Weg: spätere Teile würden den Einführweg versperren
            spaeter = [t for j in range(i + 1, len(schritte)) for t in schritte[j].get("neu") or []
                       if t in wp.koerper]
            if not spaeter:
                continue
            for el in s.get("einbau") or []:
                if el.get("grundteil") or el.get("richtung") is None:
                    continue
                d1 = -np.asarray(el["richtung"], dtype=float)
                zuerst = el.get("zuerst")
                for t in el.get("teile") or []:
                    if t not in wp.koerper:
                        continue
                    if zuerst is not None:
                        s1 = float(el.get("weg") or 0.0)
                        sperr = dict(wp.sperrer(t, d1, gegen=spaeter, weg=max(s1, 1.0)))
                        sperr.update(wp.sperrer(t, -np.asarray(zuerst, float), gegen=spaeter, versatz=d1 * s1))
                    else:
                        sperr = wp.sperrer(t, d1, gegen=spaeter)
                    for q in sperr:
                        if q in wo:
                            neu(s, schritte[wo[q]], f"{q.rsplit('/', 1)[-1]} versperrt sonst den Weg von "
                                                    f"{t.rsplit('/', 1)[-1]}", [t, q])
    return out


def _position(plan: dict[str, Any], ref: str) -> tuple[Any, int] | None:
    for ebene, schritte in _ebenen(plan).items():
        for i, s in enumerate(schritte):
            if s.get("id") == ref or ref in (s.get("neu") or []):
                return ebene, i
    return None


def einordnen(plan: dict[str, Any]) -> list[str]:
    """Montageschritte so verschieben, dass die Reihenfolgen von Agent und Kevin gelten (a direkt vor b, wenn a
    dahinter steht). Meldungen der Verschiebungen."""
    meldungen = []
    regeln = [r for r in plan.get("vorher") or [] if r.get("quelle") in ("agent", "kevin")]
    if not regeln:
        return meldungen
    abschnitt = next((a for a in plan.get("abschnitte") or [] if a.get("art") == "montage"), None)
    if abschnitt is None:
        return meldungen
    for _ in range(3):  # wenige Durchgänge genügen für verträgliche Regeln
        geaendert = False
        for r in regeln:
            pa, pb = _position(plan, str(r.get("a"))), _position(plan, str(r.get("b")))
            if pa is None or pb is None or pa[0] != pb[0] or pa[1] < pb[1]:
                continue
            liste = abschnitt["schritte"]
            sa = next(s for s in liste if s.get("id") == r.get("a") or r.get("a") in (s.get("neu") or []))
            sb = next(s for s in liste if s.get("id") == r.get("b") or r.get("b") in (s.get("neu") or []))
            liste.remove(sa)
            liste.insert(liste.index(sb), sa)
            meldungen.append(f"{sa['id']} vor {sb['id']} gestellt ({r.get('quelle')}: {r.get('grund') or 'Vorgabe'})")
            geaendert = True
        if not geaendert:
            break
    return meldungen


def verstoesse(plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Befunde ``reihenfolge`` je Schritt-id (am Schritt, der zu spät kommt)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for r in plan.get("vorher") or []:
        pa, pb = _position(plan, str(r.get("a"))), _position(plan, str(r.get("b")))
        if pa is None or pb is None or pa[0] != pb[0] or pa[1] < pb[1]:
            continue
        ebene = _ebenen(plan)[pa[0]]
        sa, sb = ebene[pa[1]], ebene[pb[1]]
        schwere = "fehler" if r.get("quelle") == "auto" and "versperrt" in str(r.get("grund")) else "warnung"
        out.setdefault(sa["id"], []).append({
            "art": "reihenfolge", "teile": list(r.get("teile") or [])[:2] or list(sa.get("neu") or [])[:1],
            "schwere": schwere, "schritt": sa["id"], "ort": None, "wert": {"vor": sb["id"]},
            "text": f"„{sa.get('titel')}“ soll vor „{sb.get('titel')}“ kommen ({r.get('grund') or 'Vorgabe'}, "
                    f"{r.get('quelle')}), steht aber dahinter.",
            "loesung": f"Schritt {sa['id']} vor {sb['id']} verschieben (bauplan_bearbeiten verschieben) oder die "
                       "Reihenfolge-Regel löschen, wenn sie nicht mehr gilt."})
    return out
