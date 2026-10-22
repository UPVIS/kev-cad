"""Referenznetz und Kameras: OBJ und poses.json von kevcad-capture lesen, Kameras in die Form von REF_PHOTOS bringen,
das Netz an das Modell anlegen.

Kamera (wie fotomess ``Kamera.als_dict`` und poses.json ``opencv``): ``R`` (3 × 3 zeilenweise, Welt → Kamera), ``t``,
``f`` (Pixel), ``cx``, ``cy``, ``w``, ``h`` (Bildgröße in Pixeln, auf die sich f, cx, cy beziehen). OpenCV-Konvention:
Kamera x rechts, y unten, z Blickrichtung; Pixel = K · (R · X + t), Ursprung links oben, mm, Z oben.

Anlegen: Object Capture richtet sein Netz am Boden und am Grundkörper aus (Mitte x = y = 0, lange Seite = X), das
Modell hat sein eigenes System. Stammen Netz und Messung aus demselben Video, liegen für dieselben Zeitpunkte zwei
Kameras vor (Object Capture interpoliert über ``time_s``, fotomess aus der Messung). Daraus folgt die Drehung um Z und
die Verschiebung, die das Netz auf das Modell legt (Maßstab des Netzes bleibt, er kommt aus dem gemessenen Maß).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

MAX_DREIECKE = 250_000


def lies_obj(pfad: str | Path) -> dict[str, np.ndarray]:
    """Dreiecksnetz aus einer OBJ-Datei (v, f; Vielecke werden gefächert). Normalen je Punkt flächengewichtet."""
    punkte: list[list[float]] = []
    dreiecke: list[list[int]] = []
    with open(pfad, encoding="utf-8", errors="replace") as f:
        for zeile in f:
            if zeile.startswith("v "):
                teile = zeile.split()
                punkte.append([float(teile[1]), float(teile[2]), float(teile[3])])
            elif zeile.startswith("f "):
                ids = [int(t.split("/")[0]) for t in zeile.split()[1:]]
                ids = [i - 1 if i > 0 else len(punkte) + i for i in ids]
                for k in range(1, len(ids) - 1):
                    dreiecke.append([ids[0], ids[k], ids[k + 1]])
    pos = np.asarray(punkte, dtype=np.float64).reshape(-1, 3)
    tri = np.asarray(dreiecke, dtype=np.int64).reshape(-1, 3)
    if len(tri) and (tri.min() < 0 or tri.max() >= len(pos)):
        raise ValueError(f"{Path(pfad).name}: Flächen verweisen auf Punkte, die es nicht gibt")
    if len(tri) > MAX_DREIECKE:
        tri = tri[np.linspace(0, len(tri) - 1, MAX_DREIECKE).astype(int)]
    return {"positions": pos, "triangles": tri, "normals": normalen(pos, tri)}


def normalen(pos: np.ndarray, tri: np.ndarray) -> np.ndarray:
    n = np.zeros_like(pos)
    if len(tri):
        a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
        fn = np.cross(b - a, c - a)
        for k in range(3):
            np.add.at(n, tri[:, k], fn)
    laenge = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(laenge > 1e-12, n / np.maximum(laenge, 1e-12), np.array([0.0, 0.0, 1.0]))
    return n


def huelle(pos: np.ndarray) -> dict[str, list[float]]:
    if not len(pos):
        return {"min": [0, 0, 0], "max": [0, 0, 0]}
    return {"min": [round(float(x), 3) for x in pos.min(0)], "max": [round(float(x), 3) for x in pos.max(0)]}


def kamera_aus_pose(eintrag: dict[str, Any]) -> dict[str, Any] | None:
    """Kamera (R, t, f, cx, cy, w, h) aus einem Eintrag von poses.json (Form ``aligned``)."""
    a = eintrag.get("aligned") or {}
    cv = a.get("opencv") or {}
    if "R" not in cv or "t" not in cv:
        return None
    w, h = int(eintrag.get("width") or 0), int(eintrag.get("height") or 0)
    fx = a.get("fx")
    if fx is None and a.get("K"):
        fx = a["K"][0][0]
    if fx is None and a.get("hfov_deg") and w:
        fx = w / 2 / math.tan(math.radians(float(a["hfov_deg"])) / 2)
    if fx is None or not w or not h:
        return None
    return {"R": [[float(x) for x in r] for r in cv["R"]], "t": [float(x) for x in cv["t"]], "f": float(fx),
            "fy": float(a.get("fy") or fx), "cx": float(a.get("cx") if a.get("cx") is not None else w / 2),
            "cy": float(a.get("cy") if a.get("cy") is not None else h / 2), "w": w, "h": h}


def lies_posen(pfad: str | Path) -> list[dict[str, Any]]:
    """Kameras aus poses.json: je Bild ``name``, ``bild`` (Pfad), ``zeit`` (s im Video), ``kamera``."""
    d = json.loads(Path(pfad).read_text(encoding="utf-8"))
    out = []
    for e in d.get("cameras") or []:
        k = kamera_aus_pose(e)
        if k is None:
            continue
        bild = e.get("path") or str(Path(pfad).parent / "bilder" / str(e.get("image")))
        out.append({"name": Path(str(e.get("image") or bild)).stem, "bild": str(bild),
                    "zeit": float(e["time_s"]) if e.get("time_s") is not None else None, "kamera": k})
    return out


def zentrum(k: dict[str, Any]) -> np.ndarray:
    R = np.asarray(k["R"], float)
    return -R.T @ np.asarray(k["t"], float)


def blickrichtung(k: dict[str, Any]) -> np.ndarray:
    return np.asarray(k["R"], float)[2]


def skaliert(k: dict[str, Any], breite: int, hoehe: int) -> dict[str, Any]:
    """Kamera für eine verkleinerte Kopie des Bildes (f, cx, cy mit dem Faktor, w, h neu)."""
    sx = breite / float(k["w"])
    sy = hoehe / float(k["h"])
    out = dict(k)
    out.update(f=float(k["f"]) * sx, fy=float(k.get("fy", k["f"])) * sy, cx=float(k["cx"]) * sx,
               cy=float(k["cy"]) * sy, w=int(breite), h=int(hoehe))
    return out


def bewegt(k: dict[str, Any], A: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    """Kamera nach einer starren Bewegung der Welt X' = A X + b."""
    R = np.asarray(k["R"], float)
    t = np.asarray(k["t"], float)
    R2 = R @ A.T
    t2 = t - R2 @ b
    out = dict(k)
    out["R"] = [[float(x) for x in r] for r in R2]
    out["t"] = [float(x) for x in t2]
    return out


def zeit_aus_name(name: str) -> float | None:
    """Zeit aus Bildnamen wie „IMG_5186_014.833“ (fotomess, video.holen)."""
    text = Path(name).name
    text = re.sub(r"\.(jpe?g|png|heic|tiff?)$", "", text, flags=re.IGNORECASE)
    m = re.search(r"_(\d+\.\d+)$", text)
    return float(m.group(1)) if m else None


def _interpoliert(posen: list[dict[str, Any]], t: float, max_luecke: float = 1.5):
    mit_zeit = sorted((p for p in posen if p.get("zeit") is not None), key=lambda p: p["zeit"])
    if not mit_zeit:
        return None
    zeiten = np.array([p["zeit"] for p in mit_zeit])

    def achse(k: dict[str, Any]) -> np.ndarray:
        return np.asarray(k["R"], float)[0]

    i = int(np.searchsorted(zeiten, t))
    if i < len(zeiten) and abs(zeiten[i] - t) < 1e-3:
        p = mit_zeit[i]["kamera"]
        return zentrum(p), blickrichtung(p), achse(p)
    if i == 0 or i >= len(zeiten):
        j = 0 if i == 0 else len(zeiten) - 1
        if abs(zeiten[j] - t) > max_luecke / 3:
            return None
        p = mit_zeit[j]["kamera"]
        return zentrum(p), blickrichtung(p), achse(p)
    a, b = mit_zeit[i - 1], mit_zeit[i]
    if zeiten[i] - zeiten[i - 1] > max_luecke:
        return None
    w = (t - zeiten[i - 1]) / (zeiten[i] - zeiten[i - 1])
    c = (1 - w) * zentrum(a["kamera"]) + w * zentrum(b["kamera"])
    d = (1 - w) * blickrichtung(a["kamera"]) + w * blickrichtung(b["kamera"])
    x = (1 - w) * achse(a["kamera"]) + w * achse(b["kamera"])
    return c, d / max(np.linalg.norm(d), 1e-9), x / max(np.linalg.norm(x), 1e-9)


def anlegen(capture_posen: list[dict[str, Any]], mess_kameras: list[dict[str, Any]], netz_mitte: np.ndarray
            ) -> dict[str, Any] | None:
    """Lage des Netzes im Modellsystem aus Kamerapaaren gleicher Videozeit: Drehung um Z, Verschiebung.

    ``mess_kameras``: je Bild ``zeit`` und ``kamera`` (fotomess). Ergebnis: ``matrix`` (4 × 4 spaltenweise, wie
    ``transform`` im Protokoll), ``drehung_z`` (Grad), ``verschiebung``, ``massstab`` (Kamerawege fotomess / Object
    Capture, nur zur Angabe), ``rest_mm`` (mittlerer Abstand der Kamerazentren danach), ``paare``; None ohne
    mindestens zwei Paare."""
    X, Y, DX, DY, RX, RY, zeiten = [], [], [], [], [], [], []
    ohne_paar = []
    for m in mess_kameras:
        if m.get("zeit") is None:
            continue
        r = _interpoliert(capture_posen, float(m["zeit"]))
        if r is None:
            ohne_paar.append(float(m["zeit"]))
            continue
        X.append(r[0])
        DX.append(r[1])
        RX.append(r[2])
        Y.append(zentrum(m["kamera"]))
        DY.append(blickrichtung(m["kamera"]))
        RY.append(np.asarray(m["kamera"]["R"], float)[0])
        zeiten.append(float(m["zeit"]))
    if len(X) < 2:
        return None
    # Drehung um Z je Paar aus der Kamera-x-Achse (waagrecht, auch bei Draufsichten stabil); Paare, deren Drehung
    # weit vom Median abweicht, sind Ausreißer (fotomess hat eine Zwillingslage gewählt, etwa vorn und hinten
    # vertauscht) und zählen beim Anlegen nicht
    gier = np.array([math.atan2(ry[1], ry[0]) - math.atan2(rx[1], rx[0]) for rx, ry in zip(RX, RY)])
    gier = (gier + math.pi) % (2 * math.pi) - math.pi
    ref = math.atan2(np.sin(gier).sum(), np.cos(gier).sum())
    for _ in range(2):
        abw = np.abs((gier - ref + math.pi) % (2 * math.pi) - math.pi)
        drin = abw < math.radians(30)
        if drin.sum() >= max(2, (len(gier) + 1) // 2):
            ref = math.atan2(np.sin(gier[drin]).sum(), np.cos(gier[drin]).sum())
    abw = np.abs((gier - ref + math.pi) % (2 * math.pi) - math.pi)
    drin = abw < math.radians(30)
    if drin.sum() < 2:
        return None
    ausreisser = [{"zeit": z, "abweichung_grad": round(math.degrees(a), 1)} for z, a, d in zip(zeiten, abw, drin)
                  if not d]
    X, Y, DX, DY = (np.asarray(v, float)[drin] for v in (X, Y, DX, DY))
    xm, ym = X.mean(0), Y.mean(0)
    Xc, Yc = X - xm, Y - ym
    s = float(np.sqrt((Yc[:, :2] ** 2).sum() / max((Xc[:, :2] ** 2).sum(), 1e-9)))
    abstand = float(np.linalg.norm(Yc, axis=1).mean() or 300.0)
    # Drehung um Z (2D-Kabsch) aus Kamerazentren und Blickrichtungen
    P = np.concatenate([Xc[:, :2], DX[:, :2] * abstand])
    Q = np.concatenate([Yc[:, :2] * (1 / max(s, 1e-9)), DY[:, :2] * abstand])
    H = P.T @ Q
    phi = math.atan2(H[0, 1] - H[1, 0], H[0, 0] + H[1, 1])
    c, sn = math.cos(phi), math.sin(phi)
    A = np.array([[c, -sn, 0.0], [sn, c, 0.0], [0.0, 0.0, 1.0]])
    # Ähnlichkeit X -> s A X + b0 legt die Kameras aufeinander; das Netz behält seinen Maßstab und kommt mit seiner
    # Mitte dorthin, wo die Ähnlichkeit sie hinlegt: X -> A (X - p0) + (s A p0 + b0)
    b0 = ym - s * A @ xm
    p0 = np.asarray(netz_mitte, float)
    b = s * A @ p0 + b0 - A @ p0
    rest = float(np.linalg.norm((s * (A @ X.T).T + b0) - Y, axis=1).mean())
    M = np.eye(4)
    M[:3, :3] = A
    M[:3, 3] = b
    return {"matrix": [float(x) for x in M.T.reshape(-1)], "drehung_z": round(math.degrees(phi), 2),
            "verschiebung": [round(float(x), 2) for x in b], "massstab": round(s, 4), "rest_mm": round(rest, 1),
            "paare": int(len(X)), "ausreisser": ausreisser, "ohne_paar": ohne_paar, "A": A, "b": b}


def startkamera(capture_posen: list[dict[str, Any]], zeit: float, lage: dict[str, Any], breite: int, hoehe: int
                ) -> dict[str, Any] | None:
    """Kamera aus Object Capture zur Videozeit ``zeit`` im System des Modells (mit ``lage`` bewegt), für ein Bild der
    Größe ``breite`` × ``hoehe`` (Startwert für fotomess). Nächstes Bild innerhalb von 0,5 s, sonst None."""
    mit_zeit = [p for p in capture_posen if p.get("zeit") is not None]
    if not mit_zeit:
        return None
    p = min(mit_zeit, key=lambda q: abs(q["zeit"] - zeit))
    if abs(p["zeit"] - zeit) > 0.5:
        return None
    r = _interpoliert(capture_posen, zeit)
    k = bewegt(p["kamera"], np.asarray(lage["A"], float), np.asarray(lage["b"], float))
    if r is not None:  # Zentrum auf die genaue Zeit verschieben, Drehung vom nächsten Bild
        c = np.asarray(lage["A"], float) @ r[0] + np.asarray(lage["b"], float)
        R = np.asarray(k["R"], float)
        k["t"] = [float(x) for x in -R @ c]
    return skaliert(k, breite, hoehe)


def bewege_netz(netz: dict[str, np.ndarray], A: np.ndarray, b: np.ndarray) -> dict[str, np.ndarray]:
    return {"positions": netz["positions"] @ A.T + b, "normals": netz["normals"] @ A.T,
            "triangles": netz["triangles"]}
