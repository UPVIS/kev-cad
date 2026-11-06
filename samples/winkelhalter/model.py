# Winkelhalter aus PETG auf einer Platte: Beispiel für Lastfälle, Simulation und den Selbsttest KEVCAD_SELFTEST=simulation.
from build123d import *
from kevcad import befestigt, lager, show
import kevcad.statik as st

show(Pos(0, 0, -5) * Box(120, 90, 10), "Kulisse/Platte", kulisse=True)
for i, (x, y) in enumerate([(-30, -15), (30, -15), (-30, 15), (30, 15)]):
    show(Pos(x, y, -2) * Cylinder(2.75, 14, align=(Align.CENTER, Align.CENTER, Align.MIN)), f"Kulisse/Schraube {i + 1}",
         kulisse=True)

basis = Box(80, 50, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
steg = Pos(0, -20, 0) * Box(40, 10, 60, align=(Align.CENTER, Align.CENTER, Align.MIN))
form = basis + steg
for x in (-30, 30):
    for y in (-15, 15):
        form = form - Pos(x, y, 0) * Cylinder(2.75, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
form = form - Pos(0, -20, 48) * Rot(90, 0, 0) * Cylinder(6, 40)

halter = lager.druckteil(form, "Halter", material="petg", ausrichtung="-z", zweck="tragend")
show(halter, "Halter")
befestigt("Halter", grund="mit vier Schrauben auf die Platte geschraubt")

st.szenario("Bolzen 50 N")
st.last("Halter", kraft=(0, 15, 50), punkt=(0, -20, 48))
