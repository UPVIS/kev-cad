"""Gestell 800 × 600 × 900 aus Vierkantrohr 40 × 40 × 3: vier Beine, oben ein Rahmen mit 45°-Gehrung, darauf ein
Deckel aus 18-mm-Multiplex, mit acht Zylinderschrauben M8 von unten durch den Rahmen in den Deckel geschraubt.

Lagerteile kommen aus dem Katalog: lager.teil(...) sucht sie, verbauen(...) schneidet zu und meldet die
Stücklistenzeile an. Der Name in show() ist derselbe wie in verbauen(), damit die Stückliste das gezeigte Teil kennt.
Längen sind Zuschnittmaße an der längsten Kante. Alle Maße in mm, Z nach oben, Mitte des Gestells im Ursprung.
"""

from build123d import *
from kevcad import lager, param, show, step

breite = param("breite", 800)  # außen, in X
tiefe = param("tiefe", 600)  # außen, in Y
hoehe = param("hoehe", 900)  # bis Oberkante Deckel
schraube_l = param("schraube_l", 50)  # Schaftlänge: Rohrwand 3 + Luft 37 + 10 in den Deckel

rohr = lager.teil("vierkantrohr", a=40, s=3, material="stahl-s235")
platte = lager.teil("platte", s=18, material="multiplex-birke")
schraube = lager.teil("schraube-iso4762-m8")  # ISO 4762 M8, 8.8 verzinkt

a = rohr.masse["a"]  # Kantenlänge des Rohrs
s = platte.masse["s"]  # Deckelstärke
z_rahmen = hoehe - s - a  # Unterkante Rahmen = Länge der Beine
z_mitte = z_rahmen + a / 2

step("Beine")
for lage, x, y in (("vorn links", -1, -1), ("vorn rechts", 1, -1), ("hinten links", -1, 1), ("hinten rechts", 1, 1)):
    name = f"Gestell/Bein {lage}"
    bein = rohr.verbauen(laenge=z_rahmen, name=name)
    show(Pos(x * (breite / 2 - a / 2), y * (tiefe / 2 - a / 2), 0) * bein, name)

step("Rahmen mit Gehrung")
# verbauen liefert die Leiste entlang +Z; bei Gehrung (45, 45) bleibt die Kante bei +Y lang. Erst um die eigene
# Achse drehen (lange Kante nach außen), dann hinlegen, dann an den Platz schieben.
lagen = {
    "hinten": (breite, Pos(-breite / 2, tiefe / 2 - a / 2, z_mitte) * Rot(0, 90, 0)),
    "vorn": (breite, Pos(-breite / 2, -(tiefe / 2 - a / 2), z_mitte) * Rot(0, 90, 0) * Rot(0, 0, 180)),
    "rechts": (tiefe, Pos(breite / 2 - a / 2, -tiefe / 2, z_mitte) * Rot(-90, 0, 0) * Rot(0, 0, -90)),
    "links": (tiefe, Pos(-(breite / 2 - a / 2), -tiefe / 2, z_mitte) * Rot(-90, 0, 0) * Rot(0, 0, 90)),
}
for seite, (laenge, lage) in lagen.items():
    name = f"Gestell/Rahmen {seite}"
    leiste = rohr.verbauen(laenge=laenge, name=name, gehrung=(45, 45))
    show(lage * leiste, name)

step("Deckel")
deckel = platte.verbauen(breite=breite, tiefe=tiefe, name="Deckel")
show(Pos(0, 0, hoehe - s) * deckel, "Deckel")

step("Schrauben")
# Kopf unten am Rahmen, Schaft nach oben (bd_warehouse: Kopf auf z = 0, Schaft nach -Z, daher umdrehen)
punkte = [(x, y * (tiefe / 2 - a / 2)) for y in (-1, 1) for x in (-breite / 4, breite / 4)]
punkte += [(x * (breite / 2 - a / 2), y) for x in (-1, 1) for y in (-tiefe / 4, tiefe / 4)]
for i, (x, y) in enumerate(punkte, 1):
    name = f"Schrauben/M8x{schraube_l:g} {i}"
    sch = schraube.verbauen(laenge=schraube_l, name=name)
    show(Pos(x, y, z_rahmen) * Rot(180, 0, 0) * sch, name)
