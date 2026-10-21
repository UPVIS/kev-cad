"""Anbindung an die gemeinsame Prüfung (``kevcad_kernel.pruefung``): Befunde der Bedingungen im Ergebnis CHECK.

Ablauf im Rechenprozess:

1. Während des Laufs (vor RUN_DONE) prüft ``lauf.pruefe_bedingungen`` die Bedingungen, Freiheitsgrade und die
   Befestigung (schnell) und legt den Stand hier ab (``merke``). Daraus entsteht die Nachricht CONSTRAINTS.
2. Nach RUN_DONE läuft die gemeinsame Prüfung (``pruefung/lauf.py``). Die hier registrierte Prüffunktion
   ``bedingungen`` gibt die Befunde aus Schritt 1 im Format der Prüfung zurück und prüft zusätzlich den Bewegungsraum
   (B8, kann Sekunden dauern, deshalb nicht vor RUN_END). So sperren verletzte Bedingungen, nicht befestigte Teile und
   blockierte Bewegungswege den Export wie Durchdringungen, an einer Stelle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from kevcad_kernel.pruefung import befund as bf
from kevcad_kernel.pruefung.befund import befund
from kevcad_kernel.pruefung.pruefer import PruefKontext, registriere

# Art der Befunde in der gemeinsamen Prüfung (Text für die Zusammenfassung)
ARTEN = {
    "bedingung": ("Bedingung verletzt", "Bedingungen verletzt"),
    "bewegungsraum": ("Bewegungsweg blockiert", "Bewegungswege blockiert"),
    "befestigung": ("Befestigung fehlt", "Befestigungen fehlen"),
}
for _art, _text in ARTEN.items():
    bf.ART_TEXT.setdefault(_art, _text)


@dataclass
class Stand:
    """Was die Prüfung nach RUN_DONE vom Lauf braucht."""

    sammlung: Any = None
    formen: dict[str, Any] = field(default_factory=dict)
    schluessel: dict[str, str] = field(default_factory=dict)
    boxen: dict[str, Any] = field(default_factory=dict)
    projekt: str | None = None
    bericht: dict[str, Any] | None = None


STAND = Stand()
ZEITLIMIT_S = 8.0  # Bewegungsraum je Lauf; danach „teilweise geprüft“ (Zwischenspeicher hilft beim nächsten Lauf)


def merke(sammlung: Any, formen: dict[str, Any], schluessel: dict[str, str], boxen: dict[str, Any],
          projekt: str | None, bericht: dict[str, Any] | None) -> None:
    global STAND
    STAND = Stand(sammlung, dict(formen), dict(schluessel), dict(boxen), projekt, bericht)


def als_pruefbefund(b: dict[str, Any]) -> dict[str, Any]:
    """Befund der Bedingungen (bericht["befunde"]) → Befund der gemeinsamen Prüfung (``befund.befund``)."""
    pruefung = b.get("pruefung") or "bedingung"
    art = pruefung if pruefung in ("bewegungsraum", "befestigung") else "bedingung"
    text = str(b.get("text") or "")
    if b.get("soll") and b.get("ist") and pruefung not in ("befestigung", "bewegungsraum") \
            and str(b["ist"]) not in text:
        text += f" (Soll {b['soll']}, Ist {b['ist']})"
    elif b.get("soll") and b.get("ist") and pruefung == "bedingung":
        text += f" (Soll {b['soll']})"
    if b.get("zeile"):
        text += f" [model.py Zeile {b['zeile']}]"
    wert = {k: b.get(k) for k in ("soll", "ist", "einheit", "bedingung", "unterart", "zeile") if b.get(k) not in
            (None, "")}
    wert["pruefung"] = pruefung
    if isinstance(b.get("wert"), (int, float)):
        wert["abweichung"] = b["wert"]
    out = befund(art, list(b.get("teile") or []) or ["model.py"], b.get("schwere") or "hinweis", text,
                 str(b.get("loesung") or ""), wert=wert, ort=b.get("ort"))
    out["soll"], out["ist"] = b.get("soll") or "", b.get("ist") or ""  # Zusatzfelder (PROTOCOL.md erlaubt sie)
    return out


def pruefe(ctx: PruefKontext) -> list[dict[str, Any]]:
    """Prüffunktion „bedingungen“ der gemeinsamen Prüfung (registriert nach „durchdringung“)."""
    t0 = time.perf_counter()
    stand = STAND
    if stand.sammlung is None or stand.bericht is None:
        return []
    namen = set(ctx.koerper)
    if namen and not namen <= set(stand.formen) | {n for n in namen if n.startswith("Skizze/")}:
        return []  # Stand eines anderen Laufs
    # Modelle ganz ohne Bedingungen: der Sammelhinweis „ohne Angabe, wie befestigt“ bleibt in CONSTRAINTS und
    # bedingungen, die gemeinsame Prüfung bleibt dort still (bestehende Modelle; Entscheidung bei Kevin)
    ohne = not stand.sammlung.bedingungen
    out = [als_pruefbefund(b) for b in stand.bericht.get("befunde") or []
           if not (ohne and b.get("unterart") == "ohne_angabe")]
    from .bewegungsraum import bewegungen_pruefen

    ctx.abbrechen()
    bewegungen, bew_befunde = bewegungen_pruefen(
        stand.sammlung, stand.sammlung.aufgeloest or {}, stand.formen, schluessel=stand.schluessel,
        projekt=stand.projekt, zeitlimit_s=ZEITLIMIT_S, boxen=stand.boxen)
    out += [als_pruefbefund(b) for b in bew_befunde]
    if bewegungen:
        ctx.ergebnis["bewegungen"] = bewegungen
    ctx.zeiten["bedingungen"] = (time.perf_counter() - t0) * 1000
    return out


registriere("bedingungen", pruefe, nach="durchdringung")
