"""Kommandozeile von Kev Scan (eigene uv-Umgebung ``scan/``, eigener Prozess, nie im Kernel).

    kevscan auswerten <ordner|zip> [--aus ORDNER] [--schnell] [--modell large|small] [--geraet mps|cpu]
                                   [--video-bilder N] [--ohne-promptda]
    kevscan gewichte [--modell large|small|alle]      Gewichte von PromptDA vorab laden
    kevscan synth <ziel> [--fotos 10] [--video 30] [--mit-objekt] [--zip]
    kevscan pruefen <ordner|zip>                       nur lesen und zusammenfassen

Fortschritt als JSON-Zeilen auf stdout wie fotomess: ``{"event": "progress", "phase", "fraction", "gesamt",
"text"}``, am Ende ``{"event": "done", "ergebnis": "<aus>/bericht.json", "zusammenfassung": {…}}`` oder
``{"event": "error", "message"}``. Alles andere (Warnungen von torch, ffmpeg) geht auf stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROTO: int | None = None


def melde(ereignis: dict) -> None:
    zeile = json.dumps(ereignis, ensure_ascii=False, default=float) + "\n"
    if _PROTO is None:
        sys.stdout.write(zeile)
        sys.stdout.flush()
    else:
        os.write(_PROTO, zeile.encode("utf-8"))


def _stdout_umleiten() -> None:
    """Echtes stdout nur für die JSON-Zeilen; print() und Bibliotheken schreiben nach stderr."""
    global _PROTO
    _PROTO = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kevscan", description="Kev Scan auswerten (Kev CAD)")
    sub = p.add_subparsers(dest="befehl", required=True)
    a = sub.add_parser("auswerten", help="Scan zu Netz, Kameras und Tiefe")
    a.add_argument("quelle")
    a.add_argument("--aus", help="Zielordner (Vorgabe: <scan>/auswertung bzw. -schnell)")
    a.add_argument("--schnell", action="store_true", help="Small-Modell und weniger Videobilder (Vorschau)")
    a.add_argument("--modell", choices=("large", "small"))
    a.add_argument("--geraet", choices=("mps", "cpu"))
    a.add_argument("--video-bilder", type=int, help="Videobilder zusätzlich zu den Fotos (Vorgabe 40, schnell 12)")
    a.add_argument("--ohne-promptda", action="store_true", help="nur LiDAR-Tiefe (Vergleich, Tests)")
    a.add_argument("--ohne-angleichen", action="store_true", help="PromptDA-Tiefe nicht im Maßstab an LiDAR angleichen")
    g = sub.add_parser("gewichte", help="Gewichte von PromptDA laden")
    g.add_argument("--modell", choices=("large", "small", "alle"), default="alle")
    s = sub.add_parser("synth", help="synthetischen Scan erzeugen (Quader auf dem Boden)")
    s.add_argument("ziel")
    s.add_argument("--fotos", type=int, default=10)
    s.add_argument("--video", type=int, default=30)
    s.add_argument("--mit-objekt", action="store_true")
    s.add_argument("--zip", action="store_true")
    s.add_argument("--lage-rauschen", type=float, default=0.0, help="Lagefehler wie ARKit (mm, Sigma je Achse)")
    r = sub.add_parser("pruefen", help="Scan lesen und zusammenfassen")
    r.add_argument("quelle")
    args = p.parse_args(argv)

    _stdout_umleiten()
    try:
        if args.befehl == "auswerten":
            from kevscan.auswerten import Auswertung

            quelle = Path(args.quelle).expanduser()
            aus = Path(args.aus) if args.aus else (quelle if quelle.is_dir() else quelle.parent) / \
                ("auswertung-schnell" if args.schnell else "auswertung")
            erg = Auswertung(quelle, aus, schnell=args.schnell, modell=args.modell, geraet=args.geraet,
                             video_bilder=args.video_bilder, ohne_promptda=args.ohne_promptda,
                             angleichen=not args.ohne_angleichen, melde=melde).lauf()
            b = json.loads(erg.read_text(encoding="utf-8"))
            melde({"event": "done", "ergebnis": str(erg), "zusammenfassung": {
                k: b.get(k) for k in ("bilder", "huellmass_mm", "voxel_mm", "zeiten", "genauigkeit", "tiefe",
                                      "warnungen")}})
        elif args.befehl == "gewichte":
            from kevscan.tiefe import gewichte

            for m in (("large", "small") if args.modell == "alle" else (args.modell,)):
                melde({"event": "progress", "phase": "gewichte", "fraction": 0, "text": f"PromptDA {m} laden"})
                melde({"event": "file", "kind": f"promptda-{m}", "path": str(gewichte(m))})
            melde({"event": "done"})
        elif args.befehl == "synth":
            from kevscan.synth import erzeuge

            ordner = erzeuge(args.ziel, fotos=args.fotos, video=args.video, mit_objekt=args.mit_objekt,
                             zip_auch=args.zip, lage_rauschen_mm=args.lage_rauschen, melde=lambda i, n: melde({"event": "progress", "phase": "synth",
                                                                          "fraction": round(i / n, 3),
                                                                          "text": f"Bild {i} von {n}"}))
            melde({"event": "done", "ergebnis": str(ordner)})
        elif args.befehl == "pruefen":
            from kevscan import format as fmt

            quelle = Path(args.quelle).expanduser()
            scan = fmt.lesen(fmt.oeffnen(quelle))
            melde({"event": "done", "ordner": str(scan.ordner), "name": scan.name, "fotos": len(scan.fotos),
                   "videobilder": len(scan.video), "objekt": scan.objekt is not None, "warnungen": scan.warnungen,
                   "meta": scan.meta})
    except Exception as exc:  # noqa: BLE001 - jede Ausnahme als Ereignis melden
        import traceback

        traceback.print_exc()
        melde({"event": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
