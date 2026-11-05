"""Interne Ablage der bisherigen Werkzeuge (V2-2).

Bis V2-1 war jede Funktion ein eigenes MCP-Werkzeug (95 Stück). Seit V2-2 stehen die Funktionen hier als „Griffe“:
gleiche Signatur, gleiche Prüfung der Argumente (pydantic, unbekannte Argumente abgelehnt), gleiche Ergebnisse. Der
Agent sieht nur noch den Kernsatz (kern.py) und je Fachbereich ein Werkzeug mit ``aktion`` (fach.py); beide rufen die
Griffe über ``Griffe.aufrufen``. So geht keine Funktion verloren und die alten Tests der Fachlogik bleiben gültig.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver.tools.base import Tool
from mcp_types import CallToolResult, ToolAnnotations
from pydantic import ConfigDict, ValidationError

from . import format as fmt

log = logging.getLogger(__name__)


def ohne_json(res: CallToolResult) -> CallToolResult:
    """Ergebnis ohne den JSON-Textblock, den ``format.result`` für Clients ohne ``structuredContent`` anhängt (V2-2:
    der Agent liest den Text; die Daten bleiben in structuredContent und auf Wunsch mit ``daten=true``)."""
    if res.structured_content is None:
        return res
    roh = json.dumps(res.structured_content, ensure_ascii=False, separators=(",", ":"))
    inhalt = [b for b in res.content if not (getattr(b, "type", None) == "text" and b.text == roh)]
    return CallToolResult(content=inhalt, structured_content=res.structured_content, is_error=res.is_error)


def streng_machen(werkzeug: Tool) -> None:
    """Unbekannte Argumente ablehnen statt still zu verwerfen (KevCup, 22.10.2026: run(timeout_s=400) verschwand ohne
    Meldung). Die MCP-Bibliothek prüft mit einem pydantic-Modell, das zusätzliche Felder ignoriert; hier bekommt es
    ``extra="forbid"`` und das Schema ``additionalProperties: false``."""
    meta = getattr(werkzeug, "fn_metadata", None)
    modell = getattr(meta, "arg_model", None)
    if modell is None or modell.model_config.get("extra") == "forbid":
        return
    streng = type(modell.__name__, (modell,), {"__module__": modell.__module__,
                                                "model_config": ConfigDict(**{**modell.model_config,
                                                                              "extra": "forbid"})})
    meta.arg_model = streng
    werkzeug.parameters = {**werkzeug.parameters, "additionalProperties": False}


def schlank(schema: Any) -> Any:
    """Veröffentlichtes Schema ohne Ballast von pydantic: kein ``title`` je Feld, kein ``default: null``, optionale
    Typen ohne die Alternative ``null`` (der Parameter ist ohnehin optional). Geprüft wird weiter mit dem vollen
    Modell, auch ``null`` bleibt erlaubt."""
    if isinstance(schema, list):
        return [schlank(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "title" and isinstance(v, str):
            continue
        if k == "default" and v is None:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {name: schlank(feld) for name, feld in v.items()}
            continue
        out[k] = schlank(v)
    varianten = out.get("anyOf")
    if isinstance(varianten, list):
        ohne_null = [x for x in varianten if x != {"type": "null"}]
        if len(ohne_null) == 1 and len(ohne_null) < len(varianten) and isinstance(ohne_null[0], dict):
            del out["anyOf"]
            out = {**ohne_null[0], **out}
        elif len(ohne_null) < len(varianten):
            out["anyOf"] = ohne_null
    return out


@dataclass
class Griff:
    name: str
    titel: str
    beschreibung: str
    annotations: ToolAnnotations
    werkzeug: Tool  # Signatur, Schema und Prüfung der Argumente wie bei einem MCP-Werkzeug

    @property
    def lesend(self) -> bool:
        return bool(self.annotations.read_only_hint)

    def parameter(self) -> list[tuple[str, bool, dict[str, Any]]]:
        """(Name, Pflicht?, Schema) je Parameter in der Reihenfolge der Signatur."""
        schema = self.werkzeug.parameters or {}
        pflicht = set(schema.get("required") or [])
        return [(n, n in pflicht, s) for n, s in (schema.get("properties") or {}).items()]

    def signatur(self, umbenennen: dict[str, str] | None = None) -> str:
        """Kurzform der Parameter: ``teil, szenario?, fein?`` (``?`` = optional), mit den Namen nach außen."""
        aussen = {v: k for k, v in (umbenennen or {}).items()}
        return ", ".join(aussen.get(n, n) + ("" if p else "?") for n, p, _ in self.parameter())


class Griffe:
    """Alle bisherigen Werkzeuge nach Namen."""

    def __init__(self) -> None:
        self._griffe: dict[str, Griff] = {}

    def dekorator(self, guard: Callable[[Callable[..., Awaitable[CallToolResult]]],
                                        Callable[..., Awaitable[CallToolResult]]]) -> Callable[..., Any]:
        """Ersatz für den früheren ``tool(name, title, description, annotations)``-Dekorator der Werkzeugdateien:
        legt die Funktion hier ab statt am MCP-Server. ``guard`` macht aus Ausnahmen lesbare Fehlerergebnisse."""

        def tool(name: str, title: str, description: str, annotations: ToolAnnotations) -> Callable[..., Any]:
            def deco(fn: Callable[..., Awaitable[CallToolResult]]) -> Callable[..., Awaitable[CallToolResult]]:
                geschuetzt = guard(fn)
                werkzeug = Tool.from_function(geschuetzt, name=name, title=title, description=description,
                                              annotations=annotations, structured_output=False)
                streng_machen(werkzeug)
                if name in self._griffe:
                    log.warning("Griff %s doppelt registriert", name)
                self._griffe[name] = Griff(name, title, description, annotations, werkzeug)
                return geschuetzt

            return deco

        return tool

    def __contains__(self, name: str) -> bool:
        return name in self._griffe

    def __getitem__(self, name: str) -> Griff:
        return self._griffe[name]

    def namen(self) -> list[str]:
        return list(self._griffe)

    async def aufrufen(self, name: str, argumente: dict[str, Any] | None = None, *, aufruf: str | None = None,
                       umbenennen: dict[str, str] | None = None) -> CallToolResult:
        """Ruft den Griff mit geprüften Argumenten auf (Namen wie in seiner Signatur). Ungültige Argumente kommen als
        isError mit den erlaubten Parametern zurück; ``aufruf`` nennt, wie der Agent ihn erreicht (etwa
        ``druck(aktion="export")``), ``umbenennen`` (außen → innen) die Namen, die er dabei benutzt."""
        griff = self._griffe[name]
        try:
            werte = griff.werkzeug.fn_metadata.validate_arguments(dict(argumente or {}))
        except ValidationError as exc:
            return fmt.error_result(argument_fehler(exc, aufruf or name, griff, umbenennen))
        return await griff.werkzeug.fn(**werte)


def argument_fehler(exc: ValidationError, aufruf: str, griff: Griff, umbenennen: dict[str, str] | None = None) -> str:
    """Kurze deutsche Meldung zu ungültigen Argumenten, mit den erlaubten Parametern."""
    aussen = {v: k for k, v in (umbenennen or {}).items()}
    teile = []
    for err in exc.errors():
        ort = ".".join(aussen.get(str(p), str(p)) for p in err.get("loc") or ()) or "Argumente"
        art = err.get("type", "")
        if art == "extra_forbidden":
            teile.append(f"{ort}: gibt es nicht")
        elif art == "missing":
            teile.append(f"{ort}: fehlt")
        else:
            teile.append(f"{ort}: {err.get('msg')}")
    return (f"Ungültige Eingabe für {aufruf}: {'; '.join(teile)}. Parameter: {griff.signatur(umbenennen) or 'keine'} "
            "(? = optional).")
