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
    add("agent", {"type": "AGENT", "seq": 9, "connected": True, "activity": "misst Abstand Lasche ↔ Grundplatte"})
    add("view_cmd_focus", {"type": "VIEW_CMD", "seq": 10, "id": "k-1", "cmd": "focus",
                           "args": {"refs": ["Halter/Bolzen"], "animate": True}})
    add("screenshot_req", {"type": "SCREENSHOT_REQ", "seq": 11, "id": "k-2", "width": 1280, "height": 800,
                           "source": "current", "view": None, "hide_overlays": False})
    add("measure_res", {"type": "MEASURE_RES", "seq": 12, "reply_to": "a-5", "result": {
        "refs": ["Grundplatte#f0", "Halter/Bolzen#f1"], "run": 1, "kind": "distance",
        "values": {"distance": 20.0, "dx": 20.0, "dy": 0.0, "dz": 0.0},
        "points": [[5.0, 0.0, 15.0], [25.0, 0.0, 15.0]], "text": "Abstand 20,000 mm (dx 20,000)"}})
    add("part_remove", {"type": "PART_REMOVE", "seq": 13, "run": 2, "name": "Halter/Bolzen"})

    for name, data in frames:
        (ZIEL / f"{name}.frame").write_bytes(data)
    (ZIEL / "stream.bin").write_bytes(b"".join(d for _, d in frames))
    (ZIEL / "fixtures.json").write_text(json.dumps(expected, indent=1, ensure_ascii=False))
    print(f"{len(frames)} Rahmen nach {ZIEL}")


if __name__ == "__main__":
    main()
