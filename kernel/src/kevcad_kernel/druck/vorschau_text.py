"""Deutsche Kurzfassung der Druckvorschau für das MCP-Werkzeug ``druckvorschau`` (rechnet nichts)."""

from __future__ import annotations

from typing import Any

STAND_TEXT = {"schaetzung": "Schätzung", "slicer": "Bambu Studio", "gemischt": "teils Bambu Studio"}
SLICER_TEXT = {"aus": "aus", "wartet": "wartet", "rechnet": "rechnet", "fertig": "fertig", "fehler": "Fehler"}


def _n(x: Any, nd: int = 1) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "?"
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".") if nd else f"{v:.0f}"
    return s.replace(".", ",")


def dauer_text(s: Any) -> str:
    try:
        sek = int(round(float(s)))
    except (TypeError, ValueError):
        return "?"
    h, rest = divmod(sek, 3600)
    m = rest // 60
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min" if m else f"{sek} s"


def einstellungen_text(e: dict[str, Any]) -> str:
    teile = [f"{_n(e.get('schicht_mm'), 2)} mm", f"{e.get('waende')} Wände",
             f"{_n(float(e.get('fuellung') or 0) * 100, 0)} % {str(e.get('muster') or '').capitalize()}",
             f"{e.get('decken')}/{e.get('boeden')} Decken/Böden",
             "keine Stützen" if e.get("stuetzen") in (None, "keine") else f"Stützen {e.get('stuetzen')}",
             "Brim" if e.get("brim") else "ohne Brim"]
    return ", ".join(teile)


def text(v: dict[str, Any]) -> str:
    s = v.get("summe") or {}
    z = [f"Druckvorschau Lauf {v.get('run')} ({STAND_TEXT.get(v.get('stand'), v.get('stand'))}), "
         f"{v.get('drucker')}" + (" – Reglerstand, nur Schätzung" if v.get("regler") else "") + ":"]
    if not v.get("teile"):
        z.append("Keine Druckteile im Modell.")
        return "\n".join(z)
    kt = s.get("kosten_teile") or {}
    z.append(f"Summe: {s.get('platten')} Platte{'n' if s.get('platten') != 1 else ''}, {dauer_text(s.get('zeit_s'))}"
             f" (mit Plattenwechsel {dauer_text(s.get('zeit_mit_wechsel_s'))}), {_n(s.get('kosten'), 2)} € "
             f"(Filament {_n(kt.get('filament'), 2)} €, Strom {_n(kt.get('strom'), 2)} €, Risiko "
             f"{_n(kt.get('risiko'), 2)} €).")
    z.append("Material: " + "; ".join(
        f"{m.get('name')} {_n(m.get('g'))} g, {_n(m.get('m'))} m, {_n(m.get('kosten'), 2)} € "
        f"({_n(m.get('preis_kg'), 2)} €/kg, Stand {m.get('preis_stand') or '?'}; {STAND_TEXT.get(m.get('stand'))})"
        for m in s.get("material") or []) + ".")
    namen = {t.get("gruppe"): t.get("name") for t in v.get("teile") or []}
    for p in v.get("platten") or []:
        zaehl: dict[str, int] = {}
        for t in p.get("teile") or []:
            zaehl[t.get("gruppe")] = zaehl.get(t.get("gruppe"), 0) + 1
        mat = (p.get("material") or [{}])[0]
        z.append(f"Platte {p.get('nr')} ({str(mat.get('material', '')).upper()}, {STAND_TEXT.get(p.get('stand'))}, "
                 f"Anordnung {p.get('anordnung')}): {dauer_text(p.get('zeit_s'))}, {_n(mat.get('g'))} g, "
                 f"Auslastung {_n(float(p.get('auslastung') or 0) * 100, 0)} %: "
                 + ", ".join(f"{namen.get(g, g)} ×{n}" for g, n in zaehl.items())
                 + (" – PASST NICHT" if p.get("passt_nicht") else ""))
    z.append("Teile:")
    for t in v.get("teile") or []:
        abw = t.get("abweichung")
        quelle = STAND_TEXT.get(t.get("stand")) or ""
        if abw is not None:
            quelle += f", Schätzung lag {_n(abs(abw) * 100, 0)} % {'darüber' if abw > 0 else 'darunter'}"
        z.append(f"- {t.get('gruppe')} {t.get('name')} ×{t.get('anzahl')}, {str(t.get('material')).upper()}, "
                 f"{t.get('zweck')}{' (geschätzt)' if t.get('zweck_geschaetzt') else ''}: {_n(t.get('g'))} g, "
                 f"{dauer_text(t.get('zeit_s'))} ({quelle}); {einstellungen_text(t.get('einstellungen') or {})}"
                 + (f"; fest: {', '.join(t.get('fest'))}" if t.get("fest") else ""))
        for b in (t.get("begruendung") or [])[:3]:
            z.append(f"    {b}")
        for h in t.get("hinweise") or []:
            z.append(f"    {str(h.get('schwere', '')).capitalize()}: {h.get('text')}")
    for h in v.get("hinweise") or []:
        z.append(f"{str(h.get('schwere', '')).capitalize()}: {h.get('text')}")
    sl_ = v.get("slicer") or {}
    z.append(f"Slicer: {SLICER_TEXT.get(sl_.get('zustand'), sl_.get('zustand'))}"
             + (f" {sl_.get('fertig')}/{sl_.get('gesamt')}" if sl_.get("gesamt") else "")
             + (f" ({sl_.get('meldung')})" if sl_.get("meldung") else "")
             + (f", Bambu Studio {sl_.get('version')}" if sl_.get("version") else "") + ".")
    return "\n".join(z)
