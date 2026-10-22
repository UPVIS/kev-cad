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
CHECK_STATES = ("running", "done", "teilweise", "cancelled", "failed")


def pack_check(*, run: int, state: str, ergebnis: dict[str, Any] | None = None,
               geometrie: list[tuple[np.ndarray, np.ndarray, np.ndarray]] | None = None, message: str | None = None,
               seq: int = 0, im_hintergrund: list[str] | None = None) -> tuple[dict[str, Any], bytes]:
    """Baut Kopf und Nutzlast von CHECK (Prüfergebnis, PROTOCOL.md Abschnitt „Prüfung“). ``geometrie``: je
    Schnittkörper (Punkte (n, 3), Normalen (n, 3), Dreiecke (m, 3)); die Nutzlast reiht sie hintereinander.
    ``state`` "teilweise" (additiv, Prüftempo): Ergebnis steht, der Bewegungsraum wird noch fertig gerechnet;
    ``im_hintergrund`` nennt die offenen Wege, danach folgt dasselbe ``run`` mit "done"."""
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


def unpack_netze(koepfe: list[dict[str, Any]], payload: bytes) -> list[dict[str, np.ndarray]]:
    """Gegenstück zu pack_netze."""
    out = []
    offset = 0
    for k in koepfe:
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
                  optionen: dict[str, Any] | None = None, auftrag: str | None = None, seq: int = 0) -> dict[str, Any]:
    h: dict[str, Any] = {"type": "PRINT_JOB_REQ", "seq": seq, "id": id, "platten": [int(p) for p in (platten or [])],
                         "weg": weg, "bestaetigt": bool(bestaetigt)}
    if optionen is not None:
        h["optionen"] = dict(optionen)
    if auftrag is not None:
        h["auftrag"] = auftrag
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
STATIK_LAST_FELDER = ("teile", "kraft", "punkt", "kg", "zeile", "gegen", "paar")  # Feld ``lasten`` je Szenario (T32)
STATIK_ABLAUF_STAENDE = ("done", "laeuft", "failed")  # Stufe 2 (Ablauf): Feld ``ablauf`` je Szenario
STATIK_ABLAUF_KURZ = ("kippreserve", "a_abheben", "abheben_max_mm", "kippwinkel_max", "rutschgrenze", "rutschreserve",
                      "geschwindigkeit", "verzoegerung")
STATIK_FK_STAENDE = ("done", "laeuft", "failed", "abgebrochen")  # Stufe 3 (Festkörper): Feld ``festkoerper``
STATIK_FK_TEIL = ("teil", "stand", "ampel", "sicherheit", "ziel", "ausnutzung", "spannung_max", "kriterium", "ort",
                  "sicherheit_lagerrand", "verformung_max_mm", "kragtraeger", "druckteil", "q", "ausrichtungen",
                  "ausrichtung_beste", "netz", "ms", "feld", "meldung", "text", "aus_speicher")
STATIK_FELD_ARRAYS = (("punkte", "<f4", 3), ("dreiecke", "<u4", 3), ("ausnutzung", "<f4", 1), ("spannung", "<f4", 1),
                      ("verschiebung", "<f4", 3))


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
    header = {"type": "STATICS_FIELD", "seq": seq, "run": int(run),
              **{k: kopf.get(k) for k in ("szenario", "teil", "feld", "ziel", "sicherheit", "ampel", "spannung_max",
                                         "verformung_max_mm", "ueberhoehung")},
              "werte": "ausnutzung", "punkte": n, "dreiecke": m}
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
