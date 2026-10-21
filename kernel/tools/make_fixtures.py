"""Erzeugt die Testdateien des Protokolls für Kernel und App (siehe PROTOCOL.md).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/

- <name>.frame   je ein Rahmen
- stream.bin     alle Rahmen hintereinander (für schrittweises Einlesen)
- fixtures.json  erwartete Werte, die beide Seiten in ihren Tests prüfen
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from build123d import Box, Cylinder, GeomType, Pos
from OCP.BRep import BRep_Tool
from ocp_tessellate.ocp_utils.topology import get_edges
from ocp_tessellate.tessellator import compute_quality, tessellate

from kevcad_kernel.protocol import PartGeometry, encode_frame, pack_part

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"

TYP = {
    GeomType.PLANE: "plane", GeomType.CYLINDER: "cylinder", GeomType.CONE: "cone", GeomType.SPHERE: "sphere",
    GeomType.TORUS: "torus", GeomType.BSPLINE: "bspline", GeomType.LINE: "line", GeomType.CIRCLE: "circle",
    GeomType.ELLIPSE: "ellipse",
}


def r3(v) -> list[float]:
    return [round(float(v.X), 4), round(float(v.Y), 4), round(float(v.Z), 4)]


def geometry_of(shape) -> PartGeometry:
    bb = shape.bounding_box()
    quality = compute_quality(SimpleNamespace(xsize=bb.size.X, ysize=bb.size.Y, zsize=bb.size.Z), 0.1)
    t = tessellate(shape.wrapped, f"fixture-{id(shape)}", deviation=0.1, quality=quality, angular_tolerance=0.2)
    tpf = np.asarray(t["triangles_per_face"], dtype=np.int64)
    segs = np.asarray(t["edges"], dtype=np.float32).reshape(-1, 2, 3)
    spe = np.asarray(t["segments_per_edge"], dtype=np.int64)
    degenerated = [BRep_Tool.Degenerated_s(e) for e in get_edges(shape.wrapped)]
    pts, offs, s = [], [0], 0
    for n, deg in zip(spe, degenerated):
        n = int(n)
        chunk = segs[s:s + n]
        s += n
        if deg:
            continue
        poly = np.vstack([chunk[:, 0], chunk[-1:, 1]]) if n else np.zeros((0, 3), np.float32)
        pts.append(poly)
        offs.append(offs[-1] + len(poly))
    faces = []
    for f in shape.faces():
        d = {"t": TYP.get(f.geom_type, "other"), "a": round(f.area, 4)}
        if f.geom_type == GeomType.PLANE:
            d["n"] = r3(f.normal_at())
            d["c"] = r3(f.center())
        elif f.geom_type == GeomType.CYLINDER:
            d["r"] = round(f.radius, 4)
            d["ax"] = r3(f.axis_of_rotation.direction)
            d["c"] = r3(f.axis_of_rotation.position)
        faces.append(d)
    edges = []
    for e in shape.edges():
        d = {"t": TYP.get(e.geom_type, "other"), "l": round(e.length, 4)}
        if e.geom_type == GeomType.CIRCLE:
            d["r"] = round(e.radius, 4)
            d["c"] = r3(e.arc_center)
        edges.append(d)
    return PartGeometry(
        positions=np.asarray(t["vertices"], dtype=np.float32).reshape(-1, 3),
        normals=np.asarray(t["normals"], dtype=np.float32).reshape(-1, 3),
        triangles=np.asarray(t["triangles"], dtype=np.uint32).reshape(-1, 3),
        tri_face=np.repeat(np.arange(len(tpf), dtype=np.int32), tpf),
        edge_points=np.vstack(pts).astype(np.float32) if pts else np.zeros((0, 3), np.float32),
        edge_offsets=np.asarray(offs, dtype=np.uint32),
        vertices=np.asarray([[v.X, v.Y, v.Z] for v in shape.vertices()], dtype=np.float32).reshape(-1, 3),
        faces=faces,
        edges=edges,
    )


def part_frame(seq: int, run: int, name: str, shape, color) -> tuple[bytes, dict]:
    g = geometry_of(shape)
    bb = shape.bounding_box()
    bbox = {"min": r3(bb.min), "max": r3(bb.max)}
    props = {"volume": round(shape.volume, 4), "area": round(shape.area, 4), "center": r3(shape.center())}
    header, payload = pack_part(run=run, name=name, geometry=g, color=color, bbox=bbox, props=props, seq=seq)
    expect = {
        "name": name,
        "counts": header["counts"],
        "payload_bytes": len(payload),
        "first_position": [round(float(x), 4) for x in g.positions[0]],
        "first_triangle": [int(x) for x in g.triangles[0]],
        "tri_face_last": int(g.tri_face[-1]),
        "face_types": [f["t"] for f in g.faces],
        "edge_types": [e["t"] for e in g.edges],
        "bbox": bbox,
        "volume": props["volume"],
    }
    return encode_frame(header, payload), expect


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[str, bytes]] = []
    expected: dict = {"protocol": 1, "frames": [], "parts": {}}

    def add(name: str, header: dict, payload: bytes = b"") -> None:
        frames.append((name, encode_frame(header, payload)))
        expected["frames"].append({"file": f"{name}.frame", "type": header["type"], "payload_bytes": len(payload)})

    add("hello", {"type": "HELLO", "seq": 1, "protocol": 1, "kernel_version": "0.1.0", "build123d": "0.13.0",
                  "mcp_port": 47823})
    add("project", {"type": "PROJECT", "seq": 2, "path": "/Users/test/Documents/Kev CAD/Wandhalter",
                    "name": "Wandhalter", "model": "/Users/test/Documents/Kev CAD/Wandhalter/model.py"})
    add("run_start", {"type": "RUN_START", "seq": 3, "run": 1, "file_hash": "abc123", "params": {"breite": 120},
                      "slow_ms": 0})
    add("step", {"type": "STEP", "seq": 4, "run": 1, "index": 1, "text": "Grundplatte"})

    box = Box(10, 20, 30)
    data, exp = part_frame(5, 1, "Grundplatte", box, (0.72, 0.75, 0.79, 1.0))
    frames.append(("part_box", data))
    expected["frames"].append({"file": "part_box.frame", "type": "PART_UPSERT", "payload_bytes": exp["payload_bytes"]})
    expected["parts"]["part_box.frame"] = exp

    cyl = Pos(30, 0, 0) * Cylinder(5, 20)
    data, exp = part_frame(6, 1, "Halter/Bolzen", cyl, (0.85, 0.55, 0.2, 1.0))
    frames.append(("part_cylinder", data))
    expected["frames"].append({"file": "part_cylinder.frame", "type": "PART_UPSERT",
                               "payload_bytes": exp["payload_bytes"]})
    expected["parts"]["part_cylinder.frame"] = exp

    add("run_end", {"type": "RUN_END", "seq": 7, "run": 1, "duration_ms": 412, "parts": 2, "triangles": 0,
                    "warnings": [], "params": {"breite": 120}})
    add("run_error", {"type": "RUN_ERROR", "seq": 8, "run": 2, "message": "NameError: name 'Boxx' is not defined",
                      "line": 7, "excerpt": "6 | step('Grundplatte')\n7 | platte = Boxx(10, 20, 30)",
                      "traceback": "File model.py, line 7"})
    add("agent", {"type": "AGENT", "seq": 9, "connected": True, "activity": "misst Abstand Lasche ↔ Grundplatte",
                  "sessions": [{"session_id": "6b1f2c3d-0000-4000-8000-00000000000a", "aktiv": True,
                                "seit": "2026-10-21T21:50:00Z", "taetigkeit": "misst Abstand Lasche ↔ Grundplatte",
                                "zuletzt": "2026-10-21T22:05:12Z"},
                               {"session_id": "6b1f2c3d-0000-4000-8000-00000000000b", "aktiv": False,
                                "seit": "2026-10-21T21:58:30Z", "taetigkeit": None}]})
    add("view_cmd_focus", {"type": "VIEW_CMD", "seq": 10, "id": "k-1", "cmd": "focus",
                           "args": {"refs": ["Halter/Bolzen"], "animate": True}})
    add("screenshot_req", {"type": "SCREENSHOT_REQ", "seq": 11, "id": "k-2", "width": 1280, "height": 800,
                           "source": "current", "view": None, "hide_overlays": False})
    add("measure_res", {"type": "MEASURE_RES", "seq": 12, "reply_to": "a-5", "result": {
        "refs": ["Grundplatte#f0", "Halter/Bolzen#f1"], "run": 1, "kind": "distance",
        "values": {"distance": 20.0, "dx": 20.0, "dy": 0.0, "dz": 0.0},
        "points": [[5.0, 0.0, 15.0], [25.0, 0.0, 15.0]], "text": "Abstand 20,000 mm (dx 20,000)"}})
    add("part_remove", {"type": "PART_REMOVE", "seq": 13, "run": 2, "name": "Halter/Bolzen"})

    # Phase 2: Lagerteil, Stückliste, Katalog (PROTOCOL.md Abschnitt "Phase 2")
    from build123d import Rectangle, extrude
    rohr = extrude(Rectangle(40, 40) - Rectangle(34, 34), amount=882)
    data, exp = part_frame(14, 3, "Gestell/Bein vorn links", rohr, (0.54, 0.56, 0.6, 1.0))
    header_len = int.from_bytes(data[:4], "little")
    head = json.loads(data[4:4 + header_len])
    head["stock"] = {"id": "vierkantrohr-en10219-40x40x3", "name": "Vierkantrohr 40 × 40 × 3", "laenge": 882.0,
                     "gehrung": [0, 45], "material": "stahl-s235", "kg": 2.98, "preis": 7.06}
    payload = data[8 + header_len:]
    data = encode_frame(head, payload)
    exp["stock"] = head["stock"]
    frames.append(("part_stock", data))
    expected["frames"].append({"file": "part_stock.frame", "type": "PART_UPSERT", "payload_bytes": len(payload)})
    expected["parts"]["part_stock.frame"] = exp

    add("bom", {"type": "BOM", "seq": 15, "run": 3, "lines": [
        {"pos": 1, "art": "vierkantrohr", "stock_id": "vierkantrohr-en10219-40x40x3",
         "benennung": "Vierkantrohr 40 × 40 × 3", "norm": "DIN EN 10219", "material": "Stahl S235", "laenge": 882.0,
         "gehrung": [0, 45], "masse_text": "882 mm", "anzahl": 4, "kg_je": 2.98, "kg": 11.92, "preis_je": 7.06,
         "preis": 28.24, "teile": ["Gestell/Bein vorn links", "Gestell/Bein vorn rechts", "Gestell/Bein hinten links",
                                   "Gestell/Bein hinten rechts"], "eigenteil": False},
        {"pos": 2, "art": "platte", "stock_id": "platte-multiplex-birke-18", "benennung": "Multiplex Birke 18 mm",
         "norm": None, "material": "Multiplex Birke", "laenge": None, "gehrung": [0, 0], "masse_text": "800 × 600 mm",
         "flaeche_m2": 0.48, "anzahl": 1, "kg_je": 5.9, "kg": 5.9, "preis_je": 21.6, "preis": 21.6,
         "teile": ["Deckel"], "eigenteil": False},
        {"pos": 3, "art": "schraube", "stock_id": "schraube-iso4762-m8", "benennung": "Zylinderschraube ISO 4762",
         "norm": "ISO 4762", "material": "Stahl 8.8 verzinkt", "laenge": 60.0, "gehrung": [0, 0],
         "masse_text": "M8 × 60", "anzahl": 8, "kg_je": 0.031, "kg": 0.248, "preis_je": 0.32, "preis": 2.56,
         "teile": [f"Schrauben/M8x60 {i}" for i in range(1, 9)], "eigenteil": False},
        {"pos": 4, "art": "eigenteil", "stock_id": None, "benennung": "Halter", "norm": None, "material": "Aluminium",
         "laenge": None, "gehrung": [0, 0], "masse_text": "60 × 5 × 120 mm", "anzahl": 1, "kg_je": 0.096,
         "kg": 0.096, "preis_je": None, "preis": None, "teile": ["Halter"], "eigenteil": True}],
        "cuts": [{"stock_id": "vierkantrohr-en10219-40x40x3", "benennung": "Vierkantrohr 40 × 40 × 3",
                  "stangenlaenge": 6000, "saegeschnitt": 3, "stangen": [[882, 882, 882, 882, 800, 800]],
                  "verschnitt_prozent": 13.6}],
        "totals": {"kg": 18.16, "preis": 52.4, "positionen": 4, "teile": 14,
                   "preis_hinweis": "Richtpreise, Stand 2026-10"},
        "warnings": ["Halter: kein Lagerteil, Masse aus Volumen × Dichte"]})
    add("catalog", {"type": "CATALOG", "seq": 16, "reply_to": "a-9", "arten": ["rohr", "vierkantrohr", "platte"],
                    "materials": [{"id": "stahl-s235", "name": "Stahl S235", "gruppe": "Stahl", "dichte": 7.85,
                                   "farbe": "#8A9099", "preis_je_kg": 2.4, "preis_quelle": "Richtwert",
                                   "preis_stand": "2026-10", "ebene": "mitgeliefert"}],
                    "items": [{"id": "vierkantrohr-en10219-40x40x3", "art": "vierkantrohr",
                               "name": "Vierkantrohr 40 × 40 × 3", "norm": "DIN EN 10219",
                               "masse": {"a": 40, "s": 3}, "material": "stahl-s235", "kg_je_m": 3.41,
                               "stangenlaenge": 6000, "preis": {"je_m": 8.0, "quelle": "Richtwert", "stand": "2026-10"},
                               "tags": ["quadrat"], "ebene": "mitgeliefert"},
                              {"id": "rohr-edelstahl-33.7x2", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2",
                               "norm": "ISO 1127", "masse": {"d": 33.7, "s": 2.0}, "material": "edelstahl-1.4301",
                               "preis": {"je_m": 14.5, "quelle": "Kevin", "stand": "2026-10"}, "ebene": "eigen"}]})

    # Phase 5: Animation (PROTOCOL.md Abschnitt "Phase 5: Animation")
    from kevcad.bewegung import Animation
    from kevcad_kernel.animation import evaluate_all, pack_anim_def

    anim = Animation(1, 4, "Fahrt")
    anim.bewege("Wagen", nach=(314.159265, 0, 0), von=0, bis=1)
    anim.rolle("Wagen/Rad", auf="Wagen", radius=50, achse="y")
    anim.sichtbar("Wagen/Rad", an=False, zeit=0.75)
    anim.ansicht(0, lage=(0, -1000, 500), ziel=(0, 0, 0), kurve="linear")
    anim.ansicht(1, lage=(1000, -1000, 500), ziel=(314, 0, 0), bildwinkel=40, kurve="linear")
    order = ["Wagen/Platte", "Wagen/Rad", "Boden"]
    bboxes = {"Wagen/Platte": ([-300, -200, 100], [300, 200, 120]), "Wagen/Rad": ([-50, -16, 0], [50, 16, 100]),
              "Boden": ([-1000, -1000, -10], [1000, 1000, 0])}
    (ausw,) = evaluate_all([anim], order, bboxes)
    head, payload = pack_anim_def(ausw, 4)
    add("anim_def", {**head, "seq": 17}, payload)
    expected["animations"] = {"anim_def.frame": {
        "name": "Fahrt", "bilder": ausw.frames, "teile": ausw.teile, "dauer": 1.0, "fps": 4.0,
        "matrices": {f"{k}/{j}": [[round(float(v), 5) for v in row] for row in ausw.matrices[k, j]]
                     for k in (0, 2, 4) for j in range(len(ausw.teile))},
        "kamera": [[round(float(v), 4) for v in ausw.kamera[k]] for k in range(ausw.frames)],
        "sichtbar": ausw.sichtbar}}
    add("anim_collisions", {"type": "ANIM_COLLISIONS", "seq": 18, "name": "Fahrt", "run": 4, "reply_to": "a-12",
                            "kollisionen": [{"teile": ["Wagen/Rad", "Boden"], "von": 0.25, "bis": 0.5, "zeit": 0.5,
                                             "bild": 2, "tiefe": 1.5, "volumen": 230.4, "ort": [157.1, 0.0, -0.7],
                                             "bilder": [1, 2]}],
                            "geprueft": {"paare": 2, "bilder": 5, "schritt": 1, "geprueft_bilder": 5, "ms": 12.5}})
    add("anim_remove", {"type": "ANIM_REMOVE", "seq": 19, "name": "Alt"})
    add("anim_play", {"type": "ANIM_PLAY", "seq": 20, "id": "k-7", "name": "Fahrt", "an": True, "schleife": True,
                      "geschwindigkeit": 0.5, "von_vorn": False})
    add("anim_seek", {"type": "ANIM_SEEK", "seq": 21, "id": "k-8", "name": "Fahrt", "zeit": 0.5})
    add("anim_video_req", {"type": "ANIM_VIDEO_REQ", "seq": 22, "id": "k-9", "name": "Fahrt", "width": 640,
                           "height": 360, "fps": 4.0, "kamera": None, "format": "mp4",
                           "path": "/Users/test/Documents/Kev CAD/Wagen/output/animationen/Fahrt.mp4"})

    for name, data in frames:
        (ZIEL / f"{name}.frame").write_bytes(data)
    (ZIEL / "stream.bin").write_bytes(b"".join(d for _, d in frames))
    # Zwangsbedingungen (PROTOCOL.md, Abschnitt Zwangsbedingungen): eigene Datei, nicht im Strom
    from kevcad_kernel.protocol import constraints_example

    (ZIEL / "constraints.frame").write_bytes(encode_frame({**constraints_example(), "seq": 17}))
    (ZIEL / "fixtures.json").write_text(json.dumps(expected, indent=1, ensure_ascii=False))
    print(f"{len(frames)} Rahmen nach {ZIEL}")
    import make_pruef_fixtures  # Prüfung (CHECK): eigene Dateien, stream.bin bleibt gleich

    make_pruef_fixtures.main()


if __name__ == "__main__":
    main()
