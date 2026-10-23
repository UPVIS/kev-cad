"""Das fertige CAD-Netz (GLB) aus einer Fotokamera zeichnen, auf der Grafikkarte (moderngl, OpenGL 3.3).

Dient dem Einpassen der Kameras gegen das echte Modell statt gegen das Ersatzmodell aus konvexen Körpern in
mehrfach.py. Die Kamera ist dieselbe wie dort und in render_blender.py: Lochkamera mit Brennweite f in
Originalpixeln, Hauptpunkt (ppx, ppy) gegenüber der Bildmitte, Blick über yaw, pitch, roll; Bildkoordinaten
stetig (Pixel i deckt [i, i+1]), also wie Blender rendert.

Bewegliche Gruppen (Haube und später Türen, Klappen) bekommen je eine eigene Matrix; Gruppe 0 steht still.

    from netz_gl import Netz, Zeichner
    z = Zeichner(Netz(pfad_glb))
    cov = z.maske(cam, s, {1: haube_matrix(winkel, y, z)})     # Deckung 0..1 je Pixel (8-fach Kantenglättung)
    ids = z.teile(cam, s, {...})                                # Bauteilnummer + 1 je Pixel, 0 = Hintergrund
"""
import math
from pathlib import Path

import moderngl
import numpy as np
import trimesh

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
EXPORTE = WURZEL / "exports"

# Gruppe je Bauteil nach Namensanfang (wie render_blender.py: Haube und Thermometer drehen sich mit)
GRUPPEN = ((1, ("grillhaube", "thermometer")),)

VS = """
#version 330
uniform mat4 kamera;
uniform mat4 bewegung[8];
in vec3 pos;
in float gruppe;
in float teil;
flat out float v_teil;
void main() {
    vec4 p = bewegung[int(gruppe + 0.5)] * vec4(pos, 1.0);
    gl_Position = kamera * p;
    v_teil = teil;
}
"""
FS_MASKE = """
#version 330
out vec4 farbe;
void main() { farbe = vec4(1.0); }
"""
FS_TEIL = """
#version 330
flat in float v_teil;
out vec4 farbe;
void main() { farbe = vec4(v_teil + 1.0, 0.0, 0.0, 1.0); }
"""


def gruppe_fuer(name):
    n = name.lower()
    for nummer, anfaenge in GRUPPEN:
        if n.startswith(anfaenge):
            return nummer
    return 0


class Netz:
    """Dreiecke des GLB in Welt-Millimetern (z oben, wie kueche.py), nach Bauteilen."""

    def __init__(self, pfad=None, dreiecke=None):
        """Aus einem GLB oder aus fertigen Dreiecken {Bauteil: (n, 3, 3) oder (3 n, 3)} (cad_netz.baue)."""
        if dreiecke is None:
            self.pfad = Path(pfad)
            sc = trimesh.load(self.pfad, force="scene")
            teile = {}
            for node in sc.graph.nodes_geometry:
                T, gname = sc.graph[node]
                g = sc.geometry[gname]
                v = trimesh.transform_points(g.vertices, T)
                v = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]]) * 1000.0      # glTF (y oben, m) -> Welt (z oben, mm)
                teile.setdefault(node.rsplit("_", 1)[0], []).append(v[g.faces].reshape(-1, 3))
            dreiecke = {n: np.concatenate(t) for n, t in teile.items()}
        self.namen = sorted(dreiecke)
        self.dreiecke = {n: np.asarray(dreiecke[n], np.float32).reshape(-1, 3) for n in self.namen}

    def puffer(self):
        daten = []
        for i, n in enumerate(self.namen):
            t = self.dreiecke[n]
            spalten = np.column_stack([t, np.full(len(t), gruppe_fuer(n), np.float32), np.full(len(t), i, np.float32)])
            daten.append(spalten)
        return np.concatenate(daten).astype(np.float32)

    def grenzen(self):
        alle = np.concatenate(list(self.dreiecke.values()))
        return alle.min(0), alle.max(0)


def rotation(yaw, pitch, roll):
    fwd = np.array([math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)])
    right = np.cross(fwd, [0, 0, 1.0]); right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    c, s = math.cos(roll), math.sin(roll)
    return np.vstack([c * right + s * down, -s * right + c * down, fwd])


def kamera_matrix(cam, s, breite, hoehe, nah=100.0, fern=30000.0):
    """Welt (mm) -> Clip-Raum für ein Bild von breite x hoehe Pixeln (Originalpixel mal s).
    Zeile 0 des gelesenen Puffers ist die oberste Bildzeile (y_ndc = 2 v / hoehe - 1)."""
    R = rotation(cam["yaw"], cam["pitch"], cam["roll"])
    C = np.array([cam["camx"], cam["camy"], cam["camz"]])
    E = np.eye(4); E[:3, :3] = R; E[:3, 3] = -R @ C
    f = cam["f"] * s
    cx = (cam["w"] / 2 + cam.get("ppx", 0.0)) * s
    cy = (cam["h"] / 2 + cam.get("ppy", 0.0)) * s
    K = np.zeros((4, 4))
    K[0, 0] = 2 * f / breite; K[0, 2] = 2 * cx / breite - 1
    K[1, 1] = 2 * f / hoehe; K[1, 2] = 2 * cy / hoehe - 1
    K[2, 2] = (fern + nah) / (fern - nah); K[2, 3] = -2 * fern * nah / (fern - nah)
    K[3, 2] = 1.0
    return K @ E


def haube_matrix(winkel_grad, achse_y, achse_z):
    """Drehung um die Scharnierachse parallel zu x durch (achse_y, achse_z), wie render_blender.py."""
    w = math.radians(winkel_grad)
    c, s = math.cos(w), math.sin(w)
    T = np.eye(4); T[1, 3], T[2, 3] = achse_y, achse_z
    Ti = np.eye(4); Ti[1, 3], Ti[2, 3] = -achse_y, -achse_z
    R = np.eye(4); R[1, 1], R[1, 2], R[2, 1], R[2, 2] = c, -s, s, c
    return T @ R @ Ti


def drehung_um_achse(punkt, richtung, winkel_grad):
    """Drehung um eine beliebige Achse (Punkt, Richtung) in Grad, rechte Hand."""
    a = np.asarray(richtung, float); a /= np.linalg.norm(a)
    w = math.radians(winkel_grad)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    R3 = np.eye(3) + math.sin(w) * K + (1 - math.cos(w)) * K @ K
    M = np.eye(4); M[:3, :3] = R3
    p = np.asarray(punkt, float)
    M[:3, 3] = p - R3 @ p
    return M


_KONTEXT = None


def kontext():
    """Ein OpenGL-Kontext für alle Zeichner im Prozess (mehrere eigenständige Kontexte stören sich gegenseitig)."""
    global _KONTEXT
    if _KONTEXT is None:
        _KONTEXT = moderngl.create_standalone_context(require=330)
        _KONTEXT.enable(moderngl.DEPTH_TEST)
    return _KONTEXT


class Zeichner:
    def __init__(self, netz, proben=8):
        self.netz = netz
        self.ctx = kontext()
        self.proben = min(proben, self.ctx.max_samples)
        daten = netz.puffer()
        self.vbo = self.ctx.buffer(daten.tobytes())
        self.prog_maske = self.ctx.program(vertex_shader=VS, fragment_shader=FS_MASKE)
        self.prog_teil = self.ctx.program(vertex_shader=VS, fragment_shader=FS_TEIL)
        self.vao_maske = self._vao(self.prog_maske)
        self.vao_teil = self._vao(self.prog_teil)
        self.fbos = {}

    def setze_netz(self, dreiecke):
        """Neue Eckpunkte bei gleicher Bauteilliste (z. B. aus cad_netz.Jacobi.netz) in den Puffer schreiben."""
        netz = Netz(dreiecke=dreiecke)
        daten = netz.puffer()
        if netz.namen != self.netz.namen or daten.nbytes != self.vbo.size:
            raise ValueError("andere Bauteile oder Dreieckszahl: neuen Zeichner anlegen")
        self.netz = netz
        self.vbo.write(daten.tobytes())

    def _vao(self, prog):
        namen = [n for n in ("pos", "gruppe", "teil") if n in prog]
        formate = {"pos": "3f", "gruppe": "1f", "teil": "1f"}
        fmt = " ".join(formate[n] if n in namen else ("12x" if n == "pos" else "4x") for n in ("pos", "gruppe", "teil"))
        return self.ctx.vertex_array(prog, [(self.vbo, fmt, *namen)])

    def _ziele(self, breite, hoehe):
        key = (breite, hoehe)
        if key not in self.fbos:
            ms = self.ctx.framebuffer(
                color_attachments=[self.ctx.renderbuffer((breite, hoehe), components=1, samples=self.proben)],
                depth_attachment=self.ctx.depth_renderbuffer((breite, hoehe), samples=self.proben))
            einfach = self.ctx.framebuffer(color_attachments=[self.ctx.renderbuffer((breite, hoehe), components=1)])
            teil = self.ctx.framebuffer(
                color_attachments=[self.ctx.renderbuffer((breite, hoehe), components=1, dtype="f4")],
                depth_attachment=self.ctx.depth_renderbuffer((breite, hoehe)))
            self.fbos[key] = (ms, einfach, teil)
        return self.fbos[key]

    def _uniforms(self, prog, cam, s, breite, hoehe, bewegungen):
        prog["kamera"].write(kamera_matrix(cam, s, breite, hoehe).T.astype("f4").tobytes())
        mats = [np.eye(4)] * 8
        for g, M in (bewegungen or {}).items():
            mats[g] = M
        prog["bewegung"].write(np.concatenate([m.T.astype("f4").ravel() for m in mats]).tobytes())

    def groesse(self, cam, s):
        return round(cam["w"] * s), round(cam["h"] * s)

    def maske(self, cam, s, bewegungen=None, groesse=None):
        breite, hoehe = groesse or self.groesse(cam, s)
        ms, einfach, _ = self._ziele(breite, hoehe)
        self._uniforms(self.prog_maske, cam, s, breite, hoehe, bewegungen)
        ms.use(); ms.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self.vao_maske.render(moderngl.TRIANGLES)
        self.ctx.copy_framebuffer(einfach, ms)
        roh = np.frombuffer(einfach.read(components=1, alignment=1), dtype=np.uint8)
        return roh.reshape(hoehe, breite).astype(np.float32) / 255.0

    def teile(self, cam, s, bewegungen=None, groesse=None):
        breite, hoehe = groesse or self.groesse(cam, s)
        _, _, teil = self._ziele(breite, hoehe)
        self._uniforms(self.prog_teil, cam, s, breite, hoehe, bewegungen)
        teil.use(); teil.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self.vao_teil.render(moderngl.TRIANGLES)
        roh = np.frombuffer(teil.read(components=1, dtype="f4", alignment=1), dtype=np.float32)
        return np.rint(roh.reshape(hoehe, breite)).astype(np.int32)
