"""Auswertung der Benchmark-Läufe: Tabelle je Lauf, Matrix je Aufgabe, Verhältnis zur Baseline, Ketten.

    kernel/.venv/bin/python benchmark/auswertung.py ~/Library/Caches/de.upvis.kevcad-bench [--json gesamt.json]

Zeitaufteilung je Lauf: Start der CLI bis zum ersten Ereignis, Zeit bis zum ersten Zeichen (Summe über alle
Modellaufrufe), Erzeugung (Rest der Modellaufrufe), Werkzeuge (Aufruf bis Ergebnis), Rest (Lücken zwischen den Schritten:
vor allem die Wartezeit des Servers vor ``message_start``, dazu Hooks und Ausgabe der CLI).

Vergleiche nur innerhalb derselben Aufgabe: Je Aufgabe der Median je Variante, dann je Variante das geometrische Mittel
der Verhältnisse zur Baseline über die Aufgaben, die beide haben. Ein Mittel über alle Läufe einer Variante hinge sonst
davon ab, welche Aufgaben sie gerechnet hat.

Qualität neben dem Orakel: neue Befunde der Prüfung (Endstand nach dem Agenten minus Stand vor ihm, je Schwere).
Ein später nachgeprüftes Orakel (``orakel_nachgeprueft``, heutiges Orakel auf der gespeicherten model.py) gilt vor dem
ursprünglichen.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


def laeufe(wurzel: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(wurzel.rglob("*.json")):
        if p.name == "zusammenfassung.json" or p.name.endswith(".model.json"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(d, dict) and "variante" in d and "gesamt_s" in d:
            if d.get("ungueltig"):  # Fehler des Benchmarks, nicht der Variante (Grund steht in der JSON)
                continue
            d["_datei"] = str(p)
            out.append(d)
    return out


def orakel(d: dict[str, Any]) -> dict[str, Any]:
    return d.get("orakel_nachgeprueft") or d.get("orakel") or {}


def bestanden(d: dict[str, Any]) -> bool:
    return bool(orakel(d).get("bestanden")) and not d.get("abgebrochen")


# Befunde, die eine Aufgabe zwangsläufig auslöst und die die Musterlösung genauso hat: „gedruckt_geaendert“ meldet, dass
# ein schon gedrucktes Teil des Kugelschiebers (Druckbuch der Vorlage) durch die verlangte Änderung anders wird.
ERWARTET = {"gedruckt_geaendert"}


def neue_befunde(d: dict[str, Any]) -> dict[str, int] | None:
    """Neue Befunde je Schwere (Endstand minus Anfang, ohne erwartete Arten); None, wenn der Lauf das noch nicht
    gemessen hat. Mit Zählern je Art genau, sonst (ältere Läufe) aus den Schweren, erwartete Arten als je ein Befund
    abgezogen."""
    vorher, nachher = d.get("befunde_vorher") or {}, d.get("befunde_nachher") or {}
    if nachher.get("zaehler") is None:
        return None
    out: dict[str, int] = {}
    if "je_art" in nachher:
        vor = vorher.get("je_art") or {}
        for art, n in nachher["je_art"].items():
            schwere, _, name = art.partition(":")
            if name not in ERWARTET and n - vor.get(art, 0) > 0:
                out[schwere] = out.get(schwere, 0) + n - vor.get(art, 0)
        return out
    vor = vorher.get("zaehler") or {}
    neu_erwartet = {a for a in set(nachher.get("arten") or []) - set(vorher.get("arten") or [])
                    if a.partition(":")[2] in ERWARTET}
    for s, n in nachher["zaehler"].items():
        delta = n - vor.get(s, 0)
        if any(a.startswith(s + ":") for a in neu_erwartet):
            delta = 0  # ältere Läufe: erwartete Art neu, Anzahl je Art unbekannt
        if delta > 0:
            out[s] = delta
    return out


def konventionen(d: dict[str, Any]) -> dict[str, Any] | None:
    """Wartbarkeit der gespeicherten model.py, grob und objektiv: Zahl der ``param()`` und ``step()``, Kopfkommentar,
    Anteil der gezeigten Namen mit Gruppe (``Gruppe/Teil``)."""
    import re  # noqa: PLC0415

    datei = Path(str(d.get("_datei", ""))[: -len(".json")] + ".model.py")
    if not datei.is_file():
        return None
    code = datei.read_text(encoding="utf-8")
    namen = re.findall(r"show\([^\n]*?,\s*[\"']([^\"']+)[\"']", code)
    # Kopf (Kevins Regel 1): Anforderungen oder Annahmen als Docstring oder Kommentar vor dem ersten Bauschritt
    kopf_text = re.split(r"^\s*step\(", code, maxsplit=1, flags=re.M)[0]
    kommentare = " ".join(re.findall(r"#[^\n]*|\"\"\"[\s\S]*?\"\"\"", kopf_text)).lower()
    return {"param": len(re.findall(r"\bparam\(", code)), "step": len(re.findall(r"\bstep\(", code)),
            "kopf": any(w in kommentare for w in ("annahme", "anforderung")),
            "gruppen": round(sum("/" in n for n in namen) / len(namen), 2) if namen else None,
            "zeilen": len(code.splitlines())}


def aufteilung(d: dict[str, Any]) -> dict[str, float]:
    gesamt = d.get("gesamt_s") or 0.0
    start = d.get("cli_start_s") or 0.0
    erstes = d.get("bis_erstes_summe_s") or 0.0
    modell = d.get("modell_s") or 0.0
    werkzeug = d.get("werkzeug_s") or 0.0
    return {"cli_start": start, "bis_erstes": erstes, "erzeugung": max(0.0, modell - erstes), "werkzeuge": werkzeug,
            "rest": max(0.0, gesamt - start - modell - werkzeug)}


def zeile(d: dict[str, Any]) -> list[str]:
    t = d.get("tokens") or {}
    a = aufteilung(d)
    o = orakel(d)
    nb = neue_befunde(d)
    return [
        d["variante"], d["aufgabe"], f"{d['gesamt_s']:.0f}",
        "–" if d.get("erste_geometrie_s") is None else f"{d['erste_geometrie_s']:.0f}",
        str(d.get("modellaufrufe")), str(len(d.get("werkzeuge") or [])),
        f"{a['bis_erstes']:.0f}/{a['erzeugung']:.0f}/{a['werkzeuge']:.0f}/{a['rest']:.0f}",
        str(t.get("ausgabe")), str(t.get("denken")), str(t.get("cache_lesen")), str(t.get("cache_schreiben")),
        f"{d.get('run_aufrufe')}/{d.get('run_fehler')}",
        ("OK" if bestanden(d) else "FEHLER") + f" {o.get('anteil', 0):.0%}" + ("*" if d.get("orakel_nachgeprueft") else ""),
        "–" if nb is None else (", ".join(f"{n} {s}" for s, n in nb.items()) or "keine"),
        "–" if d.get("kosten_usd") is None else f"{d['kosten_usd']:.2f}",
    ]


KOPF = ["Variante", "Aufgabe", "gesamt s", "1. Geo s", "Modell-Aufr.", "Werkz.-Aufr.",
        "bis 1. Zeichen/Erzeugung/Werkzeuge/Rest s", "Ausgabe", "Denken", "Cache lesen", "Cache schreiben",
        "run/Fehler", "Orakel", "neue Befunde", "USD"]


def tabelle(kopf: list[str], zeilen: list[list[str]]) -> str:
    out = ["| " + " | ".join(kopf) + " |", "|" + "---|" * len(kopf)]
    out += ["| " + " | ".join(z) + " |" for z in zeilen]
    return "\n".join(out)


GROESSEN = {
    "gesamt_s": lambda d: d["gesamt_s"],
    "erste_geometrie_s": lambda d: d.get("erste_geometrie_s"),
    "modellaufrufe": lambda d: d.get("modellaufrufe"),
    "ausgabe": lambda d: (d.get("tokens") or {}).get("ausgabe"),
    "eingabe_gesamt": lambda d: sum((d.get("tokens") or {}).get(k) or 0
                                    for k in ("eingabe", "cache_lesen", "cache_schreiben")),
    "kosten_usd": lambda d: d.get("kosten_usd"),
}


def gruppiert(liste: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{aufgabe: {variante: [läufe]}}"""
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for d in liste:
        out.setdefault(d["aufgabe"], {}).setdefault(d["variante"], []).append(d)
    return out


def median(werte: list[float | None]) -> float | None:
    xs = [w for w in werte if isinstance(w, (int, float))]
    return statistics.median(xs) if xs else None


def matrix(liste: list[dict[str, Any]], varianten: list[str], groesse: str = "gesamt_s") -> str:
    """Je Aufgabe der Median der Größe je Variante (n Läufe, bestanden)."""
    g = gruppiert(liste)
    zeilen = []
    for aufgabe in sorted(g):
        z = [aufgabe]
        for v in varianten:
            ds = g[aufgabe].get(v) or []
            m = median([GROESSEN[groesse](d) for d in ds])
            if m is None:
                z.append("")
                continue
            ok = sum(bestanden(d) for d in ds)
            z.append(f"{m:.0f}" + (f" ({len(ds)})" if len(ds) > 1 else "") + ("" if ok == len(ds) else f" ✗{len(ds) - ok}"))
        zeilen.append(z)
    return tabelle(["Aufgabe", *varianten], zeilen)


def verhaeltnisse(liste: list[dict[str, Any]], basis: str = "baseline") -> dict[str, dict[str, Any]]:
    """Je Variante: geometrisches Mittel der Verhältnisse (Median der Variante / Median der Baseline) je Größe über die
    Aufgaben, die beide haben; dazu Erfolgsquote und neue Fehler/Warnungen."""
    g = gruppiert(liste)
    out: dict[str, dict[str, Any]] = {}
    varianten = sorted({d["variante"] for d in liste})
    for v in varianten:
        r: dict[str, Any] = {"aufgaben": 0}
        for groesse, f in GROESSEN.items():
            logs = []
            for aufgabe, je in g.items():
                if v not in je or basis not in je:
                    continue
                a, b = median([f(d) for d in je[v]]), median([f(d) for d in je[basis]])
                if a and b:
                    logs.append(math.log(a / b))
            if logs:
                r[groesse] = round(math.exp(sum(logs) / len(logs)), 2)
                r["aufgaben"] = max(r["aufgaben"], len(logs))
        ds = [d for d in liste if d["variante"] == v]
        r["laeufe"] = len(ds)
        r["bestanden"] = f"{sum(bestanden(d) for d in ds)}/{len(ds)}"
        neu = [neue_befunde(d) for d in ds]
        gemessen = [n for n in neu if n is not None]
        r["neue_fehler_warnungen"] = (f"{sum(n.get('fehler', 0) + n.get('warnung', 0) for n in gemessen)} "
                                      f"in {len(gemessen)} gemessenen") if gemessen else "–"
        r["kosten_summe"] = round(sum(d.get("kosten_usd") or 0 for d in ds), 2)
        konv = [k for k in (konventionen(d) for d in ds if d.get("art") == "neu") if k]
        if konv:
            r["neubau_konventionen"] = (f"param {median([k['param'] for k in konv]):.0f}, "
                                        f"step {median([k['step'] for k in konv]):.0f}, "
                                        f"Kopf {sum(k['kopf'] for k in konv)}/{len(konv)}")
        out[v] = r
    return out


def ketten(liste: list[dict[str, Any]]) -> str:
    """Stufe D: dieselbe Änderung fortgesetzt (gleiche Sitzung) gegen frisch (Kopie, neue Sitzung)."""
    zeilen = []
    paare: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
    for d in liste:
        if d.get("kette") and d.get("rolle") in ("fort", "frisch"):
            paare.setdefault((d["kette"], d["variante"]), {}).setdefault(d["rolle"], []).append(d)
    for (k, v), je in sorted(paare.items()):
        for rolle in ("fort", "frisch"):
            for d in je.get(rolle) or []:
                t = d.get("tokens") or {}
                zeilen.append([k, v, rolle, f"{d['gesamt_s']:.0f}", str(d.get("modellaufrufe")),
                               str(t.get("cache_lesen")), str(t.get("ausgabe")),
                               "OK" if bestanden(d) else "FEHLER",
                               "–" if d.get("kosten_usd") is None else f"{d['kosten_usd']:.2f}"])
    if not zeilen:
        return ""
    return tabelle(["Kette", "Variante", "Sitzung", "gesamt s", "Modell-Aufr.", "Cache lesen", "Ausgabe", "Orakel",
                    "USD"], zeilen)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ordner", nargs="+")
    ap.add_argument("--json", default=None)
    ap.add_argument("--varianten", default=None, help="Spalten der Matrix (Vorgabe: alle)")
    ap.add_argument("--seit", default=None,
                    help="nur Läufe aus Ablagen ab diesem Zeitstempel (JJJJMMTT-HHMMSS), etwa ab der ersten Runde, "
                         "in der alle verglichenen Varianten verschränkt liefen")
    args = ap.parse_args()
    alle: list[dict[str, Any]] = []
    for o in args.ordner:
        alle += laeufe(Path(o).expanduser())
    if args.seit:
        alle = [d for d in alle if Path(d["_datei"]).parent.name[:15] >= args.seit]
    if args.varianten:
        alle = [d for d in alle if d["variante"] in args.varianten.split(",")]
    if not alle:
        print("keine Läufe gefunden", file=sys.stderr)
        return 1
    alle.sort(key=lambda d: (d["aufgabe"], d["variante"], d.get("_datei", "")))
    print(tabelle(KOPF, [zeile(d) for d in alle]))
    varianten = (args.varianten.split(",") if args.varianten
                 else sorted({d["variante"] for d in alle}, key=lambda v: (v != "baseline", v)))
    print("\nGesamtzeit, Median je Aufgabe und Variante (Anzahl Läufe, ✗ nicht bestanden):\n")
    print(matrix(alle, varianten))
    print("\nVerhältnis zur Baseline (geometrisches Mittel über gemeinsame Aufgaben, < 1 ist besser):\n")
    v = verhaeltnisse(alle)
    kopf = ["Variante", "Aufgaben", "Läufe", "bestanden", "gesamt", "1. Geo", "Modell-Aufr.", "Ausgabe", "Eingabe",
            "Kosten", "neue Fehler/Warn.", "Neubau: Konventionen", "USD Summe"]
    print(tabelle(kopf, [[name, str(r.get("aufgaben")), str(r["laeufe"]), r["bestanden"], str(r.get("gesamt_s", "")),
                          str(r.get("erste_geometrie_s", "")), str(r.get("modellaufrufe", "")),
                          str(r.get("ausgabe", "")), str(r.get("eingabe_gesamt", "")), str(r.get("kosten_usd", "")),
                          r["neue_fehler_warnungen"], r.get("neubau_konventionen", "–"), str(r["kosten_summe"])]
                         for name, r in sorted(v.items(), key=lambda kv: (kv[0] != "baseline", kv[0]))]))
    k = ketten(alle)
    if k:
        print("\nKetten (Stufe D):\n")
        print(k)
    if args.json:
        Path(args.json).write_text(json.dumps({"laeufe": alle, "verhaeltnisse": v}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
