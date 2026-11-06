"""``kevcad-feedback``: endet genau dann, wenn Kevin mit dem Sprechen fertig ist (V2-6, PROTOCOL.md).

Ein Agent ist nur aktiv, solange er eine Runde läuft. Er startet diesen Befehl als Hintergrund-Shell und beendet seinen
Zug; endet der Befehl, weckt das den Agenten, und ``feedback()`` holt das Paket ab. Der Befehl holt selbst nichts ab und
braucht nur die Standardbibliothek. Neustarts von Kev CAD übersteht er.

Ausgang 0: Feedback ist da. 2: ``--warten-s`` abgelaufen.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PORT = 47823
ANFRAGE_S = 300.0  # eine Anfrage, gleich dem Höchstwert des Kernels
ERNEUT_S = 2.0  # so lange wartet er, wenn Kev CAD gerade nicht läuft


def warten(port: int, warten_s: float | None, *, erneut_s: float = ERNEUT_S) -> dict | None:
    """Gibt die Antwort des Kernels zurück, sobald ein Paket offen ist, sonst None nach ``warten_s``."""
    ende = None if warten_s is None else time.monotonic() + warten_s
    while True:
        rest = ANFRAGE_S if ende is None else min(ANFRAGE_S, ende - time.monotonic())
        if rest <= 0:
            return None
        url = f"http://127.0.0.1:{port}/feedback/warten?warten_s={rest:.1f}"
        try:
            with urllib.request.urlopen(url, timeout=rest + 10) as antwort:  # noqa: S310 - nur localhost
                daten = json.load(antwort)
            if daten.get("da"):
                return daten
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(erneut_s)  # Kev CAD läuft nicht oder startet gerade neu


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kevcad-feedback", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("KEVCAD_PORT") or DEFAULT_PORT))
    parser.add_argument("--warten-s", type=float, default=None, help="höchstens so lange warten (Vorgabe: unbegrenzt)")
    args = parser.parse_args(argv)
    try:
        daten = warten(args.port, args.warten_s)
    except KeyboardInterrupt:
        return 130
    if daten is None:
        print(f"Kein Feedback nach {args.warten_s:g} s.")
        return 2
    print(f"Kevin ist fertig: {daten.get('name')}, {daten.get('saetze')} Sätze, {daten.get('striche')} Striche. "
          "feedback() holt es ab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
