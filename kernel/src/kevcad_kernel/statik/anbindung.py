"""Prüfer „statik“ nach jedem Lauf (Rechenprozess) und Szenarien auf Anfrage.

Nach den anderen Prüfern (Durchdringung, Stand, Montage, Druck) baut ``pruefe`` das Statikmodell aus Körpern und
Kontakten, nimmt die Szenarien aus model.py (``kevcad.statik``) und die Standardszenarien (T3) und rechnet S0 und S1.
Das Ergebnis steht in ``ergebnis["statik"]`` (CHECK-Kopf, Feld ``statik``); die Laufzeit macht daraus die Nachricht
STATICS an die App. Rote und gelbe Urteile werden Befunde (``statik_*``), die den Export nicht sperren (T7).

``LETZTER`` hält Modell, Körper und Katalog des letzten geprüften Laufs: ``rechne_auftrag`` (über ``dienst.py`` aus der
Laufzeit) rechnet damit ein neues Szenario ohne neuen Lauf.

Simulation (PLAN-SIMULATION.md): Lastfälle, Lasten und Lager aus ``<projekt>/simulation.json`` (Bereich „Simulation“ der
App, MCP ``simulation_aendern``) kommen bei jedem Lauf dazu (``simulation/zuordnung.py``); gleiche Namen wie in model.py:
die Fassung der App gewinnt. ``neu_mit_simulation`` rechnet nach einer Änderung in der App alles noch einmal mit dem
Modell des letzten Laufs (Lager ändern das Statikmodell, deshalb auch das Modell neu), ohne model.py auszuführen. Im
Ergebnis steht ``simulation`` (Zustand je Last und Lager, abgeleitete Lager, Hinweise) für die Nachricht SIM.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from kevcad_kernel.pruefung import befund as bf
from kevcad_kernel.pruefung.pruefer import PruefKontext

ARTEN = {
    "statik_festigkeit": ("Statik: hält nicht", "Statik: halten nicht"),
    "statik_knicken": ("Statik: knickt", "Statik: knicken"),
    "statik_durchbiegung": ("Statik: biegt sich zu stark", "Statik: biegen sich zu stark"),
    "statik_kippen": ("Statik: kippt", "Statik: kippen"),
    "statik_rutschen": ("Statik: rutscht", "Statik: rutschen"),
    "statik_schraube": ("Statik: Schrauben knapp", "Statik: Schrauben knapp"),
    "statik_bauteil": ("Statik: Bauteil hält nicht", "Statik: Bauteile halten nicht"),
    "statik_ueberdimensioniert": ("überdimensioniert", "überdimensioniert"),
    "statik_stabwerk": ("Statik: Stabwerk nicht gerechnet", "Statik: Stabwerk nicht gerechnet"),
    "statik_szenario": ("Statik: Szenario ungültig", "Statik: Szenarien ungültig"),
    # Stufe 2 (Ablauf, statik/dynamik): aus dem Ergebnis von dynamik() und den Abläufen aus model.py
    "statik_dyn_kippen": ("Ablauf: kippt", "Ablauf: kippen"),
    "statik_dyn_ladung": ("Ablauf: Ladung springt heraus", "Ablauf: Ladung springt heraus"),
    "statik_dyn_rutschen": ("Ablauf: rutscht", "Ablauf: rutschen"),
    # Stufe 3 (Festkörper, statik/festkoerper): aus dem Ergebnis von festigkeit() und der Rechnung nach dem Lauf
    "statik_festkoerper": ("Statik: Bauteil hält nicht (FEM)", "Statik: Bauteile halten nicht (FEM)"),
}
for _art, _text in ARTEN.items():
    bf.ART_TEXT.setdefault(_art, _text)


@dataclass
class Letzter:
    modell: Any = None
    szenarien: list[Any] = field(default_factory=list)
    koerper: dict[str, Any] = field(default_factory=dict)
    katalog: Any = None
    ergebnis: dict[str, Any] | None = None
    namen: set[str] = field(default_factory=set)
    befestigt: dict[str, str] = field(default_factory=dict)  # für S2: an der Umgebung befestigte Teile
    run: int | None = None
    # Simulation: was ``neu_mit_simulation`` zum erneuten Aufbau braucht (Prüfstand des Laufs)
    paare: dict[frozenset, Any] = field(default_factory=dict)
    erklaerungen: dict[str, Any] = field(default_factory=dict)
    stand: dict[str, Any] = field(default_factory=dict)
    druck: dict[str, Any] | None = None
    params: dict[str, Any] = field(default_factory=dict)
    projekt: str | None = None
    vorbereitet: Any = None  # simulation.zuordnung.Vorbereitet


LETZTER = Letzter()


def szenarien_fuer(ctx_erkl: dict[str, Any], params: dict[str, Any] | None, modell: Any,
                   vorbereitet: Any = None) -> tuple[list[Any], dict]:
    """Szenarien eines Laufs: Standard, model.py und (``vorbereitet``) die Lastfälle der App; gleicher Name wie in
    model.py: die App gewinnt (Hinweis in ``einst["hinweise"]``)."""
    from kevcad_kernel.statik import szenario as sc
    from kevcad_kernel.statik.modell import auf_rollen, oberste_teile

    eigene, einst = sc.aus_modell(ctx_erkl.get("statik") or [])
    einst.setdefault("hinweise", [])
    if vorbereitet is not None and vorbereitet.szenarien:
        app = []
        for d in vorbereitet.szenarien:
            try:
                app.append(sc.szenario_aus(d, "app"))
            except ValueError as exc:
                einst["warnungen"].append({"text": f"Lastfall „{d.get('name')}“ (App): {exc}", "zeile": None})
        namen = {s.name for s in app}
        for s in eigene:
            if s.name in namen:
                einst["hinweise"].append(f"Lastfall „{s.name}“ aus der App ersetzt den gleichnamigen aus model.py"
                                         + (f" (Zeile {s.zeile})" if s.zeile else ""))
                einst.setdefault("ersetzt", []).append({"name": s.name, "zeile": s.zeile,
                                                        "art": "dynamisch" if s.dynamisch else "statisch"})
        eigene = [s for s in eigene if s.name not in namen] + app
    std = sc.standard(eigene, params, auf_rollen(modell), oberste_teile(modell))
    return std + eigene, einst


def simulation_vorbereiten(projekt: str | None, koerper: dict[str, Any], ereignisse: list[dict[str, Any]]) -> Any:
    """``simulation.json`` lesen und gegen den aktuellen Stand zuordnen; dazu die Lager aus model.py (``st.lager``)."""
    from kevcad_kernel.simulation import datei, zuordnung
    from kevcad_kernel.statik import szenario as sc

    _, einst = sc.aus_modell(ereignisse or [])
    doc = datei.lies(projekt)
    return zuordnung.vorbereiten(doc, koerper, einst.get("lager"), einst.get("ziel"))


def _abgeleitet_kontakt(m: Any, erg: dict[str, Any]) -> list[dict[str, Any]]:
    """Abgeleitete Lager im Bauteil-Nachweis und in der FEM: Nachbarn, die ein Teil mit Last halten (``kontakt:…``),
    dazu die ausgeschalteten (damit die App sie wieder einschalten kann)."""
    out: dict[str, dict[str, Any]] = {}
    for e in erg.get("szenarien") or []:
        for b in e.get("bauteile") or []:
            teil = b.get("teil")
            for x in b.get("nachbarn") or []:
                if str(x).startswith("Lager: "):
                    continue
                key = f"kontakt:{teil}|{x}"
                out.setdefault(key, {"id": key, "art": "kontakt", "teil": teil, "nachbar": x,
                                     "text": f"{str(teil).rsplit('/', 1)[-1]} wird von {str(x).rsplit('/', 1)[-1]} "
                                             "gehalten (Kontakt)", "aktiv": True, "szenarien": []})
                out[key]["szenarien"].append(e.get("name"))
    for key in sorted(m.aus):
        if key.startswith("kontakt:") and key not in out:
            teil, _, x = key[len("kontakt:"):].partition("|")
            out[key] = {"id": key, "art": "kontakt", "teil": teil, "nachbar": x, "aktiv": False, "szenarien": [],
                        "text": f"{teil.rsplit('/', 1)[-1]} wird von {x.rsplit('/', 1)[-1]} gehalten (Kontakt, aus)"}
    return list(out.values())


def simulation_ergebnis(m: Any, v: Any, erg: dict[str, Any], einst: dict[str, Any]) -> dict[str, Any]:
    """Feld ``simulation`` im Statik-Ergebnis: Zustand je Last und Lager der App, alle Lager im Modell, abgeleitete
    Lager, Hinweise (für SIM)."""
    if v is None:
        return {}
    hinweise = list(v.hinweise) + list(einst.get("hinweise") or [])
    if v.fehler:
        hinweise.insert(0, v.fehler)
    return {"stand": v.stand, "zustand": v.zustand, "lager": [L.kurz() for L in m.lager_explizit],
            "abgeleitet": list(m.abgeleitet) + _abgeleitet_kontakt(m, erg), "hinweise": hinweise,
            "signaturen": v.signaturen, "app": [d.get("name") for d in v.szenarien],
            "ersetzt": list(einst.get("ersetzt") or [])}


def pruefe(ctx: PruefKontext) -> list[dict[str, Any]]:
    """Prüffunktion „statik“ (registriert in pruefung/lauf.py, nach allen anderen)."""
    if ctx.optionen.get("statik") is False:
        return []
    t0 = time.perf_counter()
    from kevcad_kernel.statik import modell as md
    from kevcad_kernel.statik.rechnen import befunde, rechne_alles

    katalog = ctx.optionen.get("katalog")
    ereignisse = ctx.erklaerungen.get("statik") or []
    untergrund = None
    for e in ereignisse:
        if e.get("was") == "untergrund":
            untergrund = e.get("material")
    befestigt = ctx.befestigt()
    projekt = ctx.optionen.get("projekt")
    try:
        vorb = simulation_vorbereiten(projekt, ctx.koerper, ereignisse)  # Simulation: App-Lastfälle und Lager
    except Exception as exc:  # noqa: BLE001 - eine kaputte simulation.json darf die Statik nicht verhindern
        from kevcad_kernel.simulation.zuordnung import Vorbereitet

        vorb = Vorbereitet(fehler=f"simulation.json nicht ausgewertet: {type(exc).__name__}: {exc}")
    m = md.baue(ctx.koerper, ctx.paare, ctx.erklaerungen, ctx.ergebnis.get("stand") or {}, ctx.ergebnis.get("druck"),
                katalog, befestigt, untergrund, vorb.lager, vorb.aus)
    if not m.teile:
        return []
    ctx.abbrechen()
    szen, einst = szenarien_fuer(ctx.erklaerungen, ctx.optionen.get("params"), m, vorb)
    erg = rechne_alles(m, szen, katalog, ctx.koerper)
    erg["simulation"] = simulation_ergebnis(m, vorb, erg, einst)
    ctx.abbrechen()
    global LETZTER
    LETZTER = Letzter(m, szen, dict(ctx.koerper), katalog, erg, set(ctx.koerper), _mit_lagern(befestigt, vorb),
                      ctx.optionen.get("run"), dict(ctx.paare), dict(ctx.erklaerungen),
                      dict(ctx.ergebnis.get("stand") or {}), ctx.ergebnis.get("druck"),
                      dict(ctx.optionen.get("params") or {}), projekt, vorb)
    ctx.ergebnis["statik"] = erg
    ctx.zeiten["statik"] = (time.perf_counter() - t0) * 1000
    out = befunde(erg)
    for w in einst.get("warnungen") or []:
        out.append(bf.befund("statik_szenario", ["model.py"], "warnung", w["text"]
                             + (f" [model.py Zeile {w['zeile']}]" if w.get("zeile") else ""),
                             "Angaben in st.szenario/st.last korrigieren (Kraft in N als (fx, fy, fz) oder kg=…).",
                             wert={"pruefung": "statik"}))
    return out


def _mit_lagern(befestigt: dict[str, str], vorb: Any) -> dict[str, str]:
    """Für den Ablauf (S2): Teile mit festem Lager gelten wie ``befestigt``."""
    out = dict(befestigt)
    for L in getattr(vorb, "lager", None) or []:
        if L.art == "fest":
            out.setdefault(L.teil, f"Lager {L.id} (fest)")
    return out


def neu_mit_simulation() -> dict[str, Any]:
    """Nach einer Änderung an ``simulation.json``: Lager und Lastfälle neu zuordnen, das Statikmodell mit dem
    Prüfstand des letzten Laufs neu aufbauen und alle Szenarien rechnen (ohne model.py). Ergebnis wie
    ``ergebnis["statik"]`` mit ``simulation``."""
    from kevcad_kernel.statik import modell as md
    from kevcad_kernel.statik.rechnen import rechne_alles

    global LETZTER
    st = LETZTER
    if st.modell is None:
        return {"stand": "failed", "meldung": "Noch kein Statikmodell: erst model.py laufen lassen."}
    ereignisse = st.erklaerungen.get("statik") or []
    untergrund = next((e.get("material") for e in ereignisse if e.get("was") == "untergrund"), None)
    vorb = simulation_vorbereiten(st.projekt, st.koerper, ereignisse)
    befestigt = {n: g for n, g in st.befestigt.items() if not str(g).startswith("Lager ")}
    m = md.baue(st.koerper, st.paare, st.erklaerungen, st.stand, st.druck, st.katalog, befestigt, untergrund,
                vorb.lager, vorb.aus)
    szen, einst = szenarien_fuer(st.erklaerungen, st.params, m, vorb)
    erg = rechne_alles(m, szen, st.katalog, st.koerper)
    erg["simulation"] = simulation_ergebnis(m, vorb, erg, einst)
    LETZTER = Letzter(m, szen, st.koerper, st.katalog, erg, st.namen, _mit_lagern(befestigt, vorb), st.run,
                      st.paare, st.erklaerungen, st.stand, st.druck, st.params, st.projekt, vorb)
    return erg


def rechne_auftrag(auftrag: dict[str, Any]) -> dict[str, Any]:
    """Szenario auf Anfrage mit dem Modell des letzten Laufs: ``{"szenario": {...}}`` (wie MCP ``szenario_rechnen``)
    oder ``{"neu": true}`` (alle Szenarien des Laufs noch einmal). Liefert das Ergebnis wie ``ergebnis["statik"]``,
    das neue Szenario zuerst und als ``aktiv``."""
    from kevcad_kernel.statik import szenario as sc
    from kevcad_kernel.statik.rechnen import rechne_alles

    st = LETZTER
    if st.modell is None:
        return {"stand": "failed", "meldung": "Noch kein Statikmodell: erst run aufrufen (die Statik rechnet nach jedem "
                                             "Lauf mit)."}
    if auftrag.get("szenario"):
        neu = sc.szenario_aus(auftrag["szenario"], "agent")
        unbekannt = [t for l in neu.lasten for t in l.teile + l.gegen if not st.modell.aufloesen(t)]
        if unbekannt:
            import difflib

            tips = difflib.get_close_matches(unbekannt[0], list(st.modell.teile), n=3, cutoff=0.5)
            return {"stand": "failed", "meldung": f"Teil {unbekannt[0]!r} gibt es nicht"
                    + (f"; meinten Sie {', '.join(repr(t) for t in tips)}?" if tips else "")
                    + " (Namen wie in show(), auch Gruppen wie \"Kugelschieber/\")."}
        # Nur das neue Szenario rechnen; die übrigen stehen schon im Ergebnis des Laufs (und früherer Anfragen)
        erg = rechne_alles(st.modell, [neu], st.katalog, st.koerper, aktiv=neu.name,
                           alternativen=bool(auftrag.get("alternativen", True)))
        if erg.get("stand") == "done" and not auftrag.get("allein") and st.ergebnis:
            alt = st.ergebnis
            erg = {**alt, "aktiv": neu.name, "ms": erg.get("ms"), "zeiten_ms": erg.get("zeiten_ms"),
                   "szenarien": erg["szenarien"] + [e for e in alt.get("szenarien") or [] if e.get("name") != neu.name],
                   "vereinfachungen": list(dict.fromkeys(list(alt.get("vereinfachungen") or [])
                                                         + list(erg.get("vereinfachungen") or [])))}
            # bis zum nächsten Lauf gehört das Szenario dazu (die App zeigt es in der Liste, statik() kennt es)
            st.szenarien = [s for s in st.szenarien if s.name != neu.name] + [neu]
            st.ergebnis = erg
    else:
        erg = rechne_alles(st.modell, st.szenarien, st.katalog, st.koerper)
    return erg
