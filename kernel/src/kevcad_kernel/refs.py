"""Szene der Laufzeit und Referenzen ``Teil#f12`` / ``Teil#e3`` / ``Teil#v2`` / ``Teil`` (PROTOCOL.md).

Die Laufzeit hält je Teil den Kopf und die Nutzlast des letzten ``PART_UPSERT`` (für neu verbundene Apps) und die
BRep-Binärform aus dem Rechenprozess. Die build123d-Form entsteht daraus erst, wenn gemessen oder exportiert wird.

Gültigkeit: Eine Referenz trägt die Laufnummer, in der sie entstand. Sie gilt, solange das Teil seitdem nicht neu
berechnet wurde (gleicher Formschlüssel zählt als unverändert, auch über mehrere Läufe). Ohne Laufnummer gilt der
aktuelle Stand.
"""

from __future__ import annotations

import difflib
import re
import threading
from dataclasses import dataclass, field
from typing import Any

_REF = re.compile(r"^(?P<part>.+?)(?:#(?P<kind>[fev])(?P<index>\d+))?$")
KIND_NAMES = {"f": "face", "e": "edge", "v": "vertex"}
KIND_GERMAN = {"f": ("Fläche", "Flächen"), "e": ("Kante", "Kanten"), "v": ("Punkt", "Punkte")}


class RefError(ValueError):
    """Referenz ungültig, unbekannt oder veraltet (Meldung ist für den Agenten und die App gedacht)."""


@dataclass
class PartRecord:
    name: str
    run: int  # Lauf, der das Teil zuletzt geschickt hat
    since_run: int  # seit diesem Lauf unverändert
    key: str  # Formschlüssel aus dem Rechenprozess
    header: dict[str, Any]  # Kopf des PART_UPSERT ohne seq
    payload: bytes  # Nutzlast des PART_UPSERT
    brep: bytes  # BRep-Binärform
    density: float | None = None  # kg/m³
    visible: bool = True
    _shape: Any = field(default=None, repr=False)
    _lists: dict[str, Any] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- Werte aus dem Kopf --------------------------------------------------------------------------------------------

    @property
    def counts(self) -> dict[str, int]:
        return self.header.get("counts", {})

    @property
    def props(self) -> dict[str, Any]:
        return self.header.get("props", {})

    @property
    def bbox(self) -> dict[str, list[float]]:
        return self.header.get("bbox", {})

    @property
    def material(self) -> str | None:
        return self.header.get("material")

    @property
    def color(self) -> list[float]:
        return self.header.get("color", [0.72, 0.75, 0.79, 1.0])

    def summary(self) -> dict[str, Any]:
        bb = self.bbox
        size = [round(b - a, 6) for a, b in zip(bb.get("min", [0, 0, 0]), bb.get("max", [0, 0, 0]))]
        c = self.counts
        return {
            "name": self.name,
            "bbox": {"min": bb.get("min"), "max": bb.get("max"), "size": size},
            "volume": self.props.get("volume", 0.0),
            "area": self.props.get("area", 0.0),
            "mass": self.props.get("mass"),
            "material": self.material,
            "color": self.color,
            "faces": c.get("face", 0),
            "edges": c.get("edge", 0),
            "triangles": c.get("tri", 0),
            "visible": self.visible,
            "run": self.run,
        }

    # -- Form (erst bei Bedarf) ----------------------------------------------------------------------------------------

    @property
    def shape(self):
        with self._lock:
            if self._shape is None:
                from kevcad_kernel.tessellate import deserialize_shape

                self._shape = deserialize_shape(self.brep)
            return self._shape

    def elements(self, kind: str) -> list[Any]:
        """Flächen ("f"), Kanten ("e") oder Punkte ("v") in der Nummerierung von PROTOCOL.md."""
        shape = self.shape
        with self._lock:
            if kind not in self._lists:
                from kevcad_kernel.tessellate import edges_of, faces_of, vertices_of

                fn = {"f": faces_of, "e": edges_of, "v": vertices_of}[kind]
                self._lists[kind] = list(fn(shape))
            return self._lists[kind]


class Scene:
    """Teile des aktuellen Stands, in der Reihenfolge, in der sie zuerst gezeigt wurden. Threadsicher."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._parts: dict[str, PartRecord] = {}

    def upsert(self, *, name: str, run: int, key: str, header: dict[str, Any], payload: bytes, brep: bytes,
               density: float | None) -> PartRecord:
        with self.lock:
            old = self._parts.get(name)
            since = old.since_run if old is not None and old.key == key else run
            rec = PartRecord(name=name, run=run, since_run=since, key=key, header=header, payload=payload, brep=brep,
                             density=density, visible=old.visible if old is not None else True)
            if old is not None and old.key == key:
                rec._shape = old._shape  # gleiche Form: entpackte Form weiterverwenden
                rec._lists = old._lists
            self._parts[name] = rec
            return rec

    def remove(self, name: str) -> PartRecord | None:
        with self.lock:
            return self._parts.pop(name, None)

    def clear(self) -> list[PartRecord]:
        with self.lock:
            old = list(self._parts.values())
            self._parts.clear()
            return old

    def get(self, name: str) -> PartRecord | None:
        with self.lock:
            return self._parts.get(name)

    def records(self) -> list[PartRecord]:
        with self.lock:
            return list(self._parts.values())

    def names(self) -> list[str]:
        with self.lock:
            return list(self._parts)

    def group(self, prefix: str) -> list[PartRecord]:
        """Alle Teile unterhalb von ``prefix`` im Baum (``Halter`` → ``Halter/Lasche``, ``Halter/Platte``)."""
        p = prefix.rstrip("/") + "/"
        with self.lock:
            return [r for n, r in self._parts.items() if n.startswith(p)]

    def select(self, names: list[str] | None) -> list[PartRecord]:
        """Teile nach Namen oder Gruppen; None = alle. Unbekannte Namen → RefError."""
        if not names:
            return self.records()
        out: list[PartRecord] = []
        seen: set[str] = set()
        for n in names:
            n = n.split("#", 1)[0]
            rec = self.get(n)
            recs = [rec] if rec is not None else self.group(n)
            if not recs:
                raise RefError(unknown_part_message(n, self.names()))
            for r in recs:
                if r.name not in seen:
                    seen.add(r.name)
                    out.append(r)
        return out


@dataclass
class Ref:
    text: str
    part: str
    kind: str | None  # "f", "e", "v" oder None (ganzes Teil oder Gruppe)
    index: int | None


@dataclass
class Resolved:
    ref: Ref
    kind: str  # face | edge | vertex | part | group
    records: list[PartRecord]
    shape: Any  # build123d-Form des Elements, des Teils oder der Gruppe (Compound)

    @property
    def record(self) -> PartRecord:
        return self.records[0]


def parse_ref(text: str) -> Ref:
    if not isinstance(text, str) or not text.strip():
        raise RefError("Leere Referenz. Form: \"Teil\", \"Teil#f3\" (Fläche), \"Teil#e2\" (Kante), \"Teil#v0\" (Punkt)")
    t = text.strip()
    m = _REF.match(t)
    if m is None or (("#" in t) and m.group("kind") is None):
        raise RefError(f"Referenz {text!r} nicht lesbar. Form: \"Teil\", \"Teil#f3\" (Fläche), \"Teil#e2\" (Kante), "
                       "\"Teil#v0\" (Punkt)")
    idx = m.group("index")
    return Ref(text=t, part=m.group("part"), kind=m.group("kind"), index=int(idx) if idx is not None else None)


def unknown_part_message(name: str, names: list[str]) -> str:
    if not names:
        return f"Unbekanntes Teil {name!r}: es sind keine Teile da (erst rechnen)."
    close = difflib.get_close_matches(name, names, n=3, cutoff=0.5)
    tip = f" Meinten Sie {', '.join(repr(c) for c in close)}?" if close else ""
    shown = ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
    return f"Unbekanntes Teil {name!r}.{tip} Vorhanden: {shown}"


def resolve(scene: Scene, text: str, run: int | None = None, latest_run: int | None = None) -> Resolved:
    """Referenz gegen den aktuellen Stand auflösen. ``run`` = Laufnummer der Referenz (None: ohne Prüfung)."""
    ref = parse_ref(text)
    rec = scene.get(ref.part)
    if rec is None:
        group = scene.group(ref.part)
        if group and ref.kind is None:
            _check_run(ref, group, run, latest_run)
            from build123d import Compound

            shape = Compound([r.shape for r in group]) if len(group) > 1 else group[0].shape
            return Resolved(ref, "group", group, shape)
        if group:
            raise RefError(f"{ref.part!r} ist eine Gruppe; Flächen, Kanten und Punkte gibt es nur an einzelnen Teilen "
                           f"(z. B. {group[0].name}#f0).")
        raise RefError(unknown_part_message(ref.part, scene.names()))
    _check_run(ref, [rec], run, latest_run)
    if ref.kind is None:
        return Resolved(ref, "part", [rec], rec.shape)
    items = rec.elements(ref.kind)
    one, many = KIND_GERMAN[ref.kind]
    if ref.index is None or ref.index >= len(items):
        if not items:
            raise RefError(f"Teil {rec.name!r} hat keine {many}.")
        raise RefError(f"{ref.text!r}: Teil {rec.name!r} hat {len(items)} {many} "
                       f"(#{ref.kind}0 bis #{ref.kind}{len(items) - 1}).")
    return Resolved(ref, KIND_NAMES[ref.kind], [rec], items[ref.index])


def _check_run(ref: Ref, records: list[PartRecord], run: int | None, latest_run: int | None) -> None:
    if run is None:
        return
    if latest_run is not None and run > latest_run:
        raise RefError(f"{ref.text!r}: Lauf {run} ist unbekannt (letzter Lauf {latest_run}).")
    for rec in records:
        if rec.since_run > run:
            raise RefError(f"{ref.text!r} stammt aus Lauf {run}, Teil {rec.name!r} wurde in Lauf {rec.since_run} neu "
                           f"berechnet. Referenz ist veraltet: bitte neu auswählen (aktueller Lauf {rec.run}).")
