"""Kameramodell: Lochkamera mit gemeinsamen Innenparametern, Lage als Drehung und Verschiebung im Objektsystem.

Konvention wie OpenCV: Kamerakoordinaten x rechts, y unten, z nach vorn; x_k = R X + t. Bildkoordinaten sind
stetig (Pixel i deckt [i, i+1]), genau wie fotocad und Blender; der Hauptpunkt liegt in der Bildmitte (cx = w/2,
cy = h/2), sofern nicht anders angegeben. Brennweite f in Pixeln der Originalauflösung; eine Bildstufe mit Faktor s
skaliert f, cx und cy mit s.

Beim Einpassen ändert sich die Lage linksseitig im Kamerasystem: R <- exp([dw]) R, t <- exp([dw]) t + dt. Dann ist
die Ableitung eines Kamerapunkts nach (dw, dt) einfach (-[x_k], I) und die Normalgleichungen sind gut konditioniert.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def schief(v):
    """Kreuzproduktmatrix [v]x."""
    x, y, z = v
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def exp_so3(w):
    """Drehvektor -> Drehmatrix (Rodrigues)."""
    w = np.asarray(w, float)
    th = float(np.linalg.norm(w))
    if th < 1e-12:
        return np.eye(3) + schief(w)
    k = schief(w / th)
    return np.eye(3) + math.sin(th) * k + (1 - math.cos(th)) * k @ k


def log_so3(R):
    c = (np.trace(R) - 1) / 2
    th = math.acos(max(-1.0, min(1.0, c)))
    if th < 1e-9:
        return np.zeros(3)
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    if abs(math.pi - th) < 1e-6:
        # Gegenüberliegend: Achse aus der symmetrischen Matrix
        A = (R + np.eye(3)) / 2
        i = int(np.argmax(np.diag(A)))
        a = A[:, i] / math.sqrt(max(A[i, i], 1e-12))
        return a * th
    return v * th / (2 * math.sin(th))


def winkel_zwischen(R1, R2):
    """Drehwinkel zwischen zwei Drehungen in Grad."""
    return math.degrees(float(np.linalg.norm(log_so3(R1 @ R2.T))))


def blick(azimut_grad, hoehe_grad, roll_grad=0.0):
    """Drehung einer Kamera, die aus Richtung azimut (0 = von +x) und Höhe auf den Ursprung blickt.
    roll dreht um die Blickachse; 180 heißt: das Objekt steht im Bild auf dem Kopf (oben = -z)."""
    a, e = math.radians(azimut_grad), math.radians(hoehe_grad)
    richtung = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    vorn = -richtung
    oben = np.array([0.0, 0.0, 1.0])
    rechts = np.cross(vorn, oben)
    if np.linalg.norm(rechts) < 1e-6:
        rechts = np.array([math.sin(a), -math.cos(a), 0.0])
    rechts /= np.linalg.norm(rechts)
    unten = np.cross(vorn, rechts)
    R = np.vstack([rechts, unten, vorn])
    if roll_grad:
        R = exp_so3(np.array([0.0, 0.0, math.radians(roll_grad)])) @ R
    return R


@dataclass
class Kamera:
    R: np.ndarray                       # Welt -> Kamera
    t: np.ndarray
    f: float                            # Pixel der Originalauflösung
    w: int
    h: int
    cx: float | None = None
    cy: float | None = None
    name: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.R = np.asarray(self.R, float)
        self.t = np.asarray(self.t, float)
        if self.cx is None:
            self.cx = self.w / 2
        if self.cy is None:
            self.cy = self.h / 2

    def kopie(self, **aend):
        d = dict(R=self.R.copy(), t=self.t.copy(), f=self.f, w=self.w, h=self.h, cx=self.cx, cy=self.cy,
                 name=self.name, extra=dict(self.extra))
        d.update(aend)
        return Kamera(**d)

    @property
    def zentrum(self):
        return -self.R.T @ self.t

    def nach_kamera(self, X):
        return np.asarray(X, float) @ self.R.T + self.t

    def projiziere(self, X, s=1.0):
        """Weltpunkte -> Bildpunkte (Pixel der Stufe s) und Tiefe."""
        Xk = self.nach_kamera(X)
        z = np.maximum(Xk[:, 2], 1e-6)
        u = (self.f * Xk[:, 0] / z + self.cx) * s
        v = (self.f * Xk[:, 1] / z + self.cy) * s
        return np.stack([u, v], 1), Xk[:, 2]

    def schritt(self, dw, dt):
        Rn = exp_so3(dw)
        return self.kopie(R=Rn @ self.R, t=Rn @ self.t + dt)

    def opengl_matrix(self, s, breite, hoehe, nah=10.0, fern=1e5):
        """Welt -> Clip-Raum für ein Bild breite x hoehe; Zeile 0 des gelesenen Puffers ist die oberste Bildzeile
        (wie fotocad.netz_gl.kamera_matrix)."""
        E = np.eye(4)
        E[:3, :3] = self.R
        E[:3, 3] = self.t
        f = self.f * s
        cx, cy = self.cx * s, self.cy * s
        K = np.zeros((4, 4))
        K[0, 0] = 2 * f / breite
        K[0, 2] = 2 * cx / breite - 1
        K[1, 1] = 2 * f / hoehe
        K[1, 2] = 2 * cy / hoehe - 1
        K[2, 2] = (fern + nah) / (fern - nah)
        K[2, 3] = -2 * fern * nah / (fern - nah)
        K[3, 2] = 1.0
        return K @ E

    # -------------------------------------------------------------- Umrechnung zu fotocad
    @classmethod
    def aus_fotocad(cls, c, name=""):
        from fotocad.kamera import rotation
        R = rotation(c["yaw"], c["pitch"], c["roll"])
        C = np.array([c["camx"], c["camy"], c["camz"]], float)
        w, h = int(c["w"]), int(c["h"])
        return cls(R=R, t=-R @ C, f=float(c["f"]), w=w, h=h, cx=w / 2 + c.get("ppx", 0.0), cy=h / 2 + c.get("ppy", 0.0),
                   name=name)

    def als_fotocad(self):
        fwd = self.R[2]
        yaw = math.atan2(fwd[1], fwd[0])
        pitch = math.asin(max(-1.0, min(1.0, fwd[2])))
        from fotocad.kamera import rotation
        R0 = rotation(yaw, pitch, 0.0)
        # Roll: Drehung um die Blickachse zwischen R0 und R
        c = float(self.R[0] @ R0[0])
        s = float(self.R[0] @ R0[1])
        roll = math.atan2(s, c)
        C = self.zentrum
        return dict(f=float(self.f), camx=float(C[0]), camy=float(C[1]), camz=float(C[2]), yaw=yaw, pitch=pitch,
                    roll=roll, ppx=float(self.cx - self.w / 2), ppy=float(self.cy - self.h / 2), w=float(self.w),
                    h=float(self.h))

    def als_dict(self):
        return dict(name=self.name, R=self.R.tolist(), t=self.t.tolist(), f=float(self.f), w=self.w, h=self.h,
                    cx=float(self.cx), cy=float(self.cy), zentrum=self.zentrum.tolist())

    @classmethod
    def aus_dict(cls, d):
        return cls(R=np.array(d["R"]), t=np.array(d["t"]), f=d["f"], w=d["w"], h=d["h"], cx=d["cx"], cy=d["cy"],
                   name=d.get("name", ""))


def projektion_ableitung(Xk, f):
    """Ableitung der Bildpunkte nach den Kamerakoordinaten (n, 2, 3) und nach log f (n, 2), Stufe 1."""
    x, y, z = Xk[:, 0], Xk[:, 1], np.maximum(Xk[:, 2], 1e-6)
    iz = 1.0 / z
    J = np.zeros((len(Xk), 2, 3))
    J[:, 0, 0] = f * iz
    J[:, 0, 2] = -f * x * iz * iz
    J[:, 1, 1] = f * iz
    J[:, 1, 2] = -f * y * iz * iz
    Jf = np.stack([f * x * iz, f * y * iz], 1)
    return J, Jf


def rollwinkel(R):
    """Neigung der Bild-x-Achse gegen die Waagerechte des Objekts (Grad); 0 bei waagerecht gehaltener Kamera,
    auch wenn das Objekt auf dem Kopf liegt."""
    return math.degrees(math.asin(max(-1.0, min(1.0, float(R[0, 2])))))


def brennweite_aus_35mm(f35, breite, hoehe, video_beschnitt=1.0):
    """Brennweite in Pixeln aus der Kleinbild-Äquivalenz (bezogen auf die Diagonale des 4:3-Fotosensors).
    video_beschnitt: Faktor > 1, wenn das Video einen engeren Ausschnitt des Sensors nutzt (Bildstabilisierung)."""
    diag_kb = math.hypot(36.0, 24.0)
    lang = max(breite, hoehe)
    # Sensorbreite der langen Seite bei 4:3 relativ zur Diagonale: 4/5
    lang_aequiv = diag_kb * 0.8
    return f35 / lang_aequiv * lang * video_beschnitt
