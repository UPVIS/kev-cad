"""Referenzen (refs.py) und exaktes Messen (measure.py) ohne Rechenprozess: Teile kommen direkt in die Szene."""

import math

import pytest
from build123d import Box, Cylinder, Pos, Rot

from kevcad_kernel.measure import fmt, measure
from kevcad_kernel.protocol import pack_part
from kevcad_kernel.refs import RefError, Scene, parse_ref, resolve
from kevcad_kernel.tessellate import serialize_shape, tessellate_shape


def add(scene: Scene, name: str, shape, run: int = 1, density: float | None = None):
    brep = serialize_shape(shape.wrapped)
    t = tessellate_shape(shape, brep=brep)
    props = dict(t.props)
    if density:
        props["mass"] = round(props["volume"] * density * 1e-6, 6)
    header, payload = pack_part(run=run, name=name, geometry=t.geometry, color=(0.7, 0.7, 0.7, 1), bbox=t.bbox,
                                props=props, material="aluminium" if density else None)
    header.pop("seq")
    return scene.upsert(name=name, run=run, key=t.key, header=header, payload=payload, brep=brep, density=density)


def m(scene, *refs, run=None, latest=1):
    return measure([resolve(scene, r, run=run, latest_run=latest) for r in refs])


@pytest.fixture()
def scene():
    s = Scene()
    add(s, "A", Box(10, 10, 10))  # x -5 … 5
    add(s, "B", Pos(30, 0, 0) * Box(10, 10, 10))  # x 25 … 35, Lücke 20 mm
    plate = Box(100, 60, 5) - Pos(-20, 0, 0) * Cylinder(3.3, 10) - Pos(20, 0, 0) * Cylinder(3.3, 10)
    add(s, "Halter/Platte", plate, density=2700)
    add(s, "Halter/Bolzen", Pos(0, 50, 0) * Cylinder(5, 20), density=7850)
    add(s, "Schraeg", Pos(0, -80, 0) * Rot(0, 0, 30) * Box(10, 10, 10))
    return s


def test_fmt_german():
    assert fmt(12.5) == "12,500"
    assert fmt(48000) == "48.000,000"
    assert fmt(-0.0001) == "0,000"
    assert fmt(-3.14159) == "-3,142"


def test_distance_between_boxes(scene):
    r = m(scene, "A", "B")
    assert r["kind"] == "distance"
    assert abs(r["values"]["distance"] - 20.0) < 1e-6
    assert abs(r["values"]["dx"] - 20.0) < 1e-6 and r["values"]["dy"] == 0 and r["values"]["dz"] == 0
    assert r["text"] == "Abstand 20,000 mm (dx 20,000)"
    p1, p2 = r["points"]
    assert abs(p1[0] - 5.0) < 1e-6 and abs(p2[0] - 25.0) < 1e-6


def test_parallel_faces_distance(scene):
    # A#f1 ist die Fläche x = +5, B#f0 die Fläche x = 25 (Reihenfolge wie Box.faces())
    r = m(scene, "A#f1", "B#f0")
    assert r["values"]["parallel"] is True
    assert abs(r["values"]["plane_distance"] - 20.0) < 1e-6
    assert r["text"].startswith("Abstand 20,000 mm (parallele Ebenen")


def test_angle_between_perpendicular_faces(scene):
    r = m(scene, "A#f0", "A#f4")  # Normale -x und -z
    assert r["kind"] == "angle"
    assert abs(r["values"]["angle"] - 90.0) < 1e-2
    assert r["text"].startswith("Winkel 90,000°")


def test_angle_rotated_box(scene):
    r = m(scene, "A#f1", "Schraeg#f1")
    assert abs(r["values"]["angle"] - 30.0) < 1e-6
    assert r["kind"] == "angle"


def test_cylinder_radius(scene):
    rec = scene.get("Halter/Bolzen")
    idx = next(i for i, f in enumerate(rec.header["faces"]) if f["t"] == "cylinder")
    r = m(scene, f"Halter/Bolzen#f{idx}")
    assert r["kind"] == "face"
    assert abs(r["values"]["radius"] - 5.0) < 1e-9 and abs(r["values"]["diameter"] - 10.0) < 1e-9
    assert r["values"]["axis"] == [0.0, 0.0, 1.0]
    assert r["text"].startswith("Zylinderfläche: r 5,000 mm (Ø 10,000)")


def test_center_distance_between_holes(scene):
    rec = scene.get("Halter/Platte")
    holes = [i for i, f in enumerate(rec.header["faces"]) if f["t"] == "cylinder"]
    assert len(holes) == 2
    r = m(scene, f"Halter/Platte#f{holes[0]}", f"Halter/Platte#f{holes[1]}")
    assert abs(r["values"]["center_distance"] - 40.0) < 1e-6
    assert abs(r["values"]["distance"] - (40.0 - 6.6)) < 1e-6
    assert r["text"].startswith("Mittenabstand 40,000 mm")


def test_edge_and_vertex(scene):
    r = m(scene, "A#e0")
    assert r["kind"] == "edge" and abs(r["values"]["length"] - 10.0) < 1e-9
    circ = scene.get("Halter/Bolzen")
    idx = next(i for i, e in enumerate(circ.header["edges"]) if e["t"] == "circle")
    r = m(scene, f"Halter/Bolzen#e{idx}")
    assert abs(r["values"]["radius"] - 5.0) < 1e-9 and abs(r["values"]["length"] - 10 * math.pi) < 1e-6
    r = m(scene, "A#v0")
    assert r["kind"] == "vertex" and all(abs(abs(c) - 5.0) < 1e-9 for c in r["values"]["point"])


def test_part_and_group(scene):
    r = m(scene, "Halter/Platte")
    assert r["kind"] == "part"
    assert r["values"]["bbox"]["size"] == [100.0, 60.0, 5.0]
    assert abs(r["values"]["mass"] - r["values"]["volume"] * 2700e-6) < 1e-6
    g = m(scene, "Halter")
    assert g["values"]["parts"] == 2
    mp, mb = scene.get("Halter/Platte").props["mass"], scene.get("Halter/Bolzen").props["mass"]
    assert abs(g["values"]["mass"] - (mp + mb)) < 1e-5
    # massengewichteter Schwerpunkt liegt näher am schweren Bolzen (y = 50) als der volumengewichtete
    assert g["values"]["center_of_mass"][1] > g["values"]["center"][1]


def test_refs_errors(scene):
    with pytest.raises(RefError, match="Unbekanntes Teil 'C'"):
        resolve(scene, "C")
    with pytest.raises(RefError, match="hat 6 Flächen"):
        resolve(scene, "A#f6")
    with pytest.raises(RefError, match="nicht lesbar"):
        resolve(scene, "A#x3")
    with pytest.raises(RefError, match="Lauf 5 ist unbekannt"):
        resolve(scene, "A#f0", run=5, latest_run=1)
    with pytest.raises(RefError, match="Gruppe"):
        resolve(scene, "Halter#f0")
    assert parse_ref("Halter/Lasche#e12").index == 12


def test_refs_stale_after_change(scene):
    add(scene, "A", Box(12, 10, 10), run=2)  # geändert in Lauf 2
    add(scene, "B", Pos(30, 0, 0) * Box(10, 10, 10), run=2)  # unverändert
    with pytest.raises(RefError, match="veraltet"):
        resolve(scene, "A#f0", run=1, latest_run=2)
    assert resolve(scene, "B#f0", run=1, latest_run=2).kind == "face"  # gleiche Form gilt weiter
    assert resolve(scene, "A#f0", run=2, latest_run=2).kind == "face"
