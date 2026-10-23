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

Lager je Lastfall (simulation2): Ein Lager gilt in allen Szenarien oder nur in den genannten. Je verschiedener Menge
gültiger Lager entsteht ein eigenes Statikmodell (``modelle_bauen``), gerechnet wird je Gruppe (``rechne_gruppen``) und
zu einem Ergebnis zusammengeführt; ohne Lager je Lastfall ist es genau ein Modell wie bisher. ``LETZTER.modell`` ist das
Modell mit den Lagern für alle Szenarien, ``LETZTER.modell_fuer(name)`` das eines Szenarios (Festkörper, Topologie,
Grenze, Ablauf). Je Szenario steht ``lager_ids`` im Ergebnis (STATICS ``lager``).
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
    # Lager je Lastfall: Modell und befestigte Teile je Szenario (fehlt der Name: ``modell`` bzw. ``befestigt``)
    modelle: dict[str, Any] = field(default_factory=dict)
    befestigt_je: dict[str, dict[str, str]] = field(default_factory=dict)
    s4: dict[str, Any] = field(default_factory=dict)  # Stufe 4: st.kontakt und st.festigkeit aus model.py

    def modell_fuer(self, szenario: str | None) -> Any:
        """Statikmodell eines Szenarios (mit den Lagern, die dort gelten)."""
        return self.modelle.get(szenario, self.modell) if szenario is not None else self.modell

    def befestigt_fuer(self, szenario: str | None) -> dict[str, str]:
        """Für den Ablauf (S2): an der Umgebung befestigte Teile, mit den festen Lagern dieses Szenarios."""
        return self.befestigt_je.get(szenario, self.befestigt) if szenario is not None else self.befestigt


LETZTER = Letzter()


def _gruppen(lager: list[Any], szen: list[Any]) -> dict[tuple[str, ...], list[Any]]:
    """Szenarien nach der Menge der Lager, die in ihnen gelten (Reihenfolge der Szenarien bleibt je Gruppe)."""
    out: dict[tuple[str, ...], list[Any]] = {}
    for sz in szen:
        key = tuple(L.id for L in lager if L.gilt_fuer(sz.name))
        out.setdefault(key, []).append(sz)
    return out


def modelle_bauen(baue: Any, lager: list[Any], szen: list[Any], m0: Any) -> tuple[dict[str, Any], dict]:
    """Je Gruppe gleicher Lager ein Statikmodell (``baue(lager)``); ``m0`` ist das mit den Lagern für alle Szenarien.
    Rückgabe: (Szenario → Modell, Gruppen)."""
    gruppen = _gruppen(lager, szen)
    alle = tuple(L.id for L in lager if L.szenarien is None)
    modelle: dict[str, Any] = {}
    for key, szs in gruppen.items():
        m = m0 if key == alle else baue([L for L in lager if L.id in key])
        for sz in szs:
            modelle[sz.name] = m
    return modelle, gruppen


def rechne_gruppen(modelle: dict[str, Any], szen: list[Any], katalog: Any, koerper: dict[str, Any] | None,
                   m0: Any, **kw: Any) -> dict[str, Any]:
    """S0 und S1 je Gruppe von Szenarien mit demselben Statikmodell, zusammengeführt wie ein Ergebnis von
    ``rechne_alles``; je Szenario ``lager_ids`` (ausdrückliche Lager, die dort gelten)."""
    from kevcad_kernel.statik.bewertung import RANG
    from kevcad_kernel.statik.rechnen import rechne_alles

    reihen: dict[int, tuple[Any, list[Any]]] = {}
    for sz in szen:
        m = modelle.get(sz.name, m0)
        reihen.setdefault(id(m), (m, []))[1].append(sz)
    if len(reihen) <= 1:
        m = next(iter(reihen.values()))[0] if reihen else m0
        erg = rechne_alles(m, szen, katalog, koerper, **kw)
        ids = [L.id for L in getattr(m, "lager_explizit", None) or []]
        for e in erg.get("szenarien") or []:
            e["lager_ids"] = ids
        return erg
    teil_erg: list[tuple[Any, dict[str, Any]]] = []
    for m, szs in reihen.values():
        e = rechne_alles(m, szs, katalog, koerper, **{k: v for k, v in kw.items() if k != "aktiv"})
        for x in e.get("szenarien") or []:
            x["lager_ids"] = [L.id for L in m.lager_explizit]
        teil_erg.append((m, e))
    basis = next((e for m, e in teil_erg if m is m0), teil_erg[0][1])
    je = {x["name"]: x for _, e in teil_erg for x in e.get("szenarien") or []}
    out_sz = [je[sz.name] for sz in szen if sz.name in je]
    ueber: dict[str, Any] = {}
    for _, e in teil_erg:
        for u in e.get("ueberdimensioniert") or []:
            ueber.setdefault(u.get("text"), u)
    aktiv = kw.get("aktiv")
    if aktiv is None:
        mit = [x for x, sz in zip(out_sz, szen) if sz.hat_lasten] or out_sz
        aktiv = max(mit, key=lambda x: RANG.get(x.get("ampel"), 0))["name"] if mit else None
    zeiten: dict[str, float] = {}
    for _, e in teil_erg:
        for k, v in (e.get("zeiten_ms") or {}).items():
            zeiten[k] = round(zeiten.get(k, 0.0) + float(v or 0.0), 1)
    return {**basis, "aktiv": aktiv, "szenarien": out_sz, "ueberdimensioniert": list(ueber.values()),
            "vereinfachungen": list(dict.fromkeys(v for _, e in teil_erg for v in e.get("vereinfachungen") or [])),
            "zeiten_ms": zeiten, "ms": round(sum(float(e.get("ms") or 0.0) for _, e in teil_erg), 1),
            "lager_gruppen": len(teil_erg)}


def _lager_hinweise(lager: list[Any], szen: list[Any], einst: dict[str, Any]) -> None:
    """Lager je Lastfall: Namen, die es im Lauf nicht gibt."""
    namen = {s.name for s in szen}
    for L in lager:
        for n in L.szenarien or []:
            if n not in namen:
                einst.setdefault("hinweise", []).append(f"Lager {L.id}: Lastfall „{n}“ gibt es nicht (zählt dort nicht)")


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


def simulation_ergebnis(m: Any, v: Any, erg: dict[str, Any], einst: dict[str, Any],
                        modelle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Feld ``simulation`` im Statik-Ergebnis: Zustand je Last und Lager der App, alle Lager im Modell, abgeleitete
    Lager, Hinweise (für SIM). ``modelle``: Lager je Lastfall, Modell je Szenario (``m`` hat die für alle)."""
    if v is None:
        return {}
    hinweise = list(v.hinweise) + list(einst.get("hinweise") or [])
    if v.fehler:
        hinweise.insert(0, v.fehler)
    abgeleitet = [dict(a) for a in m.abgeleitet]
    # Lager je Lastfall: ein Bodenlager, das nur in einigen Szenarien ersetzt ist, bleibt sichtbar, mit diesen Namen
    for name, mg in (modelle or {}).items():
        if mg is m:
            continue
        for a in mg.abgeleitet:
            if a.get("ersetzt"):
                for b in abgeleitet:
                    if b["id"] == a["id"]:
                        b.setdefault("ersetzt_in", [])
                        if name not in b["ersetzt_in"]:
                            b["ersetzt_in"].append(name)
    lager = [L for L in (getattr(v, "lager", None) or []) if L.teil in m.teile]
    return {"stand": v.stand, "zustand": v.zustand, "lager": [L.kurz() for L in lager],
            "abgeleitet": abgeleitet + _abgeleitet_kontakt(m, erg), "hinweise": hinweise,
            "signaturen": v.signaturen, "app": [d.get("name") for d in v.szenarien],
            "ersetzt": list(einst.get("ersetzt") or [])}


def pruefe(ctx: PruefKontext) -> list[dict[str, Any]]:
    """Prüffunktion „statik“ (registriert in pruefung/lauf.py, nach allen anderen)."""
    if ctx.optionen.get("statik") is False:
        return []
    t0 = time.perf_counter()
    from kevcad_kernel.statik import modell as md
    from kevcad_kernel.statik.rechnen import befunde

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
    def baue(lager: list[Any]) -> Any:
        return md.baue(ctx.koerper, ctx.paare, ctx.erklaerungen, ctx.ergebnis.get("stand") or {},
                       ctx.ergebnis.get("druck"), katalog, befestigt, untergrund, lager, vorb.aus)

    m = baue([L for L in vorb.lager if L.szenarien is None])  # Lager, die in allen Szenarien gelten
    if not m.teile:
        return []
    ctx.abbrechen()
    szen, einst = szenarien_fuer(ctx.erklaerungen, ctx.optionen.get("params"), m, vorb)
    modelle, _ = modelle_bauen(baue, vorb.lager, szen, m)
    _lager_hinweise(vorb.lager, szen, einst)
    erg = rechne_gruppen(modelle, szen, katalog, ctx.koerper, m)
    erg["simulation"] = simulation_ergebnis(m, vorb, erg, einst, modelle)
    ctx.abbrechen()
    s4 = stufe4_aus(ereignisse, m)
    if s4.get("auftraege") or s4.get("kontakte"):
        erg["s4"] = s4  # die Laufzeit rechnet st.festigkeit(…) nach dem Festkörper im Hintergrund (Stufe 4)
    global LETZTER
    LETZTER = Letzter(m, szen, dict(ctx.koerper), katalog, erg, set(ctx.koerper), _mit_lagern(befestigt, vorb),
                      ctx.optionen.get("run"), dict(ctx.paare), dict(ctx.erklaerungen),
                      dict(ctx.ergebnis.get("stand") or {}), ctx.ergebnis.get("druck"),
                      dict(ctx.optionen.get("params") or {}), projekt, vorb, modelle,
                      {sz.name: _mit_lagern(befestigt, vorb, sz.name) for sz in szen}, s4=s4)
    ctx.ergebnis["statik"] = erg
    ctx.zeiten["statik"] = (time.perf_counter() - t0) * 1000
    out = befunde(erg)
    for w in s4.get("warnungen") or []:
        out.append(bf.befund("statik_szenario", ["model.py"], "warnung", w,
                             "Namen wie in show() oder eine Gruppe angeben.", wert={"pruefung": "statik"}))
    for w in einst.get("warnungen") or []:
        out.append(bf.befund("statik_szenario", ["model.py"], "warnung", w["text"]
                             + (f" [model.py Zeile {w['zeile']}]" if w.get("zeile") else ""),
                             "Angaben in st.szenario/st.last korrigieren (Kraft in N als (fx, fy, fz) oder kg=…).",
                             wert={"pruefung": "statik"}))
    return out


def stufe4_aus(ereignisse: list[dict[str, Any]], m: Any) -> dict[str, Any]:
    """Stufe 4 aus model.py: ``st.kontakt(a, b, …)`` (Kontaktpaare mit Reibwert, Klemmkraft, Spiel) und
    ``st.festigkeit(teil, …)`` (Teile, die nach jedem Lauf mit CalculiX nachgerechnet werden)."""
    from kevcad_kernel.statik.ccx.auftrag import aufloesen

    out: dict[str, Any] = {"kontakte": [], "auftraege": [], "warnungen": []}
    for e in ereignisse or []:
        was = e.get("was")
        if was == "kontakt":
            unbekannt = [t for t in (e.get("teile") or []) + (e.get("gegen") or []) if not aufloesen(m, str(t))]
            if unbekannt:
                out["warnungen"].append(f"st.kontakt: Teil {unbekannt[0]!r} gibt es nicht")
                continue
            out["kontakte"].append({k: e.get(k) for k in ("teile", "gegen", "reibwert", "klemmkraft", "spiel",
                                                          "zeile")})
        elif was == "festigkeit":
            teile = [n for t in e.get("teile") or [] for n in m.aufloesen(str(t))]
            if not teile:
                out["warnungen"].append(f"st.festigkeit: Teil {(e.get('teile') or ['?'])[0]!r} gibt es nicht")
                continue
            out["auftraege"].append({**{k: e.get(k) for k in ("kontakt", "plastisch", "traglast", "beulen",
                                                              "klemmkraft", "reibwert", "szenario", "zeile")},
                                     "teile": teile})
    return out


def _mit_lagern(befestigt: dict[str, str], vorb: Any, szenario: str | None = None) -> dict[str, str]:
    """Für den Ablauf (S2): Teile mit festem Lager gelten wie ``befestigt`` (ohne ``szenario`` nur Lager für alle
    Szenarien, sonst die dort gültigen)."""
    out = dict(befestigt)
    for L in getattr(vorb, "lager", None) or []:
        gilt = L.szenarien is None if szenario is None else L.gilt_fuer(szenario)
        if L.art == "fest" and gilt:
            out.setdefault(L.teil, f"Lager {L.id} (fest)")
    return out


def neu_mit_simulation() -> dict[str, Any]:
    """Nach einer Änderung an ``simulation.json``: Lager und Lastfälle neu zuordnen, das Statikmodell mit dem
    Prüfstand des letzten Laufs neu aufbauen und alle Szenarien rechnen (ohne model.py). Ergebnis wie
    ``ergebnis["statik"]`` mit ``simulation``."""
    from kevcad_kernel.statik import modell as md

    global LETZTER
    st = LETZTER
    if st.modell is None:
        return {"stand": "failed", "meldung": "Noch kein Statikmodell: erst model.py laufen lassen."}
    ereignisse = st.erklaerungen.get("statik") or []
    untergrund = next((e.get("material") for e in ereignisse if e.get("was") == "untergrund"), None)
    vorb = simulation_vorbereiten(st.projekt, st.koerper, ereignisse)
    befestigt = {n: g for n, g in st.befestigt.items() if not str(g).startswith("Lager ")}

    def baue(lager: list[Any]) -> Any:
        return md.baue(st.koerper, st.paare, st.erklaerungen, st.stand, st.druck, st.katalog, befestigt, untergrund,
                       lager, vorb.aus)

    m = baue([L for L in vorb.lager if L.szenarien is None])
    szen, einst = szenarien_fuer(st.erklaerungen, st.params, m, vorb)
    modelle, _ = modelle_bauen(baue, vorb.lager, szen, m)
    _lager_hinweise(vorb.lager, szen, einst)
    erg = rechne_gruppen(modelle, szen, st.katalog, st.koerper, m)
    erg["simulation"] = simulation_ergebnis(m, vorb, erg, einst, modelle)
    LETZTER = Letzter(m, szen, st.koerper, st.katalog, erg, st.namen, _mit_lagern(befestigt, vorb), st.run,
                      st.paare, st.erklaerungen, st.stand, st.druck, st.params, st.projekt, vorb, modelle,
                      {sz.name: _mit_lagern(befestigt, vorb, sz.name) for sz in szen}, s4=st.s4)
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
        ids = [L.id for L in getattr(st.modell, "lager_explizit", None) or []]
        for e in erg.get("szenarien") or []:
            e["lager_ids"] = ids
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
        erg = rechne_gruppen(st.modelle, st.szenarien, st.katalog, st.koerper, st.modell)
    return erg
