"""Bewegungsraum prüfen: bewegliche Teile über ihren ganzen Weg drehen oder schieben und jede Kollision mit den übrigen
Teilen melden (Behelf, bis Gelenke mit Bereich in Kev CAD das bei jedem Lauf selbst prüfen).

Rechnet das Projekt wie `check_interference.py` auf einer Kopie, bewegt dann die angegebenen Teile schrittweise und prüft
an jedem Schritt das exakte Schnittvolumen gegen alle übrigen Teile. Teile innerhalb der bewegten Gruppe werden nicht
gegeneinander geprüft (sie bewegen sich gemeinsam). Gemeldet werden je Gegenstück die Bereiche (Grad bzw. mm), in denen
es kollidiert, und das größte Schnittvolumen.

Eine Bewegung:
  .venv/bin/python tools/check_motion.py <Projekt> --teile "Rollwagen/Lenkrolle 1" --drehen \
      --punkt 255,-195,128 --richtung 0,0,1 --von 0 --bis 360 --schritte 36

Mehrere Bewegungen auf einmal (das Projekt wird nur einmal gerechnet), JSON-Liste mit
{"name", "teile": [...], "art": "drehen"|"schieben", "punkt": [x,y,z] oder "punkt_von": "<Teil>" (Achse durch
dessen Mitte, z. B. ein Bolzen) oder "achse_von": "<Teil>" (Längsachse eines Bolzens oder Stifts, ersetzt
"richtung"), "richtung": [dx,dy,dz], "von", "bis", "schritte", "ignorieren": [...]}:
  .venv/bin/python tools/check_motion.py <Projekt> --plan bewegungen.json

Ohne --teile und --plan nimmt es `<Projekt>/bewegungen.json`: Dort hält jedes Projekt alle bedienbaren und beweglichen
Teile mit ihrem Weg fest, damit die Prüfung bei jedem Lauf vollständig ist.

Ohne --punkt dreht es um die Mitte des Hüllquaders der bewegten Teile (nur für einen ersten Blick; die echte Achse
angeben). Exit-Code 1, wenn es Kollisionen gibt.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build123d import Axis, Vector  # noqa: E402
from check_interference import load_shapes, overlaps  # noqa: E402


def _vec(text: str | list | None) -> list[float] | None:
    if text is None:
        return None
    if isinstance(text, list):
        return [float(v) for v in text]
    return [float(v) for v in str(text).split(",")]


def _member(name: str, prefixes: list[str]) -> bool:
    return any(name == p or name.startswith(p.rstrip("/") + "/") for p in prefixes)


def run_motion(shapes: dict, spec: dict, threshold: float) -> dict:
    teile = spec["teile"] if isinstance(spec["teile"], list) else [spec["teile"]]
    ignore = spec.get("ignorieren") or []
    moving = {n: s for n, s in shapes.items() if _member(n, teile)}
    if not moving:
        raise SystemExit(f"Keine Teile zu {teile} gefunden")
    static = {n: s for n, s in shapes.items() if n not in moving and not _member(n, ignore)}
    static_boxes = {n: s.bounding_box() for n, s in static.items()}
    art = spec.get("art", "drehen")
    direction = Vector(*(_vec(spec.get("richtung")) or [0, 0, 1])).normalized()
    if spec.get("punkt") is not None:
        pivot = Vector(*_vec(spec["punkt"]))
    elif spec.get("achse_von"):  # Achse = Längsachse eines Bolzens oder Stifts (längste Seite des Hüllquaders)
        if spec["achse_von"] not in shapes:
            raise SystemExit(f"Teil für achse_von nicht gefunden: {spec['achse_von']}")
        bb = shapes[spec["achse_von"]].bounding_box()
        pivot = bb.center()
        size = tuple(bb.size)
        longest = max(range(3), key=lambda i: size[i])
        direction = Vector(*[1.0 if i == longest else 0.0 for i in range(3)])
    elif spec.get("punkt_von"):  # Achse durch die Mitte eines Teils, z. B. Bolzen oder Schraube eines Gelenks
        if spec["punkt_von"] not in shapes:
            raise SystemExit(f"Teil für punkt_von nicht gefunden: {spec['punkt_von']}")
        pivot = shapes[spec["punkt_von"]].bounding_box().center()
    else:
        lo = [min(tuple(s.bounding_box().min)[i] for s in moving.values()) for i in range(3)]
        hi = [max(tuple(s.bounding_box().max)[i] for s in moving.values()) for i in range(3)]
        pivot = Vector(*[(a + b) / 2 for a, b in zip(lo, hi)])
    von, bis = float(spec.get("von", 0)), float(spec.get("bis", 360 if art == "drehen" else 100))
    steps = max(1, int(spec.get("schritte", 36 if art == "drehen" else 20)))
    axis = Axis(pivot, direction)

    t0 = time.perf_counter()
    hits: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for k in range(steps + 1):
        value = von + (bis - von) * k / steps
        for mn, ms in moving.items():
            moved = ms.rotate(axis, value) if art == "drehen" else ms.translate(direction * value)
            mbox = moved.bounding_box()
            for sn, sbox in static_boxes.items():
                if not overlaps(mbox, sbox):
                    continue
                common = moved & static[sn]
                vol = common.volume if common is not None else 0.0
                if vol > threshold:
                    hits.setdefault((mn, sn), []).append((value, vol))
    befunde = []
    step_size = (bis - von) / steps
    # Ruhelage = gezeichnete Lage (Wert 0), sofern sie im Bereich liegt; sonst der Startwert
    rest = 0.0 if min(von, bis) <= 0.0 <= max(von, bis) else von
    if all(abs(von + (bis - von) * k / steps - rest) > 1e-9 for k in range(steps + 1)):
        rest = von
    # Paare, die schon in der Ausgangslage im Gewinde greifen, blockieren eine Bewegung entlang bzw. um die
    # Gewindeachse nicht (herausdrehen), wie die Prüfung des Bewegungsraums bei jedem Lauf
    from kevcad_kernel.pruefung.kollision import im_gewinde

    gewinde = []
    for (mn, sn), values in list(hits.items()):
        if not any(abs(v - rest) < 1e-9 for v, _ in values):
            continue
        g = im_gewinde(moving[mn], static[sn], name_a=mn, name_b=sn)
        if g is not None and g.entlang(list(direction), list(pivot), drehen=art == "drehen"):
            del hits[(mn, sn)]
            gewinde.append({"teile": [mn, sn], "text": g.text})
    for (mn, sn), values in sorted(hits.items()):
        ranges: list[list[float]] = []
        for value, _ in values:
            if ranges and abs(value - ranges[-1][1] - step_size) < 1e-9:
                ranges[-1][1] = value
            else:
                ranges.append([value, value])
        worst = max(values, key=lambda v: v[1])
        befunde.append({"bewegt": mn, "gegen": sn, "bereiche": [[round(a, 2), round(b, 2)] for a, b in ranges],
                        "max_volumen_mm3": round(worst[1], 3), "bei": round(worst[0], 2),
                        "schon_in_ruhe": any(abs(v - rest) < 1e-9 for v, _ in values)})
    blocked = sorted((a, b) for c in befunde for a, b in c["bereiche"])
    frei: list[list[float]] = []
    cursor = von
    for a, b in blocked:
        if a - cursor > step_size / 2:
            frei.append([round(cursor, 2), round(a - step_size, 2)])
        cursor = max(cursor, b + step_size)
    if bis - cursor > -step_size / 2 and cursor <= bis:
        frei.append([round(cursor, 2), round(bis, 2)])
    return {"name": spec.get("name") or ", ".join(teile), "art": art, "frei": frei, "punkt": [round(v, 3) for v in pivot],
            "richtung": [round(v, 4) for v in direction], "von": von, "bis": bis, "schritte": steps,
            "bewegte_teile": len(moving), "dauer_s": round(time.perf_counter() - t0, 2), "kollisionen": befunde,
            "gewinde": gewinde}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--plan", type=Path, help="JSON-Datei mit einer Liste von Bewegungen")
    ap.add_argument("--teile", action="append", help="Teil oder Baugruppe (Präfix), mehrfach möglich")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--drehen", action="store_true")
    mode.add_argument("--schieben", action="store_true")
    ap.add_argument("--punkt", help="Drehpunkt x,y,z in mm (Welt)")
    ap.add_argument("--richtung", default="0,0,1", help="Drehachse bzw. Schieberichtung dx,dy,dz")
    ap.add_argument("--von", type=float, default=0.0)
    ap.add_argument("--bis", type=float)
    ap.add_argument("--schritte", type=int)
    ap.add_argument("--ignorieren", action="append", default=[], help="Teile, die nicht stören (z. B. der Boden)")
    ap.add_argument("--schwelle", type=float, default=0.001, help="kleinstes gemeldetes Schnittvolumen in mm³")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    default_plan = args.project / "bewegungen.json"
    if args.plan:
        specs = json.loads(args.plan.read_text(encoding="utf-8"))
    elif args.teile:
        spec = {"teile": args.teile, "art": "schieben" if args.schieben else "drehen", "punkt": args.punkt,
                "richtung": args.richtung, "von": args.von, "ignorieren": args.ignorieren}
        if args.bis is not None:
            spec["bis"] = args.bis
        if args.schritte is not None:
            spec["schritte"] = args.schritte
        specs = [spec]
    elif default_plan.exists():  # Standard: alle Bewegungen, die das Projekt in bewegungen.json festhält
        specs = json.loads(default_plan.read_text(encoding="utf-8"))
    else:
        ap.error(f"weder --teile noch --plan angegeben und keine {default_plan.name} im Projekt")

    shapes = load_shapes(args.project.resolve())
    results = [run_motion(shapes, s, args.schwelle) for s in specs]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        for r in results:
            unit = "°" if r["art"] == "drehen" else " mm"
            print(f"{r['name']}: {r['art']} {r['von']:g}…{r['bis']:g}{unit} in {r['schritte']} Schritten um "
                  f"{r['punkt']} {r['richtung']}, {len(r['kollisionen'])} Kollisionen ({r['dauer_s']} s)")
            if r["kollisionen"]:
                print("  frei: " + (", ".join(f"{a:g}…{b:g}{unit}" for a, b in r["frei"]) or "nirgends"))
            for c in r["kollisionen"]:
                ber = ", ".join(f"{a:g}…{b:g}{unit}" for a, b in c["bereiche"])
                ruhe = " (schon in Ruhelage)" if c["schon_in_ruhe"] else ""
                print(f"- {c['bewegt']} ↔ {c['gegen']}: bei {ber}, max. {c['max_volumen_mm3']:.3f} mm³ "
                      f"bei {c['bei']:g}{unit}{ruhe}")
            for g in r.get("gewinde") or []:
                print(f"- kein Hindernis, greift im Gewinde und dreht heraus: {g['text']}")
    return 1 if any(r["kollisionen"] for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
