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
