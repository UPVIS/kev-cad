"""Focusrite Scarlett 2i2 (4. Generation) als Messmodell, Nachbau aus Kevins Video IMG_5186.MOV (Phase 4).

Entspricht fotomess/src/fotomess/modelle/scarlett.py, als model.py für Kev CAD: Maße als param(), Teile mit show().
Hersteller 180 × 117 × 47,5 mm (Breite × Tiefe × Höhe); ob Tiefe und Höhe Knöpfe und Füße einschließen, ist offen.
Das Modell trennt deshalb das Gehäuse von den Überständen:

- Gehäuse: rotes Aluminiumrohr entlang der Tiefe (Y), Querschnitt mit gerundeten Ecken (kanten_r); vorn und hinten je
  eine schwarze Blende um blende_t vertieft, mit rotem Rand (rand) darum.
- Vorn (−Y): zwei Gain-Knöpfe und der Kopfhörerknopf (Überstand knopf_h), der große Output-Knopf (gross_h), die
  Kopfhörerbuchse (fest). Die Knöpfe sitzen auf der Blende auf (berühren, keine Durchdringung).
- Unten vier Gummifüße (fuss_h, aus dem Video nicht messbar: die Unterseite ist nie zu sehen).

Koordinaten: Auflage z = 0 (Unterseite der Füße), Gehäusemitte x = y = 0, Breite entlang X, Knöpfe vorn (−Y).
Nachbau ohne Lagerteile: Inventar-Regel in kevcad.json aus.

Vermessen (MCP referenz_vermessen) mit dem Messmodell unten: rotes Gehäuse als Farbteil, vorn und hinten als
Zwillingslage, Masken aus Rot und Apple Vision ohne die Holzscheibe.
"""

from build123d import *
from kevcad import param, show, step

breite = param("breite", 180.0)  # Hersteller, Maßstab (das Rohr hat seitlich keine Anbauten)
tiefe = param("tiefe", 110.0)  # Gehäusetiefe ohne Knöpfe
hoehe = param("hoehe", 46.0)  # Gehäusehöhe ohne Füße
kanten_r = param("kanten_r", 5.0)  # Radius der vier Kanten entlang der Tiefe
knopf_h = param("knopf_h", 12.0)  # Überstand Gain-Knöpfe und Kopfhörerknopf vor der Gehäusevorderkante
gross_h = param("gross_h", 12.0)  # Überstand großer Output-Knopf
fuss_h = param("fuss_h", 1.5)  # Gummifüße (nicht messbar)
rand = param("rand", 3.0)  # roter Rand um die Blenden (Wandstärke des Rohrs)
blende_t = param("blende_t", 0.5)  # Blende gegenüber der Rohrkante vertieft
buchse_h = param("buchse_h", 10.0)  # Überstand Kopfhörerbuchse

ROT = "#B3121D"
SCHWARZ = "#1C1C1E"

# (Name, x relativ zur halben Breite, z relativ zur Gehäusehöhe, Durchmesser, Überstand)
KNOEPFE = (
    ("Knopf Gain 1", -0.794, 0.67, 12.5, knopf_h),
    ("Knopf Gain 2", -0.528, 0.67, 12.5, knopf_h),
    ("Knopf Output", 0.300, 0.52, 25.0, gross_h),
    ("Knopf Kopfhoerer", 0.806, 0.80, 11.0, knopf_h),
    ("Buchse Kopfhoerer", 0.806, 0.40, 9.0, buchse_h),
)
FUSS_D, FUSS_RAND_X, FUSS_RAND_Y = 10.0, 18.0, 15.0


def rohr(b, t, h, r):
    """Quader b × t × h (Mitte im Ursprung) mit gerundeten Kanten entlang Y."""
    k = Box(b, t, h)
    if r > 0.05:
        k = fillet(k.edges().filter_by(Axis.Y), radius=min(r, b / 2 - 0.1, h / 2 - 0.1))
    return k


step("Gehäuse")
z0 = fuss_h
zm = z0 + hoehe / 2
gehaeuse = Pos(0, 0, zm) * rohr(breite, tiefe, hoehe, kanten_r)
bi, hi, ri = breite - 2 * rand, hoehe - 2 * rand, max(kanten_r - rand, 0.3)
for sy in (-1, 1):
    gehaeuse -= Pos(0, sy * tiefe / 2, zm) * rohr(bi, 2 * blende_t, hi, ri)
show(gehaeuse, "Scarlett/Gehaeuse", color=ROT, material="aluminium")

step("Knöpfe")
vorn = -tiefe / 2 + blende_t  # Blendenfläche vorn
for name, fx, fz, d, ueber in KNOEPFE:
    laenge = ueber + blende_t  # von der Blende bis vor die Gehäusevorderkante
    knopf = Pos(fx * breite / 2, vorn - laenge / 2, z0 + fz * hoehe) * Rot(90, 0, 0) * Cylinder(d / 2, laenge)
    show(knopf, f"Scarlett/{name}", color="#C9A227" if name.startswith("Buchse") else SCHWARZ)

step("Füße")
for i, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
    fuss = Pos(sx * (breite / 2 - FUSS_RAND_X), sy * (tiefe / 2 - FUSS_RAND_Y), 0) * \
        Cylinder(FUSS_D / 2, z0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    show(fuss, f"Scarlett/Fuss {i + 1}", color=SCHWARZ)


def messmodell(p):
    """Angaben für referenz_vermessen (fotomess): Farbteile, Zwillingslagen, Masken, Vorgaben und Grenzen."""
    halb = p["tiefe"] / 2

    def rot(teil, flaeche):
        # rotes Aluminium: das Gehäuse ohne die vertieften schwarzen Blenden (Fläche quer zu Y hinter der Rohrkante)
        if teil != "Scarlett/Gehaeuse":
            return False
        try:
            n = flaeche.normal_at()
        except Exception:  # gekrümmte Fläche (Rundung): rot
            return True
        return not (abs(n.Y) > 0.9 and abs(flaeche.center().Y) < halb - 0.5 * p["blende_t"])

    return dict(
        farbteile=rot,
        zwillinge=["z180"],  # vorn und hinten sehen gleich aus, nur die Knöpfe unterscheiden sie
        maske=dict(maske="vision+farbe", farbe_hsv=[[168, 4], 70, 25], ausschluss_hsv=[[6, 24], 50, 45],
                   gehaeuse=True, umkreis=0.12),
        frei=["tiefe", "hoehe", "kanten_r", "knopf_h", "gross_h"],
        bekannt={"breite": 180.0},
        vorgaben={"tiefe": (110, 25), "hoehe": (46, 10), "kanten_r": (5, 5), "knopf_h": (12, 8), "gross_h": (12, 8)},
        grenzen={"tiefe": (80, 130), "hoehe": (35, 60), "kanten_r": (0.5, 15), "knopf_h": (4, 25),
                 "gross_h": (4, 25)},
        hoehen=[0, 80],  # liegt aufrecht: Grobsuche von flach bis steil von oben
    )
