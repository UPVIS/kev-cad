"""Rendering „Foto“ in Blender Cycles (Phase 7). Läuft in Blenders eigenem Python, nicht im Kernel.

Aufruf (der Kernel startet es, render/blender.py):
    Blender -b --factory-startup -noaudio --python blender_skript.py -- /pfad/szene.json

``szene.json`` (geschrieben von render/blender.py):
    breite, hoehe, samples, rauschgrenze, ausgabe (PNG), netze (npz mit p<i>, n<i>, t<i>),
    szene {name, licht (studio | umgebung), umgebung (Pfad .hdr oder null), staerke, drehung, hintergrund (Hex,
           „umgebung“ oder „transparent“), boden (bool)},
    kamera {projection, position, target, up, fov_deg, ortho_height_mm} in mm (Z oben),
    grenzen {min, max} der sichtbaren Teile in mm, teile [{name, netz, matrix (16, spaltenweise) oder null, material}],
    materialien {schluessel: PBR wie render/materialien.py}.

Einheiten: Netze in mm, Objekte mit Maßstab 0,001 (Blender rechnet in Metern). Gibt „KEVCAD …“-Zeilen für den Kernel
aus; den Fortschritt liest der Kernel aus Cycles' „Sample n/m“.
"""

from __future__ import annotations

import json
import math
import sys
import time

import bpy
import mathutils
import numpy as np

T0 = time.time()


def melden(text: str) -> None:
    print(f"KEVCAD {text}", flush=True)


def srgb_linear(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_linear(h: str) -> tuple[float, float, float, float]:
    h = h.lstrip("#")
    return (*(srgb_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)), 1.0)


def farbe_linear(rgb) -> tuple[float, float, float, float]:
    return (*(srgb_linear(c) for c in rgb[:3]), 1.0)


args = sys.argv[sys.argv.index("--") + 1:]
S = json.load(open(args[0], encoding="utf-8"))
NETZE = np.load(S["netze"])
scene = bpy.context.scene

# -- leere Szene ---------------------------------------------------------------------------------------------------------
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
    for block in list(coll):
        coll.remove(block)

# -- Materialien ---------------------------------------------------------------------------------------------------------


def _knoten(nt, art, x=0, y=0, **werte):
    n = nt.nodes.new(art)
    n.location = (x, y)
    for k, v in werte.items():
        setattr(n, k, v)
    return n


def material(key: str, pbr: dict, achse: int = 0) -> bpy.types.Material:
    """Material je Darstellung; ``achse`` (0 = X, 1 = Y, 2 = Z) ist die Faser- bzw. Schliffrichtung des Teils."""
    m = bpy.data.materials.new(key[:56] + "|" + "xyz"[achse])
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    basis = farbe_linear(pbr.get("basisfarbe", [0.7, 0.7, 0.7]))
    rau = float(pbr.get("rauheit", 0.5))
    b.inputs["Base Color"].default_value = basis
    b.inputs["Metallic"].default_value = float(pbr.get("metallisch", 0.0))
    b.inputs["Roughness"].default_value = rau
    if pbr.get("klarlack"):
        b.inputs["Coat Weight"].default_value = float(pbr["klarlack"])
        b.inputs["Coat Roughness"].default_value = float(pbr.get("klarlack_rauheit", 0.1))
    if pbr.get("anisotropie"):
        b.inputs["Anisotropic"].default_value = float(pbr["anisotropie"])
    if pbr.get("durchsichtig"):
        b.inputs["Transmission Weight"].default_value = float(pbr["durchsichtig"])
        b.inputs["IOR"].default_value = 1.49
    o = pbr.get("oberflaeche", "glatt")
    koord = _knoten(nt, "ShaderNodeTexCoord", -1200, 0)
    links = nt.links

    def rauheit_variation(fac_out, staerke):
        mr = _knoten(nt, "ShaderNodeMapRange", -300, -200)
        mr.inputs["To Min"].default_value = max(0.02, rau - staerke)
        mr.inputs["To Max"].default_value = min(1.0, rau + staerke)
        links.new(fac_out, mr.inputs["Value"])
        links.new(mr.outputs["Result"], b.inputs["Roughness"])

    def beule(hoehe_out, staerke, abstand=1.0):
        bump = _knoten(nt, "ShaderNodeBump", -300, -400)
        bump.inputs["Strength"].default_value = staerke
        bump.inputs["Distance"].default_value = abstand
        links.new(hoehe_out, bump.inputs["Height"])
        links.new(bump.outputs["Normal"], b.inputs["Normal"])
        if pbr.get("klarlack") and "Coat Normal" in b.inputs:
            pass  # Klarlack bleibt glatt (eloxiert, Film)

    def farb_variation(fac_out, tief, hoch):
        ramp = _knoten(nt, "ShaderNodeValToRGB", -300, 200)
        e0, e1 = ramp.color_ramp.elements[0], ramp.color_ramp.elements[1]
        e0.color = tuple(c * tief for c in basis[:3]) + (1.0,)
        e1.color = tuple(min(1.0, c * hoch) for c in basis[:3]) + (1.0,)
        links.new(fac_out, ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], b.inputs["Base Color"])

    if o == "gebuerstet":
        # Schliff entlang X: Rauschen in X stark gestreckt
        mp = _knoten(nt, "ShaderNodeMapping", -1000, 0)
        streckung = [3.0, 3.0, 3.0]
        streckung[achse] = 0.02
        mp.inputs["Scale"].default_value = streckung
        links.new(koord.outputs["Object"], mp.inputs["Vector"])
        nz = _knoten(nt, "ShaderNodeTexNoise", -700, 0)
        nz.inputs["Scale"].default_value = 6.0
        nz.inputs["Detail"].default_value = 8.0
        links.new(mp.outputs["Vector"], nz.inputs["Vector"])
        rauheit_variation(nz.outputs["Fac"], 0.08)
        beule(nz.outputs["Fac"], 0.04, 0.2)
    elif o in ("eloxiert", "pulver"):
        nz = _knoten(nt, "ShaderNodeTexNoise", -700, 0)
        nz.inputs["Scale"].default_value = 3.0 if o == "pulver" else 0.8
        nz.inputs["Detail"].default_value = 6.0
        links.new(koord.outputs["Object"], nz.inputs["Vector"])
        rauheit_variation(nz.outputs["Fac"], 0.04)
        beule(nz.outputs["Fac"], 0.03 if o == "pulver" else 0.01, 0.2)
    elif o == "verzinkt":
        vo = _knoten(nt, "ShaderNodeTexVoronoi", -700, 0)
        vo.inputs["Scale"].default_value = 0.12  # Zinkblumen um 8 mm
        links.new(koord.outputs["Object"], vo.inputs["Vector"])
        sep = _knoten(nt, "ShaderNodeSeparateColor", -500, 0)
        links.new(vo.outputs["Color"], sep.inputs["Color"])
        rauheit_variation(sep.outputs["Red"], 0.07)
        farb_variation(sep.outputs["Green"], 0.94, 1.03)
    elif o in ("walzhaut", "guss", "beton"):
        nz = _knoten(nt, "ShaderNodeTexNoise", -700, 0)
        nz.inputs["Scale"].default_value = {"walzhaut": 0.05, "guss": 0.6, "beton": 0.3}[o]
        nz.inputs["Detail"].default_value = 10.0
        links.new(koord.outputs["Object"], nz.inputs["Vector"])
        rauheit_variation(nz.outputs["Fac"], 0.12)
        farb_variation(nz.outputs["Fac"], 0.8, 1.08)
        if o != "walzhaut":
            fein = _knoten(nt, "ShaderNodeTexNoise", -700, -300)
            fein.inputs["Scale"].default_value = 4.0
            links.new(koord.outputs["Object"], fein.inputs["Vector"])
            beule(fein.outputs["Fac"], 0.25, 0.3)
    elif o == "schichten":
        # Schichtlinien quer zu Z: sin(2π z / h), dazu leichtes Rauschen
        h = float(pbr.get("schichthoehe", 0.2))
        sep = _knoten(nt, "ShaderNodeSeparateXYZ", -1000, 0)
        links.new(koord.outputs["Object"], sep.inputs["Vector"])
        mul = _knoten(nt, "ShaderNodeMath", -800, 0, operation="MULTIPLY")
        mul.inputs[1].default_value = 2 * math.pi / h
        links.new(sep.outputs["Z"], mul.inputs[0])
        sin = _knoten(nt, "ShaderNodeMath", -600, 0, operation="SINE")
        links.new(mul.outputs[0], sin.inputs[0])
        beule(sin.outputs[0], 0.18, 0.05)
    elif o == "holz":
        # Maserung: Jahresringe als Zylinder um die Faserrichtung (weit außerhalb des Teils, also flach
        # angeschnitten), mit verzerrendem Rauschen
        mp = _knoten(nt, "ShaderNodeMapping", -1000, 0)
        skala = [1.0, 1.0, 1.0]
        skala[achse] = 0.0
        mp.inputs["Scale"].default_value = skala
        versatz = [260.0, 260.0, 260.0]
        versatz[achse] = 0.0
        mp.inputs["Location"].default_value = versatz
        links.new(koord.outputs["Object"], mp.inputs["Vector"])
        wv = _knoten(nt, "ShaderNodeTexWave", -700, 0)
        wv.wave_type = "RINGS"
        wv.inputs["Scale"].default_value = 0.07
        wv.inputs["Distortion"].default_value = 5.0
        wv.inputs["Detail"].default_value = 2.0
        wv.inputs["Detail Scale"].default_value = 1.0
        links.new(mp.outputs["Vector"], wv.inputs["Vector"])
        farb_variation(wv.outputs["Fac"], 0.78, 1.06)
        rauheit_variation(wv.outputs["Fac"], 0.06)
    elif o in ("gummi", "schaum"):
        nz = _knoten(nt, "ShaderNodeTexNoise", -700, 0)
        nz.inputs["Scale"].default_value = 2.5 if o == "gummi" else 1.2
        nz.inputs["Detail"].default_value = 8.0
        links.new(koord.outputs["Object"], nz.inputs["Vector"])
        beule(nz.outputs["Fac"], 0.12 if o == "gummi" else 0.4, 0.3)
    return m


MATS: dict[tuple[str, int], bpy.types.Material] = {}
RICHTUNG = ("holz", "gebuerstet")


def material_fuer(key: str, achse: int) -> bpy.types.Material:
    pbr = S["materialien"][key]
    a = achse if pbr.get("oberflaeche") in RICHTUNG else 0
    if (key, a) not in MATS:
        MATS[(key, a)] = material(key, pbr, a)
    return MATS[(key, a)]


# -- Teile -----------------------------------------------------------------------------------------------------------------
coll = bpy.data.collections.new("Modell")
scene.collection.children.link(coll)
MM = mathutils.Matrix.Scale(0.001, 4)
dreiecke = 0
for t in S["teile"]:
    i = t["netz"]
    P = NETZE[f"p{i}"].astype(np.float32).reshape(-1, 3)
    N = NETZE[f"n{i}"].astype(np.float32).reshape(-1, 3)
    T = NETZE[f"t{i}"].astype(np.int32).reshape(-1, 3)
    if len(T) == 0:
        continue
    me = bpy.data.meshes.new(t["name"][:60])
    me.vertices.add(len(P))
    me.vertices.foreach_set("co", P.ravel())
    me.loops.add(len(T) * 3)
    me.loops.foreach_set("vertex_index", T.ravel())
    me.polygons.add(len(T))
    me.polygons.foreach_set("loop_start", np.arange(0, len(T) * 3, 3, dtype=np.int32))
    me.update(calc_edges=True)
    me.polygons.foreach_set("use_smooth", np.ones(len(T), dtype=bool))
    if len(N) == len(P):
        nn = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        me.normals_split_custom_set_from_vertices([tuple(v) for v in nn])
    ausdehnung = P.max(axis=0) - P.min(axis=0)
    me.materials.append(material_fuer(t["material"], int(np.argmax(ausdehnung))))
    ob = bpy.data.objects.new(t["name"][:60], me)
    m = t.get("matrix")
    welt = mathutils.Matrix([m[0:4], m[4:8], m[8:12], m[12:16]]).transposed() if m else mathutils.Matrix.Identity(4)
    ob.matrix_world = MM @ welt
    coll.objects.link(ob)
    dreiecke += len(T)
melden(f"teile {len(S['teile'])} dreiecke {dreiecke} materialien {len(MATS)} in {time.time() - T0:.1f} s")

# -- Grenzen, Kamera -------------------------------------------------------------------------------------------------------
lo = mathutils.Vector(S["grenzen"]["min"]) * 0.001
hi = mathutils.Vector(S["grenzen"]["max"]) * 0.001
mitte = (lo + hi) / 2
diag = max((hi - lo).length, 0.01)

K = S["kamera"]
cam_data = bpy.data.cameras.new("Kamera")
cam = bpy.data.objects.new("Kamera", cam_data)
scene.collection.objects.link(cam)
pos = mathutils.Vector(K["position"]) * 0.001
ziel = mathutils.Vector(K["target"]) * 0.001
oben = mathutils.Vector(K.get("up") or (0, 0, 1)).normalized()
vor = (ziel - pos).normalized()
rechts = vor.cross(oben)
if rechts.length < 1e-6:
    rechts = vor.cross(mathutils.Vector((0, 1, 0)))
rechts.normalize()
oben2 = rechts.cross(vor).normalized()
rot = mathutils.Matrix((rechts, oben2, -vor)).transposed()
cam.matrix_world = mathutils.Matrix.Translation(pos) @ rot.to_4x4()
cam_data.sensor_fit = "VERTICAL"
if K.get("projection") == "orthographic" and K.get("ortho_height_mm"):
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = float(K["ortho_height_mm"]) * 0.001
else:
    cam_data.type = "PERSP"
    cam_data.angle_y = math.radians(float(K.get("fov_deg") or 30.0))
abstand = (mitte - pos).length
cam_data.clip_start = max(0.0005, (abstand - diag * 2) * 0.5 if abstand > diag * 2 else 0.0005)
cam_data.clip_end = abstand + diag * 60 + 10
scene.camera = cam

# -- Licht und Welt --------------------------------------------------------------------------------------------------------
SZ = S["szene"]
welt = bpy.data.worlds.new("Welt")
scene.world = welt
welt.use_nodes = True
wn = welt.node_tree
wbg = wn.nodes["Background"]
hintergrund = SZ.get("hintergrund")


def flaechenlicht(name, richtung, abstand_f, groesse_f, leistung, farbe=(1, 1, 1)):
    """Softbox: Flächenlicht aus ``richtung`` (vom Modell weg) auf die Mitte gerichtet; Leistung skaliert mit dem
    Abstand², damit die Helligkeit nicht von der Modellgröße abhängt."""
    d = mathutils.Vector(richtung).normalized()
    ort = mitte + d * diag * abstand_f
    li = bpy.data.lights.new(name, "AREA")
    li.shape = "RECTANGLE"
    li.size = diag * groesse_f
    li.size_y = diag * groesse_f * 0.7
    li.energy = leistung * (diag * abstand_f) ** 2
    li.color = farbe
    ob = bpy.data.objects.new(name, li)
    ob.location = ort
    ob.rotation_euler = (mitte - ort).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(ob)
    return ob


if SZ.get("licht") == "umgebung" and SZ.get("umgebung"):
    env = wn.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(SZ["umgebung"])
    mp = wn.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(float(SZ.get("drehung") or 0)))
    tc = wn.nodes.new("ShaderNodeTexCoord")
    # Kamerastrahlen sehen die Umgebung unscharf (Bokeh statt grober 1K-Pixel): Richtung leicht verrauschen
    rausch = wn.nodes.new("ShaderNodeTexWhiteNoise")
    rausch.noise_dimensions = "4D"
    lp_w = wn.nodes.new("ShaderNodeLightPath")
    zufall = wn.nodes.new("ShaderNodeVectorMath")
    zufall.operation = "SUBTRACT"
    zufall.inputs[1].default_value = (0.5, 0.5, 0.5)
    wn.links.new(tc.outputs["Generated"], rausch.inputs["Vector"])
    wn.links.new(rausch.outputs["Color"], zufall.inputs[0])
    staerke_unschaerfe = wn.nodes.new("ShaderNodeMath")
    staerke_unschaerfe.operation = "MULTIPLY"
    staerke_unschaerfe.inputs[1].default_value = float(SZ.get("unschaerfe", 0.04))
    wn.links.new(lp_w.outputs["Is Camera Ray"], staerke_unschaerfe.inputs[0])
    skaliert = wn.nodes.new("ShaderNodeVectorMath")
    skaliert.operation = "SCALE"
    wn.links.new(zufall.outputs["Vector"], skaliert.inputs[0])
    wn.links.new(staerke_unschaerfe.outputs[0], skaliert.inputs["Scale"])
    richtung = wn.nodes.new("ShaderNodeVectorMath")
    richtung.operation = "ADD"
    wn.links.new(tc.outputs["Generated"], richtung.inputs[0])
    wn.links.new(skaliert.outputs["Vector"], richtung.inputs[1])
    wn.links.new(richtung.outputs["Vector"], mp.inputs["Vector"])
    wn.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    wn.links.new(env.outputs["Color"], wbg.inputs["Color"])
    wbg.inputs["Strength"].default_value = float(SZ.get("staerke") or 1.0)
else:
    # Studio: neutrales Grau, oben heller (Decke), dazu Softboxen
    wbg.inputs["Color"].default_value = (0.55, 0.56, 0.58, 1)
    wbg.inputs["Strength"].default_value = 0.22 * float(SZ.get("staerke") or 1.0)
    flaechenlicht("Hauptlicht", (-0.9, -1.1, 1.25), 2.2, 1.4, 11.0, (1.0, 0.985, 0.96))
    flaechenlicht("Aufheller", (1.3, -0.6, 0.5), 2.4, 1.6, 3.5, (0.96, 0.98, 1.0))
    flaechenlicht("Kante", (0.4, 1.3, 1.1), 2.2, 1.0, 7.0)
    flaechenlicht("Decke", (0.0, 0.0, 1.0), 2.0, 2.0, 2.5)

# Kamerastrahlen sehen die Hintergrundfarbe (Studio), sonst die Umgebung
if hintergrund and hintergrund.startswith("#"):
    lp = wn.nodes.new("ShaderNodeLightPath")
    farbe = wn.nodes.new("ShaderNodeBackground")
    farbe.inputs["Color"].default_value = hex_linear(hintergrund)
    farbe.inputs["Strength"].default_value = 1.0
    mix = wn.nodes.new("ShaderNodeMixShader")
    wn.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    wn.links.new(wbg.outputs["Background"], mix.inputs[1])
    wn.links.new(farbe.outputs["Background"], mix.inputs[2])
    wn.links.new(mix.outputs["Shader"], wn.nodes["World Output"].inputs["Surface"])

# Boden als Schattenfänger, knapp unter dem tiefsten Punkt
if SZ.get("boden", True):
    bpy.ops.mesh.primitive_plane_add(size=diag * 80, location=(mitte.x, mitte.y, lo.z - 0.00005))
    boden = bpy.context.active_object
    boden.name = "Boden"
    boden.is_shadow_catcher = True
    bm = bpy.data.materials.new("Boden")
    bm.use_nodes = True
    bm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    boden.data.materials.append(bm)

# -- Rendern ---------------------------------------------------------------------------------------------------------------
scene.render.engine = "CYCLES"
geraet = "CPU"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    gpus = [d for d in prefs.devices if d.type == "METAL"]
    for d in prefs.devices:
        d.use = d.type == "METAL"
    if gpus:
        scene.cycles.device = "GPU"
        geraet = "GPU " + gpus[0].name
except Exception as exc:  # noqa: BLE001
    melden(f"hinweis GPU nicht verfügbar: {exc}")
scene.cycles.samples = int(S.get("samples") or 128)
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = float(S.get("rauschgrenze") or 0.02)
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8
scene.cycles.transparent_max_bounces = 8
scene.render.resolution_x = int(S["breite"])
scene.render.resolution_y = int(S["hoehe"])
scene.render.resolution_percentage = 100
scene.render.film_transparent = hintergrund == "transparent"
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.exposure = float(S.get("belichtung") or 0.0)
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA" if hintergrund == "transparent" else "RGB"
scene.render.image_settings.color_depth = "8"
scene.render.filepath = S["ausgabe"]
melden(f"rendert {S['breite']}x{S['hoehe']} samples {scene.cycles.samples} auf {geraet}")
T1 = time.time()
bpy.ops.render.render(write_still=True)
melden(f"fertig {S['ausgabe']} rendern {time.time() - T1:.1f} s gesamt {time.time() - T0:.1f} s")
