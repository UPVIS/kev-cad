"""Experiment Pipeline (PLAN-PIPELINE.md, K2/K3): model.py gezielt lesen und ändern, ohne die ganze Datei.

- ``gliederung(code)``: Parameter mit Wert, Zeile und Kommentar, Bauschritte und gezeigte Teile mit Zeile. Für große
  Modelle (Kugelschieber: 78.000 Zeichen) liest der Agent danach nur die Zeilen, die er braucht.
- ``setze_parameter(code, werte)``: Vorgabewerte von ``param("name", wert)`` ersetzen, nur an diesen Stellen (Zahl
  statt Ausdruck); Ausdrücke als Vorgabe bleiben unberührt und werden gemeldet.
"""

from __future__ import annotations

import ast
import io
import tokenize
from typing import Any


def _kommentare(code: str) -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string.lstrip("#").strip()
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def _name(call: ast.Call) -> str | None:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _text(node: ast.AST, code: str) -> str:
    return ast.get_source_segment(code, node) or ""


def gliederung(code: str) -> dict[str, Any]:
    baum = ast.parse(code)
    kommentare = _kommentare(code)
    params: list[dict[str, Any]] = []
    schritte: list[dict[str, Any]] = []
    teile: list[dict[str, Any]] = []
    for node in ast.walk(baum):
        if not isinstance(node, ast.Call):
            continue
        n = _name(node)
        args = node.args
        if n == "param" and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            params.append({"name": args[0].value, "wert": _text(args[1], code) if len(args) > 1 else None,
                           "zeile": node.lineno, "kommentar": kommentare.get(node.lineno)})
        elif n == "step" and args and isinstance(args[0], (ast.Constant, ast.JoinedStr)):
            schritte.append({"text": _text(args[0], code).strip("\"'f"), "zeile": node.lineno})
        elif n == "show" and len(args) >= 2:
            teile.append({"name": _text(args[1], code).strip("\"'f"), "zeile": node.lineno})
    for liste in (params, schritte, teile):
        liste.sort(key=lambda e: e["zeile"])
    return {"zeilen": code.count("\n") + 1, "zeichen": len(code), "params": params, "schritte": schritte,
            "teile": teile}


def gliederung_text(g: dict[str, Any], pfad: str) -> str:
    z = [f"model.py ({pfad}): {g['zeilen']} Zeilen, {g['zeichen']} Zeichen"]
    if g["params"]:
        z.append(f"Parameter ({len(g['params'])}):")
        for p in g["params"]:
            z.append(f"  Z{p['zeile']} {p['name']} = {p['wert']}" + (f"  # {p['kommentar']}" if p["kommentar"] else ""))
    if g["schritte"]:
        z.append("Schritte: " + "; ".join(f"Z{s['zeile']} {s['text']}" for s in g["schritte"]))
    if g["teile"]:
        z.append(f"show() ({len(g['teile'])}): " + "; ".join(f"Z{t['zeile']} {t['name']}" for t in g["teile"][:80])
                 + (" …" if len(g["teile"]) > 80 else ""))
    z.append("Einzelne Zeilen danach mit dem Dateiwerkzeug lesen (offset und limit), Maße mit modell(setze=…) ändern.")
    return "\n".join(z)


def setze_parameter(code: str, werte: dict[str, float]) -> tuple[str, list[str], list[str]]:
    """Neuer Code, Meldungen je geändertem Parameter, Fehler (unbekannt oder Ausdruck als Vorgabe)."""
    baum = ast.parse(code)
    zeilen = code.splitlines(keepends=True)
    start = [0]
    for zeile in zeilen:
        start.append(start[-1] + len(zeile))
    stellen: dict[str, list[ast.AST]] = {}
    for node in ast.walk(baum):
        if (isinstance(node, ast.Call) and _name(node) == "param" and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant) and node.args[0].value in werte):
            stellen.setdefault(node.args[0].value, []).append(node.args[1])
    meldungen: list[str] = []
    fehler: list[str] = []
    ersatz: list[tuple[int, int, str]] = []
    for name, wert in werte.items():
        orte = stellen.get(name)
        if not orte:
            fehler.append(f"{name}: kein param(\"{name}\", …) in model.py")
            continue
        for alt in orte:
            if not (isinstance(alt, ast.Constant) and isinstance(alt.value, (int, float))) and not (
                    isinstance(alt, ast.UnaryOp) and isinstance(alt.operand, ast.Constant)):
                fehler.append(f"{name}: Vorgabe ist ein Ausdruck ({_text(alt, code)}), bitte von Hand ändern")
                continue
            neu = repr(int(wert)) if float(wert).is_integer() else repr(float(wert))
            a = start[alt.lineno - 1] + len(code[start[alt.lineno - 1]:].encode()[:alt.col_offset].decode(errors="ignore"))
            b = start[alt.end_lineno - 1] + len(
                code[start[alt.end_lineno - 1]:].encode()[:alt.end_col_offset].decode(errors="ignore"))
            ersatz.append((a, b, neu))
            meldungen.append(f"{name}: {_text(alt, code)} → {neu} (Zeile {alt.lineno})")
    for a, b, neu in sorted(ersatz, reverse=True):
        code = code[:a] + neu + code[b:]
    return code, meldungen, fehler
