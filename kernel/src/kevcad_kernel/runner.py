"""Führt model.py im Rechenprozess aus und füllt die API ``kevcad`` (show, step, param) mit Leben.

Läuft nur im Rechenprozess (``kevcad_kernel.worker``). Jedes ``show()`` tesselliert sofort und schickt das Teil über
``emit`` an den Elternprozess, noch während das Skript läuft. Ergebnis eines Laufs ist ein ``RUN_DONE`` oder
``RUN_FAILED`` (siehe worker.py); die Teile reisen vorher einzeln als ``PART``.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import difflib
import io
import linecache
import os
import sys
import sysconfig
import time
import traceback
import warnings
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build123d import BuildLine, BuildPart, BuildSketch, Color, Compound, Shape

import kevcad
from kevcad_kernel.bom import LagerRegister, Piece, ShownPart, build_bom
from kevcad_kernel.catalog import Catalog, number
from kevcad_kernel.protocol import pack_part
from kevcad_kernel.tessellate import (
    DEFAULT_ANGULAR,
    DEFAULT_DEVIATION,
    edges_of,
    faces_of,
    serialize_shape,
    tessellate_shape,
    vertices_of,
)

Emit = Callable[[dict[str, Any], bytes], None]

SKETCH_PREFIX = "Skizze/"
SKETCH_COLOR = (0.35, 0.66, 0.90, 0.5)
MAX_STDOUT = 20_000
MAX_WARNINGS = 30

# Gedämpfte Farben für Teile ohne Farbangabe; Auswahl über den Namen, damit ein Teil seine Farbe behält
PALETTE: tuple[tuple[float, float, float, float], ...] = (
    (0.72, 0.75, 0.79, 1.0),  # Stahlgrau
    (0.56, 0.66, 0.77, 1.0),  # Graublau
    (0.79, 0.70, 0.56, 1.0),  # Sand
    (0.62, 0.72, 0.60, 1.0),  # Salbei
    (0.77, 0.63, 0.63, 1.0),  # Altrosa
    (0.66, 0.64, 0.79, 1.0),  # Lavendel
    (0.79, 0.75, 0.56, 1.0),  # Ocker
    (0.56, 0.77, 0.75, 1.0),  # Petrol
)

# Deutsche und britische Namen auf die Namen von build123d (bd_materials) abbilden
MATERIAL_ALIASES = {
    "aluminium": "aluminum", "alu": "aluminum", "alublech": "aluminum",
    "stahl": "mild_steel", "baustahl": "mild_steel", "steel": "mild_steel", "s235": "mildsteel_ga36_hot_rolled",
    "edelstahl": "stainless", "v2a": "stainless_g304_annealed", "v4a": "stainless_g316l_annealed",
    "stainless_steel": "stainless", "werkzeugstahl": "tool_steel", "federstahl": "spring_steel",
    "messing": "brass", "kupfer": "copper", "titan": "titanium", "silber": "silver",
    "holz": "hardwood", "hartholz": "hardwood", "weichholz": "softwood", "eiche": "oak", "buche": "beech",
    "birke": "birch", "ahorn": "maple", "nussbaum": "walnut", "kirsche": "american_cherry", "esche": "ash",
    "kiefer": "pine", "fichte": "spruce", "holzwerkstoff": "engineered_wood",
    "glas": "soda_lime", "acrylglas": "pmma", "plexiglas": "pmma", "acryl": "pmma",
    "gummi": "rubber", "filz": "felt", "leder": "leather", "pappe": "cardboard", "karton": "cardboard",
    "papier": "paper", "keramik": "ceramic", "kohlefaser": "cfrp", "carbon": "cfrp",
    "polycarbonat": "pc", "polyethylen": "pe", "polypropylen": "pp", "nylon": "nylon", "pa": "nylon",
    "polyamid": "nylon", "pa6": "nylon_pa6", "pa12": "nylon_pa12", "teflon": "ptfe", "pla+": "pla",
    "hdpe": "pe_hdpe", "glasfaser": "fr4", "magnesiumlegierung": "magnesium",
}


# ---------------------------------------------------------------------------------------------------------------------
# Farben und Materialien
# ---------------------------------------------------------------------------------------------------------------------


def parse_color(value: Any) -> tuple[float, float, float, float]:
    """"#RRGGBB", "#RRGGBBAA", Farbname ("red"), Tupel 0…1 oder 0…255, build123d-Color → RGBA 0…1."""
    if isinstance(value, Color):
        return tuple(float(c) for c in value)  # type: ignore[return-value]
    if isinstance(value, str):
        try:
            return tuple(float(c) for c in Color(value.strip()))  # type: ignore[return-value]
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Farbe {value!r} unbekannt (erlaubt: \"#RRGGBB\", Farbname wie \"red\", Tupel)") from exc
    if isinstance(value, (tuple, list)) and len(value) in (3, 4) and all(isinstance(c, (int, float)) for c in value):
        vals = [float(c) for c in value]
        if max(vals[:3]) > 1.0:
            vals[:3] = [c / 255.0 for c in vals[:3]]
            if len(vals) == 4 and vals[3] > 1.0:
                vals[3] /= 255.0
        if len(vals) == 3:
            vals.append(1.0)
        if not all(0.0 <= c <= 1.0 for c in vals):
            raise ValueError(f"Farbe {value!r}: Werte müssen zwischen 0 und 1 (oder 0 und 255) liegen")
        return tuple(vals)  # type: ignore[return-value]
    raise ValueError(f"Farbe {value!r} unbekannt (erlaubt: \"#RRGGBB\", Farbname wie \"red\", Tupel)")


def palette_color(name: str) -> tuple[float, float, float, float]:
    return PALETTE[zlib.crc32(name.encode("utf-8")) % len(PALETTE)]


def resolve_material(value: Any) -> tuple[Any, str | None]:
    """Materialname oder FinishedMaterial → (FinishedMaterial, Name). Unbekannt → ValueError mit Vorschlag."""
    from bd_materials import FinishedMaterial, canonical_name, material_names, resolve

    if value is None:
        return None, None
    if isinstance(value, FinishedMaterial):
        try:
            return value, canonical_name(value)
        except Exception:  # noqa: BLE001
            return value, getattr(value.material, "name", "material")
    if not isinstance(value, str):
        raise ValueError(f"Material {value!r}: bitte als Name angeben, z. B. \"aluminium\"")
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    key = MATERIAL_ALIASES.get(key, key)
    try:
        return resolve(key), value.strip()
    except Exception as exc:  # noqa: BLE001
        names = list(material_names()) + list(MATERIAL_ALIASES)
        close = difflib.get_close_matches(key, names, n=3, cutoff=0.6)
        tip = f" Meinten Sie {', '.join(repr(c) for c in close)}?" if close else ""
        raise ValueError(f"Material {value!r} unbekannt.{tip}") from exc


def material_density(fm: Any) -> float | None:
    """Dichte in kg/m³."""
    try:
        d = fm.material.density
        return float(d) if d is not None else None
    except Exception:  # noqa: BLE001
        return None


@dataclass
class MatInfo:
    """Aufgelöstes Material eines gezeigten Teils: aus dem Katalog von Kev CAD oder aus build123d."""

    display: str  # Name für PART_UPSERT.material
    density: float | None = None  # kg/m³
    color: tuple[float, float, float, float] | None = None  # sRGB
    entry: dict[str, Any] | None = None  # Katalogmaterial
    fm: Any = None  # FinishedMaterial aus build123d


def catalog_matinfo(entry: dict[str, Any], display: str | None = None) -> MatInfo:
    from kevcad_kernel.catalog import number

    dichte = number(entry.get("dichte"))
    color = None
    try:
        color = parse_color(entry.get("farbe"))
    except ValueError:
        color = None
    return MatInfo(display=display or entry.get("name") or entry["id"],
                   density=dichte * 1000.0 if dichte is not None else None, color=color, entry=entry)


def _strict_entry(value: str, catalog: Catalog | None) -> tuple[dict[str, Any], str]:
    entry = kevcad.lager.released_material(value, cat=catalog)
    display = entry.get("name") if value.strip() == entry["id"] else value.strip()
    return entry, display


def material_info(value: Any, catalog: Catalog | None, strict: bool = False) -> MatInfo | None:
    """Material aus show() oder vom Teil: zuerst der Katalog (id, Alias, Name), dann build123d (und die deutschen
    Namen in MATERIAL_ALIASES). Unbekannt → ValueError mit Vorschlägen aus beiden.

    ``strict`` (Inventar-Regel): nur freigegebene Katalogmaterialien, sonst ``kevcad.lager.MaterialError``."""
    if value is None:
        return None
    if strict:
        if not isinstance(value, str):
            raise kevcad.lager.MaterialError(f"Material {value!r}: Inventar-Regel – nur Materialien aus dem Katalog "
                                             "(id oder Alias als Text, siehe material_list)")
        return catalog_matinfo(*_strict_entry(value, catalog))
    if isinstance(value, str) and catalog is not None:
        entry = catalog.find_material(value)
        if entry is not None:
            display = entry.get("name") if value.strip() == entry["id"] else value.strip()
            return catalog_matinfo(entry, display)
    try:
        fm, name = resolve_material(value)
    except ValueError as exc:
        tips = catalog.material_suggestions(str(value)) if catalog is not None and isinstance(value, str) else []
        if tips:
            raise ValueError(f"Material {value!r} unbekannt. Im Katalog: {', '.join(repr(t) for t in tips)}?") from exc
        raise
    color = None
    if getattr(fm, "pbr", None) is not None:
        try:
            mc = fm.pbr.interpolate_color()
            color = tuple(float(x) for x in mc) if mc else None
        except Exception:  # noqa: BLE001
            color = None
    return MatInfo(display=name or "material", density=material_density(fm), color=color, fm=fm)


# ---------------------------------------------------------------------------------------------------------------------
# show(): Objekte in Teile zerlegen
# ---------------------------------------------------------------------------------------------------------------------


def _as_shape(obj: Any) -> Any:
    """Builder → Ergebnis, Listen von Formen → Compound, Formen unverändert."""
    if isinstance(obj, BuildPart):
        return obj.part
    if isinstance(obj, BuildSketch):
        return obj.sketch
    if isinstance(obj, BuildLine):
        return obj.line
    return obj


def _is_empty(shape: Shape) -> bool:
    try:
        return shape.wrapped is None or (not faces_of(shape) and not edges_of(shape) and not vertices_of(shape))
    except Exception:  # noqa: BLE001
        return True


def _labeled_children(obj: Any) -> list[Any] | None:
    """Kinder eines Compound (oder Elemente einer Liste), wenn mindestens eines einen Namen (label) hat."""
    if isinstance(obj, (list, tuple)):
        kids = [_as_shape(o) for o in obj]
    elif isinstance(obj, Compound):
        kids = list(obj.children)
    else:
        return None
    if kids and all(isinstance(k, Shape) for k in kids) and any(getattr(k, "label", "") for k in kids):
        return kids
    return None


def split_parts(obj: Any, name: str) -> list[tuple[str, Shape, bool]]:
    """Zerlegt das Objekt aus show() in (Name, Form, ist_Unterteil). Benannte Kinder werden rekursiv zu
    "Name/Kindname"; doppelte Kindnamen bekommen " 2", " 3" angehängt."""
    obj = _as_shape(obj)
    kids = _labeled_children(obj)
    if kids is not None:
        out: list[tuple[str, Shape, bool]] = []
        used: dict[str, int] = {}
        for i, kid in enumerate(kids):
            label = (getattr(kid, "label", "") or f"Teil {i + 1}").replace("#", "-").strip() or f"Teil {i + 1}"
            n = used.get(label, 0) + 1
            used[label] = n
            child_name = f"{name}/{label}" if n == 1 else f"{name}/{label} {n}"
            for sub_name, sub_shape, _ in split_parts(kid, child_name):
                out.append((sub_name, sub_shape, True))
        return out
    if isinstance(obj, (list, tuple)):
        items = [_as_shape(o) for o in obj]
        if not items or not all(isinstance(o, Shape) for o in items):
            raise TypeError(f"show({name!r}): Liste enthält Objekte, die keine build123d-Formen sind")
        obj = Compound(items)
    if not isinstance(obj, Shape):
        raise TypeError(f"show({name!r}): {type(obj).__name__} ist keine build123d-Form (erwartet Part, Compound, "
                        "Solid, Sketch, Face, Kanten oder einen Builder)")
    return [(name, obj, False)]


# ---------------------------------------------------------------------------------------------------------------------
# Fehlermeldungen
# ---------------------------------------------------------------------------------------------------------------------


def excerpt(source: str, line: int | None, col: int | None = None, context: int = 3) -> str:
    """±3 Zeilen um ``line`` mit Zeilennummern, die Fehlerzeile mit ">" markiert."""
    if not line:
        return ""
    lines = source.splitlines()
    if not lines:
        return ""
    line = max(1, min(line, len(lines)))
    start, end = max(1, line - context), min(len(lines), line + context)
    width = len(str(end))
    out = []
    for n in range(start, end + 1):
        out.append(f"{'>' if n == line else ' '} {n:>{width}} | {lines[n - 1]}")
        if n == line and col and col > 0:
            out.append(f"  {' ' * width} | {' ' * (col - 1)}^")
    return "\n".join(out)


_LIB_DIRS = tuple(
    {os.path.realpath(p) for p in (sysconfig.get_paths().get("stdlib"), sysconfig.get_paths().get("purelib"),
                                   sysconfig.get_paths().get("platlib"), sys.prefix, sys.base_prefix) if p}
)
_OWN_DIRS = (os.path.realpath(os.path.dirname(kevcad.__file__)), os.path.realpath(os.path.dirname(__file__)))


def _is_user_file(filename: str) -> bool:
    if not filename or filename.startswith("<"):
        return False
    real = os.path.realpath(filename)
    if any(real.startswith(d + os.sep) for d in _OWN_DIRS):
        return False
    return not any(real.startswith(d + os.sep) or real == d for d in _LIB_DIRS)


def user_traceback(exc: BaseException, model_path: str) -> tuple[int | None, str]:
    """(Zeile in model.py, gekürzter Traceback nur mit Rahmen aus model.py und anderem eigenem Code)."""
    frames = traceback.extract_tb(exc.__traceback__)
    line = None
    lines = []
    for fr in frames:
        if fr.filename == model_path:
            line = fr.lineno
            lines.append(f"model.py, Zeile {fr.lineno}, in {fr.name}: {(fr.line or '').strip()}")
        elif _is_user_file(fr.filename):
            lines.append(f"{Path(fr.filename).name}, Zeile {fr.lineno}, in {fr.name}: {(fr.line or '').strip()}")
    if isinstance(exc, SyntaxError) and exc.filename == model_path:
        line = exc.lineno
    lines.append(f"{type(exc).__name__}: {exc}")
    return line, "\n".join(lines)


def hint_for(exc: BaseException, ns: dict[str, Any] | None = None) -> str:
    """Kurzer Reparaturhinweis für häufige Fehler (leer, wenn keiner passt)."""
    msg = str(exc)
    name = type(exc).__name__
    if name == "MaterialError":
        return ("Nur freigegebene Materialien aus dem Katalog (material_list). Fehlt eins: Kevin fragen und erst nach "
                "seiner Freigabe benutzen; Teile aus dem Lager tragen ihr Material schon.")
    if name == "LagerError":
        if "Freigabe" in msg:
            return "Der Eintrag ist nur vorgeschlagen: Kevin bitten, ihn im Lagerkatalog freizugeben."
        return "Lagerteile mit stock_search suchen und mit lager.teil(id) holen; Maße wie im Katalog angeben."
    if isinstance(exc, IndentationError):
        return "Einrückung prüfen: Blöcke mit 4 Leerzeichen einrücken, Tabs und Leerzeichen nicht mischen."
    if isinstance(exc, SyntaxError):
        return "Syntax prüfen: Klammern schließen, Doppelpunkt nach if/for/def/with, Kommas zwischen Argumenten."
    if isinstance(exc, NameError):
        missing = getattr(exc, "name", None)
        if missing:
            import build123d

            candidates = list(dict.fromkeys(list((ns or {}).keys()) + dir(build123d) + dir(builtins)))
            close = difflib.get_close_matches(missing, candidates, n=3, cutoff=0.7)
            if close:
                return f"Name {missing!r} ist nicht definiert. Meinten Sie {', '.join(close)}?"
            return f"Name {missing!r} ist nicht definiert: Tippfehler, fehlender Import (from build123d import *) " \
                   "oder Variable erst weiter unten angelegt?"
    if isinstance(exc, ImportError):
        return "Modul nicht gefunden: Name prüfen; eigene Hilfsdateien gehören in den Projektordner."
    if isinstance(exc, ZeroDivisionError):
        return "Division durch null: Ist ein Parameter 0?"
    if isinstance(exc, RecursionError):
        return "Endlose Rekursion: Ruft sich eine Funktion ohne Abbruchbedingung selbst auf?"
    if name in ("Standard_Failure", "StdFail_NotDone", "Standard_ConstructionError", "Standard_DomainError") \
            or "not done" in msg.lower() or "BRep_API" in msg:
        return "OCCT konnte die Operation nicht ausführen. Häufige Ursachen: Verrundung oder Fase größer als die " \
               "angrenzende Fläche, Flächen, die sich nur berühren, oder Profile mit Selbstüberschneidung. " \
               "Radius verkleinern oder Körper leicht überlappen lassen."
    if isinstance(exc, TypeError) and "unsupported operand" in msg:
        return "Boolesche Operationen nur zwischen gleichartigen Objekten: Skizzen erst mit extrude() zu Körpern " \
               "machen, Positionen mit Pos(...) * Objekt setzen."
    if isinstance(exc, TypeError) and ("argument" in msg or "positional" in msg):
        return "Aufruf prüfen: Anzahl und Namen der Argumente stimmen nicht."
    if isinstance(exc, AttributeError) and "NoneType" in msg:
        return "Ein Aufruf hat None geliefert (etwa eine leere Auswahl mit .sort_by()/.filter_by()). Auswahl prüfen."
    if isinstance(exc, AttributeError):
        return "Methode oder Eigenschaft gibt es für dieses Objekt nicht. Bei Buildern auf .part/.sketch/.line zugreifen."
    if isinstance(exc, ValueError) and ("empty" in msg.lower() or "no objects" in msg.lower()):
        return "Leere Auswahl oder leeres Ergebnis: Prüfen, ob die vorherige Operation etwas erzeugt hat."
    if isinstance(exc, IndexError):
        return "Index außerhalb der Liste: Hat die Auswahl (faces(), edges(), ...) weniger Elemente als erwartet?"
    return ""


def _error_dict(exc: BaseException, model_path: str, source: str, ns: dict[str, Any] | None) -> dict[str, Any]:
    line, tb = user_traceback(exc, model_path)
    col = exc.offset if isinstance(exc, SyntaxError) and exc.filename == model_path else None
    if isinstance(exc, SyntaxError):
        message = f"{type(exc).__name__}: {exc.msg}"
    else:
        message = f"{type(exc).__name__}: {exc}"
    return {
        "message": message,
        "line": line,
        "excerpt": excerpt(source, line, col),
        "traceback": tb,
        "hint": hint_for(exc, ns),
    }


# ---------------------------------------------------------------------------------------------------------------------
# Läufe
# ---------------------------------------------------------------------------------------------------------------------


def _purge_user_modules() -> None:
    """Eigene Module (Hilfsdateien neben model.py, per sys.path geladene Skripte) vor jedem Lauf neu laden lassen."""
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and name not in ("__main__",) and _is_user_file(f):
            sys.modules.pop(name, None)


class _Capture(io.StringIO):
    """stdout des Modells sammeln (begrenzt)."""

    def write(self, s: str) -> int:  # type: ignore[override]
        if self.tell() < MAX_STDOUT:
            return super().write(s)
        return len(s)


class Runner:
    """Zustand des Rechenprozesses: Namensraum des letzten Laufs, Parameter, Laufnummer."""

    def __init__(self, emit: Emit) -> None:
        self.emit = emit
        self.ns: dict[str, Any] | None = None
        self.ns_project: str | None = None
        self.run_no = 0
        self.params: dict[str, Any] = {}
        self.catalog: Catalog | None = None
        self.inventar = True  # Inventar-Regel des letzten Laufs (gilt auch für execute)

    def _catalog(self, msg: dict[str, Any], project: str | None) -> Catalog:
        """Katalog mit den Ordnern aus der Laufzeit (Nachricht ``catalog``) und dem Projekt des Laufs."""
        dirs = msg.get("catalog") or {}
        if self.catalog is None:
            self.catalog = Catalog(builtin=dirs.get("builtin"), own=dirs.get("own"), project=project)
        else:
            self.catalog.configure(builtin=dirs.get("builtin"), own=dirs.get("own"), project=project)
        self.catalog.refresh()
        return self.catalog

    # -- Hooks ---------------------------------------------------------------------------------------------------------

    def _install(self, *, run: int, overrides: dict[str, Any], slow_ms: int, deviation: float, angular: float,
                 sketch: bool, state: dict[str, Any], catalog: Catalog | None = None,
                 register: LagerRegister | None = None, strict: bool = False) -> None:
        def show(obj: Any, name: str | None = None, color: Any = None, material: Any = None) -> None:
            if name is None or not str(name).strip():
                label = getattr(_as_shape(obj), "label", "") or ""
                name = label or f"Teil {len(state['shown']) + 1}"
                state["warnings"].append(f"show() ohne Namen: als {name!r} gezeigt; bitte sprechenden Namen angeben")
            name = str(name).strip().strip("/").replace("#", "-")
            if sketch and not name.startswith(SKETCH_PREFIX):
                name = SKETCH_PREFIX + name
            explicit_color = None
            if color is not None:
                try:
                    explicit_color = parse_color(color)
                except ValueError as exc:
                    state["warnings"].append(f"{name}: {exc}")
            explicit = None
            if material is not None:
                if strict:
                    explicit = material_info(material, catalog, strict=True)  # Fehler bricht den Lauf hier ab
                else:
                    try:
                        explicit = material_info(material, catalog)
                    except ValueError as exc:
                        state["warnings"].append(f"{name}: {exc}")
            for part_name, shape, is_child in split_parts(obj, name):
                self._show_part(part_name, shape, is_child, explicit_color, explicit, run=run, deviation=deviation,
                                angular=angular, sketch=sketch, state=state, catalog=catalog, register=register,
                                strict=strict)
                if slow_ms > 0:
                    time.sleep(slow_ms / 1000.0)

        def step(text: str) -> None:
            state["steps"].append(str(text))
            if not sketch:
                self.emit({"type": "STEP", "run": run, "index": len(state["steps"]), "text": str(text)}, b"")

        def param(name: str, default: Any, min: Any = None, max: Any = None) -> Any:  # noqa: A002
            if not isinstance(name, str) or not name:
                raise TypeError("param() braucht einen Namen als Text, z. B. param(\"breite\", 120)")
            value = default
            if name in overrides and overrides[name] is not None:
                value = overrides[name]
                if isinstance(default, bool):
                    value = bool(value)
                elif isinstance(default, int) and isinstance(value, (int, float)) and float(value).is_integer():
                    value = int(value)
                elif isinstance(default, (int, float)) and not isinstance(value, (int, float)):
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        state["warnings"].append(f"param {name}: Wert {value!r} ist keine Zahl, Vorgabe {default!r}")
                        value = default
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if min is not None and value < min:
                    state["warnings"].append(f"param {name} = {value} liegt unter dem Minimum {min}")
                if max is not None and value > max:
                    state["warnings"].append(f"param {name} = {value} liegt über dem Maximum {max}")
            state["params"][name] = value
            return value

        def lager(piece: Piece, shape: Any) -> None:
            if register is not None:
                register.register(piece, shape)

        def warn(text: str) -> None:
            state["warnings"].append(str(text))

        def animation(anim: Any) -> None:  # Phase 5: Animationen sammeln, ausgewertet wird nach dem Lauf
            anims = state.setdefault("animations", [])
            names = {a.name for a in anims}
            if anim.name is None:
                anim.name = "Animation" if "Animation" not in names else next(
                    f"Animation {i}" for i in range(2, 1000) if f"Animation {i}" not in names)
            elif anim.name in names:
                raise ValueError(f"Animation {anim.name!r} gibt es schon; jede Animation braucht einen eigenen Namen")
            anims.append(anim)

        hooks: dict[str, Any] = {"show": show, "step": step, "param": param, "warn": warn}
        if not sketch:
            hooks["animation"] = animation
        if catalog is not None:
            hooks["catalog"] = lambda: catalog
        if register is not None:
            hooks["lager"] = lager
        kevcad._hooks.update(hooks)

    def _show_part(self, name: str, shape: Shape, is_child: bool, explicit_color, explicit: MatInfo | None, *,
                   run: int, deviation: float, angular: float, sketch: bool, state: dict[str, Any],
                   catalog: Catalog | None = None, register: LagerRegister | None = None,
                   strict: bool = False) -> None:
        if _is_empty(shape):
            state["warnings"].append(f"{name}: leere Form, nicht gezeigt")
            return
        # Lagerteile zu diesem Teil (Name wie in verbauen, sonst Form, sonst label)
        pieces = register.link(name, shape) if register is not None and not sketch else []
        piece_mat = None
        if pieces and catalog is not None and pieces[0].material_id:
            entry = catalog.material(pieces[0].material_id)
            piece_mat = catalog_matinfo(entry) if entry is not None else None
        # Material: bei Unterteilen zuerst das eigene (build123d, auch vom Eltern-Compound geerbt), sonst show(material);
        # danach das Material des Lagerteils
        own = None
        if not strict:  # mit Inventar-Regel zählen nur Katalogmaterialien, nicht die von build123d
            try:
                own_fm = shape.material
                own = material_info(own_fm, catalog) if own_fm is not None else None
            except Exception:  # noqa: BLE001
                own = None
        if pieces:  # verbaute Lagerteile tragen ihr Katalogmaterial (bd_warehouse setzt sonst Baustahl)
            mat = (None if is_child else explicit) or piece_mat or own
        elif is_child:
            mat = own or explicit
        else:
            mat = explicit or own
        # Farbe: bei Unterteilen zuerst die eigene; sonst show(color) > Teilfarbe > Materialfarbe > Palette
        own_color = None
        try:
            c = shape.color
            own_color = tuple(float(x) for x in c) if c is not None else None
        except Exception:  # noqa: BLE001
            own_color = None
        if is_child:
            color = own_color or explicit_color
        else:
            color = explicit_color or own_color
        if color is None and mat is not None:
            color = mat.color
        if color is None:
            color = SKETCH_COLOR if sketch else palette_color(name)
        if sketch:
            color = (color[0], color[1], color[2], 0.5)

        brep = serialize_shape(shape.wrapped)
        tess = tessellate_shape(shape, deviation, angular, brep=brep)
        props = dict(tess.props)
        density = mat.density if mat is not None else None
        if density is not None:
            props["mass"] = round(props["volume"] * density * 1e-6, 6)  # mm³ · kg/m³ · 1e-6 = g
        header, payload = pack_part(run=run, name=name, geometry=tess.geometry, color=color, bbox=tess.bbox,
                                    props=props, material=mat.display if mat is not None else None)
        header.pop("seq", None)
        if len({p.seq for p in pieces}) == 1:
            if pieces[0].stock_id:
                header["stock"] = pieces[0].stock_info()
            elif pieces[0].art == "druckteil":
                header["druckteil"] = pieces[0].druck_info()
        if strict and not sketch:
            header["inventar"] = "ok" if pieces else "fehlt"
        if not sketch:
            entry = mat.entry if mat is not None else None
            lo, hi = tess.bbox.get("min", [0, 0, 0]), tess.bbox.get("max", [0, 0, 0])
            state["bom_parts"][name] = ShownPart(
                name=name, material=mat.display if mat is not None else None,
                material_id=entry["id"] if entry else None,
                material_name=(entry.get("name") if entry else (mat.display if mat is not None else None)),
                preis_je_kg=number(entry.get("preis_je_kg")) if entry else None,
                preis_stand=entry.get("preis_stand") if entry else None,
                volume=float(props.get("volume") or 0.0), mass_g=props.get("mass"),
                size=[round(float(b) - float(a), 3) for a, b in zip(lo, hi)], pieces=[p.seq for p in pieces])
        if not sketch:
            state.setdefault("bboxes", {})[name] = (list(tess.bbox.get("min", [0, 0, 0])),
                                                    list(tess.bbox.get("max", [0, 0, 0])))
        if name in state["shown"]:
            state["shown"].remove(name)
        state["shown"].append(name)
        state["tess_ms"] += tess.tess_ms
        state["cached"] += int(tess.cached)
        self.emit({"type": "PART", "run": run, "name": name, "key": tess.key, "cached": tess.cached,
                   "tess_ms": round(tess.tess_ms, 2), "density": density, "app_len": len(payload), "app": header},
                  payload + brep)

    @staticmethod
    def _uninstall() -> None:
        kevcad._hooks.clear()

    # -- Lauf ----------------------------------------------------------------------------------------------------------

    def run(self, msg: dict[str, Any]) -> dict[str, Any]:
        run = int(msg["run"])
        path = str(msg["path"])
        source = msg.get("code")
        if source is None:
            source = Path(path).read_text(encoding="utf-8")
        overrides = dict(msg.get("params") or {})
        slow_ms = int(msg.get("slow_ms") or 0)
        deviation = float(msg.get("deviation") or DEFAULT_DEVIATION)
        angular = float(msg.get("angular") or DEFAULT_ANGULAR)
        project = str(Path(path).parent)
        self.run_no = run
        state: dict[str, Any] = {"shown": [], "steps": [], "warnings": [], "params": {}, "tess_ms": 0.0, "cached": 0,
                                 "bom_parts": {}}
        register = LagerRegister()
        strict = self.inventar = bool(msg.get("inventar_regel", True))
        catalog = None
        try:
            catalog = self._catalog(msg, project)
        except Exception as exc:  # noqa: BLE001 - ohne Katalog rechnen, aber Bescheid geben
            state["warnings"].append(f"Katalog nicht geladen: {type(exc).__name__}: {exc}")
        ns: dict[str, Any] = {"__name__": "__main__", "__file__": path, "__builtins__": builtins}
        out = _Capture()
        t0 = time.perf_counter()
        old_cwd, old_path = os.getcwd(), list(sys.path)
        # Tracebacks sollen den ausgeführten Code zeigen, nicht einen inzwischen geänderten Dateistand
        linecache.cache[path] = (len(source), None, source.splitlines(True), path)
        error = None
        try:
            _purge_user_modules()
            with contextlib.suppress(OSError):
                os.chdir(project)
            sys.path.insert(0, project)
            self._install(run=run, overrides=overrides, slow_ms=slow_ms, deviation=deviation, angular=angular,
                          sketch=False, state=state, catalog=catalog, register=register, strict=strict)
            with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(out):
                warnings.simplefilter("always")
                try:
                    code = compile(source, path, "exec")
                    exec(code, ns)  # noqa: S102 - eigener Code auf dem eigenen Rechner (PLAN-MVP, Rechenprozess)
                except SystemExit as exc:
                    if exc.code not in (None, 0):
                        error = _error_dict(exc, path, source, ns)
                except Exception as exc:  # noqa: BLE001
                    error = _error_dict(exc, path, source, ns)
            for w in caught[:MAX_WARNINGS]:
                state["warnings"].append(f"{w.category.__name__}: {w.message}")
        finally:
            self._uninstall()
            sys.path[:] = old_path
            with contextlib.suppress(OSError):
                os.chdir(old_cwd)
        anim_names: list[str] = []
        if error is None and state.get("animations"):
            error, anim_names = self._animations(run, state, path, source)
        self.ns = ns
        self.ns_project = project
        self.params = dict(state["params"])
        result = {
            "run": run,
            "shown": state["shown"],
            "steps": state["steps"],
            "warnings": state["warnings"][:MAX_WARNINGS],
            "params": state["params"],
            "stdout": out.getvalue(),
            "duration_ms": int(round((time.perf_counter() - t0) * 1000)),
            "tess_ms": round(state["tess_ms"], 1),
            "cached": state["cached"],
        }
        if anim_names:
            result["animations"] = anim_names
        if error is not None:
            result["type"] = "RUN_FAILED"
            result["error"] = error
        else:
            result["type"] = "RUN_DONE"
            parts = [state["bom_parts"][n] for n in state["shown"] if n in state["bom_parts"]]
            result["inventar_regel"] = strict
            result["inventar_verstoesse"] = [sp.name for sp in parts if not sp.pieces] if strict else []
            try:
                result["bom"] = build_bom(register.pieces, parts, inventar_regel=strict)
            except Exception as exc:  # noqa: BLE001 - Stückliste darf den Lauf nicht kippen
                result["warnings"].append(f"Stückliste nicht erstellt: {type(exc).__name__}: {exc}")
        return result

    def _animations(self, run: int, state: dict[str, Any], path: str,
                    source: str) -> tuple[dict[str, Any] | None, list[str]]:
        """Phase 5: Animationen gegen die gezeigten Teile auswerten und als ``ANIM`` schicken. Ein Fehler (unbekanntes
        Teil, Kreis bei folge …) bricht den Lauf mit der Zeile der Spur ab."""
        from kevcad.bewegung import AnimationError
        from kevcad_kernel.animation import evaluate_all, worker_message

        try:
            results = evaluate_all(state["animations"], state["shown"], state.get("bboxes", {}))
        except AnimationError as exc:
            line = exc.line if exc.filename in (None, path) else None
            where = f"model.py, Zeile {line}" if line else (f"{Path(exc.filename).name}, Zeile {exc.line}"
                                                           if exc.filename and exc.line else "model.py")
            return {"message": f"AnimationError: {exc}", "line": line, "excerpt": excerpt(source, line),
                    "traceback": f"{where}\nAnimationError: {exc}",
                    "hint": "Teilnamen wie in show() angeben (Baugruppe = Präfix vor \"/\"); Zeiten zwischen 0 und "
                            "dauer."}, []
        except Exception as exc:  # noqa: BLE001 - Auswertung darf den Lauf nicht abstürzen lassen
            return {"message": f"Animation nicht ausgewertet: {type(exc).__name__}: {exc}", "line": None,
                    "excerpt": "", "traceback": traceback.format_exc(limit=6), "hint": ""}, []
        for a in results:
            state["warnings"].extend(a.warnungen)
            head, payload = worker_message(a, run)
            self.emit(head, payload)
        return None, [a.name for a in results]

    # -- execute -------------------------------------------------------------------------------------------------------

    def execute(self, msg: dict[str, Any]) -> dict[str, Any]:
        code = str(msg.get("code") or "")
        project = msg.get("project")
        run = int(msg.get("run") or self.run_no or 0)
        deviation = float(msg.get("deviation") or DEFAULT_DEVIATION)
        angular = float(msg.get("angular") or DEFAULT_ANGULAR)
        fresh = self.ns is None or (project is not None and self.ns_project != str(project))
        if fresh:
            self.ns = {"__name__": "__main__", "__builtins__": builtins}
            exec("from build123d import *\nfrom kevcad import show, step, param, lager", self.ns)  # noqa: S102
            self.ns_project = str(project) if project is not None else None
        ns = self.ns
        state: dict[str, Any] = {"shown": [], "steps": [], "warnings": [], "params": dict(self.params),
                                 "tess_ms": 0.0, "cached": 0, "bom_parts": {}}
        catalog = None
        try:
            catalog = self._catalog(msg, str(project) if project else None)
        except Exception:  # noqa: BLE001
            catalog = None
        out = _Capture()
        result: dict[str, Any] = {"type": "EXEC_RES", "ok": True, "result": None, "fresh_namespace": fresh}
        old_cwd = os.getcwd()
        try:
            if project:
                with contextlib.suppress(OSError):
                    os.chdir(str(project))
            strict = bool(msg.get("inventar_regel", self.inventar))
            self._install(run=run, overrides=self.params, slow_ms=0, deviation=deviation, angular=angular,
                          sketch=True, state=state, catalog=catalog, strict=strict)
            with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(out):
                warnings.simplefilter("always")
                try:
                    tree = ast.parse(code, "<execute>", "exec")
                    last = tree.body[-1] if tree.body and isinstance(tree.body[-1], ast.Expr) else None
                    body = tree.body[:-1] if last is not None else tree.body
                    exec(compile(ast.Module(body=body, type_ignores=[]), "<execute>", "exec"), ns)  # noqa: S102
                    if last is not None:
                        value = eval(compile(ast.Expression(last.value), "<execute>", "eval"), ns)  # noqa: S307
                        if value is not None:
                            text = repr(value)
                            result["result"] = text if len(text) <= 10_000 else text[:10_000] + " …"
                except BaseException as exc:  # noqa: BLE001
                    if isinstance(exc, KeyboardInterrupt):
                        raise
                    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == "<execute>"]
                    line = exc.lineno if isinstance(exc, SyntaxError) else (frames[-1].lineno if frames else None)
                    result.update(ok=False, error=f"{type(exc).__name__}: {exc}", line=line,
                                  excerpt=excerpt(code, line), hint=hint_for(exc, ns))
            for w in caught[:MAX_WARNINGS]:
                state["warnings"].append(f"{w.category.__name__}: {w.message}")
        finally:
            self._uninstall()
            with contextlib.suppress(OSError):
                os.chdir(old_cwd)
        result["stdout"] = out.getvalue()
        result["shown"] = state["shown"]
        result["warnings"] = state["warnings"][:MAX_WARNINGS]
        return result
