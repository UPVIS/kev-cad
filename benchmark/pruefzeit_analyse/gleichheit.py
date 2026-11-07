"""Gleichheitsprobe für ``benchmark/pruefzeit.py`` (PLAN-PRUEFUNG-INKREMENTELL.md, A0).

Ein Endstand ist das, was Kevin und der Agent nach ``pruefen(endstand=True)`` sehen: CHECK (Befunde, Schnittkörper,
Montage, Stand, Druck, Gewinde, Kurzfassung der Statik), die volle Statik der Laufzeit (je Szenario S0, S1, Urteile,
Festkörper je Teil), die Bedingungen und die Felder der FEM (Oberflächennetz mit Ausnutzung, Spannung, Verschiebung).

``erfassen`` nimmt ihn aus einer laufenden ``KernelRuntime``, ``normalisieren`` lässt weg, was nicht zum Ergebnis gehört
(Zeiten, Laufnummern, Herkunft aus einem Zwischenspeicher), ``vergleichen`` liefert die Unterschiede zweier Endstände:
JSON-Werte genau (sie sind schon gerundet), Felder der FEM (float32) relativ zum größten Betrag höchstens ``FELD_TOL``.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

FELD_TOL = 1e-6  # float32-Felder der FEM: relativ zum größten Betrag des Felds
MAX_UNTERSCHIEDE = 500

# Schlüssel, die nicht zum Ergebnis gehören: Zeiten, Laufnummern, Zähler und Herkunft (Zwischenspeicher, Gedächtnis)
FLUECHTIG = {
    "ms", "zeiten_ms", "duration_ms", "dauer_ms", "dienst_ms", "rechnen_ms", "prozess_ms", "lu_ms", "amg_ms",
    "pruef_ms", "laufzeit_ms", "statistik", "seq", "type", "run", "pid", "beginn", "zeiten_teile", "speicher_mb",
    "prozesse", "aus_speicher", "aus_gedaechtnis", "aus_zwischenspeicher", "zwischenspeicher", "gesendet",
    "fortschritt", "felder_run", "laeuft", "hintergrund", "statik_hintergrund", "tests", "neu_gerechnet",
    "neu_geprueft", "geprueft_ms", "lauf_ok",
}

# Vorbestehend: Werte, die schon zwischen zwei frischen Prozessen schwanken, also nichts mit Zwischenspeichern zu tun
# haben. Sie stehen im Ergebnis unter ``bekannt`` und lassen die Probe nicht scheitern; ihr Grund steht dabei. Knicken
# (S1) und Rutschen (S0) standen hier bis 07.11.2026 und sind seitdem deterministisch (stabwerk.py, s0.py).
BEKANNT: list[tuple[re.Pattern[str], str]] = []
AMG_RESIDUUM = re.compile(r"\.festkoerper\.teile\[\d+\]\.loeser\.residuum$")
AMG_GRUND = "AMG: Startvektor der Spektralradius-Schätzung von pyamg zufällig (bis A3)"


def normalisieren(x: Any) -> Any:
    """Kopie ohne flüchtige Schlüssel; Tupel als Listen, numpy-Zahlen als Python-Zahlen."""
    if isinstance(x, dict):
        return {str(k): normalisieren(v) for k, v in x.items() if str(k) not in FLUECHTIG}
    if isinstance(x, (list, tuple)):
        return [normalisieren(v) for v in x]
    if isinstance(x, np.ndarray):
        return normalisieren(x.tolist())
    if isinstance(x, np.generic):
        return x.item()
    return x


def erfassen(rt: Any, warten_s: float = 900.0) -> dict[str, Any]:
    """Endstand des letzten Laufs aus der Laufzeit (wartet auf ihn)."""
    check = rt.pruefen(warten_s=warten_s, endstand=True)
    _, payload = rt._pruef.letztes()
    with rt._lock:
        statik = copy.deepcopy(rt._statik_voll)
        bedingungen = copy.deepcopy(getattr(rt, "_constraints", None))
    return {"check": check, "schnittkoerper_sha1": hashlib.sha1(payload or b"").hexdigest(),
            "statik": statik, "bedingungen": bedingungen}


def fem_schluessel(endstand: dict[str, Any]) -> list[str]:
    """Schlüssel der Fälle, deren Feld die Statik zeigt (je Szenario und Teil)."""
    out = []
    for e in ((endstand.get("statik") or {}).get("szenarien") or []):
        for t in ((e.get("festkoerper") or {}).get("teile") or []):
            if t.get("stand") == "done" and t.get("feld"):
                out.append(str(t["feld"]))
    return sorted(set(out))


def _vergleiche(a: Any, b: Any, pfad: str, out: list[dict[str, Any]]) -> None:
    if len(out) >= MAX_UNTERSCHIEDE:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append({"pfad": f"{pfad}.{k}", "a": a.get(k, "<fehlt>"), "b": b.get(k, "<fehlt>")})
                continue
            _vergleiche(a[k], b[k], f"{pfad}.{k}", out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append({"pfad": f"{pfad}[len]", "a": len(a), "b": len(b)})
        for i, (x, y) in enumerate(zip(a, b)):
            _vergleiche(x, y, f"{pfad}[{i}]", out)
        return
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))
                                       and not isinstance(a, bool) and not isinstance(b, bool)):
        out.append({"pfad": pfad, "a": a, "b": b})
        return
    if a != b:
        out.append({"pfad": pfad, "a": a, "b": b})


def felder_vergleichen(schluessel: list[str], ordner_a: Path, ordner_b: Path) -> dict[str, Any]:
    """Felder der FEM-Fälle (``<ordner>/<schluessel>.npz``) beider Endstände: Abweichung je Feld relativ zum größten
    Betrag; ganzzahlige Felder genau."""
    out: dict[str, Any] = {"faelle": len(schluessel), "fehlt": [], "abweichend": [], "max_rel": 0.0}
    for s in schluessel:
        pa, pb = ordner_a / f"{s}.npz", ordner_b / f"{s}.npz"
        if not pa.exists() or not pb.exists():
            out["fehlt"].append({"schluessel": s, "a": pa.exists(), "b": pb.exists()})
            continue
        with np.load(pa) as za, np.load(pb) as zb:
            namen = sorted((set(za.files) | set(zb.files)) - {"info"})
            for n in namen:
                if n not in za.files or n not in zb.files:
                    out["abweichend"].append({"schluessel": s, "feld": n, "grund": "fehlt"})
                    continue
                x, y = np.asarray(za[n]), np.asarray(zb[n])
                if x.shape != y.shape:
                    out["abweichend"].append({"schluessel": s, "feld": n, "grund": f"Form {x.shape} / {y.shape}"})
                    continue
                if not np.issubdtype(x.dtype, np.floating):
                    if not np.array_equal(x, y):
                        out["abweichend"].append({"schluessel": s, "feld": n, "grund": "ungleich"})
                    continue
                gross = float(np.max(np.abs(y))) if y.size else 0.0
                diff = float(np.max(np.abs(x.astype(np.float64) - y.astype(np.float64)))) if y.size else 0.0
                rel = diff / gross if gross > 0 else diff
                out["max_rel"] = max(out["max_rel"], rel)
                if rel > FELD_TOL:
                    out["abweichend"].append({"schluessel": s, "feld": n, "grund": f"relativ {rel:.3g}"})
    return out


def _nachschlagen(x: Any, pfad: str) -> Any:
    """Wert an einem Pfad wie ``.statik.szenarien[1].festkoerper`` (None, wenn es ihn nicht gibt)."""
    for teil in re.findall(r"\.([^.\[]+)|\[(\d+)\]", pfad):
        schl, idx = teil
        try:
            x = x[schl] if schl else x[int(idx)]
        except (KeyError, IndexError, TypeError):
            return None
    return x


def _bekannt(u: dict[str, Any], a: Any) -> str | None:
    for muster, grund in BEKANNT:
        if muster.search(u["pfad"]):
            return grund
    if AMG_RESIDUUM.search(u["pfad"]):
        loeser = _nachschlagen(a, u["pfad"].rsplit(".", 1)[0])
        if isinstance(loeser, dict) and loeser.get("verfahren") == "amg":
            return AMG_GRUND
    return None


def vergleichen(a: dict[str, Any], b: dict[str, Any], fem_a: Path | None = None,
                fem_b: Path | None = None) -> dict[str, Any]:
    """Unterschiede zweier Endstände (``erfassen``); ``fem_a``/``fem_b``: Ordner ``faelle`` der FEM-Zwischenspeicher.
    Vorbestehende Schwankungen (``BEKANNT``) stehen getrennt unter ``bekannt``."""
    alle: list[dict[str, Any]] = []
    na, nb = normalisieren(a), normalisieren(b)
    _vergleiche(na, nb, "", alle)
    unterschiede, bekannt = [], []
    for u in alle:
        grund = _bekannt(u, na)
        if grund:
            bekannt.append({**u, "grund": grund})
        else:
            unterschiede.append(u)
    out: dict[str, Any] = {"unterschiede": unterschiede, "bekannt": bekannt}
    if fem_a is not None and fem_b is not None:
        sa, sb = fem_schluessel(a), fem_schluessel(b)
        out["felder"] = felder_vergleichen(sorted(set(sa) & set(sb)), fem_a, fem_b)
        if sa != sb:
            unterschiede.append({"pfad": "fem.schluessel", "a": sorted(set(sa) - set(sb)), "b": sorted(set(sb) - set(sa))})
    f = out.get("felder") or {}
    out["gleich"] = not unterschiede and not f.get("fehlt") and not f.get("abweichend")
    return out


def kurz(v: dict[str, Any]) -> str:
    """Eine Zeile für die Ausgabe."""
    f = v.get("felder") or {}
    teile = []
    if v.get("unterschiede"):
        teile.append(f"{len(v['unterschiede'])} Unterschiede, erster bei {v['unterschiede'][0]['pfad']}")
    if f.get("fehlt"):
        teile.append(f"{len(f['fehlt'])} Felder fehlen")
    if f.get("abweichend"):
        teile.append(f"{len(f['abweichend'])} Felder abweichend")
    feld = f" (FEM-Felder: {f.get('faelle', 0)}, größte Abweichung relativ {f.get('max_rel', 0.0):.2g})" if f else ""
    bekannt = f", {len(v['bekannt'])} vorbestehende Schwankungen" if v.get("bekannt") else ""
    return ("gleich" if v.get("gleich") else "UNGLEICH: " + "; ".join(teile)) + feld + bekannt
