"""Drehknopf Ø 60 mm mit Rändel, 3D-Druckteil aus PETG, auf eine Welle Ø 6 mm mit Abflachung.

Dient im Repo auch als Quelle für die Testdateien des Spiegels (mirror-fixtures/): Das Netz des Knopfs ist gepackt
größer als 64 KB und reist deshalb in mehreren Blöcken. Maße in mm, Z nach oben, Knopf steht auf z = 0.
"""

from build123d import *
from kevcad import lager, param, show, step

durchmesser = param("durchmesser", 60)
hoehe = param("hoehe", 18)
rillen = int(param("rillen", 40))
rille_r = param("rille_r", 1.2)
welle = param("welle", 6.2)  # Bohrung für Welle Ø 6 mit etwas Spiel

step("Grundkörper")
knopf = Cylinder(durchmesser / 2, hoehe, align=(Align.CENTER, Align.CENTER, Align.MIN))
knopf = chamfer(knopf.edges().group_by(Axis.Z)[-1], length=2)

step("Rändel")
for i in range(rillen):
    knopf -= Rot(0, 0, i * 360 / rillen) * Pos(durchmesser / 2, 0, 0) * Cylinder(
        rille_r, hoehe * 3, align=(Align.CENTER, Align.CENTER, Align.CENTER))

step("Bohrung mit Abflachung")
bohrung = Cylinder(welle / 2, hoehe - 4, align=(Align.CENTER, Align.CENTER, Align.MIN))
bohrung -= Pos(welle / 2 + 0.5 - 1.0, 0, 0) * Box(1, welle, hoehe * 2, align=(Align.MIN, Align.CENTER, Align.CENTER))
knopf -= bohrung

show(lager.druckteil(knopf, "Drehknopf", material="petg"), "Drehknopf")
