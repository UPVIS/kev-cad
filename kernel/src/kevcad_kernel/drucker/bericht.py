"""Text des MCP-Werkzeugs ``drucker_status`` (deutsch, Kevin liest mit). Nie mit Seriennummer oder Zugangscode: der
Status enthält sie nicht."""

from __future__ import annotations

from typing import Any

VERBINDUNG = {"aus": "aus", "verbindet": "verbindet", "verbunden": "verbunden (nur lesend)", "getrennt": "getrennt",
              "fehler": "Fehler"}


def _dauer(s: int | None) -> str:
    if s is None:
        return "?"
    h, m = divmod(int(s) // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def _satz(text: str) -> str:
    """Satzende anhängen, wenn noch keins da ist (sonst stand „Weg A geht trotzdem..“ im Status)."""
    text = text.rstrip()
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def status_text(st: dict[str, Any]) -> str:
    z: list[str] = []
    d = st.get("drucker")
    if d:
        fw = f", Firmware {d['firmware']}" if d.get("firmware") else ""
        modus = {"cloud": "Cloud-Modus", "lan": "LAN-Modus", "unbekannt": "Modus unbekannt"}.get(d.get("modus"), "")
        z.append(f"Drucker: {d.get('name')} ({d.get('modell')}) unter {d.get('ip') or '?'}, {modus}{fw}.")
    else:
        z.append("Kein Drucker eingestellt (Drucker-Einstellungen in Kev CAD).")
    verbindung = VERBINDUNG.get(st.get("verbindung"), st.get("verbindung"))
    z.append(_satz(f"Status: {verbindung}" + (f" – {st['meldung']}" if st.get("meldung") else "")))
    w = st.get("wege") or {}
    a, b = w.get("a") or {}, w.get("b") or {}
    z.append(f"Weg: {str(st.get('weg') or 'a').upper()} (A = in Bambu Studio öffnen"
             + ("" if a.get("moeglich", True) else f", nicht möglich: {a.get('grund')}") + "; B = direkt, "
             + ("möglich" if b.get("moeglich") else f"gesperrt: {b.get('grund')}") + ").")
    p = st.get("druck")
    if p:
        teile = [p.get("zustand") or "unbekannt"]
        if p.get("fortschritt") is not None:
            teile.append(f"{round(p['fortschritt'] * 100)} %")
        if p.get("schicht") is not None and p.get("schichten"):
            teile.append(f"Schicht {p['schicht']}/{p['schichten']}")
        if p.get("restzeit_s") is not None and p.get("zustand") in ("druckt", "pausiert", "vorbereiten"):
            teile.append(f"noch {_dauer(p['restzeit_s'])}")
        if p.get("aufgabe"):
            teile.append(f"„{p['aufgabe']}“")
        if p.get("stufe") and p.get("stufe") != "druckt":
            teile.append(str(p["stufe"]))
        z.append("Druck: " + ", ".join(teile) + ".")
    t = st.get("temperaturen")
    if t:
        def grad(ist: Any, soll: Any) -> str:
            if ist is None:
                return "?"
            return f"{ist:g} °C" + (f" (Ziel {soll:g})" if soll else "")

        z.append(f"Temperaturen: Düse {grad(t.get('duese'), t.get('duese_ziel'))}, Bett "
                 f"{grad(t.get('bett'), t.get('bett_ziel'))}.")
    for f in st.get("fehler") or []:
        z.append(f"{'Fehler' if f.get('schwere') == 'fehler' else 'Hinweis'} {f.get('code')}: {f.get('text')}")
    auf = st.get("auftrag")
    if auf:
        platten = ", ".join(str(n) for n in auf.get("platten") or []) or "alle"
        z.append(f"Auftrag {auf.get('auftrag')} ({'vom Agenten' if auf.get('von') == 'agent' else 'von Kevin'}, Weg "
                 f"{str(auf.get('weg')).upper()}, Platten {platten}): {auf.get('zustand')}"
                 + (f" – {_satz(str(auf['meldung']))}" if auf.get("meldung") else "")
                 + (f" Datei: {auf['datei']}" if auf.get("datei") else ""))
    gef = st.get("gefunden") or []
    if gef:
        z.append("Im LAN gehört: " + "; ".join(f"{g.get('name')} ({g.get('modell')}, {g.get('ip')}, "
                                               f"{g.get('verbindung') or '?'})" for g in gef) + ".")
    z.append("Kamera: nicht genutzt (im Cloud-Modus nicht sicher erlaubt).")
    return "\n".join(z)
