"""Zwischenspeicher je Version für Vergleich und Vorschaubild (PLAN-VERSIONEN.md, V4 und V6).

- ``daten/<nr>.json``: Teile (Name, Formschlüssel, Volumen, Masse, Lage, Farbe, Material, Lagerteil), Stückliste,
  Parameter, Prüfstand und Schritte des Laufs, der die Version zuletzt gerechnet hat (ohne überschriebene Parameter).
- ``geometrie/<hash>.kvg``: Netz eines Teils je Formschlüssel (Punkte, Normalen, Dreiecke, Kanten), zlib-gepackt.
  Gleiche Teile in vielen Versionen liegen nur einmal da. Größe begrenzt (älteste zuerst weg); fehlt ein Netz, rechnet
  der Kernel die Version neu (Lauf ohne Live-Aufbau).
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import threading
import zlib
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.protocol import unpack_part

MAGIC = b"KVG1"
MAX_GEOMETRIE_BYTES = 400 * 1024 * 1024
NETZ_ARRAYS = ("positions", "normals", "triangles", "edge_points", "edge_offsets")


def teil_daten(name: str, key: str, header: dict[str, Any]) -> dict[str, Any]:
    """Was der Vergleich über ein Teil wissen muss (aus dem Kopf von PART_UPSERT)."""
    props = header.get("props") or {}
    bbox = header.get("bbox") or {}
    out: dict[str, Any] = {
        "name": name, "key": key,
        "volumen": _r(props.get("volume")), "flaeche": _r(props.get("area")), "masse": _r(props.get("mass")),
        "mitte": [_r(x) for x in (props.get("center") or [])] or None,
        "min": [_r(x) for x in (bbox.get("min") or [])], "max": [_r(x) for x in (bbox.get("max") or [])],
        "farbe": [round(float(c), 4) for c in (header.get("color") or [])], "material": header.get("material"),
        "dreiecke": int((header.get("counts") or {}).get("tri", 0)),
    }
    stock = header.get("stock")
    if isinstance(stock, dict):
        out["lager"] = {k: stock.get(k) for k in ("id", "name", "laenge", "gehrung") if stock.get(k) is not None}
    druck = header.get("druckteil")
    if isinstance(druck, dict):
        out["druckteil"] = {k: druck.get(k) for k in ("verfahren", "material") if druck.get(k) is not None}
    return out


def _r(x: Any, n: int = 6) -> float | None:
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def kennzahlen(teile: list[dict[str, Any]], bom: dict[str, Any] | None,
               pruefung: dict[str, Any] | None = None) -> dict[str, Any]:
    """Teilezahl, Masse (kg, aus den Teilen, sonst aus der Stückliste), Kosten (Stückliste), Prüfzähler."""
    masse_g = sum(float(t["masse"]) for t in teile if t.get("masse"))
    totals = (bom or {}).get("totals") or {}
    out: dict[str, Any] = {"teile": len(teile)}
    if masse_g > 0:
        out["masse_kg"] = round(masse_g / 1000.0, 3)
    elif totals.get("kg"):
        out["masse_kg"] = round(float(totals["kg"]), 3)
    if totals.get("preis") is not None:
        out["kosten"] = round(float(totals["preis"]), 2)
    if (bom or {}).get("lines"):
        out["positionen"] = len(bom["lines"])
    if pruefung:
        out.update(pruef_kurz(pruefung))
    return out


def pruef_kurz(check: dict[str, Any] | None) -> dict[str, Any]:
    """Prüfstand für die Kennzahlen: Fehler, Warnungen, Zusammenfassung (aus CHECK)."""
    if not check:
        return {}
    z = check.get("zaehler") or {}
    out = {"fehler": int(z.get("fehler") or 0), "warnungen": int(z.get("warnung") or 0),
           "pruefung": check.get("zusammenfassung") or ""}
    if check.get("state") not in (None, "done"):
        out["pruefung_zustand"] = check.get("state")
    return out


def pruef_daten(check: dict[str, Any] | None) -> dict[str, Any] | None:
    """Prüfergebnis für ``daten`` (Befunde ohne Geometrie)."""
    if not check:
        return None
    befunde = [{k: b.get(k) for k in ("id", "art", "teile", "schwere", "text") if b.get(k) is not None}
               for b in check.get("befunde") or []]
    return {"state": check.get("state"), "zusammenfassung": check.get("zusammenfassung") or "",
            "zaehler": check.get("zaehler") or {}, "befunde": befunde[:200]}


def stueckliste_daten(bom: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(bom, dict):
        return None
    zeilen = []
    for ln in bom.get("lines") or []:
        zeilen.append({k: ln.get(k) for k in ("pos", "art", "stock_id", "benennung", "material", "laenge", "gehrung",
                                              "masse_text", "anzahl", "kg", "preis", "teile", "eigenteil")})
    return {"lines": zeilen, "totals": bom.get("totals") or {}}


def daten_aus_teilen(teile: list[tuple[str, str, dict[str, Any]]], *, bom: dict[str, Any] | None,
                     params: dict[str, Any] | None, pruefung: dict[str, Any] | None = None,
                     schritte: list[str] | None = None) -> dict[str, Any]:
    """``schritte``: Texte der step()-Aufrufe des Laufs (für den Titel der Version; ältere Daten haben sie nicht)."""
    liste = [teil_daten(n, k, h) for n, k, h in teile]
    out = {"format": 1, "teile": liste, "stueckliste": stueckliste_daten(bom), "params": dict(params or {}),
           "pruefung": pruef_daten(pruefung), "kennzahlen": kennzahlen(liste, bom, pruefung)}
    if schritte is not None:
        out["schritte"] = [str(x) for x in schritte]
    return out


def netz(header: dict[str, Any], payload: bytes) -> dict[str, np.ndarray]:
    a = unpack_part(header, payload)
    return {k: a[k] for k in NETZ_ARRAYS}


def _datei_name(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:28] + ".kvg"


def packe_netz(n: dict[str, np.ndarray]) -> bytes:
    pos = np.ascontiguousarray(n["positions"], dtype="<f4").reshape(-1, 3)
    nrm = np.ascontiguousarray(n["normals"], dtype="<f4").reshape(-1, 3)
    tri = np.ascontiguousarray(n["triangles"], dtype="<u4").reshape(-1, 3)
    ept = np.ascontiguousarray(n["edge_points"], dtype="<f4").reshape(-1, 3)
    eof = np.ascontiguousarray(n["edge_offsets"], dtype="<u4").reshape(-1)
    roh = pos.tobytes() + nrm.tobytes() + tri.tobytes() + ept.tobytes() + eof.tobytes()
    return MAGIC + struct.pack("<IIII", len(pos), len(tri), len(ept), len(eof)) + zlib.compress(roh, 1)


def entpacke_netz(data: bytes) -> dict[str, np.ndarray]:
    if data[:4] != MAGIC:
        raise ValueError("kein Netz des Versionsspeichers")
    nv, nt, ne, no = struct.unpack_from("<IIII", data, 4)
    roh = zlib.decompress(data[20:])
    o = 0

    def take(dtype: str, n: int, per: int) -> np.ndarray:
        nonlocal o
        arr = np.frombuffer(roh, dtype=dtype, count=n * per, offset=o)
        o += n * per * 4
        return arr.reshape(-1, per) if per > 1 else arr

    return {"positions": take("<f4", nv, 3), "normals": take("<f4", nv, 3), "triangles": take("<u4", nt, 3),
            "edge_points": take("<f4", ne, 3), "edge_offsets": take("<u4", no, 1)}


class Zwischenspeicher:
    """Daten und Netze der Versionen eines Projekts (``<projekt>/.kevcad/versionen``). Threadsicher."""

    def __init__(self, ordner: str | Path, max_bytes: int = MAX_GEOMETRIE_BYTES) -> None:
        self.ordner = Path(ordner)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    @property
    def daten_ordner(self) -> Path:
        return self.ordner / "daten"

    @property
    def geo_ordner(self) -> Path:
        return self.ordner / "geometrie"

    # -- Daten ---------------------------------------------------------------------------------------------------------

    def speichere_daten(self, nr: int, daten: dict[str, Any]) -> None:
        self.daten_ordner.mkdir(parents=True, exist_ok=True)
        ziel = self.daten_ordner / f"{nr}.json"
        tmp = ziel.with_name(f".{nr}.json.tmp")
        tmp.write_text(json.dumps(daten, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(ziel)

    def lade_daten(self, nr: int) -> dict[str, Any] | None:
        try:
            data = json.loads((self.daten_ordner / f"{nr}.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def hat_daten(self, nr: int) -> bool:
        return (self.daten_ordner / f"{nr}.json").is_file()

    # -- Netze ---------------------------------------------------------------------------------------------------------

    def hat_netz(self, key: str) -> bool:
        return (self.geo_ordner / _datei_name(key)).is_file()

    def speichere_netz(self, key: str, header: dict[str, Any], payload: bytes) -> bool:
        """Netz eines Teils ablegen, falls noch nicht da. True, wenn neu geschrieben."""
        ziel = self.geo_ordner / _datei_name(key)
        if ziel.is_file():
            return False
        self.geo_ordner.mkdir(parents=True, exist_ok=True)
        data = packe_netz(netz(header, payload))
        tmp = ziel.with_name("." + ziel.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(ziel)
        return True

    def lade_netz(self, key: str) -> dict[str, np.ndarray] | None:
        ziel = self.geo_ordner / _datei_name(key)
        try:
            data = ziel.read_bytes()
            os.utime(ziel)  # zuletzt benutzt (für das Begrenzen)
            return entpacke_netz(data)
        except (OSError, ValueError, zlib.error, struct.error):
            return None

    def hat_alle_netze(self, daten: dict[str, Any]) -> bool:
        return all(self.hat_netz(t["key"]) for t in daten.get("teile") or [] if t.get("key"))

    def begrenze(self) -> int:
        """Netze über ``max_bytes``: die am längsten unbenutzten zuerst löschen. Rückgabe: gelöschte Dateien."""
        with self._lock:
            try:
                dateien = [(p, p.stat()) for p in self.geo_ordner.glob("*.kvg")]
            except OSError:
                return 0
            summe = sum(st.st_size for _, st in dateien)
            if summe <= self.max_bytes:
                return 0
            weg = 0
            for p, st in sorted(dateien, key=lambda x: x[1].st_mtime):
                if summe <= self.max_bytes * 0.8:
                    break
                try:
                    p.unlink()
                    summe -= st.st_size
                    weg += 1
                except OSError:
                    pass
            return weg

    def entferne_verwaiste(self) -> int:
        """Netze, die keine gespeicherte Version mehr braucht."""
        with self._lock:
            gebraucht = set()
            for p in self.daten_ordner.glob("*.json"):
                try:
                    for t in json.loads(p.read_text(encoding="utf-8")).get("teile") or []:
                        if t.get("key"):
                            gebraucht.add(_datei_name(t["key"]))
                except (OSError, json.JSONDecodeError, AttributeError):
                    continue
            weg = 0
            for p in self.geo_ordner.glob("*.kvg"):
                if p.name not in gebraucht:
                    try:
                        p.unlink()
                        weg += 1
                    except OSError:
                        pass
            return weg
