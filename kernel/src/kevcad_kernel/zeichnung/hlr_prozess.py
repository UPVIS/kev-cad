"""Hilfsprozess für die exakte Verdeckungsrechnung (``python -m kevcad_kernel.zeichnung.hlr_prozess``).

HLRBRep_Algo lässt sich nicht abbrechen und braucht bei achsparallelen Ansichten verschmolzener Zylinder mitunter
Minuten (RECHERCHE-PHASE6.md 3.2). Deshalb rechnet sie hier, in einem eigenen Prozess: Die Laufzeit
(projektion._ExaktProzess) schickt eine Anfrage und beendet den Prozess, wenn das Zeitbudget abläuft; dann gilt das
Netzergebnis.

Rahmen wie zwischen Kernel und App (protocol.encode_frame). Eingang ``HLR`` mit ``id``, ``blick``, ``verdeckt``,
``glatt``, ``toleranz``, ``je_teil``, ``teile`` [{name, len}] und den BRep-Binärformen als Nutzlast; Ausgang
``HLR_RES`` mit ``id``, ``ok``, ``teile`` (Namen), ``arten``, ``ms`` und den Linien als Nutzlast
(projektion.schreibe_linien). Beim Start ``BEREIT``.
"""

from __future__ import annotations

import io
import os
import sys
import time


def main() -> int:
    proto = os.dup(1)
    os.dup2(2, 1)
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape

    from kevcad_kernel.protocol import FrameReader, encode_frame
    from kevcad_kernel.zeichnung.ansichten import Blick
    from kevcad_kernel.zeichnung.projektion import LINIENARTEN, _hlr, schreibe_linien

    def senden(kopf: dict, nutz: bytes = b"") -> None:
        data = encode_frame(kopf, nutz)
        view = memoryview(data)
        while view:
            n = os.write(proto, view)
            view = view[n:]

    senden({"type": "BEREIT", "pid": os.getpid()})
    reader = FrameReader()
    while True:
        data = os.read(0, 1 << 20)
        if not data:
            return 0
        for kopf, nutz in reader.feed(data):
            if kopf.get("type") == "ENDE":
                return 0
            if kopf.get("type") != "HLR":
                continue
            t0 = time.perf_counter()
            try:
                liste = []
                off = 0
                for t in kopf.get("teile") or []:
                    shape = TopoDS_Shape()
                    BinTools.Read_s(shape, io.BytesIO(nutz[off:off + int(t["len"])]))
                    off += int(t["len"])
                    liste.append((str(t["name"]), shape))
                bd = kopf["blick"]
                b = Blick(str(bd["art"]), tuple(bd["richtung"]), tuple(bd["rechts"]), tuple(bd["oben"]))
                teile = _hlr(liste, b, verdeckt=bool(kopf.get("verdeckt", True)), glatt=bool(kopf.get("glatt", True)),
                             toleranz=float(kopf.get("toleranz") or 0.02), exakt=True,
                             je_teil=bool(kopf.get("je_teil")))
                namen, daten = schreibe_linien(teile)
                senden({"type": "HLR_RES", "id": kopf.get("id"), "ok": True, "teile": namen,
                        "arten": list(LINIENARTEN), "ms": round((time.perf_counter() - t0) * 1000, 1)}, daten)
            except Exception as exc:  # noqa: BLE001
                senden({"type": "HLR_RES", "id": kopf.get("id"), "ok": False, "fehler": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    sys.exit(main())
