"""Zwei Stände vergleichen (PLAN-VERSIONEN.md, V6): Parameter, Teile, Stückliste, Prüfstand, Kennzahlen.

Eingabe sind zwei ``daten`` aus schnappschuss.py (alt = a, neu = b). Code-Unterschied und Geometrie hängt die
Laufzeit an (archiv.code_diff, Netze aus dem Zwischenspeicher).
"""

from __future__ import annotations

import math
from typing import Any

LAGE_TOL = 1e-3  # mm
REL_TOL = 1e-6


def _gleich(a: Any, b: Any, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=tol)
    except (TypeError, ValueError):
        return a == b


def _vek_gleich(a: list | None, b: list | None, tol: float = LAGE_TOL) -> bool:
    a, b = a or [], b or []
    return len(a) == len(b) and all(_gleich(x, y, tol) for x, y in zip(a, b))


def teil_aenderung(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Was sich an einem gleichnamigen Teil geändert hat: Form, Lage, Farbe, Material, Lagerteil (leer = gleich)."""
    if a.get("key") and a.get("key") == b.get("key") and a.get("farbe") == b.get("farbe") \
            and a.get("material") == b.get("material"):
        return []
    arten = []
    form_gleich = _gleich(a.get("volumen"), b.get("volumen"), 1e-4) and _gleich(a.get("flaeche"), b.get("flaeche"),
                                                                                 1e-4)
    lage_gleich = _vek_gleich(a.get("min"), b.get("min")) and _vek_gleich(a.get("max"), b.get("max"))
    if not form_gleich:
        arten.append("form")
    elif not lage_gleich or not _vek_gleich(a.get("mitte"), b.get("mitte")):
        arten.append("lage")
    elif a.get("key") != b.get("key") and a.get("dreiecke") != b.get("dreiecke"):
        arten.append("form")
    if a.get("farbe") != b.get("farbe"):
        arten.append("farbe")
    if a.get("material") != b.get("material"):
        arten.append("material")
    if (a.get("lager") or {}).get("id") != (b.get("lager") or {}).get("id"):
        arten.append("lagerteil")
    return arten


def vergleiche_teile(alt: list[dict[str, Any]], neu: list[dict[str, Any]]) -> dict[str, Any]:
    a = {t["name"]: t for t in alt}
    b = {t["name"]: t for t in neu}
    geaendert = []
    gleich = 0
    for name in [t["name"] for t in neu if t["name"] in a]:
        arten = teil_aenderung(a[name], b[name])
        if not arten:
            gleich += 1
            continue
        eintrag: dict[str, Any] = {"name": name, "arten": arten}
        if a[name].get("volumen") is not None and b[name].get("volumen") is not None:
            eintrag["dvolumen"] = round(float(b[name]["volumen"]) - float(a[name]["volumen"]), 3)
        if a[name].get("masse") is not None and b[name].get("masse") is not None:
            eintrag["dmasse"] = round(float(b[name]["masse"]) - float(a[name]["masse"]), 3)
        if "lage" in arten and a[name].get("mitte") and b[name].get("mitte"):
            eintrag["verschiebung"] = [round(float(y) - float(x), 3) for x, y in zip(a[name]["mitte"],
                                                                                     b[name]["mitte"])]
        geaendert.append(eintrag)
    return {"neu": [t["name"] for t in neu if t["name"] not in a],
            "weg": [t["name"] for t in alt if t["name"] not in b],
            "geaendert": geaendert, "gleich": gleich}


def vergleiche_params(alt: dict[str, Any], neu: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for name in list(dict.fromkeys(list(neu) + list(alt))):
        va, vb = alt.get(name), neu.get(name)
        if name not in alt:
            out.append({"name": name, "alt": None, "neu": vb, "art": "neu"})
        elif name not in neu:
            out.append({"name": name, "alt": va, "neu": None, "art": "weg"})
        elif not _gleich(va, vb, 1e-9):
            out.append({"name": name, "alt": va, "neu": vb, "art": "geaendert"})
    return out


def _zeilen_schluessel(ln: dict[str, Any]) -> tuple:
    return (ln.get("art"), ln.get("stock_id") or ln.get("benennung"), ln.get("masse_text"),
            tuple(ln.get("gehrung") or ()), ln.get("material"))


def _zeile_kurz(ln: dict[str, Any]) -> dict[str, Any]:
    return {k: ln.get(k) for k in ("benennung", "masse_text", "anzahl", "material", "preis", "kg", "stock_id", "art")}


def vergleiche_stueckliste(alt: dict[str, Any] | None, neu: dict[str, Any] | None) -> dict[str, Any]:
    la = list((alt or {}).get("lines") or [])
    lb = list((neu or {}).get("lines") or [])
    rest_a = {}
    for ln in la:
        rest_a.setdefault(_zeilen_schluessel(ln), []).append(ln)
    geaendert, neu_z, offen_b = [], [], []
    for ln in lb:
        k = _zeilen_schluessel(ln)
        if rest_a.get(k):
            alt_ln = rest_a[k].pop(0)
            if alt_ln.get("anzahl") != ln.get("anzahl") or not _gleich(alt_ln.get("preis"), ln.get("preis"), 0.005):
                geaendert.append({**_zeile_kurz(ln), "alt_anzahl": alt_ln.get("anzahl"), "neu_anzahl": ln.get("anzahl"),
                                  "alt_masse_text": alt_ln.get("masse_text"), "alt_preis": alt_ln.get("preis")})
        else:
            offen_b.append(ln)
    offen_a = [ln for liste in rest_a.values() for ln in liste]
    # gleiches Lagerteil, andere Maße und gemeinsame Teile: geändert statt neu + weg
    for ln in offen_b:
        partner = None
        for alt_ln in offen_a:
            if (alt_ln.get("stock_id") or alt_ln.get("benennung")) == (ln.get("stock_id") or ln.get("benennung")) \
                    and set(alt_ln.get("teile") or []) & set(ln.get("teile") or []):
                partner = alt_ln
                break
        if partner is not None:
            offen_a.remove(partner)
            geaendert.append({**_zeile_kurz(ln), "alt_anzahl": partner.get("anzahl"), "neu_anzahl": ln.get("anzahl"),
                              "alt_masse_text": partner.get("masse_text"), "alt_preis": partner.get("preis")})
        else:
            neu_z.append(_zeile_kurz(ln))
    return {"neu": neu_z, "weg": [_zeile_kurz(ln) for ln in offen_a], "geaendert": geaendert,
            "totals_alt": (alt or {}).get("totals") or {}, "totals_neu": (neu or {}).get("totals") or {}}


def vergleiche(alt: dict[str, Any], neu: dict[str, Any]) -> dict[str, Any]:
    """Vergleich zweier ``daten``. Rückgabe ohne Code und Geometrie."""
    return {
        "params": vergleiche_params(alt.get("params") or {}, neu.get("params") or {}),
        "teile": vergleiche_teile(alt.get("teile") or [], neu.get("teile") or []),
        "stueckliste": vergleiche_stueckliste(alt.get("stueckliste"), neu.get("stueckliste")),
        "pruefung": {"alt": alt.get("pruefung"), "neu": neu.get("pruefung")},
        "kennzahlen": {"alt": alt.get("kennzahlen") or {}, "neu": neu.get("kennzahlen") or {}},
    }


def geister_auswahl(vergleich: dict[str, Any], alt: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Welche Teile der alten Version als Geisterkörper erscheinen: (Name, Formschlüssel, Art) mit Art
    ``alt`` (Teil geändert, so sah es vorher aus) oder ``weg`` (Teil gibt es nicht mehr)."""
    teile = {t["name"]: t for t in alt.get("teile") or []}
    out = []
    for g in vergleich["teile"]["geaendert"]:
        t = teile.get(g["name"])
        if t and t.get("key") and ({"form", "lage"} & set(g["arten"])):
            out.append((t["name"], t["key"], "alt"))
    for name in vergleich["teile"]["weg"]:
        t = teile.get(name)
        if t and t.get("key"):
            out.append((name, t["key"], "weg"))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Text (deutsch, für MCP und Protokoll)


def _num(x: Any, digits: int = 2) -> str:
    if x is None:
        return "–"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return (text or "0").replace(".", ",")


def zusammenfassung(v: dict[str, Any]) -> str:
    """Eine Zeile: „3 Teile geändert, 1 neu, 2 weg · 2 Parameter · Stückliste +1/−0/~2 · Masse … · Kosten …“."""
    t = v["teile"]
    bits = []
    teile = []
    if t["geaendert"]:
        teile.append(f"{len(t['geaendert'])} geändert")
    if t["neu"]:
        teile.append(f"{len(t['neu'])} neu")
    if t["weg"]:
        teile.append(f"{len(t['weg'])} weg")
    bits.append("Teile: " + (", ".join(teile) if teile else "unverändert"))
    if v["params"]:
        bits.append(f"{len(v['params'])} Parameter geändert")
    s = v["stueckliste"]
    if s["neu"] or s["weg"] or s["geaendert"]:
        bits.append(f"Stückliste +{len(s['neu'])} −{len(s['weg'])} ~{len(s['geaendert'])}")
    ka, kb = v["kennzahlen"]["alt"], v["kennzahlen"]["neu"]
    if ka.get("masse_kg") is not None and kb.get("masse_kg") is not None \
            and not _gleich(ka["masse_kg"], kb["masse_kg"], 1e-4):
        bits.append(f"Masse {_num(ka['masse_kg'], 3)} → {_num(kb['masse_kg'], 3)} kg")
    if ka.get("kosten") is not None and kb.get("kosten") is not None and not _gleich(ka["kosten"], kb["kosten"], 0.005):
        bits.append(f"Kosten {_num(ka['kosten'])} → {_num(kb['kosten'])} €")
    pa, pb = (v["pruefung"]["alt"] or {}), (v["pruefung"]["neu"] or {})
    fa, fb = (pa.get("zaehler") or {}).get("fehler"), (pb.get("zaehler") or {}).get("fehler")
    if fa is not None and fb is not None and fa != fb:
        bits.append(f"Prüfung {fa} → {fb} Fehler")
    return " · ".join(bits)


def text(v: dict[str, Any], *, max_teile: int = 25) -> str:
    """Mehrzeilige Beschreibung für das MCP-Werkzeug versionen_vergleichen."""
    zeilen = [zusammenfassung(v)]
    for p in v["params"]:
        if p["art"] == "neu":
            zeilen.append(f"- Parameter {p['name']} neu: {_num(p['neu'], 4)}")
        elif p["art"] == "weg":
            zeilen.append(f"- Parameter {p['name']} entfernt (war {_num(p['alt'], 4)})")
        else:
            zeilen.append(f"- Parameter {p['name']}: {_num(p['alt'], 4)} → {_num(p['neu'], 4)}")
    t = v["teile"]
    namen = {"form": "Form", "lage": "Lage", "farbe": "Farbe", "material": "Material", "lagerteil": "Lagerteil"}
    for g in t["geaendert"][:max_teile]:
        extra = ""
        if g.get("dvolumen"):
            extra = f", Volumen {'+' if g['dvolumen'] > 0 else ''}{_num(g['dvolumen'], 1)} mm³"
        if g.get("verschiebung"):
            extra += f", verschoben um ({'; '.join(_num(x, 2) for x in g['verschiebung'])}) mm"
        zeilen.append(f"- geändert: {g['name']} ({', '.join(namen.get(a, a) for a in g['arten'])}{extra})")
    if len(t["geaendert"]) > max_teile:
        zeilen.append(f"- … und {len(t['geaendert']) - max_teile} weitere geänderte Teile")
    for name in t["neu"][:max_teile]:
        zeilen.append(f"- neu: {name}")
    for name in t["weg"][:max_teile]:
        zeilen.append(f"- weg: {name}")
    s = v["stueckliste"]
    for ln in s["neu"][:15]:
        zeilen.append(f"- Stückliste neu: {ln.get('anzahl')} × {ln.get('benennung')} {ln.get('masse_text') or ''}".rstrip())
    for ln in s["weg"][:15]:
        zeilen.append(f"- Stückliste weg: {ln.get('anzahl')} × {ln.get('benennung')} {ln.get('masse_text') or ''}".rstrip())
    for ln in s["geaendert"][:15]:
        alt_m = ln.get("alt_masse_text")
        mass = f"{alt_m} → {ln.get('masse_text')}" if alt_m and alt_m != ln.get("masse_text") else ln.get("masse_text")
        zeilen.append(f"- Stückliste geändert: {ln.get('benennung')} {mass or ''}, Anzahl {ln.get('alt_anzahl')} → "
                      f"{ln.get('neu_anzahl')}")
    pa, pb = v["pruefung"]["alt"], v["pruefung"]["neu"]
    if pa or pb:
        za = (pa or {}).get("zusammenfassung") or ("in Ordnung" if pa else "unbekannt")
        zb = (pb or {}).get("zusammenfassung") or ("in Ordnung" if pb else "unbekannt")
        if za != zb:
            zeilen.append(f"- Prüfung: {za} → {zb}")
    return "\n".join(zeilen)
