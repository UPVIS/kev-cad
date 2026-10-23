"""Prüfer „statik“ nach jedem Lauf (Rechenprozess) und Szenarien auf Anfrage.

Nach den anderen Prüfern (Durchdringung, Stand, Montage, Druck) baut ``pruefe`` das Statikmodell aus Körpern und
Kontakten, nimmt die Szenarien aus model.py (``kevcad.statik``) und die Standardszenarien (T3) und rechnet S0 und S1.
Das Ergebnis steht in ``ergebnis["statik"]`` (CHECK-Kopf, Feld ``statik``); die Laufzeit macht daraus die Nachricht
STATICS an die App. Rote und gelbe Urteile werden Befunde (``statik_*``), die den Export nicht sperren (T7).

``LETZTER`` hält Modell, Körper und Katalog des letzten geprüften Laufs: ``rechne_auftrag`` (über ``dienst.py`` aus der
Laufzeit) rechnet damit ein neues Szenario ohne neuen Lauf.
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
    s4: dict[str, Any] = field(default_factory=dict)  # Stufe 4: st.kontakt und st.festigkeit aus model.py


LETZTER = Letzter()


def szenarien_fuer(ctx_erkl: dict[str, Any], params: dict[str, Any] | None, modell: Any) -> tuple[list[Any], dict]:
    from kevcad_kernel.statik import szenario as sc
    from kevcad_kernel.statik.modell import auf_rollen, oberste_teile

    eigene, einst = sc.aus_modell(ctx_erkl.get("statik") or [])
    std = sc.standard(eigene, params, auf_rollen(modell), oberste_teile(modell))
    return std + eigene, einst


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
    m = md.baue(ctx.koerper, ctx.paare, ctx.erklaerungen, ctx.ergebnis.get("stand") or {}, ctx.ergebnis.get("druck"),
                katalog, befestigt, untergrund)
    if not m.teile:
        return []
    ctx.abbrechen()
    szen, einst = szenarien_fuer(ctx.erklaerungen, ctx.optionen.get("params"), m)
    erg = rechne_alles(m, szen, katalog, ctx.koerper)
    ctx.abbrechen()
    s4 = stufe4_aus(ereignisse, m)
    if s4.get("auftraege") or s4.get("kontakte"):
        erg["s4"] = s4  # die Laufzeit rechnet st.festigkeit(…) nach dem Festkörper im Hintergrund (Stufe 4)
    global LETZTER
    LETZTER = Letzter(m, szen, dict(ctx.koerper), katalog, erg, set(ctx.koerper), befestigt,
                      ctx.optionen.get("run"), s4)
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
    out: dict[str, Any] = {"kontakte": [], "auftraege": [], "warnungen": []}
    for e in ereignisse or []:
        was = e.get("was")
        if was == "kontakt":
            unbekannt = [t for t in (e.get("teile") or []) + (e.get("gegen") or []) if not m.aufloesen(str(t))]
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
