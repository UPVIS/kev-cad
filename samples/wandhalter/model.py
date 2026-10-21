"""Wandhalter für ein Rohr Ø 42,4 mm aus 5-mm-Alublech mit zwei M6-Löchern.

Alle Maße in mm, Z nach oben, die Wand liegt in der Ebene y = 0. Parameter stehen oben, jedes Teil wird mit show()
und sprechendem Namen gezeigt; "/" im Namen bildet den Baum.
"""

from build123d import *
from kevcad import param, show, step

rohr_d = param("rohr_d", 42.4)  # Außendurchmesser des Rohrs
blech = param("blech", 5)  # Blechdicke
breite = param("breite", 60)  # Breite der Grundplatte
hoehe = param("hoehe", 120)  # Höhe der Grundplatte
abstand = param("abstand", 70)  # Wand bis Rohrmitte
loch = param("loch", 6.6)  # Durchgangsloch für M6
lochabstand = param("lochabstand", 80)  # Abstand der beiden Löcher
schelle = param("schelle", 30)  # Höhe der Rohrschelle

step("Grundplatte")
platte = Box(breite, blech, hoehe, align=(Align.CENTER, Align.MIN, Align.CENTER))
show(platte, "Halter/Grundplatte", color="#B8BEC4", material="aluminium")

step("Bohrungen")
for z in (-lochabstand / 2, lochabstand / 2):
    platte -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(loch / 2, 3 * blech)
show(platte, "Halter/Grundplatte", color="#B8BEC4", material="aluminium")  # gleicher Name: ersetzt das Teil

step("Lasche mit Schelle")
ring_r = rohr_d / 2 + blech
arm = abstand - ring_r + blech
lasche = Pos(0, blech + arm / 2, 0) * Box(breite * 0.6, arm, blech)
lasche += Pos(0, abstand, 0) * Cylinder(ring_r, schelle)
lasche -= Pos(0, abstand, 0) * Cylinder(rohr_d / 2, schelle + 2)
show(lasche, "Halter/Lasche", color="#9FB4C7", material="aluminium")

step("Rohr")
rohr = Pos(0, abstand, 0) * (Cylinder(rohr_d / 2, 300) - Cylinder(rohr_d / 2 - 2.6, 300))
show(rohr, "Rohr", color="#8A949C", material="edelstahl")
