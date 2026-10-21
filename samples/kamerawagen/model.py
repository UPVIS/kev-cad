"""Kamerawagen: Sony FX6 mit Sigma 35 mm T1,5 auf der Tilta-Baseplate, auf einem Rollwagen vor einem Bowlingball,
dazu eine zweite Kamera für die Totale. Beispiel für Kameras in Kev CAD (Phase 5).

- Kameras kommen aus dem Katalog (kamera_katalog): lager.kamera(kamera, objektiv=…, format=…, blende=…, fokus=…).
- Die FX6 hängt mit ihrem 1/4"-Gewinde auf der Baseplate und folgt dem Wagendeckel (an(..., lokal=True)): wird der
  Wagen verschoben (param wagen_x), wandert die Kamera mit.
- fx6.koerper() zeigt Gehäuse und Objektiv aus den Katalogmaßen und steht als Inventar in der Stückliste.
- In der App: Taste 0 schaut durch die gewählte Kamera, Strg+Alt+0 schlägt die aktuelle Ansicht als neue Lage vor.

Wagen und Ball sind vereinfachte Nachbauten (Inventar-Regel in kevcad.json aus). Maße in mm, Z oben, Fahrtrichtung +X.
"""

from build123d import *
from kevcad import lager, param, show, step

wagen_x = param("wagen_x", 0)  # Lage des Wagens entlang X
wagen_h = param("wagen_h", 150)  # Oberkante Rahmen
kamera_ball = param("kamera_ball", 200)  # Wagenvorderkante bis Ballrückseite
brennweite = param("brennweite", 35)  # nur für das Zoom der zweiten Kamera
fokus_ball = param("fokus_ball", 1)  # 1 = FX6 fokussiert auf den Ball, 0 = unendlich

boden = (Align.CENTER, Align.CENTER, Align.MIN)

step("Rollwagen")
rahmen = Pos(wagen_x, 0, 100) * Box(610, 410, wagen_h - 100, align=boden)
show(rahmen, "Rollwagen/Rahmen", color="#2F6DB5")
for i, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
    rolle = Pos(wagen_x + sx * 240, sy * 140, 50) * Rot(90, 0, 0) * Cylinder(50, 32)
    show(rolle, f"Rollwagen/Rolle {i + 1}", color="#8A8F96")
deckel = Pos(wagen_x, 0, wagen_h) * Box(600, 400, 20, align=boden)
show(deckel, "Rollwagen/Deckel", color="#8C9196")

step("Bowlingball")
r_ball = 108.5
ball_x = wagen_x + 610 / 2 + kamera_ball + r_ball
show(Pos(ball_x, 0, r_ball) * Sphere(r_ball), "Bowlingball", color="#5B2A86")

step("Kamera FX6")
fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", blende=2.8, name="FX6")
# Baseplate-Platzhalter ist 20 mm hoch: das 1/4"-Gewinde der FX6 sitzt 20 mm über dem Deckel (Deckel 20 mm dick)
fx6.an("Rollwagen/Deckel", punkt=(150, 0, 20 + 20), richtung=(1, 0, 0), bezug="stativ_1_4", lokal=True)
if fokus_ball:
    fx6.einstellen(fokus=ball_x - r_ball - fx6.position[0])  # Fokus auf die Ballrückseite (ab Sensorebene)
else:
    fx6.einstellen(fokus="unendlich")
show(fx6.koerper(), "Kamera FX6")
platte = lager.kamerazubehoer("tilta-es-t20-qrbp")
show(platte.verbauen("Rig/Baseplate", an=fx6.bezugspunkt("stativ_1_4"), bezug="kamera_1_4"), "Rig/Baseplate")
for seite in ("links", "rechts"):
    stange = lager.kamerazubehoer("lws-stange-15x150")
    show(stange.verbauen(f"Rig/Stange {seite}", an=platte.bezugspunkt(f"lws_{seite}"), bezug="hinten"),
         f"Rig/Stange {seite}")

step("Totale")
totale = lager.kamera("sony-fx6", objektiv="sony-fe-24-105-f4-g-oss", brennweite=brennweite, format="dci",
                      blende=5.6, name="Totale")
totale.setzen((wagen_x - 1400, -1600, 1500), blick_auf=(ball_x - 300, 0, 200))
