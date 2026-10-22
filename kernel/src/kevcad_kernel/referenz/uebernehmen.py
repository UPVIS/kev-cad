"""Gemessene Maße in model.py übernehmen: der Vorgabewert in ``param("name", wert)`` wird ersetzt.

Nur auf Kevins Klick in der App (REF_APPLY), kein MCP-Werkzeug. Geändert wird genau die Zahl im Quelltext (Lage aus
dem AST), alles andere bleibt Zeichen für Zeichen stehen. Werte werden auf 0,1 mm gerundet.
"""

from __future__ import annotations

import ast
from typing import Any


class UebernahmeFehler(ValueError):
    pass


def _zahl_text(wert: float, vorher: str) -> str:
    w = round(float(wert), 1)
    if w == int(w) and "." not in vorher and "e" not in vorher.lower():
        return str(int(w))
    return f"{w:.1f}"


def param_stellen(code: str) -> dict[str, tuple[int, int, int, int, str]]:
    """{Name: (Zeile, Spalte, Endzeile, Endspalte, Text)} des Vorgabewerts je ``param("name", <Zahl>)``."""
    baum = ast.parse(code)
    out: dict[str, tuple[int, int, int, int, str]] = {}
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        f = knoten.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        if name != "param" or not knoten.args or not isinstance(knoten.args[0], ast.Constant):
            continue
        pname = knoten.args[0].value
        wert = knoten.args[1] if len(knoten.args) > 1 else next(
            (k.value for k in knoten.keywords if k.arg == "default"), None)
        if not isinstance(pname, str) or wert is None:
            continue
        ziel = wert
        if isinstance(wert, ast.UnaryOp) and isinstance(wert.op, ast.USub):
            ziel = wert
        if not (isinstance(ziel, ast.Constant) and isinstance(ziel.value, (int, float)) and
                not isinstance(ziel.value, bool)) and not (isinstance(ziel, ast.UnaryOp) and
                                                           isinstance(ziel.operand, ast.Constant)):
            continue
        if pname in out:
            continue  # erster Aufruf zählt (wie param() selbst nur einen Wert kennt)
        text = ast.get_source_segment(code, ziel) or ""
        out[pname] = (ziel.lineno, ziel.col_offset, ziel.end_lineno or ziel.lineno,
                      ziel.end_col_offset or ziel.col_offset, text)
    return out


def uebernehmen(code: str, werte: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Neuer Quelltext und die Änderungen [{name, vorher, nachher, zeile}]. Fehler, wenn ein Maß kein
    ``param("name", Zahl)`` hat."""
    stellen = param_stellen(code)
    fehlt = [k for k in werte if k not in stellen]
    if fehlt:
        raise UebernahmeFehler("In model.py gibt es kein param(\"…\", Zahl) für: " + ", ".join(fehlt))
    zeilen = code.splitlines(keepends=True)
    aenderungen = []
    # von hinten nach vorn ersetzen, damit die Spalten davor stimmen
    for name in sorted(werte, key=lambda k: (stellen[k][0], stellen[k][1]), reverse=True):
        z, s, ez, es, alt = stellen[name]
        if z != ez:
            raise UebernahmeFehler(f"param {name}: Vorgabewert über mehrere Zeilen, bitte von Hand ändern")
        neu = _zahl_text(float(werte[name]), alt)
        zeile = zeilen[z - 1]
        # Spalten im AST sind UTF-8-Byte-Versätze
        b = zeile.encode("utf-8")
        zeilen[z - 1] = (b[:s] + neu.encode("utf-8") + b[es:]).decode("utf-8")
        aenderungen.append({"name": name, "vorher": alt, "nachher": neu, "zeile": z})
    neu_code = "".join(zeilen)
    ast.parse(neu_code)  # muss weiter gültig sein
    return neu_code, sorted(aenderungen, key=lambda a: a["zeile"])
