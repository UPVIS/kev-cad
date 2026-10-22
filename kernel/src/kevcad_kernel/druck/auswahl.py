"""Teile beim Druckexport auswählen: ``druck_export(…, teile=[…], ohne=[…])`` (DRUCKVORSCHAU.md, „Auswahl“).

Reine Rechnung auf den Platten der Druckvorschau (keine Formen, kein Slicer):

- ``teile``: nur diese Teile exportieren; ``ohne``: diese weglassen. Beides zusammen geht, ``ohne`` gewinnt. Ein
  Eintrag ist ein Teilname aus ``show()`` (genau), eine Baugruppe als Präfix („Kugelschieber/Lenksperren“ trifft alles
  darunter), eine Gruppe der Vorschau („g3“) oder ihr Name („Lenksperre (Druck)“). Unbekannte Einträge sind ein
  Fehler mit Vorschlägen.
- Die übrigen Teile bleiben, wo die Vorschau sie hingelegt hat; Lücken sind in Ordnung. Bambu Studio lädt und slict
  Platten mit festen Lagen und Lücken ohne Weiteres (``need_arrange: false`` in der Montageliste); die Lagen waren vorher
  überschneidungsfrei, im Bauraum und außerhalb der Sperrzone, und das bleibt so, wenn Teile wegfallen. Neu anordnen
  hieße: andere Platten als in der Vorschau, die Kevin gesehen hat. Leere Platten fallen weg; passen die übrigen
  Teile auf weniger Platten, sagt das ein Hinweis (schnelles Anordnen als Probe).
- Teile „später drucken“ (``lager.druckteil(…, spaeter=True)``) liegen auf keiner Platte und stehen immer unter
  ``weggelassen``; sie lassen sich nicht über ``teile`` holen (dafür ``spaeter`` in model.py weglassen).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from kevcad_kernel.druck import anordnen as ao


class AuswahlFehler(ValueError):
    pass


@dataclass
class Auswahl:
    platten: list[tuple[int, str, ao.Platte]]     # (Nummer in der Vorschau, Material, Platte mit den übrigen Teilen)
    teile: list[str]                              # exportierte Teilnamen (je einmal, in Plattenfolge)
    weggelassen: list[dict[str, Any]]             # {"name", "grund": ohne | teile | spaeter, "platte", "anzahl"}
    leere_platten: list[int]                      # Platten der Vorschau, die ganz weggefallen sind
    hinweise: list[str] = field(default_factory=list)
    gewaehlt: bool = False                        # teile oder ohne angegeben


def _liste(wert: Any) -> list[str]:
    if wert is None:
        return []
    if isinstance(wert, str):
        wert = [wert]
    return [str(w).strip() for w in wert if str(w).strip()]


def _kandidaten(namen: list[str], gruppen: list[Any]) -> list[str]:
    """Alles, was ein Eintrag sein könnte: Teilnamen, Baugruppen davor, Gruppen-ids und Gruppennamen."""
    out = list(namen)
    for n in namen:
        teile = n.split("/")
        out += ["/".join(teile[:i]) for i in range(1, len(teile))]
    out += [g.id for g in gruppen] + [g.name for g in gruppen]
    return list(dict.fromkeys(x for x in out if x))


def aufloesen(eintrag: str, namen: list[str], gruppen: list[Any]) -> list[str]:
    """Teilnamen zu einem Eintrag: genauer Teilname, Gruppe (id oder Name) der Vorschau, Baugruppen-Präfix."""
    e = str(eintrag).strip()
    if e in namen:
        return [e]
    for g in gruppen:
        if e in (g.id, g.name):
            return [n for n in dict.fromkeys(g.teile) if n in namen]
    praefix = e.rstrip("/") + "/"
    return [n for n in namen if n.startswith(praefix)]


def vorschlaege(eintrag: str, namen: list[str], gruppen: list[Any], n: int = 3) -> list[str]:
    kand = _kandidaten(namen, gruppen)
    treffer = difflib.get_close_matches(eintrag, kand, n=n, cutoff=0.5)
    if not treffer:  # Teilwort („Lenksperre“ in „Kugelschieber/Lenksperre links (Druck)“)
        klein = eintrag.lower()
        treffer = [k for k in kand if klein and klein in k.lower()][:n]
    return treffer


def _unbekannt(eintrag: str, wo: str, namen: list[str], gruppen: list[Any]) -> AuswahlFehler:
    tipp = vorschlaege(eintrag, namen, gruppen)
    text = f"{wo}: {eintrag!r} ist kein Druckteil der Druckvorschau"
    if tipp:
        text += ". Meintest du " + ", ".join(repr(t) for t in tipp) + "?"
    else:
        koepfe = list(dict.fromkeys(n.split("/")[0] for n in namen))
        text += " (Druckteile: " + ", ".join(koepfe[:8]) + (" …" if len(koepfe) > 8 else "") + ")"
    return AuswahlFehler(text)


def waehle(platten: list[tuple[int, str, ao.Platte]], gruppen: list[Any], teile: Any = None, ohne: Any = None,
           gedruckt: list[str] | None = None) -> Auswahl:
    """Wählt aus den Platten der Vorschau (``platten``: schon nach ``platten=`` gefiltert, je (Nummer, Material,
    Platte)) die Teile nach ``teile`` und ``ohne``. ``gruppen``: alle Gruppen der Vorschau (auch „später“),
    ``gedruckt``: Namen schon gedruckter Teile (gültige Einträge, aber nie auf einer Platte)."""
    teile_l, ohne_l = _liste(teile), _liste(ohne)
    spaeter_namen = list(dict.fromkeys(n for g in gruppen if getattr(g, "spaeter", False) for n in g.teile))
    auf_platte = list(dict.fromkeys(l_.stueck.name for _, _, p in platten for l_ in p.lagen))
    alle_platten = list(dict.fromkeys(n for g in gruppen if not getattr(g, "spaeter", False) for n in g.teile))
    gedruckt = list(gedruckt or [])
    namen = list(dict.fromkeys(alle_platten + auf_platte + spaeter_namen + gedruckt))
    hinweise: list[str] = []

    def treffer(eintrag: str, wo: str) -> list[str]:
        t = aufloesen(eintrag, namen, gruppen)
        if not t:
            raise _unbekannt(eintrag, wo, namen, gruppen)
        return t

    behalten: set[str] | None = None
    if teile_l:
        behalten = set()
        for e in teile_l:
            t = treffer(e, "teile")
            jetzt = [n for n in t if n not in spaeter_namen and n not in gedruckt]
            if not jetzt:
                if all(n in gedruckt for n in t):
                    raise AuswahlFehler(f"teile: {e!r} ist schon gedruckt (lager.druckteil(…, gedruckt=True)) und "
                                        "kommt in keinen Druckexport.")
                raise AuswahlFehler(f"teile: {e!r} ist als später markiert (lager.druckteil(…, spaeter=True)) und "
                                    "liegt auf keiner Platte. Zum Drucken spaeter=True in model.py weglassen und neu "
                                    "rechnen.")
            nicht_da = [n for n in jetzt if n not in auf_platte]
            if nicht_da and len(nicht_da) == len(jetzt):
                hinweise.append(f"teile: {e!r} liegt nicht auf den gewählten Platten.")
            behalten |= set(jetzt)
    weg: set[str] = set()
    for e in ohne_l:
        weg |= set(treffer(e, "ohne"))

    neue: list[tuple[int, str, ao.Platte]] = []
    leer: list[int] = []
    zaehl: dict[tuple[str, str, int | None], int] = {}
    for nr, mat, p in platten:
        lagen = []
        for l_ in p.lagen:
            n = l_.stueck.name
            if n in weg:
                grund = "ohne"
            elif behalten is not None and n not in behalten:
                grund = "teile"
            else:
                lagen.append(l_)
                continue
            zaehl[(n, grund, nr)] = zaehl.get((n, grund, nr), 0) + 1
        if lagen:
            q = ao.Platte(p.material, lagen=lagen, passt_nicht=p.passt_nicht)
            neue.append((nr, mat, q))
        elif p.lagen:
            leer.append(nr)
    weggelassen = [{"name": n, "grund": g, "platte": nr, "anzahl": k} for (n, g, nr), k in zaehl.items()]
    for g in gruppen:
        if getattr(g, "spaeter", False):
            je = {n: 0 for n in dict.fromkeys(g.teile)}
            for i in range(max(int(g.anzahl), len(g.teile))):
                je[g.teile[i % len(g.teile)]] += 1
            weggelassen += [{"name": n, "grund": "spaeter", "platte": None, "anzahl": k} for n, k in je.items()]
    exportiert = list(dict.fromkeys(l_.stueck.name for _, _, p in neue for l_ in p.lagen))
    if not exportiert:
        raus = sorted({w["name"] for w in weggelassen if w["grund"] != "spaeter"})
        raise AuswahlFehler("Nach der Auswahl bleibt kein Teil zum Drucken"
                            + (f" (weggelassen: {', '.join(raus[:6])}{' …' if len(raus) > 6 else ''})" if raus else "")
                            + ".")
    gewaehlt = bool(teile_l or ohne_l)
    if gewaehlt and leer:
        hinweise.append("Leer und weggefallen: Platte " + ", ".join(str(n) for n in leer) + ".")
    gelichtet = sorted({nr for (_, _, nr) in zaehl} & {nr for nr, _, _ in neue})
    if gelichtet:
        hinweise.append("Die übrigen Teile bleiben an ihrer Stelle aus der Druckvorschau (Lücken auf Platte "
                        + ", ".join(str(n) for n in gelichtet) + ").")
        # Probe: passten die übrigen Teile auf weniger Platten?
        for mat in dict.fromkeys(m for _, m, _ in neue):
            jetzt = [q for _, m, q in neue if m == mat]
            stuecke = [l_.stueck for q in jetzt for l_ in q.lagen]
            probe = ao.anordne(stuecke)
            if len(jetzt) > 1 and len(probe) < len(jetzt) and not any(p.passt_nicht for p in probe):
                hinweise.append(f"{mat.upper()}: neu angeordnet passten die übrigen Teile auf {len(probe)} statt "
                                f"{len(jetzt)} Platten (bei Bedarf in Bambu Studio neu anordnen).")
    return Auswahl(platten=neue, teile=exportiert, weggelassen=weggelassen, leere_platten=leer, hinweise=hinweise,
                   gewaehlt=gewaehlt)


def weggelassen_text(weg: list[dict[str, Any]]) -> str:
    """„Weggelassen: A ×2 (ohne), B (später)“ für Hinweise und den MCP-Text."""
    grund_text = {"ohne": "ohne", "teile": "nicht in teile", "spaeter": "später"}
    teile = []
    gesehen: dict[tuple[str, str], int] = {}
    for w in weg:
        k = (str(w.get("name")), str(w.get("grund")))
        gesehen[k] = gesehen.get(k, 0) + int(w.get("anzahl") or 1)
    for (n, g), k in gesehen.items():
        teile.append(f"{n}{f' ×{k}' if k > 1 else ''} ({grund_text.get(g, g)})")
    return "Weggelassen: " + ", ".join(teile) + "." if teile else ""
