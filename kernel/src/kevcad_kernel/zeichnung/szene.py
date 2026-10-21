"""Eingangsdaten der Zeichnungs-Engine: Teile eines Laufs mit Form, Formschlüssel, Kopfdaten, Katalogeintrag;
Stückliste und Projektangaben. Merkmale werden je Formstand zwischengespeichert (Teil unverändert → keine neue
Erkennung, auch über Läufe hinweg)."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.merkmale import Merkmal, Merkmale, erkenne, verbindungsmittel, zahl
from kevcad_kernel.zeichnung.teilsystem import STANGENWARE, Teilsystem

KLEINTEIL_ARTEN = ("schraube", "mutter", "scheibe")
NICHT_GEFERTIGT = ("kamera", "objektiv", "kamerazubehoer")


@dataclass
class Teil:
    name: str
    form: Any  # build123d-Form in Weltkoordinaten
    key: str  # Formschlüssel des Laufs
    kopf: dict[str, Any] = field(default_factory=dict)  # PART_UPSERT-Kopf (stock, druckteil, material, props, bbox)
    katalog: dict[str, Any] | None = None  # Lagerteil-Eintrag

    @property
    def info(self) -> dict[str, Any]:
        return {"stock": self.kopf.get("stock"), "druckteil": self.kopf.get("druckteil"),
                "material": self.kopf.get("material"), "katalog": self.katalog}

    @property
    def lo(self) -> np.ndarray:
        return np.asarray((self.kopf.get("bbox") or {}).get("min") or [0, 0, 0], dtype=float)

    @property
    def hi(self) -> np.ndarray:
        return np.asarray((self.kopf.get("bbox") or {}).get("max") or [0, 0, 0], dtype=float)

    @property
    def masse_g(self) -> float | None:
        m = (self.kopf.get("props") or {}).get("mass")
        return float(m) if isinstance(m, (int, float)) else None

    @property
    def lager_art(self) -> str:
        if self.katalog and self.katalog.get("art"):
            return str(self.katalog["art"])
        if self.kopf.get("druckteil"):
            return "druckteil"
        sid = str((self.kopf.get("stock") or {}).get("id") or "")
        for a in (*STANGENWARE, "platte", *KLEINTEIL_ARTEN):
            if sid.startswith(a):
                return a
        return ""

    @property
    def gefertigt(self) -> bool:
        """Wird das Teil gefertigt (Zuschnitt, Bearbeitung, Druck)? Stangenware, Platten, Druckteile."""
        art = self.lager_art
        return art in STANGENWARE or art == "platte" or art == "druckteil"


class _MerkmalCache:
    def __init__(self, groesse: int = 512) -> None:
        self._d: OrderedDict[str, Merkmale] = OrderedDict()
        self._lock = threading.Lock()
        self.groesse = groesse

    def get(self, key: str) -> Merkmale | None:
        with self._lock:
            m = self._d.get(key)
            if m is not None:
                self._d.move_to_end(key)
            return m

    def put(self, key: str, m: Merkmale) -> None:
        with self._lock:
            self._d[key] = m
            while len(self._d) > self.groesse:
                self._d.popitem(last=False)


MERKMAL_CACHE = _MerkmalCache()
_VM_CACHE: dict[str, dict[str, Any] | None] = {}


@dataclass
class Szene:
    teile: dict[str, Teil]
    bom: dict[str, Any] | None = None
    projekt: dict[str, Any] = field(default_factory=dict)  # name, pfad, version, datum
    run: int = 0
    _vm: list[dict[str, Any]] | None = None

    def namen(self) -> list[str]:
        return list(self.teile)

    def auswahl(self, namen: list[str]) -> list[Teil]:
        """Teile nach Namen oder Gruppenpräfix, in der Reihenfolge der Szene."""
        out: list[Teil] = []
        for n in namen or []:
            n = str(n).split("#", 1)[0]
            if n in ("*", ""):
                out += [t for t in self.teile.values() if t not in out]
                continue
            if n in self.teile:
                if self.teile[n] not in out:
                    out.append(self.teile[n])
                continue
            p = n.rstrip("/") + "/"
            out += [t for name, t in self.teile.items() if name.startswith(p) and t not in out]
        return out

    def verbindungsmittel(self) -> list[dict[str, Any]]:
        """Schrauben, Gewindestifte, Einsätze, Muttern der Szene (für Gewinde und Einsatztaschen)."""
        if self._vm is None:
            out = []
            for t in self.teile.values():
                if t.key in _VM_CACHE:
                    vm = _VM_CACHE[t.key]
                else:
                    try:
                        vm = verbindungsmittel(t.name, t.form, t.info)
                    except Exception:  # noqa: BLE001 - Verbindungsmittel sind nur ein Hinweis
                        vm = None
                    _VM_CACHE[t.key] = vm
                if vm is not None:
                    out.append({**vm, "name": t.name, "_lo": t.lo, "_hi": t.hi, "_key": t.key})
            self._vm = out
        return self._vm

    def merkmale(self, name: str) -> Merkmale | None:
        t = self.teile.get(name)
        if t is None:
            return None
        lo, hi = t.lo - 0.5, t.hi + 0.5
        nah = [v for v in self.verbindungsmittel() if v["name"] != name
               and np.all(v["_lo"] <= hi) and np.all(v["_hi"] >= lo)]
        key = hashlib.sha1((t.key + "|" + "|".join(sorted(v["_key"] for v in nah)) + "|"
                            + str(t.katalog.get("id") if t.katalog else "")).encode()).hexdigest()
        m = MERKMAL_CACHE.get(key)
        if m is None:
            m = erkenne(t.form, t.info, name=name, umgebung=nah)
            MERKMAL_CACHE.put(key, m)
        return m

    def bom_zeile(self, name: str) -> dict[str, Any] | None:
        for ln in (self.bom or {}).get("lines") or []:
            if name in (ln.get("teile") or []):
                return ln
        return None

    def gleiche_teile(self, name: str) -> list[str]:
        """Alle Teile derselben Stücklistenposition (für „gilt für“ und die Stückzahl)."""
        ln = self.bom_zeile(name)
        return list(ln.get("teile") or [name]) if ln else [name]


def gruppen_merkmale(teile: list[Teil], name: str = "Zusammenbau") -> Merkmale:
    """Hülle einer Baugruppe als Merkmale (für Hauptmaße): System = Weltachsen, Ursprung in der Min-Ecke."""
    lo = np.min([t.lo for t in teile], axis=0) if teile else np.zeros(3)
    hi = np.max([t.hi for t in teile], axis=0) if teile else np.zeros(3)
    sys = Teilsystem(np.eye(3), lo, hi - lo, "welt")
    g = hi - lo
    liste = [Merkmal("huelle", "huelle", {"typ": "box", "mitte": g / 2, "richtung": None, "radius": None,
                                          "laenge": float(g.max())}, {"groesse": g},
                     f"{zahl(g[0])} × {zahl(g[1])} × {zahl(g[2])}")]
    for i in range(3):
        for s, z in ((-1, "-"), (1, "+")):
            p = g / 2
            p = p.copy()
            p[i] = 0.0 if s < 0 else g[i]
            n = np.zeros(3)
            n[i] = s
            liste.append(Merkmal(f"seite:{'xyz'[i]}{z}", "seite",
                                 {"typ": "ebene", "mitte": p, "richtung": n, "radius": None, "laenge": None},
                                 {"achse": i, "seite": s}))
    return Merkmale(name, sys, liste, {"art": "baugruppe"})
