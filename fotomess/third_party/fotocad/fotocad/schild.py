"""Echte Markenschilder und Logos in KI-Produktbilder einsetzen und Kleinstschrift entfernen, ohne Bildmodell.

KI-Bilder sollen kein Logo malen (es wird nie formtreu). Stattdessen bekommt das Bild das echte Schild nachträglich:
als RGBA-Bild (aus dem Logo der Dumb Reference Library gebaut), perspektivisch auf die Fläche gelegt, auf der es am
echten Produkt sitzt, und an Licht, Farbstich, Schärfe und Korn des Bildes angepasst.

Eine Stelle ist ein dict:

    flaeche   Viereck der Trägerfläche im Bild: oben links, oben rechts, unten rechts, unten links (Bildpunkte)
    mm        Breite und Höhe dieser Fläche am echten Produkt
    schild    Lage des Schilds auf der Fläche in mm: u0, v0, u1, v1 (von links oben)
    oder schild_auto  für Blenden, deren Höhe die KI anders zeichnet als in echt (siehe auto_lage)
    gain      Kontrast des Schilds über dem Schwarz der Fläche (0,5 bis 0,7; dunkle Szenen weniger)
    grund     "eigen" für helle Trägerflächen (Edelstahl): das Schild behält seine Farben, belichtung (0,7 bis 1)
              und die Lichtfarbe der Umgebung wirken; sonst liegt es über dem Schwarz der Fläche
    ring, stich, weich, korn   Feinheiten der Anpassung

Referenzanwendung: ~/Code Experiments/Beelonia/assets/outdoor-kueche-2026-10/retusche/werkzeug/ (retusche.py,
stellen.json), Oktober 2026.
"""
import cv2
import numpy as np

UEBER = 4                       # Überabtastung beim Verzerren


def linear(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255.0


def homographie(von, nach):
    return cv2.getPerspectiveTransform(np.float32(von), np.float32(nach))


def auto_lage(eintrag, breite_mm=117.0):
    """Lage für ein Schild auf einer schmalen Blende, deren Höhe im KI-Bild nicht dem echten Maß entspricht.

    schild_auto: mitte_x (Bildspalte der Schildmitte, etwa über der Türfuge), aspekt (Breite zu Höhe des Schilds im
    Bild; aus den Türen abschätzen: echtes Seitenverhältnis mal Verkürzung der Front), max_hoehe (Anteil der
    Blendenhöhe, Vorgabe 0,88), breite_mm, versatz (Anteil der Blendenhöhe nach unten). Die Breite folgt dem echten
    Maß entlang der Blende; passt das Schild dann nicht in die Höhe, wird es als Ganzes kleiner."""
    a = eintrag["schild_auto"]
    b_mm, h_mm = eintrag["mm"]
    H = homographie([[0, 0], [b_mm, 0], [b_mm, h_mm], [0, h_mm]], eintrag["flaeche"])
    us = np.linspace(0, b_mm, 2001)
    xs = cv2.perspectiveTransform(np.float32([[[u, h_mm / 2] for u in us]]), H)[0][:, 0]
    uc = float(us[np.argmin(np.abs(xs - a["mitte_x"]))])
    p = cv2.perspectiveTransform(np.float32([[[uc, 0], [uc, h_mm], [uc - 10, h_mm / 2], [uc + 10, h_mm / 2]]]), H)[0]
    h_px = np.linalg.norm(p[1] - p[0])
    s_u = np.linalg.norm(p[3] - p[2]) / 20
    breite_mm = a.get("breite_mm", breite_mm)
    hoehe_px = breite_mm * s_u / a.get("aspekt", 2.0)
    grenze = a.get("max_hoehe", 0.88) * h_px
    if a.get("stauchen"):
        # geneigte Fläche (Haube): Breite wie am Produkt, Höhe auf das Band begrenzt, also perspektivisch gestaucht
        v_span = min(hoehe_px, grenze) / h_px * h_mm
    else:
        k = min(1.0, grenze / hoehe_px)
        breite_mm *= k
        v_span = hoehe_px * k / h_px * h_mm
    v0 = (h_mm - v_span) / 2 + a.get("versatz", 0.0) * h_mm
    return [uc - breite_mm / 2, v0, uc + breite_mm / 2, v0 + v_span]


def schild_einsetzen(bild, eintrag, schild_rgba, rng, schwarz_schild=(16, 15, 16)):
    """Schild in bild (float64 RGB 0..255, wird verändert) einsetzen; gibt die vier Ecken im Bild zurück.

    Das Schild wird mit vierfacher Überabtastung verzerrt (scharfe, saubere Kanten auch bei 20 Pixel Höhe). Seine
    Farben werden linear über das Schwarz der Fläche gelegt: Grund = Median eines Rings um das Schild, Rot und Weiß
    mit gain und dem Farbstich der Umgebung, danach leicht weichgezeichnet und mit Korn wie das Bild."""
    flaeche = np.float64(eintrag["flaeche"])
    b_mm, h_mm = eintrag["mm"]
    u0, v0, u1, v1 = eintrag["schild"]
    H_flaeche = homographie([[0, 0], [b_mm, 0], [b_mm, h_mm], [0, h_mm]], flaeche)
    sh, sw = schild_rgba.shape[:2]
    S = homographie([[0, 0], [sw, 0], [sw, sh], [0, sh]], [[u0, v0], [u1, v0], [u1, v1], [u0, v1]])
    H = H_flaeche @ S
    ecken = cv2.perspectiveTransform(np.float32([[[0, 0], [sw, 0], [sw, sh], [0, sh]]]), H)[0]
    x0, y0 = np.floor(ecken.min(0)).astype(int) - 3
    x1, y1 = np.ceil(ecken.max(0)).astype(int) + 3
    T = np.array([[UEBER, 0, -x0 * UEBER], [0, UEBER, -y0 * UEBER], [0, 0, 1]], dtype=np.float64)
    gross = cv2.warpPerspective(schild_rgba, T @ H, ((x1 - x0) * UEBER, (y1 - y0) * UEBER),
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    klein = cv2.resize(gross, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA).astype(np.float64)
    alpha = klein[..., 3:4] / 255.0
    rgb = np.where(alpha > 1e-3, klein[..., :3] / np.maximum(alpha, 1e-3), 0)

    maske = np.zeros(bild.shape[:2], np.uint8)
    cv2.fillConvexPoly(maske, np.int32(np.round(ecken)), 255)
    ring = cv2.dilate(maske, np.ones((2 * eintrag.get("ring", 9) + 1,) * 2, np.uint8)) & ~cv2.dilate(maske, np.ones((5, 5), np.uint8))
    schwarz_lokal = np.median(bild[ring > 0], axis=0)
    farbstich = schwarz_lokal / max(schwarz_lokal.mean(), 1.0)
    farbstich = np.clip(1 + (farbstich - 1) * eintrag.get("stich", 1.0), 0.8, 1.2)
    if eintrag.get("grund") == "eigen":
        # Schild auf heller Fläche (Edelstahl): eigene Farben, nur Belichtung und Lichtfarbe der Umgebung
        lin = linear(rgb) * eintrag.get("belichtung", 0.85) * farbstich
    else:
        lin = linear(schwarz_lokal) + (linear(rgb) - linear(schwarz_schild)) * eintrag.get("gain", 0.7) * farbstich
    neu = cv2.GaussianBlur(srgb(lin), (0, 0), eintrag.get("weich", 0.55))
    neu += rng.normal(0, eintrag.get("korn", 1.4), neu.shape)
    alpha = cv2.GaussianBlur(alpha[..., 0], (0, 0), 0.35)[..., None]
    bild[y0:y1, x0:x1] = bild[y0:y1, x0:x1] * (1 - alpha) + neu * alpha
    return ecken


def retusche(bild, eintrag):
    """Kleinstschrift entfernen (bild float64 RGB, wird verändert). poly: Polygon in Bildpunkten.
    art "kopie": aus einem um versatz [dx, dy] verschobenen sauberen Nachbarbereich derselben Fläche kopieren (erhält
    Struktur wie gebürsteten Edelstahl; dy der Neigung der Kante folgen lassen). art "inpaint" (Vorgabe): ausbessern
    nach Telea mit radius, für kleine Stellen auf ruhigen Flächen."""
    maske = np.zeros(bild.shape[:2], np.uint8)
    cv2.fillPoly(maske, [np.int32(eintrag["poly"])], 255)
    if eintrag.get("art", "inpaint") == "kopie":
        dx, dy = eintrag["versatz"]
        quelle = np.roll(np.roll(bild, -dy, axis=0), -dx, axis=1)
        weich = cv2.GaussianBlur(maske.astype(np.float64) / 255.0, (0, 0), eintrag.get("rand", 1.5))[..., None]
        bild[:] = bild * (1 - weich) + quelle * weich
    else:
        b8 = np.clip(bild, 0, 255).astype(np.uint8)
        aus = cv2.inpaint(b8, maske, eintrag.get("radius", 4), cv2.INPAINT_TELEA).astype(np.float64)
        weich = cv2.GaussianBlur(cv2.dilate(maske, np.ones((3, 3), np.uint8)).astype(np.float64) / 255.0, (0, 0), 1.0)[..., None]
        bild[:] = bild * (1 - weich) + aus * weich
