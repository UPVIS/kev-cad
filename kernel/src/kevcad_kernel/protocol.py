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


# Phase 6: Bauplan (DOKUMENTE.md, Abschnitt „Protokoll“; Strang P6-B)

# Linienarten der Strichbilder im Bauplan: die acht der Zeichnungen, dazu ``neu`` (neue Teile des Schritts,
# hervorgehoben) und ``pfeil`` (Einführpfeile). Die App zeichnet unbekannte Arten dünn durchgezogen.
BAUPLAN_LINIEN: tuple[str, ...] = (*LINIEN_REIHENFOLGE, "neu", "pfeil")
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
