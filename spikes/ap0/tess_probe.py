"""AP0 Kerneltest: Outdoorküche mit ocp-tessellate zerlegen, Flächen-/Kantenreihenfolge gegen build123d
prüfen und das Ergebnis als Binärdatei für den Viewer-Test schreiben.

Aufruf:  .venv/bin/python tess_probe.py [--innen] [--deviation 0.1] [--out kueche.kcad]

Dateiformat (little endian), nur für den Test:
  b"KCAD" · u32 Version · u32 JSON-Länge · JSON · Auffüllung auf 4 Byte · Datenblock
  JSON: {"parts": [{name, color, n_vert, n_tri, n_face, n_edge, n_epts, off_*}], "stats": {...}}
  Datenblock je Teil: f32 Punkte (n_vert*3), f32 Normalen (n_vert*3), u32 Dreiecke (n_tri*3),
  i32 Fläche je Dreieck (n_tri), f32 Kantenpunkte (n_epts*3), u32 Kantenversatz (n_edge+1)
"""
import argparse
import json
import struct
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

KUECHE = Path("/Users/kevinschwed/Code Experiments/Beelonia/cad/outdoor-kueche")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--innen", action="store_true", help="Animationsvariante mit Innenleben")
    ap.add_argument("--deviation", type=float, default=0.1)
    ap.add_argument("--angular", type=float, default=0.2)
    ap.add_argument("--out", default="kueche.kcad")
    args = ap.parse_args()

    t0 = time.perf_counter()
    sys.path.insert(0, str(KUECHE))
    import kueche
    from ocp_tessellate.ocp_utils.topology import get_edges, get_faces
    from ocp_tessellate.tessellator import compute_quality, tessellate
    t_import = time.perf_counter() - t0

    t0 = time.perf_counter()
    k = kueche.kueche(kueche.P, True, "winkel", innen=args.innen)
    leaves = list(k.leaves)
    t_build = time.perf_counter() - t0

    parts, blobs = [], []
    offset = 0
    face_order_ok = edge_order_ok = tri_face_ok = 0
    problems = []
    per_part_ms = []

    def put(arr):
        nonlocal offset
        b = np.ascontiguousarray(arr).tobytes()
        blobs.append(b)
        start = offset
        offset += len(b)
        return start

    t_tess_total = time.perf_counter()
    for i, leaf in enumerate(leaves):
        name = leaf.label or f"Teil {i}"
        bb = leaf.bounding_box()
        quality = compute_quality(SimpleNamespace(xsize=bb.size.X, ysize=bb.size.Y, zsize=bb.size.Z),
                                  args.deviation)
        t1 = time.perf_counter()
        tess = tessellate(leaf.wrapped, f"{i}:{name}", deviation=args.deviation, quality=quality,
                          angular_tolerance=args.angular, compute_faces=True, compute_edges=True)
        per_part_ms.append((time.perf_counter() - t1) * 1000)

        verts = np.asarray(tess["vertices"], dtype=np.float32).reshape(-1, 3)
        normals = np.asarray(tess["normals"], dtype=np.float32).reshape(-1, 3)
        tris = np.asarray(tess["triangles"], dtype=np.uint32).reshape(-1, 3)
        tpf = np.asarray(tess["triangles_per_face"], dtype=np.int64)
        segs = np.asarray(tess["edges"], dtype=np.float32).reshape(-1, 2, 3)
        spe = np.asarray(tess["segments_per_edge"], dtype=np.int64)

        # Flächen- und Kantenreihenfolge: ocp-tessellate gegen build123d
        occ_faces = list(get_faces(leaf.wrapped))
        b3d_faces = leaf.faces()
        same_faces = len(occ_faces) == len(b3d_faces) and all(
            a.IsSame(b.wrapped) for a, b in zip(occ_faces, b3d_faces))
        face_order_ok += same_faces
        occ_edges = list(get_edges(leaf.wrapped))
        b3d_edges = leaf.edges()
        same_edges = len(occ_edges) == len(b3d_edges) and all(
            a.IsSame(b.wrapped) for a, b in zip(occ_edges, b3d_edges))
        edge_order_ok += same_edges
        # Jede Fläche muss Dreiecke haben, sonst verrutscht die Zuordnung
        tri_ok = len(tpf) == len(occ_faces) and int(tpf.sum()) == len(tris)
        tri_face_ok += tri_ok
        if not (same_faces and same_edges and tri_ok):
            problems.append(dict(name=name, faces=len(occ_faces), faces_b3d=len(b3d_faces),
                                 tpf=len(tpf), edges=len(occ_edges), edges_b3d=len(b3d_edges),
                                 same_faces=same_faces, same_edges=same_edges, tri_ok=tri_ok))

        tri_face = np.repeat(np.arange(len(tpf), dtype=np.int32), tpf)
        # Kanten: Segmentpaare zu einem Polygonzug je Kante
        pts, offs = [], [0]
        s = 0
        for n in spe:
            n = int(n)
            if n == 0:
                offs.append(offs[-1])
                continue
            e = segs[s:s + n]
            poly = np.vstack([e[:, 0], e[-1:, 1]])
            pts.append(poly)
            offs.append(offs[-1] + len(poly))
            s += n
        epts = np.vstack(pts).astype(np.float32) if pts else np.zeros((0, 3), np.float32)

        col = tuple(leaf.color) if leaf.color is not None else (0.7, 0.7, 0.7, 1.0)
        part = dict(name=name, color=[round(c, 4) for c in col],
                    n_vert=len(verts), n_tri=len(tris), n_face=len(tpf), n_edge=len(spe), n_epts=len(epts))
        part["off_pos"] = put(verts)
        part["off_nrm"] = put(normals)
        part["off_tri"] = put(tris)
        part["off_tface"] = put(tri_face)
        part["off_epts"] = put(epts)
        part["off_eoff"] = put(np.asarray(offs, dtype=np.uint32))
        parts.append(part)
    t_tess_total = time.perf_counter() - t_tess_total

    stats = dict(
        parts=len(parts),
        vertices=int(sum(p["n_vert"] for p in parts)),
        triangles=int(sum(p["n_tri"] for p in parts)),
        faces=int(sum(p["n_face"] for p in parts)),
        edges=int(sum(p["n_edge"] for p in parts)),
        import_s=round(t_import, 2),
        build_s=round(t_build, 2),
        tessellate_s=round(t_tess_total, 2),
        part_ms_max=round(max(per_part_ms), 1),
        part_ms_median=round(float(np.median(per_part_ms)), 1),
        face_order_ok=f"{face_order_ok}/{len(parts)}",
        edge_order_ok=f"{edge_order_ok}/{len(parts)}",
        triangles_per_face_ok=f"{tri_face_ok}/{len(parts)}",
        deviation=args.deviation,
        angular=args.angular,
        innen=args.innen,
    )

    # Zweiter Durchlauf: Zwischenspeicher von ocp-tessellate
    t2 = time.perf_counter()
    for i, leaf in enumerate(leaves):
        bb = leaf.bounding_box()
        quality = compute_quality(SimpleNamespace(xsize=bb.size.X, ysize=bb.size.Y, zsize=bb.size.Z),
                                  args.deviation)
        tessellate(leaf.wrapped, f"{i}:{leaf.label}", deviation=args.deviation, quality=quality,
                   angular_tolerance=args.angular)
    stats["tessellate_cached_s"] = round(time.perf_counter() - t2, 3)

    head = json.dumps(dict(parts=parts, stats=stats), ensure_ascii=False).encode()
    pad = (-(12 + len(head))) % 4
    with open(args.out, "wb") as f:
        f.write(b"KCAD" + struct.pack("<II", 1, len(head)) + head + b"\0" * pad)
        for b in blobs:
            f.write(b)
    stats["file_mb"] = round(Path(args.out).stat().st_size / 1e6, 1)
    print(json.dumps(stats, indent=1, ensure_ascii=False))
    if problems:
        print(f"Abweichungen ({len(problems)}):")
        for p in problems[:15]:
            print(" ", p)


if __name__ == "__main__":
    main()
