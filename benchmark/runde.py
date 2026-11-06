"""Verschränkte Runde: je Aufgabe alle Varianten nacheinander, dann die nächste Aufgabe (A B C, A B C …).

Die Wartezeit der Modelle schwankt mit der Last bei Anthropic (Opus am 06.11.2026 abends 2 bis 24 s bis zum ersten
Zeichen): In Blöcken gerechnet entschiede die Tageszeit mit. Jeder Lauf ist ein eigener Aufruf von lauf.py (eigener
Kernel-Stand je Variante); der Budgetwächter dort gilt weiter.

    kernel/.venv/bin/python -u benchmark/runde.py --aufgaben t7,t1 --varianten baseline,schlank,schlank-k
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aufgaben", required=True)
    ap.add_argument("--varianten", required=True)
    ap.add_argument("--app", default=str(HIER.parent / "build" / "Kev CAD Test bench.app"))
    ap.add_argument("--budget", default="1.01")
    args = ap.parse_args()
    varianten = [v.strip() for v in args.varianten.split(",") if v.strip()]
    for i, aufgabe in enumerate([a.strip() for a in args.aufgaben.split(",") if a.strip()]):
        # Reihenfolge je Aufgabe weiterdrehen, damit keine Variante immer zuerst oder zuletzt läuft
        for variante in varianten[i % len(varianten):] + varianten[:i % len(varianten)]:
            p = subprocess.run([sys.executable, "-u", str(HIER / "lauf.py"), "--variante", variante, "--aufgaben", aufgabe,
                                "--app", args.app, "--budget", args.budget], capture_output=True, text=True)
            for zeile in (p.stdout + p.stderr).splitlines():
                if any(s in zeile for s in ("läuft", "s, erste", "Budget", "rror", "Traceback", "Wochenlimit")):
                    print(zeile, flush=True)
                if "Budget erreicht" in zeile:
                    return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
