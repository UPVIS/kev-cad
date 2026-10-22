"""Bereits gedruckte Teile (Strang „Feinschliff 2“, Punkt 7; DRUCKVORSCHAU.md Abschnitt „Gedruckt“).

``lager.druckteil(…, gedruckt=True)`` kennzeichnet ein Teil, das Kevin schon gedruckt hat. Es bleibt in Modell und
Stückliste, fällt aber aus Druckvorschau, Druckexport, Druckbericht, Filament der Einkaufsliste und dem Bauplanschritt
„Drucken“ heraus. Damit das Gedruckte zum Modell passt, schreibt der Kernel beim ersten Lauf mit ``gedruckt=True`` die
Form fest: ``<projekt>/gedruckt.json`` (gehört zu den Projektdateien und damit zu den Versionen)::

    {"version": 1, "teile": {"Kugelschieber/Fangrolle (Druck)": {
        "signatur": {...wie druck/signatur.py...}, "groesse": [35.7, 35.7, 100.0], "volumen": 49379.8,
        "material": "petg", "seit": "2026-10-22T10:15:00"}}}

Ändert sich die Form später (Volumen, Oberfläche, Hauptmomente oder Spiegelbild), meldet der Prüfer ``gedruckt`` den
Befund ``gedruckt_geaendert`` (Warnung, kein Fehler): „Fangrolle ist als gedruckt markiert, die Form hat sich geändert
(Volumen +3 %). Neu drucken oder Änderung zurücknehmen.“ Heraus kommt man mit ``gedruckt=True, neu_drucken=True``
(ein Lauf schreibt die neue Form fest; danach ``neu_drucken`` wieder weglassen) oder durch Löschen des Eintrags.

- Rechenprozess: Prüfer ``gedruckt`` (nach „druckvorschau“) vergleicht mit der Datei (nur lesen) und legt das Ergebnis
  je Teil in ``ergebnis["druck"]["gedruckt"]`` ab.
- Laufzeit (``GedrucktAnbindung``): schreibt nach dem CHECK neue Einträge (``neu``, ``neu_drucken``).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.druck import signatur as sg

DATEI = "gedruckt.json"
# Engere Grenzen als beim Gruppieren: dasselbe Netz derselben Form ändert sich zwischen Läufen nicht
TOLERANZ = {"v": 0.002, "a": 0.003, "m": 0.005, "k": 0.05, "g_mm": 0.1}


def pfad(projekt: str | Path) -> Path:
    return Path(projekt) / DATEI


def lies(projekt: str | Path | None) -> dict[str, Any]:
    """Inhalt von gedruckt.json (fehlt die Datei: leer; kaputt: leer mit ``fehler``)."""
    leer: dict[str, Any] = {"version": 1, "teile": {}}
    if projekt is None:
        return leer
    try:
        d = json.loads(pfad(projekt).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return leer
    except (OSError, ValueError) as exc:
        return {**leer, "fehler": f"gedruckt.json nicht lesbar: {exc}"}
    if not isinstance(d, dict) or not isinstance(d.get("teile", {}), dict):
        return {**leer, "fehler": "gedruckt.json muss {\"version\": 1, \"teile\": {…}} sein"}
    d.setdefault("version", 1)
    d.setdefault("teile", {})
    return d


def schreibe(projekt: str | Path, daten: dict[str, Any]) -> None:
    """Atomar schreiben (Temp-Datei im selben Ordner, dann ersetzen)."""
    p = pfad(projekt)
    text = json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".gedruckt.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _rel(x: float, y: float, tol: float) -> bool:
    return abs(x - y) <= tol * max(abs(x), abs(y), 1e-9)


def geaendert(alt: dict[str, Any], neu: dict[str, Any]) -> list[str]:
    """Unterschiede der festgeschriebenen Form (``alt``: Signatur) zur jetzigen (``neu``); leer = unverändert. Nur
    lageunabhängige Größen (Volumen, Oberfläche, Hauptmomente, Momente): eine andere Druckausrichtung ändert nichts."""
    out: list[str] = []

    def prozent(x: float, y: float) -> str:
        p = (y - x) / x * 100 if x else 0.0
        return (f"{'+' if p >= 0 else '−'}{abs(p):.1f} %").replace(".", ",")

    va, vn = float(alt.get("v") or 0.0), float(neu.get("v") or 0.0)
    aa, an = float(alt.get("a") or 0.0), float(neu.get("a") or 0.0)
    if not _rel(va, vn, TOLERANZ["v"]):
        out.append(f"Volumen {prozent(va, vn)}")
    if not _rel(aa, an, TOLERANZ["a"]):
        out.append(f"Oberfläche {prozent(aa, an)}")
    ma, mn = alt.get("m") or [], neu.get("m") or []
    momente = len(ma) == len(mn) == 3 and all(
        abs(float(x) - float(y)) <= TOLERANZ["m"] * max(float(ma[0]), float(mn[0]), 1e-9) for x, y in zip(ma, mn))
    ga, gn = sorted(float(x) for x in alt.get("g") or []), sorted(float(x) for x in neu.get("g") or [])
    if len(ga) == len(gn) == 3 and any(abs(x - y) > TOLERANZ["g_mm"] for x, y in zip(ga, gn)):
        def mm(xs: list[float]) -> str:
            return " × ".join(f"{x:.1f}".replace(".", ",").replace(",0", "") for x in xs)
        out.append(f"Maße {mm(ga)} → {mm(gn)} mm")
    if not momente and not out:
        out.append("Form innen geändert (Verteilung, Bohrungen oder Taschen)")
    ka, kn = alt.get("k") or [], neu.get("k") or []
    if not out and ka and kn and len(ka) == len(kn) and not (alt.get("e") or neu.get("e")):
        if sg._abstand(ka, kn, False) > TOLERANZ["k"]:
            out.append("gespiegelt" if sg._abstand(ka, kn, True) <= TOLERANZ["k"]
                       else "Form innen geändert (Verteilung, Bohrungen oder Taschen)")
    return out


def _exakt(k: Any) -> tuple[float | None, list[float] | None]:
    """Volumen und Maße der B-Rep (``k``: Prüfkörper): die Signatur rechnet auf dem Netz und dient nur dem Vergleich;
    angezeigt werden die exakten Werte wie in der Stückliste (KevCup, 22.10.2026: 49 379,8 statt 49 273 mm³)."""
    if k is None:
        return None, None
    vol = float(getattr(k, "volumen", 0.0) or 0.0) or None
    try:
        from OCP.Bnd import Bnd_OBB
        from OCP.BRepBndLib import BRepBndLib

        obb = Bnd_OBB()
        BRepBndLib.AddOBB_s(k.shape, obb, True, True, False)
        groesse = sorted(round(2.0 * h, 2) for h in (obb.XHSize(), obb.YHSize(), obb.ZHSize()))
    except Exception:  # noqa: BLE001 - ohne OBB bleiben die Maße der Signatur
        groesse = None
    return vol, groesse


def eintrag(sig: dict[str, Any], geo: dict[str, Any], k: Any = None) -> dict[str, Any]:
    vol, groesse = _exakt(k)
    return {"signatur": sig, "groesse": groesse or list(sig.get("g") or geo.get("groesse") or []),
            "volumen": round(vol if vol else float(sig.get("v") or geo.get("volumen") or 0.0), 1),
            "material": geo.get("material"), "seit": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ---------------------------------------------------------------------------------------------------------------------
# Prüfer im Rechenprozess


def pruefe(ctx: Any) -> list[dict[str, Any]]:
    """Prüffunktion „gedruckt“: Form der als gedruckt markierten Teile mit gedruckt.json vergleichen."""
    from kevcad_kernel.druck.vorschau_geo import teil_mit_form
    from kevcad_kernel.pruefung.befund import befund

    druck = ctx.ergebnis.get("druck") or {}
    vorschau = druck.get("vorschau") or {}
    namen = [n for n, k in ctx.koerper.items() if k.info.get("druck_gedruckt")]
    if not namen:
        return []
    projekt = ctx.optionen.get("projekt")
    datei = lies(projekt)
    gespeichert = datei.get("teile") or {}
    out: list[dict[str, Any]] = []
    stand: dict[str, Any] = {}
    for name in namen:
        k = ctx.koerper[name]
        geo = teil_mit_form(vorschau, name) or {}
        sig = geo.get("signatur")
        if not isinstance(sig, dict):
            stand[name] = {"status": "ohne_signatur"}
            continue
        e = gespeichert.get(name)
        if k.info.get("druck_neu_drucken"):
            stand[name] = {"status": "neu_drucken", "eintrag": eintrag(sig, geo, k)}
        elif not isinstance(e, dict) or not isinstance(e.get("signatur"), dict):
            stand[name] = {"status": "neu", "eintrag": eintrag(sig, geo, k)}
        else:
            diff = geaendert(e["signatur"], sig)
            stand[name] = {"status": "geaendert" if diff else "gleich", "unterschiede": diff, "seit": e.get("seit")}
            if diff:
                kurz = name.rsplit("/", 1)[-1].replace(" (Druck)", "")
                out.append(befund(
                    "gedruckt_geaendert", [name], "warnung",
                    f"{kurz} ist als gedruckt markiert, die Form hat sich geändert ({', '.join(diff)}).",
                    "Neu drucken (lager.druckteil(…, gedruckt=True, neu_drucken=True) einen Lauf lang, dann neu_drucken "
                    "weglassen) oder die Änderung zurücknehmen.",
                    wert={"pruefung": "gedruckt", "unterschiede": diff, "seit": e.get("seit")}))
    if datei.get("fehler"):
        out.append(befund("gedruckt_geaendert", namen[:1], "hinweis", str(datei["fehler"]),
                          "gedruckt.json reparieren oder löschen; dann schreibt der nächste Lauf die Formen neu fest.",
                          wert={"pruefung": "gedruckt", "datei": True}))
    druck["gedruckt"] = stand
    ctx.ergebnis["druck"] = druck
    return out


# Registriert wird in pruefung/lauf.py (nach „druckvorschau“, unabhängig von der Reihenfolge der Importe).


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit


class GedrucktAnbindung:
    """Mixin für ``KernelRuntime``: neue Formen nach dem CHECK in gedruckt.json festschreiben. Erwartet ``_project``,
    ``_log``."""

    def _gedruckt_check(self, check: dict[str, Any]) -> None:
        if check.get("state") not in ("done", "teilweise"):
            return
        if int(check.get("run") or 0) >= 1_000_000_000:  # Schattenlauf der Versionen
            return
        stand = ((check.get("druck") or {}).get("gedruckt")) or {}
        neu = {n: s["eintrag"] for n, s in stand.items()
               if isinstance(s, dict) and s.get("status") in ("neu", "neu_drucken") and s.get("eintrag")}
        proj = self._project  # type: ignore[attr-defined]
        if not neu or proj is None:
            return
        try:
            daten = lies(proj.path)
            if daten.get("fehler"):
                return  # kaputte Datei nicht überschreiben (der Befund sagt es)
            geaendert_ = False
            for name, e in neu.items():
                alt = (daten["teile"] or {}).get(name)
                if stand[name].get("status") == "neu_drucken" and isinstance(alt, dict) and \
                        alt.get("signatur") == e.get("signatur"):
                    continue
                daten["teile"][name] = e
                geaendert_ = True
            if geaendert_:
                daten.pop("fehler", None)
                schreibe(proj.path, daten)
                self._log(f"[kernel] gedruckt.json: Form festgeschrieben für {', '.join(neu)}")  # type: ignore
        except Exception as exc:  # noqa: BLE001 - die Kennzeichnung darf die Laufzeit nicht stören
            self._log(f"[kernel] gedruckt.json nicht geschrieben: {type(exc).__name__}: {exc}")  # type: ignore
