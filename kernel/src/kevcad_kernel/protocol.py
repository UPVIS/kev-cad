"""Referenz-Implementierung des Protokolls zwischen Kernel und App (siehe PROTOCOL.md).

Rahmen: u32 LE Kopflänge · JSON · u32 LE Nutzlastlänge · Nutzlast. Diese Datei ist der Maßstab für den Swift-Decoder in
KevCADCore; Änderungen nur zusammen mit PROTOCOL.md, den Testdateien und dem Swift-Decoder.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
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
CHECK_STATES = ("running", "done", "teilweise", "cancelled", "failed")


def pack_check(*, run: int, state: str, ergebnis: dict[str, Any] | None = None,
               geometrie: list[tuple[np.ndarray, np.ndarray, np.ndarray]] | None = None, message: str | None = None,
               seq: int = 0, im_hintergrund: list[str] | None = None,
               statik_im_hintergrund: list[str] | None = None) -> tuple[dict[str, Any], bytes]:
    """Baut Kopf und Nutzlast von CHECK (Prüfergebnis, PROTOCOL.md Abschnitt „Prüfung“). ``geometrie``: je
    Schnittkörper (Punkte (n, 3), Normalen (n, 3), Dreiecke (m, 3)); die Nutzlast reiht sie hintereinander.
    ``state`` "teilweise" (additiv, Prüftempo): Ergebnis steht, der Bewegungsraum wird noch fertig gerechnet;
    ``im_hintergrund`` nennt die offenen Wege, danach folgt dasselbe ``run`` mit "done". ``statik_im_hintergrund``
    (additiv, T34): Ablauf (S2) bzw. Festkörper (S3), die nach dem Lauf noch rechnen; ihre Befunde kommen nach."""
    if state not in CHECK_STATES:
        raise ValueError(f"CHECK: state {state!r} unbekannt")
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
    if im_hintergrund is not None:
        header["im_hintergrund"] = list(im_hintergrund)
    if statik_im_hintergrund:
        header["statik_im_hintergrund"] = list(statik_im_hintergrund)
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
# Phase 6: Dokumente (DOKUMENTE.md, Protokoll) – Zeichnungen
# ---------------------------------------------------------------------------------------------------------------------

LINIEN_REIHENFOLGE: tuple[str, ...] = ("sichtbar", "verdeckt", "mitte", "schnitt", "schraffur", "duenn", "nachbar",
                                       "bruch")


def pack_polylinien(gruppen: list[dict[str, list[Any]]],
                    reihenfolge: tuple[str, ...] = LINIEN_REIHENFOLGE) -> tuple[bytes, list[dict[str, int]]]:
    """Polylinien-Nutzlast (DOKUMENTE.md): je Gruppe (Ansicht), je Linienart in ``reihenfolge``: u32 Anzahl
    Polylinien, je Polylinie u32 Punktzahl und f32 x, y paarweise (little-endian). Liefert Nutzlast und je Gruppe die
    Anzahl Polylinien je Linienart (für ``geometrie[i].linien``)."""
    teile: list[bytes] = []
    zaehler: list[dict[str, int]] = []
    for linien in gruppen:
        z: dict[str, int] = {}
        for art in reihenfolge:
            ls = [np.asarray(pl, dtype="<f4").reshape(-1, 2) for pl in (linien.get(art) or []) if len(pl) >= 2]
            z[art] = len(ls)
            teile.append(struct.pack("<I", len(ls)))
            for pl in ls:
                teile.append(struct.pack("<I", len(pl)))
                teile.append(np.ascontiguousarray(pl, dtype="<f4").tobytes())
        zaehler.append(z)
    return b"".join(teile), zaehler


def unpack_polylinien(header: dict[str, Any], payload: bytes, feld: str = "geometrie") -> list[dict[str, Any]]:
    """Gegenstück zu pack_polylinien: je Eintrag von ``header[feld]`` ein Wörterbuch Linienart → Liste (n, 2)."""
    reihenfolge = header.get("linien_reihenfolge") or list(LINIEN_REIHENFOLGE)
    out = []
    off = 0
    for _ in header.get(feld) or []:
        linien: dict[str, Any] = {}
        for art in reihenfolge:
            (n,) = struct.unpack_from("<I", payload, off)
            off += 4
            ls = []
            for _k in range(n):
                (k,) = struct.unpack_from("<I", payload, off)
                off += 4
                ls.append(np.frombuffer(payload, dtype="<f4", count=2 * k, offset=off).reshape(-1, 2))
                off += 8 * k
            linien[art] = ls
        out.append(linien)
    if off != len(payload):
        raise ValueError(f"Polylinien-Nutzlast hat {len(payload)} Byte, gelesen {off}")
    return out


def pack_drawing(kopf: dict[str, Any], gruppen: list[dict[str, list[Any]]], *, reply_to: str | None = None,
                 seq: int = 0) -> tuple[dict[str, Any], bytes]:
    """Nachricht DRAWING: ``kopf`` enthält ``blatt``, ``geometrie`` (je Ansicht und zuletzt ``blatt`` für Rahmen und
    Schriftfeld; je Eintrag ``id``, ``art``, ``rahmen``), ``masse``, ``texte``, ``stand`` …; ``gruppen`` die Linien in
    derselben Reihenfolge wie ``geometrie``. Setzt ``linien`` (Anzahl je Linienart) und ``linien_reihenfolge``."""
    payload, zaehler = pack_polylinien(gruppen)
    geo = [dict(g) for g in kopf.get("geometrie") or []]
    if len(geo) != len(gruppen):
        raise ValueError(f"DRAWING: {len(geo)} Einträge in geometrie, aber {len(gruppen)} Liniengruppen")
    for g, z in zip(geo, zaehler):
        g["linien"] = z
    header = {"type": "DRAWING", "seq": seq, **{k: v for k, v in kopf.items() if k not in ("type", "seq")},
              "geometrie": geo, "linien_reihenfolge": list(LINIEN_REIHENFOLGE)}
    if reply_to is not None:
        header["reply_to"] = reply_to
    return header, payload


def docs_message(run: int, blaetter: list[dict[str, Any]], bauplan: dict[str, Any] | None = None,
                 seq: int = 0) -> dict[str, Any]:
    """Nachricht DOCS: Übersicht der Blätter (``id``, ``titel``, ``inhalt``, ``format``, ``verwaiste_masse``, dazu
    ``ausrichtung``, ``massstab``, ``masse``, ``stand``, ``hinweise``, ``pruefung``) und Zusammenfassung des Bauplans."""
    return {"type": "DOCS", "seq": seq, "run": run, "blaetter": blaetter, "bauplan": bauplan}


def drawing_create_message(rid: str, art: str = "teil", teile: list[str] | None = None, fmt: str | None = None,
                           seq: int = 0) -> dict[str, Any]:
    """Nachricht DRAWING_CREATE (App → Kernel, DOKUMENTE.md 1.2): Blätter anlegen wie ``zeichnung_erstellen``.
    ``teile`` weggelassen: alle gefertigten Teile und der Zusammenbau; ``format`` z. B. „A3 quer“. Antwort: ACK, danach
    DOCS mit ``reply_to``."""
    msg: dict[str, Any] = {"type": "DRAWING_CREATE", "seq": seq, "id": rid, "art": art}
    if teile:
        msg["teile"] = list(teile)
    if fmt:
        msg["format"] = fmt
    return msg


# Phase 6: Bauplan (DOKUMENTE.md, Abschnitt „Protokoll“; Strang P6-B)

# Linienarten der Strichbilder im Bauplan: die acht der Zeichnungen, dazu ``neu`` (neue Teile des Schritts,
# hervorgehoben) und ``pfeil`` (Einführpfeile). Die App zeichnet unbekannte Arten dünn durchgezogen.
# „kontext“ (Version 1.3): aufnehmendes Teil beim Bearbeiten, dünn und grau
BAUPLAN_LINIEN: tuple[str, ...] = (*LINIEN_REIHENFOLGE, "neu", "pfeil", "kontext")
BAUPLAN_FELD = (180.0, 120.0)


def pack_bauplan(bauplan: dict[str, Any], bilder: list[dict[str, Any]], *, run: int | None = None,
                 reply_to: str | None = None, stand: dict[str, Any] | None = None,
                 seq: int = 0) -> tuple[dict[str, Any], bytes]:
    """BAUPLAN: Kopf mit dem Inhalt von bauplan.json (samt Prüfung) und je Schritt ein Strichbild im Feld 180 × 120 mm
    wie ``geometrie`` einer Ansicht (``bilder``: ``{schritt, rahmen, massstab, linien}``, ``linien`` = Anzahl je
    Linienart), Nutzlast die Polylinien aller Bilder hintereinander (pack_polylinien mit ``BAUPLAN_LINIEN``)."""
    payload, zaehler = pack_polylinien([b.get("linien") or {} for b in bilder], BAUPLAN_LINIEN)
    kopf_bilder = []
    for b, z in zip(bilder, zaehler):
        kopf_bilder.append({"schritt": b.get("schritt"),
                            "rahmen": [float(x) for x in b.get("rahmen") or [0, 0, *BAUPLAN_FELD]],
                            "massstab": b.get("massstab"), "linien": z,
                            **({"fehler": b["fehler"]} if b.get("fehler") else {})})
    header: dict[str, Any] = {"type": "BAUPLAN", "seq": seq, "run": run, "bauplan": bauplan, "bilder": kopf_bilder,
                              "feld": list(BAUPLAN_FELD), "linien_reihenfolge": list(BAUPLAN_LINIEN),
                              "stand": stand or {}}
    if reply_to:
        header["reply_to"] = reply_to
    return header, payload


def unpack_bauplan(header: dict[str, Any], payload: bytes) -> list[dict[str, Any]]:
    """Gegenstück zu pack_bauplan: die Bilder mit ihren Linien (Linienart → Liste (n, 2)) statt der Anzahlen."""
    gruppen = unpack_polylinien(header, payload, feld="bilder")
    return [{**b, "linien": g} for b, g in zip(header.get("bilder") or [], gruppen)]


def bauplan_beispiel() -> dict[str, Any]:
    """Kleiner Bauplan wie in bauplan.json (Grundlage der Testdateien)."""
    befund = {"id": "bp1", "art": "werkzeugzugang", "teile": ["Halter/Schraube 1", "Halter/Deckel"],
              "schwere": "fehler", "schritt": "m-2", "ort": [10.0, 0.0, 30.0], "wert": {"volumen": 42.0},
              "text": "Werkzeug kommt schlecht an Schraube 1 (Innensechskant 5 mm): Deckel im Weg (42 mm³ im "
                      "Werkzeugraum).",
              "loesung": "Verbindungsmittel anbringen, bevor Halter/Deckel montiert wird (Schritt teilen)"}
    return {
        "version": 1, "titel": "Halter",
        "abschnitte": [
            {"art": "material", "titel": "Material", "schritte": [
                {"id": "m-1", "titel": "Normteile und Kleinteile", "text": "Schrauben abzählen.", "quelle": "auto",
                 "fest": False, "teile": ["Halter/Schraube 1"], "neu": [], "baugruppe": None,
                 "verbindungsmittel": [], "werkzeug": [], "bohrbild": [], "zuschnitt": [], "druck": None, "bild": None,
                 "pruefung": [], "anzahl": 1, "hinweise": [],
                 "material": [{"benennung": "Zylinderschraube ISO 4762 M6 × 20", "menge": 2, "einheit": "Stück",
                               "preis": 0.3, "quelle": "kaufen oder Bestand"}]}]},
            {"art": "zuschnitt", "titel": "Zuschnitt", "schritte": [
                {"id": "z-1", "titel": "Stange 1: 300 + 300 mm", "text": "Ablängen: 300 + 300 mm, Rest 394 mm.",
                 "quelle": "auto", "fest": False, "teile": ["Halter/Bein 1", "Halter/Bein 2"], "neu": [],
                 "baugruppe": None, "verbindungsmittel": [], "werkzeug": ["Metallkreissäge"], "bohrbild": [],
                 "zuschnitt": [{"stock_id": "vierkantrohr-en10219-40x40x3", "laenge": 300.0, "gehrung": [0, 0],
                                "anzahl": 2}],
                 "druck": None, "bild": None, "pruefung": [], "anzahl": 1, "hinweise": []}]},
            {"art": "bearbeiten", "titel": "Bearbeiten", "schritte": [
                {"id": "b-1", "titel": "2× Bein: 2 Bohrungen", "text": "Anreißen, körnen, bohren.", "quelle": "auto",
                 "fest": False, "teile": ["Halter/Bein 1", "Halter/Bein 2"], "neu": [], "baugruppe": None,
                 "verbindungsmittel": [], "werkzeug": ["Bohrer Ø 6,6", "Körner", "Entgrater"],
                 "bohrbild": [{"teil": "Halter/Bein 1", "bezug": {"teil": "Halter/Bein 1", "art": "bohrung",
                                                                  "signatur": {"typ": "kreis",
                                                                               "mitte": [25.0, 20.0, 0.0],
                                                                               "richtung": [0, 1, 0], "radius": 3.3,
                                                                               "laenge": 40.0},
                                                                  "merkmal": "bohrung:1", "ref": None},
                               "durchmesser": 6.6, "tiefe": None, "lage_mm": [25.0], "von": "Ende A (links)",
                               "senkung": None, "gewinde": None, "text": "Ø6,6", "art": "bohrung",
                               "richtung": [0.0, 1.0, 0.0]}],
                 "zuschnitt": [], "druck": None, "bild": None, "pruefung": [], "anzahl": 2, "hinweise": []}]},
            {"art": "drucken", "titel": "Drucken", "schritte": []},
            {"art": "montage", "titel": "Montage", "schritte": [
                {"id": "m-1g", "titel": "Bein 1 als Grundteil auflegen", "text": "Bein 1 als Grundteil hinstellen.",
                 "quelle": "auto", "fest": False, "teile": ["Halter/Bein 1"], "neu": ["Halter/Bein 1"],
                 "baugruppe": None, "verbindungsmittel": [], "werkzeug": [], "bohrbild": [], "zuschnitt": [],
                 "druck": None, "pruefung": [], "anzahl": 1, "hinweise": [],
                 "einbau": [{"name": "Halter/Bein 1", "art": "teil", "teile": ["Halter/Bein 1"],
                             "haupt": "Halter/Bein 1", "richtung": None, "zuerst": None, "weg": 0.0,
                             "aufbocken": 0.0, "grundteil": True, "erzwungen": False, "sperrer": []}],
                 "bild": {"kamera": {"rotation": [0.2798, -0.1159, -0.3647, 0.8805], "pivot": [0.0, 0.0, 150.0],
                                     "distance": 900.0, "ortho": True},
                          "ansicht": {"richtung": [0.57735, 0.57735, -0.57735], "oben": [0.40825, 0.40825, 0.8165]},
                          "explosion": {}, "pfeile": [], "hervorheben": ["Halter/Bein 1"], "kontext": [],
                          "sichtbarkeit": {}, "quelle": "auto"}},
                {"id": "m-2", "titel": "Deckel einbauen", "text": "Deckel von oben einsetzen, auf Bein 1 legen. 2 × "
                 "Zylinderschraube ISO 4762 M6 × 20 ansetzen und anziehen.", "quelle": "agent", "fest": True,
                 "teile": ["Halter/Deckel", "Halter/Schraube 1"], "neu": ["Halter/Deckel", "Halter/Schraube 1"],
                 "baugruppe": None,
                 "verbindungsmittel": [{"id": "schraube-iso4762-m6", "benennung": "Zylinderschraube ISO 4762 M6 × 20",
                                        "laenge": 20.0, "anzahl": 1, "geschaetzt": False}],
                 "werkzeug": ["Innensechskant 5 mm"], "bohrbild": [], "zuschnitt": [], "druck": None,
                 "pruefung": [befund], "anzahl": 1, "hinweise": ["Schraube erst handfest, dann über Kreuz anziehen"],
                 "einbau": [{"name": "Halter/Deckel", "art": "teil", "teile": ["Halter/Deckel"],
                             "haupt": "Halter/Deckel", "richtung": [0.0, 0.0, -1.0], "zuerst": None, "weg": 25.0,
                             "aufbocken": 0.0, "grundteil": False, "erzwungen": False, "sperrer": []}],
                 "bild": {"kamera": {"rotation": [0.2798, -0.1159, -0.3647, 0.8805], "pivot": [0.0, 0.0, 150.0],
                                     "distance": 900.0, "ortho": True},
                          "ansicht": {"richtung": [0.57735, 0.57735, -0.57735], "oben": [0.40825, 0.40825, 0.8165]},
                          "explosion": {"Halter/Deckel": [0.0, 0.0, 25.0], "Halter/Schraube 1": [0.0, 0.0, 47.5]},
                          "pfeile": [{"teil": "Halter/Deckel", "richtung": [0.0, 0.0, -1.0],
                                      "von": [0.0, 0.0, 330.0], "nach": [0.0, 0.0, 305.0]}],
                          "hervorheben": ["Halter/Deckel", "Halter/Schraube 1"], "kontext": ["Halter/Bein 1"],
                          "sichtbarkeit": {"Halter/Deckel": 0.97, "Halter/Schraube 1": 0.62}, "quelle": "auto"}}]}],
        "vorher": [{"a": "m-1g", "b": "m-2", "grund": "Deckel wird an Bein 1 befestigt (schraube)", "quelle": "auto",
                    "teile": ["Halter/Bein 1", "Halter/Deckel"]},
                   {"a": "m-1g", "b": "m-2", "grund": "erst das Gestell ausrichten", "quelle": "kevin"}],
        "umfang": {"ohne": ["Umgebung"]},
        "stand": {"run": 3, "erzeugt": "2026-10-22T21:00:00", "gesamt_ms": 812.5, "verbinde": True},
    }


# Phase 6: Dokumente exportieren (DOKUMENTE.md, Anhang „Export“; Strang P6-A2). Das PDF baut die App.

DOC_EXPORT_BAUSTEINE: tuple[str, ...] = ("deckblatt", "produktbild", "stueckliste", "teileliste", "einkaufsliste",
                                         "zuschnitt", "druck", "zeichnungen", "bauplan")  # produktbild: Phase 7


def doc_export_req(bausteine: list[dict[str, Any]], *, ziel: str | None, drucken: bool = False,
                   format: str | None = None, ausrichtung: str | None = None,  # noqa: A002
                   vorlage: str | None = None, id: str | None = None, seq: int = 0) -> dict[str, Any]:  # noqa: A002
    """Kopf von DOC_EXPORT_REQ (Kernel → App): ``bausteine`` je ``{art, spalten?, auswahl?}`` in der gewünschten
    Reihenfolge, ``ziel`` (absoluter Pfad der .pdf oder None nur zum Drucken), ``drucken``, Papier der Berichtsseiten
    (``format`` A4/A3, ``ausrichtung`` hoch/quer, None = Vorgabe der App), ``vorlage`` (Name einer Vorlage der App)."""
    h: dict[str, Any] = {"type": "DOC_EXPORT_REQ", "seq": seq, "bausteine": [dict(b) for b in bausteine],
                         "ziel": ziel, "drucken": bool(drucken), "format": format, "ausrichtung": ausrichtung,
                         "vorlage": vorlage}
    if id is not None:
        h["id"] = id
    return h


def check_doc_export_res(header: dict[str, Any]) -> list[str]:
    """Fehlende Pflichtfelder von DOC_EXPORT_RES (App → Kernel): ``reply_to``, ``ok``, ``pfad``, ``seiten``, ``fehler``
    (additiv: ``bausteine`` je ``{art, seiten}``, ``formate``, ``gedruckt``, ``hinweise``, ``ms``)."""
    if header.get("type") != "DOC_EXPORT_RES":
        return [f"{header.get('type')!r} ist nicht DOC_EXPORT_RES"]
    return [k for k in ("reply_to", "ok", "pfad", "seiten", "fehler") if k not in header]


# Bestand je Projekt (BESTAND.md): Nachrichten ohne Nutzlast

BESTAND_NACHRICHTEN: dict[str, tuple[str, ...]] = {
    # type: Pflichtfelder (außer type/seq)
    "BESTAND": ("bestand", "buchungen", "stand"),
    "BESTAND_REQ": ("id",),
    "BESTAND_SAVE": ("id",),  # dazu posten_id und posten oder einstellungen
    "GEBAUT_REQ": ("id", "run"),
    "BUCHUNG_RUECKGAENGIG": ("id", "buchung"),
    # Strang „Rest Druck“: Knopf „Gedruckt“ (wie MCP gedruckt_buchen); platten leer = alle noch nicht gebuchten,
    # spule optional (Kennung zuerst), run optional (Lauf der Druckvorschau), grund
    "GEDRUCKT_REQ": ("id",),
}


def pack_bestand(*, bestand: dict[str, Any] | None, buchungen: list[dict[str, Any]], stand: str | None,
                 datei: str | None = None, fehler: str | None = None, reply_to: str | None = None,
                 seq: int = 0, gebaut_filament: dict[str, Any] | None = None) -> dict[str, Any]:
    """Kopf der Nachricht BESTAND: Inhalt der Projektdatei (null ohne Projekt oder bei kaputter Datei, dann mit
    ``fehler``), die letzten Buchungen (neueste zuerst, je mit ``zusammenfassung`` und ``rueckgaengig_durch``), Stand als
    ISO-Zeit; ``datei`` (Pfad) und ``fehler`` sind additiv. ``gebaut_filament`` (Strang „Bestand Stufe 2“, additiv, nur
    wenn das Projekt Filament führt): was „Gebaut“ jetzt vom Filament abbuchen würde (BESTAND.md, „Filament“)."""
    header: dict[str, Any] = {"type": "BESTAND", "seq": seq, "bestand": bestand, "buchungen": list(buchungen),
                              "stand": stand, "datei": datei, "fehler": fehler}
    if gebaut_filament is not None:
        header["gebaut_filament"] = gebaut_filament
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
    spule = "spule" in header or header.get("filament_fuehren") is True  # Strang „Bestand Stufe 2“, additiv
    if (kind == "BESTAND_SAVE" and "einstellungen" not in header and not spule
            and not ("posten_id" in header and "posten" in header)):
        missing.append("posten_id und posten, einstellungen, spule oder filament_fuehren")
    if kind == "BESTAND" and isinstance(header.get("buchungen"), list):
        for b in header["buchungen"]:
            for key in ("id", "zeit", "art", "aenderungen", "zusammenfassung", "rueckgaengig_durch"):
                if key not in b:
                    missing.append(f"buchungen[].{key}")
    return missing


# Freigabe im Projektfenster (Strang „Feinschliff 2“, PROTOCOL.md Abschnitt „Freigabe im Projektfenster“, additiv)

FREIGABE_NACHRICHTEN: dict[str, tuple[str, ...]] = {
    "FREIGABE_ANFRAGE": ("id", "anfrage", "eintraege", "grund"),  # Kernel → App, Antwort ACK
    "FREIGABE_GESCHLOSSEN": ("anfrage", "freigegeben", "abgelehnt", "offen"),  # App → Kernel, ohne Antwort
}


def check_freigabe_message(header: dict[str, Any]) -> list[str]:
    """Fehlende oder falsche Felder einer Freigabe-Nachricht (leer = gültig)."""
    kind = header.get("type")
    need = FREIGABE_NACHRICHTEN.get(str(kind))
    if need is None:
        return [f"{kind!r} ist keine Freigabe-Nachricht"]
    out = [k for k in need if k not in header]
    if kind == "FREIGABE_ANFRAGE":
        for i, e in enumerate(header.get("eintraege") or []):
            if not isinstance(e, dict) or not e.get("id") or e.get("kind") not in ("teil", "material"):
                out.append(f"eintraege[{i}]: id und kind (teil oder material) nötig")
    else:
        for k in ("freigegeben", "abgelehnt", "offen"):
            if k in header and not isinstance(header[k], list):
                out.append(f"{k} muss eine Liste sein")
    return out


def freigabe_beispiel() -> tuple[dict[str, Any], dict[str, Any]]:
    """Beispiel für Testdateien: Anfrage (Kernel → App) und Meldung beim Schließen (App → Kernel)."""
    anfrage = {"type": "FREIGABE_ANFRAGE", "id": "k-7", "anfrage": "F-0001", "grund": "Für die Lenksperren am Kugelschieber",
               "eintraege": [{"id": "rohr-alfer-16x1", "kind": "teil", "name": "ALFER-Rundrohr 16 × 1", "art": "rohr",
                              "ebene": "eigen"},
                             {"id": "petg-cf", "kind": "material", "name": "PETG-CF", "art": "material",
                              "ebene": "eigen"}]}
    geschlossen = {"type": "FREIGABE_GESCHLOSSEN", "anfrage": "F-0001", "freigegeben": ["rohr-alfer-16x1"],
                   "abgelehnt": [], "offen": ["petg-cf"]}
    return anfrage, geschlossen


# Phase 3: Zukaufteile (PROTOCOL.md, Abschnitt „Phase 3“)

ZUKAUF_ZUSTAENDE: tuple[str, ...] = ("angelegt", "wartet_auf_cad", "importiert", "fehler")


def zukauf_status(teil_id: str, zustand: str, text: str, *, cad_links: list[dict[str, str]] | None = None,
                  erwartet: list[str] | None = None, name: str | None = None) -> dict[str, Any]:
    """Kopf einer ``ZUKAUF_STATUS``-Nachricht (Kernel → App, unaufgefordert, ohne ``reply_to``). ``cad_links`` und
    ``erwartet`` nur bei ``wartet_auf_cad`` gefüllt; ``name`` ist der Anzeigename des Teils."""
    if zustand not in ZUKAUF_ZUSTAENDE:
        raise ValueError(f"zustand {zustand!r} unbekannt (erlaubt: {', '.join(ZUKAUF_ZUSTAENDE)})")
    wartet = zustand == "wartet_auf_cad"
    msg: dict[str, Any] = {"type": "ZUKAUF_STATUS", "id": teil_id, "zustand": zustand, "text": text,
                           "cad_links": [{"titel": str(c["titel"]), "url": str(c["url"])} for c in (cad_links or [])]
                           if wartet else [],
                           "erwartet": list(erwartet or []) if wartet else []}
    if name:
        msg["name"] = name
    return msg


# Versionen (PROTOCOL.md, Abschnitt „Versionen“): Netze für Geisterkörper (VERSION_VERGLEICH) und Vorschaubilder
# (VERSION_BILD_REQ). Je Eintrag hintereinander: positions f32 (vert × 3), normals f32 (vert × 3), triangles u32
# (tri × 3), edge_points f32 (epts × 3), edge_offsets u32 (edge + 1). Weltkoordinaten.

NETZ_ARRAYS: tuple[tuple[str, str, str, int], ...] = (
    ("positions", "<f4", "vert", 3),
    ("normals", "<f4", "vert", 3),
    ("triangles", "<u4", "tri", 3),
    ("edge_points", "<f4", "epts", 3),
    ("edge_offsets", "<u4", "edge", 1),
)


def pack_netze(eintraege: list[tuple[dict[str, Any], dict[str, np.ndarray]]]) -> tuple[list[dict[str, Any]], bytes]:
    """(Kopf je Netz, Nutzlast). Der Kopf ist der übergebene plus ``vert``, ``tri``, ``epts``, ``edge``."""
    koepfe: list[dict[str, Any]] = []
    teile: list[bytes] = []
    for meta, n in eintraege:
        pos = np.ascontiguousarray(n["positions"], dtype="<f4").reshape(-1, 3)
        nrm = np.ascontiguousarray(n["normals"], dtype="<f4").reshape(-1, 3)
        tri = np.ascontiguousarray(n["triangles"], dtype="<u4").reshape(-1, 3)
        ept = np.ascontiguousarray(n.get("edge_points", np.zeros((0, 3))), dtype="<f4").reshape(-1, 3)
        eof = np.ascontiguousarray(n.get("edge_offsets", np.zeros(1)), dtype="<u4").reshape(-1)
        if len(eof) == 0:
            eof = np.zeros(1, dtype="<u4")
        if len(nrm) != len(pos):
            raise ValueError(f"{meta}: {len(pos)} Punkte, aber {len(nrm)} Normalen")
        koepfe.append({**meta, "vert": int(len(pos)), "tri": int(len(tri)), "epts": int(len(ept)),
                       "edge": int(len(eof) - 1)})
        teile += [pos.tobytes(), nrm.tobytes(), tri.tobytes(), ept.tobytes(), eof.tobytes()]
    return koepfe, b"".join(teile)


def unpack_netze(koepfe: list[dict[str, Any]], payload: bytes) -> list[dict[str, np.ndarray] | None]:
    """Gegenstück zu pack_netze; None für Köpfe mit ``aus_szene`` (V2-5, das Netz hat die App)."""
    out = []
    offset = 0
    for k in koepfe:
        if k.get("aus_szene"):  # V2-5 (delta-1): Netz aus der Szene der App, ohne Anteil an der Nutzlast
            out.append(None)
            continue
        n: dict[str, np.ndarray] = {}
        for name, dtype, key, per in NETZ_ARRAYS:
            count = (int(k[key]) + 1 if name == "edge_offsets" else int(k[key])) * per
            arr = np.frombuffer(payload, dtype=dtype, count=count, offset=offset)
            offset += count * 4
            n[name] = arr.reshape(-1, per) if per == 3 else arr
        out.append(n)
    if offset != len(payload):
        raise ValueError(f"Nutzlast der Netze hat {len(payload)} Byte, erwartet {offset}")
    return out


# Druckvorschau (DRUCKVORSCHAU.md): Nachrichten ohne Nutzlast. Inhalt von PRINT_PREVIEW wie das Ergebnis des
# MCP-Werkzeugs druckvorschau (Summe, Platten, Teile mit Empfehlung, Hinweise, Zustand des Slicers).

DRUCK_NACHRICHTEN: dict[str, tuple[str, ...]] = {
    # type: Pflichtfelder (außer type/seq)
    "PRINT_PREVIEW": ("run", "stand", "drucker", "summe", "platten", "teile", "hinweise", "slicer"),
    "PRINT_PREVIEW_REQ": ("id",),
    "PRINT_SETTINGS": ("id",),  # dazu teil oder gruppe und einstellungen, zweck oder zuruecksetzen
    "PRINT_EXPORT_REQ": ("id", "platten", "ziel"),
    "PRINT_EXPORT_RES": ("reply_to", "ok", "pfad", "platten", "fehler"),
}
DRUCK_STAENDE: tuple[str, ...] = ("schaetzung", "slicer", "gemischt")
DRUCK_ZWECKE: tuple[str, ...] = ("zier", "funktion", "tragend", "bewegt", "aussen")
DRUCK_STUETZEN: tuple[str, ...] = ("keine", "baum", "normal")
DRUCK_MUSTER: tuple[str, ...] = ("gyroid", "grid", "cubic", "honeycomb", "rectilinear", "line", "concentric",
                                 "triangles", "zigzag", "crosshatch", "lightning")
DRUCK_SLICER_ZUSTAENDE: tuple[str, ...] = ("aus", "wartet", "rechnet", "fertig", "fehler")
DRUCK_SCHWEREN: tuple[str, ...] = ("fehler", "warnung", "hinweis")
DRUCK_HINWEIS_ARTEN: tuple[str, ...] = ("trocknen", "verzug", "material", "brim", "stuetzen", "ams", "duese", "risiko",
                                        "bauraum", "auflage", "festigkeit", "slicer", "platte")
DRUCK_EINSTELLUNGEN: tuple[str, ...] = ("schicht_mm", "waende", "decken", "boeden", "fuellung", "muster", "stuetzen",
                                        "brim", "ausrichtung")
# Paket B „druckfertig je Objekt“ (additiv, optional in teile[].einstellungen, auch in PRINT_SETTINGS erlaubt)
DRUCK_EINSTELLUNGEN_ERWEITERT: tuple[str, ...] = ("stuetzen_nur_platte", "stuetzen_abstand_mm", "brim_mm", "naht",
                                                  "buegeln", "oberflaeche", "loch_kompensation_mm",
                                                  "kontur_kompensation_mm", "elefantenfuss_mm")
DRUCK_SUMME_FELDER: tuple[str, ...] = ("platten", "zeit_s", "zeit_mit_wechsel_s", "kosten", "kosten_teile", "material")
DRUCK_MATERIAL_FELDER: tuple[str, ...] = ("material", "name", "g", "m", "kosten", "preis_kg", "preis_stand", "stand")
DRUCK_PLATTE_FELDER: tuple[str, ...] = ("nr", "zeit_s", "material", "stand", "teile", "auslastung")
DRUCK_PLATTENTEIL_FELDER: tuple[str, ...] = ("name", "gruppe", "x", "y", "drehung", "umriss")
DRUCK_TEIL_FELDER: tuple[str, ...] = ("gruppe", "name", "teile", "anzahl", "material", "zweck", "zweck_geschaetzt", "g",
                                      "m", "zeit_s", "stand", "abweichung", "einstellungen", "begruendung", "hinweise")
DRUCK_SLICER_FELDER: tuple[str, ...] = ("zustand", "fertig", "gesamt", "meldung")
# PRINT_EXPORT_RES.weggelassen[].grund (additiv): per ohne, nicht in teile, als später markiert
DRUCK_WEG_GRUENDE: tuple[str, ...] = ("ohne", "teile", "spaeter")


def pack_print_preview(vorschau: dict[str, Any], *, reply_to: str | None = None, seq: int = 0) -> dict[str, Any]:
    """Kopf von PRINT_PREVIEW (Kernel → App) aus dem Ergebnis der Druckvorschau (ohne ``ok``)."""
    h: dict[str, Any] = {"type": "PRINT_PREVIEW", "seq": seq,
                         **{k: v for k, v in vorschau.items() if k not in ("ok", "type", "seq", "reply_to")}}
    if reply_to:
        h["reply_to"] = reply_to
    return h


def print_preview_req(id: str, *, seq: int = 0) -> dict[str, Any]:  # noqa: A002
    return {"type": "PRINT_PREVIEW_REQ", "seq": seq, "id": id}


def print_settings(id: str, *, teil: str | None = None, gruppe: str | None = None,  # noqa: A002
                   einstellungen: dict[str, Any] | None = None, zweck: str | None = None, von: str | None = None,
                   zuruecksetzen: bool = False, seq: int = 0) -> dict[str, Any]:
    """Kopf von PRINT_SETTINGS (App → Kernel): feste Vorgabe je Teil (Name aus show) oder Gruppe (``g3``).
    ``einstellungen``: Teilmenge von DRUCK_EINSTELLUNGEN, ein Wert ``None`` nimmt die Vorgabe zurück;
    ``zuruecksetzen`` nimmt alle Vorgaben des Teils bzw. der Gruppe zurück; ``von`` ``kevin`` (Vorgabe) oder ``agent``."""
    h: dict[str, Any] = {"type": "PRINT_SETTINGS", "seq": seq, "id": id}
    if teil is not None:
        h["teil"] = teil
    if gruppe is not None:
        h["gruppe"] = gruppe
    if einstellungen is not None:
        h["einstellungen"] = dict(einstellungen)
    if zweck is not None:
        h["zweck"] = zweck
    if von is not None:
        h["von"] = von
    if zuruecksetzen:
        h["zuruecksetzen"] = True
    return h


def print_export_req(id: str, *, platten: list[int] | None = None, ziel: str | None = None,  # noqa: A002
                     teile: list[str] | None = None, ohne: list[str] | None = None,
                     filament: dict[str, str] | None = None, seq: int = 0) -> dict[str, Any]:
    """Kopf von PRINT_EXPORT_REQ (App → Kernel): ``platten`` leer = alle, ``ziel`` Pfad der .3mf oder None
    (dann ``<projekt>/output/<projekt>-druck.3mf``). Additiv ``teile`` (nur diese Teile) und ``ohne`` (diese
    nicht): Teilname, Baugruppen-Präfix, Gruppe "g3" oder Gruppenname; ``ohne`` gewinnt; nur gesetzt, wenn nicht leer.
    Additiv ``filament``: je Material die id eines Filaments aus Kevins Liste ({"petg": "<id>"}); ohne antwortet der
    Kernel mit ``PRINT_EXPORT_RES`` ``ok: false``, ``filament_frage: true`` und ``vorschlaege`` (nichts geschrieben)."""
    h: dict[str, Any] = {"type": "PRINT_EXPORT_REQ", "seq": seq, "id": id,
                         "platten": [int(p) for p in (platten or [])], "ziel": ziel}
    if teile:
        h["teile"] = [str(t) for t in teile]
    if ohne:
        h["ohne"] = [str(t) for t in ohne]
    if filament:
        h["filament"] = {str(k): str(v) for k, v in filament.items()}
    return h


def print_export_res(reply_to: str, *, ok: bool, pfad: str | None, platten: list[int],
                     fehler: str | None = None, seq: int = 0, **extra: Any) -> dict[str, Any]:
    """Kopf von PRINT_EXPORT_RES (Kernel → App); additiv ``hinweise``, ``ms``, ``geprueft`` (in Bambu Studio geladen),
    ``pfade``, ``dateien`` (je Datei auch ``objekte``: Objektnamen im 3MF), ``weggelassen`` ([{"name", "grund":
    ohne | teile | spaeter, "platte", "anzahl"}]) und ``leere_platten``."""
    return {"type": "PRINT_EXPORT_RES", "seq": seq, "reply_to": reply_to, "ok": bool(ok), "pfad": pfad,
            "platten": [int(p) for p in platten], "fehler": fehler, **extra}


def _fehlend(d: Any, felder: tuple[str, ...], wo: str) -> list[str]:
    if not isinstance(d, dict):
        return [f"{wo} ist kein Objekt"]
    return [f"{wo}.{k}" for k in felder if k not in d]


def check_druck_message(header: dict[str, Any]) -> list[str]:
    """Fehlende oder ungültige Felder einer Druckvorschau-Nachricht (leer = in Ordnung); für Tests und Ersatz-Kernel."""
    kind = header.get("type")
    need = DRUCK_NACHRICHTEN.get(str(kind))
    if need is None:
        return [f"{kind!r} ist keine Nachricht der Druckvorschau"]
    out = [k for k in need if k not in header]
    if kind == "PRINT_SETTINGS":
        if "teil" not in header and "gruppe" not in header:
            out.append("teil oder gruppe")
        if not any(k in header for k in ("einstellungen", "zweck", "zuruecksetzen")):
            out.append("einstellungen, zweck oder zuruecksetzen")
        if header.get("zweck") is not None and header["zweck"] not in DRUCK_ZWECKE:
            out.append(f"zweck {header['zweck']!r} unbekannt")
        for k in (header.get("einstellungen") or {}):
            if k not in DRUCK_EINSTELLUNGEN and k not in DRUCK_EINSTELLUNGEN_ERWEITERT:
                out.append(f"einstellungen.{k} unbekannt")
    if kind == "PRINT_EXPORT_REQ":  # additiv: Auswahl der Teile
        for k in ("teile", "ohne"):
            if k in header and not (isinstance(header[k], list) and all(isinstance(x, str) for x in header[k])):
                out.append(f"{k} ist keine Liste von Teilnamen")
        f = header.get("filament")
        if f is not None and not (isinstance(f, dict) and all(isinstance(k, str) and isinstance(v, str)
                                                              for k, v in f.items())):
            out.append("filament ist kein Objekt {material: Filament-id}")
    if kind == "PRINT_EXPORT_RES":
        for i, w in enumerate(header.get("weggelassen") or []):
            out += _fehlend(w, ("name", "grund", "platte", "anzahl"), f"weggelassen[{i}]")
            if isinstance(w, dict) and w.get("grund") not in DRUCK_WEG_GRUENDE:
                out.append(f"weggelassen[{i}].grund {w.get('grund')!r} unbekannt")
    if kind != "PRINT_PREVIEW" or out:
        return out
    if header["stand"] not in DRUCK_STAENDE:
        out.append(f"stand {header['stand']!r} unbekannt")
    s = header["summe"]
    out += _fehlend(s, DRUCK_SUMME_FELDER, "summe")
    if isinstance(s, dict):
        out += _fehlend(s.get("kosten_teile"), ("filament", "strom"), "summe.kosten_teile")
        for i, m in enumerate(s.get("material") or []):
            out += _fehlend(m, DRUCK_MATERIAL_FELDER, f"summe.material[{i}]")
    for i, p in enumerate(header["platten"]):
        out += _fehlend(p, DRUCK_PLATTE_FELDER, f"platten[{i}]")
        for j, t in enumerate((p or {}).get("teile") or []):
            out += _fehlend(t, DRUCK_PLATTENTEIL_FELDER, f"platten[{i}].teile[{j}]")
    for i, t in enumerate(header["teile"]):
        out += _fehlend(t, DRUCK_TEIL_FELDER, f"teile[{i}]")
        if isinstance(t, dict):
            out += _fehlend(t.get("einstellungen"), DRUCK_EINSTELLUNGEN, f"teile[{i}].einstellungen")
            if t.get("zweck") not in DRUCK_ZWECKE:
                out.append(f"teile[{i}].zweck {t.get('zweck')!r} unbekannt")
            st = (t.get("einstellungen") or {}).get("stuetzen")
            if st is not None and st not in DRUCK_STUETZEN:
                out.append(f"teile[{i}].einstellungen.stuetzen {st!r} unbekannt")
            for j, h in enumerate(t.get("hinweise") or []):
                out += _fehlend(h, ("schwere", "text", "art"), f"teile[{i}].hinweise[{j}]")
    for j, h in enumerate(header["hinweise"]):
        out += _fehlend(h, ("schwere", "text", "art"), f"hinweise[{j}]")
    out += _fehlend(header["slicer"], DRUCK_SLICER_FELDER, "slicer")
    if isinstance(header["slicer"], dict) and header["slicer"].get("zustand") not in DRUCK_SLICER_ZUSTAENDE:
        out.append(f"slicer.zustand {header['slicer'].get('zustand')!r} unbekannt")
    return out


def druckvorschau_beispiel(run: int = 12) -> dict[str, Any]:
    """Beispiel einer Druckvorschau (Kugelschieber, zwei Materialien, Slicer halb fertig) für Testdateien und den
    Ersatz-Kernel. Die Zahlen sind in sich stimmig (Summen, Meter aus Gramm, Kosten)."""
    import math

    g_je_m = {"petg": 1.27 * math.pi * 0.0875 ** 2 * 100, "pla": 1.24 * math.pi * 0.0875 ** 2 * 100}
    preis = {"petg": 17.0, "pla": 17.0}
    namen = {"petg": "PETG", "pla": "PLA"}
    strom_kwh, leistung_w, wechsel_s = 0.32, 150.0, 120

    def rechteck(x: float, y: float, w: float, h: float, drehung: int) -> list[list[float]]:
        if drehung % 180:
            w, h = h, w
        return [[round(x - w / 2, 2), round(y - h / 2, 2)], [round(x + w / 2, 2), round(y - h / 2, 2)],
                [round(x + w / 2, 2), round(y + h / 2, 2)], [round(x - w / 2, 2), round(y + h / 2, 2)]]

    gruppen = [
        # gruppe, name, teile, anzahl, material, zweck, geschätzt, g je Stück, s je Stück, stand, abweichung, Maße
        ("g1", "Stangenhalter (Druck)", ["Kugelschieber/Stangenhalter vorn links (Druck)",
                                         "Kugelschieber/Stangenhalter vorn rechts (Druck)",
                                         "Kugelschieber/Stangenhalter hinten links (Druck)",
                                         "Kugelschieber/Stangenhalter hinten rechts (Druck)"], 4, "petg", "tragend",
         False, 35.6, 4980, "slicer", 0.06, (62.0, 38.0)),
        ("g2", "Fangrolle (Druck)", ["Kugelschieber/Fangrolle (Druck)"], 2, "petg", "bewegt", False, 12.2, 2400,
         "schaetzung", None, (30.0, 30.0)),
        ("g3", "Lenksperre (Druck)", ["Kugelschieber/Lenksperre (Druck)"], 1, "petg", "funktion", True, 22.0, 3300,
         "slicer", -0.04, (24.0, 18.0)),
        ("g4", "Abdeckkappe (Druck)", ["Kugelschieber/Abdeckkappe 1 (Druck)", "Kugelschieber/Abdeckkappe 2 (Druck)",
                                       "Kugelschieber/Abdeckkappe 3 (Druck)", "Kugelschieber/Abdeckkappe 4 (Druck)",
                                       "Kugelschieber/Abdeckkappe 5 (Druck)", "Kugelschieber/Abdeckkappe 6 (Druck)"],
         6, "pla", "zier", False, 4.1, 900, "schaetzung", None, (22.0, 22.0)),
    ]
    einstellungen = {
        "tragend": {"schicht_mm": 0.2, "waende": 4, "decken": 5, "boeden": 4, "fuellung": 0.25, "muster": "gyroid",
                    "stuetzen": "keine", "brim": False},
        "bewegt": {"schicht_mm": 0.16, "waende": 4, "decken": 6, "boeden": 4, "fuellung": 0.3, "muster": "gyroid",
                   "stuetzen": "baum", "brim": False},
        "funktion": {"schicht_mm": 0.2, "waende": 3, "decken": 5, "boeden": 3, "fuellung": 0.2, "muster": "gyroid",
                     "stuetzen": "keine", "brim": True},
        "zier": {"schicht_mm": 0.16, "waende": 2, "decken": 6, "boeden": 4, "fuellung": 0.15, "muster": "grid",
                 "stuetzen": "keine", "brim": False},
    }
    prozess = {0.2: "0.20mm Standard @BBL P1P", 0.16: "0.16mm Optimal @BBL P1P"}
    filament = {"petg": "Bambu PETG Basic @BBL X1C", "pla": "Amazon Basics PLA"}
    filament_id = {"petg": "polymaker-polylite-petg-gelb", "pla": "amazon-basics-pla"}
    begruendung = {
        "tragend": ["tragend: 4 Wände, 25 % Gyroid (Kevins Regel für Funktionsteile: 3–4 Wände, 20–40 % Füllung)",
                    "Last längs der Schichten: liegend drucken, Zug und Biegung in der Schichtebene"],
        "bewegt": ["bewegt: 4 Wände und 30 % Gyroid für verschleißfeste Laufflächen, 0,16 mm für glattere Flächen",
                   "Baumstützen unter der Lauffläche: Stützen sauber entfernen, Lauffläche nacharbeiten"],
        "funktion": ["Zweck nicht angegeben, geschätzt als funktion: 3 Wände, 20 % Gyroid",
                     "Brim: kleine Auflage (ca. 120 mm²) bei 32 mm Höhe"],
        "zier": ["zier: 2 Wände, 15 % Grid, 0,16 mm für die Sichtflächen"],
    }
    hinweise = {
        "petg": [{"schwere": "hinweis", "text": "PETG vorher trocknen (65 °C, 12 h).", "art": "trocknen"}],
        "pla": [],
    }
    teile_out = []
    for (gid, name, teile, anzahl, mat, zweck, geschaetzt, g1, s1, stand, abw, _mass) in gruppen:
        e = einstellungen[zweck]
        h = list(hinweise[mat])
        if e["stuetzen"] != "keine":
            h.append({"schwere": "warnung", "text": "Braucht Stützen unter der Lauffläche (Fläche #f7, ca. 140 mm²): "
                      "Nacharbeit, ca. 1,1 g Stützmaterial je Stück.", "art": "stuetzen"})
        if e["brim"]:
            h.append({"schwere": "hinweis", "text": "Brim 5 mm: kleine Auflage bei großer Höhe, sonst kippt das Teil.",
                      "art": "brim"})
        g = round(g1 * anzahl, 1)
        kosten = round(g / 1000 * preis[mat], 2)
        teile_out.append({
            "gruppe": gid, "name": name, "teile": teile, "anzahl": anzahl, "material": mat, "zweck": zweck,
            "zweck_geschaetzt": geschaetzt, "g": g, "m": round(g / g_je_m[mat], 2), "zeit_s": s1 * anzahl,
            "kosten": kosten, "stand": stand, "abweichung": abw,
            "je_stueck": {"g": g1, "m": round(g1 / g_je_m[mat], 2), "zeit_s": s1},
            "einstellungen": {**e, "ausrichtung": "−Z-Seite unten (wie modelliert), Fläche #f3 liegt auf"},
            "fest": {"g1": ["waende"], "g3": ["fuellung"]}.get(gid, []),
            "fest_von": {"g1": {"waende": "kevin"}, "g3": {"fuellung": "agent"}}.get(gid, {}),
            "profil": {"prozess": prozess[e["schicht_mm"]], "filament": filament[mat]},
            "risiko": 0.12 if e["stuetzen"] != "keine" else 0.04,
            "begruendung": begruendung[zweck], "hinweise": h,
        })
        if gid == "g2":  # additiv (Paket B): druckfertig je Objekt mit Begründung je Einstellung
            teile_out[-1]["einstellungen"].update({
                "stuetzen_nur_platte": True, "stuetzen_abstand_mm": 0.25, "brim_mm": 0.0, "naht": "ausgerichtet",
                "buegeln": False, "oberflaeche": "monoton_linie", "loch_kompensation_mm": 0.0,
                "kontur_kompensation_mm": 0.0, "elefantenfuss_mm": 0.15})
            teile_out[-1]["begruendung_je"] = {
                "stuetzen_nur_platte": "nur von der Platte: Baumstützen wachsen um das Teil herum",
                "stuetzen_abstand_mm": "Abstand oben 0,25 mm statt 0,2: PETG haftet stark an Stützen (EW)",
                "loch_kompensation_mm": "X-Y-Lochkompensation 0: Zugabe steckt im Modell"}
    t = {x["gruppe"]: x for x in teile_out}
    # Platte 1 (PETG): 4 Halter, 2 Fangrollen, Lenksperre; Platte 2 (PLA): 6 Kappen
    platz1 = [("g1", t["g1"]["teile"][i], 60 + (i % 2) * 72, 60 + (i // 2) * 48, 0) for i in range(4)] + \
             [("g2", "Kugelschieber/Fangrolle (Druck)", 180, 60 + i * 40, 0) for i in range(2)] + \
             [("g3", "Kugelschieber/Lenksperre (Druck)", 180, 150, 90)]
    platz2 = [("g4", t["g4"]["teile"][i], 50 + (i % 3) * 32, 50 + (i // 3) * 32, 0) for i in range(6)]
    masse = {g[0]: g[11] for g in gruppen}
    platten = []
    for nr, (platz, stand) in enumerate(((platz1, "gemischt"), (platz2, "schaetzung")), start=1):
        mat = t[platz[0][0]]["material"]
        zeit = 0
        g = 0.0
        teile_p = []
        flaeche = 0.0
        for i, (gid, name, x, y, dreh) in enumerate(platz):
            je = t[gid]["je_stueck"]
            zeit += je["zeit_s"]
            g += je["g"]
            w, hh = masse[gid]
            flaeche += w * hh
            ersatz = gid == "g2" and i > 4
            teile_p.append({"name": name, "gruppe": gid, "x": float(x), "y": float(y), "drehung": dreh,
                            "umriss": rechteck(x, y, w, hh, dreh), "ersatz": ersatz})
        zeit += 35  # Start der Platte (Reinigungslinie)
        g = round(g, 1)
        kosten = round(g / 1000 * preis[mat], 2)
        platten.append({"nr": nr, "zeit_s": zeit, "stand": stand, "anordnung": "slicer" if nr == 1 else "schnell",
                        "material": [{"material": mat, "g": g, "m": round(g / g_je_m[mat], 2), "kosten": kosten}],
                        "kosten": kosten, "hoehe_mm": 32.0 if nr == 1 else 9.6, "teile": teile_p,
                        "auslastung": round(flaeche / (256 * 256 - 18 * 28), 3)})
    zeit_s = sum(p["zeit_s"] for p in platten)
    mit_wechsel = zeit_s + (len(platten) - 1) * wechsel_s
    material = []
    for mat in ("petg", "pla"):
        g = round(sum(p["material"][0]["g"] for p in platten if p["material"][0]["material"] == mat), 1)
        material.append({"material": mat, "name": namen[mat], "g": g, "m": round(g / g_je_m[mat], 2),
                         "kosten": round(g / 1000 * preis[mat], 2), "preis_kg": preis[mat], "preis_stand": "2026-10",
                         "stand": "gemischt" if mat == "petg" else "schaetzung",
                         # additiv (Strang „Druckexport 2“): angenommenes Filament aus Kevins Liste, woher
                         "filament_id": filament_id[mat], "filament_quelle": "zuletzt" if mat == "petg" else "standard"})
    filament_eur = round(sum(m["kosten"] for m in material), 2)
    strom = round(mit_wechsel / 3600 * leistung_w / 1000 * strom_kwh, 2)
    risiko = round(sum(x["risiko"] * x["kosten"] for x in teile_out), 2)
    return {
        "run": run, "stand": "gemischt", "drucker": "Bambu Lab P1P 0.4",
        "summe": {"platten": len(platten), "zeit_s": zeit_s, "zeit_mit_wechsel_s": mit_wechsel,
                  "kosten": round(filament_eur + strom + risiko, 2),
                  "kosten_teile": {"filament": filament_eur, "strom": strom, "risiko": risiko},
                  "material": material},
        "platten": platten,
        "teile": teile_out,
        "hinweise": [{"schwere": "hinweis", "text": "Zwei Materialien (PETG, PLA): je Material eigene Platten; ohne "
                      "AMS die Spule zwischen den Platten wechseln.", "art": "ams"}],
        "slicer": {"zustand": "rechnet", "fertig": 2, "gesamt": 4,
                   "meldung": "Bambu Studio 02.07.01.62: 2 von 4 Gruppen gerechnet", "version": "02.07.01.62"},
        "einstellungen": {"drucker": "p1p-0.4", "strompreis_kwh": strom_kwh, "leistung_w": leistung_w,
                          "plattenwechsel_s": wechsel_s, "slicer": True},
        "regler": False,
        "ms": 38.2,
        # additiv: Kevins Filamente der Materialien (Auswahl beim Export, druck/filamente.py)
        "filamente": [
            {"id": "polymaker-polylite-petg-gelb", "name": "Polymaker PolyLite PETG gelb (1,75 mm)", "material": "petg",
             "farbe": "gelb", "farbe_hex": "#F5C518", "preset": "Polymaker PolyLite PETG gelb (Kev CAD)",
             "basis": "PolyLite PETG @BBL P1P", "abweichungen": 0},
            {"id": "bambu-petg-basic", "name": "Bambu Lab PETG Basic (1,75 mm)", "material": "petg", "farbe": None,
             "farbe_hex": None, "preset": "Bambu Lab PETG Basic (Kev CAD)", "basis": "Bambu PETG Basic @BBL X1C",
             "abweichungen": 0, "offen": ["farbe"]},
            {"id": "amazon-basics-pla", "name": "Amazon Basics PLA (1,75 mm)", "material": "pla", "farbe": None,
             "farbe_hex": None, "preset": "Amazon Basics PLA (Kev CAD)", "basis": "Amazon Basics PLA",
             "abweichungen": 0}],
    }


# Drucken (Phase 8, DRUCKVORSCHAU.md „Drucken (Phase 8)“): Nachrichten ohne Nutzlast. Nie mit Seriennummer oder
# Zugangscode: PRINTER_CONFIG trägt nur den Eintrag aus drucker.json, PRINTER_STATUS nur eine gehashte Kennung.

DRUCKER_NACHRICHTEN: dict[str, tuple[str, ...]] = {
    "PRINTER_CONFIG": ("id", "drucker"),
    "PRINTER_STATUS_REQ": ("id",),
    "PRINTER_STATUS": ("konfiguriert", "verbindung", "meldung", "drucker", "weg", "wege", "steuern", "druck",
                       "temperaturen", "fehler", "kamera", "gefunden", "auftrag", "aktualisiert"),
    "PRINT_JOB_REQ": ("id", "platten", "weg", "bestaetigt"),
    "PRINT_JOB_RES": ("reply_to", "ok", "auftrag", "weg", "schritt", "datei", "platten", "fehler", "hinweise", "ms"),
    "PRINT_JOB_ASK": ("id", "auftrag", "platten", "weg", "von", "grund"),
    "PRINT_CONTROL": ("id", "aktion"),
}
DRUCKER_VERBINDUNGEN: tuple[str, ...] = ("aus", "verbindet", "verbunden", "getrennt", "fehler")
DRUCKER_WEGE: tuple[str, ...] = ("a", "b")
DRUCKER_MODI: tuple[str, ...] = ("cloud", "lan", "unbekannt")
DRUCK_ZUSTAENDE: tuple[str, ...] = ("unbekannt", "bereit", "vorbereiten", "druckt", "pausiert", "fertig",
                                    "fehlgeschlagen")
AUFTRAG_ZUSTAENDE: tuple[str, ...] = ("wartet", "slict", "bereit", "oeffnet", "geoeffnet", "laedt_hoch", "startet",
                                      "gestartet", "fehler", "verworfen")
AUFTRAG_SCHRITTE: tuple[str, ...] = ("vorbereitet", "geoeffnet", "gestartet")
DRUCKER_AKTIONEN: tuple[str, ...] = ("aktualisieren", "pause", "fortsetzen", "abbrechen", "verwerfen")
DRUCKER_EINTRAG_FELDER: tuple[str, ...] = ("id", "name", "modell", "ip", "weg", "status_lesen")
DRUCKER_FELDER: tuple[str, ...] = ("id", "name", "modell", "ip", "firmware", "modus", "entwicklermodus", "signal")
DRUCK_STATUS_FELDER: tuple[str, ...] = ("zustand", "gcode_state", "fortschritt", "schicht", "schichten", "restzeit_s",
                                        "aufgabe", "datei", "stufe", "geschwindigkeit")
AUFTRAG_FELDER: tuple[str, ...] = ("auftrag", "zustand", "weg", "platten", "fortschritt", "meldung", "datei", "von")
_GEHEIM = ("seriennummer", "zugangscode", "access_code", "serial", "passwort", "password")


def printer_config(id: str, drucker: dict[str, Any] | None, *, seq: int = 0) -> dict[str, Any]:  # noqa: A002
    return {"type": "PRINTER_CONFIG", "seq": seq, "id": id, "drucker": None if drucker is None else dict(drucker)}


def printer_status(status: dict[str, Any], *, reply_to: str | None = None, seq: int = 0) -> dict[str, Any]:
    h: dict[str, Any] = {"type": "PRINTER_STATUS", "seq": seq,
                         **{k: v for k, v in status.items() if k not in ("ok", "type", "seq", "reply_to")}}
    if reply_to:
        h["reply_to"] = reply_to
    return h


def print_job_req(id: str, *, platten: list[int] | None = None, weg: str = "a", bestaetigt: bool = False,  # noqa: A002
                  optionen: dict[str, Any] | None = None, auftrag: str | None = None,
                  filament: dict[str, str] | None = None, seq: int = 0) -> dict[str, Any]:
    """``filament`` (additiv, Strang „Rest Druck“): Kevins Filament je Material bzw. Farbklasse („petg“, „petg/gelb“)
    aus dem Dialog; ohne lehnt der Kernel ``bestaetigt: true`` ab."""
    h: dict[str, Any] = {"type": "PRINT_JOB_REQ", "seq": seq, "id": id, "platten": [int(p) for p in (platten or [])],
                         "weg": weg, "bestaetigt": bool(bestaetigt)}
    if optionen is not None:
        h["optionen"] = dict(optionen)
    if auftrag is not None:
        h["auftrag"] = auftrag
    if filament:
        h["filament"] = dict(filament)
    return h


def print_control(id: str, aktion: str, *, auftrag: str | None = None, seq: int = 0) -> dict[str, Any]:  # noqa: A002
    h: dict[str, Any] = {"type": "PRINT_CONTROL", "seq": seq, "id": id, "aktion": aktion}
    if auftrag is not None:
        h["auftrag"] = auftrag
    return h


def _geheimnisse(obj: Any, wo: str = "") -> list[str]:
    """Pfade von Feldern, deren Name nach Seriennummer oder Zugangscode klingt (dürfen nie in Nachrichten stehen)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in _GEHEIM:
                out.append(f"{wo}{k}")
            out += _geheimnisse(v, f"{wo}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _geheimnisse(v, f"{wo}[{i}].")
    return out


def check_drucker_message(header: dict[str, Any]) -> list[str]:
    """Fehlende oder ungültige Felder einer Drucker-Nachricht (leer = in Ordnung); Felder mit Geheimnissen sind immer
    ein Fehler."""
    kind = header.get("type")
    need = DRUCKER_NACHRICHTEN.get(str(kind))
    if need is None:
        return [f"{kind!r} ist keine Drucker-Nachricht"]
    out = [k for k in need if k not in header]
    out += [f"{p} darf nie in einer Nachricht stehen" for p in _geheimnisse(header)]
    if out:
        return out
    if kind == "PRINTER_CONFIG" and header["drucker"] is not None:
        out += _fehlend(header["drucker"], DRUCKER_EINTRAG_FELDER, "drucker")
        if isinstance(header["drucker"], dict) and header["drucker"].get("weg") not in DRUCKER_WEGE:
            out.append(f"drucker.weg {header['drucker'].get('weg')!r} unbekannt")
    elif kind in ("PRINT_JOB_REQ", "PRINT_JOB_ASK") and header["weg"] not in DRUCKER_WEGE:
        out.append(f"weg {header['weg']!r} unbekannt")
    elif kind == "PRINT_JOB_REQ" and header.get("filament") is not None and not (
            isinstance(header["filament"], dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in header["filament"].items())):
        out.append("filament ist kein Objekt {material: Filament-id}")
    elif kind == "PRINT_CONTROL" and header["aktion"] not in DRUCKER_AKTIONEN:
        out.append(f"aktion {header['aktion']!r} unbekannt")
    elif kind == "PRINT_JOB_RES" and header["schritt"] is not None and header["schritt"] not in AUFTRAG_SCHRITTE:
        out.append(f"schritt {header['schritt']!r} unbekannt")
    elif kind == "PRINTER_STATUS":
        if header["verbindung"] not in DRUCKER_VERBINDUNGEN:
            out.append(f"verbindung {header['verbindung']!r} unbekannt")
        if header["weg"] not in DRUCKER_WEGE:
            out.append(f"weg {header['weg']!r} unbekannt")
        if header["drucker"] is not None:
            out += _fehlend(header["drucker"], DRUCKER_FELDER, "drucker")
            if isinstance(header["drucker"], dict) and header["drucker"].get("modus") not in DRUCKER_MODI:
                out.append(f"drucker.modus {header['drucker'].get('modus')!r} unbekannt")
        for w in DRUCKER_WEGE:
            out += _fehlend((header["wege"] or {}).get(w), ("moeglich", "grund"), f"wege.{w}")
        if header["druck"] is not None:
            out += _fehlend(header["druck"], DRUCK_STATUS_FELDER, "druck")
            if isinstance(header["druck"], dict) and header["druck"].get("zustand") not in DRUCK_ZUSTAENDE:
                out.append(f"druck.zustand {header['druck'].get('zustand')!r} unbekannt")
        if header["temperaturen"] is not None:
            out += _fehlend(header["temperaturen"], ("duese", "duese_ziel", "bett", "bett_ziel"), "temperaturen")
        for i, f in enumerate(header["fehler"] or []):
            out += _fehlend(f, ("code", "text", "schwere", "art"), f"fehler[{i}]")
        for i, g in enumerate(header["gefunden"] or []):
            out += _fehlend(g, ("name", "modell", "ip", "verbindung", "kennung"), f"gefunden[{i}]")
        if header["auftrag"] is not None:
            out += _fehlend(header["auftrag"], AUFTRAG_FELDER, "auftrag")
            if isinstance(header["auftrag"], dict) and header["auftrag"].get("zustand") not in AUFTRAG_ZUSTAENDE:
                out.append(f"auftrag.zustand {header['auftrag'].get('zustand')!r} unbekannt")
        if header["kamera"] is not False:
            out.append("kamera muss false sein (Phase 8 nutzt keine Kamera)")
    return out


def drucker_status_beispiel(*, druckt: bool = True) -> dict[str, Any]:
    """Beispiel eines PRINTER_STATUS (Weg A, Cloud-Modus, Status lesend, Druck läuft) für Testdateien und Attrappen."""
    from kevcad_kernel.drucker.sperre import ANLEITUNG_WEG_B

    return {
        "konfiguriert": True, "verbindung": "verbunden", "meldung": None,
        "drucker": {"id": "p1p", "name": "P1P Werkstatt", "modell": "P1P", "ip": "192.168.178.40",
                    "firmware": "01.10.00.00", "modus": "cloud", "entwicklermodus": False, "signal": "-52dBm"},
        "weg": "a",
        "wege": {"a": {"moeglich": True, "grund": None},
                 "b": {"moeglich": False, "grund": "Der Drucker ist im Cloud-Modus (LAN Only Mode aus).",
                       "anleitung": list(ANLEITUNG_WEG_B)}},
        "steuern": False,
        "druck": ({"zustand": "druckt", "gcode_state": "RUNNING", "fortschritt": 0.42, "schicht": 41, "schichten": 98,
                   "restzeit_s": 3720, "aufgabe": "Kugelschieber-platten", "datei": "Kugelschieber-platten.gcode.3mf",
                   "stufe": "druckt", "geschwindigkeit": "standard"} if druckt else
                  {"zustand": "bereit", "gcode_state": "IDLE", "fortschritt": 0.0, "schicht": 0, "schichten": 0,
                   "restzeit_s": 0, "aufgabe": None, "datei": None, "stufe": None, "geschwindigkeit": "standard"}),
        "temperaturen": {"duese": 219.5, "duese_ziel": 220.0, "bett": 55.0, "bett_ziel": 55.0},
        "fehler": [{"code": "0300-0100-0003-0007", "text": "Meldung 0300-0100-0003-0007 des Druckers, Erklärung: "
                    "https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/0300_0100_0003_0007",
                    "schwere": "warnung", "art": "hms"}] if druckt else [],
        "kamera": False,
        "gefunden": [{"name": "P1P Werkstatt", "modell": "P1P", "ip": "192.168.178.40", "verbindung": "cloud",
                      "kennung": "3fa2c1d09e7b"}],
        "auftrag": {"auftrag": "j-3", "zustand": "geoeffnet", "weg": "a", "platten": [1, 2], "fortschritt": None,
                    "meldung": "In Bambu Studio geöffnet: dort „Platte drucken“ (bzw. „Alle drucken“) und „Senden“ "
                               "klicken.",
                    "datei": "/Users/test/Documents/Kev CAD/Kugelschieber/output/Kugelschieber-platten.gcode.3mf",
                    "von": "kevin"},
        "aktualisiert": 1792656000.0,
    }


# ---------------------------------------------------------------------------------------------------------------------
# Phase 4: Referenzen (PROTOCOL.md, Abschnitt „Phase 4: Referenzen“; Umsetzung in kevcad_kernel/referenz/)
# ---------------------------------------------------------------------------------------------------------------------

REF_NACHRICHTEN: dict[str, tuple[str, ...]] = {
    # Kernel → App (Pflichtfelder außer type/seq)
    "REF_LIST": ("referenzen",),
    "REF_UPSERT": ("name", "farbe", "counts", "bbox", "quelle"),
    "REF_REMOVE": ("name",),
    "REF_PHOTOS": ("referenz", "satz", "fotos"),
    "REF_RESULT": ("referenz", "stand", "masse", "huelle", "empfehlungen"),
    # App → Kernel
    "REF_ADD": ("id", "pfade"),
    "REF_MEASURE_REQ": ("id", "referenz"),
    "REF_APPLY": ("id", "referenz", "werte"),
}
REF_ZUSTAENDE: tuple[str, ...] = ("leer", "rechnet", "fertig", "fehler")
REF_ARTEN: tuple[str, ...] = ("video", "fotos", "scan")  # "scan": Kev Scan (SCAN.md), additiv
REF_SAETZE: tuple[str, ...] = ("messung", "capture")
REF_LISTE_FELDER: tuple[str, ...] = ("name", "art", "quelle", "zustand", "laeuft", "fortschritt", "text", "meldung",
                                     "netz", "fotos", "messung", "erstellt")
REF_FOTO_FELDER: tuple[str, ...] = ("name", "bild", "maske", "kamera")
REF_KAMERA_FELDER: tuple[str, ...] = ("R", "t", "f", "cx", "cy", "w", "h")
REF_MASS_FELDER: tuple[str, ...] = ("name", "wert", "sigma", "start")
REF_NETZ_ARRAYS: tuple[tuple[str, str, str, int], ...] = (
    ("positions", "<f4", "vert", 3),
    ("normals", "<f4", "vert", 3),
    ("triangles", "<u4", "tri", 3),
)
REF_FARBE: tuple[float, float, float, float] = (0.36, 0.62, 0.86, 0.45)  # sRGB, halbdurchsichtig


def pack_ref_netz(*, name: str, positions: np.ndarray, normals: np.ndarray, triangles: np.ndarray,
                  quelle: str = "object_capture", farbe: tuple[float, ...] | list[float] = REF_FARBE,
                  lage: dict[str, Any] | None = None, seq: int = 0) -> tuple[dict[str, Any], bytes]:
    """Kopf und Nutzlast von REF_UPSERT: Referenznetz in Weltkoordinaten des Modells (mm, Z oben), schon an das
    Modell angelegt (``lage`` beschreibt nur, wie). Nutzlast wie PART_UPSERT ohne Flächen, Kanten und Punkte."""
    pos = np.ascontiguousarray(positions, dtype="<f4").reshape(-1, 3)
    nrm = np.ascontiguousarray(normals, dtype="<f4").reshape(-1, 3)
    tri = np.ascontiguousarray(triangles, dtype="<u4").reshape(-1, 3)
    if len(nrm) != len(pos):
        raise ValueError(f"{name}: {len(pos)} Punkte, aber {len(nrm)} Normalen")
    if len(tri) and int(tri.max()) >= len(pos):
        raise ValueError(f"{name}: Dreiecke verweisen auf Punkte, die es nicht gibt")
    lo = pos.min(0) if len(pos) else np.zeros(3)
    hi = pos.max(0) if len(pos) else np.zeros(3)
    header: dict[str, Any] = {
        "type": "REF_UPSERT", "seq": seq, "name": name, "farbe": [float(c) for c in farbe],
        "counts": {"vert": int(len(pos)), "tri": int(len(tri))},
        "bbox": {"min": [round(float(x), 3) for x in lo], "max": [round(float(x), 3) for x in hi]},
        "quelle": quelle, "lage": lage,
    }
    return header, pos.tobytes() + nrm.tobytes() + tri.tobytes()


def unpack_ref_netz(header: dict[str, Any], payload: bytes) -> dict[str, np.ndarray]:
    """Gegenstück zu pack_ref_netz."""
    counts = header["counts"]
    out: dict[str, np.ndarray] = {}
    offset = 0
    for name, dtype, key, per in REF_NETZ_ARRAYS:
        n = int(counts[key]) * per
        out[name] = np.frombuffer(payload, dtype=dtype, count=n, offset=offset).reshape(-1, per)
        offset += n * 4
    if offset != len(payload):
        raise ValueError(f"Nutzlast von REF_UPSERT hat {len(payload)} Byte, erwartet {offset}")
    return out


def check_ref_message(header: dict[str, Any]) -> list[str]:
    """Pflichtfelder und Wertebereiche der Referenz-Nachrichten (für Tests und Testdateien)."""
    typ = header.get("type")
    if typ not in REF_NACHRICHTEN:
        return [f"type {typ!r} ist keine Referenz-Nachricht"]
    out = _fehlend(header, REF_NACHRICHTEN[typ], typ)
    if out:
        return out
    if typ == "REF_LIST":
        for r in header["referenzen"]:
            out += _fehlend(r, REF_LISTE_FELDER, "referenzen[]")
            if r.get("zustand") not in REF_ZUSTAENDE:
                out.append(f"zustand {r.get('zustand')!r} unbekannt")
            if r.get("art") not in REF_ARTEN:
                out.append(f"art {r.get('art')!r} unbekannt")
            abw = r.get("abweichung")  # additiv (22.10.2026): Kurzfassung der Abweichung
            if isinstance(abw, dict) and abw.get("stand") not in REF_ABW_STAENDE:
                out.append(f"abweichung.stand {abw.get('stand')!r} unbekannt")
    elif typ == "REF_DEVIATION":
        if header["auf"] not in REF_ABW_RICHTUNGEN:
            out.append(f"auf {header['auf']!r} unbekannt")
        if header["auf"] == "modell" and not header.get("teil"):
            out.append("REF_DEVIATION auf dem Modell braucht teil")
    elif typ == "REF_SCALE":
        punkte = header.get("punkte")
        if punkte is None and not header.get("kante"):
            out.append("REF_SCALE braucht punkte oder kante")
        if punkte is not None and (len(punkte) != 2 or any(len(q) != 3 for q in punkte)):
            out.append("REF_SCALE.punkte: zwei Punkte mit je drei Zahlen")
    elif typ == "SCAN_LIST":
        for s in header["scans"]:
            out += _fehlend(s, SCAN_FELDER, "scans[]")
            if s.get("zustand") not in SCAN_ZUSTAENDE:
                out.append(f"scans[].zustand {s.get('zustand')!r} unbekannt")
    elif typ == "REF_PHOTOS":
        if header["satz"] not in REF_SAETZE:
            out.append(f"satz {header['satz']!r} unbekannt")
        for f in header["fotos"]:
            out += _fehlend(f, REF_FOTO_FELDER, "fotos[]")
            if isinstance(f.get("kamera"), dict):
                out += _fehlend(f["kamera"], REF_KAMERA_FELDER, "fotos[].kamera")
                if len(f["kamera"].get("R") or []) != 3:
                    out.append("kamera.R braucht drei Zeilen")
    elif typ == "REF_RESULT":
        for m in header["masse"]:
            out += _fehlend(m, REF_MASS_FELDER, "masse[]")
    elif typ == "REF_UPSERT":
        out += _fehlend(header["counts"], ("vert", "tri"), "counts")
    return out


def referenz_beispiele() -> list[tuple[str, dict[str, Any], bytes]]:
    """Beispielnachrichten für die Testdateien (kernel/tools/make_referenz_fixtures.py): (Dateiname, Kopf, Nutzlast)."""
    kamera = {"R": [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]], "t": [0.0, 40.0, 600.0], "f": 1546.8,
              "cx": 960.0, "cy": 540.0, "w": 1920, "h": 1080}
    liste = {"type": "REF_LIST", "seq": 1, "referenzen": [
        {"name": "IMG_5186", "art": "video", "quelle": "/Volumes/Aufnahmen/IMG_5186.MOV", "zustand": "rechnet",
         "laeuft": "capture", "fortschritt": 0.42, "text": "Rekonstruktion: Netz wird erzeugt", "meldung": None,
         "netz": False, "fotos": 8, "messung": True, "erstellt": "2026-10-22T14:03:11",
         "capture": None, "lage": None},
        {"name": "Fotos Küche", "art": "fotos", "quelle": "3 Fotos", "zustand": "leer", "laeuft": None,
         "fortschritt": None, "text": None, "meldung": None, "netz": False, "fotos": 0, "messung": False,
         "erstellt": "2026-10-22T14:10:00"}]}
    pos = np.array([[-90, -51, 0], [90, -51, 0], [90, 51, 0], [-90, 51, 0], [0, 0, 47.5]], float)
    tri = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4], [0, 2, 1], [0, 3, 2]])
    from kevcad_kernel.referenz.netz import normalen

    netz, nutz = pack_ref_netz(name="IMG_5186", positions=pos, normals=normalen(pos, tri), triangles=tri,
                               lage={"drehung_z": 180.0, "verschiebung": [0.0, -1.2, 0.0], "rest_mm": 6.3, "paare": 8,
                                     "massstab": 1.012}, seq=2)
    fotos = {"type": "REF_PHOTOS", "seq": 3, "referenz": "IMG_5186", "satz": "messung", "fotos": [
        {"name": "IMG_5186_003.667", "bild": "/p/referenzen/IMG_5186/messung/bilder/IMG_5186_003.667.jpg",
         "maske": "/p/referenzen/IMG_5186/messung/masken/IMG_5186_003.667.png",
         "kontrolle": "/p/referenzen/IMG_5186/messung/kontrolle/IMG_5186_003.667.jpg", "zeit": 3.667, "iou": 0.916,
         "kamera": kamera},
        {"name": "bild_0007", "bild": "/p/referenzen/IMG_5186/capture/bilder/bild_0007.jpg", "maske": None,
         "kontrolle": None, "zeit": 4.1, "iou": None, "kamera": {**kamera, "cx": 951.5, "cy": 547.25}}]}
    ergebnis = {"type": "REF_RESULT", "seq": 4, "referenz": "IMG_5186", "stand": "2026-10-22T14:05:40",
                "masse": [{"name": "tiefe", "wert": 103.4, "sigma": 1.8, "start": 110.0},
                          {"name": "hoehe", "wert": 46.4, "sigma": 2.2, "start": 46.0}],
                "bekannt": {"breite": 180.0},
                "huelle": {"min": [-90.0, -63.0, 0.0], "max": [90.0, 55.0, 47.9], "groesse": [180.0, 118.0, 47.9]},
                "grundkoerper": {"teil": "Scarlett/Gehaeuse", "groesse": [180.0, 103.7, 46.5]},
                "brennweite_px": 3093.6, "bilder": 8, "verworfen": [],
                "empfehlungen": [
                    {"art": "nachmessen", "mass": "gross_h", "anteil": 0.45,
                     "text": "Von Hand nachmessen: gross_h (die Unsicherheit aller Maße sinkt auf 45 %)"},
                    {"art": "aufnahme", "anteil": 0.93,
                     "text": "Zusatzaufnahme schräg von vorne rechts, 30° hoch: bringt nur noch 7 %"}],
                "dauer_s": 72.6}
    return [
        ("ref_list", liste, b""),
        ("ref_upsert", netz, nutz),
        ("ref_remove", {"type": "REF_REMOVE", "seq": 5, "name": "Fotos Küche"}, b""),
        ("ref_photos", fotos, b""),
        ("ref_result", ergebnis, b""),
        ("ref_add", {"type": "REF_ADD", "seq": 1, "id": "a-1", "pfade": ["/Users/test/IMG_5186.MOV"],
                     "name": None, "masz": {"laenge": 180.0}, "auflage": True, "von": None, "bis": None,
                     "einstellung": "schnell"}, b""),
        ("ref_measure_req", {"type": "REF_MEASURE_REQ", "seq": 2, "id": "a-2", "referenz": "IMG_5186",
                             "frei": ["tiefe", "hoehe"], "bekannt": {"breite": 180.0}, "bilder": 8}, b""),
        ("ref_apply", {"type": "REF_APPLY", "seq": 3, "id": "a-3", "referenz": "IMG_5186",
                       "werte": {"tiefe": 103.4, "hoehe": 46.4}}, b""),
    ] + referenz_beispiele_rest()


# ---------------------------------------------------------------------------------------------------------------------
# Phase 4, Rest (22.10.2026, additiv): Abweichung als Farbkarte (REF_DEVIATION), Maßstab nachträglich (REF_SCALE),
# Scans in der App (SCAN_LIST, SCAN_IMPORT). PROTOCOL.md „Phase 4: Referenzen“, Abschnitte „Abweichung“, „Maßstab“,
# „Scans in der App“.
# ---------------------------------------------------------------------------------------------------------------------

REF_NACHRICHTEN.update({
    "REF_DEVIATION": ("referenz", "run", "auf", "teil", "feld", "punkte", "dreiecke"),  # Kernel → App
    "REF_SCALE": ("id", "referenz", "mm"),  # App → Kernel
    "SCAN_LIST": ("scans", "empfaenger"),  # Kernel → App
    "SCAN_IMPORT": ("id",),  # App → Kernel
})
REF_ABW_RICHTUNGEN: tuple[str, ...] = ("modell", "referenz")
REF_ABW_STAENDE: tuple[str, ...] = ("done", "laeuft", "failed")
REF_ABW_KENNZAHLEN: tuple[str, ...] = ("mittel_mm", "max_mm", "p95_mm", "versatz_mm", "abgedeckt")
REF_MASSSTAB_KANTEN: tuple[str, ...] = ("laenge", "breite", "hoehe", "grund_laenge", "grund_breite")
SCAN_FELDER: tuple[str, ...] = ("id", "name", "empfangen", "fotos", "videobilder", "zustand")
SCAN_ZUSTAENDE: tuple[str, ...] = ("neu", "uebernommen")
REF_ABW_ARRAYS: tuple[tuple[str, str, int], ...] = (("punkte", "<f4", 3), ("dreiecke", "<u4", 3), ("werte", "<f4", 1))


def pack_ref_abweichung(*, referenz: str, run: int, auf: str, teil: str | None, feld: str, punkte: np.ndarray,
                        dreiecke: np.ndarray, werte: np.ndarray, grenze_mm: float | None = None,
                        kennzahlen: dict[str, Any] | None = None, seq: int = 0) -> tuple[dict[str, Any], bytes]:
    """REF_DEVIATION: Netz (Modellteil oder Referenznetz, Weltkoordinaten in mm) mit dem Abstand je Punkt in mm,
    positiv = die Referenz liegt außerhalb des Modells, NaN = keine Referenz in der Nähe. Nutzlast: Punkte f32
    (n × 3), Dreiecke u32 (m × 3), Werte f32 (n), little-endian, ohne Lücken."""
    p = np.ascontiguousarray(punkte, dtype="<f4").reshape(-1, 3)
    t = np.ascontiguousarray(dreiecke, dtype="<u4").reshape(-1, 3)
    w = np.ascontiguousarray(werte, dtype="<f4").reshape(-1)
    if len(w) != len(p):
        raise ValueError(f"REF_DEVIATION: {len(p)} Punkte, aber {len(w)} Werte")
    if len(t) and int(t.max()) >= len(p):
        raise ValueError("REF_DEVIATION: Dreiecke verweisen auf Punkte, die es nicht gibt")
    if auf not in REF_ABW_RICHTUNGEN:
        raise ValueError(f"REF_DEVIATION: auf {auf!r} unbekannt")
    header = {"type": "REF_DEVIATION", "seq": seq, "referenz": referenz, "run": int(run), "auf": auf, "teil": teil,
              "feld": feld, "punkte": int(len(p)), "dreiecke": int(len(t)),
              "grenze_mm": None if grenze_mm is None else round(float(grenze_mm), 2),
              "kennzahlen": kennzahlen or {}}
    return header, p.tobytes() + t.tobytes() + w.tobytes()


def unpack_ref_abweichung(header: dict[str, Any], payload: bytes) -> dict[str, np.ndarray]:
    n, m = int(header["punkte"]), int(header["dreiecke"])
    out: dict[str, np.ndarray] = {}
    pos = 0
    for name, typ, breite in REF_ABW_ARRAYS:
        k = (m if name == "dreiecke" else n) * breite
        a = np.frombuffer(payload, dtype=typ, count=k, offset=pos)
        pos += a.nbytes
        out[name] = a.reshape(-1, breite) if breite > 1 else a
    if pos != len(payload):
        raise ValueError(f"REF_DEVIATION: Nutzlast {len(payload)} Byte, erwartet {pos}")
    return out


def check_ref_abweichung(header: dict[str, Any], payload: bytes) -> list[str]:
    """Fehler einer REF_DEVIATION-Nachricht mit Nutzlast (leer = gültig)."""
    err = check_ref_message(header)
    if err:
        return err
    try:
        f = unpack_ref_abweichung(header, payload)
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]
    if len(f["dreiecke"]) and int(f["dreiecke"].max()) >= int(header["punkte"]):
        err.append("REF_DEVIATION: Dreieck zeigt auf einen Punkt, den es nicht gibt")
    return err


def abweichung_kurz(stand: str, **felder: Any) -> dict[str, Any]:
    """``REF_LIST.referenzen[i].abweichung``: Stand, Lauf, Grenze, Spanne der Legende, Kennzahlen je Teil und für das
    Referenznetz mit dem Schlüssel ``feld`` der zugehörigen REF_DEVIATION."""
    return {"stand": stand, **felder}


def referenz_beispiele_rest() -> list[tuple[str, dict[str, Any], bytes]]:
    """Beispiele für Abweichung, Maßstab und Scans (Dateinamen ``ref_deviation*``, ``ref_scale*``, ``scan_*``)."""
    # Teil „Kiste/Korpus“ 100 × 60 × 40 als Quader (8 Punkte, 12 Dreiecke), Referenz rechts 1 mm außerhalb,
    # links 2 mm innerhalb, unten keine Referenz (NaN)
    p = np.array([[x, y, z] for z in (0.0, 40.0) for y in (-30.0, 30.0) for x in (-50.0, 50.0)], dtype=np.float32)
    tri = np.array([[0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6], [0, 1, 5], [0, 5, 4], [2, 6, 7], [2, 7, 3],
                    [0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5]], dtype=np.uint32)
    werte = np.where(p[:, 0] > 0, 1.0, -2.0).astype(np.float32)
    werte[p[:, 2] < 1] = np.nan
    kz = {"mittel_mm": 1.5, "max_mm": 2.0, "p95_mm": 2.0, "versatz_mm": -0.5, "abgedeckt": 0.8, "punkte": 8,
          "ort_max": [-50.0, -30.0, 40.0]}
    modell, nutz_m = pack_ref_abweichung(referenz="IMG_5186", run=7, auf="modell", teil="Kiste/Korpus",
                                         feld="a1b2c3d4e5f6a7b8c9d0", punkte=p, dreiecke=tri, werte=werte,
                                         grenze_mm=10.0, kennzahlen=kz, seq=6)
    rp = np.array([[-49, -31, 1], [51, -31, 1], [51, 31, 1], [-49, 31, 1], [0, 0, 41]], dtype=np.float32)
    rt = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]], dtype=np.uint32)
    rw = np.array([1.0, 1.0, 1.0, 1.0, 0.5], dtype=np.float32)
    ref, nutz_r = pack_ref_abweichung(referenz="IMG_5186", run=7, auf="referenz", teil=None,
                                      feld="f0e1d2c3b4a596877869", punkte=rp, dreiecke=rt, werte=rw, grenze_mm=10.0,
                                      kennzahlen={"mittel_mm": 0.9, "max_mm": 1.0, "p95_mm": 1.0, "versatz_mm": 0.9,
                                                  "abgedeckt": 1.0, "punkte": 5, "ort_max": [51.0, 31.0, 1.0]},
                                      seq=7)
    liste = {"type": "REF_LIST", "seq": 8, "referenzen": [
        {"name": "IMG_5186", "art": "video", "quelle": "/Volumes/Aufnahmen/IMG_5186.MOV", "zustand": "fertig",
         "laeuft": None, "fortschritt": None, "text": None, "meldung": None, "netz": True, "fotos": 8,
         "messung": True, "erstellt": "2026-10-22T14:03:11", "capture": None,
         "lage": {"drehung_z": 180.0, "verschiebung": [0.0, -1.2, 0.0], "rest_mm": 6.3, "paare": 8},
         "massstab": {"faktor": 1.0125, "mm": 180.0, "ist_mm": 177.78, "quelle": "punkte",
                      "stand": "2026-10-22T22:10:00"},
         "abweichung": abweichung_kurz("done", run=7, grenze_mm=10.0, skala_mm=2.0, skala_fest=False,
                                       angelegt=True, ms=840.0, meldung=None,
                                       teile=[{"teil": "Kiste/Korpus", "feld": modell["feld"], **kz}],
                                       referenz={"feld": ref["feld"], **ref["kennzahlen"]})},
        {"name": "Scan Packung", "art": "scan", "quelle": "/Users/test/Documents/Kev CAD/Scans/2026-10-22_213800_Scan",
         "zustand": "rechnet", "laeuft": "capture", "fortschritt": 0.42, "text": "Scan: Tiefe 12 von 101",
         "phase": "Tiefe (PromptDA)", "meldung": None, "netz": False, "fotos": 0, "messung": False,
         "erstellt": "2026-10-22T21:40:00", "capture": None, "lage": None, "abweichung": None}]}
    scale_punkte = {"type": "REF_SCALE", "seq": 4, "id": "a-4", "referenz": "IMG_5186",
                    "punkte": [[-88.9, -50.4, 0.0], [88.9, -50.4, 0.0]], "kante": None, "mm": 180.0}
    scale_kante = {"type": "REF_SCALE", "seq": 5, "id": "a-5", "referenz": "IMG_5186", "punkte": None,
                   "kante": "laenge", "mm": 180.0}
    scan_liste = {"type": "SCAN_LIST", "seq": 9, "ordner": "/Users/test/Documents/Kev CAD/Scans",
                  "neu": "2026-10-22_213800_Scan 22.10.",
                  "empfaenger": {"laeuft": True, "port": 50123, "name": "MacBook Pro", "dienst": "_kevscan._tcp"},
                  "scans": [
                      {"id": "2026-10-22_213800_Scan 22.10.", "name": "Scan 22.10. 21.38",
                       "empfangen": "2026-10-22T21:40:12", "erstellt": "2026-10-22T21:38:00+02:00",
                       "geraet": "iPhone16,1", "fotos": 61, "videobilder": 779, "objekt": True, "groesse_mb": 433.9,
                       "vorschau": "/Users/test/Documents/Kev CAD/Scans/2026-10-22_213800_Scan 22.10./vorschau.jpg",
                       "zustand": "neu", "referenzen": []},
                      {"id": "2026-10-21_101500_Rollwagen", "name": "Rollwagen", "empfangen": "2026-10-21T10:15:40",
                       "erstellt": None, "geraet": "iPhone16,1", "fotos": 12, "videobilder": 240, "objekt": False,
                       "groesse_mb": 120.5, "vorschau": None, "zustand": "uebernommen",
                       "referenzen": [{"projekt": "/Users/test/Documents/Kev CAD/Rollwagen", "name": "Rollwagen",
                                       "stand": "2026-10-21T10:20:00", "schnell": True}]}]}
    scan_import = {"type": "SCAN_IMPORT", "seq": 6, "id": "a-6", "scan": "2026-10-22_213800_Scan 22.10.",
                   "name": None, "schnell": False}
    return [
        ("ref_deviation_modell", modell, nutz_m),
        ("ref_deviation_referenz", ref, nutz_r),
        ("ref_list_abweichung", liste, b""),
        ("ref_scale_punkte", scale_punkte, b""),
        ("ref_scale_kante", scale_kante, b""),
        ("scan_list", scan_liste, b""),
        ("scan_import", scan_import, b""),
    ]
# Statik (PLAN-STATIK.md, Stufe 1): STATICS (Kernel → App), siehe PROTOCOL.md Abschnitt „Statik“

STATIK_AMPELN = ("gruen", "gelb", "rot", "grau")
STATIK_STAENDE = ("done", "failed")
STATIK_URTEIL_FELDER = ("art", "teil", "ampel", "text", "loesung", "sicherheit", "ziel", "reserve", "ausnutzung", "ort",
                        "durchbiegung", "grenze", "schichtfaktor", "quer_zur_schicht", "alternative", "kurz")
STATIK_LAST_FELDER = ("teile", "kraft", "punkt", "kg", "zeile", "gegen", "paar", "id",  # ``lasten`` je Szenario (T32)
                      "flaeche")  # additiv (Simulation): Last auf der ganzen Fläche {teil, index, flaeche_mm2, druck}
STATIK_ABLAUF_STAENDE = ("done", "laeuft", "failed")  # Stufe 2 (Ablauf): Feld ``ablauf`` je Szenario
STATIK_ABLAUF_KURZ = ("kippreserve", "a_abheben", "abheben_max_mm", "kippwinkel_max", "rutschgrenze", "rutschreserve",
                      "geschwindigkeit", "verzoegerung")
STATIK_FK_STAENDE = ("done", "laeuft", "failed", "abgebrochen")  # Stufe 3 (Festkörper): Feld ``festkoerper``
STATIK_FK_TEIL = ("teil", "stand", "ampel", "sicherheit", "ziel", "ausnutzung", "spannung_max", "kriterium", "ort",
                  "sicherheit_lagerrand", "verformung_max_mm", "kragtraeger", "druckteil", "q", "ausrichtungen",
                  "ausrichtung_beste", "netz", "ms", "feld", "meldung", "text", "aus_speicher",
                  # Stufe 4 (CalculiX, additiv): Verfahren, Sicherheit unter Last, Kontakt je Paar, Plastizität,
                  # Traglast, Beulen, Rutschen, größte Zusatzwerte des Felds
                  "verfahren", "sicherheit_last", "kontakt", "plastisch", "traglast", "beulen", "rutscht",
                  "zusatz_max")
STATIK_FELD_ARRAYS = (("punkte", "<f4", 3), ("dreiecke", "<u4", 3), ("ausnutzung", "<f4", 1), ("spannung", "<f4", 1),
                      ("verschiebung", "<f4", 3))
# Stufe 4 (additiv): weitere Werte je Punkt (float32), in der Reihenfolge von ``zusatz`` im Kopf hinter den obigen:
# Kontaktdruck (N/mm²), plastische Vergleichsdehnung (1), Klaffen (mm), Schlupf (mm)
STATIK_FELD_ZUSATZ = ("kontaktdruck", "plast_dehnung", "klaffen", "schlupf")


def _statik_ablauf(ab: dict[str, Any], voll: bool = True) -> dict[str, Any]:
    """Ablauf (S2) eines Szenarios für die App: Stand, Ampel, Text, Animation (Name in ANIM_DEF), Kennzahlen; voll
    zusätzlich Antrieb, Handrechnung, Verlauf je Bild und Kontaktpfeile."""
    out: dict[str, Any] = {k: ab.get(k) for k in ("stand", "ampel", "text", "animation", "meldung")}
    kz = dict(ab.get("kennzahlen") or {})
    if not voll:
        out["kennzahlen"] = {k: kz.get(k) for k in STATIK_ABLAUF_KURZ if k in kz}
        return out
    out.update({"kennzahlen": kz, "dauer": ab.get("dauer"), "fps": ab.get("fps"), "bilder": ab.get("bilder"),
                "antrieb": ab.get("antrieb"), "handrechnung": ab.get("handrechnung"),
                "verlauf": ab.get("verlauf"), "pfeile": ab.get("pfeile"), "ms": ab.get("ms")})
    return out


def _statik_festkoerper(fk: dict[str, Any], voll: bool = True) -> dict[str, Any]:
    """Festkörper (S3) eines Szenarios für die App: Stand, Fortschritt, je Teil Sicherheit, Ampel, Kriterium, Ort und
    der Schlüssel des Felds (STATICS_FIELD); kurz nur Stand und je Teil Ampel und Sicherheit."""
    out: dict[str, Any] = {k: fk.get(k) for k in ("stand", "fortschritt", "text", "meldung")}
    teile = fk.get("teile") or []
    if voll:
        out["teile"] = [{k: t.get(k) for k in STATIK_FK_TEIL if k in t} for t in teile]
    else:
        out["teile"] = [{k: t.get(k) for k in ("teil", "stand", "ampel", "sicherheit")} for t in teile]
    return out


def _statik_szenario(e: dict[str, Any], voll: bool = True) -> dict[str, Any]:
    sz = e.get("szenario") or {}
    out: dict[str, Any] = {
        "name": e.get("name"), "art": sz.get("art") or e.get("art") or "statisch",
        "quelle": sz.get("quelle") or e.get("quelle") or "modell", "ampel": e.get("ampel") or "grau",
        "ziel": e.get("ziel"), "text": e.get("text") or "", "kennzahlen": dict(e.get("kennzahlen") or {}),
        "beschreibung": sz.get("beschreibung") or e.get("beschreibung"),
    }
    if not voll:
        if isinstance(e.get("ablauf"), dict):
            out["ablauf"] = _statik_ablauf(e["ablauf"], voll=False)
        if isinstance(e.get("festkoerper"), dict):
            out["festkoerper"] = _statik_festkoerper(e["festkoerper"], voll=False)
        return out
    out["urteile"] = [{k: u[k] for k in STATIK_URTEIL_FELDER if k in u} for u in e.get("urteile") or []]
    out["teile"] = list(e.get("teile") or [])
    out["staebe"] = list(e.get("staebe") or [])
    out["auflager"] = list(e.get("auflager") or [])
    # additiv (Nachbesserung, T32): Lasten mit Angriffspunkt; Kraftpaare mit `gegen` und `paar` (Gegenkraft −kraft am
    # selben Punkt auf `gegen`)
    out["lasten"] = [{k: l[k] for k in STATIK_LAST_FELDER if k in l} for l in e.get("lasten") or []]
    # additiv (Simulation): ausdrückliche Lager, die in diesem Szenario gelten (Lager je Lastfall), eigener Untergrund
    if e.get("lager_ids") is not None:
        out["lager"] = list(e.get("lager_ids") or [])
    if sz.get("untergrund"):
        out["untergrund"] = sz.get("untergrund")
    out["ueberhoehung"] = e.get("ueberhoehung") or 1.0
    kippen = (e.get("s0") or {}).get("kippen") if e.get("s0") is not None else e.get("kippen")
    out["kippen"] = [{k: g.get(k) for k in ("name", "reserve", "richtung_text", "je_richtung", "teile")}
                     for g in kippen or []]
    if isinstance(e.get("ablauf"), dict):
        out["ablauf"] = _statik_ablauf(e["ablauf"])
    if isinstance(e.get("festkoerper"), dict):
        out["festkoerper"] = _statik_festkoerper(e["festkoerper"])
    return out


def pack_statics(statik: dict[str, Any], *, run: int, aktiv: str | None = None, reply_to: str | None = None,
                 zeigen: bool = False, seq: int = 0) -> dict[str, Any]:
    """Kopf von STATICS (keine Nutzlast): Ergebnis der Statik (statik/rechnen.py) für die App. ``aktiv``: Szenario,
    das die App anbietet (sonst das des Ergebnisses); ``zeigen``: der Agent will es im Viewer sehen (Farbverlauf und
    Verformung an)."""
    header: dict[str, Any] = {
        "type": "STATICS", "seq": seq, "run": int(run), "stand": statik.get("stand") or "done",
        "aktiv": aktiv or statik.get("aktiv"), "zeigen": bool(zeigen), "meldung": statik.get("meldung"),
        "szenarien": [_statik_szenario(e) for e in statik.get("szenarien") or []],
        "ueberdimensioniert": [{k: u[k] for k in STATIK_URTEIL_FELDER if k in u}
                               for u in statik.get("ueberdimensioniert") or []],
        "grenzen": list(statik.get("grenzen") or []), "vereinfachungen": list(statik.get("vereinfachungen") or []),
        "modell": dict(statik.get("modell") or {}), "ms": statik.get("ms"),
    }
    if reply_to is not None:
        header["reply_to"] = reply_to
    return header


def statik_kurz(statik: dict[str, Any]) -> dict[str, Any]:
    """Kurzfassung für den CHECK-Kopf (Feld ``statik``): je Szenario Ampel, Text und Kennzahlen."""
    return {"stand": statik.get("stand") or "done", "aktiv": statik.get("aktiv"),
            "szenarien": [_statik_szenario(e, voll=False) for e in statik.get("szenarien") or []],
            "ms": statik.get("ms")}


def check_statics_message(header: dict[str, Any]) -> list[str]:
    """Fehler einer STATICS-Nachricht (leer = gültig): Pflichtfelder, Ampeln, Stäbe mit gleich langen Listen."""
    err: list[str] = []
    if header.get("type") != "STATICS":
        err.append("type ist nicht STATICS")
    if header.get("stand") not in STATIK_STAENDE:
        err.append(f"stand {header.get('stand')!r} unbekannt")
    namen = []
    for i, e in enumerate(header.get("szenarien") or []):
        wo = f"szenarien[{i}]"
        err += _fehlend(e, ("name", "ampel", "kennzahlen", "urteile", "teile", "staebe"), wo)
        namen.append(e.get("name"))
        if e.get("ampel") not in STATIK_AMPELN:
            err.append(f"{wo}.ampel {e.get('ampel')!r} unbekannt")
        for u in e.get("urteile") or []:
            if u.get("ampel") not in STATIK_AMPELN:
                err.append(f"{wo}: Urteil mit Ampel {u.get('ampel')!r}")
        for t in e.get("teile") or []:
            if t.get("ampel") not in STATIK_AMPELN:
                err.append(f"{wo}: Teil {t.get('name')!r} mit Ampel {t.get('ampel')!r}")
        for s in e.get("staebe") or []:
            n = len(s.get("punkte") or [])
            if n < 2 or len(s.get("ausnutzung") or []) != n or len(s.get("verschiebung") or []) != n:
                err.append(f"{wo}: Stab {s.get('name')!r}: punkte, ausnutzung und verschiebung brauchen gleich viele "
                           "Einträge (mindestens 2)")
        for j, l in enumerate(e.get("lasten") or []):
            for k in ("kraft", "punkt"):
                v = l.get(k)
                if not isinstance(v, list) or len(v) != 3 or not all(isinstance(c, (int, float)) for c in v):
                    err.append(f"{wo}.lasten[{j}].{k}: drei Zahlen erwartet")
            if l.get("paar") and not l.get("gegen"):
                err.append(f"{wo}.lasten[{j}]: Kraftpaar ohne gegen")
        ab = e.get("ablauf")
        if ab is not None:
            if ab.get("stand") not in STATIK_ABLAUF_STAENDE:
                err.append(f"{wo}.ablauf.stand {ab.get('stand')!r} unbekannt")
            if ab.get("stand") == "done":
                if not isinstance(ab.get("animation"), str) or not ab.get("animation"):
                    err.append(f"{wo}.ablauf: animation fehlt")
                if ab.get("ampel") not in STATIK_AMPELN:
                    err.append(f"{wo}.ablauf.ampel {ab.get('ampel')!r} unbekannt")
                vl = ab.get("verlauf") or {}
                n = len(vl.get("zeit") or [])
                for k in ("kipp", "abheben"):
                    if k in vl and len(vl[k]) != n:
                        err.append(f"{wo}.ablauf.verlauf.{k}: {len(vl[k])} Werte, Zeiten {n}")
                if ab.get("pfeile") is not None and ab.get("bilder") and len(ab["pfeile"]) != ab["bilder"]:
                    err.append(f"{wo}.ablauf.pfeile: {len(ab['pfeile'])} Bilder, erwartet {ab['bilder']}")
        fk = e.get("festkoerper")
        if fk is not None:
            if fk.get("stand") not in STATIK_FK_STAENDE:
                err.append(f"{wo}.festkoerper.stand {fk.get('stand')!r} unbekannt")
            for t in fk.get("teile") or []:
                if not t.get("teil"):
                    err.append(f"{wo}.festkoerper: Teil ohne Namen")
                if t.get("stand") == "done" and t.get("ampel") not in STATIK_AMPELN:
                    err.append(f"{wo}.festkoerper: Teil {t.get('teil')!r} mit Ampel {t.get('ampel')!r}")
    if header.get("aktiv") is not None and header.get("aktiv") not in namen:
        err.append(f"aktiv {header.get('aktiv')!r} ist kein Szenario")
    return err


def statik_beispiel() -> dict[str, Any]:
    """Kleines, vollständiges Ergebnis für Testdateien und Attrappen (zwei Szenarien, ein Stab, ein Druckteil)."""
    punkte = [[0.0, 0.0, 30.0], [250.0, 0.0, 30.0], [500.0, 0.0, 30.0]]
    return {
        "stand": "done", "aktiv": "Aufstützen 30 kg", "ms": 412.5,
        "modell": {"staebe": 1, "starrkoerper": 1, "geerdet": 1, "anschluesse": 2, "ms": 12.0},
        "szenarien": [
            {"name": "Eigengewicht", "szenario": {"art": "statisch", "quelle": "standard",
                                                  "beschreibung": "nur das eigene Gewicht"},
             "ampel": "gruen", "ziel": 2.0, "text": "Eigengewicht: grün – Sicherheit 41,2",
             "kennzahlen": {"sicherheit": 41.2, "knicken": None, "kippreserve": 9.6, "rutschreserve": None,
                            "durchbiegung_mm": 0.3, "durchbiegung_grenze_mm": 5.0, "verformung_max_mm": 0.3},
             "urteile": [], "teile": [{"name": "Rahmen/Rohr", "ausnutzung": 0.049, "ampel": "gruen",
                                       "verformung_mm": 0.3, "sicherheit": 41.2}],
             "staebe": [{"name": "Rahmen/Rohr", "punkte": punkte, "ausnutzung": [0.05, 0.02, 0.0],
                         "verschiebung": [[0, 0, 0], [0, 0, -0.1], [0, 0, -0.3]], "radius": 6.0, "sicherheit": 41.2,
                         "ampel": "gruen"}],
             "auflager": [{"stab": "Rahmen/Rohr", "teil": "Rahmen/Halter (Druck)", "punkt": [0.0, 0.0, 30.0],
                           "kraft": [0.0, 0.0, 1.7], "moment": [0.0, 210.0, 0.0], "art": "fest"}],
             "ueberhoehung": 66.7, "s0": {"kippen": [{"name": "Der Aufbau um Rahmen (3 Teile)", "reserve": 9.6,
                                                     "richtung_text": "+X", "teile": ["Rahmen/Platte"],
                                                     "je_richtung": {"+X": {"kippwinkel": 31.0, "a_kipp": 5.9}}}]}},
            {"name": "Aufstützen 30 kg", "szenario": {"art": "statisch", "quelle": "modell",
                                                      "beschreibung": "30 kg vorn auf dem Rohr"},
             "ampel": "rot", "ziel": 2.0, "text": "Aufstützen 30 kg: rot – Rahmen/Rohr hält nicht (Sicherheit 0,2)",
             "kennzahlen": {"sicherheit": 0.2, "knicken": None, "kippreserve": 0.8, "rutschreserve": None,
                            "durchbiegung_mm": 61.0, "durchbiegung_grenze_mm": 5.0, "verformung_max_mm": 61.0},
             "urteile": [
                 {"art": "festigkeit", "teil": "Rahmen/Rohr", "ampel": "rot",
                  "text": "Rahmen/Rohr hält nicht: Sicherheit 0,2 (Ziel 2), Spannung 790 N/mm² bei 0 mm (Grenze "
                          "160 N/mm², Aluminium EN AW-6060).",
                  "loesung": "Alurohr 25 × 2,0 aus dem Lager reicht (Sicherheit 2,4, 0,2 kg mehr)",
                  "sicherheit": 0.2, "ziel": 2.0, "ausnutzung": 10.0, "ort": [0.0, 0.0, 30.0]},
                 {"art": "bauteil", "teil": "Rahmen/Halter (Druck)", "ampel": "rot",
                  "text": "Rahmen/Halter (Druck) hält nicht: Sicherheit 1,4 (Ziel 4, Druckteil), quer zur Schicht.",
                  "loesung": "Drehen: so drucken, dass die Schichten längs der Last liegen (z. B. lager.druckteil(…, "
                             "ausrichtung=\"-y\")); oder verstärken: an der Einspannung um etwa 70 % höher machen",
                  "sicherheit": 1.4, "ziel": 4.0, "schichtfaktor": 0.4, "quer_zur_schicht": True}],
             "teile": [{"name": "Rahmen/Rohr", "ausnutzung": 10.0, "ampel": "rot", "verformung_mm": 61.0,
                        "sicherheit": 0.2},
                       {"name": "Rahmen/Halter (Druck)", "ausnutzung": 2.86, "ampel": "rot", "verformung_mm": None,
                        "sicherheit": 1.4}],
             "staebe": [{"name": "Rahmen/Rohr", "punkte": punkte, "ausnutzung": [10.0, 5.0, 0.0],
                         "verschiebung": [[0, 0, 0], [0, 0, -22.0], [0, 0, -61.0]], "radius": 6.0, "sicherheit": 0.2,
                         "ampel": "rot"}],
             "auflager": [], "ueberhoehung": 1.0, "s0": {"kippen": []},
             "lasten": [{"teile": ["Rahmen/Rohr"], "kraft": [0.0, 0.0, -294.3], "punkt": [250.0, 0.0, 30.0],
                         "kg": 30.0, "zeile": 12},
                        {"teile": ["Rahmen/Rohr"], "kraft": [100.0, 0.0, 0.0], "punkt": [500.0, 0.0, 30.0],
                         "kg": None, "zeile": 13, "gegen": ["Ball"], "paar": True}]},
        ],
        "ueberdimensioniert": [],
        "grenzen": ["Vereinfacht gerechnet: Stäbe als Balken, linear-elastisch, kleine Verformungen, keine "
                    "Plastizität.", "Kein Ersatz für einen Statiker bei sicherheitsrelevanten Dingen."],
        "vereinfachungen": ["Aluminium EN AW-6060: Zustand T66 angenommen"],
    }


def statik_beispiel_ablauf() -> dict[str, Any]:
    """Wie ``statik_beispiel`` plus ein Ablauf (S2): „Bremsen aus 1 m/s“ mit drei Bildern Verlauf und Kontaktpfeilen
    (Testdatei ``statics_ablauf.frame``)."""
    b = statik_beispiel()
    urteile = [
        {"art": "dyn_kippen", "teil": None, "ampel": "rot", "kurz": "Rollwagen kippt nach vorn (hebt 17 mm ab)",
         "text": "Rollwagen kippt nach vorn: hebt hinten 17 mm ab (Rollwagen/Lenkrolle 2), 1,7°, fällt zurück; "
                 "Fangrolle setzt auf dem Boden auf. Hebt schon ab 2,5 m/s² ab (Kippreserve 0,25).",
         "loesung": "Sanfter bremsen oder langsamer schieben.", "reserve": 0.25, "ziel": 1.5,
         "ort": [102.6, -347.3, 126.1]},
        {"art": "dyn_ladung", "teil": "Bowlingball", "ampel": "gelb",
         "kurz": "Bowlingball bleibt knapp (springt ab 1,12 m/s heraus)",
         "text": "Bowlingball bleibt im Schieber: größter Versatz 46 mm, steigt 30 mm hoch; springt bei dieser "
                 "Bremsart ab 1,12 m/s heraus.", "loesung": "Langsamer schieben oder sanfter bremsen.",
         "reserve": 1.12, "ziel": 1.5},
    ]
    ablauf = {
        "stand": "done", "ampel": "rot", "animation": "Ablauf: Bremsen aus 1 m/s",
        "text": "Bremsen aus 1 m/s: rot – Rollwagen kippt nach vorn (hebt 17 mm ab), Bowlingball bleibt knapp "
                "(springt ab 1,12 m/s heraus)",
        "dauer": 0.04, "fps": 50.0, "bilder": 3,
        "antrieb": {"koerper": "Rollwagen mit Kugelschieber (121 Teile)", "geschwindigkeit": 1.0,
                    "verzoegerung": 10.0, "bremsen": "abrupt (Stillstand in 0,1 s)", "angriff": "boden"},
        "kennzahlen": {"geschwindigkeit": 1.0, "verzoegerung": 10.0, "kippwinkel_max": 1.68, "abheben_max_mm": 16.6,
                       "a_abheben": 2.46, "kippreserve": 0.25, "kippt_um": False, "v_abheben": 0.29,
                       "a_abheben_ohne_ladung": 13.92, "a_kipp_hand": 14.1, "rutschgrenze": 5.89,
                       "rutschreserve": 0.59, "mu_rad": 0.6, "setzt_auf": "Fangrolle",
                       "ladung": [{"koerper": "K2", "name": "Bowlingball", "versatz_max_mm": 46.4,
                                   "hebt_max_mm": 30.5, "bleibt": True, "v_grenze": 1.12}],
                       "kontaktkraefte": [{"paar": ["Bowlingball", "Kugelschieber/Fangrolle (Druck)"],
                                           "max_n": 97.9}]},
        "handrechnung": {"b_mm": 169.3, "h_mm": 117.8, "a_kipp": 14.1, "kippwinkel": 55.2,
                         "text": "a = g · b / h = 9,81 · 169 / 118 = 14,1 m/s²"},
        "verlauf": {"zeit": [0.0, 0.02, 0.04], "kipp": [0.0, 0.4, 1.68], "abheben": [0.0, 4.1, 16.6],
                    "weg": [0.0, 0.02, 0.035], "fuehrung": [0.0, -120.0, -190.0],
                    "ladung": {"Bowlingball": {"laengs": [0.0, 12.0, 46.4], "hebt": [0.0, 5.0, 30.5]}},
                    "kraefte": {"Bowlingball ↔ Kugelschieber/Fangrolle (Druck)": [0.0, 40.0, 97.9]}},
        "pfeile": [[], [{"punkt": [700.0, -344.0, 60.0], "kraft": [-30.0, 0.0, 28.0],
                         "paar": ["Kugelschieber/Fangrolle (Druck)", "Bowlingball"]}],
                   [{"punkt": [700.0, -344.0, 60.0], "kraft": [-70.0, 0.0, 68.0],
                     "paar": ["Kugelschieber/Fangrolle (Druck)", "Bowlingball"]},
                    {"punkt": [705.0, -344.0, 0.0], "kraft": [0.0, 0.0, 156.5],
                     "paar": ["Boden", "Kugelschieber/Fangrolle (Druck)"]}]],
        "ms": {"ablauf": 96.9, "suche": 1248.6, "varianten": 56, "gesamt": 1469.4},
        "urteile": urteile,
    }
    b["szenarien"].append({
        "name": "Bremsen aus 1 m/s", "szenario": {"art": "dynamisch", "quelle": "agent",
                                                  "beschreibung": "mit 1 m/s schieben, abrupt bremsen"},
        "ampel": "rot", "ziel": 3.0, "text": ablauf["text"],
        "kennzahlen": {"sicherheit": 8.4, "knicken": None, "kippreserve": 0.25, "rutschreserve": 0.59,
                       "durchbiegung_mm": None, "durchbiegung_grenze_mm": None, "verformung_max_mm": 0.0,
                       "kippwinkel_max": 1.68, "abheben_max_mm": 16.6},
        "urteile": urteile, "teile": [], "staebe": [], "auflager": [], "ueberhoehung": 1.0, "s0": {"kippen": []},
        "ablauf": ablauf})
    b["aktiv"] = "Bremsen aus 1 m/s"
    b["grenzen"] = list(b["grenzen"]) + ["Ablauf (S2) mit Starrkörpern: keine Verformung, kein Federn der Rohre, "
                                         "Stöße ohne Rückprall."]
    return b


# ---------------------------------------------------------------------------------------------------------------------
# Phase 7: Renderings (PROTOCOL.md, Abschnitt „Phase 7: Renderings“; PLAN-PHASE7-RENDERINGS.md)
# ---------------------------------------------------------------------------------------------------------------------

RENDER_NACHRICHTEN: dict[str, tuple[str, ...]] = {
    # App → Kernel
    "RENDER_START": ("id", "szene", "ansicht", "kamera", "breite", "hoehe", "qualitaet", "hintergrund", "ziel",
                     "vorschau"),
    "RENDER_CANCEL": ("id", "auftrag"),
    "RENDER_RES": ("reply_to", "ok", "path", "width", "height", "ms", "kamera", "message"),
    "RENDER_SCENE": ("reply_to", "ok", "kamera", "teile", "message"),
    # Kernel → App
    "RENDER_REQ": ("id", "auftrag", "szene", "ansicht", "kamera", "width", "height", "teile", "path", "vorschau"),
    "RENDER_SCENE_REQ": ("id", "auftrag", "ansicht", "kamera", "width", "height"),
    "RENDER_STATUS": ("auftrag", "zustand", "qualitaet", "szene", "fortschritt", "text", "pfad", "width", "height",
                      "ms", "von", "vorschau", "fehler"),
}
RENDER_ZUSTAENDE: tuple[str, ...] = ("wartet", "laeuft", "fertig", "fehler", "abgebrochen")
RENDER_SZENE_FELDER: tuple[str, ...] = ("name", "titel", "licht", "umgebung", "staerke", "drehung", "hintergrund",
                                        "transparent", "boden")
RENDER_PBR_FELDER: tuple[str, ...] = ("name", "basisfarbe", "metallisch", "rauheit", "oberflaeche", "klarlack",
                                      "klarlack_rauheit", "anisotropie", "durchsichtig")
RENDER_KAMERA_FELDER: tuple[str, ...] = ("projection", "position", "target", "up", "fov_deg", "ortho_height_mm")


def render_status(auftrag: str, zustand: str, *, qualitaet: str, szene: str, fortschritt: float = 0.0,
                  text: str = "", pfad: str | None = None, width: int = 0, height: int = 0, ms: int | None = None,
                  von: str = "agent", vorschau: bool = False, fehler: str | None = None,
                  seq: int = 0) -> dict[str, Any]:
    """RENDER_STATUS (Kernel → App): Stand eines Auftrags, bei jedem Wechsel und höchstens alle 0,4 s im Lauf."""
    return {"type": "RENDER_STATUS", "seq": seq, "auftrag": auftrag, "zustand": zustand, "qualitaet": qualitaet,
            "szene": szene, "fortschritt": round(max(0.0, min(1.0, float(fortschritt))), 3), "text": text,
            "pfad": pfad, "width": width, "height": height, "ms": ms, "von": von, "vorschau": vorschau,
            "fehler": fehler}


def check_render_message(header: dict[str, Any]) -> list[str]:
    """Fehler einer Render-Nachricht (leer = gültig)."""
    kind = header.get("type")
    if kind not in RENDER_NACHRICHTEN:
        return [f"type {kind!r} ist keine Render-Nachricht"]
    err = _fehlend(header, RENDER_NACHRICHTEN[kind], kind)
    if kind == "RENDER_STATUS" and header.get("zustand") not in RENDER_ZUSTAENDE:
        err.append(f"zustand {header.get('zustand')!r} unbekannt")
    if kind == "RENDER_REQ":
        err += _fehlend(header.get("szene") or {}, RENDER_SZENE_FELDER, "RENDER_REQ.szene")
        for i, t in enumerate(header.get("teile") or []):
            err += _fehlend(t, RENDER_PBR_FELDER, f"RENDER_REQ.teile[{i}]")
    if kind == "RENDER_SCENE" and header.get("ok"):
        err += _fehlend(header.get("kamera") or {}, RENDER_KAMERA_FELDER, "RENDER_SCENE.kamera")
        for i, t in enumerate(header.get("teile") or []):
            m = t.get("matrix")
            if "name" not in t or not (m is None or (isinstance(m, list) and len(m) == 16)):
                err.append(f"RENDER_SCENE.teile[{i}]: name und matrix (16 Zahlen oder null) erwartet")
    for key in ("width", "height", "breite", "hoehe"):
        v = header.get(key)
        if v is not None and (not isinstance(v, int) or v < 0 or v > 8192):
            err.append(f"{kind}.{key} {v!r} außerhalb von 0 bis 8192")
    return err


def render_beispiele() -> list[tuple[str, dict[str, Any]]]:
    """Beispiel-Nachrichten für Testdateien beider Seiten (tools/make_render_fixtures.py)."""
    szene = {"name": "studio", "titel": "Studio", "licht": "studio", "umgebung": None, "staerke": 1.0, "drehung": 0.0,
             "hintergrund": "#F1F2F4", "transparent": False, "boden": True}
    szene_hdri = {"name": "draussen", "titel": "Draußen", "licht": "umgebung",
                  "umgebung": "/Applications/Kev CAD/umgebungen/garten.hdr", "staerke": 1.0, "drehung": 30.0,
                  "hintergrund": "umgebung", "transparent": False, "boden": True}
    teile = [
        {"name": "Rahmen/Rohr", "basisfarbe": [0.827, 0.839, 0.851], "metallisch": 1.0, "rauheit": 0.42,
         "oberflaeche": "eloxiert", "klarlack": 0.35, "klarlack_rauheit": 0.25, "anisotropie": 0.0,
         "durchsichtig": 0.0, "material": "alu-6060", "quelle": "katalog", "kulisse": False},
        {"name": "Rahmen/Halter (Druck)", "basisfarbe": [0.85, 0.2, 0.15], "metallisch": 0.0, "rauheit": 0.5,
         "oberflaeche": "schichten", "klarlack": 0.0, "klarlack_rauheit": 0.1, "anisotropie": 0.0,
         "durchsichtig": 0.0, "schichthoehe": 0.2, "material": "pla", "quelle": "teilfarbe", "kulisse": False},
        {"name": "Kulisse/Boden", "basisfarbe": [0.9, 0.9, 0.9], "metallisch": 0.0, "rauheit": 0.5,
         "oberflaeche": "glatt", "klarlack": 0.0, "klarlack_rauheit": 0.1, "anisotropie": 0.0, "durchsichtig": 0.0,
         "material": None, "quelle": "ohne_material", "kulisse": True},
    ]
    kamera = {"projection": "perspective", "position": [420.0, -510.0, 360.0], "target": [0.0, 0.0, 40.0],
              "up": [0.0, 0.0, 1.0], "fov_deg": 26.0, "ortho_height_mm": None, "name": None}
    return [
        ("render_start", {"type": "RENDER_START", "seq": 1, "id": "a-41", "szene": "studio", "ansicht": "aktuell",
                          "kamera": None, "breite": 1920, "hoehe": 1080, "qualitaet": "schnell", "hintergrund": None,
                          "ziel": None, "vorschau": False}),
        ("render_start_foto", {"type": "RENDER_START", "seq": 2, "id": "a-42", "szene": "draussen",
                               "ansicht": "produkt", "kamera": "Kamera/FX6", "breite": 3840, "hoehe": 2160,
                               "qualitaet": "foto", "hintergrund": "transparent", "ziel": "titel.png",
                               "vorschau": False}),
        ("render_cancel", {"type": "RENDER_CANCEL", "seq": 3, "id": "a-43", "auftrag": "R-7"}),
        ("render_req", {"type": "RENDER_REQ", "seq": 31, "id": "k-80", "auftrag": "R-6", "szene": szene,
                        "ansicht": "aktuell", "kamera": None, "width": 1920, "height": 1080, "teile": teile,
                        "path": "/Users/kevin/Documents/Kev CAD/Halter/output/renders/Halter_studio_schnell.png",
                        "vorschau": False}),
        ("render_req_hdri", {"type": "RENDER_REQ", "seq": 32, "id": "k-81", "auftrag": "R-8", "szene": szene_hdri,
                             "ansicht": "produkt", "kamera": "Kamera/FX6", "width": 960, "height": 540,
                             "teile": teile[:1], "path": "/tmp/vorschau-schnell.png", "vorschau": True}),
        ("render_res", {"type": "RENDER_RES", "seq": 5, "reply_to": "k-80", "ok": True,
                        "path": "/Users/kevin/Documents/Kev CAD/Halter/output/renders/Halter_studio_schnell.png",
                        "width": 1920, "height": 1080, "ms": 840, "kamera": kamera, "message": None,
                        "phasen": {"netze_ms": 120, "umgebung_ms": 310, "rendern_ms": 330, "png_ms": 80}}),
        ("render_scene_req", {"type": "RENDER_SCENE_REQ", "seq": 33, "id": "k-82", "auftrag": "R-9",
                              "ansicht": "iso", "kamera": None, "width": 2400, "height": 1600,
                              "kulisse": ["Kulisse/Boden"]}),
        ("render_scene", {"type": "RENDER_SCENE", "seq": 6, "reply_to": "k-82", "ok": True, "kamera": kamera,
                          "teile": [{"name": "Rahmen/Rohr", "matrix": None},
                                    {"name": "Rahmen/Halter (Druck)",
                                     "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 25.5, 1]}],
                          "message": None}),
        ("render_status_laeuft", render_status("R-9", "laeuft", qualitaet="foto", szene="studio", fortschritt=0.42,
                                               text="Probe 54 von 128", width=2400, height=1600, von="app",
                                               seq=34)),
        ("render_status_fertig", render_status("R-9", "fertig", qualitaet="foto", szene="studio", fortschritt=1.0,
                                               text="fertig in 74 s",
                                               pfad="/Users/kevin/Documents/Kev CAD/Halter/output/renders/x.png",
                                               width=2400, height=1600, ms=74210, von="app", seq=35)),
        ("render_status_fehler", render_status("R-10", "fehler", qualitaet="foto", szene="werkstatt",
                                               text="Blender fehlt", fehler="Blender fehlt (erwartet unter "
                                               "/Applications/Blender.app)", von="agent", seq=36)),
    ]


# Statik Stufe 3 (Festkörper-FEM): STATICS_FIELD (Kernel → App), siehe PROTOCOL.md „Festkörper (Stufe 3)“


def pack_statics_feld(kopf: dict[str, Any], felder: dict[str, Any], *, run: int, seq: int = 0
                      ) -> tuple[dict[str, Any], bytes]:
    """STATICS_FIELD: Oberflächennetz eines Teils mit Ausnutzung, von-Mises-Spannung und Verschiebung je Punkt.
    ``kopf``: ``szenario``, ``teil``, ``feld`` (Schlüssel wie in ``festkoerper.teile[i].feld``), dazu ``ziel``,
    ``sicherheit``, ``ampel``, ``spannung_max``, ``verformung_max_mm``, ``ueberhoehung``. Nutzlast: Felder in der
    Reihenfolge von ``STATIK_FELD_ARRAYS``, little-endian, ohne Lücken."""
    import numpy as np

    teile = []
    n = int(np.asarray(felder["punkte"]).reshape(-1, 3).shape[0])
    m = int(np.asarray(felder["dreiecke"]).reshape(-1, 3).shape[0])
    for name, typ, breite in STATIK_FELD_ARRAYS:
        a = np.ascontiguousarray(np.asarray(felder[name]), dtype=typ).reshape(-1)
        soll = (m if name == "dreiecke" else n) * breite
        if a.size != soll:
            raise ValueError(f"STATICS_FIELD: {name} hat {a.size} Werte, erwartet {soll}")
        teile.append(a.tobytes())
    zusatz = [z for z in (kopf.get("zusatz") or [z for z in STATIK_FELD_ZUSATZ if z in felder]) if z in felder]
    for name in zusatz:  # Stufe 4 (additiv)
        a = np.ascontiguousarray(np.asarray(felder[name]), dtype="<f4").reshape(-1)
        if a.size != n:
            raise ValueError(f"STATICS_FIELD: {name} hat {a.size} Werte, erwartet {n}")
        teile.append(a.tobytes())
    header = {"type": "STATICS_FIELD", "seq": seq, "run": int(run),
              **{k: kopf.get(k) for k in ("szenario", "teil", "feld", "ziel", "sicherheit", "ampel", "spannung_max",
                                         "verformung_max_mm", "ueberhoehung")},
              "werte": "ausnutzung", "punkte": n, "dreiecke": m}
    if zusatz:
        header["zusatz"] = list(zusatz)
        header["zusatz_max"] = {z: round(float(np.max(felder[z])) if n else 0.0, 6) for z in zusatz}
        if kopf.get("verfahren"):
            header["verfahren"] = kopf["verfahren"]
    return header, b"".join(teile)


def unpack_statics_feld(header: dict[str, Any], payload: bytes) -> dict[str, Any]:
    import numpy as np

    n, m = int(header["punkte"]), int(header["dreiecke"])
    out: dict[str, Any] = {}
    pos = 0
    for name, typ, breite in STATIK_FELD_ARRAYS:
        k = (m if name == "dreiecke" else n) * breite
        a = np.frombuffer(payload, dtype=typ, count=k, offset=pos)
        pos += a.nbytes
        out[name] = a.reshape(-1, breite) if breite > 1 else a
    for name in header.get("zusatz") or []:  # Stufe 4 (additiv)
        a = np.frombuffer(payload, dtype="<f4", count=n, offset=pos)
        pos += a.nbytes
        out[name] = a
    if pos != len(payload):
        raise ValueError(f"STATICS_FIELD: Nutzlast {len(payload)} Byte, erwartet {pos}")
    return out


def check_statics_feld(header: dict[str, Any], payload: bytes) -> list[str]:
    """Fehler einer STATICS_FIELD-Nachricht (leer = gültig)."""
    err = _fehlend(header, ("run", "szenario", "teil", "feld", "punkte", "dreiecke"), "STATICS_FIELD")
    if err:
        return err
    try:
        f = unpack_statics_feld(header, payload)
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]
    if len(f["dreiecke"]) and int(f["dreiecke"].max()) >= int(header["punkte"]):
        err.append("STATICS_FIELD: Dreieck zeigt auf einen Punkt, den es nicht gibt")
    if header.get("ampel") is not None and header["ampel"] not in STATIK_AMPELN:
        err.append(f"STATICS_FIELD: Ampel {header['ampel']!r} unbekannt")
    for z in header.get("zusatz") or []:
        if z not in STATIK_FELD_ZUSATZ:
            err.append(f"STATICS_FIELD: Zusatzwert {z!r} unbekannt")
    return err


def statik_beispiel_feld() -> tuple[dict[str, Any], dict[str, Any]]:
    """Kleines Feld für Testdateien: Quader 80 × 20 × 8 mm (Wandhalter) als 8 Punkte und 12 Dreiecke, Ausnutzung von
    der Wand (2,1) zur Spitze (0) fallend, Spitze 2,4 mm nach unten verschoben."""
    import numpy as np

    p = np.array([[x, y, z] for z in (96.0, 104.0) for y in (-10.0, 10.0) for x in (0.0, 80.0)], dtype=np.float32)
    tri = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                    [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]], dtype=np.uint32)
    aus = np.where(p[:, 0] < 1, 2.1, 0.0).astype(np.float32)
    vm = (aus / 4.0 * 34.0).astype(np.float32)
    v = np.zeros((8, 3), dtype=np.float32)
    v[p[:, 0] > 1, 2] = -2.4
    kopf = {"szenario": "Haken 2 kg", "teil": "Wandhalter (Druck)", "feld": "d0f84561664942f7ae15", "ziel": 4.0,
            "sicherheit": 1.87, "ampel": "rot", "spannung_max": 7.05, "verformung_max_mm": 2.43, "ueberhoehung": 2.6}
    return kopf, {"punkte": p, "dreiecke": tri, "ausnutzung": aus, "spannung": vm, "verschiebung": v}


def statik_beispiel_feld_s4() -> tuple[dict[str, Any], dict[str, Any]]:
    """Feld der Stufe 4: wie ``statik_beispiel_feld`` plus Kontaktdruck (an der Wand), plastische Dehnung (an der
    Kante), Klaffen und Schlupf (Testdatei ``statics_feld_s4.frame``)."""
    import numpy as np

    kopf, f = statik_beispiel_feld()
    p = f["punkte"]
    wand = p[:, 0] < 1
    f = {**f, "kontaktdruck": np.where(wand & (p[:, 2] < 100), 6.5, 0.0).astype(np.float32),
         "plast_dehnung": np.where(wand & (p[:, 2] > 100), 0.004, 0.0).astype(np.float32),
         "klaffen": np.where(wand & (p[:, 2] > 100), 0.08, 0.0).astype(np.float32),
         "schlupf": np.where(wand, 0.01, 0.0).astype(np.float32)}
    kopf = {**kopf, "feld": "s4a8b3c2d1e0f9a8b7c6", "verfahren": "ccx", "zusatz": list(STATIK_FELD_ZUSATZ),
            "szenario": "Haken 2 kg (Kontakt)"}
    return kopf, f


def statik_beispiel_s4() -> dict[str, Any]:
    """Wie ``statik_beispiel_festkoerper`` plus ein Szenario mit einem Teil der Stufe 4 (CalculiX): Kontakt mit der
    Wand (klafft oben), plastisch, Traglast (Testdatei ``statics_s4.frame``)."""
    b = statik_beispiel_festkoerper()
    kopf, _ = statik_beispiel_feld_s4()
    teil = {"teil": "Wandhalter (Druck)", "stand": "done", "ampel": "gelb", "sicherheit": 6.2, "ziel": 4.0,
            "ausnutzung": 0.645, "spannung_max": 31.4, "kriterium": "mises", "ort": [0.0, -10.0, 104.0],
            "sicherheit_lagerrand": 1.1, "verformung_max_mm": 2.61, "kragtraeger": 1.98, "druckteil": True,
            "q": 0.4, "ausrichtungen": {}, "ausrichtung_beste": None,
            "netz": {"tetraeder": 1820, "freiheitsgrade": 31250, "h_mm": 2.5}, "ms": 18400.0, "feld": kopf["feld"],
            "aus_speicher": False, "verfahren": "ccx", "sicherheit_last": 1.12,
            "kontakt": {"paare": [{"mit": "Wand", "rolle": "lager", "reibwert": 0.4, "druck_max": 6.5,
                                   "kraft_n": 61.0, "traegt_mm2": 80.0, "anteil_traegt": 0.5,
                                   "klaffen_max_mm": 0.08, "schlupf_max_mm": 0.01, "reibung_ausnutzung": 0.3,
                                   "gleitet_anteil": 0.0, "quelle": "Berührung (beruehrt)"}],
                        "klemmungen": [{"schraube": "Schraube M4", "kraft_n": 480.0,
                                        "quelle": "handfest angenommen (120 N je mm, M4)"}]},
            "plastisch": {"dehnung_max": 0.004, "bleibend_mm": 0.12, "fliesst": True, "grenzdehnung": 0.02,
                          "fliessgrenze": 34.0, "modell": "Druckteil: ideal plastisch ab der Zugfestigkeit, "
                                                         "Schichtfuge spröde (Näherung)", "ort": [0.0, -10.0, 104.0]},
            "traglast": {"faktor": 6.2, "kriterium": "schicht", "text": "Schichtfuge", "lastfaktor_max": 12.0,
                         "erreicht": 6.3},
            "beulen": None, "rutscht": False,
            "zusatz_max": {"kontaktdruck": 6.5, "plast_dehnung": 0.004, "klaffen": 0.08, "schlupf": 0.01},
            "text": "Wandhalter (Druck) hält knapp (CalculiX, S4): Traglast beim 6,2-Fachen der Last (Schichtfuge); "
                    "fließt: plastische Dehnung 0,4 %, bleibend 0,12 mm."}
    urteil = {"art": "festkoerper", "teil": "Wandhalter (Druck)", "ampel": "gelb", "text": teil["text"],
              "loesung": "", "sicherheit": 6.2, "ziel": 4.0, "ausnutzung": 0.645, "ort": [0.0, -10.0, 104.0]}
    b["szenarien"].append({
        "name": "Haken 2 kg (Kontakt)", "szenario": {"art": "statisch", "quelle": "agent", "beschreibung": None},
        "ampel": "gelb", "ziel": 2.0, "text": "Haken 2 kg (Kontakt): gelb – Wandhalter (Druck) hält knapp",
        "kennzahlen": {"sicherheit": 6.2, "knicken": None, "kippreserve": None, "rutschreserve": None,
                       "durchbiegung_mm": None, "durchbiegung_grenze_mm": None, "verformung_max_mm": 2.61},
        "urteile": [urteil],
        "teile": [{"name": "Wandhalter (Druck)", "ausnutzung": 0.645, "ampel": "gelb", "verformung_mm": 2.61,
                   "sicherheit": 6.2, "fem": True}],
        "staebe": [], "auflager": [], "ueberhoehung": 1.0, "s0": {"kippen": []},
        "festkoerper": {"stand": "done", "fortschritt": 1.0, "text": "1 Teil gerechnet", "meldung": None,
                        "teile": [teil]}})
    b["aktiv"] = "Haken 2 kg (Kontakt)"
    b["grenzen"] = list(b["grenzen"]) + ["CalculiX (S4): Kontakt nach dem Strafverfahren, kleine Verformungen."]
    return b


def statik_beispiel_festkoerper() -> dict[str, Any]:
    """Wie ``statik_beispiel`` plus ein Szenario „Haken 2 kg“ mit Festkörper (S3): ein Druckteil, rot, gerechnet;
    dazu läuft der Festkörper von „Aufstützen 30 kg“ noch (Testdatei ``statics_festkoerper.frame``)."""
    b = statik_beispiel()
    kopf, _ = statik_beispiel_feld()
    teil = {"teil": "Wandhalter (Druck)", "stand": "done", "ampel": "rot", "sicherheit": 1.87, "ziel": 4.0,
            "ausnutzung": 2.14, "spannung_max": 7.05, "kriterium": "schicht", "ort": [3.7, -2.4, 104.0],
            "sicherheit_lagerrand": 1.52, "verformung_max_mm": 2.43, "kragtraeger": 1.98,
            "druckteil": True, "q": 0.4, "ausrichtungen": {"-z": 4.82, "-y": 4.82, "-x": 1.87},
            "ausrichtung_beste": "-z", "netz": {"tetraeder": 535, "freiheitsgrade": 3543, "h_mm": 5.33},
            "ms": 1960.0, "feld": kopf["feld"], "aus_speicher": False,
            "text": "Wandhalter (Druck) hält nicht (FEM): Sicherheit 1,87 (Ziel 4, Druckteil)"}
    urteil = {"art": "festkoerper", "teil": "Wandhalter (Druck)", "ampel": "rot",
              "text": "Wandhalter (Druck) hält nicht (Festkörper-FEM): Sicherheit 1,87 (Ziel 4, Druckteil), "
                      "Schichtfuge maßgebend (nur 40 % der Festigkeit quer zur Schicht); Kragträger S0: 1,98.",
              "loesung": "Drehen: mit lager.druckteil(…, ausrichtung=\"-z\") Sicherheit 4,82 statt 1,87 (FEM); "
                         "oder verstärken: bei (4; −2; 104) in Lastrichtung um etwa 46 % höher",
              "sicherheit": 1.87, "ziel": 4.0, "ausnutzung": 2.14, "ort": [3.7, -2.4, 104.0], "schichtfaktor": 0.4,
              "quer_zur_schicht": True}
    b["szenarien"].append({
        "name": "Haken 2 kg", "szenario": {"art": "statisch", "quelle": "modell", "beschreibung": None},
        "ampel": "rot", "ziel": 2.0, "text": "Haken 2 kg: rot – Wandhalter (Druck) hält nicht (Sicherheit 1,87)",
        "kennzahlen": {"sicherheit": 1.87, "knicken": None, "kippreserve": None, "rutschreserve": None,
                       "durchbiegung_mm": None, "durchbiegung_grenze_mm": None, "verformung_max_mm": 2.43},
        "urteile": [urteil],
        "teile": [{"name": "Wandhalter (Druck)", "ausnutzung": 2.14, "ampel": "rot", "verformung_mm": 2.43,
                   "sicherheit": 1.87}],
        "staebe": [], "auflager": [], "ueberhoehung": 1.0, "s0": {"kippen": []},
        "festkoerper": {"stand": "done", "fortschritt": 1.0, "text": "1 Teil gerechnet", "meldung": None,
                        "teile": [teil]}})
    for e in b["szenarien"]:
        if e["name"] == "Aufstützen 30 kg":
            e["festkoerper"] = {"stand": "laeuft", "fortschritt": 0.45, "text": "Rahmen/Halter (Druck): lösen",
                                "meldung": None, "teile": [{"teil": "Rahmen/Halter (Druck)", "stand": "laeuft"}]}
    b["aktiv"] = "Haken 2 kg"
    b["grenzen"] = list(b["grenzen"]) + ["Festkörper (S3) linear-elastisch mit kleinen Verformungen."]
    return b


# Topologieoptimierung (PLAN-TOPOLOGIE.md): TOPO und TOPO_FIELD (Kernel → App), TOPO_START, TOPO_CANCEL, TOPO_APPLY
# (App → Kernel), siehe PROTOCOL.md „Topologie“. Rein additiv; ältere Gegenseiten ignorieren die Typen.

TOPO_STAENDE = ("laeuft", "done", "failed", "abgebrochen")
TOPO_FELDER = ("stand", "auftrag", "teil", "szenario", "einstellungen", "fortschritt", "phase", "text", "text_lang",
               "iteration", "max_iter", "verlauf", "voxel", "h_mm", "kennzahlen", "schutz", "netz", "gitter",
               "druckpruefung", "hinweise", "grenzen", "meldung", "ergebnis", "quelle", "modell_schluessel",
               "behalten_wirksam", "optimierung", "ms", "berechnet")
TOPO_FELD_ARTEN = ("dichte", "schutz", "koerper", "vorher", "nachher")
TOPO_FELD_KOPF = ("art", "auftrag", "teil", "iteration", "sicherheit", "ziel", "spannung_max", "verformung_max_mm",
                  "ueberhoehung")
TOPO_APP = ("TOPO_START", "TOPO_CANCEL", "TOPO_APPLY")


def _json_rein(x: Any) -> Any:
    """Zahlen aus numpy und nicht endliche Werte JSON-tauglich machen (NaN/inf → None)."""
    import math

    if isinstance(x, dict):
        return {str(k): _json_rein(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_rein(v) for v in x]
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            x = x.item()
        except Exception:  # noqa: BLE001
            pass
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def pack_topo(stand: dict[str, Any], *, run: int, seq: int = 0) -> dict[str, Any]:
    """Kopf von TOPO (ohne Nutzlast): Stand der Topologieoptimierung (``topologie/laufzeit.py``)."""
    head = {"type": "TOPO", "seq": seq, "run": int(run)}
    for k in TOPO_FELDER:
        head[k] = _json_rein(stand.get(k))
    head["stand"] = head["stand"] or "laeuft"
    if head["fortschritt"] is None:
        head["fortschritt"] = 0.0
    return head


def check_topo_message(header: dict[str, Any]) -> list[str]:
    """Fehler einer TOPO-Nachricht (leer = gültig)."""
    err = _fehlend(header, ("type", "run", "stand", "teil", "fortschritt"), "TOPO")
    if err:
        return err
    if header["type"] != "TOPO":
        err.append("type ist nicht TOPO")
    if header["stand"] not in TOPO_STAENDE:
        err.append(f"TOPO: stand {header['stand']!r} unbekannt")
    f = header.get("fortschritt")
    if f is not None and not (0.0 <= float(f) <= 1.0):
        err.append("TOPO: fortschritt außerhalb 0…1")
    kz = header.get("kennzahlen")
    if header["stand"] == "done":
        if not isinstance(kz, dict) or not isinstance(kz.get("vorher"), dict) or not isinstance(kz.get("nachher"), dict):
            err.append("TOPO: done ohne kennzahlen.vorher/nachher")
        if not isinstance(header.get("ergebnis"), dict) or not header["ergebnis"].get("datei"):
            err.append("TOPO: done ohne ergebnis.datei")
    for i, v in enumerate(header.get("verlauf") or []):
        if not isinstance(v, dict) or "i" not in v:
            err.append(f"TOPO: verlauf[{i}] ohne i")
            break
    return err


def topo_feld_arrays(werte: str | None) -> tuple[tuple[str, str, int], ...]:
    """Reihenfolge der Nutzlast von TOPO_FIELD: immer Punkte und Dreiecke, bei ``werte`` "ausnutzung" (Felder der
    Festkörper-FEM vorher und nachher) dazu Ausnutzung, Spannung und Verschiebung wie bei STATICS_FIELD."""
    return STATIK_FELD_ARRAYS if werte == "ausnutzung" else STATIK_FELD_ARRAYS[:2]


def pack_topo_feld(kopf: dict[str, Any], felder: dict[str, Any], *, seq: int = 0) -> tuple[dict[str, Any], bytes]:
    """TOPO_FIELD: Netz in Weltkoordinaten (Dichte einer Iteration, Schutzzonen, Körper, Festkörperfeld vorher und
    nachher). ``kopf``: ``art`` (TOPO_FELD_ARTEN) und Angaben aus TOPO_FELD_KOPF; ``felder``: ``punkte``,
    ``dreiecke`` und bei vorher/nachher ``ausnutzung``, ``spannung``, ``verschiebung``."""
    import numpy as np

    art = kopf.get("art")
    if art not in TOPO_FELD_ARTEN:
        raise ValueError(f"TOPO_FIELD: art {art!r} unbekannt")
    werte = "ausnutzung" if art in ("vorher", "nachher") and "ausnutzung" in felder else None
    n = int(np.asarray(felder["punkte"]).reshape(-1, 3).shape[0])
    m = int(np.asarray(felder["dreiecke"]).reshape(-1, 3).shape[0])
    teile = []
    for name, typ, breite in topo_feld_arrays(werte):
        a = np.ascontiguousarray(np.asarray(felder[name]), dtype=typ).reshape(-1)
        soll = (m if name == "dreiecke" else n) * breite
        if a.size != soll:
            raise ValueError(f"TOPO_FIELD: {name} hat {a.size} Werte, erwartet {soll}")
        teile.append(a.tobytes())
    header = {"type": "TOPO_FIELD", "seq": seq, **{k: _json_rein(kopf.get(k)) for k in TOPO_FELD_KOPF},
              "werte": werte, "punkte": n, "dreiecke": m}
    return header, b"".join(teile)


def unpack_topo_feld(header: dict[str, Any], payload: bytes) -> dict[str, Any]:
    import numpy as np

    n, m = int(header["punkte"]), int(header["dreiecke"])
    out: dict[str, Any] = {}
    pos = 0
    for name, typ, breite in topo_feld_arrays(header.get("werte")):
        k = (m if name == "dreiecke" else n) * breite
        a = np.frombuffer(payload, dtype=typ, count=k, offset=pos)
        pos += a.nbytes
        out[name] = a.reshape(-1, breite) if breite > 1 else a
    if pos != len(payload):
        raise ValueError(f"TOPO_FIELD: Nutzlast {len(payload)} Byte, erwartet {pos}")
    return out


def check_topo_feld(header: dict[str, Any], payload: bytes) -> list[str]:
    """Fehler einer TOPO_FIELD-Nachricht (leer = gültig)."""
    err = _fehlend(header, ("art", "punkte", "dreiecke"), "TOPO_FIELD")
    if err:
        return err
    if header["art"] not in TOPO_FELD_ARTEN:
        err.append(f"TOPO_FIELD: art {header['art']!r} unbekannt")
    try:
        f = unpack_topo_feld(header, payload)
    except Exception as exc:  # noqa: BLE001
        return err + [str(exc)]
    if len(f["dreiecke"]) and int(f["dreiecke"].max()) >= int(header["punkte"]):
        err.append("TOPO_FIELD: Dreieck zeigt auf einen Punkt, den es nicht gibt")
    return err


def check_topo_app(header: dict[str, Any]) -> list[str]:
    """Fehler einer Anfrage der App (TOPO_START, TOPO_CANCEL, TOPO_APPLY)."""
    t = header.get("type")
    if t not in TOPO_APP:
        return [f"type {t!r} ist keine Topologie-Anfrage"]
    err = []
    if t == "TOPO_START":
        b = header.get("behalten")
        if b is not None and not (0.05 <= float(b) <= 0.95):
            err.append("TOPO_START: behalten außerhalb 0,05…0,95")
        if header.get("lager") not in (None, "kontakt", "bohrungen"):
            err.append("TOPO_START: lager ist kontakt oder bohrungen")
        # additiv (Simulation): Schutzzonen je Art abwählbar, Schutzflächen per Klick
        for k in ("bohrungen", "einsaetze", "kontakt", "bett"):
            if header.get(k) is not None and not isinstance(header.get(k), bool):
                err.append(f"TOPO_START: {k} ist ein Wahrheitswert")
        s = header.get("schutz")
        if s is not None and (not isinstance(s, list) or any(not isinstance(z, dict) or z.get("index") is None
                                                             for z in s)):
            err.append("TOPO_START: schutz ist eine Liste von {\"art\": \"index\", \"index\": n}")
    return err


def topo_beispiel(stand: str = "done") -> dict[str, Any]:
    """Stand für Testdateien: Winkelhalter wie im Reel, 42 % behalten (Zahlen gerundet aus dem Nachweis in
    PLAN-TOPOLOGIE.md)."""
    basis = {"auftrag": 3, "teil": "Halter", "szenario": "Bolzen 50 N", "quelle": "app",
             "einstellungen": {"behalten": 0.42, "ueberhang": False, "fein": False, "steg": 6, "bett": False,
                               "bohrungen": True, "einsaetze": True, "kontakt": True, "iterationen": 60,
                               "lager": "kontakt"},
             "max_iter": 60, "voxel": 59804, "h_mm": 0.947}
    if stand == "laeuft":
        return {**basis, "stand": "laeuft", "fortschritt": 0.41, "phase": "optimieren", "iteration": 12,
                "text": "Iteration 12: Nachgiebigkeit 15 %, Volumen 42 %",
                "verlauf": [{"i": 1, "c": 568.0, "volumen": 0.56, "grau": 0.62},
                            {"i": 12, "c": 85.3, "volumen": 0.42, "grau": 0.31}]}
    return {**basis, "stand": "done", "fortschritt": 1.0, "phase": "fertig", "iteration": 25, "text": "fertig",
            "verlauf": [{"i": 1, "c": 568.0, "volumen": 0.56, "grau": 0.62},
                        {"i": 25, "c": 74.1, "volumen": 0.42, "grau": 0.18}],
            "kennzahlen": {"vorher": {"volumen_mm3": 50908.8, "masse_g": 64.7, "filament_g": 34.1,
                                      "druckzeit_min": 82.6, "sicherheit": 11.8, "ziel": 4.0, "ampel": "gruen",
                                      "spannung_max": 2.1, "verformung_max_mm": 0.18},
                           "nachher": {"volumen_mm3": 21304.5, "masse_g": 27.1, "filament_g": 20.6,
                                       "druckzeit_min": 70.2, "sicherheit": 5.4, "ziel": 4.0, "ampel": "gruen",
                                       "spannung_max": 4.5, "verformung_max_mm": 0.25, "steg_min_mm": 2.4},
                           "ersparnis": {"volumen_prozent": 58.2, "masse_g": 37.6, "filament_g": 13.5,
                                         "druckzeit_min": 12.4}},
            "schutz": {"anteil": 0.12, "zonen": [{"art": "Bohrung", "d": 5.5, "ring_mm": 3.15, "elemente": 768},
                                                 {"art": "Lastfläche", "haut_mm": 2.52, "elemente": 1672}]},
            "netz": {"dreiecke": 8000, "punkte": 3990, "offen": 0},
            "hinweise": [], "grenzen": ["Topologieoptimierung ist eine Näherung, kein Festigkeitsnachweis."],
            "ergebnis": {"datei": "topologie/Halter-1a2b3c4d5e6f.brep", "schluessel": "1a2b3c4d5e6f78901234",
                         "im_modell": False, "aus_projekt": False},
            "text_lang": "Halter: Volumen −58 % (50,9 → 21,3 cm³); Näherung, kein Festigkeitsnachweis."}


def topo_beispiel_feld(art: str = "nachher") -> tuple[dict[str, Any], dict[str, Any]]:
    """Kleines Netz (Quader, 8 Punkte, 12 Dreiecke) als TOPO_FIELD; vorher und nachher mit Ausnutzung."""
    import numpy as np

    kopf_s, felder = statik_beispiel_feld()
    kopf: dict[str, Any] = {"art": art, "auftrag": 3, "teil": "Halter"}
    if art in ("vorher", "nachher"):
        kopf.update({k: kopf_s.get(k) for k in ("sicherheit", "ziel", "spannung_max", "verformung_max_mm")})
        kopf["ueberhoehung"] = 2.6
        return kopf, felder
    if art == "dichte":
        kopf["iteration"] = 12
    return kopf, {"punkte": felder["punkte"], "dreiecke": felder["dreiecke"].astype(np.uint32)}


# Simulation (PLAN-SIMULATION.md): SIM und SIM_JOB (Kernel → App), SIM_REQ, SIM_EDIT, SIM_RUN, SIM_CANCEL (App → Kernel),
# siehe PROTOCOL.md „Simulation“. Rein additiv; ältere Gegenseiten ignorieren die Typen. Inhalt von SIM:
# ``simulation/laufzeit.py`` (``simulation_stand``), Format von simulation.json: ``simulation/datei.py``.

SIM_FELDER = ("run", "stand", "datei", "vorhanden", "lastfaelle", "modell", "lager", "modell_lager", "abgeleitet",
              "topologie", "hinweise", "fehler", "job")
SIM_ZUSTAENDE = ("ok", "neu", "fehlt", "offen")
SIM_JOB_FELDER = ("auftrag", "was", "lastfall", "teil", "grenze", "von", "stand", "fortschritt", "text", "ergebnis",
                  "meldung", "ms", "verfahren")  # verfahren: additiv (simulation2), bei grenze
SIM_JOB_STAENDE = ("laeuft", "done", "failed", "abgebrochen")
SIM_APP = ("SIM_REQ", "SIM_EDIT", "SIM_RUN", "SIM_CANCEL")
SIM_VERFAHREN = ("s0s1", "fem")  # additiv: Grenze suchen mit S0 und S1 bzw. dazu mit der Festkörper-FEM
SIM_GLEITEN = ("flaeche", "richtung")  # additiv: gleitendes Lager in der Fläche oder entlang einer Richtung
SIM_VERTEILUNGEN = ("punkt", "flaeche")  # additiv: Last am Klickpunkt oder auf der ganzen Fläche


def pack_sim(stand: dict[str, Any], *, reply_to: str | None = None, seq: int = 0) -> dict[str, Any]:
    """Kopf von SIM (keine Nutzlast): Lastfälle, Lasten und Lager aus simulation.json mit ihrem Zustand im aktuellen
    Modell, Szenarien und Lager aus model.py, abgeleitete Lager, Topologie-Einstellungen, laufender Auftrag."""
    head: dict[str, Any] = {"type": "SIM", "seq": seq}
    for k in SIM_FELDER:
        head[k] = _json_rein(stand.get(k))
    head["run"] = int(head["run"] or 0)
    head["stand"] = int(head["stand"] or 0)
    for k in ("lastfaelle", "modell", "lager", "modell_lager", "abgeleitet", "hinweise"):
        head[k] = list(head[k] or [])
    head["topologie"] = dict(head["topologie"] or {})
    if reply_to is not None:
        head["reply_to"] = reply_to
    return head


def check_sim_message(header: dict[str, Any]) -> list[str]:
    """Fehler einer SIM-Nachricht (leer = gültig)."""
    err = _fehlend(header, ("type", "run", "stand", "lastfaelle", "lager", "abgeleitet"), "SIM")
    if err:
        return err
    if header["type"] != "SIM":
        err.append("type ist nicht SIM")
    namen = set()
    for i, l in enumerate(header.get("lastfaelle") or []):
        wo = f"SIM.lastfaelle[{i}]"
        err += _fehlend(l, ("name", "art", "lasten"), wo)
        if l.get("name") in namen:
            err.append(f"{wo}: Name {l.get('name')!r} doppelt")
        namen.add(l.get("name"))
        if l.get("art") not in ("statisch", "dynamisch"):
            err.append(f"{wo}.art {l.get('art')!r} unbekannt")
        for j, x in enumerate(l.get("lasten") or []):
            err += _fehlend(x, ("id", "teil", "kraft", "zustand"), f"{wo}.lasten[{j}]")
            if x.get("zustand") not in SIM_ZUSTAENDE:
                err.append(f"{wo}.lasten[{j}].zustand {x.get('zustand')!r} unbekannt")
    for i, x in enumerate(header.get("lager") or []):
        err += _fehlend(x, ("id", "teil", "art", "zustand"), f"SIM.lager[{i}]")
        if x.get("art") not in ("fest", "gelenkig", "gleitend"):
            err.append(f"SIM.lager[{i}].art {x.get('art')!r} unbekannt")
        sz = x.get("szenarien")
        if sz is not None and (not isinstance(sz, list) or not all(isinstance(n, str) for n in sz)):
            err.append(f"SIM.lager[{i}].szenarien: null oder Liste von Namen")
        g = x.get("gleiten")
        if g is not None and (not isinstance(g, dict) or g.get("art") not in SIM_GLEITEN
                              or (g.get("art") == "richtung" and len(g.get("richtung") or []) != 3)):
            err.append(f"SIM.lager[{i}].gleiten: {{art: flaeche}} oder {{art: richtung, richtung: [x, y, z]}}")
    for i, l in enumerate(header.get("lastfaelle") or []):
        for j, x in enumerate(l.get("lasten") or []):
            if x.get("verteilung") not in (None, *SIM_VERTEILUNGEN):
                err.append(f"SIM.lastfaelle[{i}].lasten[{j}].verteilung {x.get('verteilung')!r} unbekannt")
            if x.get("einheit") not in (None, "N", "kg", "N/mm2"):
                err.append(f"SIM.lastfaelle[{i}].lasten[{j}].einheit {x.get('einheit')!r} unbekannt")
    for i, a in enumerate(header.get("abgeleitet") or []):
        err += _fehlend(a, ("id", "art", "teil", "aktiv"), f"SIM.abgeleitet[{i}]")
    return err


def pack_sim_job(job: dict[str, Any], *, seq: int = 0) -> dict[str, Any]:
    """Kopf von SIM_JOB: Stand eines Auftrags aus dem Bereich Simulation (Rechnen, Festigkeit, Ablauf, Grenze)."""
    head: dict[str, Any] = {"type": "SIM_JOB", "seq": seq}
    for k in SIM_JOB_FELDER:
        head[k] = _json_rein(job.get(k))
    head["stand"] = head["stand"] or "laeuft"
    return head


def check_sim_job(header: dict[str, Any]) -> list[str]:
    err = _fehlend(header, ("type", "auftrag", "was", "stand"), "SIM_JOB")
    if err:
        return err
    if header["stand"] not in SIM_JOB_STAENDE:
        err.append(f"SIM_JOB: stand {header['stand']!r} unbekannt")
    if header.get("was") not in ("rechnen", "festigkeit", "ablauf", "grenze"):
        err.append(f"SIM_JOB: was {header.get('was')!r} unbekannt")
    f = header.get("fortschritt")
    if f is not None and not 0.0 <= float(f) <= 1.0:
        err.append("SIM_JOB: fortschritt außerhalb 0…1")
    return err


def check_sim_app(header: dict[str, Any]) -> list[str]:
    """Fehler einer Anfrage der App (SIM_REQ, SIM_EDIT, SIM_RUN, SIM_CANCEL)."""
    t = header.get("type")
    if t not in SIM_APP:
        return [f"type {t!r} ist keine Simulations-Anfrage"]
    err: list[str] = []
    if t == "SIM_EDIT":
        ops = header.get("ops")
        if not isinstance(ops, list) or not ops:
            err.append("SIM_EDIT: ops (Liste von Operationen) fehlt")
        else:
            from kevcad_kernel.simulation.datei import OPS

            for i, op in enumerate(ops):
                if not isinstance(op, dict) or op.get("op") not in OPS:
                    err.append(f"SIM_EDIT: ops[{i}] unbekannt")
    if t == "SIM_RUN":
        if header.get("was") not in ("rechnen", "festigkeit", "ablauf", "grenze"):
            err.append(f"SIM_RUN: was {header.get('was')!r} unbekannt")
        if header.get("was") == "grenze" and header.get("grenze") not in ("last", "neigung", "geschwindigkeit"):
            err.append("SIM_RUN: grenze ist last, neigung oder geschwindigkeit")
        # additiv: Verfahren der Grenzsuche (S0 und S1, oder dazu die Festkörper-FEM)
        if header.get("verfahren") not in (None, *SIM_VERFAHREN):
            err.append(f"SIM_RUN: verfahren ist {' oder '.join(SIM_VERFAHREN)}")
        if header.get("verfahren") == "fem" and header.get("grenze") == "geschwindigkeit":
            err.append("SIM_RUN: „wie schnell“ sucht der Ablauf (S2), nicht die FEM")
    return err


def sim_beispiel() -> dict[str, Any]:
    """Stand für Testdateien: ein Lastfall der App mit einer Last auf einer Fläche (zugeordnet) und einer nicht mehr
    zuordenbaren, ein festes Lager, ein Lastfall aus model.py (ersetzt), ein abgeleitetes Lager (aus)."""
    ort = {"flaeche": 5, "punkt": [40.0, 0.0, 60.0], "normale": [0.0, 0.0, 1.0],
           "signatur": {"t": "plane", "a": 800.0, "n": [0.0, 0.0, 1.0], "c": [40.0, 0.0, 60.0]}}
    return {
        "run": 7, "stand": 3, "datei": "simulation.json", "vorhanden": True,
        "lastfaelle": [{
            "name": "Aufstützen 30 kg", "art": "statisch", "beschreibung": "Kevin stützt sich auf", "kopie_von": None,
            "neigung": {"grad": 5.0, "richtung": "+y"}, "beschleunigung": None,
            "fahrt": None, "stoss": None, "untergrund": "holz", "ziel": {"sicherheit": 2.5, "durchbiegung": 300.0},
            "ampel": "gelb", "text": "Aufstützen 30 kg: gelb – Halter hält knapp (Sicherheit 3,1)", "gerechnet": True,
            "lasten": [
                {"id": "L1", "teil": "Halter", "gegen": None, "ort": ort, "richtung": {"art": "normale"},
                 "betrag": 30.0, "einheit": "kg", "kraft": [0.0, 0.0, -294.3], "zustand": "ok", "zustand_text": "",
                 "kraft_wirksam": [0.0, 0.0, -294.3], "punkt_wirksam": [40.0, 0.0, 60.0],
                 "normale_wirksam": [0.0, 0.0, 1.0], "flaeche_wirksam": 5},
                {"id": "L2", "teil": "Halter", "gegen": "Bolzen",
                 "ort": {"flaeche": 9, "punkt": [10.0, 0.0, 30.0], "normale": None, "signatur": None},
                 "richtung": {"art": "frei", "azimut": 0.0, "hoehe": -30.0}, "betrag": 50.0, "einheit": "N",
                 "kraft": [43.3, 0.0, -25.0], "zustand": "fehlt",
                 "zustand_text": "Fläche 9 (Zylinder, 120 mm²) passt zu keiner Fläche des Teils mehr",
                 "kraft_wirksam": None, "punkt_wirksam": None, "normale_wirksam": None, "flaeche_wirksam": None},
                {"id": "L3", "teil": "Halter", "gegen": None, "verteilung": "flaeche", "ort": ort,
                 "richtung": {"art": "normale"}, "betrag": 0.05, "einheit": "N/mm2", "kraft": [0.0, 0.0, -40.0],
                 "zustand": "ok", "zustand_text": "", "kraft_wirksam": [0.0, 0.0, -40.0],
                 "punkt_wirksam": [40.0, 0.0, 60.0], "normale_wirksam": [0.0, 0.0, 1.0], "flaeche_wirksam": 5,
                 "flaeche_mm2_wirksam": 800.0}]},
            {"name": "Bremsen aus 1 m/s", "art": "dynamisch", "beschreibung": "", "kopie_von": "Bremsen",
             "neigung": None, "beschleunigung": None,
             "fahrt": {"geschwindigkeit": 1.0, "bremsen": "abrupt", "dauer": None, "animation": None,
                       "angriff": "boden", "fahrtrichtung": "+x", "antrieb": None},
             "stoss": None, "untergrund": None, "ziel": None, "ampel": "rot", "text": "", "gerechnet": True,
             "lasten": []}],
        "modell": [{"name": "Eigengewicht", "quelle": "standard", "art": "statisch", "zeile": None, "ampel": "gruen",
                    "text": "", "beschreibung": "nur das eigene Gewicht", "dynamisch": False, "ersetzt": False},
                   {"name": "Aufstützen 30 kg", "quelle": "modell", "art": "statisch", "zeile": 12, "ampel": None,
                    "text": "", "beschreibung": None, "dynamisch": False, "ersetzt": True}],
        "lager": [{"id": "A1", "teil": "Halter", "art": "fest", "auf": "flaeche",
                   "ort": {"flaeche": 2, "punkt": [0.0, 0.0, 30.0], "normale": [-1.0, 0.0, 0.0], "signatur": None},
                   "szenarien": None,
                   "zustand": "neu", "zustand_text": "Fläche 3 → 2", "punkt_wirksam": [0.0, 0.0, 30.0],
                   "normale_wirksam": [-1.0, 0.0, 0.0], "flaeche_wirksam": 2},
                  {"id": "A2", "teil": "Halter", "art": "gleitend", "auf": "flaeche",
                   "ort": {"flaeche": 4, "punkt": [40.0, 0.0, 0.0], "normale": [0.0, 0.0, -1.0], "signatur": None},
                   "szenarien": ["Aufstützen 30 kg"],
                   "gleiten": {"art": "richtung", "richtung": [0.0, 1.0, 0.0], "quelle": "kante", "kante": 7},
                   "zustand": "ok", "zustand_text": "", "punkt_wirksam": [40.0, 0.0, 0.0],
                   "normale_wirksam": [0.0, 0.0, -1.0], "flaeche_wirksam": 4,
                   "gehalten_wirksam": [[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0]]}],
        "modell_lager": [{"id": "M1", "teil": "Platte", "art": "gleitend", "quelle": "modell", "auf": "flaeche",
                          "flaeche": 0, "punkt": [0.0, 0.0, 0.0], "normale": [0.0, 0.0, -1.0], "zeile": 20,
                          "szenarien": None, "gehalten": [[0.0, 0.0, -1.0]],
                          "zustand": "ok", "zustand_text": ""}],
        "abgeleitet": [{"id": "boden:Fuß", "art": "boden", "teil": "Fuß", "text": "Fuß steht auf dem Boden",
                        "punkt": [0.0, 0.0, 0.0], "aktiv": False},
                       {"id": "kontakt:Halter|Wand", "art": "kontakt", "teil": "Halter", "nachbar": "Wand",
                        "text": "Halter wird von Wand gehalten (Kontakt)", "aktiv": True,
                        "szenarien": ["Aufstützen 30 kg"]}],
        "topologie": {"Halter": {"szenario": "Aufstützen 30 kg", "behalten": 0.42, "ueberhang": True,
                                 "bohrungen": True, "einsaetze": False, "kontakt": True,
                                 "schutz": [{"art": "index", "index": 7, "zustand": "ok", "text": ""}]}},
        "hinweise": ["Lastfall „Aufstützen 30 kg“ aus der App ersetzt den gleichnamigen aus model.py (Zeile 12)",
                     "1 Lasten bzw. Lager aus der App sind nicht mehr zuordenbar und zählen nicht mit (L2)"],
        "fehler": None,
        "job": None}


def sim_job_beispiel(stand: str = "done") -> dict[str, Any]:
    """Auftrag für Testdateien: „Grenze suchen“ (Last) fertig bzw. FEM laufend."""
    if stand == "laeuft":
        return {"auftrag": 4, "was": "festigkeit", "lastfall": "Aufstützen 30 kg", "teil": None, "grenze": None,
                "von": "app", "stand": "laeuft", "fortschritt": 0.45, "text": "Halter: lösen", "ergebnis": None,
                "meldung": None, "ms": None}
    return {"auftrag": 5, "was": "grenze", "lastfall": "Aufstützen 30 kg", "teil": None, "grenze": "last",
            "von": "app", "stand": "done", "fortschritt": 1.0, "verfahren": "fem",
            "text": "„Aufstützen 30 kg“ hält bis zum 1,24-fachen (365 N statt 294 N), begrenzt durch Ziel-Sicherheit "
                    "(FEM, Halter)",
            "ergebnis": {"art": "last", "lastfall": "Aufstützen 30 kg", "verfahren": "fem",
                         "massgebend_verfahren": "FEM",
                         "werte": [{"kriterium": "Ziel-Sicherheit", "grenze": 1.24, "einheit": "×", "last_n": 364.9,
                                    "massgebend": "Halter", "verfahren": "FEM",
                                    "text": "Ziel-Sicherheit: bis zum 1,24-fachen der Lasten (FEM)"},
                                   {"kriterium": "Ziel-Sicherheit", "grenze": 1.71, "einheit": "×", "last_n": 503.2,
                                    "massgebend": "Halter", "verfahren": "S0",
                                    "text": "Ziel-Sicherheit: bis zum 1,71-fachen der Lasten (S0)"},
                                   {"kriterium": "Bruch (Sicherheit 1)", "grenze": 3.1, "einheit": "×",
                                    "last_n": 912.3, "massgebend": "Halter", "verfahren": "FEM",
                                    "text": "Bruch (Sicherheit 1): bis zum 3,10-fachen der Lasten (FEM)"}],
                         "probe": {"faktor": 1.24, "ausnutzung": 1.0, "teil": "Halter"},
                         "text": "„Aufstützen 30 kg“ hält bis zum 1,24-fachen", "rechnungen": 41,
                         "hinweis": "S0 und S1 gesucht, dazu die Festkörper-FEM (zwei Lösungen, überlagert; "
                                    "Probe bei 1,24)", "ms": 812.0},
            "meldung": None, "ms": 905.0}


# =====================================================================================================================
# V2-5 Live (PROTOCOL.md, Abschnitt „V2-5 Live“): Fähigkeiten, Delta, In Arbeit, Agentenspur, Lagebild, Live-Maße.
# Die Weiche je Verbindung (was eine App bekommt) steht in live.py; hier stehen Format, Schlüssel, Strukturpatch,
# Prüfen und die Beispiele für die Testdateien (tools/make_live_fixtures.py).
# =====================================================================================================================

FAEHIGKEIT_DELTA = "delta-1"
FAEHIGKEIT_IN_ARBEIT = "in-arbeit-1"
FAEHIGKEIT_SPUR = "spur-1"
FAEHIGKEIT_LAGE = "lage-1"
FAEHIGKEIT_LIVE_MASSE = "live-masse-1"
FAEHIGKEIT_FEEDBACK = "feedback-1"  # V2-6 (Abschnitt „V2-6 Sprach-Feedback“)
FAEHIGKEIT_FLAECHE = "flaeche-1"  # V2-7: Kacheln, Modus, Rand (PROTOCOL.md, „Fläche“)
FAEHIGKEIT_DATEI = "datei-1"  # I-8: Datei ans Gerät (PROTOCOL.md, „I-8 Datei ans Gerät“)
FAEHIGKEIT_ANSICHT = "ansicht-1"  # I-6: Live-Kopplung der Geräte (PROTOCOL.md, „I-6 Live-Kopplung“)
FAEHIGKEIT_DATEI_HOCH = "datei-hoch-1"  # I-8: Datei vom Gerät an den Mac (DATEI_HOCH)
#: was der Kernel kann (HELLO.faehigkeiten)
KERNEL_FAEHIGKEITEN: tuple[str, ...] = (FAEHIGKEIT_DELTA, FAEHIGKEIT_IN_ARBEIT, FAEHIGKEIT_SPUR, FAEHIGKEIT_LAGE,
                                        FAEHIGKEIT_LIVE_MASSE, FAEHIGKEIT_FEEDBACK, FAEHIGKEIT_FLAECHE,
                                        FAEHIGKEIT_DATEI, FAEHIGKEIT_ANSICHT, FAEHIGKEIT_DATEI_HOCH)
#: neue Nachrichten Kernel → App und die Fähigkeit, die eine App dafür gemeldet haben muss
LIVE_NACHRICHTEN: dict[str, str] = {
    "PART_SAME": FAEHIGKEIT_DELTA, "WIE_ZUVOR": FAEHIGKEIT_DELTA, "IN_ARBEIT": FAEHIGKEIT_IN_ARBEIT,
    "AGENT_SPUR": FAEHIGKEIT_SPUR, "AGENT_SCHRITT": FAEHIGKEIT_SPUR, "LAGE_REQ": FAEHIGKEIT_LAGE,
    "GERAETE": FAEHIGKEIT_ANSICHT, "ANSICHT": FAEHIGKEIT_ANSICHT, "SPRECHEN_LIVE": FAEHIGKEIT_ANSICHT,
}
#: neue Felder bestehender Nachrichten Kernel → App: (type, Feld) → Fähigkeit
LIVE_FELDER: dict[tuple[str, str], str] = {
    ("PART_UPSERT", "inhalt"): FAEHIGKEIT_DELTA, ("RUN_START", "delta"): FAEHIGKEIT_DELTA,
    ("RUN_END", "teile"): FAEHIGKEIT_DELTA,
}
#: neue Nachrichten App → Kernel
LIVE_APP_NACHRICHTEN: tuple[str, ...] = ("LAGE", "PARTS_REQ", "NOCHMAL")
#: Arten, die als WIE_ZUVOR kommen können (große JSON-Nachrichten, die sich zwischen Läufen kaum ändern)
WIE_ZUVOR_ARTEN: tuple[str, ...] = ("CHECK", "STATICS", "CONSTRAINTS", "BOM", "PRINT_PREVIEW", "SIM", "DOCS",
                                    "VERSIONEN")
WIE_ZUVOR_BASEN = 6  # so viele Rahmen je Art merken sich beide Seiten als mögliche Basis
TEIL_INHALTE = 4  # so viele verschiedene Inhalte je Teilname halten App und Kernel (PART_SAME)
WIE_ZUVOR_ANTEIL = 0.5  # ein WIE_ZUVOR geht nur, wenn es höchstens so groß ist wie dieser Anteil der vollen Nachricht
SPUR_LAENGE = 50  # Schritte der Agentenspur, die Kernel und App halten
SPUR_STAENDE: tuple[str, ...] = ("laeuft", "ok", "fehler")
SPUR_FELDER: tuple[str, ...] = ("id", "werkzeug", "text", "absicht", "sitzung", "beginn", "ende", "dauer_ms", "stand",
                                "fehler")
SPUR_TEXT_MAX = 200  # absicht und fehler höchstens so viele Zeichen
IN_ARBEIT_NACH_S = 0.3  # IN_ARBEIT, wenn so lange kein Teil kam (und höchstens so oft)
LAGE_WARTEN_S = 0.2  # so lange wartet der Kernel auf LAGE, dann nimmt er, was er selbst weiß
LAGE_KAMERA_FELDER: tuple[str, ...] = ("position", "ziel", "richtung", "oben", "abstand", "projektion", "fov",
                                       "ortho_hoehe", "ansicht", "durch")
ANNOTATE_ARTEN: tuple[str, ...] = ("mass", "param", "hinweis")
#: V2-7: Kacheln der Werkstatt (App: ``KachelArt``), Befehle mit ``flaeche-1``
KACHELN: tuple[str, ...] = ("modell", "zeichnung", "bauplan", "stueckliste", "zuschnitt", "druck", "animation",
                            "ansicht", "material", "simulation", "versionen", "details", "render")
MODI: tuple[str, ...] = ("fokus", "werkstatt")
RAENDER: tuple[str, ...] = ("links", "rechts")
FLAECHE_BEFEHLE: tuple[str, ...] = ("flaeche", "projekt_name")
FLAECHE_FEHLT = ("Diese App kennt die Kacheln noch nicht (ältere Fassung ohne flaeche-1). Kevin muss Kev CAD "
                 "aktualisieren; bis dahin bleibt die Oberfläche, wie sie ist.")
_INHALT_OHNE = frozenset(("type", "seq", "run", "faces", "edges", "inhalt"))
_HEX = frozenset("0123456789abcdef")


def kanonisch(wert: Any) -> str:
    """JSON-Text zum Vergleichen: Schlüssel sortiert, kompakt; unterscheidet 1, 1.0 und true."""
    return json.dumps(wert, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def inhalt_schluessel(key: str, header: dict[str, Any], payload: bytes | None = None) -> str:
    """Inhaltsschlüssel eines Teils (``PART_UPSERT.inhalt``, 16 Hex-Zeichen): SHA-1 über den Tessellierungs-Schlüssel
    ``key`` (Form, Lage und Genauigkeit, aus dem Rechenprozess) und den Kopf ohne type, seq, run, faces, edges und
    inhalt (Farbe, Material, Hüllquader, Masse, Lager, Druck, Zukauf, Kulisse, Inventar …). ``faces`` und ``edges``
    folgen aus der Form. Ohne ``key`` zählen stattdessen die Nutzlast und beide Listen."""
    h = hashlib.sha1()
    if key:
        h.update(b"form:" + key.encode("utf-8"))
    else:
        h.update(b"netz:" + hashlib.sha1(payload or b"").digest())
        h.update(kanonisch([header.get("faces"), header.get("edges")]).encode("utf-8"))
    h.update(b"\n")
    h.update(kanonisch({k: v for k, v in header.items() if k not in _INHALT_OHNE}).encode("utf-8"))
    return h.hexdigest()[:16]


def part_same(run: int, name: str, inhalt: str) -> dict[str, Any]:
    """PART_SAME (delta-1): Teil ``name`` ist in Lauf ``run`` unverändert."""
    return {"type": "PART_SAME", "run": int(run), "name": str(name), "inhalt": str(inhalt)}


class _PatchZuGross(Exception):
    pass


def strukturpatch(alt: Any, neu: Any, grenze: float | None = None) -> tuple[list[Any], list[Any]] | None:
    """Änderung von ``alt`` nach ``neu`` als (``setzen``, ``weg``) für WIE_ZUVOR. Pfade bestehen aus Schlüsseln (Text)
    und Listenstellen (Zahl). Rekursiv in Objekte (nur mit Text-Schlüsseln) und in Listen gleicher Länge; alles
    andere wird ganz ersetzt. ``grenze``: höchstens so viele Byte JSON, sonst None. Gleichheit nach ``==``; was danach
    noch abweicht (1 gegen 1.0 gegen true in sonst gleichen Teilen), findet die Probe in ``live.py``."""
    setzen: list[Any] = []
    weg: list[Any] = []
    rest = [float("inf") if grenze is None else float(grenze)]

    def kosten(n: int) -> None:
        rest[0] -= n
        if rest[0] < 0:
            raise _PatchZuGross

    def setze(pfad: list[Any], wert: Any) -> None:
        kosten(len(kanonisch([pfad, wert])) + 1)
        setzen.append([pfad, wert])

    def gehe(a: Any, b: Any, pfad: list[Any]) -> None:
        if type(a) is type(b) and a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict) and all(isinstance(k, str) for k in a) \
                and all(isinstance(k, str) for k in b):
            for k, v in b.items():
                if k in a:
                    gehe(a[k], v, pfad + [k])
                else:
                    setze(pfad + [k], v)
            for k in a:
                if k not in b:
                    kosten(len(kanonisch(pfad + [k])) + 1)
                    weg.append(pfad + [k])
            return
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                gehe(x, y, pfad + [i])
            return
        setze(pfad, b)

    try:
        gehe(alt, neu, [])
    except _PatchZuGross:
        return None
    return setzen, weg


def patch_anwenden(basis: dict[str, Any], setzen: list[Any], weg: list[Any], *, kopieren: bool = True
                   ) -> dict[str, Any]:
    """WIE_ZUVOR aufbauen: Kopie der Basis, ``setzen`` der Reihe nach, dann ``weg``. Ungültige Pfade: ValueError."""
    out = copy.deepcopy(basis) if kopieren else basis

    def eltern(pfad: list[Any]) -> tuple[Any, Any]:
        if not isinstance(pfad, list) or not pfad:
            raise ValueError(f"WIE_ZUVOR: Pfad {pfad!r} ungültig")
        ziel: Any = out
        for p in pfad[:-1]:
            if isinstance(ziel, dict) and isinstance(p, str) and p in ziel:
                ziel = ziel[p]
            elif isinstance(ziel, list) and isinstance(p, int) and not isinstance(p, bool) and 0 <= p < len(ziel):
                ziel = ziel[p]
            else:
                raise ValueError(f"WIE_ZUVOR: Pfad {pfad!r} passt nicht zur Basis")
        return ziel, pfad[-1]

    for paar in setzen:
        if not isinstance(paar, list) or len(paar) != 2:
            raise ValueError(f"WIE_ZUVOR: setzen-Eintrag {paar!r} ungültig")
        ziel, letzter = eltern(paar[0])
        if isinstance(ziel, dict) and isinstance(letzter, str):
            ziel[letzter] = copy.deepcopy(paar[1])
        elif isinstance(ziel, list) and isinstance(letzter, int) and not isinstance(letzter, bool) \
                and 0 <= letzter < len(ziel):
            ziel[letzter] = copy.deepcopy(paar[1])
        else:
            raise ValueError(f"WIE_ZUVOR: Pfad {paar[0]!r} passt nicht zur Basis")
    for pfad in weg:
        ziel, letzter = eltern(pfad)
        if not isinstance(ziel, dict) or not isinstance(letzter, str) or letzter not in ziel:
            raise ValueError(f"WIE_ZUVOR: weg {pfad!r} passt nicht zur Basis")
        del ziel[letzter]
    return out


def wie_zuvor(art: str, basis: int, setzen: list[Any], weg: list[Any]) -> dict[str, Any]:
    """Kopf von WIE_ZUVOR (ohne seq; keine Nutzlast)."""
    return {"type": "WIE_ZUVOR", "art": art, "basis": int(basis), "setzen": setzen, "weg": weg}


def wie_zuvor_aufbauen(wz: dict[str, Any], basis_kopf: dict[str, Any]) -> dict[str, Any]:
    """Rahmen aus WIE_ZUVOR und dem Kopf der Basis (ohne seq): was die App daraus macht, mit seq des WIE_ZUVOR."""
    out = patch_anwenden({k: v for k, v in basis_kopf.items() if k != "seq"}, list(wz.get("setzen") or []),
                         list(wz.get("weg") or []))
    out["type"] = wz["art"]
    if "seq" in wz:
        out["seq"] = wz["seq"]
    return out


def netz_bytes(kopf: dict[str, Any]) -> int:
    """Byte eines Netzes in der Nutzlast von pack_netze (0 bei ``aus_szene``)."""
    if kopf.get("aus_szene"):
        return 0
    return 4 * (int(kopf["vert"]) * 6 + int(kopf["tri"]) * 3 + int(kopf["epts"]) * 3 + int(kopf["edge"]) + 1)


def _ist_inhalt(x: Any) -> bool:
    return isinstance(x, str) and len(x) == 16 and set(x) <= _HEX


def _zahl(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _punkt(x: Any) -> bool:
    return isinstance(x, list) and len(x) == 3 and all(_zahl(v) for v in x)


def _namen(x: Any) -> bool:
    return isinstance(x, list) and all(isinstance(n, str) for n in x)


def _check_pfad(pfad: Any) -> bool:
    return isinstance(pfad, list) and len(pfad) > 0 and all(
        isinstance(p, str) or (isinstance(p, int) and not isinstance(p, bool) and p >= 0) for p in pfad)


def check_spur_schritt(s: Any) -> list[str]:
    """Probleme eines Schritts der Agentenspur (leer = gut)."""
    if not isinstance(s, dict):
        return ["Schritt ist kein Objekt"]
    out = []
    if not isinstance(s.get("id"), str) or not s["id"]:
        out.append("Schritt ohne id")
    if not isinstance(s.get("werkzeug"), str):
        out.append(f"Schritt {s.get('id')}: werkzeug fehlt")
    if s.get("stand") not in SPUR_STAENDE:
        out.append(f"Schritt {s.get('id')}: stand {s.get('stand')!r} unbekannt")
    if not _zahl(s.get("beginn")):
        out.append(f"Schritt {s.get('id')}: beginn fehlt")
    for k in ("ende", "dauer_ms"):
        if s.get(k) is not None and not _zahl(s[k]):
            out.append(f"Schritt {s.get('id')}: {k} keine Zahl")
    if s.get("stand") != "laeuft" and (s.get("ende") is None or s.get("dauer_ms") is None):
        out.append(f"Schritt {s.get('id')}: fertig, aber ohne ende/dauer_ms")
    for k in ("text", "absicht", "sitzung", "fehler"):
        if s.get(k) is not None and not isinstance(s[k], str):
            out.append(f"Schritt {s.get('id')}: {k} kein Text")
    for k in ("absicht", "fehler"):
        if isinstance(s.get(k), str) and len(s[k]) > SPUR_TEXT_MAX:
            out.append(f"Schritt {s.get('id')}: {k} länger als {SPUR_TEXT_MAX} Zeichen")
    if s.get("stand") == "fehler" and not s.get("fehler"):
        out.append(f"Schritt {s.get('id')}: stand fehler ohne Meldung")
    if s.get("phasen") is not None and not isinstance(s["phasen"], dict):
        out.append(f"Schritt {s.get('id')}: phasen kein Objekt")
    return out


def _kachel_oder_nummer(wert: Any) -> bool:
    return wert in KACHELN or (isinstance(wert, int) and not isinstance(wert, bool) and 1 <= wert <= 4)


def _flaeche_args_fehler(a: dict[str, Any]) -> list[str]:
    """Probleme der Felder von ``VIEW_CMD flaeche`` (PROTOCOL.md, „Fläche“)."""
    out: list[str] = []
    for feld in ("ordnen", "zeigen"):
        if feld in a and (not isinstance(a[feld], list) or any(k not in KACHELN for k in a[feld])):
            out.append(f"VIEW_CMD flaeche: {feld} ist keine Liste von Kacheln")
    z = a.get("schliessen")
    if z is not None and z != "alle" and (not isinstance(z, list) or not all(_kachel_oder_nummer(k) for k in z)):
        out.append("VIEW_CMD flaeche: schliessen ist weder alle noch eine Liste von Kacheln oder Nummern")
    g = a.get("gross")
    if g is not None and g != "aus" and not _kachel_oder_nummer(g):
        out.append(f"VIEW_CMD flaeche: gross {g!r} unbekannt")
    if "modus" in a and a["modus"] not in MODI:
        out.append(f"VIEW_CMD flaeche: modus {a['modus']!r} unbekannt")
    if "rand" in a and a["rand"] not in (*RAENDER, "aus"):
        out.append(f"VIEW_CMD flaeche: rand {a['rand']!r} unbekannt")
    for feld in ("zeitleiste", "leiste_links", "leiste_rechts"):
        if feld in a and not isinstance(a[feld], bool):
            out.append(f"VIEW_CMD flaeche: {feld} kein Wahrheitswert")
    return out


def _lage_flaeche_fehler(f: Any) -> list[str]:
    """Probleme von ``LAGE.flaeche`` (fehlt das Feld, ist es eine App ohne ``flaeche-1``)."""
    if not isinstance(f, dict):
        return ["LAGE: flaeche kein Objekt"]
    out: list[str] = []
    if f.get("modus") not in MODI:
        out.append(f"LAGE: flaeche.modus {f.get('modus')!r} unbekannt")
    k = f.get("kacheln")
    if not isinstance(k, list) or len(k) > 4 or any(x not in KACHELN for x in k):
        out.append("LAGE: flaeche.kacheln ist keine Liste von höchstens vier Kacheln")
    for feld in ("gross", "aktiv"):
        if f.get(feld) is not None and f[feld] not in KACHELN:
            out.append(f"LAGE: flaeche.{feld} {f[feld]!r} unbekannt")
    if f.get("rand") is not None and f["rand"] not in RAENDER:
        out.append(f"LAGE: flaeche.rand {f['rand']!r} unbekannt")
    if not isinstance(f.get("zeitleiste"), bool):
        out.append("LAGE: flaeche.zeitleiste kein Wahrheitswert")
    for feld in ("leiste_links", "leiste_rechts"):  # V2-9, fehlen bei Apps davor
        if feld in f and not isinstance(f[feld], bool):
            out.append(f"LAGE: flaeche.{feld} kein Wahrheitswert")
    return out


def check_live_message(header: dict[str, Any], payload: bytes = b"") -> list[str]:
    """Probleme einer Nachricht oder eines neuen Felds aus V2-5 (leer = gut). Andere Nachrichten: leer."""
    art = header.get("type")
    out: list[str] = []
    if art in ("HELLO", "HELLO_APP"):
        f = header.get("faehigkeiten")
        if f is not None and not _namen(f):
            out.append(f"{art}: faehigkeiten keine Liste von Texten")
    elif art == "PART_SAME":
        if not isinstance(header.get("run"), int) or not isinstance(header.get("name"), str):
            out.append("PART_SAME: run oder name fehlt")
        if not _ist_inhalt(header.get("inhalt")):
            out.append("PART_SAME: inhalt kein Schlüssel aus 16 Hex-Zeichen")
        if payload:
            out.append("PART_SAME mit Nutzlast")
    elif art == "PART_UPSERT":
        if "inhalt" in header and not _ist_inhalt(header["inhalt"]):
            out.append("PART_UPSERT: inhalt kein Schlüssel aus 16 Hex-Zeichen")
    elif art == "RUN_START":
        if "delta" in header and not isinstance(header["delta"], bool):
            out.append("RUN_START: delta kein Wahrheitswert")
    elif art == "RUN_END":
        if "teile" in header and not _namen(header["teile"]):
            out.append("RUN_END: teile keine Liste von Namen")
    elif art == "WIE_ZUVOR":
        if header.get("art") not in WIE_ZUVOR_ARTEN:
            out.append(f"WIE_ZUVOR: art {header.get('art')!r} nicht erlaubt")
        if not isinstance(header.get("basis"), int):
            out.append("WIE_ZUVOR: basis fehlt")
        setzen, weg = header.get("setzen"), header.get("weg")
        if not isinstance(setzen, list) or not all(isinstance(p, list) and len(p) == 2 and _check_pfad(p[0])
                                                    for p in setzen):
            out.append("WIE_ZUVOR: setzen ungültig")
        if not isinstance(weg, list) or not all(_check_pfad(p) for p in weg):
            out.append("WIE_ZUVOR: weg ungültig")
        if payload:
            out.append("WIE_ZUVOR mit Nutzlast")
    elif art == "NOCHMAL":
        if header.get("art") not in WIE_ZUVOR_ARTEN:
            out.append(f"NOCHMAL: art {header.get('art')!r} nicht erlaubt")
    elif art == "PARTS_REQ":
        if header.get("teile") is not None and not _namen(header.get("teile")):
            out.append("PARTS_REQ: teile weder null noch Liste von Namen")
    elif art == "IN_ARBEIT":
        if not isinstance(header.get("run"), int) or not isinstance(header.get("teil"), str):
            out.append("IN_ARBEIT: run oder teil fehlt")
        if header.get("nach") is not None and not isinstance(header["nach"], str):
            out.append("IN_ARBEIT: nach weder Text noch null")
        if not _zahl(header.get("ms")):
            out.append("IN_ARBEIT: ms fehlt")
    elif art == "AGENT_SPUR":
        schritte = header.get("schritte")
        if not isinstance(schritte, list) or len(schritte) > SPUR_LAENGE:
            out.append(f"AGENT_SPUR: schritte keine Liste mit höchstens {SPUR_LAENGE} Einträgen")
        else:
            for s in schritte:
                out += check_spur_schritt(s)
    elif art == "AGENT_SCHRITT":
        out += check_spur_schritt(header.get("schritt"))
    elif art == "LAGE_REQ":
        if not isinstance(header.get("id"), str):
            out.append("LAGE_REQ: id fehlt")
    elif art == "LAGE":
        if not isinstance(header.get("reply_to"), str):
            out.append("LAGE: reply_to fehlt")
        if not _zahl(header.get("zeit")):
            out.append("LAGE: zeit fehlt")
        k = header.get("kamera")
        if k is not None:
            if not isinstance(k, dict) or set(k) != set(LAGE_KAMERA_FELDER):
                out.append(f"LAGE: kamera braucht genau {', '.join(LAGE_KAMERA_FELDER)}")
            else:
                for f in ("position", "ziel", "richtung", "oben"):
                    if not _punkt(k[f]):
                        out.append(f"LAGE: kamera.{f} kein Punkt")
                if k["projektion"] not in ("perspective", "orthographic"):
                    out.append("LAGE: kamera.projektion unbekannt")
        for f in ("sichtbar", "verborgen"):
            if not _namen(header.get(f)):
                out.append(f"LAGE: {f} keine Liste von Namen")
        if header.get("isoliert") is not None and not _namen(header["isoliert"]):
            out.append("LAGE: isoliert weder null noch Liste")
        aw = header.get("auswahl")
        if not isinstance(aw, dict) or not _namen(aw.get("refs")):
            out.append("LAGE: auswahl braucht refs")
        m = header.get("maus")
        if m is not None and (not isinstance(m, dict) or not isinstance(m.get("teil"), str)
                              or (m.get("punkt") is not None and not _punkt(m["punkt"]))):
            out.append("LAGE: maus braucht teil und punkt (oder null)")
        if "flaeche" in header:
            out.extend(_lage_flaeche_fehler(header["flaeche"]))
    elif art == "VIEW_CMD" and header.get("cmd") in ("annotate", "highlight"):
        a = header.get("args") or {}
        if "dauer_s" in a and (not _zahl(a["dauer_s"]) or a["dauer_s"] <= 0):
            out.append("VIEW_CMD: dauer_s muss eine Zahl über 0 sein")
        if header.get("cmd") == "annotate" and "art" in a and a["art"] not in ANNOTATE_ARTEN:
            out.append(f"VIEW_CMD annotate: art {a['art']!r} unbekannt")
        if header.get("cmd") == "highlight" and "id" in a and not isinstance(a["id"], str):
            out.append("VIEW_CMD highlight: id kein Text")
    elif art == "VIEW_CMD" and header.get("cmd") == "flaeche":
        out.extend(_flaeche_args_fehler(header.get("args") or {}))
    elif art == "VIEW_CMD" and header.get("cmd") == "projekt_name":
        if not isinstance((header.get("args") or {}).get("name"), str):
            out.append("VIEW_CMD projekt_name: name fehlt")
    elif art == "VERSION_BILD_REQ":
        koepfe = header.get("teile") or []
        for k in koepfe:
            if k.get("aus_szene") and (not _ist_inhalt(k.get("inhalt")) or not isinstance(k.get("teil"), str)
                                       or any(f in k for f in ("vert", "tri", "epts", "edge"))):
                out.append(f"VERSION_BILD_REQ: Kopf {k.get('teil')!r} aus der Szene braucht teil und inhalt, "
                           "keine Zählwerte")
        try:
            erwartet = sum(netz_bytes(k) for k in koepfe)
        except (KeyError, TypeError, ValueError):
            out.append("VERSION_BILD_REQ: Kopf ohne Zählwerte")
        else:
            if erwartet != len(payload):
                out.append(f"VERSION_BILD_REQ: Nutzlast {len(payload)} Byte, erwartet {erwartet}")
    return out


def live_beispiele() -> list[tuple[str, dict[str, Any], bytes, str]]:
    """Beispiele für die Testdateien (Name, Kopf mit seq, Nutzlast, Richtung ``kernel`` | ``app``)."""
    tri_geo = PartGeometry(
        positions=np.array([[0, 0, 0], [40, 0, 0], [0, 20, 0]], np.float32),
        normals=np.array([[0, 0, 1]] * 3, np.float32),
        triangles=np.array([[0, 1, 2]], np.uint32), tri_face=np.array([0], np.int32),
        edge_points=np.array([[0, 0, 0], [40, 0, 0]], np.float32), edge_offsets=np.array([0, 2], np.uint32),
        vertices=np.array([[0, 0, 0], [40, 0, 0], [0, 20, 0]], np.float32),
        faces=[{"t": "plane", "a": 400.0, "n": [0, 0, 1], "c": [13.3333, 6.6667, 0]}],
        edges=[{"t": "line", "l": 40.0}])
    kopf, nutz = pack_part(run=8, name="Halter/Lasche", geometry=tri_geo, color=(0.72, 0.75, 0.79, 1.0),
                           bbox={"min": [0, 0, 0], "max": [40, 20, 0]},
                           props={"volume": 0.0, "area": 400.0, "center": [13.3333, 6.6667, 0.0]},
                           material="aluminium", seq=12)
    kopf["inhalt"] = inhalt_schluessel("0f3a5c1e9b7d2a4c6e8f0a1b3c5d7e9f1a2b3c4d:0.1:0.2", kopf)
    faehig = list(KERNEL_FAEHIGKEITEN)
    schritt_laeuft = {"id": "s-12", "werkzeug": "run", "text": "führt model.py aus", "absicht": "Laufrolle auf 90 mm",
                      "sitzung": "3f2a9c1b77", "beginn": 1793452991.123, "ende": None, "dauer_ms": None,
                      "stand": "laeuft", "fehler": None}
    schritt_ok = {**schritt_laeuft, "ende": 1793452993.456, "dauer_ms": 2333.0, "stand": "ok",
                  "phasen": {"run": 8, "erstes_teil": 210.0, "letztes_teil": 1400.0, "run_end": 1450.0,
                             "pruefung": 2300.0, "zurueck": 2310.0}}
    schritt_fehler = {"id": "s-13", "werkzeug": "measure", "text": "misst Lasche ↔ Grundplatte", "absicht": None,
                      "sitzung": None, "beginn": 1793452995.0, "ende": 1793452995.08, "dauer_ms": 80.0,
                      "stand": "fehler", "fehler": "Teil 'Halter/Lasch' gibt es nicht. Meinten Sie 'Halter/Lasche'?"}
    befund = {"id": "du1", "art": "durchdringung", "teile": ["Halter/Lasche", "Halter/Grundplatte"],
              "schwere": "fehler", "wert": {"volumen": 200.0, "tiefe": 2.0, "achse": [0, 0, 1]}, "ort": [20, 5, 0],
              "text": "Halter/Lasche und Halter/Grundplatte durchdringen sich: 200 mm³, Tiefe etwa 2 mm.",
              "loesung": "Halter/Lasche um 2,2 mm in +Z verschieben", "geometrie": None}
    check_alt, _ = pack_check(run=7, state="done", seq=40, ergebnis={
        "dauer_ms": 954.8, "zusammenfassung": "1 Durchdringung", "zaehler": {"fehler": 1, "warnung": 0, "hinweis": 0},
        "befunde": [befund], "stand": {"boden_z": 0.0, "boden_erklaert": True, "gruppen": []}})
    check_neu, _ = pack_check(run=8, state="done", seq=41, ergebnis={
        "dauer_ms": 911.5, "zusammenfassung": "1 Durchdringung", "zaehler": {"fehler": 1, "warnung": 0, "hinweis": 0},
        "befunde": [befund], "stand": {"boden_z": 0.0, "boden_erklaert": True, "gruppen": []}})
    gepatcht = strukturpatch({k: v for k, v in check_alt.items() if k != "seq"},
                             {k: v for k, v in check_neu.items() if k != "seq"})
    assert gepatcht is not None
    wz = {**wie_zuvor("CHECK", 40, *gepatcht), "seq": 41}
    netz_eintrag = ({"teil": "Halter/Grundplatte", "farbe": [0.5, 0.5, 0.5, 1.0]},
                    {"positions": tri_geo.positions, "normals": tri_geo.normals, "triangles": tri_geo.triangles,
                     "edge_points": tri_geo.edge_points, "edge_offsets": tri_geo.edge_offsets})
    koepfe, netze = pack_netze([netz_eintrag])
    bild_koepfe = [{"teil": "Halter/Lasche", "farbe": [0.72, 0.75, 0.79, 1.0], "inhalt": kopf["inhalt"],
                    "aus_szene": True}] + koepfe
    lage = {"type": "LAGE", "seq": 9, "reply_to": "k-41", "zeit": 1793452991.2, "ms": 2.1,
            "kamera": {"position": [612.0, -880.0, 540.0], "ziel": [120.0, 0.0, 60.0],
                       "richtung": [-0.3854, 0.6894, -0.6131], "oben": [-0.2994, 0.5355, 0.7895], "abstand": 1276.3,
                       "projektion": "perspective", "fov": 30.0, "ortho_hoehe": None, "ansicht": None,
                       "durch": None},
            "viewport": {"breite": 1280, "hoehe": 800},
            "sichtbar": ["Halter/Grundplatte", "Halter/Lasche"], "verborgen": ["Deckel"], "isoliert": None,
            "auswahl": {"run": 8, "refs": ["Halter/Lasche#f0"]},
            "maus": {"teil": "Halter/Lasche", "ref": "Halter/Lasche#f0", "punkt": [12.0, 4.0, 0.0],
                     "normale": [0.0, 0.0, 1.0], "bild": [640, 380]},
            "darstellung": "shaded_edges", "schnitt": None, "explosion": 0.0,
            "animation": {"name": "Fahrt", "zeit": 1.25, "spielt": False},
            "flaeche": {"modus": "werkstatt", "kacheln": ["modell", "zeichnung", "druck"], "gross": None,
                        "aktiv": "druck", "rand": None, "zeitleiste": False, "ansicht": "top",
                        "blatt": {"id": "b-2", "titel": "Rohr", "nr": 2, "von": 5}}}
    lage_parallel = {"type": "LAGE", "seq": 10, "reply_to": "k-42", "zeit": 1793452992.0, "ms": 1.4,
                     "kamera": {"position": [20.0, 10.0, 1000.0], "ziel": [20.0, 10.0, 0.0],
                                "richtung": [0.0, 0.0, -1.0], "oben": [0.0, 1.0, 0.0], "abstand": 1000.0,
                                "projektion": "orthographic", "fov": None, "ortho_hoehe": 240.0, "ansicht": "top",
                                "durch": None},
                     "viewport": {"breite": 900, "hoehe": 600}, "sichtbar": ["Halter/Lasche"], "verborgen": [],
                     "isoliert": ["Halter/Lasche"], "auswahl": {"run": None, "refs": []}, "maus": None,
                     "darstellung": "wireframe", "schnitt": {"axis": "z", "offset": 5.0}, "explosion": 0.25,
                     "animation": None,
                     "flaeche": {"modus": "fokus", "kacheln": ["modell"], "gross": None, "aktiv": None,
                                 "rand": "rechts", "zeitleiste": True, "ansicht": "top", "blatt": None}}
    return [
        ("live_hello", {"type": "HELLO", "seq": 1, "protocol": PROTOCOL_VERSION, "kernel_version": "0.1.0",
                        "build123d": "0.13.0", "mcp_port": 47823, "faehigkeiten": faehig}, b"", "kernel"),
        ("live_hello_app", {"type": "HELLO_APP", "seq": 1, "app_version": "2.0", "bundle_id": "de.upvis.kevcad",
                            "faehigkeiten": faehig}, b"", "app"),
        ("live_run_start", {"type": "RUN_START", "seq": 11, "run": 8, "file_hash": "5a0c1f9e2b7d", "params":
                            {"laufrolle_l": 90.0}, "slow_ms": 0, "delta": True}, b"", "kernel"),
        ("live_part_upsert", kopf, nutz, "kernel"),
        ("live_part_same", {**part_same(8, "Halter/Grundplatte", "9c1d2e3f4a5b6c7d"), "seq": 13}, b"", "kernel"),
        ("live_in_arbeit", {"type": "IN_ARBEIT", "seq": 14, "run": 8, "teil": "Halter/Lasche",
                            "nach": "Halter/Grundplatte", "ms": 640.5}, b"", "kernel"),
        ("live_run_end", {"type": "RUN_END", "seq": 15, "run": 8, "duration_ms": 2370, "parts": 2, "triangles": 13,
                          "warnings": [], "params": {"laufrolle_l": 90.0}, "inventar_regel": True,
                          "inventar_verstoesse": [], "teile": ["Halter/Grundplatte", "Halter/Lasche"]}, b"", "kernel"),
        ("live_check_basis", check_alt, b"", "kernel"),
        ("live_wie_zuvor", wz, b"", "kernel"),
        ("live_nochmal", {"type": "NOCHMAL", "seq": 4, "art": "CHECK"}, b"", "app"),
        ("live_parts_req", {"type": "PARTS_REQ", "seq": 5, "teile": ["Halter/Lasche"]}, b"", "app"),
        ("live_version_bild_req", {"type": "VERSION_BILD_REQ", "seq": 42, "id": "k-17", "nr": 12, "width": 480,
                                   "height": 320, "view": "iso", "teile": bild_koepfe}, netze, "kernel"),
        ("live_agent_spur", {"type": "AGENT_SPUR", "seq": 3, "schritte": [schritt_ok, schritt_fehler]}, b"",
         "kernel"),
        ("live_agent_schritt", {"type": "AGENT_SCHRITT", "seq": 20, "schritt": schritt_laeuft}, b"", "kernel"),
        ("live_agent_schritt_ende", {"type": "AGENT_SCHRITT", "seq": 21, "schritt": schritt_ok}, b"", "kernel"),
        ("live_agent_schritt_fehler", {"type": "AGENT_SCHRITT", "seq": 22, "schritt": schritt_fehler}, b"",
         "kernel"),
        ("live_lage_req", {"type": "LAGE_REQ", "seq": 23, "id": "k-41"}, b"", "kernel"),
        ("live_lage", lage, b"", "app"),
        ("live_lage_parallel", lage_parallel, b"", "app"),
        ("live_view_annotate_param", {"type": "VIEW_CMD", "seq": 24, "id": "k-43", "cmd": "annotate",
                                      "args": {"kind": "label", "points": [[20.0, 10.0, 25.0]],
                                               "text": "laufrolle_l 80 → 90 mm", "id": "p-3", "art": "param",
                                               "dauer_s": 4.0}}, b"", "kernel"),
        ("live_view_highlight_dauer", {"type": "VIEW_CMD", "seq": 25, "id": "k-44", "cmd": "highlight",
                                       "args": {"refs": ["Halter/Lasche"], "color": None, "label": None,
                                                "clear": False, "id": "p-3", "dauer_s": 4.0}}, b"", "kernel"),
        ("live_view_flaeche", {"type": "VIEW_CMD", "seq": 26, "id": "k-45", "cmd": "flaeche",
                               "args": {"rand": "aus", "ordnen": ["modell", "zeichnung"], "zeigen": ["druck"],
                                        "schliessen": [2], "gross": "druck", "modus": "werkstatt",
                                        "zeitleiste": False, "ansicht": "front", "blatt": 2}}, b"", "kernel"),
        ("live_view_projekt_name", {"type": "VIEW_CMD", "seq": 27, "id": "k-46", "cmd": "projekt_name",
                                    "args": {"name": "Kugelschieber"}}, b"", "kernel"),
    ]


# =====================================================================================================================
# V2-6 Sprach-Feedback (PROTOCOL.md, Abschnitt „V2-6 Sprach-Feedback“): Nachrichten, Paketformat, Prüfen, Beispiele für
# die Testdateien (tools/make_feedback_fixtures.py). Warten und Abholen stehen in feedback.py.
# =====================================================================================================================

FEEDBACK_FORMAT = "kevcad-feedback/1"
FEEDBACK_ABGEHOLT_FORMAT = "kevcad-feedback-abgeholt/1"
FEEDBACK_ORDNER = "feedback"
FEEDBACK_ABGEHOLT = "abgeholt.json"
FEEDBACK_STAENDE = ("spricht", "pause", "aus")
FEEDBACK_GRUENDE = ("fertig", "verworfen")
FEEDBACK_NACHRICHTEN = ("FEEDBACK_STAND", "FEEDBACK_PAKET")
FEEDBACK_WARTEN_S = 600.0  # Vorgabe von feedback(warten_s)
FEEDBACK_WARTEN_MAX_S = 1800.0  # unter der Lesezeit der Brücke (bridge.LESEZEIT_S)
FEEDBACK_HTTP_WARTEN_MAX_S = 300.0  # je Anfrage an /feedback/warten
FEEDBACK_HTTP_PFAD = "/feedback/warten"
#: Bezüge: Fenster um den Satz, Mindestdauer eines Zeigers, Suche um ein Zeigewort, Zeiger je Satz
FEEDBACK_ZEIGER_VOR_S = 0.5
FEEDBACK_ZEIGER_NACH_S = 0.3
FEEDBACK_ZEIGER_MIN_S = 0.25
FEEDBACK_ZEIGEWORT_SUCHE_S = 0.4
FEEDBACK_ZEIGER_JE_SATZ = 6
FEEDBACK_MAUS_JE_S = 10
FEEDBACK_KAMERA_JE_S = 5
FEEDBACK_BILD_LAENGE_MAX = 1600
FEEDBACK_ZEIGEWOERTER = ("hier", "da", "dort", "dahin", "hierhin", "dorthin", "das", "dies", "diese", "dieser", "dieses",
                         "diesem", "diesen")
FEEDBACK_ERKENNUNGEN = ("wortlaut-parakeet", "apple-dictation", "apple-speech", "test")
FEEDBACK_WORTZEITEN = ("ton", "geschaetzt")
#: I-4 (PLAN-IPAD.md 4.4): Strichfarben aus dem Werkzeugkranz; Kevin nennt sie beim Sprechen („die rote Linie“)
FEEDBACK_STRICHFARBEN = ("rot", "gelb", "gruen", "blau", "weiss")
#: Gerät, an dem gesprochen bzw. gezeichnet wurde
FEEDBACK_GERAETE = ("mac", "ipad")
_FEEDBACK_NAME = re.compile(r"fb-\d{8}-\d{6}(-\d+)?")


def feedback_name_ok(name: Any) -> bool:
    return isinstance(name, str) and _FEEDBACK_NAME.fullmatch(name) is not None


def check_feedback_message(header: dict[str, Any], payload: bytes = b"") -> list[str]:
    """Probleme einer Nachricht aus V2-6 (leer = gut). Andere Nachrichten: leer."""
    art = header.get("type")
    if art not in FEEDBACK_NACHRICHTEN:
        return []
    out: list[str] = []
    if not isinstance(header.get("sitzung"), str) or not header["sitzung"]:
        out.append(f"{art}: sitzung fehlt")
    if payload and not (art == "FEEDBACK_PAKET" and header.get("nutzlast") is not None):
        out.append(f"{art} mit Nutzlast")
    if art == "FEEDBACK_STAND":
        if header.get("stand") not in FEEDBACK_STAENDE:
            out.append(f"FEEDBACK_STAND: stand {header.get('stand')!r} unbekannt")
        if not _zahl(header.get("seit")):
            out.append("FEEDBACK_STAND: seit fehlt")
        grund = header.get("grund")
        if header.get("stand") == "aus":
            if grund not in FEEDBACK_GRUENDE:
                out.append(f"FEEDBACK_STAND: grund {grund!r} unbekannt")
        elif grund is not None:
            out.append("FEEDBACK_STAND: grund nur bei aus")
    else:
        if not feedback_name_ok(header.get("name")):
            out.append(f"FEEDBACK_PAKET: name {header.get('name')!r} ungültig")
        nutzlast = header.get("nutzlast")
        if nutzlast is None:
            if not isinstance(header.get("datei"), str) or not header["datei"].endswith(".json"):
                out.append("FEEDBACK_PAKET: datei ist kein Pfad zu einer JSON-Datei")
        else:
            # I-5: Gerät ohne den Projektordner (iPad) schickt JSON und Bild mit, der Kernel legt sie ab
            if header.get("datei") is not None:
                out.append("FEEDBACK_PAKET: datei und nutzlast zugleich")
            if not (isinstance(nutzlast, dict) and _ganz(nutzlast.get("json")) and nutzlast["json"] > 0
                    and _ganz(nutzlast.get("bild")) and nutzlast["bild"] >= 0):
                out.append("FEEDBACK_PAKET: nutzlast braucht json (über 0) und bild (ab 0) in Bytes")
            elif len(payload) != nutzlast["json"] + nutzlast["bild"]:
                out.append(f"FEEDBACK_PAKET: Nutzlast hat {len(payload)} Bytes, angesagt sind "
                           f"{nutzlast['json'] + nutzlast['bild']}")
        for feld in ("saetze", "striche"):
            if not isinstance(header.get(feld), int):
                out.append(f"FEEDBACK_PAKET: {feld} fehlt")
        if not _zahl(header.get("dauer_s")):
            out.append("FEEDBACK_PAKET: dauer_s fehlt")
    return out


def _ganz(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _vec(v: Any, n: int = 3) -> bool:
    return isinstance(v, list) and len(v) == n and all(_zahl(x) for x in v)


def _check_zeiger(q: dict[str, Any], wo: str) -> list[str]:
    """Felder, die Mausproben und Zeiger gemeinsam haben: Teil und Punkt gibt es nur zusammen."""
    out = []
    if q.get("teil") is not None:
        if not isinstance(q["teil"], str) or not isinstance(q.get("ref"), str):
            out.append(f"{wo}: teil oder ref ungültig")
        if not isinstance(q.get("run"), int):
            out.append(f"{wo}: run fehlt")
        if q.get("punkt") is not None and not _vec(q["punkt"]):
            out.append(f"{wo}: punkt ungültig")
        if q.get("normale") is not None and not _vec(q["normale"]):
            out.append(f"{wo}: normale ungültig")
    if q.get("bild") is not None and not _vec(q["bild"], 2):
        out.append(f"{wo}: bild ungültig")
    return out


def check_feedback_paket(p: Any) -> list[str]:
    """Probleme eines Pakets ``kevcad-feedback/1`` (leer = gut). Zeiten liegen innerhalb der Sitzung und steigen nicht
    rückwärts; alles andere prüft nur die Form."""
    if not isinstance(p, dict):
        return ["Paket ist kein Objekt"]
    out: list[str] = []
    if p.get("format") != FEEDBACK_FORMAT:
        out.append(f"format {p.get('format')!r} unbekannt")
    if not feedback_name_ok(p.get("name")):
        out.append(f"name {p.get('name')!r} ungültig")
    if not isinstance(p.get("erstellt"), str):
        out.append("erstellt fehlt")
    if not _zahl(p.get("uhr_start")):
        out.append("uhr_start fehlt")
    if not _zahl(p.get("dauer_s")) or p["dauer_s"] < 0:
        out.append("dauer_s fehlt")
    if not isinstance(p.get("spracherkennung"), str):
        out.append("spracherkennung fehlt")
    if p.get("wortzeiten") not in FEEDBACK_WORTZEITEN:
        out.append(f"wortzeiten {p.get('wortzeiten')!r} unbekannt")
    projekt = p.get("projekt")
    if not isinstance(projekt, dict) or not isinstance(projekt.get("pfad"), str):
        out.append("projekt fehlt")
    if not isinstance(p.get("run"), int):
        out.append("run fehlt")
    if p.get("geraet") is not None and p["geraet"] not in FEEDBACK_GERAETE:
        out.append(f"geraet {p.get('geraet')!r} unbekannt")
    for feld in ("abschnitte", "worte", "saetze", "striche", "mausweg", "kamera_verlauf", "auswahl_verlauf"):
        if not isinstance(p.get(feld), list):
            out.append(f"{feld} keine Liste")
    if out:
        return out
    dauer = float(p["dauer_s"]) + 1e-6
    for a in p["abschnitte"]:
        if not (_zahl(a.get("von")) and _zahl(a.get("bis")) and 0 <= a["von"] <= a["bis"] <= dauer):
            out.append(f"abschnitt {a!r} ungültig")
    nummern = {s.get("nr") for s in p["saetze"]}
    for w in p["worte"]:
        if not (isinstance(w.get("text"), str) and _zahl(w.get("von")) and _zahl(w.get("bis"))):
            out.append(f"wort {w!r} ungültig")
        elif w.get("satz") not in nummern:
            out.append(f"wort {w.get('text')!r}: satz {w.get('satz')!r} fehlt")
    striche = {s.get("nr") for s in p["striche"]}
    for s in p["saetze"]:
        wo = f"satz {s.get('nr')}"
        if not (isinstance(s.get("nr"), int) and isinstance(s.get("text"), str) and _zahl(s.get("von"))
                and _zahl(s.get("bis")) and s["von"] <= s["bis"]):
            out.append(f"{wo}: nr, text, von oder bis ungültig")
        if not isinstance(s.get("vorlaeufig"), bool):
            out.append(f"{wo}: vorlaeufig fehlt")
        if not isinstance(s.get("kamera"), dict):
            out.append(f"{wo}: kamera fehlt")
        auswahl = s.get("auswahl")
        if not isinstance(auswahl, dict) or not isinstance(auswahl.get("refs"), list):
            out.append(f"{wo}: auswahl fehlt")
        bezuege = s.get("bezuege")
        if not isinstance(bezuege, list):
            out.append(f"{wo}: bezuege fehlt")
            continue
        zeiger = [b for b in bezuege if b.get("art") == "zeiger"]
        if len(zeiger) > FEEDBACK_ZEIGER_JE_SATZ:
            out.append(f"{wo}: mehr als {FEEDBACK_ZEIGER_JE_SATZ} Zeiger")
        for b in bezuege:
            if b.get("art") == "zeiger":
                if not isinstance(b.get("teil"), str):
                    out.append(f"{wo}: Zeiger ohne teil")
                out += _check_zeiger(b, f"{wo}, Zeiger")
            elif b.get("art") == "strich":
                if b.get("strich") not in striche:
                    out.append(f"{wo}: Strich {b.get('strich')!r} fehlt")
            else:
                out.append(f"{wo}: Bezug {b.get('art')!r} unbekannt")
    for s in p["striche"]:
        wo = f"strich {s.get('nr')}"
        if not (isinstance(s.get("nr"), int) and _zahl(s.get("t")) and _zahl(s.get("bis")) and s["t"] <= s["bis"]):
            out.append(f"{wo}: nr, t oder bis ungültig")
        if not isinstance(s.get("teile"), list) or not _zahl(s.get("laenge_mm")):
            out.append(f"{wo}: teile oder laenge_mm fehlt")
        if not isinstance(s.get("kamera"), dict):
            out.append(f"{wo}: kamera fehlt")
        # I-4: Farbe und Gerät je Strich; ältere Pakete haben sie nicht
        if s.get("farbe") is not None and s["farbe"] not in FEEDBACK_STRICHFARBEN:
            out.append(f"{wo}: farbe {s.get('farbe')!r} unbekannt")
        if s.get("geraet") is not None and s["geraet"] not in FEEDBACK_GERAETE:
            out.append(f"{wo}: geraet {s.get('geraet')!r} unbekannt")
        punkte = s.get("punkte")
        if not isinstance(punkte, list) or not punkte:
            out.append(f"{wo}: keine Punkte")
            continue
        for q in punkte:
            if not (_zahl(q.get("t")) and _vec(q.get("bild"), 2) and _vec(q.get("welt"))):
                out.append(f"{wo}: Punkt {q!r} ungültig")
    for liste, feld in ((p["mausweg"], "mausweg"), (p["kamera_verlauf"], "kamera_verlauf"),
                        (p["auswahl_verlauf"], "auswahl_verlauf")):
        t = -1.0
        for q in liste:
            if not _zahl(q.get("t")) or q["t"] < t or q["t"] > dauer:
                out.append(f"{feld}: Zeit {q.get('t')!r} ungültig")
                break
            t = q["t"]
    for q in p["mausweg"]:
        out += _check_zeiger(q, "mausweg")
    if not isinstance(p.get("ende"), dict):
        out.append("ende fehlt")
    bild = p.get("bild")
    if bild is not None and not (isinstance(bild, dict) and isinstance(bild.get("datei"), str)
                                 and isinstance(bild.get("breite"), int) and isinstance(bild.get("hoehe"), int)):
        out.append("bild ungültig")
    return out


def feedback_beispiel() -> dict[str, Any]:
    """Volles Beispielpaket für die Testdateien: zwei Sätze, Zeigewort, Strich auf einem Teil und in der Bildebene."""
    kamera = {"position": [612.0, -880.0, 540.0], "ziel": [120.0, 0.0, 60.0], "richtung": [-0.39, 0.71, -0.59],
              "oben": [-0.26, 0.47, 0.84], "abstand": 1118.0, "projektion": "perspective", "fov": 30.0,
              "ortho_hoehe": None, "ansicht": None, "durch": None}
    kamera2 = {**kamera, "position": [700.0, -700.0, 600.0], "richtung": [-0.5, 0.6, -0.62], "abstand": 1050.0}
    lasche, lasche_f = "Halter/Lasche", "Halter/Lasche#f3"
    worte = [("Mach", 1.2, 1.46, 1), ("das", 1.5, 1.7, 1), ("hier", 1.75, 2.1, 1), ("höher.", 2.15, 2.6, 1),
             ("Und", 6.1, 6.3, 2), ("den", 6.35, 6.5, 2), ("Rest", 6.55, 6.9, 2), ("lass", 6.95, 7.2, 2),
             ("so.", 7.25, 7.5, 2)]
    zeiger = {"art": "zeiger", "t": 1.6, "bis": 2.4, "wort": "hier", "teil": lasche, "ref": lasche_f, "run": 7,
              "punkt": [120.0, 4.0, 62.5], "normale": [0.0, 0.0, 1.0], "bild": [640, 380]}
    return {
        "format": FEEDBACK_FORMAT, "name": "fb-20261105-223011", "erstellt": "2026-11-05T22:30:11+01:00",
        "uhr_start": 1793480977.25, "dauer_s": 9.5, "spracherkennung": "wortlaut-parakeet",
        "wortzeiten": "geschaetzt",
        "projekt": {"name": "Halter", "pfad": "/Users/kevin/Documents/Kev CAD/Halter"}, "run": 7, "geraet": "mac",
        "abschnitte": [{"von": 0.0, "bis": 3.5}, {"von": 5.5, "bis": 9.5}],
        "worte": [{"text": t, "von": a, "bis": b, "satz": s} for t, a, b, s in worte],
        "saetze": [
            {"nr": 1, "text": "Mach das hier höher.", "von": 1.2, "bis": 2.6, "vorlaeufig": False, "kamera": kamera,
             "auswahl": {"run": 7, "refs": [lasche]},
             "bezuege": [zeiger, {"art": "strich", "strich": 1, "t": 1.9, "bis": 2.5, "teile": [lasche]}]},
            {"nr": 2, "text": "Und den Rest lass so.", "von": 6.1, "bis": 7.5, "vorlaeufig": False,
             "kamera": kamera2, "auswahl": {"run": 7, "refs": []}, "bezuege": []},
        ],
        "striche": [
            {"nr": 1, "t": 1.9, "bis": 2.5, "run": 7, "teile": [lasche], "laenge_mm": 84.5, "kamera": kamera,
             "farbe": "rot", "geraet": "mac",
             "punkte": [{"t": 1.9, "bild": [612, 402], "welt": [118.0, 4.0, 60.0], "ref": lasche_f},
                        {"t": 2.5, "bild": [690, 330], "welt": [190.0, 4.0, 88.0], "ref": lasche_f}]},
            {"nr": 2, "t": 8.0, "bis": 8.4, "run": 7, "teile": [], "laenge_mm": 40.0, "kamera": kamera2,
             "farbe": "blau", "geraet": "mac",
             "punkte": [{"t": 8.0, "bild": [100, 100], "welt": [40.0, 0.0, 200.0], "ref": None},
                        {"t": 8.4, "bild": [140, 100], "welt": [80.0, 0.0, 200.0], "ref": None}]},
        ],
        "mausweg": [
            {"t": 0.4, "bild": [300, 200], "teil": None, "ref": None, "run": None, "punkt": None, "normale": None},
            {"t": 1.6, "bild": [640, 380], "teil": lasche, "ref": lasche_f, "run": 7, "punkt": [120.0, 4.0, 62.5],
             "normale": [0.0, 0.0, 1.0]},
            {"t": 2.4, "bild": None, "teil": None, "ref": None, "run": None, "punkt": None, "normale": None},
        ],
        "kamera_verlauf": [{"t": 0.0, "kamera": kamera}, {"t": 5.6, "kamera": kamera2}],
        "auswahl_verlauf": [{"t": 0.0, "run": 7, "refs": [lasche]}, {"t": 6.0, "run": 7, "refs": []}],
        "ende": {"kamera": kamera2, "viewport": {"breite": 1280, "hoehe": 800}, "sichtbar": ["Halter/Grundplatte", lasche],
                 "verborgen": ["Deckel"], "isoliert": None, "auswahl": {"run": 7, "refs": []},
                 "darstellung": "shaded_edges", "schnitt": None, "explosion": 0.0, "animation": None},
        "bild": {"datei": "fb-20261105-223011.jpg", "breite": 1280, "hoehe": 800},
    }


def feedback_beispiele() -> list[tuple[str, dict[str, Any], bytes, str]]:
    """Rahmen für die Testdateien: (Name, Kopf, Nutzlast, Richtung)."""
    return [
        ("feedback_stand_spricht", {"type": "FEEDBACK_STAND", "seq": 9, "sitzung": "s-1793480977",
                                    "stand": "spricht", "seit": 1793480977.25, "grund": None}, b"", "app"),
        ("feedback_stand_pause", {"type": "FEEDBACK_STAND", "seq": 10, "sitzung": "s-1793480977", "stand": "pause",
                                  "seit": 1793480980.75, "grund": None}, b"", "app"),
        ("feedback_stand_aus", {"type": "FEEDBACK_STAND", "seq": 11, "sitzung": "s-1793480977", "stand": "aus",
                                "seit": 1793480986.75, "grund": "fertig"}, b"", "app"),
        ("feedback_paket", {"type": "FEEDBACK_PAKET", "seq": 12, "sitzung": "s-1793480977",
                            "name": "fb-20261105-223011",
                            "datei": "/Users/kevin/Documents/Kev CAD/Halter/feedback/fb-20261105-223011.json",
                            "saetze": 2, "striche": 2, "dauer_s": 9.5}, b"", "app"),
        # I-5: vom iPad, das den Projektordner nicht hat: Paket und Bild als Nutzlast
        ("feedback_paket_nutzlast", {"type": "FEEDBACK_PAKET", "seq": 13, "sitzung": "s-1793480977",
                                     "name": "fb-20261105-223011",
                                     "nutzlast": {"json": len(_BEISPIEL_JSON), "bild": len(_BEISPIEL_JPEG)},
                                     "saetze": 2, "striche": 2, "dauer_s": 9.5},
         _BEISPIEL_JSON + _BEISPIEL_JPEG, "app"),
    ]


#: Nutzlast des Beispiels mit Paket: das Beispielpaket als JSON und ein kleinstes JPEG (Anfang und Ende)
_BEISPIEL_JPEG = b"\xff\xd8\xff\xd9"
_BEISPIEL_JSON = json.dumps(feedback_beispiel(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# =====================================================================================================================
# I-8 Datei ans Gerät (PROTOCOL.md, Abschnitt „I-8 Datei ans Gerät“): Ein Gerät ohne die Dateien des Mac (das iPad) holt
# eine Datei, die der Kernel am Mac geschrieben hat (Export, 3MF, PDF, CSV, Video, model.py), stückweise, um sie zu
# teilen. Freigegeben sind nur Dateien unter den Wurzeln des Kernels (runtime.py, datei_teilen.py).
# =====================================================================================================================

#: Stückgröße, wenn die App keine nennt, und die größte, die der Kernel schickt (Byte)
DATEI_STUECK_VORGABE = 4 * 1024 * 1024
DATEI_STUECK_MAX = 8 * 1024 * 1024
DATEI_NACHRICHTEN = ("DATEI_REQ", "DATEI", "DATEI_HOCH", "DATEI_HOCH_STAND")


def check_datei_message(header: dict[str, Any], payload: bytes = b"") -> list[str]:
    """Probleme einer Nachricht aus I-8 (leer = gut). Andere Nachrichten: leer."""
    art = header.get("type")
    if art not in DATEI_NACHRICHTEN:
        return []
    out: list[str] = []
    if art in ("DATEI_HOCH", "DATEI_HOCH_STAND"):
        return _check_datei_hoch(art, header, payload)
    if art == "DATEI_REQ":
        if not isinstance(header.get("id"), str) or not header["id"]:
            out.append("DATEI_REQ: id fehlt")
        if not isinstance(header.get("pfad"), str) or not header["pfad"].startswith("/"):
            out.append("DATEI_REQ: pfad ist kein absoluter Pfad")
        ab = header.get("ab", 0)
        if not isinstance(ab, int) or isinstance(ab, bool) or ab < 0:
            out.append("DATEI_REQ: ab ist keine Zahl ab 0")
        mx = header.get("max")
        if mx is not None and (not isinstance(mx, int) or isinstance(mx, bool) or mx <= 0):
            out.append("DATEI_REQ: max ist keine positive Zahl")
        if payload:
            out.append("DATEI_REQ mit Nutzlast")
        return out
    for feld in ("reply_to", "pfad", "name"):
        if not isinstance(header.get(feld), str) or not header[feld]:
            out.append(f"DATEI: {feld} fehlt")
    for feld in ("groesse", "ab", "laenge"):
        v = header.get(feld)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            out.append(f"DATEI: {feld} ist keine Zahl ab 0")
    if not out:
        if header["laenge"] != len(payload):
            out.append(f"DATEI: laenge {header['laenge']} passt nicht zur Nutzlast ({len(payload)} Byte)")
        if header["ab"] + header["laenge"] > header["groesse"]:
            out.append("DATEI: Stück reicht über das Dateiende")
        if header["laenge"] > DATEI_STUECK_MAX:
            out.append("DATEI: Stück größer als erlaubt")
    if not _zahl(header.get("geaendert")):
        out.append("DATEI: geaendert fehlt")
    return out


def _check_datei_hoch(art: str, header: dict[str, Any], payload: bytes) -> list[str]:
    out: list[str] = []
    feld = "id" if art == "DATEI_HOCH" else "reply_to"
    if not isinstance(header.get(feld), str) or not header[feld]:
        out.append(f"{art}: {feld} fehlt")
    for f in ("sitzung", "name"):
        if not isinstance(header.get(f), str) or not header[f]:
            out.append(f"{art}: {f} fehlt")
    if isinstance(header.get("name"), str) and ("/" in header["name"] or header["name"].startswith(".")):
        out.append(f"{art}: name ist kein Dateiname")
    zahlen = ("groesse", "ab") if art == "DATEI_HOCH" else ("groesse", "empfangen")
    for f in zahlen:
        v = header.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            out.append(f"{art}: {f} ist keine Zahl ab 0")
    if art == "DATEI_HOCH":
        if not out and header["ab"] + len(payload) > header["groesse"]:
            out.append("DATEI_HOCH: Stück reicht über die Größe")
        if len(payload) > DATEI_STUECK_MAX:
            out.append("DATEI_HOCH: Stück größer als erlaubt")
    else:
        if payload:
            out.append("DATEI_HOCH_STAND mit Nutzlast")
        pfad = header.get("pfad")
        fertig = not out and header["empfangen"] == header["groesse"]
        if fertig and not (isinstance(pfad, str) and pfad.startswith("/")):
            out.append("DATEI_HOCH_STAND: fertig ohne pfad")
        if not fertig and pfad is not None:
            out.append("DATEI_HOCH_STAND: pfad vor dem letzten Stück")
    return out


def datei_antwort(reply_to: str, pfad: str, groesse: int, ab: int, daten: bytes,
                  geaendert: float) -> tuple[dict[str, Any], bytes]:
    """Kopf und Nutzlast der Antwort DATEI auf DATEI_REQ (ein Stück ab ``ab``)."""
    kopf = {"type": "DATEI", "reply_to": reply_to, "pfad": pfad, "name": pfad.rsplit("/", 1)[-1],
            "groesse": int(groesse), "ab": int(ab), "laenge": len(daten), "geaendert": float(geaendert)}
    return kopf, daten


def datei_beispiele() -> list[tuple[str, dict[str, Any], bytes, str]]:
    """Rahmen für die Testdateien: (Name, Kopf, Nutzlast, Richtung)."""
    inhalt = b"solid Halter\nendsolid Halter\n"
    pfad = "/Users/kevin/Documents/Kev CAD/Halter/output/Halter.stl"
    erstes, nutz1 = datei_antwort("a-31", pfad, len(inhalt), 0, inhalt[:16], 1793480977.5)
    zweites, nutz2 = datei_antwort("a-32", pfad, len(inhalt), 16, inhalt[16:], 1793480977.5)
    return [
        ("datei_req", {"type": "DATEI_REQ", "seq": 31, "id": "a-31", "pfad": pfad, "ab": 0, "max": 16}, b"", "app"),
        ("datei_stueck", {**erstes, "seq": 40}, nutz1, "kernel"),
        ("datei_stueck_ende", {**zweites, "seq": 41}, nutz2, "kernel"),
        # Gegenrichtung: das iPad schickt eine CAD-Datei in zwei Stücken an den Mac
        ("datei_hoch", {"type": "DATEI_HOCH", "seq": 32, "id": "a-33", "sitzung": "c1a2b3c4", "name": "Auszug.step",
                        "groesse": len(inhalt), "ab": 0}, inhalt[:16], "app"),
        ("datei_hoch_stand", {"type": "DATEI_HOCH_STAND", "seq": 42, "reply_to": "a-33", "sitzung": "c1a2b3c4",
                              "name": "Auszug.step", "groesse": len(inhalt), "empfangen": 16, "pfad": None},
         b"", "kernel"),
        ("datei_hoch_fertig", {"type": "DATEI_HOCH_STAND", "seq": 43, "reply_to": "a-34", "sitzung": "c1a2b3c4",
                               "name": "Auszug.step", "groesse": len(inhalt), "empfangen": len(inhalt),
                               "pfad": "/Users/kevin/Library/Application Support/de.upvis.kevcad/Eingang/c1a2b3c4/"
                                       "Auszug.step"}, b"", "kernel"),
    ]


# =====================================================================================================================
# I-6 Live-Kopplung (PROTOCOL.md, Abschnitt „I-6 Live-Kopplung“; PLAN-IPAD.md, Abschnitt 5): Gemeinsame und Eigene
# Ansicht, Führung, Live-Striche. Die Weiterleitung steht in kopplung.py; hier Format, Prüfen und Beispiele für die
# Testdateien (tools/make_kopplung_fixtures.py).
# =====================================================================================================================

ANSICHT_MODI: tuple[str, ...] = ("gemeinsam", "eigen")
#: neue Nachrichten App → Kernel
ANSICHT_APP_NACHRICHTEN: tuple[str, ...] = ("ANSICHT_MODUS", "ANSICHT", "SPRECHEN_LIVE")
#: Teile einer ANSICHT (je Teil nur, wenn er sich geändert hat; mit ``voll`` alle)
ANSICHT_TEILE: tuple[str, ...] = ("kamera", "sicht", "auswahl", "darstellung", "schnitt", "explosion")
ANSICHT_KAMERA_FELDER: tuple[str, ...] = ("drehung", "ziel", "abstand", "projektion", "fov", "ortho_hoehe")
#: Nach so langer Ruhe des führenden Geräts darf ein anderes ohne neuen Griff übernehmen (Sekunden)
FUEHRUNG_PAUSE_S = 1.0
#: So oft schickt ein Gerät höchstens eine ANSICHT, während Kevin dort bedient (je Sekunde)
ANSICHT_JE_S = 60
#: Live-Striche: höchstens so viele Nachrichten je Sekunde und Punkte je Strich
SPRECHEN_LIVE_JE_S = 20
SPRECHEN_LIVE_PUNKTE_MAX = 2000
SPRECHEN_LIVE_TEXT_MAX = 2000


def _quaternion(x: Any) -> bool:
    return isinstance(x, list) and len(x) == 4 and all(_zahl(v) for v in x)


def check_ansicht_kamera(k: Any) -> list[str]:
    if not isinstance(k, dict):
        return ["kamera kein Objekt"]
    out: list[str] = []
    if not _quaternion(k.get("drehung")):
        out.append("kamera.drehung keine Quaternion [x, y, z, w]")
    if not _punkt(k.get("ziel")):
        out.append("kamera.ziel kein Punkt")
    for feld in ("abstand", "fov", "ortho_hoehe"):
        if not _zahl(k.get(feld)) or k[feld] <= 0:
            out.append(f"kamera.{feld} keine positive Zahl")
    if k.get("projektion") not in ("perspective", "orthographic"):
        out.append("kamera.projektion ungültig")
    return out


def check_ansicht_message(header: dict[str, Any], payload: bytes = b"") -> list[str]:
    """Probleme einer Nachricht aus I-6 (leer = gut). Andere Nachrichten: leer."""
    art = header.get("type")
    out: list[str] = []
    if art not in ("ANSICHT_MODUS", "ANSICHT", "SPRECHEN_LIVE", "GERAETE"):
        return out
    if payload:
        out.append(f"{art} mit Nutzlast")
    if art == "ANSICHT_MODUS":
        if header.get("modus") not in ANSICHT_MODI:
            out.append(f"ANSICHT_MODUS: modus {header.get('modus')!r} ungültig")
    elif art == "ANSICHT":
        if not _zahl(header.get("t")):
            out.append("ANSICHT: t fehlt")
        for feld in ("griff", "voll"):
            if not isinstance(header.get(feld), bool):
                out.append(f"ANSICHT: {feld} kein Wahrheitswert")
        if "von" in header and not isinstance(header["von"], int):
            out.append("ANSICHT: von keine Nummer")
        if not any(k in header for k in ANSICHT_TEILE):
            out.append("ANSICHT ohne Inhalt")
        if header.get("voll") is True and not all(k in header for k in ANSICHT_TEILE):
            out.append("ANSICHT: voll, aber nicht alle Teile")
        if "kamera" in header:
            out += ["ANSICHT: " + p for p in check_ansicht_kamera(header["kamera"])]
        if "sicht" in header:
            s = header["sicht"]
            if not isinstance(s, dict) or not _namen(s.get("verborgen")) or (
                    s.get("isoliert") is not None and not _namen(s.get("isoliert"))):
                out.append("ANSICHT: sicht ungültig (verborgen, isoliert)")
        if "auswahl" in header:
            a = header["auswahl"]
            if not isinstance(a, dict) or not _namen(a.get("refs")) or (
                    a.get("run") is not None and not isinstance(a.get("run"), int)):
                out.append("ANSICHT: auswahl ungültig (run, refs)")
        if "darstellung" in header and not isinstance(header["darstellung"], str):
            out.append("ANSICHT: darstellung kein Text")
        if "schnitt" in header and header["schnitt"] is not None:
            s = header["schnitt"]
            if not isinstance(s, dict) or not _punkt(s.get("normale")) or not _zahl(s.get("abstand")):
                out.append("ANSICHT: schnitt ungültig (normale, abstand)")
        if "explosion" in header and not _zahl(header["explosion"]):
            out.append("ANSICHT: explosion keine Zahl")
    elif art == "SPRECHEN_LIVE":
        if not isinstance(header.get("sitzung"), str) or not header["sitzung"]:
            out.append("SPRECHEN_LIVE: sitzung fehlt")
        if "von" in header and not isinstance(header["von"], int):
            out.append("SPRECHEN_LIVE: von keine Nummer")
        st = header.get("strich")
        if st is not None:
            if not isinstance(st, dict) or not isinstance(st.get("nr"), int) or not isinstance(st.get("fertig"), bool):
                out.append("SPRECHEN_LIVE: strich ungültig (nr, fertig)")
            elif not isinstance(st.get("punkte"), list) or not all(_punkt(p) for p in st["punkte"]) \
                    or len(st["punkte"]) > SPRECHEN_LIVE_PUNKTE_MAX:
                out.append("SPRECHEN_LIVE: strich.punkte ungültig")
        if "zeiger" in header and header["zeiger"] is not None and not _punkt(header["zeiger"]):
            out.append("SPRECHEN_LIVE: zeiger kein Punkt")
        if "text" in header and (not isinstance(header["text"], str) or len(header["text"]) > SPRECHEN_LIVE_TEXT_MAX):
            out.append("SPRECHEN_LIVE: text ungültig")
        if "ende" in header and not isinstance(header["ende"], bool):
            out.append("SPRECHEN_LIVE: ende kein Wahrheitswert")
    elif art == "GERAETE":
        g = header.get("geraete")
        if not isinstance(g, list) or not g:
            out.append("GERAETE: geraete fehlt")
        else:
            for e in g:
                if not isinstance(e, dict) or not isinstance(e.get("nr"), int) or e.get("art") not in ("mac", "ipad"):
                    out.append("GERAETE: Eintrag ohne nr oder art")
                    continue
                if e.get("ansicht") is not None and e["ansicht"] not in ANSICHT_MODI:
                    out.append("GERAETE: ansicht ungültig")
                for feld in ("aktiv", "fuehrt", "ich"):
                    if not isinstance(e.get(feld), bool):
                        out.append(f"GERAETE: {feld} kein Wahrheitswert")
            if sum(1 for e in g if isinstance(e, dict) and e.get("ich") is True) != 1:
                out.append("GERAETE: nicht genau ein Eintrag mit ich")
    return out


def ansicht_beispiele() -> list[tuple[str, dict[str, Any], bytes, str]]:
    """Rahmen für die Testdateien: (Name, Kopf, Nutzlast, Richtung)."""
    kamera = {"drehung": [0.2797, 0.1159, 0.3647, 0.8806], "ziel": [120.0, 0.0, 60.0], "abstand": 1118.0,
              "projektion": "perspective", "fov": 30.0, "ortho_hoehe": 240.0}
    voll = {"type": "ANSICHT", "seq": 31, "t": 1793480990.125, "griff": True, "voll": True, "kamera": kamera,
            "sicht": {"verborgen": ["Deckel"], "isoliert": None},
            "auswahl": {"run": 8, "refs": ["Halter/Lasche#f0"]}, "darstellung": "shaded_edges",
            "schnitt": {"normale": [0.0, 0.0, -1.0], "abstand": 5.0}, "explosion": 0.0}
    return [
        ("ansicht_modus", {"type": "ANSICHT_MODUS", "seq": 2, "modus": "gemeinsam"}, b"", "app"),
        ("ansicht_modus_eigen", {"type": "ANSICHT_MODUS", "seq": 3, "modus": "eigen"}, b"", "app"),
        ("ansicht_voll", voll, b"", "app"),
        ("ansicht_kamera", {"type": "ANSICHT", "seq": 32, "t": 1793480990.142, "griff": False, "voll": False,
                            "kamera": {**kamera, "abstand": 1050.0}}, b"", "app"),
        ("ansicht_weiter", {**{k: v for k, v in voll.items() if k != "griff"}, "griff": False, "seq": 40, "von": 2},
         b"", "kernel"),
        ("ansicht_parallel", {"type": "ANSICHT", "seq": 41, "t": 1793480991.5, "griff": False, "voll": False,
                              "von": 1, "kamera": {"drehung": [0.0, 0.0, 0.0, 1.0], "ziel": [20.0, 10.0, 0.0],
                                                   "abstand": 1000.0, "projektion": "orthographic", "fov": 30.0,
                                                   "ortho_hoehe": 240.0},
                              "sicht": {"verborgen": [], "isoliert": ["Halter/Lasche"]}, "schnitt": None},
         b"", "kernel"),
        ("geraete", {"type": "GERAETE", "seq": 42, "geraete": [
            {"nr": 1, "art": "mac", "name": "MacBook von Kevin", "app": "de.upvis.kevcad", "aktiv": False,
             "ansicht": "gemeinsam", "fuehrt": False, "ich": False},
            {"nr": 2, "art": "ipad", "name": "iPad von Kevin", "app": "de.upvis.kevcad.ipad", "aktiv": True,
             "ansicht": "gemeinsam", "fuehrt": True, "ich": True}]}, b"", "kernel"),
        ("sprechen_live_strich", {"type": "SPRECHEN_LIVE", "seq": 50, "sitzung": "s-1793480977",
                                  "strich": {"nr": 1, "punkte": [[118.0, 4.0, 60.0], [121.5, 4.0, 62.0]],
                                             "fertig": False},
                                  "zeiger": [121.5, 4.0, 62.0], "text": "Mach das hier"}, b"", "app"),
        ("sprechen_live_ende", {"type": "SPRECHEN_LIVE", "seq": 51, "sitzung": "s-1793480977", "ende": True,
                                "von": 2}, b"", "kernel"),
    ]
