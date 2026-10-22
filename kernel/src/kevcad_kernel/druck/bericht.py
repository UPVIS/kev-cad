"""Texte und Auszüge der Druckprüfung für das Laufergebnis (``run``) und das MCP-Werkzeug ``druckpruefung``.

Quelle ist das Feld ``druck`` im letzten CHECK (siehe ``druck/anbindung.py``) samt den Befunden mit
``wert.pruefung == "druck"``. Rechnet nichts (läuft in der Kernel-Laufzeit und im MCP-Server).
"""

from __future__ import annotations

import difflib
from typing import Any

SCHWERE_TEXT = {"fehler": "Fehler", "warnung": "Warnung", "hinweis": "Hinweis"}
MAX_TEILE_IM_LAUF = 6  # bis zu so vielen Druckteilen nennt run die Ausrichtung je Teil im Text


def _num(x: Any, nd: int = 1) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "?"
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".") if nd else f"{v:.0f}"
    return s.replace(".", ",")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def druck_befunde(check: dict[str, Any], teil: str | None = None) -> list[dict[str, Any]]:
    out = [b for b in check.get("befunde") or [] if (b.get("wert") or {}).get("pruefung") == "druck"]
    if teil is not None:
        out = [b for b in out if (b.get("teile") or [None])[0] == teil]
    return out


def ohne_druckhinweise(befunde: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Befunde ohne die Hinweise der Druckprüfung (fürs Laufergebnis; die App und druckpruefung zeigen sie)."""
    out = [b for b in befunde if not ((b.get("wert") or {}).get("pruefung") == "druck"
                                      and b.get("schwere") == "hinweis")]
    return out, len(befunde) - len(out)


def druck_kurz(druck: dict[str, Any]) -> dict[str, Any]:
    """Gekürzt fürs Laufergebnis: je Teil Zusammenfassung und Ausrichtung samt Begründung."""
    teile = {}
    for name, t in (druck.get("teile") or {}).items():
        a = t.get("ausrichtung") or {}
        teile[name] = {"zusammenfassung": t.get("zusammenfassung"),
                       "ausrichtung": {k: a.get(k) for k in ("text", "liegt_auf", "automatisch", "vorgabe",
                                                             "begruendung", "drehung")}}
        if t.get("gedruckt"):
            teile[name]["gedruckt"] = True
    return {"drucker": druck.get("drucker"), "teile": teile, "zaehler": _summen(druck),
            "festigkeit": {m: v.get("festigkeit") for m, v in (druck.get("materialien") or {}).items()},
            "neu_geprueft": druck.get("neu_geprueft"), "aus_zwischenspeicher": druck.get("aus_zwischenspeicher"),
            "dauer_ms": druck.get("dauer_ms")}


def _summen(druck: dict[str, Any]) -> dict[str, int]:
    if isinstance(druck.get("zaehler"), dict):  # gekürzte Fassung (druck_kurz)
        return dict(druck["zaehler"])
    out = {"fehler": 0, "warnung": 0, "hinweis": 0}
    for t in (druck.get("teile") or {}).values():
        for k, v in (t.get("zaehler") or {}).items():
            out[k] = out.get(k, 0) + int(v or 0)
    return out


def druck_zeilen(druck: dict[str, Any] | None) -> list[str]:
    """Zeilen für den Abschnitt „Prüfung“ von run: Kopf mit Summen, bei wenigen Teilen die Ausrichtung je Teil."""
    if not druck or not druck.get("teile"):
        return []
    teile = druck["teile"]
    s = _summen(druck)
    kopf = (f"Druckprüfung ({druck.get('drucker') or 'Bambu Lab P1P'}): {_plural(len(teile), 'Druckteil', 'Druckteile')}"
            f", {_plural(s['fehler'], 'Fehler', 'Fehler')}, {_plural(s['warnung'], 'Warnung', 'Warnungen')}, "
            f"{_plural(s['hinweis'], 'Hinweis', 'Hinweise')}")
    neu, alt = int(druck.get("neu_geprueft") or 0), int(druck.get("aus_zwischenspeicher") or 0)
    kopf += f" ({neu} neu geprüft, {alt} aus dem Zwischenspeicher, {_num(druck.get('dauer_ms'), 0)} ms)."
    zeilen = [kopf]
    gedruckt = [n for n, t in teile.items() if t.get("gedruckt")]
    if gedruckt:
        zeilen.append(f"Gedruckt, vorhanden (nicht mehr geprüft): {', '.join(gedruckt)}.")
    if len(teile) <= MAX_TEILE_IM_LAUF:
        for name, t in teile.items():
            if t.get("gedruckt"):
                continue
            a = t.get("ausrichtung") or {}
            art = "automatisch" if a.get("automatisch") else f"vorgegeben: {a.get('vorgabe')}"
            zeilen.append(f"- Ausrichtung {name}: {a.get('text')} ({art}). {a.get('begruendung') or ''}".rstrip())
    hinweise = " und alle Hinweise" if s["hinweis"] else ""
    if len(teile) <= MAX_TEILE_IM_LAUF:
        zeilen.append(f"Kennzahlen, Materialeinstellungen{hinweise}: druckpruefung.")
    else:
        zeilen.append(f"Ausrichtung und Begründung je Teil stehen im Ergebnis (pruefung.druck); Kennzahlen{hinweise} "
                      "mit druckpruefung oder druckpruefung(teil=…).")
    return zeilen


# ---------------------------------------------------------------------------------------------------------------------
# Werkzeug druckpruefung


def _mit_refs(befunde: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Referenzen Teil#f<n> zu den Flächen (für focus, highlight, annotate)."""
    out = []
    for b in befunde:
        flaechen = (b.get("wert") or {}).get("flaechen") or []
        out.append({**b, "refs": [f"{b['teile'][0]}#f{f}" for f in flaechen]} if flaechen and b.get("teile") else b)
    return out


def druck_auszug(check: dict[str, Any] | None, teil: str | None = None,
                 namen: list[str] | None = None) -> dict[str, Any]:
    """Ergebnis für ``KernelService.druckpruefung``: {"ok", "run", "drucker", "teile": [{"name", …, "befunde"}],
    "materialien", "zaehler", "statistik"} oder {"ok": False, "error"}."""
    if check is None:
        return {"ok": False, "error": "Noch keine Prüfung: erst run aufrufen."}
    state = check.get("state")
    if state == "failed":
        return {"ok": False, "error": f"Prüfung fehlgeschlagen: {check.get('message') or 'ohne Meldung'}"}
    if state not in (None, "done", "teilweise"):  # teilweise: nur der Bewegungsraum rechnet noch
        return {"ok": False, "error": f"Prüfung {state}: erst run aufrufen und das Ergebnis abwarten."}
    druck = check.get("druck") or {}
    alle = druck.get("teile") or {}
    run = check.get("run")
    if teil is not None:
        t = teil.strip()
        gruppe = t.rstrip("/") + "/"
        gewaehlt = [n for n in alle if n == t or n.startswith(gruppe)]
        if not gewaehlt:
            if namen and (t in namen or any(n.startswith(gruppe) for n in namen)):
                return {"ok": False, "error": f"{t} ist kein Druckteil (nur Teile aus lager.druckteil(...) werden auf "
                                              "Druckbarkeit geprüft)."}
            tips = difflib.get_close_matches(t, list(alle) or list(namen or []), n=3, cutoff=0.5)
            return {"ok": False, "error": f"Kein Druckteil {t!r} im letzten Lauf"
                                          + (f"; meinten Sie {', '.join(repr(x) for x in tips)}?" if tips else ".")}
    else:
        gewaehlt = list(alle)
    teile = []
    for name in gewaehlt:
        teile.append({"name": name, **alle[name], "befunde": _mit_refs(druck_befunde(check, name))})
    andere = [b for b in druck_befunde(check) if (b.get("teile") or [None])[0] not in alle]
    if teil is None and andere:  # Teile ohne Ergebnis (unbekanntes Material, Prüfung fehlgeschlagen)
        for b in andere:
            teile.append({"name": b["teile"][0], "befunde": [b], "zusammenfassung": "nicht geprüft"})
    zaehler = {"fehler": 0, "warnung": 0, "hinweis": 0}
    for t in teile:
        for b in t["befunde"]:
            zaehler[b["schwere"]] = zaehler.get(b["schwere"], 0) + 1
    mats = {m for t in teile for m in [t.get("material")] if m}
    return {"ok": True, "run": run, "drucker": druck.get("drucker"), "teile": teile, "zaehler": zaehler,
            "materialien": {m: v for m, v in (druck.get("materialien") or {}).items() if m in mats},
            "statistik": {"neu_geprueft": druck.get("neu_geprueft"),
                          "aus_zwischenspeicher": druck.get("aus_zwischenspeicher"),
                          "dauer_ms": druck.get("dauer_ms")}}


def _kennzahlen_text(kz: dict[str, Any]) -> str:
    teile = []
    abm = kz.get("abmessungen_mm")
    if abm:
        teile.append(" × ".join(_num(x, 1) for x in abm) + " mm auf dem Bett")
    if kz.get("schichten") is not None:
        teile.append(f"{kz['schichten']} Schichten")
    if kz.get("stuetzflaeche_mm2") is not None:
        teile.append(f"Stützfläche ca. {_num(kz['stuetzflaeche_mm2'], 0)} mm²")
    if kz.get("auflageflaeche_mm2") is not None:
        teile.append(f"Auflage {_num(kz['auflageflaeche_mm2'], 0)} mm²")
    if kz.get("volumen_cm3") is not None:
        teile.append(f"{_num(kz['volumen_cm3'], 1)} cm³ (voll {_num(kz.get('masse_voll_g'), 1)} g)")
    if kz.get("bauraum_ausnutzung_prozent") is not None:
        teile.append(f"Bauraum {_num(kz['bauraum_ausnutzung_prozent'], 0)} %")
    return ", ".join(teile)


def druck_text(res: dict[str, Any]) -> str:
    """Text des Werkzeugs druckpruefung (deutsch, Kevin liest mit)."""
    teile = res.get("teile") or []
    if not teile:
        return (f"Lauf {res.get('run', '?')}: keine Druckteile. Selbst konstruierte Druckteile mit "
                "lager.druckteil(form, \"Name\", material=\"petg\") anlegen; dann prüft die Druckprüfung sie bei "
                "jedem Lauf.")
    z = res.get("zaehler") or {}
    st = res.get("statistik") or {}
    zeilen = [f"Druckprüfung Lauf {res.get('run', '?')} ({res.get('drucker') or 'Bambu Lab P1P'}): "
              f"{_plural(len(teile), 'Druckteil', 'Druckteile')}, {_plural(z.get('fehler', 0), 'Fehler', 'Fehler')}, "
              f"{_plural(z.get('warnung', 0), 'Warnung', 'Warnungen')}, "
              f"{_plural(z.get('hinweis', 0), 'Hinweis', 'Hinweise')} "
              f"({_num(st.get('dauer_ms'), 0)} ms, {st.get('aus_zwischenspeicher') or 0} aus dem Zwischenspeicher)."]
    for t in teile:
        zeilen.append("")
        zeilen.append(f"{t['name']} – {t.get('material_name') or t.get('material') or '?'}: "
                      f"{t.get('zusammenfassung') or ''}")
        a = t.get("ausrichtung") or {}
        if a:
            art = "automatisch" if a.get("automatisch") else f"vorgegeben: {a.get('vorgabe')}"
            auf = f", liegt auf {a['liegt_auf']}" if a.get("liegt_auf") else ""
            dreh = a.get("drehung")
            dreh_text = (f", Rot({', '.join(_num(w, 1) for w in dreh)}) * form legt es so aufs Bett"
                         if dreh and any(abs(float(w)) > 1e-6 for w in dreh) else "")
            zeilen.append(f"  Ausrichtung: {a.get('text')} ({art}{auf}{dreh_text}).")
            if a.get("begruendung"):
                zeilen.append(f"  Begründung: {a['begruendung']}")
        kz = _kennzahlen_text(t.get("kennzahlen") or {})
        if kz:
            zeilen.append(f"  Kennzahlen: {kz}.")
        for b in t.get("befunde") or []:
            zeilen.append(f"  - [{SCHWERE_TEXT.get(b.get('schwere'), b.get('schwere'))}] {b.get('text', '')}")
            if b.get("loesung"):
                zeilen.append(f"    Abhilfe: {b['loesung']}")
    for mid, m in (res.get("materialien") or {}).items():
        zeilen.append("")
        zeilen.append(f"Materialeinstellungen {m.get('name') or mid}:")
        for h in m.get("druckhinweise") or []:
            zeilen.append(f"  - {h}")
        if m.get("festigkeit"):
            zeilen.append(f"  - {m['festigkeit']}")
    if z.get("fehler"):
        zeilen.append("")
        zeilen.append("Fehler sperren den Export: beheben (teilen, anderes Material) und run erneut aufrufen.")
    return "\n".join(zeilen)
