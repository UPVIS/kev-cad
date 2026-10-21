"""Kontrollbilder eines ausgerichteten Referenznetzes (mm, Z oben) aus drei Richtungen plus Schrägansicht.

Aufruf (Blender im Hintergrund, kein Fenster):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python kontrollbilder.py -- \
        <netz_mm.obj> <ausgabeordner> [präfix]

Schreibt <präfix>_vorne.png, <präfix>_seite.png, <präfix>_oben.png, <präfix>_schraeg.png.
Workbench-Renderer mit Textur, orthografische Kamera, 1 mm-Raster als Boden (10-cm-Linien).
"""
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(argv) < 2:
    print("Aufruf: ... -- <netz.obj> <ausgabeordner> [präfix]")
    sys.exit(2)
mesh_path, out_dir = argv[0], argv[1]
prefix = argv[2] if len(argv) > 2 else "kontrolle"
os.makedirs(out_dir, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=mesh_path, forward_axis="Y", up_axis="Z")
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not objs:
    print("Kein Netz geladen")
    sys.exit(1)

lo = Vector((1e18, 1e18, 1e18))
hi = Vector((-1e18, -1e18, -1e18))
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w))
        hi = Vector(map(max, hi, w))
center = (lo + hi) / 2
size = hi - lo
diag = size.length

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.display.shading.show_cavity = True
scene.display.shading.show_object_outline = True
scene.render.resolution_x = 1200
scene.render.resolution_y = 900
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("Welt")
scene.world.color = (0.80, 0.82, 0.86)

# Bodenraster: Linien alle 100 mm auf z = 0
grid = bpy.data.meshes.new("Raster")
verts, edges = [], []
ext = max(size.x, size.y) * 0.8 + 100
step = 100.0
n = int(ext // step) + 1
for i in range(-n, n + 1):
    a = len(verts)
    verts += [(center.x + i * step, center.y - n * step, 0), (center.x + i * step, center.y + n * step, 0)]
    edges.append((a, a + 1))
    a = len(verts)
    verts += [(center.x - n * step, center.y + i * step, 0), (center.x + n * step, center.y + i * step, 0)]
    edges.append((a, a + 1))
grid.from_pydata(verts, edges, [])
gobj = bpy.data.objects.new("Raster", grid)
scene.collection.objects.link(gobj)
# Linien im Workbench sichtbar machen: als dünne Kurve (nur das Raster umwandeln, nicht das Netz)
for o in bpy.context.scene.objects:
    o.select_set(False)
gobj.select_set(True)
bpy.context.view_layer.objects.active = gobj
bpy.ops.object.convert(target="CURVE")
gobj = bpy.context.view_layer.objects.active
gobj.data.bevel_depth = max(diag / 900.0, 0.4)

cam_data = bpy.data.cameras.new("Kamera")
cam_data.type = "ORTHO"
cam = bpy.data.objects.new("Kamera", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam


def shoot(name, direction, up, scale):
    d = Vector(direction).normalized()
    cam.location = center + d * diag * 3
    look = (center - cam.location).normalized()
    rot = look.to_track_quat("-Z", "Y")
    # Kamera so drehen, dass `up` oben im Bild liegt
    cam.rotation_euler = rot.to_euler()
    right = look.cross(Vector(up)).normalized()
    true_up = right.cross(look).normalized()
    m = cam.matrix_world.to_3x3()
    m.col[0], m.col[1], m.col[2] = right, true_up, -look
    cam.rotation_euler = m.to_euler()
    cam_data.ortho_scale = scale
    cam_data.clip_end = diag * 10
    scene.render.filepath = os.path.join(out_dir, f"{prefix}_{name}.png")
    bpy.ops.render.render(write_still=True)
    print("Bild:", scene.render.filepath)


margin = 1.15
shoot("vorne", (0, -1, 0), (0, 0, 1), max(size.x, size.z * 4 / 3) * margin)
shoot("seite", (1, 0, 0), (0, 0, 1), max(size.y, size.z * 4 / 3) * margin)
shoot("oben", (0, 0, 1), (0, 1, 0), max(size.x, size.y * 4 / 3) * margin)
shoot("schraeg", (1, -1.3, 0.9), (0, 0, 1), diag * 0.95)
print(f"Hülle (mm): {size.x:.1f} x {size.y:.1f} x {size.z:.1f}")
