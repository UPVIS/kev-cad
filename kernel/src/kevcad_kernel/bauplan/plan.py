"""Bauplan erzeugen: Eingang → Montagefolge → Gerüst → Bestehendes übernehmen → Bilder → Simulation.

    erzeuge(eingang, alt=None) -> Ergebnis   (plan: Inhalt von bauplan.json mit Prüfung, folge, wege, zeiten)
    pruefe(ergebnis, schritt=None)           Simulation neu (nach Bearbeiten), schreibt ``pruefung`` je Schritt
    strichbilder(ergebnis)                   Strichbilder je Schritt (Feld 180 × 120 mm), für die Nachricht BAUPLAN
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from kevcad_kernel.bauplan import datei, reihenfolge
from kevcad_kernel.bauplan.bild import Bilder, strichbild
from kevcad_kernel.bauplan.eingang import Eingang
from kevcad_kernel.bauplan.geruest import geruest
from kevcad_kernel.bauplan.montagefolge import Folge, plane
from kevcad_kernel.bauplan.simulation import Simulation, befund_ids, montage_schritte
from kevcad_kernel.bauplan.wege import WegPruefer


@dataclass
class Ergebnis:
    ein: Eingang
    plan: dict[str, Any]
    folge: Folge
    wege: WegPruefer
    zeiten: dict[str, float] = field(default_factory=dict)
    bilder_cache: dict[str, Any] = field(default_factory=dict)


def wegpruefer(ein: Eingang) -> WegPruefer:
    gew: dict[frozenset, np.ndarray] = {}
    for a, b in ein.gewinde:
        ta, tb = ein.teile.get(a), ein.teile.get(b)
        if ta is None or tb is None:
            continue
        ax = None
        for t in (ta, tb):
            if t.vm.get("achse") is not None:
                ax = np.asarray(t.vm["achse"], dtype=float)
                break
        if ax is None:
            achsen = ta.koerper.zylinder_achsen(1) or tb.koerper.zylinder_achsen(1)
            ax = achsen[0] if achsen else np.array([0.0, 0.0, 1.0])
        gew[frozenset((a, b))] = ax
    # Einsätze und eingeklebte Stifte wandern mit ihrem Teil: keine Sperre untereinander
    aus = set(ein.erlaubt) | set(ein.durchdringend)
    for t in ein.teile.values():
        if t.wirt:
            aus.add(frozenset((t.name, t.wirt)))
    koerper = {n: t.koerper for n, t in ein.teile.items() if t.rolle != "ohne"}
    return WegPruefer(koerper, aus, gew)


def bilder_setzen(ein: Eingang, plan: dict[str, Any]) -> None:
    """Bildparameter je Schritt (Montage mit Explosion und Kamera; Einsätze, Lager und Stifte mit ihrem aufnehmenden
    Teil als Bezug; sonst das Teil allein)."""
    b = Bilder(ein)
    montiert: dict[Any, list[str]] = {}
    eingebracht: set[str] = set()  # Einsätze und Lager aus früheren Bearbeiten-Schritten (Bezug für Stifte)
    for a in plan.get("abschnitte") or []:
        for s in a.get("schritte") or []:
            alt = s.get("bild") or {}
            neu: dict[str, Any] | None = None
            if a.get("art") == "montage":
                ebene = s.get("baugruppe")
                vorher = list(montiert.get(ebene, []))
                neu = b.parameter(s, vorher)
                montiert.setdefault(ebene, []).extend(t for t in s.get("neu") or [] if t in ein.teile)
            elif a.get("art") == "bearbeiten" and s.get("neu"):
                try:
                    neu = b.einbringen(s, eingebracht)
                except Exception:  # noqa: BLE001 - ein Bild darf den Bauplan nicht verhindern
                    neu = None
                eingebracht.update(t for t in s.get("neu") or [] if t in ein.teile)
            if neu is None and a.get("art") != "montage":
                teile = [t for t in s.get("teile") or [] if t in ein.teile][:1]
                if not teile or a.get("art") == "material":
                    s["bild"] = alt or None
                    continue
                neu = b.parameter({"neu": teile, "einbau": []}, [])
                neu["kontext"] = []
            if alt.get("quelle") in ("agent", "kevin"):
                for k in ("kamera", "explosion", "pfeile", "hervorheben", "ansicht"):
                    if k in alt:
                        neu[k] = alt[k]
                neu["quelle"] = alt["quelle"]
            s["bild"] = neu


def erzeuge(ein: Eingang, alt: dict[str, Any] | None = None, zeitlimit_s: float = 90.0) -> Ergebnis:
    t0 = time.perf_counter()
    wp = wegpruefer(ein)
    folge = plane(ein, wp, zeitlimit_s)
    t1 = time.perf_counter()
    plan = geruest(ein, folge)
    auto = reihenfolge.ableiten(ein, wp, plan)  # aus der erzeugten Folge, vor dem Übernehmen fester Schritte
    t2 = time.perf_counter()
    plan = datei.zusammenfuehren(plan, alt, set(ein.teile))
    if alt and alt.get("umfang"):
        plan["umfang"] = alt["umfang"]
    plan["vorher"] = auto + [r for r in (alt or {}).get("vorher") or [] if r.get("quelle") in ("agent", "kevin")]
    eingeordnet = reihenfolge.einordnen(plan)
    bilder_setzen(ein, plan)
    t3 = time.perf_counter()
    erg = Ergebnis(ein, plan, folge, wp)
    pruefe(erg)
    t4 = time.perf_counter()
    erg.zeiten = {"montagefolge_ms": round((t1 - t0) * 1000, 1), "geruest_ms": round((t2 - t1) * 1000, 1),
                  "bilder_ms": round((t3 - t2) * 1000, 1), "simulation_ms": round((t4 - t3) * 1000, 1),
                  "gesamt_ms": round((t4 - t0) * 1000, 1)}
    plan["stand"] = {"run": ein.run, "erzeugt": datetime.now().isoformat(timespec="seconds"), **erg.zeiten,
                     "montagefolge": folge.statistik, "nicht_im_aufbau": dict(ein.ohne),
                     "verbinde": ein.hat_verbinde, "eingeordnet": eingeordnet}
    return erg


def pruefe(erg: Ergebnis, schritt: str | None = None) -> list[dict[str, Any]]:
    """Simulation (alle Schritte oder einer); schreibt ``pruefung`` in die Schritte, liefert alle Befunde."""
    sim = Simulation(erg.ein, erg.wege)
    befunde = sim.pruefe(erg.plan, schritt)
    # Befunde aus der Montagefolge (Teil steckt fest) an den Schritt, der die Einheit einbaut
    for b in erg.folge.befunde:
        haupt = (b.get("teile") or [None])[0]
        for s in montage_schritte(erg.plan):
            if haupt in (s.get("neu") or []):
                if schritt is None or schritt == s["id"]:
                    befunde.setdefault(s["id"], []).append({**b, "schritt": s["id"]})
                break
    for sid_, bs in reihenfolge.verstoesse(erg.plan).items():
        if schritt is None or schritt == sid_:
            befunde.setdefault(sid_, []).extend(bs)
    for s in montage_schritte(erg.plan):  # Sichtbarkeit im Schrittbild (Agrawala: neue Teile mindestens 50 %)
        if schritt is not None and schritt != s["id"]:
            continue
        bild = s.get("bild") or {}
        for t, v in (bild.get("sichtbarkeit") or {}).items():
            tt = erg.ein.teile.get(t)
            if v >= 0.5 or (tt is not None and tt.rolle == "vm"):
                continue  # Verbindungsmittel zeigt der Stapel der Explosion; gemeldet werden Hauptteile
            alt = (bild.get("besser") or {}).get(t)
            loesung = ("Blickrichtung ändern (bauplan_bearbeiten bild): von "
                       + _auge_text(alt["auge"]) + f" ist es zu {round(alt['sichtbarkeit'] * 100)} % sichtbar"
                       if alt else "Explosion vergrößern oder den Schritt teilen, damit das Teil frei steht")
            befunde.setdefault(s["id"], []).append({
                "art": "verdeckt", "teile": [t], "schwere": "hinweis", "schritt": s["id"], "ort": None,
                "wert": {"sichtbarkeit": v}, "loesung": loesung,
                "text": f"{t.rsplit('/', 1)[-1]} ist im Schrittbild nur zu {round(v * 100)} % zu sehen."})
    befund_ids(befunde)
    for _, s in datei.alle_schritte(erg.plan):
        if s.get("id") in befunde and (schritt is None or schritt == s["id"]):
            s["pruefung"] = befunde[s["id"]]
        elif schritt is None:
            s.setdefault("pruefung", [])
    erg.plan.setdefault("stand", {})["simulation_ms"] = sim.dauer_ms
    return [b for bs in befunde.values() for b in bs]


def _auge_text(auge: list[float]) -> str:
    x, y, z = auge
    return ("oben" if z > 0 else "unten") + " " + ("vorn" if y < 0 else "hinten") + " " + ("links" if x < 0 else "rechts")


def strichbilder(erg: Ergebnis, nur: list[str] | None = None) -> list[dict[str, Any]]:
    """Strichbilder aller Schritte (zwischengespeichert je Schritt und Bildparametern)."""
    out = []
    for _, s in datei.alle_schritte(erg.plan):
        if nur is not None and s.get("id") not in nur:
            continue
        if not s.get("bild"):
            continue
        key = f"{s['id']}|{hash(repr((s.get('bild'), s.get('neu'))))}"
        b = erg.bilder_cache.get(key)
        if b is None:
            try:
                b = strichbild(erg.ein, s)
            except Exception as exc:  # noqa: BLE001 - ein Bild darf den Bauplan nicht verhindern
                b = {"schritt": s["id"], "rahmen": [0, 0, 180, 120], "massstab": 1.0, "linien": {},
                     "fehler": f"{type(exc).__name__}: {exc}"}
            erg.bilder_cache[key] = b
        out.append(b)
    return out
