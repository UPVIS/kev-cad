"""Kameramodell für Studiofotos: Lochkamera, Blick über yaw, pitch, roll, Hauptpunkt frei.

Eine Kamera ist ein dict mit f (Brennweite in Originalpixeln), camx, camy, camz (mm), yaw, pitch, roll (rad),
ppx, ppy (Hauptpunkt gegenüber der Bildmitte in Pixeln, > 0 nach rechts und unten), w, h (Fotogröße). Bildkoordinaten
sind stetig (Pixel i deckt [i, i+1]), wie Blender rendert; render_blender-Skripte übernehmen die Kamera unverändert.

Zum Einpassen wird die Kamera als Umlauf um einen Drehpunkt beschrieben (orbit_aus / kamera_aus_orbit): Azimut,
Erhebung, Abstand, Bildmaßstab f/Abstand und die Lage des Zielpunkts in der Ebene quer zur Blickrichtung. So ändert
der Abstand bei festem Maßstab nur die Perspektive; sonst heben sich Abstand und Brennweite gegenseitig auf und die
Suche bleibt hängen (Erfahrung aus der Outdoor-Küche, Oktober 2026).
"""
import math

import numpy as np


def rotation(yaw, pitch, roll):
    """Zeilen: rechts, unten, vorn (Kamerakoordinaten wie OpenCV)."""
    fwd = np.array([math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)])
    right = np.cross(fwd, [0, 0, 1.0]); right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    c, s = math.cos(roll), math.sin(roll)
    return np.vstack([c * right + s * down, -s * right + c * down, fwd])


def projiziere(cam, X, s=1.0):
    """Weltpunkte (mm) in Pixel (Originalpixel mal s)."""
    R = rotation(cam["yaw"], cam["pitch"], cam["roll"])
    pc = (np.asarray(X, float) - [cam["camx"], cam["camy"], cam["camz"]]) @ R.T
    z = np.maximum(pc[:, 2], 1.0)
    u = cam["w"] / 2 + cam.get("ppx", 0.0) + cam["f"] * pc[:, 0] / z
    v = cam["h"] / 2 + cam.get("ppy", 0.0) + cam["f"] * pc[:, 1] / z
    return np.stack([u, v], 1) * s


def kamera_aus(azimut, hoehe, abstand, f, w, h, ziel):
    """Startkamera: aus Richtung azimut (Grad, 0 = von +x) und Höhe (Grad) auf den Zielpunkt blickend."""
    a, e = math.radians(azimut), math.radians(hoehe)
    ziel = np.asarray(ziel, float)
    C = ziel + abstand * np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    fwd = (ziel - C) / abstand
    return dict(f=f, camx=C[0], camy=C[1], camz=C[2], yaw=math.atan2(fwd[1], fwd[0]), pitch=math.asin(fwd[2]),
                roll=0.0, ppx=0.0, ppy=0.0, w=w, h=h)


def orbit_aus(cam, drehpunkt):
    P = np.asarray(drehpunkt, float)
    R = rotation(cam["yaw"], cam["pitch"], cam["roll"])
    fwd = R[2]
    C = np.array([cam["camx"], cam["camy"], cam["camz"]])
    az = math.atan2(-fwd[1], -fwd[0])
    el = math.asin(max(-1.0, min(1.0, -fwd[2])))
    n = np.array([math.cos(az), math.sin(az), 0.0])
    t = float((P - C) @ n / (fwd @ n))
    T = C + t * fwd
    quer = np.array([-math.sin(az), math.cos(az), 0.0])
    return dict(az=math.degrees(az), el=math.degrees(el), abstand=t, mass=cam["f"] / t,
                u=float((T - P) @ quer), w=float(T[2] - P[2]))


def kamera_aus_orbit(o, roll, ppx, ppy, w, h, drehpunkt):
    P = np.asarray(drehpunkt, float)
    az, el = math.radians(o["az"]), math.radians(o["el"])
    T = P + o["u"] * np.array([-math.sin(az), math.cos(az), 0.0]) + np.array([0.0, 0.0, o["w"]])
    C = T + o["abstand"] * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    fwd = (T - C) / o["abstand"]
    return dict(f=o["mass"] * o["abstand"], camx=C[0], camy=C[1], camz=C[2], yaw=math.atan2(fwd[1], fwd[0]),
                pitch=math.asin(fwd[2]), roll=roll, ppx=ppx, ppy=ppy, w=w, h=h)


def packe(cam, drehpunkt, extra=()):
    """Kamera als Vektor zum Einpassen: az, el, abstand, mass * 1000, u, w, roll (Grad), ppx, ppy, extra ..."""
    o = orbit_aus(cam, drehpunkt)
    v = [o["az"], o["el"], o["abstand"], o["mass"] * 1000, o["u"], o["w"], math.degrees(cam["roll"]), cam["ppx"], cam["ppy"]]
    return np.array(v + list(extra), float)


def entpacke(v, w, h, drehpunkt, abstand_min=1500.0):
    az, el, ab, mass, u, w_, rl, px, py = v[:9]
    o = dict(az=az, el=el, abstand=max(ab, abstand_min), mass=mass / 1000, u=u, w=w_)
    return kamera_aus_orbit(o, math.radians(rl), px, py, w, h, drehpunkt), list(v[9:])


def schritte(v, extra=()):
    """Typische Schrittweiten für die Feinsuche (Powell auf normierten Größen)."""
    s = [0.15, 0.1, 120, v[3] * 0.003, 5, 5, 0.08, 6, 6]
    return np.array(s + list(extra), float)
