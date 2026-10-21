"""Tessellierung (tessellate.py): Format, Reihenfolge von Flächen und Kanten, degenerierte Kanten, Zwischenspeicher."""

import time

import numpy as np
from build123d import Box, BuildLine, BuildSketch, CenterArc, Cylinder, Line, Pos, Rectangle, Sphere, fillet
from OCP.BRep import BRep_Tool

from kevcad_kernel.protocol import FrameReader, encode_frame, pack_part, unpack_part
from kevcad_kernel.tessellate import (
    TessCache,
    deserialize_shape,
    edges_of,
    faces_of,
    serialize_shape,
    tessellate_shape,
    vertices_of,
)


def _same_order(shape, tess):
    """Flächen-, Kanten- und Punktreihenfolge der Tessellierung = part.faces()/edges()/vertices()."""
    g = tess.geometry
    faces, edges, verts = shape.faces(), shape.edges(), shape.vertices()
    assert [round(f["a"], 3) for f in g.faces] == [round(f.area, 3) for f in faces]
    assert [round(e["l"], 3) for e in g.edges] == [round(e.length, 3) for e in edges]
    assert all(a.wrapped.IsSame(b.wrapped) for a, b in zip(faces_of(shape), faces))
    assert all(a.wrapped.IsSame(b.wrapped) for a, b in zip(edges_of(shape), edges))
    assert np.allclose(g.vertices, [[v.X, v.Y, v.Z] for v in verts], atol=1e-4)
    assert g.counts["face"] == len(faces)
    assert g.counts["edge"] == len(edges)
    assert g.counts["vtx"] == len(verts)
    # jede Fläche hat Dreiecke, tri_face ist aufsteigend und deckt alle Flächen ab
    assert sorted(set(g.tri_face.tolist())) == list(range(len(faces)))


def test_box_counts_and_metadata():
    box = Box(10, 20, 30)
    t = tessellate_shape(box, cache=None)
    g = t.geometry
    assert g.counts == {"vert": 24, "tri": 12, "face": 6, "edge": 12, "epts": 24, "vtx": 8}
    assert t.bbox == {"min": [-5.0, -10.0, -15.0], "max": [5.0, 10.0, 15.0]}
    assert t.props["volume"] == 6000.0 and t.props["area"] == 2200.0
    assert all(f["t"] == "plane" and "n" in f and "c" in f for f in g.faces)
    assert g.faces[0]["n"] == [-1.0, 0.0, 0.0] and g.faces[5]["n"] == [0.0, 0.0, 1.0]
    assert all(e["t"] == "line" for e in g.edges)
    _same_order(box, t)


def test_cylinder_metadata():
    cyl = Pos(30, 0, 0) * Cylinder(5, 20)
    t = tessellate_shape(cyl, cache=None)
    side = t.geometry.faces[0]
    assert side["t"] == "cylinder" and side["r"] == 5.0 and side["ax"] == [0.0, 0.0, 1.0]
    assert side["c"] == [30.0, 0.0, 0.0]  # Mitte der Achse
    circles = [e for e in t.geometry.edges if e["t"] == "circle"]
    assert len(circles) == 2 and all(e["r"] == 5.0 and abs(e["l"] - 31.415927) < 1e-5 for e in circles)
    _same_order(cyl, t)


def test_degenerated_edges_filtered():
    sphere = Sphere(5)
    raw = [BRep_Tool.Degenerated_s(e.wrapped) for e in sphere.get_shape_list(sphere, "Edge")]
    assert sum(raw) == 2  # Pole
    t = tessellate_shape(sphere, cache=None)
    assert t.geometry.counts["edge"] == len(sphere.edges()) == 1
    assert t.geometry.edges[0]["t"] == "circle"
    _same_order(sphere, t)


def test_filleted_part_order():
    part = fillet(Box(40, 30, 20).edges().group_by()[-1], 4)
    part = part - Pos(5, 5, 0) * Cylinder(4, 30)
    t = tessellate_shape(part, cache=None)
    _same_order(part, t)
    offsets = t.geometry.edge_offsets
    assert offsets[0] == 0 and offsets[-1] == len(t.geometry.edge_points)
    assert all(b - a >= 2 for a, b in zip(offsets[:-1], offsets[1:]))  # jede Kante ein Polygonzug


def test_sketch_and_wire():
    with BuildSketch() as sk:
        Rectangle(10, 5)
    t = tessellate_shape(sk.sketch, cache=None)
    assert t.geometry.counts["face"] == 1 and t.geometry.counts["edge"] == 4
    assert t.props["volume"] == 0.0 and t.props["area"] == 50.0
    with BuildLine() as bl:
        Line((0, 0), (10, 0))
        CenterArc((10, 5), 5, -90, 180)
    t = tessellate_shape(bl.line, cache=None)
    assert t.geometry.counts["tri"] == 0 and t.geometry.counts["edge"] == 2
    assert [e["t"] for e in t.geometry.edges] == ["line", "circle"]


def test_pack_unpack_roundtrip():
    shape = Pos(30, 0, 0) * Cylinder(5, 20)
    t = tessellate_shape(shape, cache=None)
    header, payload = pack_part(run=3, name="Halter/Bolzen", geometry=t.geometry, color=(1, 0, 0, 1), bbox=t.bbox,
                                props=t.props, seq=7)
    (h, p), = FrameReader().feed(encode_frame(header, payload))
    arrays = unpack_part(h, p)
    assert np.array_equal(arrays["triangles"], t.geometry.triangles)
    assert np.array_equal(arrays["edge_offsets"], t.geometry.edge_offsets)
    assert len(h["faces"]) == h["counts"]["face"] and len(h["edges"]) == h["counts"]["edge"]


def test_brep_roundtrip_keeps_order():
    part = fillet(Box(20, 20, 20).edges(), 2) - Cylinder(3, 40)
    copy = deserialize_shape(serialize_shape(part.wrapped))
    assert [round(f.area, 6) for f in faces_of(part)] == [round(f.area, 6) for f in faces_of(copy)]
    assert [round(e.length, 6) for e in edges_of(part)] == [round(e.length, 6) for e in edges_of(copy)]
    assert len(vertices_of(part)) == len(vertices_of(copy))


def test_cache_hit_is_faster_and_identical():
    cache = TessCache()

    def build():
        return fillet(Box(60, 40, 30).edges(), 5) - Pos(10, 0, 0) * Sphere(12)

    t0 = time.perf_counter()
    first = tessellate_shape(build(), cache=cache)
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    second = tessellate_shape(build(), cache=cache)  # neu gebaut, gleiche Geometrie
    t_second = time.perf_counter() - t0
    assert not first.cached and second.cached
    assert second.key == first.key
    assert second.geometry is first.geometry
    assert t_second < t_first
    other = tessellate_shape(Box(1, 2, 3), cache=cache)
    assert not other.cached and other.key != first.key
