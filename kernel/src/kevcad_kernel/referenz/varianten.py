"""Bauer für fotomess aus model.py: Grundstand und je freiem Maß eine Variante, flächenweise vernetzt.

Läuft als eigener Prozess in der Kernel-Umgebung (``python -m kevcad_kernel.referenz.varianten auftrag.json``), damit
der Rechenprozess der Laufzeit frei bleibt und model.py genau so läuft wie im Viewer (``kevcad``-Hooks, Lager,
Katalog): ``Runner`` aus runner.py rechnet model.py mit überschriebenen ``param``-Werten, die gezeigten Teile kommen
mit ihrer Tessellierung (``tri_face`` je Dreieck = Fläche in der Reihenfolge von ``part.faces()``).

Ausgabe (pickle, nur für fotomess.kevcad): ``basis`` {Teil: [Dreiecke (n, 3, 3) je Fläche]}, ``varianten`` (je freiem
Maß dasselbe mit ``p[k] + schritt``), ``p`` (alle param-Werte des Grundstands), ``parameter`` (die freien Maße),
``farbflaechen`` {Teil: [bool je Fläche]} oder None, ``zwillinge`` [(Q, c)], ``messmodell`` (übrige Angaben).

Messmodell in model.py (optional): eine Funktion ``messmodell()``, die ein Wörterbuch liefert, etwa

```python
def messmodell():
    return dict(
        farbteile=lambda teil, flaeche: teil == "Scarlett/Gehaeuse" and not ist_blende(flaeche),  # oder ["Gehaeuse"]
        zwillinge=["z180"],              # vorn und hinten sehen gleich aus
        maske=dict(farbe_hsv=[[168, 4], 70, 25], ausschluss_hsv=[[6, 24], 50, 45], gehaeuse=True),
        vorgaben={"tiefe": (110, 25)}, grenzen={"tiefe": (80, 130)},
        frei=["tiefe", "hoehe"], bekannt={"breite": 180},
    )
```

``farbteile``: Teile (Namen oder Baugruppen-Präfixe), deren Flächen die Objektfarbe tragen, oder eine Funktion
``(teil, flaeche) -> bool`` je build123d-Fläche. ``zwillinge``: fast gleich aussehende Lagen (``"z180"``, ``"x180"``,
``"y180"`` um die Mitte der Hülle, ``{"achse": "z", "winkel": 180, "punkt": [x, y, z]}`` oder ``(Q, c)``).
``teile`` bzw. ``ohne``: nur diese bzw. ohne diese Teile messen (Kulisse und Skizzen sind immer draußen).
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import math
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

FORMAT = "kevcad-varianten/1"
SCHRITT = 0.5  # mm, wie fotomess.modell.baue_param_netz
FEINHEIT = (0.25, 0.15)  # linear (mm), Winkel (rad): wie fotocad.cad_netz.baue
SCHLUESSEL_DURCHGEREICHT = ("maske", "vorgaben", "grenzen", "frei", "bekannt", "kopfueber", "hoehen", "kb_brennweite",
                            "bilder", "gelenke_hinweis", "roll_sigma_grad", "kanten_gewicht")


def schluessel(code: str, params: dict[str, Any], frei: list[str], schritt: float, extra: Any = None) -> str:
    h = hashlib.sha1()
    h.update(code.encode("utf-8"))
    h.update(json.dumps([sorted((k, v) for k, v in params.items() if isinstance(v, (int, float, str, bool))),
                         list(frei), schritt, FEINHEIT, extra], default=str).encode())
    return h.hexdigest()[:16]


def _teil_passt(name: str, muster: list[str]) -> bool:
    return any(name == m or name.startswith(m.rstrip("/") + "/") for m in muster)


def _flaechen(header: dict[str, Any], payload: bytes) -> list[np.ndarray]:
    from kevcad_kernel.protocol import unpack_part

    app_len = int(header.get("app_len", 0))
    arr = unpack_part(header["app"], payload[:app_len])
    pos = np.asarray(arr["positions"], np.float64)
    tri = np.asarray(arr["triangles"], np.int64)
    tf = np.asarray(arr["tri_face"], np.int64)
    n = int(tf.max()) + 1 if len(tf) else 0
    out = []
    for f in range(n):
        t = tri[tf == f]
        out.append(pos[t] if len(t) else np.zeros((0, 3, 3)))
    return out


def _drehung(achse: str, winkel: float) -> np.ndarray:
    a = {"x": 0, "y": 1, "z": 2}[achse]
    w = math.radians(winkel)
    c, s = round(math.cos(w), 12), round(math.sin(w), 12)
    Q = np.eye(3)
    i, j = [k for k in range(3) if k != a]
    Q[i, i], Q[i, j], Q[j, i], Q[j, j] = c, -s, s, c
    return Q


def zwillinge_aus(angabe: Any, mitte: np.ndarray) -> list[tuple[list[list[float]], list[float]]]:
    """Zwillingslagen aus der Angabe im Messmodell."""
    out = []
    for z in angabe or []:
        if isinstance(z, str):
            text = z.strip().lower()
            if len(text) < 2 or text[0] not in "xyz":
                raise ValueError(f"Zwilling {z!r}: z. B. \"z180\"")
            Q, c = _drehung(text[0], float(text[1:])), mitte
        elif isinstance(z, dict):
            Q = _drehung(str(z.get("achse", "z")).lower(), float(z.get("winkel", 180)))
            c = np.asarray(z.get("punkt", mitte), float)
        else:
            Q, c = np.asarray(z[0], float).reshape(3, 3), np.asarray(z[1], float).reshape(3)
        out.append(([[float(x) for x in r] for r in Q], [float(x) for x in c]))
    return out


def _jsonfaehig(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _jsonfaehig(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonfaehig(x) for x in v]
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    if isinstance(v, np.ndarray):
        return v.tolist()
    return repr(v)


def baue(auftrag: dict[str, Any]) -> dict[str, Any]:
    """Grundstand und Varianten rechnen und als pickle ablegen. Rückgabe: Zusammenfassung (JSON-tauglich)."""
    from kevcad_kernel.runner import Runner

    t0 = time.perf_counter()
    modell = str(auftrag["modell"])
    code = auftrag.get("code") or Path(modell).read_text(encoding="utf-8")
    ueber = {k: float(v) for k, v in (auftrag.get("params") or {}).items()}
    frei = list(auftrag.get("frei") or [])
    schritt = float(auftrag.get("schritt") or SCHRITT)
    teile_msg: list[tuple[dict[str, Any], bytes]] = []

    def emit(header: dict[str, Any], payload: bytes = b"") -> None:
        if header.get("type") == "PART":
            teile_msg.append((header, payload))

    runner = Runner(emit)

    def lauf(nr: int, params: dict[str, Any], schatten: bool) -> tuple[dict[str, Any], dict[str, tuple]]:
        teile_msg.clear()
        msg = {"type": "RUN", "run": nr, "path": modell, "code": code, "params": params, "slow_ms": 0,
               "deviation": FEINHEIT[0], "angular": FEINHEIT[1], "catalog": auftrag.get("catalog") or {},
               "inventar_regel": bool(auftrag.get("inventar_regel", False)), "pruefen": False, "schatten": schatten}
        with contextlib.redirect_stdout(sys.stderr):
            res = runner.run(msg)
        letzte = {}
        for h, p in teile_msg:
            letzte[str(h.get("name"))] = (h, p)
        return res, letzte

    warnungen: list[str] = []

    def grundlauf() -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, tuple], dict[str, Any]]:
        res, teile = lauf(1, ueber, False)
        if res.get("type") != "RUN_DONE":
            e = res.get("error") or {}
            return ({"ok": False, "error": "model.py lief nicht: " + str(e.get("message") or "Fehler"),
                     "line": e.get("line")}, res, teile, {})
        mm: dict[str, Any] = {}
        fn = (runner.ns or {}).get("messmodell")
        if callable(fn):
            try:
                sig = inspect.signature(fn)
                mm = fn(dict(res.get("params") or {})) if len(sig.parameters) >= 1 else fn()
                if not isinstance(mm, dict):
                    warnungen.append("messmodell() liefert kein Wörterbuch; ignoriert")
                    mm = {}
            except Exception as exc:  # noqa: BLE001
                warnungen.append(f"messmodell() fehlgeschlagen: {type(exc).__name__}: {exc}")
                mm = {}
        return None, res, teile, mm

    fehler, res0, teile0, mm = grundlauf()
    if fehler:
        return fehler
    # Angaben aus messmodell(), soweit der Auftrag sie nicht macht: freie Maße, bekannte Maße (neuer Grundlauf)
    if not frei:
        frei = [str(x) for x in mm.get("frei") or []]
    bekannt_mm = {str(k): float(v) for k, v in (mm.get("bekannt") or {}).items()
                  if str(k) not in ueber and str(k) not in frei}
    if bekannt_mm and any(float((res0.get("params") or {}).get(k, v)) != v for k, v in bekannt_mm.items()):
        ueber.update(bekannt_mm)
        warnungen.clear()
        fehler, res0, teile0, mm = grundlauf()
        if fehler:
            return fehler
    else:
        ueber.update(bekannt_mm)
    if not frei:
        return {"ok": False, "error": "Welche Maße sollen gemessen werden? freie_masse angeben (oder in model.py "
                                      "messmodell() mit frei=[…])."}
    p_alle = dict(res0.get("params") or {})
    unbekannt = [k for k in frei if k not in p_alle]
    if unbekannt:
        return {"ok": False, "error": f"Freie Maße ohne param() in model.py: {', '.join(unbekannt)} (vorhanden: "
                                      f"{', '.join(sorted(p_alle)) or 'keine'})"}
    nicht_zahl = [k for k in frei if not isinstance(p_alle[k], (int, float)) or isinstance(p_alle[k], bool)]
    if nicht_zahl:
        return {"ok": False, "error": f"Freie Maße müssen Zahlen sein: {', '.join(nicht_zahl)}"}

    gezeigt = [n for n in res0.get("shown") or [] if n in teile0]
    kulisse = set(res0.get("kulisse") or [])
    auswahl = [n for n in gezeigt if not n.startswith("Skizze/") and n not in kulisse
               and not teile0[n][0].get("app", {}).get("kulisse")]
    if mm.get("teile"):
        auswahl = [n for n in auswahl if _teil_passt(n, [str(x) for x in mm["teile"]])]
    if mm.get("ohne"):
        auswahl = [n for n in auswahl if not _teil_passt(n, [str(x) for x in mm["ohne"]])]
    if not auswahl:
        return {"ok": False, "error": "model.py zeigt keine Teile, die sich messen lassen (Kulisse und Skizzen zählen "
                                      "nicht)."}
    basis = {n: _flaechen(*teile0[n]) for n in auswahl}
    farben = {n: teile0[n][0].get("app", {}).get("color") for n in auswahl}

    varianten = []
    for i, k in enumerate(frei):
        params = dict(ueber)
        params[k] = float(p_alle[k]) + schritt
        res, teile = lauf(2 + i, params, True)
        if res.get("type") != "RUN_DONE":
            e = res.get("error") or {}
            return {"ok": False, "error": f"model.py mit {k} = {params[k]:g} lief nicht: {e.get('message')}",
                    "line": e.get("line")}
        varianten.append({n: _flaechen(*teile[n]) for n in auswahl if n in teile})
        fehlt = [n for n in auswahl if n not in teile]
        if fehlt:
            warnungen.append(f"Mit {k} + {schritt:g} mm fehlen Teile: {', '.join(fehlt[:4])}")

    # Farbteile je Fläche
    farbflaechen = None
    angabe = mm.get("farbteile")
    if angabe:
        from kevcad_kernel.tessellate import deserialize_shape, faces_of

        farbflaechen = {}
        for n in auswahl:
            anzahl = len(basis[n])
            if callable(angabe):
                h, p = teile0[n]
                try:
                    form = deserialize_shape(p[int(h.get("app_len", 0)):])
                    fl = list(faces_of(form))
                    farbflaechen[n] = [bool(angabe(n, f)) for f in fl[:anzahl]] + [False] * max(0, anzahl - len(fl))
                except Exception as exc:  # noqa: BLE001
                    warnungen.append(f"farbteile für {n}: {type(exc).__name__}: {exc}")
                    farbflaechen[n] = [False] * anzahl
            elif isinstance(angabe, dict):
                v = angabe.get(n)
                farbflaechen[n] = [bool(v)] * anzahl
            else:
                farbflaechen[n] = [_teil_passt(n, [str(x) for x in angabe])] * anzahl
        if not any(any(v) for v in farbflaechen.values()):
            warnungen.append("farbteile trifft keine Fläche")

    # Drehpunkt der Zwillinge: Mitte der Farbteile (der Grundkörper ohne Anbauten), sonst Mitte der Hülle
    punkte = [f.reshape(-1, 3) for n, fl in basis.items() for i, f in enumerate(fl)
              if len(f) and (farbflaechen is None or (farbflaechen.get(n) or [False] * (i + 1))[i])]
    if not punkte:
        punkte = [f.reshape(-1, 3) for fl in basis.values() for f in fl if len(f)]
    alle = np.concatenate(punkte)
    mitte = (alle.min(0) + alle.max(0)) / 2
    try:
        zwillinge = zwillinge_aus(mm.get("zwillinge"), mitte)
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        warnungen.append(f"zwillinge: {exc}")
        zwillinge = []

    for i, k in enumerate(frei):
        aendert = False
        for n, fl in basis.items():
            vf = varianten[i].get(n)
            if vf is None or len(vf) != len(fl) or any(a.shape != b.shape for a, b in zip(fl, vf)):
                aendert = True
                break
            if any(len(a) and np.abs(a - b).max() > 1e-6 for a, b in zip(fl, vf)):
                aendert = True
                break
        if not aendert:
            warnungen.append(f"{k} ändert die gezeigte Geometrie nicht (nicht messbar)")

    rest = {k: _jsonfaehig(v) for k, v in mm.items() if k in SCHLUESSEL_DURCHGEREICHT}
    daten = {"format": FORMAT, "p": {k: float(v) for k, v in p_alle.items()
                                      if isinstance(v, (int, float)) and not isinstance(v, bool)},
             "parameter": frei, "schritt": schritt, "basis": basis, "varianten": varianten,
             "farbflaechen": farbflaechen, "zwillinge": zwillinge, "messmodell": rest, "teile": auswahl,
             "farben": farben, "warnungen": warnungen}
    ziel = Path(auftrag["ausgabe"])
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(daten, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(ziel)
    dreiecke = sum(sum(len(f) for f in fl) for fl in basis.values())
    return {"ok": True, "datei": str(ziel), "teile": auswahl, "params": daten["p"], "messmodell": rest,
            "frei": frei, "bekannt": {k: float(v) for k, v in ueber.items() if k not in frei},
            "farbteile": farbflaechen is not None, "zwillinge": len(zwillinge), "warnungen": warnungen,
            "dreiecke": dreiecke, "ms": int((time.perf_counter() - t0) * 1000)}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Aufruf: python -m kevcad_kernel.referenz.varianten auftrag.json", file=sys.stderr)
        return 2
    auftrag = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    proto = os.dup(1)
    os.dup2(2, 1)  # OCCT und print des Modells auf stderr, stdout nur für das Ergebnis
    try:
        erg = baue(auftrag)
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        erg = {"ok": False, "error": f"Interner Fehler: {type(exc).__name__}: {exc}"}
    os.write(proto, (json.dumps(erg, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0 if erg.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
