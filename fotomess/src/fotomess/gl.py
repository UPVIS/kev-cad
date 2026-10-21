"""Zeichnen auf der Grafikkarte (moderngl, OpenGL 3.3, ein gemeinsamer Kontext wie fotocad.netz_gl).

Zwei Aufgaben, beide dort, wo die GPU messbar hilft:
- Tiefenbild einer Ansicht für die Sichtbarkeit der Kantenpunkte (ein Zeichenaufruf, Lesen als float32).
- Viele Kandidatenkameras auf einmal als Silhouetten in einen Kachel-Atlas (Grobsuche der Lage); je Kachel eigener
  Viewport, damit nichts in die Nachbarkacheln läuft.
"""
from __future__ import annotations

import moderngl
import numpy as np

VS = """
#version 330
uniform mat4 mvp;
uniform mat4 mv;
in vec3 pos;
out float tiefe;
void main() {
    gl_Position = mvp * vec4(pos, 1.0);
    tiefe = (mv * vec4(pos, 1.0)).z;
}
"""
FS_TIEFE = """
#version 330
in float tiefe;
out float farbe;
void main() { farbe = tiefe; }
"""
VS_SCHATTEN = """
#version 330
uniform mat4 mvp;
in vec3 pos;
out vec3 welt;
void main() {
    gl_Position = mvp * vec4(pos, 1.0);
    welt = pos;
}
"""
FS_SCHATTEN = """
#version 330
in vec3 welt;
uniform vec3 licht;
uniform vec3 auge;
out float farbe;
void main() {
    vec3 n = normalize(cross(dFdx(welt), dFdy(welt)));
    if (dot(n, auge - welt) < 0.0) n = -n;
    farbe = 0.25 + 0.7 * abs(dot(n, normalize(licht)));
}
"""
FS_MASKE = """
#version 330
in float tiefe;
out float farbe;
void main() { farbe = 1.0; }
"""


def kontext():
    try:
        from fotocad.netz_gl import kontext as fk
        return fk()
    except Exception:  # fotocad fehlt: eigener Kontext
        global _CTX
        if "_CTX" not in globals():
            _CTX = moderngl.create_standalone_context(require=330)
            _CTX.enable(moderngl.DEPTH_TEST)
        return _CTX


class Zeichner:
    """Indiziertes Netz auf der GPU; Eckpunkte lassen sich je Ansicht neu schreiben (Maße, Gelenke)."""

    def __init__(self, V, tris):
        self.ctx = kontext()
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.nv = len(V)
        self.vbo = self.ctx.buffer(np.asarray(V, np.float32).tobytes(), dynamic=True)
        self.ibo = self.ctx.buffer(np.asarray(tris, np.int32).tobytes())
        self.prog_tiefe = self.ctx.program(vertex_shader=VS, fragment_shader=FS_TIEFE)
        self.prog_maske = self.ctx.program(vertex_shader=VS, fragment_shader=FS_MASKE)
        self.vao_tiefe = self.ctx.vertex_array(self.prog_tiefe, [(self.vbo, "3f", "pos")], self.ibo)
        self.vao_maske = self.ctx.vertex_array(self.prog_maske, [(self.vbo, "3f", "pos")], self.ibo)
        self.prog_schatten = self.ctx.program(vertex_shader=VS_SCHATTEN, fragment_shader=FS_SCHATTEN)
        self.vao_schatten = self.ctx.vertex_array(self.prog_schatten, [(self.vbo, "3f", "pos")], self.ibo)
        self.fbos = {}
        self._stand = None

    def setze(self, V, schluessel=None):
        if schluessel is not None and schluessel == self._stand:
            return
        self.vbo.write(np.asarray(V, np.float32).tobytes())
        self._stand = schluessel

    def _fbo(self, breite, hoehe, art):
        key = (breite, hoehe, art)
        if key not in self.fbos:
            dtype = "f4" if art == "tiefe" else "f1"
            self.fbos[key] = self.ctx.framebuffer(
                color_attachments=[self.ctx.renderbuffer((breite, hoehe), components=1, dtype=dtype)],
                depth_attachment=self.ctx.depth_renderbuffer((breite, hoehe)))
        return self.fbos[key]

    @staticmethod
    def _matrizen(kamera, s, breite, hoehe, nah, fern):
        mvp = kamera.opengl_matrix(s, breite, hoehe, nah, fern)
        mv = np.eye(4)
        mv[:3, :3] = kamera.R
        mv[:3, 3] = kamera.t
        return mvp, mv

    def tiefe(self, kamera, s, groesse=None, nah=10.0, fern=1e5):
        """Tiefe (z im Kamerasystem, mm) je Pixel der Stufe s; 0 = Hintergrund."""
        breite, hoehe = groesse or (round(kamera.w * s), round(kamera.h * s))
        fbo = self._fbo(breite, hoehe, "tiefe")
        mvp, mv = self._matrizen(kamera, s, breite, hoehe, nah, fern)
        self.prog_tiefe["mvp"].write(mvp.T.astype("f4").tobytes())
        self.prog_tiefe["mv"].write(mv.T.astype("f4").tobytes())
        fbo.use()
        fbo.viewport = (0, 0, breite, hoehe)
        fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self.vao_tiefe.render(moderngl.TRIANGLES)
        roh = np.frombuffer(fbo.read(components=1, dtype="f4", alignment=1), np.float32)
        return roh.reshape(hoehe, breite)

    def schattiert(self, kamera, s, groesse=None, licht=(0.3, -0.5, 0.8), nah=10.0, fern=1e5):
        """Graues Bild mit flacher Schattierung (für Probebilder und Kontrollbilder), 0 = Hintergrund."""
        breite, hoehe = groesse or (round(kamera.w * s), round(kamera.h * s))
        fbo = self._fbo(breite, hoehe, "tiefe")
        mvp, _ = self._matrizen(kamera, s, breite, hoehe, nah, fern)
        self.prog_schatten["mvp"].write(mvp.T.astype("f4").tobytes())
        self.prog_schatten["licht"].value = tuple(float(x) for x in licht)
        self.prog_schatten["auge"].value = tuple(float(x) for x in kamera.zentrum)
        fbo.use()
        fbo.viewport = (0, 0, breite, hoehe)
        fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self.vao_schatten.render(moderngl.TRIANGLES)
        roh = np.frombuffer(fbo.read(components=1, dtype="f4", alignment=1), np.float32)
        return roh.reshape(hoehe, breite)

    def atlas(self, kameras, s, kachel, nah=10.0, fern=1e5, spalten=None):
        """Silhouetten vieler Kameras (gleiche Bildgröße kachel = (breite, hoehe) in Pixeln der Stufe s) in einem
        Zeichenpuffer; Rückgabe (n, hoehe, breite) uint8 (0/255)."""
        kb, kh = kachel
        n = len(kameras)
        spalten = spalten or max(1, min(n, 4096 // kb))
        zeilen = (n + spalten - 1) // spalten
        breite, hoehe = spalten * kb, zeilen * kh
        if hoehe > 8192:
            teile = []
            pro = (8192 // kh) * spalten
            for i in range(0, n, pro):
                teile.append(self.atlas(kameras[i:i + pro], s, kachel, nah, fern, spalten))
            return np.concatenate(teile)
        fbo = self._fbo(breite, hoehe, "maske")
        fbo.use()
        fbo.viewport = (0, 0, breite, hoehe)
        fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        for i, kam in enumerate(kameras):
            r, c = divmod(i, spalten)
            # Zeile 0 des Puffers ist oben (wie beim Tiefenbild): Kachel r liegt bei y = r * kh
            fbo.viewport = (c * kb, r * kh, kb, kh)
            mvp, mv = self._matrizen(kam, s, kb, kh, nah, fern)
            self.prog_maske["mvp"].write(mvp.T.astype("f4").tobytes())
            self.prog_maske["mv"].write(mv.T.astype("f4").tobytes())
            self.vao_maske.render(moderngl.TRIANGLES)
        roh = np.frombuffer(fbo.read(components=1, dtype="f1", alignment=1), np.uint8).reshape(hoehe, breite)
        kacheln = roh.reshape(zeilen, kh, spalten, kb).transpose(0, 2, 1, 3).reshape(zeilen * spalten, kh, kb)
        return kacheln[:n]


_JE_NETZ = {}


def fuer_netz(netz):
    """Ein Zeichner je Netz und Prozess (GPU-Puffer und Programme nur einmal anlegen)."""
    z = _JE_NETZ.get(id(netz))
    if z is None or z[0] is not netz:
        z = (netz, Zeichner(netz.V0, netz.tris))
        _JE_NETZ[id(netz)] = z
    return z[1]
