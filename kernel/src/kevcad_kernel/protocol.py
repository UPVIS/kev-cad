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


# ---------------------------------------------------------------------------------------------------------------------
# Bestand je Projekt (BESTAND.md): Nachrichten ohne Nutzlast

BESTAND_NACHRICHTEN: dict[str, tuple[str, ...]] = {
    # type: Pflichtfelder (außer type/seq)
    "BESTAND": ("bestand", "buchungen", "stand"),
    "BESTAND_REQ": ("id",),
    "BESTAND_SAVE": ("id",),  # dazu posten_id und posten oder einstellungen
    "GEBAUT_REQ": ("id", "run"),
    "BUCHUNG_RUECKGAENGIG": ("id", "buchung"),
}


def pack_bestand(*, bestand: dict[str, Any] | None, buchungen: list[dict[str, Any]], stand: str | None,
                 datei: str | None = None, fehler: str | None = None, reply_to: str | None = None,
                 seq: int = 0) -> dict[str, Any]:
    """Kopf der Nachricht BESTAND: Inhalt der Projektdatei (null ohne Projekt oder bei kaputter Datei, dann mit
    ``fehler``), die letzten Buchungen (neueste zuerst, je mit ``zusammenfassung`` und ``rueckgaengig_durch``), Stand als
    ISO-Zeit; ``datei`` (Pfad) und ``fehler`` sind additiv."""
    header: dict[str, Any] = {"type": "BESTAND", "seq": seq, "bestand": bestand, "buchungen": list(buchungen),
                              "stand": stand, "datei": datei, "fehler": fehler}
    if reply_to:
        header["reply_to"] = reply_to
    return header


def check_bestand_message(header: dict[str, Any]) -> list[str]:
    """Fehlende Pflichtfelder einer Bestandsnachricht (leer = vollständig); für Tests und den Ersatz-Kernel."""
    kind = header.get("type")
    need = BESTAND_NACHRICHTEN.get(str(kind))
    if need is None:
        return [f"{kind!r} ist keine Bestandsnachricht"]
    missing = [k for k in need if k not in header]
    if kind == "BESTAND_SAVE" and "einstellungen" not in header and not ("posten_id" in header and "posten" in header):
        missing.append("posten_id und posten oder einstellungen")
    if kind == "BESTAND" and isinstance(header.get("buchungen"), list):
        for b in header["buchungen"]:
            for key in ("id", "zeit", "art", "aenderungen", "zusammenfassung", "rueckgaengig_durch"):
                if key not in b:
                    missing.append(f"buchungen[].{key}")
    return missing
