"""Wandhalter für ein Rohr Ø 42,4 mm: Grundplatte und Lasche aus Flachstahl 40 × 5, Schelle als 3D-Druckteil aus
PETG, zwei Löcher für M6.

Alle Teile kommen aus dem Inventar (Inventar-Regel): Lagerteile mit lager.teil(...).verbauen(...), die Schelle mit
lager.druckteil(...). Maße in mm, Z nach oben, die Wand liegt in der Ebene y = 0. Parameter stehen oben; jedes Teil
wird mit show() unter demselben Namen wie in verbauen() gezeigt, "/" im Namen bildet den Baum.
"""

from build123d import *
from kevcad import lager, param, show, step

hoehe = param("hoehe", 120)  # Länge der Grundplatte
abstand = param("abstand", 70)  # Wand bis Rohrmitte
loch = param("loch", 6.6)  # Durchgangsloch für M6
lochabstand = param("lochabstand", 80)  # Abstand der beiden Löcher
schelle_h = param("schelle_h", 30)  # Höhe der Schelle
wand = param("wand", 4)  # Wandstärke der Schelle

flach = lager.teil("flach", b=40, s=5, material="stahl-s235")  # Lagerteile: erst stock_search, dann lager.teil
rohr = lager.teil("rohr-en10220-42.4x2.0")
breite, blech = flach.masse["b"], flach.masse["s"]
rohr_d = rohr.masse["d"]

step("Grundplatte")
platte = flach.verbauen(laenge=hoehe, name="Halter/Grundplatte")  # entlang +Z, Breite in X, Dicke in Y
platte = Pos(0, blech / 2, -hoehe / 2) * platte
show(platte, "Halter/Grundplatte")

step("Bohrungen")
for z in (-lochabstand / 2, lochabstand / 2):
    platte -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(loch / 2, 3 * blech)
show(platte, "Halter/Grundplatte")  # gleicher Name: ersetzt das Teil, die Stückliste bleibt beim Lagerteil

step("Lasche")
ring_r = rohr_d / 2 + wand
arm = abstand - ring_r - blech  # von der Platte bis an die Schelle
lasche = flach.verbauen(laenge=arm, name="Halter/Lasche")
show(Pos(0, blech, 0) * Rot(-90, 0, 0) * lasche, "Halter/Lasche")  # waagerecht, von der Wand weg

step("Schelle")
ring = Pos(0, abstand, 0) * (Cylinder(ring_r, schelle_h) - Cylinder(rohr_d / 2, schelle_h + 2))
schelle = lager.druckteil(ring, "Halter/Schelle", material="petg")
show(schelle, "Halter/Schelle")

step("Rohr")
stueck = rohr.verbauen(laenge=300, name="Rohr")
show(Pos(0, abstand, -150) * stueck, "Rohr")
