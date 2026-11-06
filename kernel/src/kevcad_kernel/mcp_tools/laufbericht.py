"""Knappes Laufergebnis für den Agenten (V2-2).

``run`` liefert standardmäßig nur, was der Agent für den nächsten Schritt braucht: ok oder Fehler, Zahl der Teile,
welche Teile neu sind oder sich geändert haben (mit dem Unterschied zum letzten Lauf, den der Agent gesehen hat),
unveränderte nur als Zahl, neue oder geänderte Befunde zuerst (Inventar-Regel und Durchdringung vorn), bekannte nur
gezählt, den Prüfstand und die Zeiten in einer Zeile. Was der Agent gesehen hat, merkt sich ``Gedaechtnis`` je
Claude-Sitzung (nicht je Lauf des Kernels: Läufe aus der App oder vom Auto-Lauf hat der Agent nicht gesehen).

Budget (Zeichen): unveränderter Lauf 1 500, Parameteränderung an wenigen Teilen 4 000, kalter Lauf mit 134 Teilen
8 000 (Baugruppen statt Teileliste). Fehler im Lauf bleiben vollständig.
"""

from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from . import format as fmt

MAX_BEFUNDE = 8  # Arten neuer oder geänderter Fehler und Warnungen mit Lösung, der Rest gezählt
MAX_TEILE = 25  # geänderte oder neue Teile einzeln, darüber je Baugruppe
MAX_NAMEN = 6  # Namen in Aufzählungen
MAX_GRUPPEN = 14  # Baugruppen im kalten Lauf
TEILE_WIE_KALT = 0.3  # weniger gemeinsame Teile als dieser Anteil: wie ein erster Lauf berichten
STAERKE = {"fehler": 0, "warnung": 1, "hinweis": 2}
ART_VORN = ("inventar", "durchdringung")  # diese Befunde zuerst


# ---------------------------------------------------------------------------------------------------------------------
# Gedächtnis: was der Agent gesehen hat


@dataclass
class Stand:
    run: int | None = None
    teile: dict[str, dict[str, Any]] = field(default_factory=dict)  # Name → kompakte Daten samt Signatur
    befunde: set[str] = field(default_factory=set)  # Schlüssel (Art, Teile, Text) gesehener Befunde
    befund_arten: set[str] = field(default_factory=set)  # Kennung ohne Zahlen: für „geändert“
    warnungen: set[str] = field(default_factory=set)
    verstoesse: set[str] = field(default_factory=set)  # Inventar-Regel
    params: dict[str, Any] = field(default_factory=dict)
    stueckliste: dict[str, Any] | None = None
    statik: str | None = None
    animationen: tuple[str, ...] = ()
    kameras: tuple[str, ...] = ()


class Gedaechtnis:
    """Je Claude-Sitzung der zuletzt gesehene Stand (höchstens ``max_sitzungen``, älteste fallen heraus)."""

    def __init__(self, max_sitzungen: int = 16) -> None:
        self._staende: OrderedDict[str | None, Stand] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_sitzungen

    def holen(self, sitzung: str | None) -> Stand | None:
        with self._lock:
            return self._staende.get(sitzung)

    def merken(self, sitzung: str | None, stand: Stand) -> None:
        with self._lock:
            self._staende[sitzung] = stand
            self._staende.move_to_end(sitzung)
            while len(self._staende) > self._max:
                self._staende.popitem(last=False)

    def befunde_gesehen(self, sitzung: str | None, befunde: list[dict[str, Any]]) -> None:
        """Nach ``pruefen``: alle gezeigten Befunde gelten als bekannt."""
        with self._lock:
            stand = self._staende.get(sitzung)
            if stand is None:
                return
            for b in befunde:
                stand.befunde.add(befund_schluessel(b))
                stand.befund_arten.add(befund_kennung(b))

    def vergessen(self, sitzung: str | None = None, alle: bool = False) -> None:
        with self._lock:
            if alle:
                self._staende.clear()
            else:
                self._staende.pop(sitzung, None)


# ---------------------------------------------------------------------------------------------------------------------
# Teile


def _r(v: Any, n: int = 3) -> Any:
    if isinstance(v, (list, tuple)):
        return [_r(x, n) for x in v]
    if isinstance(v, float):
        return round(v, n)
    return v


def teil_kurz(p: dict[str, Any]) -> dict[str, Any]:
    """Kompakte Daten eines Teils mit Signatur: Form (Schlüssel aus dem Rechenprozess oder Maße), Material, Lager."""
    bb = p.get("bbox") or {}
    stock = p.get("stock") if isinstance(p.get("stock"), dict) else None
    out = {
        "min": _r(bb.get("min")), "max": _r(bb.get("max")), "size": _r(fmt.bbox_size(bb)),
        "volume": _r(p.get("volume"), 1), "mass": _r(p.get("mass"), 2), "material": p.get("material"),
        "stock": {k: stock.get(k) for k in ("id", "laenge", "gehrung") if stock.get(k) is not None} if stock else None,
        "druck": bool(p.get("druckteil")), "inventar": p.get("inventar"), "key": p.get("key"),
        "faces": p.get("faces"), "edges": p.get("edges"),
    }
    out["sig"] = json.dumps(out, sort_keys=True, default=str)
    return out


def gruppe(name: str) -> str:
    return name.split("/", 1)[0] if "/" in name else name


def _mm(size: Any) -> str:
    return " × ".join(fmt.num(v, 1) for v in size) + " mm" if isinstance(size, list) else "?"


def unterschied(alt: dict[str, Any], neu: dict[str, Any]) -> str:
    """Was sich an einem Teil geändert hat, kurz: Maße, Lage, Masse, Material, Lager, Inventar."""
    teile = []
    if alt.get("size") != neu.get("size"):
        teile.append(f"{_mm(neu.get('size'))} (vorher {_mm(alt.get('size'))})")
    elif alt.get("min") != neu.get("min") and isinstance(alt.get("min"), list) and isinstance(neu.get("min"), list):
        d = [round(b - a, 2) for a, b in zip(alt["min"], neu["min"])]
        teile.append(f"{_mm(neu.get('size'))}, verschoben um {fmt.vec(d)}")
    else:
        teile.append(_mm(neu.get("size")))
    if alt.get("mass") != neu.get("mass") and isinstance(neu.get("mass"), (int, float)):
        delta = (neu["mass"] - alt["mass"]) if isinstance(alt.get("mass"), (int, float)) else None
        teile.append(f"{fmt.num(neu['mass'], 1)} g" + (f" ({'+' if delta > 0 else '−'}{fmt.num(abs(delta), 1)} g)"
                                                        if delta else ""))
    elif alt.get("volume") != neu.get("volume") and isinstance(neu.get("volume"), (int, float)):
        teile.append(f"Volumen {fmt.num(neu['volume'], 0)} mm³ (vorher {fmt.num(alt.get('volume'), 0)})")
    if alt.get("material") != neu.get("material"):
        teile.append(f"Material {neu.get('material')} (vorher {alt.get('material')})")
    if alt.get("stock") != neu.get("stock") and neu.get("stock"):
        st = neu["stock"]
        teile.append(f"Lagerteil {st.get('id')}" + (f" {fmt.num(st['laenge'], 1)} mm" if st.get("laenge") else ""))
    if alt.get("inventar") != neu.get("inventar") and neu.get("inventar") == "fehlt":
        teile.append("NICHT AUS DEM INVENTAR")
    if len(teile) == 1 and alt.get("size") == neu.get("size") and alt.get("min") == neu.get("min"):
        teile.append("Form geändert, Hüllmaß gleich")
    return ", ".join(teile)


def neu_zeile(name: str, k: dict[str, Any]) -> str:
    bits = [_mm(k.get("size"))]
    if isinstance(k.get("mass"), (int, float)):
        bits.append(f"{fmt.num(k['mass'], 1)} g")
    if k.get("stock"):
        bits.append(f"Lagerteil {k['stock'].get('id')}")
    elif k.get("druck"):
        bits.append("Druckteil")
    elif k.get("material"):
        bits.append(str(k["material"]))
    if k.get("inventar") == "fehlt":
        bits.append("NICHT AUS DEM INVENTAR")
    return f"- {name} (neu): " + ", ".join(bits)


def gruppen_zeilen(teile: dict[str, dict[str, Any]], max_gruppen: int = MAX_GRUPPEN) -> list[str]:
    """Je Baugruppe (erster Namensteil): Zahl der Teile, Masse, Hüllmaß."""
    gruppen: dict[str, list[dict[str, Any]]] = {}
    for name, k in teile.items():
        gruppen.setdefault(gruppe(name), []).append(k)
    zeilen = []
    for g, ks in sorted(gruppen.items(), key=lambda x: (-len(x[1]), x[0]))[:max_gruppen]:
        mins = [k["min"] for k in ks if isinstance(k.get("min"), list)]
        maxs = [k["max"] for k in ks if isinstance(k.get("max"), list)]
        size = [round(max(m[i] for m in maxs) - min(m[i] for m in mins), 1) for i in range(3)] if mins else None
        masse = sum(k["mass"] for k in ks if isinstance(k.get("mass"), (int, float)))
        bits = [fmt.plural(len(ks), "Teil", "Teile")]
        if size:
            bits.append(_mm(size))
        if masse:
            bits.append(f"{fmt.num(masse / 1000, 2)} kg" if masse >= 1000 else f"{fmt.num(masse, 0)} g")
        fehlt = sum(1 for k in ks if k.get("inventar") == "fehlt")
        if fehlt:
            bits.append(f"{fehlt} nicht aus dem Inventar")
        zeilen.append(f"- {g}: " + ", ".join(bits))
    if len(gruppen) > max_gruppen:
        zeilen.append(f"- … und {len(gruppen) - max_gruppen} weitere")
    return zeilen


# ---------------------------------------------------------------------------------------------------------------------
# Befunde


_ZAHL = re.compile(r"[-−+]?\d[\d.,  ]*")


def befund_kennung(b: dict[str, Any]) -> str:
    """Kennung ohne Zahlen: gleicher Befund mit anderem Wert gilt als geändert."""
    art = b.get("art") or b.get("pruefung") or ""
    teile = "|".join(b.get("teile") or [])
    return f"{art}#{teile}#{b.get('schwere')}#{_ZAHL.sub('#', str(b.get('text') or ''))}"


def befund_schluessel(b: dict[str, Any]) -> str:
    art = b.get("art") or b.get("pruefung") or ""
    return f"{art}#{'|'.join(b.get('teile') or [])}#{b.get('schwere')}#{b.get('text')}#{b.get('loesung')}"


def befund_text(b: dict[str, Any], *, loesung: bool = True) -> str:
    schwere = {"fehler": "Fehler", "warnung": "Warnung", "hinweis": "Hinweis"}.get(b.get("schwere"), b.get("schwere"))
    text = f"- [{schwere}] {b.get('text', '')}"
    if b.get("soll") and b.get("ist") and b.get("pruefung") not in ("befestigung",):
        text += f" (Soll {b['soll']}, Ist {b['ist']})"
    if b.get("zeile"):
        text += f" [Zeile {b['zeile']}]"
    if loesung and b.get("loesung"):
        text += f"\n  Lösung: {b['loesung']}"
    return text


def befunde_des_laufs(res: dict[str, Any]) -> tuple[list[dict[str, Any]], str, bool]:
    """(Befunde, Prüfstand, vorläufig?). Mit fertiger Prüfung stehen dort alle Befunde (auch die der Bedingungen);
    läuft sie noch, sind es vorläufig die Befunde der Bedingungen aus dem Lauf. Vorläufig ist auch ein Zwischenstand
    (V2-1b): Was von Druck, Montage oder Statik fehlt, ist noch nicht gerechnet, nicht behoben."""
    from kevcad_kernel.pruefung.befund import OFFENE_PRUEFUNGEN

    pr = res.get("pruefung") if isinstance(res.get("pruefung"), dict) else None
    state = (pr or {}).get("state") or ("keine" if pr is None else "?")
    if pr is not None and state in ("done", "teilweise"):
        befunde = list(pr.get("befunde") or [])
        if state == "teilweise":  # Hinweise „wird im Hintergrund gerechnet“ stehen im Prüfstand
            befunde = [b for b in befunde if not (b.get("art") == "bewegungsraum" and b.get("schwere") == "hinweis"
                                                  and "im Hintergrund" in str(b.get("text") or ""))]
        return befunde, state, any(o in OFFENE_PRUEFUNGEN for o in pr.get("im_hintergrund") or ())
    bed = res.get("bedingungen") if isinstance(res.get("bedingungen"), dict) else None
    return list((bed or {}).get("befunde") or []), state, True


def befund_gruppen(befunde: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Gleichartige Befunde (gleiche Schwere, Art und Lösung bis auf Zahlen) zusammen, in der Reihenfolge des ersten."""
    gruppen: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for b in befunde:
        art = str(b.get("art") or b.get("pruefung") or "")
        key = (str(b.get("schwere")), art, _ZAHL.sub("#", str(b.get("loesung") or b.get("text") or "")))
        gruppen.setdefault(key, []).append(b)
    return list(gruppen.values())


def orte_text(befunde: list[dict[str, Any]]) -> str:
    """„Kamerahalter/Kameraträger (Druck) 3×, Kugelschieber/Stangenhalter vorn links (Druck)“."""
    zaehler_teile: dict[str, int] = {}
    for b in befunde:
        name = " ↔ ".join((b.get("teile") or ["?"])[:2])
        zaehler_teile[name] = zaehler_teile.get(name, 0) + 1
    teile = [f"{n} {k}×" if k > 1 else n for n, k in zaehler_teile.items()]
    return ", ".join(teile[:MAX_NAMEN]) + (f" und {len(teile) - MAX_NAMEN} weitere" if len(teile) > MAX_NAMEN else "")


def sortiert(befunde: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def rang(b: dict[str, Any]) -> tuple:
        art = b.get("art") or b.get("pruefung") or ""
        vorn = ART_VORN.index(art) if art in ART_VORN else len(ART_VORN)
        return STAERKE.get(b.get("schwere"), 3), vorn, art
    return sorted(befunde, key=rang)


def zaehler(befunde: list[dict[str, Any]]) -> dict[str, int]:
    out = {"fehler": 0, "warnung": 0, "hinweis": 0}
    for b in befunde:
        if b.get("schwere") in out:
            out[b["schwere"]] += 1
    return out


def zaehler_text(z: dict[str, int]) -> str:
    teile = [fmt.plural(z.get("fehler", 0), "Fehler", "Fehler") if z.get("fehler") else "",
             fmt.plural(z.get("warnung", 0), "Warnung", "Warnungen") if z.get("warnung") else "",
             fmt.plural(z.get("hinweis", 0), "Hinweis", "Hinweise") if z.get("hinweis") else ""]
    return ", ".join(t for t in teile if t) or "keine"


# ---------------------------------------------------------------------------------------------------------------------
# Bericht


def zeiten_zeile(z: dict[str, Any] | None, duration_ms: Any = None) -> str:
    z = z or {}
    teile = []
    for key, name in (("skript", "Modell"), ("run_end", "im Viewer"), ("zurueck", "Antwort"), ("pruefung", "Prüfung")):
        v = z.get(key)
        if isinstance(v, (int, float)):
            teile.append(f"{name} {fmt.num(v / 1000, 1)} s")
    if not teile and isinstance(duration_ms, (int, float)):
        teile.append(f"Dauer {fmt.ms_text(duration_ms)}")
    return "Zeiten: " + ", ".join(teile) if teile else ""


def pruefstand_zeile(res: dict[str, Any], state: str, befunde: list[dict[str, Any]]) -> str:
    pr = res.get("pruefung") if isinstance(res.get("pruefung"), dict) else {}
    z = zaehler(befunde)
    if state == "done":
        return f"Prüfung fertig: {zaehler_text(z)}."
    if state == "teilweise":
        from kevcad_kernel.pruefung.text import hintergrund_text

        return f"Prüfung teilweise ({zaehler_text(z)}): " + hintergrund_text(pr).replace("\n", " ")
    if state == "running":
        return ("Prüfung läuft noch im Hintergrund; vorläufig aus den Bedingungen: " + zaehler_text(z)
                + ". Vor dem Fertigmelden pruefen() aufrufen.")
    if state == "failed":
        return f"Prüfung fehlgeschlagen: {pr.get('message') or 'ohne Meldung'}."
    if state == "cancelled":
        return "Prüfung abgebrochen (neuerer Lauf)."
    return f"Prüfung: {zaehler_text(z)}." if befunde else ""


def stueckliste_kurz(bom: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(bom, dict):
        return None
    t = bom.get("totals") or {}
    out = {k: t.get(k) for k in ("positionen", "teile", "kg", "preis")}
    if isinstance(bom.get("einkauf"), dict):
        out["einkauf"] = {k: bom["einkauf"].get(k) for k in ("positionen", "summe")}
    return out


def stueckliste_zeile(neu: dict[str, Any], alt: dict[str, Any] | None) -> str:
    from kevcad_kernel.bom import de_num, eur

    text = (f"Stückliste: {fmt.plural(int(neu.get('positionen') or 0), 'Position', 'Positionen')}, "
            f"{de_num(neu.get('kg') or 0, 2)} kg")
    if neu.get("preis") is not None:
        text += f", {eur(neu['preis'])}"
        if alt and alt.get("preis") is not None and alt.get("preis") != neu.get("preis"):
            text += f" (vorher {eur(alt['preis'])})"
    e = neu.get("einkauf")
    if isinstance(e, dict) and e.get("positionen") is not None:
        text += f"; Einkauf {fmt.plural(int(e['positionen']), 'Position', 'Positionen')}"
        if e.get("summe") is not None:
            text += f", {eur(e['summe'])}"
    return text + " (Details: parts(stueckliste=true))."


def bericht(res: dict[str, Any], vorher: Stand | None, detail: str = "kurz",
            gegeben: dict[str, Any] | None = None) -> tuple[str, dict[str, Any], bool, Stand | None]:
    """(Text, kompakte Daten, isError, neuer Stand) eines Laufs. ``vorher``: was der Agent zuletzt gesehen hat,
    ``gegeben``: die Parameter, die der Agent mit diesem Aufruf überschrieben hat."""
    if res.get("ok") is False:  # Fehler bleiben vollständig, das Gedächtnis bleibt beim letzten guten Lauf
        text, data, _ = fmt.run_summary(res)
        return text, data, True, None
    run_no = res.get("run")
    parts = [p for p in res.get("parts") or [] if isinstance(p, dict) and p.get("name")]
    teile = {str(p["name"]): teil_kurz(p) for p in parts}
    alt = vorher.teile if vorher is not None else {}
    gemeinsam = len(set(alt) & set(teile))
    kalt = vorher is None or (teile and gemeinsam < TEILE_WIE_KALT * len(teile))
    neu_namen = [n for n in teile if n not in alt]
    geaendert = [n for n in teile if n in alt and alt[n]["sig"] != teile[n]["sig"]]
    entfernt = [n for n in alt if n not in teile]
    gleich = len(teile) - len(neu_namen) - len(geaendert)

    befunde, state, vorlaeufig = befunde_des_laufs(res)
    verstoesse = [str(v) for v in res.get("inventar_verstoesse") or []]
    alt_v = vorher.verstoesse if vorher is not None else set()
    neue_v = [v for v in verstoesse if v not in alt_v]
    befunde = sortiert(befunde)
    gesehen = vorher.befunde if vorher is not None else set()
    arten = vorher.befund_arten if vorher is not None else set()
    neue = [b for b in befunde if befund_schluessel(b) not in gesehen]
    bekannt = [b for b in befunde if befund_schluessel(b) in gesehen]
    # behoben nur mit fertiger Prüfung: solange sie läuft, sind es vorläufig nur die Befunde der Bedingungen
    # (gezählt nach Kennung ohne Zahlen: ein Befund mit neuem Wert ist geändert, nicht behoben)
    behoben = (len(arten - {befund_kennung(b) for b in befunde})
               if vorher is not None and not vorlaeufig else 0)
    fehler_offen = [b for b in befunde if b.get("schwere") == "fehler"]

    # Kopf
    if kalt:
        kopf = f"Lauf {run_no}: {fmt.plural(len(teile), 'Teil', 'Teile')}"
        n_gruppen = len({gruppe(n) for n in teile})
        kopf += f" in {fmt.plural(n_gruppen, 'Baugruppe', 'Baugruppen')}" if n_gruppen < len(teile) else ""
        kopf += " (erster Lauf, den du siehst)." if vorher is None else " (fast alles neu)."
    else:
        bits = [fmt.plural(len(teile), "Teil", "Teile")]
        if neu_namen:
            bits.append(f"{len(neu_namen)} neu")
        if geaendert:
            bits.append(f"{len(geaendert)} geändert")
        if entfernt:
            bits.append(f"{len(entfernt)} entfernt")
        bits.append(f"{gleich} unverändert" if (neu_namen or geaendert or entfernt) else "nichts geändert")
        kopf = f"Lauf {run_no}: " + ", ".join(bits) + "."
    zeilen = [kopf]

    # Inventar-Regel zuerst: neue Verstöße mit Abhilfe, bekannte gezählt
    if neue_v:
        from kevcad_kernel.bom import inventory_text

        zeilen.append(inventory_text(neue_v) + " Die Geometrie ist im Viewer zu sehen; Export und Stückliste gelten "
                      "erst, wenn alles aus dem Inventar kommt.")
    if len(verstoesse) > len(neue_v):
        bekannt_v = [v for v in verstoesse if v in alt_v]
        zeilen.append(f"Inventar-Regel: {fmt.plural(len(bekannt_v), 'bekannter Verstoß', 'bekannte Verstöße')} weiter "
                      f"offen ({', '.join(bekannt_v[:MAX_NAMEN])}{' …' if len(bekannt_v) > MAX_NAMEN else ''}).")

    # Parameter: im ersten Lauf alle (Namen für run(params=…)), danach nur Änderungen
    params = dict(res.get("params") or {})
    alt_params = vorher.params if vorher is not None else {}
    if kalt and params:
        zeilen.append("Parameter: " + ", ".join(f"{k}={fmt.num(v)}" for k, v in params.items()))
    elif not kalt:
        anders = [f"{k} {fmt.num(alt_params.get(k))} → {fmt.num(v)}" for k, v in params.items()
                  if k in alt_params and alt_params.get(k) != v]
        anders += [f"{k}={fmt.num(v)} (neu)" for k, v in params.items() if k not in alt_params]
        if anders:
            zeilen.append("Parameter: " + ", ".join(anders))
    unbekannt = [k for k in (gegeben or {}) if k not in params]
    if unbekannt:
        zeilen.append(f"Achtung: {', '.join(unbekannt)} gibt es nicht als param() in model.py (ohne Wirkung).")

    # Befunde: neue und geänderte zuerst
    if neue:
        schwer = [b for b in neue if b.get("schwere") in ("fehler", "warnung")]
        leicht = [b for b in neue if b.get("schwere") not in ("fehler", "warnung")]
        geaendert_b = sum(1 for b in neue if befund_kennung(b) in arten)
        kopf_b = f"{'Neue oder geänderte' if geaendert_b else 'Neue'} Befunde ({zaehler_text(zaehler(neue))})"
        kopf_b += " – vorläufig, die Prüfung läuft noch:" if vorlaeufig else ":"
        zeilen.append(kopf_b)
        gruppen = befund_gruppen(schwer)
        for gleich in gruppen[:MAX_BEFUNDE]:
            zeilen.append(befund_text(gleich[0]))
            if len(gleich) > 1:
                zeilen.append(f"  Ebenso {len(gleich) - 1}× bei: " + orte_text(gleich[1:]))
        rest = sum(len(g) for g in gruppen[MAX_BEFUNDE:])
        if rest:
            zeilen.append(f"- … und {rest} weitere Fehler und Warnungen anderer Art (pruefen zeigt alle).")
        if leicht:
            zeilen.append(f"- {fmt.plural(len(leicht), 'Hinweis', 'Hinweise')} "
                          f"({', '.join(sorted({str(b.get('art') or b.get('pruefung')) for b in leicht})[:4])}; "
                          "pruefen(hinweise=true) zeigt sie).")
    if bekannt:
        z = zaehler(bekannt)
        zeilen.append(f"Bekannte Befunde unverändert: {zaehler_text(z)}"
                      + (" – die Fehler sind weiter offen, beheben (pruefen zeigt sie)." if z["fehler"] else "."))
    if behoben:
        zeilen.append(f"Behoben seit dem letzten Lauf: {fmt.plural(behoben, 'Befund', 'Befunde')}.")

    # Teile
    if kalt:
        zeilen.append("Baugruppen:")
        zeilen += gruppen_zeilen(teile)
    else:
        einzeln = [(n, "neu") for n in neu_namen] + [(n, "geaendert") for n in geaendert]
        if len(einzeln) <= MAX_TEILE:
            for n, art in einzeln:
                zeilen.append(neu_zeile(n, teile[n]) if art == "neu" else f"- {n}: {unterschied(alt[n], teile[n])}")
        else:
            je: dict[str, list[str]] = {}
            for n, art in einzeln:
                je.setdefault(gruppe(n), []).append(art)
            for g, arten_g in sorted(je.items(), key=lambda x: -len(x[1])):
                zeilen.append(f"- {g}: {arten_g.count('geaendert')} geändert, {arten_g.count('neu')} neu")
            zeilen.append("  (einzeln: run(detail=\"teile\") oder parts(filter=\"<Baugruppe>\"))")
        if entfernt:
            zeilen.append("Entfernt: " + ", ".join(entfernt[:MAX_NAMEN])
                          + (f" und {len(entfernt) - MAX_NAMEN} weitere" if len(entfernt) > MAX_NAMEN else ""))

    # Warnungen des Laufs: neue einzeln, bekannte gezählt
    warnungen = [str(w) for w in res.get("warnings") or []]
    alt_w = vorher.warnungen if vorher is not None else set()
    neue_w = [w for w in warnungen if w not in alt_w]
    for w in neue_w[:MAX_NAMEN]:
        zeilen.append(f"Warnung: {w}")
    if len(neue_w) > MAX_NAMEN:
        zeilen.append(f"… und {len(neue_w) - MAX_NAMEN} weitere neue Warnungen (run(detail=\"voll\")).")
    if len(warnungen) > len(neue_w):
        zeilen.append(f"{fmt.plural(len(warnungen) - len(neue_w), 'bekannte Warnung', 'bekannte Warnungen')}.")

    # Prüfstand, Statik, Stückliste, Version, Animationen: je eine Zeile, wenn neu oder geändert
    stand_z = pruefstand_zeile(res, state, befunde)
    if stand_z:
        zeilen.append(stand_z)
    statik = None
    pr = res.get("pruefung") if isinstance(res.get("pruefung"), dict) else None
    if pr is not None and isinstance(pr.get("statik"), dict):
        from kevcad_kernel.statik.bericht import lauf_zeile

        statik = lauf_zeile(pr["statik"]) or None
        if statik and (kalt or statik != (vorher.statik if vorher else None)):
            zeilen.append(statik)
    sl = stueckliste_kurz(res.get("bom"))
    alt_sl = vorher.stueckliste if vorher is not None else None
    if sl is not None and (kalt or sl != alt_sl):
        zeilen.append(stueckliste_zeile(sl, alt_sl))
    version = res.get("version") if isinstance(res.get("version"), dict) else None
    if version and (version.get("neu") or version.get("titel_vergeben")) and version.get("titel"):
        zeile = f"Version V{version.get('nr')}: {version['titel']}"
        auto = version.get("titel_auto")
        if auto and auto != version["titel"]:
            zeile += f" (automatisch: {auto})"
        zeilen.append(zeile)
    elif version and version.get("hinweis"):
        zeilen.append(f"Version: {version['hinweis']}")
    animationen = tuple(sorted(str(a.get("name")) for a in res.get("animationen") or [] if isinstance(a, dict)))
    if animationen and (kalt or animationen != (vorher.animationen if vorher else ())):
        zeilen.append("Animationen: " + ", ".join(animationen) + " (animation(aktion=\"liste\")).")
    kameras = tuple(str(k) for k in res.get("kameras") or [])
    if kameras and (kalt or kameras != (vorher.kameras if vorher else ())):
        zeilen.append("Kameras: " + "; ".join(kameras[:4]) + (" …" if len(kameras) > 4 else ""))
    zz = zeiten_zeile(res.get("zeiten_ms"), res.get("duration_ms"))
    if zz:
        zeilen.append(zz)

    if detail == "teile":
        zeilen.append(f"Alle {fmt.plural(len(parts), 'Teil', 'Teile')}:")
        zeilen.append(fmt.parts_tree(parts))
    elif detail == "voll":
        voll, _, _ = fmt.run_summary(res)
        zeilen.append("Vollständig:")
        zeilen.append(voll)

    # isError wie bisher: Inventar-Regel, Fehler der fertigen Prüfung oder, solange sie läuft, der Bedingungen
    fehler = bool(fehler_offen) or bool(verstoesse)
    bed = res.get("bedingungen") if isinstance(res.get("bedingungen"), dict) else None
    if vorlaeufig and bed is not None and int((bed.get("summe") or {}).get("fehler") or 0) > 0:
        fehler = True
    # was der Agent kennt: die Befunde dieses Laufs; läuft die Prüfung noch, bleiben die bisher bekannten dazu
    bekannt_neu = {befund_schluessel(b) for b in befunde} | (gesehen if vorlaeufig else set())
    arten_neu = {befund_kennung(b) for b in befunde} | (arten if vorlaeufig else set())
    stand = Stand(run=run_no, teile=teile, befunde=bekannt_neu, befund_arten=arten_neu, warnungen=set(warnungen),
                  verstoesse=set(verstoesse), params=params, stueckliste=sl,
                  statik=statik or (vorher.statik if vorher is not None and vorlaeufig else None),
                  animationen=animationen, kameras=kameras)
    data = {
        "ok": True, "run": run_no, "teile": len(teile), "neu": neu_namen[:50], "geaendert": geaendert[:50],
        "entfernt": entfernt[:50], "unveraendert": gleich, "kalt": bool(kalt),
        "befunde": {"neu": len(neue), "bekannt": len(bekannt), "behoben": behoben, **zaehler(befunde)},
        "pruefung": state, "params": params if kalt else {k: v for k, v in params.items()
                                                         if alt_params.get(k) != v},
        "zeiten_ms": {k: v for k, v in (res.get("zeiten_ms") or {}).items() if isinstance(v, (int, float))},
    }
    if verstoesse:
        data["inventar_verstoesse"] = verstoesse
    if version:
        data["version"] = {k: version.get(k) for k in ("nr", "neu", "titel") if k in version}
    return "\n".join(zeilen), data, fehler, stand
