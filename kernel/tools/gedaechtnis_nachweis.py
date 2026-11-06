"""Nachweis für das Rechengedächtnis (kevcad_kernel/gedaechtnis.py): Kopien von Projekten mit und ohne Gedächtnis
rechnen und vergleichen, ob dieselben Teile mit denselben Schlüsseln (tess.key) bzw. derselben Geometrie (Volumen,
Fläche, Hüllquader auf 1e-6) herauskommen, dazu Warnungen, Parameter, Stückliste, Bedingungen und Prüfung.

    kernel/.venv/bin/python -u kernel/tools/gedaechtnis_nachweis.py                 # alle Projekte in ~/Documents/Kev CAD
    kernel/.venv/bin/python -u kernel/tools/gedaechtnis_nachweis.py "<Projekt>" …  # nur diese
    ... --ohne-pruefung     die Prüfung nach dem Lauf weglassen (schneller)

Je Projekt rechnen drei Prozesse (zweimal KEVCAD_GEDAECHTNIS=0, einmal =1) mit dem Runner wie im Rechenprozess vier
Läufe: kalt, gleich, nach einer Kommentaränderung, mit einem geänderten Parameter (``--parameter NAME=WERT``, sonst der
erste Parameter des Modells, der nicht 0 ist, 5 % mehr). Verglichen wird jeder Lauf mit Gedächtnis gegen den ersten ohne, der Lauf mit Parameter gegen denselben
Lauf ohne; der zweite Prozess ohne Gedächtnis zeigt das Rauschen von OCCT selbst. Die Prüfung zählt mit ihrem Endstand
(der Bewegungsraum wird fertig gerechnet; was im Zeitlimit eines Laufs fertig wird, hängt an der Uhr) und läuft im
Prozess mit Gedächtnis in Stufen wie im Rechenprozess (V2-1b), ohne Gedächtnis am Stück. Verglichen werden dabei Befunde,
Montagefolge und die Ampeln der Statik. Läuft ein Projekt unter der Inventar-Regel nicht durch, rechnet es zusätzlich
ohne die Regel (Geometrie trotzdem prüfen). Arbeitet nur auf Kopien unter /tmp (messen.kopieren).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from messen import KATALOG, kopieren  # noqa: E402

PROJEKTE = Path.home() / "Documents/Kev CAD"
EPS = 1e-6


def laeufe(projekt: Path, katalog: Path, inventar: bool, pruefen: bool, parameter: str = "") -> dict:
    """Im Unterprozess: vier Läufe mit dem Runner, je Lauf Teile und Kennwerte."""
    import build123d  # noqa: F401

    from kevcad_kernel import gedaechtnis
    from kevcad_kernel.runner import Runner

    gedaechtnis.installieren()
    teile: dict[str, list] = {}

    def emit(h: dict, p: bytes = b"") -> None:
        if h.get("type") == "PART":
            a = h["app"]
            teile[h["name"]] = [h["key"], a["props"]["volume"], a["props"]["area"], a["bbox"]["min"] + a["bbox"]["max"]]

    r = Runner(emit)
    out = []
    params: dict[str, float] = {}
    stufen = gedaechtnis.aktiv()
    for i, art in enumerate(("kalt", "gleich", "kommentar", "parameter"), 1):
        if art == "kommentar":
            m = projekt / "model.py"
            m.write_text(m.read_text(encoding="utf-8") + "\n# Nachweis: Kommentar\n", encoding="utf-8")
        if art == "parameter":
            zahlen = {k: v for k, v in (out[0].get("params") or {}).items() if isinstance(v, (int, float)) and v}
            name, _, wert = parameter.partition("=")
            if name in zahlen:
                params = {name: float(wert)}
            elif zahlen:
                name = sorted(zahlen)[0]
                params = {name: round(float(zahlen[name]) * 1.05, 3)}
            else:
                break
        teile.clear()
        t = time.perf_counter()
        res = r.run({"run": i, "path": str(projekt / "model.py"), "catalog": {"own": str(katalog)},
                     "inventar_regel": inventar, "params": params})
        dauer = time.perf_counter() - t
        bed = res.get("bedingungen") or {}
        bom = res.get("bom") or {}
        e = {"lauf": art, "type": res["type"], "dauer_s": round(dauer, 2), "teile": dict(teile),
             "fehler": (res.get("error") or {}).get("message"), "warnungen": res.get("warnings"),
             "params": res.get("params"), "bom": bom.get("totals"), "bom_zeilen": len(bom.get("lines") or []),
             "bedingungen": bed.get("summe"), "gedaechtnis": (res.get("zeiten_ms") or {}).get("gedaechtnis")}
        if pruefen and res["type"] == "RUN_DONE":
            t = time.perf_counter()
            check, _ = r.pruefe(i, zwischenstand=(lambda _k, _n: None) if stufen else None)
            # Endstand vergleichen: was der Bewegungsraum im Zeitlimit des Laufs schafft, hängt an der Uhr
            while check.get("state") == "teilweise":
                fertig = r.fertig_rechnen(i)
                if fertig is None:
                    break
                check = fertig[0]
            e["pruefung_s"] = round(time.perf_counter() - t, 2)
            e["pruefung"] = {"state": check.get("state"), "zusammenfassung": check.get("zusammenfassung"),
                             "befunde": sorted(f"{b.get('art')}|{b.get('schwere')}|{','.join(b.get('teile') or [])}"
                                               for b in check.get("befunde") or []),
                             "montage": [f"{x.get('name')}|{x.get('richtung_text')}"
                                         for x in (check.get("montage") or {}).get("schritte") or []],
                             "statik": sorted(f"{x.get('name')}|{x.get('ampel')}"
                                              for x in (check.get("statik") or {}).get("szenarien") or [])}
        out.append(e)
    return {"laeufe": out}


def _rel(x: float, y: float) -> float:
    """Abweichung relativ zur Größe (unter 1 absolut): 1e-6 heißt bei einem Volumen von 8e15 mm³ (Stargate) nicht
    1e-6 mm³, das läge unter der Rechengenauigkeit von double."""
    return abs(x - y) / max(1.0, abs(x), abs(y))


def vergleiche(ref: dict, e: dict) -> dict:
    """Lauf ``e`` gegen den Bezug ``ref``: gleiche Namen, Schlüssel, Geometrie (Volumen, Fläche, Hüllquader auf
    ``EPS`` relativ), Kennwerte."""
    a, b = ref["teile"], e["teile"]
    gemeinsam = [n for n in a if n in b]
    schluessel = sum(1 for n in gemeinsam if a[n][0] == b[n][0])
    abw = {n: max([_rel(a[n][1], b[n][1]), _rel(a[n][2], b[n][2])]
                  + [_rel(x, y) for x, y in zip(a[n][3], b[n][3])]) for n in gemeinsam}
    geo_anders = [n for n in gemeinsam if abw[n] > EPS]
    sonst = [k for k in ("type", "fehler", "warnungen", "params", "bom", "bom_zeilen", "bedingungen", "pruefung")
             if ref.get(k) != e.get(k)]
    return {"namen_gleich": set(a) == set(b), "teile": len(b), "schluessel_gleich": schluessel,
            "geometrie_anders": geo_anders, "max_abweichung": max(abw.values(), default=0.0), "sonst_anders": sonst}


def projekt_pruefen(projekt: Path, args) -> list[dict]:
    katalog = Path(args.katalog).expanduser() if args.katalog else KATALOG
    import json as _json

    inventar = True
    try:
        inventar = bool(_json.loads((projekt / "kevcad.json").read_text(encoding="utf-8")).get("inventar_regel", True))
    except (OSError, ValueError):
        pass
    varianten = [inventar]
    berichte = []
    while varianten:
        regel = varianten.pop(0)
        ergebnisse = {}
        for mit in ("ohne2", False, True):
            arbeit, kopie = kopieren(projekt, katalog)
            try:
                env = dict(os.environ, KEVCAD_GEDAECHTNIS="1" if mit is True else "0")
                cmd = [sys.executable, "-u", __file__, "--unterprozess", str(kopie), str(arbeit / "katalog"),
                       "1" if regel else "0", "0" if args.ohne_pruefung else "1", args.parameter]
                p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=args.timeout_s)
                zeile = [z for z in p.stdout.splitlines() if z.startswith("{")]
                if p.returncode != 0 or not zeile:
                    raise SystemExit(f"{projekt.name}: Unterprozess gescheitert ({p.returncode}):\n{p.stderr[-3000:]}")
                ergebnisse[mit] = json.loads(zeile[-1])["laeufe"]
            finally:
                shutil.rmtree(arbeit, ignore_errors=True)
        ref = ergebnisse[False][0]
        zeilen = []
        for e in ergebnisse[True]:
            gegen = next(x for x in ergebnisse[False] if x["lauf"] == e["lauf"]) if e["lauf"] == "parameter" else ref
            v = vergleiche(gegen, e)
            v_eigen = vergleiche(ergebnisse[True][0] if e["lauf"] != "parameter" else gegen, e)
            zeilen.append({"lauf": e["lauf"], "dauer_ohne_s": next(x["dauer_s"] for x in ergebnisse[False]
                                                                   if x["lauf"] == e["lauf"]),
                           "dauer_mit_s": e["dauer_s"], **v,
                           "schluessel_gleich_wie_mit_kalt": v_eigen["schluessel_gleich"],
                           "gedaechtnis": e.get("gedaechtnis"), "type": e["type"], "fehler": e.get("fehler")})
        ohne2 = vergleiche(ref, ergebnisse["ohne2"][0])
        berichte.append({"projekt": projekt.name, "inventar_regel": regel, "zeilen": zeilen,
                         "ohne_gegen_ohne": {k: ohne2[k] for k in ("schluessel_gleich", "teile", "max_abweichung")},
                         "ohne_konsistent": [vergleiche(ref, x)["schluessel_gleich"] for x in ergebnisse[False]]})
        if regel and ref["type"] != "RUN_DONE":
            varianten.append(False)  # Geometrie trotzdem nachweisen
    return berichte


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--unterprozess":
        proj, kat, regel, pruefen, parameter = argv[1:6]
        print(json.dumps(laeufe(Path(proj), Path(kat), regel == "1", pruefen == "1", parameter), ensure_ascii=False))
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("projekte", nargs="*", help="Projektordner (Vorgabe: alle in ~/Documents/Kev CAD)")
    ap.add_argument("--katalog", default=None)
    ap.add_argument("--ohne-pruefung", action="store_true")
    ap.add_argument("--parameter", default="", help="NAME=WERT für den Lauf mit geändertem Parameter")
    ap.add_argument("--timeout-s", type=float, default=3600)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    projekte = [Path(p).expanduser() for p in args.projekte] or sorted(
        p for p in PROJEKTE.iterdir() if (p / "model.py").is_file())
    alle = []
    ok = True
    print("| Projekt | Lauf | Teile | Schlüssel gleich | Geometrie anders (größte Abw.) | sonst anders | Treffer/neu "
          "| ohne s | mit s |")
    print("|---|---|---|---|---|---|---|---|---|")
    for projekt in projekte:
        for b in projekt_pruefen(projekt, args):
            alle.append(b)
            name = b["projekt"] + ("" if b["inventar_regel"] else " (ohne Inventar-Regel)")
            for z in b["zeilen"]:
                gd = z.get("gedaechtnis") or {}
                ok = ok and z["namen_gleich"] and not z["geometrie_anders"] and not z["sonst_anders"]
                print(f"| {name} | {z['lauf']} | {z['teile']} | {z['schluessel_gleich']}/{z['teile']} "
                      f"(wie kalt: {z['schluessel_gleich_wie_mit_kalt']}) | {len(z['geometrie_anders'])} "
                      f"({z['max_abweichung']:.1e}) "
                      f"| {', '.join(z['sonst_anders']) or '–'} | {gd.get('treffer', '–')}/{gd.get('neu', '–')} "
                      f"| {z['dauer_ohne_s']:.2f} | {z['dauer_mit_s']:.2f} |", flush=True)
                if z["geometrie_anders"]:
                    print(f"    Geometrie anders: {z['geometrie_anders'][:8]}")
                if z.get("fehler"):
                    print(f"    Fehler (in beiden gleich, wenn nicht unter sonst anders): {z['fehler'][:160]}")
    print("\nOhne Gedächtnis, zwei getrennte Prozesse (Rauschen von OCCT selbst):")
    for b in alle:
        o = b["ohne_gegen_ohne"]
        print(f"  {b['projekt']}{'' if b['inventar_regel'] else ' (ohne Inventar-Regel)'}: Schlüssel gleich "
              f"{o['schluessel_gleich']}/{o['teile']}, größte Abweichung {o['max_abweichung']:.1e}")
    if args.json:
        Path(args.json).write_text(json.dumps(alle, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nNachweis " + ("bestanden: gleiche Teile und Geometrie, Kennwerte gleich." if ok else "NICHT bestanden."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
