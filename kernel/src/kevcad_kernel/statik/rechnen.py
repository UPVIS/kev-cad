"""Ein Durchgang der Statik: S0 und S1 für alle Szenarien, Urteile, Vorschläge aus dem Inventar, ehrliche Grenzen.

Ergebnis (JSON-tauglich, Feld ``statik`` im CHECK-Kopf und Inhalt der Nachricht STATICS, PROTOCOL.md):
``{"stand", "aktiv", "szenarien": [{"name", "ampel", "ziel", "urteile", "kennzahlen", "teile", "staebe", "auflager",
"lasten", "verbinder", "bauteile", "ueberhoehung", "text", …}], "ueberdimensioniert", "modell", "grenzen",
"vereinfachungen", "ms"}``.

Bauteile mit Kragträger-Nachweis (S0): Teile mit eigener Last (beide Seiten eines Kraftpaars, T32), Lagerteile des
Stabwerks (Lagerkraft aus S1) und Verbinder zwischen Stäben (Kräfte je Anschluss aus S1, T31).
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from kevcad_kernel.statik import bauteil as bt
from kevcad_kernel.statik import bewertung as bw
from kevcad_kernel.statik import s0 as stufe0
from kevcad_kernel.statik.modell import StatikModell, auf_rollen
from kevcad_kernel.statik.szenario import Szenario, angriffe

UEBERHOEHUNG_ANTEIL = 0.04  # größte Verschiebung erscheint als 4 % der Modellgröße


def _modellgroesse(m: StatikModell) -> float:
    if not m.teile:
        return 1000.0
    lo = np.min([t.bmin for t in m.teile.values()], axis=0)
    hi = np.max([t.bmax for t in m.teile.values()], axis=0)
    return float(np.linalg.norm(hi - lo)) or 1000.0


def rechne_alles(m: StatikModell, szenarien: list[Szenario], katalog: Any, koerper: dict[str, Any] | None = None,
                 s1: bool = True, alternativen: bool = True, aktiv: str | None = None,
                 alt_szenarien: list[Szenario] | None = None) -> dict[str, Any]:
    """S0 und S1 für alle Szenarien. ``alt_szenarien``: nur mit diesen nach leichteren oder stärkeren Lagerteilen
    suchen (Szenario auf Anfrage: schneller), sonst mit allen."""
    from kevcad_kernel.statik import stabwerk

    t0 = time.perf_counter()
    rollen = auf_rollen(m)
    s1erg: dict[str, Any] = {}
    t_s1 = 0.0
    if s1 and m.staebe:
        t = time.perf_counter()
        from kevcad_kernel.statik import feder

        feder.setze(m, koerper)  # Drehfedern an Druckteilen statt starrer Einspannung (T35)
        s1erg = stabwerk.rechne(m, szenarien)
        t_s1 = (time.perf_counter() - t) * 1000
    groesse = _modellgroesse(m)
    out_sz = []
    vereinfacht: list[str] = list(m.hinweise)
    for sz in szenarien:
        r1 = s1erg.get(sz.name)
        s0 = stufe0.rechne(m, sz, katalog, rollen, koerper,
                           traeger_auch=bool(m.staebe) and (r1 is None or not r1.ok))  # einfache Träger als Ersatz
        bauteile = []
        if koerper:
            for last in sz.kraefte():
                for n, F, p, gegenseite in angriffe(m, last):  # Kraftpaar: beide Seiten (T32)
                    t_ = m.teile.get(n)
                    if t_ is None or n in m.staebe or t_.verbindungselement:
                        continue
                    # beim Kraftpaar trägt die andere Seite nicht (von ihr kommt die Kraft), auch wenn sie berührt
                    andere = {x for t in (last.teile if gegenseite else last.gegen) for x in m.aufloesen(t)}
                    try:
                        b = bt.pruefe_last(m, sz, koerper, n, F, p, ohne=andere)
                    except Exception as exc:  # noqa: BLE001 - ein Teil darf die anderen nicht verhindern
                        b = {"teil": n, "sicherheit": None,
                             "text": f"{n}: Schnitt nicht gerechnet ({type(exc).__name__})"}
                    if b is None or (gegenseite and b.get("sicherheit") is None):
                        continue  # Gegenstück ohne Festigkeitswerte (Ball, Zukaufteil): kein graues Urteil
                    if last.flaeche and not gegenseite and last.flaeche.get("teil") in (None, n):
                        b["flaeche_last"] = dict(last.flaeche)  # Simulation: FEM verteilt sie über die ganze Fläche
                    if last.paar:
                        b["kraftpaar"] = {"gegen": list(last.teile if gegenseite else last.gegen),
                                          "gegenkraft": bool(gegenseite)}
                    if b.get("sicherheit") is not None and (b["sicherheit"] < b["ziel"] or b.get("quer_zur_schicht")):
                        b["vorschlag"] = bt.vorschlag_druck(m, koerper, b)
                    bauteile.append(b)
            bauteile += _lagerteile(m, sz, s1erg.get(sz.name), koerper, {b["teil"] for b in bauteile})
            bauteile += _verbinderteile(m, sz, s1erg.get(sz.name), koerper, {b["teil"] for b in bauteile})
        e = bw.bewerte(sz, s0, s1erg.get(sz.name), bauteile, m)
        e["lasten"] = lasten_anzeige(m, sz)  # Lasten mit Angriffspunkt für den Viewer, Kraftpaare als Paar (T32)
        r1v = s1erg.get(sz.name)
        if r1v is not None and getattr(r1v, "ok", False) and getattr(r1v, "verbinder", None):
            e["verbinder"] = list(r1v.verbinder)  # Stufe 3: Kräfte der Stäbe auf Verbinder
        vmax = (e["kennzahlen"] or {}).get("verformung_max_mm") or 0.0
        e["ueberhoehung"] = round(max(1.0, min(1000.0, UEBERHOEHUNG_ANTEIL * groesse / vmax)), 1) if vmax > 1e-6 else 1.0
        r1 = s1erg.get(sz.name)
        if r1 is not None and not r1.ok and r1.meldung:
            e["urteile"].append(bw.urteil("stabwerk", None, "grau", r1.meldung))
        elif r1 is not None and r1.meldung:
            vereinfacht += [x.strip() for x in r1.meldung.split(";") if x.strip()]
        out_sz.append(e)
    # Vorschläge aus dem Inventar
    ueber: list[dict[str, Any]] = []
    if alternativen and s1erg:
        t = time.perf_counter()
        try:
            fuer = alt_szenarien or szenarien
            ueber = bw.ueberdimensioniert(m, fuer, s1erg, katalog)
            stark = bw.staerker(m, fuer, s1erg, katalog)
        except Exception as exc:  # noqa: BLE001
            stark = {}
            vereinfacht.append(f"Vorschläge aus dem Lager nicht gerechnet ({type(exc).__name__}: {exc})")
        for e in out_sz:
            for u in e["urteile"]:
                if u["art"] in ("festigkeit", "durchbiegung", "knicken") and u.get("teil") in m.staebe:
                    sid = m.staebe[u["teil"]].stock_id
                    alt = stark.get(sid)
                    if alt:
                        u["loesung"] = (f"{alt['name']} aus dem Lager reicht (Sicherheit "
                                        f"{bw._sf(alt['sicherheit'])}, {bw.z(-alt['ersparnis_kg'], 2)} kg mehr); "
                                        + u["loesung"])
                        u["alternative"] = alt
        for e, sz in zip(out_sz, szenarien):
            if sz.hat_lasten:
                e["urteile"] += ueber
        t_alt = (time.perf_counter() - t) * 1000
    else:
        t_alt = 0.0
    # Ehrliche Grenzen (T7): allgemein und was dieses Modell annimmt
    for s in m.staebe.values():
        w = s.werkstoff
        if w.annahme:
            vereinfacht.append(f"{w.name}: {w.annahme}")
        if w.geschaetzt:
            vereinfacht.append(f"{w.name}: geschätzt {', '.join(w.geschaetzt)}")
        if s.q.hinweis:
            vereinfacht.append(f"{s.item.get('name') or s.stock_id}: {s.q.hinweis}")
    ann = [n for n, t in m.teile.items() if t.masse_angenommen]
    if ann:
        vereinfacht.append(f"Masse von {len(ann)} Teilen ohne Material angenommen (1 g/cm³)")
    for e in out_sz:
        for r in (e.get("s0") or {}).get("rutschen") or []:
            if r.get("angenommen"):
                vereinfacht.append(f"Reibwert {r['teil'].rsplit('/', 1)[-1]} auf {r['untergrund']}: nicht im Katalog, "
                                   f"μ = {bw.z(stufe0.MU_ANNAHME, 1)} angenommen")
    vereinfacht = list(dict.fromkeys(vereinfacht))
    for e in out_sz:
        e["text"] = bw.kurztext(e)
    if aktiv is None:
        lasten = [e for e, sz in zip(out_sz, szenarien) if sz.hat_lasten] or out_sz
        aktiv = max(lasten, key=lambda e: bw.RANG.get(e["ampel"], 0))["name"] if lasten else None
    return sauber({"stand": "done", "aktiv": aktiv, "szenarien": out_sz,
            "ueberdimensioniert": ueber, "modell": m.kurz(), "auf_rollen": rollen, "untergrund": m.untergrund,
            "grenzen": list(bw.GRENZEN), "vereinfachungen": vereinfacht,
            "zeiten_ms": {"modell": round(m.ms, 1), "s1": round(t_s1, 1), "inventar": round(t_alt, 1)},
            "ms": round((time.perf_counter() - t0) * 1000 + m.ms, 1)})


def sauber(x: Any) -> Any:
    """JSON-tauglich: numpy-Zahlen und -Felder zu Python, unendlich und NaN zu None."""
    if isinstance(x, dict):
        return {str(k): sauber(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [sauber(v) for v in x]
    if isinstance(x, np.ndarray):
        return sauber(x.tolist())
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return f if math.isfinite(f) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, set):
        return sorted(sauber(v) for v in x)
    return x


def _lagerteile(m: StatikModell, sz: Szenario, r1: Any, koerper: dict[str, Any], schon: set[str]
                ) -> list[dict[str, Any]]:
    """Teile, an denen das Stabwerk gelagert ist (Halter, Konsolen, oft Druckteile), mit der Lagerkraft des Stabs als
    Kragträger nachweisen: Last am Lagerpunkt, Einspannung an den übrigen Berührungen. Je Teil das schlechteste
    Lager."""
    if r1 is None or not getattr(r1, "ok", False):
        return []
    beste: dict[str, dict[str, Any]] = {}
    for a in r1.auflager:
        teil = a.get("teil")
        t = m.teile.get(teil)
        if t is None or teil in m.staebe or t.verbindungselement or t.werkstoff is None or teil in schon:
            continue
        F = -np.asarray(a["kraft"], dtype=float)
        if float(np.linalg.norm(F)) < 1e-3:
            continue
        try:
            b = bt.pruefe_last(m, sz, koerper, teil, F, np.asarray(a["punkt"], dtype=float),
                               moment=-np.asarray(a["moment"], dtype=float), ohne={a["stab"]})
        except Exception:  # noqa: BLE001 - ein Lager darf die anderen nicht verhindern
            continue
        if b is None or b.get("sicherheit") is None:
            continue
        b["aus_lager"] = a["stab"]
        if teil not in beste or b["sicherheit"] < beste[teil]["sicherheit"]:
            beste[teil] = b
    for b in beste.values():
        if b["sicherheit"] < b["ziel"]:
            b["vorschlag"] = bt.vorschlag_druck(m, koerper, b)
    return list(beste.values())


VERBINDER_MIN_N = 0.5  # kleinere Kräfte eines Stabs auf einen Verbinder zählen nicht


def verbinder_lager(vs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Verbinder zwischen Stäben (im Stabwerk starr, T11): ``(Lager, Lasten)``. Gehalten wird der Verbinder vom Stab
    mit der größten Kraft, die Kräfte und Momente der übrigen Stäbe aus S1 sind seine Lasten. Bei zwei Stäben ist das
    dasselbe Gleichgewicht wie umgekehrt (bis auf das Eigengewicht des Verbinders)."""
    lager = max(vs, key=lambda v: float(np.linalg.norm(v["kraft"])))
    return lager, [v for v in vs if v is not lager]


def _verbinderteile(m: StatikModell, sz: Szenario, r1: Any, koerper: dict[str, Any], schon: set[str]
                    ) -> list[dict[str, Any]]:
    """Verbinder zwischen Stäben (Schlitten, Eckverbinder) als Kragträger nachweisen (T31): Die Kräfte je Anschluss
    kommen aus dem Stabwerk (S1, statisch unbestimmt nach Steifigkeit verteilt), eingespannt ist der Verbinder an der
    Berührung mit dem Stab, der ihn hält (``verbinder_lager``), belastet von den übrigen Stäben am Anschlusspunkt
    (Resultierende mit Moment, wenn es mehrere sind)."""
    if r1 is None or not getattr(r1, "ok", False) or not getattr(r1, "verbinder", None):
        return []
    je_teil: dict[str, list[dict[str, Any]]] = {}
    for v in r1.verbinder:
        je_teil.setdefault(v["teil"], []).append(v)
    out = []
    for teil, vs in je_teil.items():
        t = m.teile.get(teil)
        if t is None or teil in m.staebe or t.verbindungselement or t.werkstoff is None or teil in schon:
            continue
        if len(vs) < 2 or max(float(np.linalg.norm(v["kraft"])) for v in vs) < VERBINDER_MIN_N:
            continue
        lager, lasten = verbinder_lager(vs)
        gross = max(lasten, key=lambda v: float(np.linalg.norm(v["kraft"])))
        P = np.asarray(gross["punkt"], dtype=float)
        F = np.sum([np.asarray(v["kraft"], dtype=float) for v in lasten], axis=0)
        M = np.sum([np.asarray(v["moment"], dtype=float) + np.cross(np.asarray(v["punkt"], dtype=float) - P,
                                                                    np.asarray(v["kraft"], dtype=float))
                    for v in lasten], axis=0)
        # Einspannung nur an der Berührung mit dem haltenden Stab: Rolle, Schrauben und die übrigen Stäbe tragen nichts
        nachbarn = {e["b"] if e["a"] == teil else e["a"] for e in m.kanten.values() if teil in (e["a"], e["b"])}
        try:
            b = bt.pruefe_last(m, sz, koerper, teil, F, P, moment=M, ohne=nachbarn - {lager["stab"]})
        except Exception:  # noqa: BLE001 - ein Verbinder darf die anderen nicht verhindern
            continue
        if b is None or b.get("sicherheit") is None:
            continue
        b["aus_verbinder"] = lager["stab"]
        b["verbinder"] = [{"stab": v["stab"], "kraft": v["kraft"], "moment": v["moment"], "punkt": v["punkt"],
                           "lager": v is lager} for v in vs]
        if b["sicherheit"] < b["ziel"] or b.get("quer_zur_schicht"):
            b["vorschlag"] = bt.vorschlag_druck(m, koerper, b)
        out.append(b)
    return out


def lasten_anzeige(m: StatikModell, sz: Szenario) -> list[dict[str, Any]]:
    """Lasten eines Szenarios für den Viewer und das Ergebnis: je Last Teile, Kraft (Stoßfaktor eingerechnet) und
    Angriffspunkt (angegeben, sonst Mitte der Teile bzw. der Stabachse); Kraftpaare mit ``gegen`` und ``paar``."""
    out = []
    for last in sz.kraefte():
        ziele = [n for t in last.teile for n in m.aufloesen(t)]
        if not ziele:
            continue
        if last.punkt is not None:
            p = np.asarray(last.punkt, dtype=float)
        else:
            pts = [(m.staebe[n].p0 + m.staebe[n].p1) / 2 if n in m.staebe else m.teile[n].schwerpunkt for n in ziele]
            p = np.mean(pts, axis=0)
        e = {"teile": list(last.teile), "kraft": [round(float(c), 2) for c in last.kraft],
             "punkt": [round(float(c), 1) for c in p], "kg": last.kg, "zeile": last.zeile}
        if last.paar:
            e["gegen"] = list(last.gegen)
            e["paar"] = True
        if last.id:  # Last aus der App (Simulation)
            e["id"] = last.id
        if last.flaeche:  # Simulation: Last auf der ganzen Fläche
            e["flaeche"] = dict(last.flaeche)
        out.append(e)
    return out


def befunde(erg: dict[str, Any]) -> list[dict[str, Any]]:
    """Befunde für die gemeinsame Prüfung: rot → Warnung, gelb und „überdimensioniert“ → Hinweis (Statik sperrt den
    Export nicht: vereinfachte Modelle, T7)."""
    from kevcad_kernel.pruefung.befund import befund

    out = []
    gesehen = set()
    for e in erg.get("szenarien") or []:
        ablauf = bool((e.get("szenario") or {}).get("ablauf"))
        for u in e.get("urteile") or []:
            if ablauf and u["art"] in ("kippen", "rutschen"):
                continue  # Szenario mit Ablauf (Stufe 2): Kippen und Rutschen beurteilt der Ablauf genauer
            if u["art"] == "ueberdimensioniert":
                schwere = "hinweis"
            elif u["ampel"] == "rot":
                schwere = "warnung"
            elif u["ampel"] == "gelb":
                schwere = "hinweis"
            else:
                continue
            key = (u["art"], u.get("teil"), u["text"] if u["art"] == "ueberdimensioniert" else e["name"])
            if key in gesehen:
                continue
            gesehen.add(key)
            text = u["text"] if u["art"] == "ueberdimensioniert" else f"Statik „{e['name']}“: {u['text']}"
            wert = {"pruefung": "statik", "szenario": e["name"], "ampel": u["ampel"]}
            for k in ("sicherheit", "ziel", "reserve", "durchbiegung", "grenze", "ausnutzung", "schichtfaktor"):
                if u.get(k) is not None and isinstance(u.get(k), (int, float)) and math.isfinite(u[k]):
                    wert[k] = u[k]
            ort = u.get("ort")
            out.append(befund("statik_" + u["art"], [u["teil"]] if u.get("teil") else ["Statik"], schwere, text,
                              u.get("loesung") or "", wert=wert, ort=ort))
    return out
