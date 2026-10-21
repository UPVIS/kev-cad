"""Referenz-Implementierung des Protokolls zwischen Kernel und App (siehe PROTOCOL.md).

Rahmen: u32 LE Kopflänge · JSON · u32 LE Nutzlastlänge · Nutzlast. Diese Datei ist der Maßstab für den Swift-Decoder in
KevCADCore; Änderungen nur zusammen mit PROTOCOL.md, den Testdateien und dem Swift-Decoder.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any

import numpy as np

PROTOCOL_VERSION = 1

# Reihenfolge und Typen der Arrays in der Nutzlast von PART_UPSERT
PART_ARRAYS: tuple[tuple[str, str, str, int], ...] = (
    # (Name, dtype, counts-Schlüssel, Werte je Eintrag)
    ("positions", "<f4", "vert", 3),
    ("normals", "<f4", "vert", 3),
    ("triangles", "<u4", "tri", 3),
    ("tri_face", "<i4", "tri", 1),
    ("edge_points", "<f4", "epts", 3),
    ("edge_offsets", "<u4", "edge", 1),  # edge + 1 Einträge, siehe _array_len
    ("vertices", "<f4", "vtx", 3),
)


def _array_len(name: str, counts: dict[str, int]) -> int:
    key = next(k for n, _, k, _ in PART_ARRAYS if n == name)
    per = next(p for n, _, _, p in PART_ARRAYS if n == name)
    n = counts[key] * per
    return n + 1 if name == "edge_offsets" else n


def encode_frame(header: dict[str, Any], payload: bytes = b"") -> bytes:
    head = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(head)) + head + struct.pack("<I", len(payload)) + payload


class FrameReader:
    """Setzt Rahmen aus einem Bytestrom zusammen: ``feed(daten)`` liefert alle vollständigen Rahmen."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[dict[str, Any], bytes]]:
        self._buf += data
        out: list[tuple[dict[str, Any], bytes]] = []
        while True:
            if len(self._buf) < 4:
                return out
            hlen = struct.unpack_from("<I", self._buf, 0)[0]
            if len(self._buf) < 8 + hlen:
                return out
            plen = struct.unpack_from("<I", self._buf, 4 + hlen)[0]
            end = 8 + hlen + plen
            if len(self._buf) < end:
                return out
            header = json.loads(bytes(self._buf[4:4 + hlen]).decode("utf-8"))
            payload = bytes(self._buf[8 + hlen:end])
            del self._buf[:end]
            out.append((header, payload))


@dataclass
class PartGeometry:
    """Geometrie eines Teils, wie sie über PART_UPSERT reist."""

    positions: np.ndarray  # (vert, 3) float32
    normals: np.ndarray  # (vert, 3) float32
    triangles: np.ndarray  # (tri, 3) uint32
    tri_face: np.ndarray  # (tri,) int32
    edge_points: np.ndarray  # (epts, 3) float32
    edge_offsets: np.ndarray  # (edge + 1,) uint32
    vertices: np.ndarray  # (vtx, 3) float32
    faces: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "vert": int(len(self.positions)),
            "tri": int(len(self.triangles)),
            "face": int(len(self.faces)) if self.faces else int(self.tri_face.max() + 1 if len(self.tri_face) else 0),
            "edge": int(len(self.edge_offsets) - 1),
            "epts": int(len(self.edge_points)),
            "vtx": int(len(self.vertices)),
        }


def pack_part(
    *,
    run: int,
    name: str,
    geometry: PartGeometry,
    color: tuple[float, float, float, float] | list[float],
    bbox: dict[str, list[float]],
    props: dict[str, Any],
    material: str | None = None,
    seq: int = 0,
) -> tuple[dict[str, Any], bytes]:
    """Baut Kopf und Nutzlast eines PART_UPSERT."""
    g = geometry
    arrays = {
        "positions": np.ascontiguousarray(g.positions, dtype="<f4"),
        "normals": np.ascontiguousarray(g.normals, dtype="<f4"),
        "triangles": np.ascontiguousarray(g.triangles, dtype="<u4"),
        "tri_face": np.ascontiguousarray(g.tri_face, dtype="<i4"),
        "edge_points": np.ascontiguousarray(g.edge_points, dtype="<f4"),
        "edge_offsets": np.ascontiguousarray(g.edge_offsets, dtype="<u4"),
        "vertices": np.ascontiguousarray(g.vertices, dtype="<f4"),
    }
    counts = g.counts
    for arr_name, _, _, _ in PART_ARRAYS:
        expected = _array_len(arr_name, counts)
        if arrays[arr_name].size != expected:
            raise ValueError(f"{name}: {arr_name} hat {arrays[arr_name].size} Werte, erwartet {expected}")
    header: dict[str, Any] = {
        "type": "PART_UPSERT",
        "seq": seq,
        "run": run,
        "name": name,
        "color": [float(c) for c in color],
        "material": material,
        "bbox": bbox,
        "props": props,
        "counts": counts,
        "faces": g.faces,
        "edges": g.edges,
        "transform": None,
    }
    payload = b"".join(arrays[n].tobytes() for n, _, _, _ in PART_ARRAYS)
    return header, payload


CONSTRAINT_ITEM_FIELDS = ("id", "art", "gruppe", "symbol", "text", "teile", "stand", "soll", "ist", "abweichung",
                          "einheit", "punkte", "zeile", "datei", "loesung")
CONSTRAINT_FINDING_FIELDS = ("art", "pruefung", "teile", "schwere", "text", "soll", "ist", "wert", "einheit", "ort",
                             "loesung", "bedingung", "unterart", "zeile")


def constraints_example(run: int = 3) -> dict[str, Any]:
    """Beispiel der Nachricht CONSTRAINTS (PROTOCOL.md, Abschnitt Zwangsbedingungen); Grundlage der Testdatei."""
    return {
        "type": "CONSTRAINTS", "run": run,
        "items": [
            {"id": "b1", "art": "auf", "gruppe": "montage", "symbol": "auf",
             "text": "Rollwagen/Rahmen.unten auf Rollwagen/Lenkrolle 1/Gabel.oben",
             "teile": ["Rollwagen/Rahmen", "Rollwagen/Lenkrolle 1/Gabel"], "stand": "erfuellt",
             "soll": "Abstand 0 mm, Flächen gegenüber", "ist": "Abstand 0 mm", "abweichung": 0.0, "einheit": "mm",
             "punkte": [[255.0, -335.0, 120.0], [255.0, -335.0, 120.0]], "zeile": 57, "datei": "model.py",
             "loesung": None},
            {"id": "b2", "art": "in_bohrung", "gruppe": "montage", "symbol": "in_bohrung",
             "text": "Schraube in Platte.Bohrung Ø6", "teile": ["Schraube", "Platte"], "stand": "verletzt",
             "schwere": "fehler", "soll": "Durchgang ≥ Ø 8 mm für M8 (mittel Ø 9 mm)", "ist": "Ø 6 mm",
             "abweichung": -2.0, "einheit": "mm", "punkte": [[10.0, 0.0, 10.0], [10.0, 0.0, 5.0]], "zeile": 61,
             "datei": "model.py", "loesung": "Bohrung auf Ø 9 mm vergrößern (ISO 273 mittel) oder kleinere Schraube (M5)",
             "schraube": {"d": 8.0, "laenge": 30.0}, "gewinde": False},
            {"id": "b3", "art": "drehgelenk", "gruppe": "gelenk", "symbol": "drehgelenk",
             "text": "Klappe.Bohrung Ø6,4 dreht um Achse.achse", "teile": ["Klappe", "Achse"], "stand": "erfuellt",
             "soll": "Achsen deckungsgleich, Winkel 0°", "ist": "Versatz 0 mm", "abweichung": 0.0, "einheit": "mm",
             "punkte": [[-50.0, 0.0, 15.0]], "zeile": 70, "datei": "model.py", "loesung": None,
             "gelenk": "revolute", "wert": 0.0, "wert_einheit": "°", "bereich": [-60.0, 90.0],
             "achse": {"p": [-50.0, 0.0, 15.0], "d": [0.0, -1.0, 0.0]}, "anim_art": "dreh"},
            {"id": "p:wand", "art": "param", "gruppe": "mass", "symbol": "param", "text": "Parameter wand", "teile": [],
             "stand": "verletzt", "schwere": "fehler", "soll": "≥ 1,2", "ist": "0,8", "abweichung": -0.4, "einheit": "",
             "punkte": [], "zeile": 5, "datei": "model.py", "loesung": "wand mindestens 1,2 wählen (Grenze in Zeile 5)"},
        ],
        "teile": [
            {"name": "Rollwagen/Rahmen", "platziert": True, "frei": 0, "stand": "bestimmt", "bedingungen": ["b1"],
             "freiheitsgrade": [], "gelenke": [], "befestigt": True, "am_boden": True, "verbindungen": ["aufliegen"]},
            {"name": "Klappe", "platziert": True, "frei": 1, "stand": "unterbestimmt", "bedingungen": ["b3"],
             "freiheitsgrade": [{"art": "drehung", "richtung": [0.0, 1.0, 0.0], "punkt": [-50.0, 0.0, 15.0],
                                 "text": "Drehung um Y durch (−50; 0; 15)", "gelenk": True, "unkritisch": False},
                                {"art": "verschiebung", "richtung": [1.0, 0.0, 0.0], "text": "Verschiebung entlang X",
                                 "gelenk": False, "unkritisch": False}],
             "gelenke": ["Drehung um Y durch (−50; 0; 15)"], "befestigt": True, "am_boden": False,
             "verbindungen": ["drehgelenk"], "verletzt": 0},
        ],
        "bewegungen": [
            {"name": "drehgelenk Klappe", "art": "drehen", "quelle": "gelenk", "bedingung": "b3", "teile": ["Klappe"],
             "punkt": [-50.0, 0.0, 15.0], "richtung": [0.0, -1.0, 0.0], "von": -60.0, "bis": 90.0, "ist": 0.0,
             "schritte": 15, "frei": [[-10.0, 40.0]], "frei_um_ist": [-10.0, 40.0], "freiraum": 15.0,
             "kollisionen": [{"gegen": "Rahmen", "bewegt": "Klappe", "bereiche": [[-60.0, -20.0], [50.0, 60.0]],
                              "max_volumen": 841.7, "bei": -40.0, "ort": [-26.6, 0.0, 6.5], "schon_in_ruhe": False}],
             "eng": [], "geprueft_ms": 110.5, "teilweise": False},
        ],
        "befunde": [
            {"art": "bedingung", "pruefung": "bedingung", "teile": ["Schraube", "Platte"], "schwere": "fehler",
             "text": "Schraube in Platte.Bohrung Ø6: Ø 6 mm", "soll": "Durchgang ≥ Ø 8 mm für M8 (mittel Ø 9 mm)",
             "ist": "Ø 6 mm", "wert": -2.0, "einheit": "mm", "ort": [10.0, 0.0, 5.0],
             "loesung": "Bohrung auf Ø 9 mm vergrößern (ISO 273 mittel) oder kleinere Schraube (M5)",
             "bedingung": "b2", "unterart": "in_bohrung", "zeile": 61},
            {"art": "bedingung", "pruefung": "bewegungsraum", "teile": ["Klappe", "Rahmen"], "schwere": "fehler",
             "text": "drehgelenk Klappe: stößt bei -60° … -20°, 50° … 60° an Rahmen; frei -10° … 40°",
             "soll": "frei von -60° bis 90°", "ist": "Kollision bei -60° … -20°, 50° … 60°, frei -10° … 40°",
             "wert": 841.7, "einheit": "mm³", "ort": [-26.6, 0.0, 6.5], "loesung": "Platz schaffen: …",
             "bedingung": "b3", "unterart": "drehen", "zeile": 70},
            {"art": "bedingung", "pruefung": "freiheitsgrade", "teile": ["Klappe"], "schwere": "hinweis",
             "text": "Klappe ist unterbestimmt: 1 Freiheitsgrad frei (Verschiebung entlang X)", "soll": "",
             "ist": "1 frei", "wert": 1.0, "einheit": "", "ort": None, "loesung": "Lage entlang X festlegen",
             "bedingung": None, "unterart": None, "zeile": 70},
        ],
        "summe": {"gesamt": 4, "erfuellt": 2, "verletzt": 2, "ungeprueft": 0, "fehler": 3, "warnungen": 0,
                  "hinweise": 1, "bewegungen": 1},
        "pruef_ms": 14.2, "loese_ms": 3.1,
    }
def pack_check(*, run: int, state: str, ergebnis: dict[str, Any] | None = None,
               geometrie: list[tuple[np.ndarray, np.ndarray, np.ndarray]] | None = None, message: str | None = None,
               seq: int = 0) -> tuple[dict[str, Any], bytes]:
    """Baut Kopf und Nutzlast von CHECK (Prüfergebnis, PROTOCOL.md Abschnitt „Prüfung“). ``geometrie``: je
    Schnittkörper (Punkte (n, 3), Normalen (n, 3), Dreiecke (m, 3)); die Nutzlast reiht sie hintereinander."""
    erg = dict(ergebnis or {})
    teile: list[bytes] = []
    geo_kopf = []
    for i, (pos, nrm, tri) in enumerate(geometrie or []):
        p = np.ascontiguousarray(pos, dtype="<f4").reshape(-1, 3)
        n = np.ascontiguousarray(nrm, dtype="<f4").reshape(-1, 3)
        t = np.ascontiguousarray(tri, dtype="<u4").reshape(-1, 3)
        if len(n) != len(p):
            raise ValueError(f"Schnittkörper {i}: {len(p)} Punkte, aber {len(n)} Normalen")
        befund_id = next((b.get("id") for b in erg.get("befunde") or [] if b.get("geometrie") == i), None)
        geo_kopf.append({"befund": befund_id, "vert": int(len(p)), "tri": int(len(t))})
        teile += [p.tobytes(), n.tobytes(), t.tobytes()]
    header: dict[str, Any] = {
        "type": "CHECK",
        "seq": seq,
        "run": run,
        "state": state,
        "duration_ms": erg.get("dauer_ms"),
        "message": message,
        "zusammenfassung": erg.get("zusammenfassung") or "",
        "zaehler": erg.get("zaehler") or {"fehler": 0, "warnung": 0, "hinweis": 0},
        "befunde": list(erg.get("befunde") or []),
        "geometrie": geo_kopf,
    }
    for key in ("montage", "stand", "gewinde", "erlaubt"):
        if key in erg:
            header[key] = erg[key]
    return header, b"".join(teile)


def unpack_check(header: dict[str, Any], payload: bytes) -> list[dict[str, np.ndarray]]:
    """Gegenstück zu pack_check: die Schnittkörper aus der Nutzlast."""
    out = []
    offset = 0
    for g in header.get("geometrie") or []:
        nv, nt = int(g["vert"]), int(g["tri"])
        pos = np.frombuffer(payload, dtype="<f4", count=nv * 3, offset=offset).reshape(-1, 3)
        offset += nv * 12
        nrm = np.frombuffer(payload, dtype="<f4", count=nv * 3, offset=offset).reshape(-1, 3)
        offset += nv * 12
        tri = np.frombuffer(payload, dtype="<u4", count=nt * 3, offset=offset).reshape(-1, 3)
        offset += nt * 12
        out.append({"positions": pos, "normals": nrm, "triangles": tri})
    if offset != len(payload):
        raise ValueError(f"Nutzlast von CHECK hat {len(payload)} Byte, erwartet {offset}")
    return out


def unpack_part(header: dict[str, Any], payload: bytes) -> dict[str, np.ndarray]:
    """Gegenstück zu pack_part (für Tests und Werkzeuge)."""
    counts = header["counts"]
    out: dict[str, np.ndarray] = {}
    offset = 0
    for arr_name, dtype, _, per in PART_ARRAYS:
        n = _array_len(arr_name, counts)
        arr = np.frombuffer(payload, dtype=dtype, count=n, offset=offset)
        offset += n * 4
        out[arr_name] = arr.reshape(-1, per) if per == 3 else arr
    if offset != len(payload):
        raise ValueError(f"Nutzlast hat {len(payload)} Byte, erwartet {offset}")
    return out
