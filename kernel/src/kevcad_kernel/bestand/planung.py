"""Stückliste mit Bestand: Zuschnitt aus Resten, Bestand und Kauf, Stückgut, Einkaufsliste (BESTAND.md).

``plane(bom, bestand, katalog)`` nimmt die Stückliste eines Laufs (wie ``build_bom`` sie liefert, mit ``run``) und den
Bestand des Projekts und gibt eine erweiterte Kopie zurück. Die bisherigen Felder bleiben, wie sie sind; dazu kommen:

- je Stangenware in ``cuts[i]``: ``art: "stange"``, ``quellen``, ``neue_reste``, ``aus_bestand``, ``kaufen``,
  ``mindestrest``;
- je Platte ein neuer Eintrag in ``cuts`` mit ``art: "platte"``, ``platte: {b, h}`` (Kaufformat oder null),
  ``saegeschnitt`` und denselben neuen Feldern;
- je Zuschnitt ``verschnitt_prozent`` nach Definition 2 (Sägeschnitte und Reste unter dem Mindestrest, bezogen auf die
  verplante Länge bzw. Fläche der Quellen; neue Reste zählen nicht) mit ``verschnitt_definition: "2"``, dazu
  ``verschnitt`` über alle Stangen bzw. Platten;
- ``stueckgut``: je Schraube, Mutter, Scheibe gebraucht, aus dem Bestand, zu kaufen;
- ``zukauf_bestand``: je Stücklistenzeile eines Zukaufteils (auch Kamera, Objektiv, Kamerazubehör) gebraucht, aus dem
  Bestand, zu kaufen (die Einkaufsliste führt nur ``kaufen``);
- ``einkaufsliste``, ``einkauf_summe``, ``einkauf_hinweis``, ``bestand_stand``, ``fehlt``.

Ohne Bestandsdatei ist alles zu kaufen. Druckteile und Eigenteile stehen (noch) nicht auf der Einkaufsliste.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from kevcad_kernel.bom import (
    VERSCHNITT_DEFINITION,
    de_num,
    first_fit_decreasing,
    round_half,
    verschnitt_prozent,
    verschnitt_summe,
)
from kevcad_kernel.catalog import KLEINTEILE, STANGENWARE, STUECKGUT_ZUKAUF, number

from .datei import einstellungen, mindestrest, zahl
from .zuschnitt import ZEITLIMIT_S, plane_1d, plane_2d, platzierungen


class KatalogQuelle(Protocol):
    def item(self, iid: str) -> dict[str, Any] | None: ...

    def material(self, mid: str) -> dict[str, Any] | None: ...


@dataclass
class Verbrauch:
    """Was der Zuschnitt eines Postens aus dem Projektbestand nimmt und was neu entsteht (für „Gebaut“)."""

    posten: str
    platte: bool = False
    reste: list[str] = field(default_factory=list)  # Kennungen
    ganze: int = 0
    ganze_mass: dict[str, float] = field(default_factory=dict)  # {"laenge"} bzw. {"b", "h"}
    neue_reste: list[Any] = field(default_factory=list)  # Längen bzw. {"b", "h"}
    stueck: list[tuple[float | None, int]] = field(default_factory=list)  # (Länge oder None, Anzahl)


@dataclass
class Planung:
    bom: dict[str, Any]
    verbrauch: list[Verbrauch]
    statistik: list[dict[str, Any]]  # je Zuschnitt: Verfahren, Dauer


def _r(x: float | None, digits: int = 2) -> float | None:
    return None if x is None else round(float(x), digits)


def _preis(item: dict[str, Any] | None) -> dict[str, Any]:
    p = (item or {}).get("preis")
    return p if isinstance(p, dict) else {}


def _bezug(item: dict[str, Any] | None) -> tuple[str | None, str | None]:
    bq = (item or {}).get("bezugsquelle")
    if isinstance(bq, dict) and isinstance(bq.get("url"), str) and bq["url"].strip():
        return bq["url"].strip(), (bq.get("name") or None)
    return None, None


def _stand(item: dict[str, Any] | None, material: dict[str, Any] | None) -> str | None:
    s = _preis(item).get("stand")
    return str(s) if s else ((material or {}).get("preis_stand") or None)


_MASS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*×\s*(\d+(?:[.,]\d+)?)")


def _platten_mass(line: dict[str, Any]) -> tuple[float, float] | None:
    b, t = number(line.get("breite")), number(line.get("tiefe"))
    if b and t:
        return float(b), float(t)
    m = _MASS_RE.search(str(line.get("masse_text") or "").replace(".", ""))
    if m:
        return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    return None


def _einheit_stange(laenge: float) -> str:
    return f"Stange {de_num(laenge)} mm"


def _einheit_platte(b: float, h: float, zuschnitt: bool = False) -> str:
    return f"{'Zuschnitt' if zuschnitt else 'Platte'} {de_num(b)} × {de_num(h)} mm"


def plane(bom: dict[str, Any], bestand: dict[str, Any] | None, katalog: KatalogQuelle, *, stand: str | None = None,
          fehler: str | None = None, zeitlimit_s: float = ZEITLIMIT_S) -> Planung:
    """Erweitert eine Stückliste um Zuschnitt mit Bestand und Einkaufsliste (siehe Moduldoku). ``bestand`` None: es
    gibt keine Bestandsdatei (alles kaufen). ``fehler``: Bestandsdatei kaputt (Hinweis, Zuschnitt ohne Bestand)."""
    out = copy.deepcopy(bom)
    posten_alle = ((bestand or {}).get("posten") or {}) if not fehler else {}
    e = einstellungen(bestand if not fehler else None)
    s = float(e["saegeblatt_mm"])
    warnings: list[str] = list(out.get("warnings") or [])
    if fehler:
        warnings.append(f"Bestand: {fehler} – Zuschnitt ohne Bestand, alles steht auf der Einkaufsliste")
    lines = list(out.get("lines") or [])
    cuts = [dict(c) for c in out.get("cuts") or []]
    einkauf: list[dict[str, Any]] = []
    verbrauch: list[Verbrauch] = []
    statistik: list[dict[str, Any]] = []

    def item_mat(sid: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        it = katalog.item(sid)
        mat = katalog.material(str(it.get("material"))) if it and it.get("material") else None
        return it, mat

    def kauf(sid: str, benennung: str, menge: int, einheit: str, preis_je: float | None, stand_: str | None,
             item: dict[str, Any] | None, hinweis: str | None) -> None:
        url, name = _bezug(item)
        einkauf.append({"id": sid, "benennung": benennung, "menge": menge, "einheit": einheit,
                        "preis_je": _r(preis_je), "preis": _r(preis_je * menge) if preis_je is not None else None,
                        "link": url, "link_text": name, "hinweis": hinweis, "preis_stand": stand_})

    # ---- Stangenware -------------------------------------------------------------------------------------------------
    bar_lines: dict[str, list[dict[str, Any]]] = {}
    for ln in lines:
        if ln.get("art") in STANGENWARE and ln.get("stock_id") and ln.get("laenge") is not None:
            bar_lines.setdefault(str(ln["stock_id"]), []).append(ln)
    for cut in cuts:
        sid = str(cut.get("stock_id"))
        rows = bar_lines.get(sid) or []
        if not rows:
            continue
        item, mat = item_mat(sid)
        kauf_laenge = float(cut.get("stangenlaenge") or 0) or None
        laengen = [float(ln["laenge"]) for ln in rows for _ in range(int(ln.get("anzahl") or 0))]
        if abs(float(cut.get("saegeschnitt") or s) - s) > 1e-9 and kauf_laenge:
            bars, too_long = first_fit_decreasing(laengen, kauf_laenge, s)
            cut["saegeschnitt"] = zahl(s)
            cut["stangen"] = bars
            if "preis_stangen" in cut:
                je_m = number(_preis(item).get("je_m"))
                if je_m is not None:
                    cut["preis_stangen"] = round(len(bars) * kauf_laenge / 1000.0 * je_m, 2)
        p = posten_alle.get(sid) if isinstance(posten_alle.get(sid), dict) else None
        m = mindestrest(bestand, p)
        reste = [(str(r.get("kennung")), float(r["laenge"])) for r in (p or {}).get("reste") or []
                 if isinstance(r, dict) and number(r.get("laenge"))]
        ganze = (p or {}).get("ganze") or {}
        g_anzahl = int(number(ganze.get("anzahl")) or 0)
        g_laenge = float(number(ganze.get("laenge")) or kauf_laenge or 0) or None
        plan = plane_1d(laengen, reste, g_anzahl, g_laenge, kauf_laenge, s, m, zeitlimit_s=zeitlimit_s)
        statistik.append({"stock_id": sid, "art": "stange", "verfahren": plan.verfahren, "dauer_ms": plan.dauer_ms,
                          "milp": plan.milp_status, "stuecke": len(laengen)})
        quellen: list[dict[str, Any]] = []
        v = Verbrauch(sid, False, ganze_mass={"laenge": zahl(g_laenge)} if g_laenge else {})
        for b in plan.belegungen:
            rest = b.rest(s)
            short = rest < m - 1e-6
            quellen.append({"art": b.quelle.art, "kennung": b.quelle.kennung, "laenge": zahl(b.quelle.laenge),
                            "stuecke": [zahl(x) for x in b.stuecke], "rest_neu": zahl(round_half(rest)),
                            "verschnitt": short and rest > 1e-6})
            if b.quelle.art == "rest":
                v.reste.append(str(b.quelle.kennung))
            elif b.quelle.art == "bestand":
                v.ganze += 1
            if not short:
                v.neue_reste.append(zahl(round_half(rest)))
        n_kauf = sum(1 for q in quellen if q["art"] == "kaufen")
        cut.update({"art": "stange", "quellen": quellen, "neue_reste": list(v.neue_reste),
                    "aus_bestand": {"reste": len(v.reste), "ganze": v.ganze}, "kaufen": n_kauf,
                    "mindestrest": zahl(m)})
        # Verschnitt (Definition 2) über die Quellen, genau wie die App: Sägeschnitte und Reste unter dem Mindestrest
        cut["verschnitt_prozent"] = verschnitt_prozent(cut, m)
        cut["verschnitt_definition"] = VERSCHNITT_DEFINITION
        if v.reste or v.ganze or v.neue_reste:
            verbrauch.append(v)
        benennung = str(cut.get("benennung") or (item or {}).get("name") or sid)
        je_m = number(_preis(item).get("je_m"))
        if je_m is None:
            priced = next((ln for ln in rows if ln.get("preis_je") is not None and ln.get("laenge")), None)
            je_m = float(priced["preis_je"]) / float(priced["laenge"]) * 1000.0 if priced else None
        hinweis = None
        if p is not None and (reste or g_anzahl):
            hinweis = (f"Bestand im Projekt reicht nicht: {_plural(v.ganze, 'ganze Stange', 'ganze Stangen')} und "
                       f"{_plural(len(v.reste), 'Rest', 'Reste')} verplant")
        if n_kauf and kauf_laenge:
            kauf(sid, benennung, n_kauf, _einheit_stange(kauf_laenge),
                 je_m * kauf_laenge / 1000.0 if je_m is not None else None, _stand(item, mat), item, hinweis)
        for laenge in sorted(set(plan.zu_lang), reverse=True):
            n = plan.zu_lang.count(laenge)
            kauf(sid, benennung, n, f"Sonderlänge {de_num(laenge)} mm",
                 je_m * laenge / 1000.0 if je_m is not None else None, _stand(item, mat), item,
                 f"länger als die Stange ({de_num(kauf_laenge or 0)} mm): Sonderlänge bestellen oder stoßen")

    # ---- Platten -----------------------------------------------------------------------------------------------------
    plate_lines: dict[str, list[dict[str, Any]]] = {}
    for ln in lines:
        if ln.get("art") == "platte" and ln.get("stock_id"):
            plate_lines.setdefault(str(ln["stock_id"]), []).append(ln)
    for sid, rows in plate_lines.items():
        item, mat = item_mat(sid)
        stuecke: list[tuple[float, float]] = []
        for ln in rows:
            dims = _platten_mass(ln)
            if dims is None:
                warnings.append(f"{ln.get('benennung')}: Plattenmaß unbekannt, nicht im Zuschnitt")
                continue
            stuecke += [dims] * int(ln.get("anzahl") or 0)
        if not stuecke:
            continue
        fmt = (item or {}).get("platte")
        kauf_fmt = (float(fmt[0]), float(fmt[1])) if isinstance(fmt, list) and len(fmt) == 2 else None
        p = posten_alle.get(sid) if isinstance(posten_alle.get(sid), dict) else None
        m = mindestrest(bestand, p)
        reste = [(str(r.get("kennung")), float(r["b"]), float(r["h"])) for r in (p or {}).get("reste") or []
                 if isinstance(r, dict) and number(r.get("b")) and number(r.get("h"))]
        ganze = (p or {}).get("ganze") or {}
        g_anzahl = int(number(ganze.get("anzahl")) or 0)
        g_fmt = ((float(ganze["b"]), float(ganze["h"])) if number(ganze.get("b")) and number(ganze.get("h"))
                 else kauf_fmt)
        plan = plane_2d(stuecke, reste, g_anzahl, g_fmt, kauf_fmt, s, m, zeitlimit_s=zeitlimit_s)
        statistik.append({"stock_id": sid, "art": "platte", "verfahren": plan.verfahren, "dauer_ms": plan.dauer_ms,
                          "varianten": plan.varianten, "stuecke": len(stuecke)})
        v = Verbrauch(sid, True, ganze_mass={"b": zahl(g_fmt[0]), "h": zahl(g_fmt[1])} if g_fmt else {})
        quellen = []
        for bel in plan.belegungen:
            neu = [{"b": zahl(r.b), "h": zahl(r.h), "x": zahl(r.x), "y": zahl(r.y)} for r in bel.reste(m)]
            quellen.append({"art": bel.quelle.art, "kennung": bel.quelle.kennung, "b": zahl(bel.quelle.b),
                            "h": zahl(bel.quelle.h),
                            "stuecke": [{**{k: zahl(d[k]) for k in ("b", "h", "x", "y")}, "gedreht": d["gedreht"]}
                                        for d in platzierungen(bel)],
                            "rest_neu": neu})
            if bel.quelle.art == "rest":
                v.reste.append(str(bel.quelle.kennung))
            elif bel.quelle.art == "bestand":
                v.ganze += 1
            v.neue_reste += [{"b": r["b"], "h": r["h"]} for r in neu]
        n_kauf = sum(1 for q in quellen if q["art"] == "kaufen")
        benennung = str(rows[0].get("benennung") or (item or {}).get("name") or sid)
        cuts.append({"stock_id": sid, "benennung": benennung, "art": "platte",
                     "platte": {"b": zahl(kauf_fmt[0]), "h": zahl(kauf_fmt[1])} if kauf_fmt else None,
                     "saegeschnitt": zahl(s), "verschnitt_prozent": 0.0,
                     "verschnitt_definition": VERSCHNITT_DEFINITION,
                     "quellen": quellen, "neue_reste": list(v.neue_reste),
                     "aus_bestand": {"reste": len(v.reste), "ganze": v.ganze}, "kaufen": n_kauf,
                     "mindestrest": zahl(m)})
        cuts[-1]["verschnitt_prozent"] = verschnitt_prozent(cuts[-1], m)
        if plan.zu_gross:
            cuts[-1]["zu_gross"] = [{"b": zahl(b), "h": zahl(h)} for b, h in plan.zu_gross]
        if v.reste or v.ganze or v.neue_reste:
            verbrauch.append(v)
        je_m2 = number(_preis(item).get("je_m2"))
        if je_m2 is None:
            priced = next((ln for ln in rows if ln.get("preis_je") is not None and ln.get("flaeche_m2")), None)
            je_m2 = float(priced["preis_je"]) / float(priced["flaeche_m2"]) if priced else None
        hinweis = None
        if p is not None and (reste or g_anzahl):
            hinweis = (f"Bestand im Projekt reicht nicht: {_plural(v.ganze, 'ganze Platte', 'ganze Platten')} und "
                       f"{_plural(len(v.reste), 'Rest', 'Reste')} verplant")
        kaufen_q = [q for q in quellen if q["art"] == "kaufen"]
        by_fmt: dict[tuple[float, float], int] = {}
        for q in kaufen_q:
            key = (float(q["b"]), float(q["h"]))
            by_fmt[key] = by_fmt.get(key, 0) + 1
        for (b, h), n in by_fmt.items():
            zuschnitt = kauf_fmt is None
            kauf(sid, benennung, n, _einheit_platte(b, h, zuschnitt),
                 je_m2 * b * h / 1e6 if je_m2 is not None else None, _stand(item, mat), item,
                 hinweis or ("kein Standardformat im Katalog: als Zuschnitt bestellen" if zuschnitt else None))
        for b, h in plan.zu_gross:
            kauf(sid, benennung, 1, _einheit_platte(b, h, True), je_m2 * b * h / 1e6 if je_m2 is not None else None,
                 _stand(item, mat), item, "größer als die Platte: als Zuschnitt bestellen oder stoßen")

    # ---- Stückgut ----------------------------------------------------------------------------------------------------
    stueckgut: list[dict[str, Any]] = []
    vorrat: dict[str, dict[float | None, int]] = {}
    for sid, p in posten_alle.items():
        if isinstance(p, dict) and isinstance(p.get("stueck"), list):
            pool: dict[float | None, int] = {}
            for row in p["stueck"]:
                if isinstance(row, dict):
                    key = None if row.get("laenge") is None else float(row["laenge"])
                    pool[key] = pool.get(key, 0) + int(number(row.get("anzahl")) or 0)
            vorrat[sid] = pool
    stueck_verbrauch: dict[str, Verbrauch] = {}
    for ln in lines:
        if ln.get("art") not in KLEINTEILE or not ln.get("stock_id"):
            continue
        sid = str(ln["stock_id"])
        item, mat = item_mat(sid)
        need = int(ln.get("anzahl") or 0)
        laenge = float(ln["laenge"]) if ln.get("art") == "schraube" and ln.get("laenge") is not None else None
        pool = vorrat.get(sid, {})
        have_before = (pool.get(laenge, 0) if laenge is not None else 0) + pool.get(None, 0)
        taken: list[tuple[float | None, int]] = []
        left = need
        for key in ([laenge, None] if laenge is not None else [None]):
            avail = pool.get(key, 0)
            k = min(avail, left)
            if k > 0:
                pool[key] = avail - k
                taken.append((key, k))
                left -= k
        aus = need - left
        stueckgut.append({"stock_id": sid, "benennung": ln.get("benennung"), "masse_text": ln.get("masse_text"),
                          "laenge": zahl(laenge) if laenge is not None else None, "anzahl": need,
                          "aus_bestand": aus, "kaufen": left})
        if taken:
            vb = stueck_verbrauch.setdefault(sid, Verbrauch(sid))
            vb.stueck += taken
        if left > 0:
            preis_je = number(ln.get("preis_je"))
            if preis_je is None:
                preis_je = number(_preis(item).get("je_stueck"))
            hinweis = f"Bestand im Projekt: {have_before}, gebraucht: {need}" if have_before else None
            name = str(ln.get("benennung") or sid)
            if laenge is not None:
                name += f", Länge {de_num(laenge)} mm"
            kauf(sid, name, left, "Stück", preis_je, _stand(item, mat), item, hinweis)
    # ---- Zukaufteile (Stückgut ohne Länge, Strang „Feinschliff 2“) ---------------------------------------------------
    # Was Kevin davon im Projekt hat, deckt die Stückliste zuerst; der Rest steht in der Gruppe „Zukaufteile“ der
    # Einkaufsliste (einkauf.py, MaterialDaten), nicht unter Lagerware. „Gebaut“ zieht das Verplante ab.
    zukauf_bestand: list[dict[str, Any]] = []
    for ln in lines:
        if ln.get("art") not in STUECKGUT_ZUKAUF or not ln.get("stock_id") or ln.get("eigenteil") is True:
            continue
        sid = str(ln["stock_id"])
        need = int(number(ln.get("anzahl")) or 0)
        pool = vorrat.get(sid, {})
        left = need
        taken = []
        # Zukaufteile ohne Länge zuerst, dann Zeilen mit Länge (falls jemand eine angegeben hat)
        for key in sorted(pool, key=lambda k: (k is not None, k or 0)):
            k = min(pool[key], left)
            if k > 0:
                pool[key] -= k
                taken.append((key, k))
                left -= k
        zukauf_bestand.append({"stock_id": sid, "pos": ln.get("pos"), "benennung": ln.get("benennung"),
                               "anzahl": need, "aus_bestand": need - left, "kaufen": left})
        if taken:
            vb = stueck_verbrauch.setdefault(sid, Verbrauch(sid))
            vb.stueck += taken
    verbrauch += list(stueck_verbrauch.values())

    priced = [k["preis"] for k in einkauf if k.get("preis") is not None]
    stands = sorted({str(k["preis_stand"]) for k in einkauf if k.get("preis_stand")})
    ohne = [k["benennung"] for k in einkauf if k.get("preis") is None]
    note = None
    if einkauf:
        note = ("Richtpreise" + (f", Stand {stands[0]}" if len(stands) == 1 else
                                 (f", Stand {stands[0]} bis {stands[-1]}" if stands else "")))
        if ohne:
            note += "; ohne Preis: " + ", ".join(dict.fromkeys(ohne))
    # „Ohne Preis“ der Stückliste nennt nur, was noch gekauft werden muss: ganz aus dem Bestand gedeckte Zukaufteile
    # haben keinen Preis nötig (KevCup, 22.10.2026)
    gedeckt = {str(z["benennung"]) for z in zukauf_bestand if z.get("benennung") and not z.get("kaufen")}
    if gedeckt:
        neu: list[str] = []
        for w in warnings:
            if w.startswith("Ohne Preis: "):
                rest = [n for n in w[len("Ohne Preis: "):].split(", ") if n not in gedeckt]
                if rest:
                    neu.append("Ohne Preis: " + ", ".join(rest))
            else:
                neu.append(w)
        warnings = neu
    if cuts:
        out["verschnitt"] = verschnitt_summe(cuts)
    else:
        out.pop("verschnitt", None)
    out.update({"cuts": cuts, "warnings": warnings, "stueckgut": stueckgut, "zukauf_bestand": zukauf_bestand,
                "einkaufsliste": einkauf,
                "einkauf_summe": round(sum(priced), 2) if priced else None, "einkauf_hinweis": note,
                "bestand_stand": stand if not fehler else None, "fehlt": bool(einkauf)})
    return Planung(out, verbrauch, statistik)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


# ---------------------------------------------------------------------------------------------------------------------
# Gebaut


def gebaut_aenderungen(verbrauch: list[Verbrauch], bestand: dict[str, Any], kennungen: Any,
                       datum: str) -> list[dict[str, Any]]:
    """Änderungen für „Gebaut“: verplante Reste und ganze weg, neue Reste (ab Mindestrest) mit neuen Kennungen dazu,
    Stückgut abziehen. ``kennungen``: ``datei.Kennungen``. Fehlt ein verplanter Rest inzwischen → ValueError."""
    from .datei import BestandError

    posten = bestand.get("posten") or {}
    ops: list[dict[str, Any]] = []
    for v in verbrauch:
        p = posten.get(v.posten) or {}
        by_k = {r.get("kennung"): r for r in p.get("reste") or [] if isinstance(r, dict)}
        for k in v.reste:
            rest = by_k.get(k)
            if rest is None:
                raise BestandError(f"Rest {k} ist nicht mehr im Bestand von {v.posten!r}; Stückliste neu rechnen")
            ops.append({"op": "rest_weg", "posten": v.posten, "rest": rest})
        if v.ganze:
            ops.append({"op": "ganze", "posten": v.posten, "delta": -v.ganze, **v.ganze_mass})
        for neu in v.neue_reste:
            if v.platte:
                rest = {"kennung": kennungen.neu(True), "b": neu["b"], "h": neu["h"], "ort": None, "seit": datum}
            else:
                rest = {"kennung": kennungen.neu(False), "laenge": neu, "ort": None, "seit": datum}
            ops.append({"op": "rest_neu", "posten": v.posten, "rest": rest})
        for laenge, n in v.stueck:
            if n:
                ops.append({"op": "stueck", "posten": v.posten, "laenge": zahl(laenge) if laenge is not None else None,
                            "delta": -int(n)})
    return ops
