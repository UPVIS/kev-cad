"""Texte und CSV zum Bestand: Zuschnitt je Quelle, Einkaufsliste, Bestandsübersicht (deutsch, Kevin liest mit)."""

from __future__ import annotations

import csv
import io
from typing import Any

from kevcad_kernel.bom import de_fixed, de_num, eur

from .datei import einstellungen, mm


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


QUELLE = {"rest": "Rest", "bestand": "Bestand", "kaufen": "kaufen"}


def quellen_zeilen(cut: dict[str, Any]) -> list[str]:
    """Je Quelle eine Zeile: „Rest R-0008 (610 mm): 425 + 175, Rest 4 mm (Verschnitt)“."""
    out: list[str] = []
    platte = cut.get("art") == "platte"
    n = {"bestand": 0, "kaufen": 0}
    for q in cut.get("quellen") or []:
        art = q.get("art")
        if art in n:
            n[art] += 1
        if platte:
            size = f"{de_num(q.get('b'))} × {de_num(q.get('h'))} mm"
            name = (f"Rest {q.get('kennung')} ({size})" if art == "rest"
                    else f"{'Bestand' if art == 'bestand' else 'kaufen'} Platte {n.get(art, 0)} ({size})")
            stuecke = ", ".join(f"{de_num(s['b'])} × {de_num(s['h'])}" + (" gedreht" if s.get("gedreht") else "")
                                for s in q.get("stuecke") or [])
            reste = q.get("rest_neu") or []
            rest = ("neue Reste " + ", ".join(f"{de_num(r['b'])} × {de_num(r['h'])}" for r in reste)) if reste \
                else "kein brauchbarer Rest"
            out.append(f"{name}: {stuecke}; {rest}")
        else:
            size = f"{de_num(q.get('laenge'))} mm"
            name = (f"Rest {q.get('kennung')} ({size})" if art == "rest"
                    else f"{'Bestand' if art == 'bestand' else 'kaufen'} Stange {n.get(art, 0)} ({size})")
            stuecke = " + ".join(de_num(x) for x in q.get("stuecke") or [])
            rest = float(q.get("rest_neu") or 0)
            if rest <= 0:
                tail = "aufgebraucht"
            elif q.get("verschnitt"):
                tail = f"Rest {de_num(rest)} mm Verschnitt"
            else:
                tail = f"neuer Rest {de_num(rest)} mm"
            out.append(f"{name}: {stuecke}; {tail}")
    for s in cut.get("zu_gross") or []:
        out.append(f"zu groß für jede Platte: {de_num(s['b'])} × {de_num(s['h'])} mm")
    return out


def zuschnitt_kopf(cut: dict[str, Any]) -> str:
    ab = cut.get("aus_bestand") or {}
    platte = cut.get("art") == "platte"
    parts = []
    if ab.get("reste"):
        parts.append(_plural(int(ab["reste"]), "Rest", "Reste"))
    if ab.get("ganze"):
        parts.append(_plural(int(ab["ganze"]), "ganze Platte" if platte else "ganze Stange",
                             "ganze Platten" if platte else "ganze Stangen") + " aus dem Bestand")
    if cut.get("kaufen"):
        parts.append(_plural(int(cut["kaufen"]), "Platte" if platte else "Stange",
                             "Platten" if platte else "Stangen") + " kaufen")
    neue = cut.get("neue_reste") or []
    if neue:
        if platte:
            parts.append("neue Reste " + ", ".join(f"{de_num(r['b'])} × {de_num(r['h'])}" for r in neue))
        else:
            parts.append("neue Reste " + ", ".join(f"{de_num(x)}" for x in neue) + " mm")
    if platte:
        parts.append(f"Verschnitt {de_num(cut.get('verschnitt_prozent'), 1)} %")
    else:
        weg = sum(float(q.get("rest_neu") or 0) for q in cut.get("quellen") or [] if q.get("verschnitt"))
        parts.append(f"Verschnitt {de_num(weg)} mm")
    return f"{cut.get('benennung')}: " + ", ".join(parts)


def einkauf_zeilen(bom: dict[str, Any]) -> list[str]:
    rows = bom.get("einkaufsliste") or []
    out = []
    for k in rows:
        price = f", {de_fixed(k['preis_je'])} € je Einheit = {eur(k.get('preis'))}" if k.get("preis_je") is not None \
            else ", ohne Preis"
        if k.get("einheit") == "Stück":
            line = f"{k.get('menge')} Stück {k.get('benennung')}{price}"
        else:
            line = f"{k.get('menge')} × {k.get('benennung')} ({k.get('einheit')}){price}"
        if k.get("link"):
            line += f" ({k['link']})"
        if k.get("hinweis"):
            line += f" – {k['hinweis']}"
        out.append(line)
    return out


def einkauf_text(bom: dict[str, Any], titel: str = "") -> str:
    rows = bom.get("einkaufsliste") or []
    head = "Einkaufsliste" + (f" {titel}" if titel else "") + (f" (Lauf {bom['run']})" if bom.get("run") else "")
    if not rows:
        return f"{head}: nichts zu kaufen, alles kommt aus dem Bestand des Projekts."
    out = [f"{head}: {_plural(len(rows), 'Position', 'Positionen')}"]
    out += [f"- {line}" for line in einkauf_zeilen(bom)]
    summe = bom.get("einkauf_summe")
    out.append(f"Summe: {eur(summe)}" + (f" ({bom['einkauf_hinweis']})" if bom.get("einkauf_hinweis") else ""))
    return "\n".join(out)


def einkauf_csv(bom: dict[str, Any], titel: str = "") -> str:
    """Einkaufsliste als CSV (Semikolon, deutsche Zahlen; als Datei mit ``utf-8-sig`` schreiben wie ``bom_csv``)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")

    def money(v: Any) -> str:
        return "" if v is None else f"{float(v):.2f}".replace(".", ",")

    head = ["Einkaufsliste"] + ([titel] if titel else []) + ([f"Lauf {bom['run']}"] if bom.get("run") else [])
    w.writerow(head)
    w.writerow(["Pos", "Lagerteil", "Benennung", "Menge", "Einheit", "€ je Einheit", "€", "Preisstand", "Bezugsquelle",
                "Link", "Hinweis"])
    for i, k in enumerate(bom.get("einkaufsliste") or [], 1):
        w.writerow([i, k.get("id"), k.get("benennung"), k.get("menge"), k.get("einheit"), money(k.get("preis_je")),
                    money(k.get("preis")), k.get("preis_stand") or "", k.get("link_text") or "", k.get("link") or "",
                    k.get("hinweis") or ""])
    w.writerow([])
    w.writerow(["Summe (€)", money(bom.get("einkauf_summe"))])
    if bom.get("einkauf_hinweis"):
        w.writerow(["Hinweis", bom["einkauf_hinweis"]])
    return buf.getvalue()


def rest_text(rest: dict[str, Any]) -> str:
    if "b" in rest:
        size = f"{mm(rest.get('b', 0))} × {mm(rest.get('h', 0))} mm"
    else:
        size = f"{mm(rest.get('laenge', 0))} mm"
    extra = []
    if rest.get("ort"):
        extra.append(str(rest["ort"]))
    if rest.get("seit"):
        extra.append(f"seit {rest['seit']}")
    return f"{rest.get('kennung')} {size}" + (f" ({', '.join(extra)})" if extra else "")


def posten_text(pid: str, posten: dict[str, Any], item: dict[str, Any] | None, bestand: dict[str, Any] | None) -> str:
    name = (item or {}).get("name") or pid
    parts: list[str] = []
    ganze = posten.get("ganze")
    if isinstance(ganze, dict):
        n = int(ganze.get("anzahl") or 0)
        platte = (item or {}).get("art") == "platte" or "b" in ganze
        if platte:
            fmt = (ganze.get("b"), ganze.get("h")) if ganze.get("b") else tuple((item or {}).get("platte") or (None,
                                                                                                             None))
            size = f" à {mm(fmt[0])} × {mm(fmt[1])} mm" if fmt[0] else ""
            parts.append(_plural(n, "ganze Platte", "ganze Platten") + size)
        else:
            L = ganze.get("laenge") or (item or {}).get("stangenlaenge")
            parts.append(_plural(n, "ganze Stange", "ganze Stangen") + (f" à {mm(L)} mm" if L else ""))
    reste = posten.get("reste") or []
    if reste:
        parts.append("Reste: " + ", ".join(rest_text(r) for r in reste))
    stueck = posten.get("stueck") or []
    if stueck:
        parts.append(", ".join((f"{mm(r['laenge'])} mm: " if r.get("laenge") is not None else "")
                               + f"{r.get('anzahl', 0)} Stück" for r in stueck))
    if posten.get("mindestrest_mm") is not None:
        parts.append(f"Mindestrest {mm(posten['mindestrest_mm'])} mm")
    return f"{name} ({pid}): " + ("; ".join(parts) or "leer")


def bestand_text(bestand: dict[str, Any] | None, katalog: Any, *, projekt: str = "", datei: str | None = None,
                 stand: str | None = None, buchungen: list[dict[str, Any]] | None = None,
                 nur: str | None = None) -> str:
    if bestand is None:
        return "Kein Projekt offen: Bestand gibt es je Projekt (bestand.json im Projektordner)."
    posten = bestand.get("posten") or {}
    head = f"Bestand im Projekt „{projekt}“" if projekt else "Bestand"
    head += f" ({datei}, Stand {stand})" if datei and stand else (" (noch keine bestand.json)" if not stand else "")
    out = [head + ":"]
    ids = [nur] if nur else list(posten)
    if not ids or (nur and nur not in posten):
        out.append(f"- {nur}: nichts im Bestand" if nur else "- leer: Kevin hat für dieses Projekt noch nichts eingetragen")
    for pid in ids:
        if pid in posten:
            item = katalog.item(pid) if katalog is not None else None
            out.append("- " + posten_text(pid, posten[pid], item, bestand))
    e = einstellungen(bestand)
    out.append(f"Einstellungen: Mindestrest {mm(e['mindestrest_mm'])} mm, Sägeblatt {mm(e['saegeblatt_mm'])} mm")
    if buchungen:
        out.append("Letzte Buchungen:")
        for b in buchungen[:5]:
            undone = f", rückgängig durch {b['rueckgaengig_durch']}" if b.get("rueckgaengig_durch") else ""
            out.append(f"- {b.get('id')} {b.get('art')} ({b.get('zeit')}, {b.get('von')}{undone}): "
                       f"{b.get('zusammenfassung')}")
    return "\n".join(out)
