"""Koordinaten zwischen ARKit und Kev CAD, Quaternionen, starre Bewegungen.

- ARKit-Welt: rechtshändig, y oben, Meter (SCAN.md). Kev CAD: rechtshändig, z oben, Millimeter.
  X_kev = 1000 · M · X_ar mit M = [[1, 0, 0], [0, 0, −1], [0, 1, 0]] (x bleibt, −z_ar wird y, y_ar wird z).
- ARKit-Kamera: x rechts, y oben, Blick −z (Querformat des Sensors). OpenCV-Kamera (fotomess, Phase 4): x rechts,
  y unten, Blick z. Umrechnung F = diag(1, −1, −1).
- Kamera als (R, t) Welt → OpenCV-Kamera, t in mm: Pixel = K · (R · X + t), wie ``Kamera`` in fotomess und
  ``aligned.opencv`` in poses.json von kevcad-capture.
"""

from __future__ import annotations

import math

import numpy as np

M_AR = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
F_CAM = np.diag([1.0, -1.0, -1.0])
MM = 1000.0


def quat_zu_matrix(q) -> np.ndarray:
    """Quaternion (x, y, z, w) -> Drehmatrix."""
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def matrix_zu_quat(R) -> list[float]:
    """Drehmatrix -> Quaternion (x, y, z, w)."""
    R = np.asarray(R, float)
    tr = np.trace(R)
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    return [float(x), float(y), float(z), float(w)]


def opencv_aus_arkit(R_wc, t_wc_m) -> tuple[np.ndarray, np.ndarray]:
    """ARKit-Lage (Kamera -> Welt, Meter) -> (R, t) Kev-CAD-Welt (mm, vor dem Verschieben auf den Boden) ->
    OpenCV-Kamera."""
    R_wc = np.asarray(R_wc, float)
    R = F_CAM @ R_wc.T @ M_AR.T
    t = -MM * F_CAM @ R_wc.T @ np.asarray(t_wc_m, float)
    return R, t


def arkit_aus_opencv(R, t_mm) -> tuple[np.ndarray, np.ndarray]:
    """Umkehrung von ``opencv_aus_arkit``: (R, t) -> (R_wc, t_wc in Metern)."""
    R = np.asarray(R, float)
    R_wc = M_AR.T @ R.T @ F_CAM
    C = -R.T @ np.asarray(t_mm, float)
    return R_wc, M_AR.T @ C / MM


def punkte_ar_zu_kev(P_m) -> np.ndarray:
    return MM * np.asarray(P_m, float) @ M_AR.T


def zentrum(R, t) -> np.ndarray:
    return -np.asarray(R, float).T @ np.asarray(t, float)


def bewegt(R, t, A, b) -> tuple[np.ndarray, np.ndarray]:
    """Kamera nach der starren Bewegung der Welt X' = A X + b (wie kevcad_kernel.referenz.netz.bewegt)."""
    R2 = np.asarray(R, float) @ np.asarray(A, float).T
    return R2, np.asarray(t, float) - R2 @ np.asarray(b, float)


def rz(winkel_rad: float) -> np.ndarray:
    c, s = math.cos(winkel_rad), math.sin(winkel_rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def matrix4(A, b) -> list[list[float]]:
    M = np.eye(4)
    M[:3, :3] = A
    M[:3, 3] = b
    return [[round(float(x), 9) for x in r] for r in M]


def winkel_grad(a, b) -> float:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    c = float(a @ b / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def fokuspunkt(zentren: np.ndarray, richtungen: np.ndarray) -> np.ndarray:
    """Punkt mit dem kleinsten Abstand zu allen Sehstrahlen (Kleinste Quadrate)."""
    A = np.zeros((3, 3))
    b = np.zeros(3)
    for c, d in zip(zentren, richtungen):
        d = d / max(np.linalg.norm(d), 1e-12)
        P = np.eye(3) - np.outer(d, d)
        A += P
        b += P @ c
    return np.linalg.lstsq(A, b, rcond=None)[0]
