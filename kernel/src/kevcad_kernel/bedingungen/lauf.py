"""Anbindung an den Lauf (runner.py): Prüfung der Bedingungen direkt nach model.py, im Rechenprozess."""

from __future__ import annotations

from typing import Any

import numpy as np

from .pruefung import pruefen
from .sammlung import Sammlung

ZEITLIMIT_S = 6.0  # für den Bewegungsraum; danach „teilweise geprüft“


def json_tauglich(value: Any) -> Any:
    """numpy-Werte in Python-Werte (der Bericht reist als JSON)."""
    if isinstance(value, dict):
        return {str(k): json_tauglich(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_tauglich(v) for v in value]
    if isinstance(value, np.ndarray):
        return [json_tauglich(v) for v in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if np.isfinite(x) else None
    return value


def pruefe_bedingungen(sammlung: Sammlung, state: dict[str, Any], projekt: str | None) -> dict[str, Any]:
    """Bericht für RUN_DONE (``bedingungen``). Fehler in der Prüfung kippen den Lauf nicht: sie stehen im Bericht."""
    formen: dict[str, Any] = {}
    netze: dict[str, Any] = {}
    boxen: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    schluessel: dict[str, str] = {}
    for name in state.get("shown", []):
        eintrag = (state.get("formen") or {}).get(name)
        if eintrag is None:
            continue
        shape, tess = eintrag
        formen[name] = shape
        schluessel[name] = str(getattr(tess, "key", ""))
        bbox = getattr(tess, "bbox", None) or {}
        if "min" in bbox and "max" in bbox:
            boxen[name] = (np.array(bbox["min"], dtype=float), np.array(bbox["max"], dtype=float))
        g = getattr(tess, "geometry", None)
        if g is not None and len(g.triangles):
            netze[name] = (g.positions, g.triangles, g.normals)
    try:
        return json_tauglich(pruefen(sammlung, formen, netze=netze, schluessel=schluessel, projekt=projekt,
                                     boxen=boxen, zeitlimit_s=ZEITLIMIT_S))
    except Exception as exc:  # noqa: BLE001
        import traceback

        return {"items": [], "teile": [], "bewegungen": [], "befunde": [{
            "art": "bedingung", "pruefung": "intern", "teile": [], "schwere": "hinweis",
            "text": f"Prüfung der Bedingungen fehlgeschlagen: {type(exc).__name__}: {exc}", "soll": "", "ist": "",
            "wert": None, "einheit": "", "ort": None, "loesung": None, "bedingung": None, "unterart": None,
            "zeile": None}], "summe": {"gesamt": 0, "erfuellt": 0, "verletzt": 0, "ungeprueft": 0, "fehler": 0,
                                       "warnungen": 0, "hinweise": 1, "bewegungen": 0},
            "loese_ms": 0.0, "pruef_ms": 0.0, "fehler": traceback.format_exc(limit=6)}
