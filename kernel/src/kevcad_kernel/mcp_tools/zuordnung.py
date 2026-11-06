"""Zuordnung der bisherigen Werkzeuge (bis V2-1, 95 Stück) zu den Aufrufen ab V2-2.

``uebersetzen(name, argumente)`` macht aus einem alten Aufruf den neuen (Werkzeug und Argumente). Die Tests der
Fachlogik rufen darüber weiter mit den alten Namen, und ``tabelle()`` erzeugt die Übersicht im Skill
(skill/kev-cad/werkzeuge.md; ein Test prüft, dass beide übereinstimmen). ``alter_aufruf(name, argumente)`` ist die Antwort
für Agentensitzungen, die nach dem Update noch alte Namen rufen (Server und stdio-Brücke, V2-8).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .fach import FAECHER, direkt

SICHTBARKEIT = {"show": "zeigen", "hide": "ausblenden", "isolate": "isolieren", "show_all": "alle"}

Uebersetzer = Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]


def _ohne_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _umbenennen(neu: str, namen: dict[str, str], fest: dict[str, Any] | None = None) -> Uebersetzer:
    def f(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return neu, {**(fest or {}), **{namen.get(k, k): v for k, v in a.items()}}
    return f


def _highlight(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    refs = list(a.get("refs") or [])
    if not refs:
        return "view", {"entfernen": "hervorhebungen"}
    return "view", _ohne_none({"hervorheben": refs, "farbe": a.get("color"), "beschriftung": a.get("label"),
                               "dazu": True if a.get("clear") is False else None})


def _section(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not a.get("enabled", True):
        return "view", {"schnitt": "aus"}
    out: dict[str, Any] = {"schnitt_mm": a.get("offset", 0)}
    if a.get("normal") is not None:
        out["schnitt_normale"] = a["normal"]
    else:
        out["schnitt"] = a.get("axis") or "z"
    return "view", out


def _annotate(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return "view", {"anmerkung": _ohne_none({"art": a.get("kind"), "punkte": a.get("points"), "text": a.get("text"),
                                             "id": a.get("id")})}


def _clear_annotations(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ids = a.get("ids")
    return "view", {"entfernen": list(ids) if ids else "anmerkungen"}


def _screenshot(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if a.get("view") or a.get("source") == "offscreen":
        return "ansichten", _ohne_none({"views": [a.get("view") or "iso"], "width": a.get("width"),
                                        "height": a.get("height")})
    return "ansichten", _ohne_none({"kevin": True, "width": a.get("width"), "height": a.get("height"),
                                    "overlays": (not a["hide_overlays"]) if "hide_overlays" in a else None})


def _visibility(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    out: dict[str, Any] = {"sichtbarkeit": SICHTBARKEIT.get(a.get("mode"), a.get("mode"))}
    if a.get("refs"):
        out["teile"] = a["refs"]
    return "view", out


def _variante(a: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rest = {k: v for k, v in a.items() if k != "aktion"}
    return "versionen", {"aktion": f"variante_{a.get('aktion') or 'liste'}", **rest}


KERN: dict[str, Uebersetzer] = {
    "status": lambda a: ("status", a),
    "project_open": _umbenennen("projekt", {"path": "pfad"}),
    "project_new": _umbenennen("projekt", {"path": "pfad", "template": "vorlage"}, {"neu": True}),
    "model_read": lambda a: ("modell", {}),
    "model_write": lambda a: ("modell", a),
    "run": lambda a: ("run", a),
    "execute": lambda a: ("execute", a),
    "parts": lambda a: ("parts", a),
    "bom": lambda a: ("parts", {"stueckliste": True, **a}),
    "view": lambda a: ("view", a),
    "focus": _umbenennen("view", {"refs": "focus"}),
    "visibility": _visibility,
    "highlight": _highlight,
    "section": _section,
    "annotate": _annotate,
    "clear_annotations": _clear_annotations,
    "screenshot": _screenshot,
    "ansichten": lambda a: ("ansichten", a),
    "selection": lambda a: ("measure", {}),
    "measure": lambda a: ("measure", a),
    "pruefen": lambda a: ("pruefen", a),
    "montage_reihenfolge": lambda a: ("pruefen", {"thema": "montage"}),
    "bedingungen": _umbenennen("pruefen", {"part": "teil"}, {"thema": "bedingungen"}),
    "stock_search": _umbenennen("katalog", {"query": "suche"}),
    "stock_get": lambda a: ("katalog", a),
    "material_list": _umbenennen("katalog", {"query": "suche"}, {"art": "material"}),
    "export": lambda a: ("export", a),
    "dokument_export": lambda a: ("export", {"formats": ["pdf"], **a}),
    "variante": _variante,
}

# Kurzform je bisherigem Werkzeug für die Tabelle im Skill (Kernsatz; Fachwerkzeuge entstehen aus fach.py)
KERN_TEXT: dict[str, str] = {
    "status": "status()",
    "project_open": "projekt(pfad)",
    "project_new": "projekt(pfad, neu=true, vorlage)",
    "model_read": "modell()",
    "model_write": "modell(code)",
    "run": "run(params, detail, titel, …)",
    "execute": "execute(code)",
    "parts": "parts(filter)",
    "bom": "parts(stueckliste=true, format)",
    "view": "view(standard, projection, display, fit, explode)",
    "focus": "view(focus=[…])",
    "visibility": "view(sichtbarkeit, teile)",
    "highlight": "view(hervorheben, farbe, beschriftung, dazu)",
    "section": "view(schnitt, schnitt_mm, schnitt_normale)",
    "annotate": "view(anmerkung={art, punkte, text, id})",
    "clear_annotations": "view(entfernen=…)",
    "screenshot": "ansichten(kevin=true) bzw. ansichten(views=[…])",
    "ansichten": "ansichten(…)",
    "selection": "measure() ohne refs",
    "measure": "measure(refs, show)",
    "pruefen": "pruefen(hinweise, bilder, warten)",
    "montage_reihenfolge": "pruefen(thema=\"montage\")",
    "bedingungen": "pruefen(thema=\"bedingungen\", teil, alle)",
    "stock_search": "katalog(suche, art)",
    "stock_get": "katalog(id)",
    "material_list": "katalog(art=\"material\", suche)",
    "export": "export(formats, parts)",
    "dokument_export": "export(formats=[\"pdf\"], bausteine, ziel, drucken)",
    "variante": "versionen(aktion=\"variante_liste|_anlegen|_wechseln|_umbenennen\")",
}


def fach_eintraege() -> dict[str, tuple[str, str]]:
    """Bisheriges Werkzeug → (Fachwerkzeug, Aktion) aus fach.py ('' bei Werkzeugen ohne aktion)."""
    out: dict[str, tuple[str, str]] = {}
    for fach in FAECHER:
        for a in fach.aktionen:
            if a.griff in KERN:
                continue
            out[a.griff] = (fach.name, "" if direkt(fach) else a.name)
    return out


def uebersetzen(name: str, argumente: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Alter Aufruf → (neues Werkzeug, Argumente). Unbekannte Namen bleiben, wie sie sind."""
    args = dict(argumente or {})
    if name in KERN:
        return KERN[name](args)
    fach = fach_eintraege().get(name)
    if fach is None:
        return name, args
    werkzeug, aktion = fach
    return (werkzeug, args) if not aktion else (werkzeug, {"aktion": aktion, **args})


def alte_namen() -> list[str]:
    return sorted(set(KERN) | set(fach_eintraege()))


def _kurzform(alt: str) -> str:
    """Neuer Aufruf als Kurzform ohne Werte, wie in der Tabelle des Skills."""
    if alt in KERN_TEXT:
        return KERN_TEXT[alt]
    werkzeug, aktion = fach_eintraege()[alt]
    return f"{werkzeug}(aktion=\"{aktion}\")" if aktion else f"{werkzeug}(…)"


def _wert(v: Any) -> str:
    """Argument für die Antwort; langer Text (etwa der Quelltext von model_write) bleibt nur angedeutet."""
    text = json.dumps(v, ensure_ascii=False)
    return text if len(text) <= 80 else text[:60] + " …"


def alter_aufruf(name: str, argumente: dict[str, Any] | None = None) -> str | None:
    """Antwort auf den Aufruf eines Werkzeugs, das es seit V2-2 nicht mehr gibt; ``None``, wenn ``name`` keiner dieser
    alten Namen ist. Nennt den neuen Aufruf mit den übergebenen Argumenten, führt ihn aber nicht aus: Der Agent soll
    sehen, was sich geändert hat, und ein Aufruf mit Folgen läuft nicht ohne sein Zutun unter neuem Namen."""
    from . import TOOL_NAMES

    if name in TOOL_NAMES or name not in alte_namen():
        return None
    try:
        neu, args = uebersetzen(name, argumente)
        aufruf = f"{neu}({', '.join(f'{k}={_wert(v)}' for k, v in args.items())})"
    except (TypeError, AttributeError, KeyError):  # Argumente, die auch das alte Werkzeug abgelehnt hätte
        aufruf = _kurzform(name)
    return (f"„{name}“ heißt seit Kev CAD V2 anders. Neuer Aufruf: {aufruf}. Nichts wurde ausgeführt. Kennt deine "
            "Sitzung den neuen Namen noch nicht, den MCP-Server kevcad neu verbinden (/mcp) oder eine neue Sitzung "
            "beginnen; die Übersicht aller Namen steht im Skill kev-cad, Datei werkzeuge.md.")


def tabelle() -> str:
    """Markdown-Tabelle alt → neu für den Skill."""
    zeilen = ["| bis V2-1 | ab V2-2 |", "|---|---|"]
    for alt in alte_namen():
        zeilen.append(f"| `{alt}` | `{_kurzform(alt)}` |")
    return "\n".join(zeilen)


def werkzeuge_md() -> str:
    """Inhalt von skill/kev-cad/werkzeuge.md: Kernsatz mit Parametern, Fachwerkzeuge mit Aktionen (aus den Werkzeugen
    selbst) und die Zuordnung der bisherigen Namen. Erzeugt von kernel/tools/skill_werkzeuge.py."""
    import anyio

    from kevcad_kernel.server import build_server

    from .fach import beschreibung
    from .kern import KERN_NAMEN

    class _Platzhalter:
        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

    mcp = build_server(_Platzhalter())  # type: ignore[arg-type]
    tools = {t.name: t for t in anyio.run(mcp.list_tools)}
    griffe = mcp.kevcad_tools.griffe  # type: ignore[attr-defined]

    def typ(s: dict[str, Any]) -> str:
        if "enum" in s:
            return " | ".join(repr(v) for v in s["enum"])
        if "anyOf" in s:
            return " | ".join(typ(x) for x in s["anyOf"])
        if s.get("type") == "array":
            return f"list[{typ(s.get('items') or {})}]" if s.get("items") else "list"
        return str(s.get("type") or "any")

    zeilen = ["# Werkzeuge von Kev CAD (ab V2-2)", "",
              "Teil des Skills kev-cad. Erzeugt aus den Werkzeugen selbst mit "
              "`kernel/.venv/bin/python kernel/tools/skill_werkzeuge.py`; nicht von Hand ändern (ein Test prüft den "
              "Gleichlauf). Beschreibungen englisch wie im MCP-Server.", "",
              "## Kernsatz", "",
              "In Claude Code mit einem ToolSearch-Aufruf laden: `select:"
              + ",".join(f"mcp__kevcad__{n}" for n in KERN_NAMEN) + "`", ""]
    for name in KERN_NAMEN:
        t = tools[name]
        zeilen += [f"### {name}", "", t.description or "", ""]
        schema = t.input_schema or {}
        pflicht = set(schema.get("required") or [])
        for p, s in (schema.get("properties") or {}).items():
            vorgabe = "" if p in pflicht or "default" not in s else f", Vorgabe {s['default']!r}"
            zeilen.append(f"- `{p}` ({typ(s)}{'' if p in pflicht else ', optional'}{vorgabe}): "
                          f"{s.get('description', '')}")
        zeilen.append("")
    zeilen += ["## Fachwerkzeuge", ""]
    for fach in FAECHER:
        zeilen += [f"### {fach.name}", ""]
        if direkt(fach):
            griff = griffe[fach.aktionen[0].griff]
            zeilen += [fach.kopf, "", f"Parameter: {griff.signatur()} (`?` = optional); Einzelheiten: "
                       f"{fach.name} mit falschen Argumenten oder [ansicht.md](ansicht.md).", ""]
        else:
            zeilen += [beschreibung(fach, griffe), ""]
    zeilen += ["## Zuordnung der bisherigen Werkzeuge (bis V2-1)", "",
               "Die 95 Werkzeuge bis V2-1 sind seit V2-2 Aktionen der Fachwerkzeuge oder Teil des Kernsatzes; alle "
               "Funktionen sind erhalten.", "", tabelle(), ""]
    return "\n".join(zeilen)
