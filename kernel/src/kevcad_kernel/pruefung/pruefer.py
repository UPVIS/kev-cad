"""Ablauf der Prüfung: eine Liste von Prüffunktionen, die nacheinander Befunde liefern.

Schnittstelle für weitere Quellen (Druckprüfung, Bedingungen …)::

    from kevcad_kernel.pruefung.pruefer import PruefKontext, registriere

    def meine_pruefung(ctx: PruefKontext) -> list[dict]:
        return [befund("bedingung", ["Halter"], "fehler", "…", "…", wert={...})]

    registriere("bedingungen", meine_pruefung, nach="durchdringung")

Jede Funktion bekommt den ``PruefKontext`` (Körper, Erklärungen aus model.py, Ergebnisse der früheren Prüfungen,
Zwischenspeicher) und gibt eine Liste von Befunden im Format von ``befund.py`` zurück. Zusatzangaben (etwa die
Montagereihenfolge) legt sie in ``ctx.ergebnis`` ab. Befunde mit ``schwere: "fehler"`` machen den Lauf zum Fehler und
sperren den Export, gleich aus welcher Quelle.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.pruefung import befund as bf
from kevcad_kernel.pruefung.befund import NACHGIEBIG_ANTEIL, SPIEL_VORSCHLAG, befund, mm, punkt, richtung_text
from kevcad_kernel.pruefung.koerper import Koerper
from kevcad_kernel.pruefung.kollision import Paar, PaarCache, gewindeeingriff, pruefe_paar


class Abgebrochen(Exception):
    """Neuerer Prüfauftrag (nächster Lauf) oder Zeitlimit."""


def _in_gruppe(name: str, muster: str) -> bool:
    return name == muster.rstrip("/") or (muster.endswith("/") and name.startswith(muster))


def passt(name: str, muster: list[str]) -> bool:
    """Name passt auf einen der Verweise aus model.py (Teilname oder Gruppe mit "/" am Ende)."""
    return any(_in_gruppe(name, m) for m in muster)

# Durchgang (ISO 273 mittel) und Kernloch je Nenndurchmesser
DURCHGANG = {3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 14: 15.5, 16: 17.5, 20: 22.0}
KERNLOCH = {3: 2.5, 4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 14: 12.0, 16: 14.0, 20: 17.5}


@dataclass
class PruefKontext:
    koerper: dict[str, Koerper]  # Volumenkörper des Laufs in show()-Reihenfolge
    erklaerungen: dict[str, Any]  # aus model.py: montage, erlaubt, befestigt, boden, warnungen
    optionen: dict[str, Any]
    cache: PaarCache
    abbrechen: Callable[[], None] = lambda: None
    paare: dict[frozenset, Paar] = field(default_factory=dict)  # Kontakte und Durchdringungen
    ergebnis: dict[str, Any] = field(default_factory=dict)  # Zusatzangaben der Prüfungen (montage, stand …)
    geometrie: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=list)  # Schnittkörper
    zeiten: dict[str, float] = field(default_factory=dict)
    stand_cache: dict = field(default_factory=dict)

    # -- Erklärungen ---------------------------------------------------------------------------------------------

    def erlaubt(self, a: str, b: str) -> str | None:
        """Grund, wenn sich a und b laut model.py überlappen dürfen."""
        for e in self.erklaerungen.get("erlaubt") or []:
            ea, eb = e.get("a") or [], e.get("b") or []
            if (passt(a, ea) and passt(b, eb)) or (passt(a, eb) and passt(b, ea)):
                return str(e.get("grund") or "")
        return None

    def befestigt(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for e in self.erklaerungen.get("befestigt") or []:
            for n in self.koerper:
                if passt(n, e.get("teile") or []):
                    out[n] = str(e.get("grund") or "")
        return out

    @property
    def nachgiebig(self) -> set[str]:
        return {n for n, k in self.koerper.items() if k.nachgiebig}

    @property
    def kontakte(self) -> list[tuple[str, str]]:
        return [(p.a, p.b) for p in self.paare.values() if p.kontakt or p.durchdringt]

    def ausschluss(self) -> set[frozenset[str]]:
        """Paare, die sich bei der Montage nicht behindern: durchdringend (eigener Befund) oder erlaubt."""
        return {k for k, p in self.paare.items() if p.durchdringt}


PruefFunktion = Callable[[PruefKontext], list[dict[str, Any]]]
PRUEFUNGEN: list[tuple[str, PruefFunktion]] = []


def registriere(name: str, fn: PruefFunktion, nach: str | None = None) -> None:
    """Prüffunktion anhängen (oder nach der Prüfung ``nach`` einreihen); gleicher Name ersetzt."""
    global PRUEFUNGEN
    PRUEFUNGEN = [(n, f) for n, f in PRUEFUNGEN if n != name]
    if nach is not None:
        for i, (n, _) in enumerate(PRUEFUNGEN):
            if n == nach:
                PRUEFUNGEN.insert(i + 1, (name, fn))
                return
    PRUEFUNGEN.append((name, fn))


# ---------------------------------------------------------------------------------------------------------------------
# Durchdringung


def kandidaten_paare(koerper: list[Koerper], pad: float) -> list[tuple[int, int]]:
    """Paare, deren Hüllquader sich (bis auf pad) überdecken."""
    if len(koerper) < 2:
        return []
    lo = np.array([k.bmin for k in koerper])
    hi = np.array([k.bmax for k in koerper])
    ov = np.all((np.minimum(hi[:, None, :], hi[None, :, :]) - np.maximum(lo[:, None, :], lo[None, :, :])) > -pad,
                axis=2)
    i, j = np.nonzero(np.triu(ov, 1))
    return list(zip(i.tolist(), j.tolist()))


def _nenn(k: Koerper) -> int | None:
    d = k.info.get("d")
    if not d:
        return None
    return min(DURCHGANG, key=lambda x: abs(x - float(d)))


def _gewinde_von(k: Koerper) -> Any:
    """Gewinde eines Verbindungselements (metrisch oder Zoll) aus Größe bzw. Nenndurchmesser, sonst None."""
    from kevcad_kernel import gewinde as gw

    g = gw.aus_text(k.info.get("groesse"))
    if g is None and k.info.get("d"):
        g = gw.naechstes(float(k.info["d"]))
    return g


def _loesung_durchdringung(a: Koerper, b: Koerper, p: Paar) -> str:
    from kevcad_kernel.bom import de_num

    vb = next((k for k in (a, b) if k.ist_verbindungselement), None)
    if vb is not None:
        andere = b if vb is a else a
        g = _gewinde_von(vb)
        if g is not None:
            norm = "ISO 273 mittel" if not g.zoll else "free fit"
            return (f"Bohrung für {vb.kurz} in {andere.name} vorsehen: Durchgang Ø {de_num(g.durchgang, 1)} mm "
                    f"({norm}). Soll {vb.kurz} dort ins Gewinde ({g.name}): Kernloch Ø {de_num(g.kernloch, 2)} mm, "
                    "den Gewindeeingriff erkennt Kev CAD dann selbst.")
    klein, gross = (a, b) if a.volumen <= b.volumen else (b, a)
    weg = p.tiefe + SPIEL_VORSCHLAG
    if klein.volumen > 0 and p.volumen >= 0.95 * klein.volumen:
        return (f"{klein.name} steckt ganz in {gross.name}: Aussparung in {gross.name} vorsehen (Form von "
                f"{klein.kurz} plus {mm(SPIEL_VORSCHLAG)} Spiel abziehen) oder {klein.kurz} an seinen Platz "
                "verschieben.")
    achse = p.achse if p.achse is not None else np.array([0.0, 0.0, 1.0])
    if klein is b:
        achse = -achse
    text = (f"{klein.name} um {mm(weg)} in {richtung_text(_runde_achse(achse))} verschieben (dann "
            f"{mm(SPIEL_VORSCHLAG)} Spiel), das Maß von {klein.kurz} oder {gross.kurz} um {mm(weg)} korrigieren oder "
            f"in {gross.kurz} eine Aussparung mit Spiel vorsehen.")
    if p.tiefe > 0.25 * float(np.min(klein.bmax - klein.bmin)):
        text += " Wenn beide Teile ineinander greifen sollen: Teilung, Bohrung oder Nut vorsehen."
    return text


def _runde_achse(a: np.ndarray) -> np.ndarray:
    """Achsnahe Richtungen auf die Achse runden (für lesbare Vorschläge)."""
    a = np.asarray(a, dtype=np.float64)
    i = int(np.argmax(np.abs(a)))
    if abs(a[i]) > 0.985:
        out = np.zeros(3)
        out[i] = np.sign(a[i])
        return out
    return a / np.linalg.norm(a)


def pruefe_durchdringungen(ctx: PruefKontext) -> list[dict[str, Any]]:
    t0 = time.perf_counter()
    ks = list(ctx.koerper.values())
    out: list[dict[str, Any]] = []
    neu0 = ctx.cache.neu
    for i, j in kandidaten_paare(ks, bf.BERUEHR_TOL):
        ctx.abbrechen()
        a, b = ks[i], ks[j]
        p = pruefe_paar(a, b, ctx.cache)
        if p is None:
            continue
        ctx.paare[frozenset((a.name, b.name))] = p
        if not p.durchdringt:
            continue
        grund = ctx.erlaubt(a.name, b.name)
        if grund:
            continue  # erlaubt mit Grund: kein Befund (steht in der Liste „erlaubt“ des Ergebnisses)
        gewinde = gewindeeingriff(a, b, p.netz[0]) if p.netz is not None else None
        if gewinde:  # Schraube in Mutter oder Kernloch: die einzige Überlappung, die ohne Erklärung gilt
            ctx.ergebnis.setdefault("gewinde", []).append({"teile": [a.name, b.name], "text": gewinde,
                                                            "volumen": round(p.volumen, 3)})
            continue
        geo = None
        if p.netz is not None and len(p.netz[2]):
            ctx.geometrie.append(p.netz)
            geo = len(ctx.geometrie) - 1
        wert = {"volumen": round(p.volumen, 3), "tiefe": round(p.tiefe, 3)}
        if p.achse is not None:
            wert["achse"] = [round(float(c), 4) for c in p.achse]
        weich = [k for k in (a, b) if k.nachgiebig]
        if weich:
            w = weich[0]
            dicke = float(np.min(w.bmax - w.bmin))
            anteil = p.tiefe / dicke if dicke > 0 else 1.0
            wert["anteil"] = round(anteil, 3)
            andere = b if w is a else a
            text = (f"{w.name} (nachgiebig) wird von {andere.name} um {mm(p.tiefe)} zusammengedrückt "
                    f"({anteil * 100:.0f} % seiner Dicke) bei {punkt(p.ort)}.")
            if anteil <= NACHGIEBIG_ANTEIL:
                out.append(befund("verformt", [w.name, andere.name], "hinweis", text,
                                  "Gewollt (Klemmung, Polster)? Dann passt es; sonst Abstand vergrößern.",
                                  wert=wert, ort=p.ort, geometrie=geo))
            else:
                out.append(befund("verformt", [w.name, andere.name], "warnung", text + " Das ist mehr als die Hälfte.",
                                  "Abstand vergrößern oder ein dünneres Polster vorsehen.", wert=wert, ort=p.ort,
                                  geometrie=geo))
            continue
        out.append(befund(
            "durchdringung", [a.name, b.name], "fehler",
            f"{a.name} und {b.name} durchdringen sich: {bf.de_num(p.volumen, 1)} mm³, Tiefe etwa {mm(p.tiefe, 2)} "
            f"bei {punkt(p.ort)}.", _loesung_durchdringung(a, b, p), wert=wert, ort=p.ort, geometrie=geo))
    ctx.zeiten["durchdringung"] = (time.perf_counter() - t0) * 1000
    ctx.ergebnis["paare"] = {"geprueft": len(ctx.paare), "neu_gerechnet": ctx.cache.neu - neu0,
                             "kontakte": sum(1 for p in ctx.paare.values() if p.kontakt)}
    erlaubt = []
    for p in ctx.paare.values():
        if p.durchdringt:
            g = ctx.erlaubt(p.a, p.b)
            if g:
                erlaubt.append({"teile": [p.a, p.b], "grund": g, "volumen": round(p.volumen, 3)})
    ctx.ergebnis["erlaubt"] = erlaubt
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Stand, Montage, Werkzeug, Erklärungen


def pruefe_erklaerungen(ctx: PruefKontext) -> list[dict[str, Any]]:
    """Ungültige Erklärungen aus model.py (ohne Grund, unbekannte Teile) als Befund."""
    out = []
    for w in ctx.erklaerungen.get("warnungen") or []:
        out.append(befund("erklaerung", [w.get("teil") or "model.py"], "warnung", str(w.get("text") or w),
                          str(w.get("loesung") or "Erklärung in model.py korrigieren.")))
    return out


registriere("erklaerungen", pruefe_erklaerungen)
registriere("durchdringung", pruefe_durchdringungen)

# Weitere Prüfungen in eigenen Modulen; sie registrieren sich beim Import selbst (Reihenfolge = Ablauf)
ERWEITERUNGEN: tuple[str, ...] = ()  # Stufe 2: ("kevcad_kernel.pruefung.stand", "kevcad_kernel.pruefung.montage")
_geladen = False


def lade_erweiterungen() -> None:
    global _geladen
    if _geladen:
        return
    import importlib

    for mod in ERWEITERUNGEN:
        importlib.import_module(mod)
    _geladen = True


# ---------------------------------------------------------------------------------------------------------------------
# Gesamtablauf


def pruefe(koerper: list[Koerper], erklaerungen: dict[str, Any] | None = None, optionen: dict[str, Any] | None = None,
           cache: PaarCache | None = None, abbrechen: Callable[[], None] | None = None,
           stand_cache: dict | None = None) -> tuple[dict[str, Any], list[tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    """Alle registrierten Prüfungen; liefert (Ergebnis, Schnittkörper). Bricht mit ``Abgebrochen`` ab, wenn
    ``abbrechen`` das verlangt (neuerer Auftrag)."""
    t0 = time.perf_counter()
    lade_erweiterungen()
    aktiv = (optionen or {}).get("pruefungen")
    volumen = [k for k in koerper if k.volumen > 1e-6 and len(k.tri)]
    ctx = PruefKontext(koerper={k.name: k for k in volumen}, erklaerungen=dict(erklaerungen or {}),
                       optionen=dict(optionen or {}), cache=cache if cache is not None else PaarCache(),
                       abbrechen=abbrechen or (lambda: None), stand_cache=stand_cache if stand_cache is not None else {})
    befunde: list[dict[str, Any]] = []
    for name, fn in PRUEFUNGEN:
        if aktiv is not None and name not in aktiv:
            continue
        try:
            befunde += list(fn(ctx) or [])
        except Abgebrochen:
            raise
        except Exception as exc:  # noqa: BLE001 - eine fehlerhafte Prüfung soll die anderen nicht verhindern
            import traceback

            befunde.append(befund("pruefung", ["Prüfung"], "warnung",
                                  f"Prüfung „{name}“ ist fehlgeschlagen: {type(exc).__name__}: {exc}",
                                  "Bitte melden; die übrigen Prüfungen sind gelaufen."))
            ctx.ergebnis.setdefault("fehler", []).append(traceback.format_exc(limit=6))
    befunde = bf.sortieren(befunde)
    bf.nummerieren(befunde)
    # Schnittkörper in Reihenfolge der Befunde umnummerieren, ungenutzte weglassen
    geo_alt, geometrie, karte = ctx.geometrie, [], {}
    for b in befunde:
        g = b.get("geometrie")
        if g is not None and 0 <= g < len(geo_alt):
            if g not in karte:
                karte[g] = len(geometrie)
                geometrie.append(geo_alt[g])
            b["geometrie"] = karte[g]
    ergebnis = {
        "befunde": befunde,
        "zusammenfassung": bf.zusammenfassung(befunde),
        "zaehler": bf.zaehler(befunde),
        "teile": len(volumen),
        "ohne_volumen": [k.name for k in koerper if k not in volumen],
        **ctx.ergebnis,
        "zeiten_ms": {k: round(v, 1) for k, v in ctx.zeiten.items()},
        "dauer_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    return ergebnis, geometrie
