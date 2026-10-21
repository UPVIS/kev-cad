"""Inventar und Kugelschieber: ein Bowlingball, den eine Vorrichtung vor dem Kamerawagen herschiebt.

Beispiel für Phase 5 (Animation): Kopie von Kevins Projekt „Neues Projekt“ (21.10.2026) mit zwei Animationen am Ende:
„Fahrt“ (Wagen rollt 2 m, Lenkrollen und Stützräder drehen mit, der Ball rollt vor dem Schieber, Kamerafahrt) und
„Verstellen“ (Spannhebel öffnen, Ballschlitten als Schubgelenk mit Grenzen verschieben, wieder klemmen).

Regel: Gebaut wird nur aus dem Inventar plus 3D-Druckteilen. Fehlt etwas, kommt es zuerst ins Inventar.

Inventar
- 4 Rohre: ALFER Art.-Nr. 01023 (EAN 4001116010231), Aluminium, silbern eloxiert, Ø 12 × 1 mm, 1 m lang.
- 2 Schwimmnudeln: Happy People Art.-Nr. 77805 (EAN 4008332778051), PE-Schaum, Ø 70 mm, 1600 mm lang, als Vollzylinder.
- Rollwagen: ALUTEC Art.-Nr. 05200 (EAN 4014688052004) für Eurobehälter 600 × 400, Kunststoff blau, 610 × 410 mm,
  vier Lenkrollen Ø 100 mm, zwei davon mit Feststeller. Aufbau und Maße aus Kevins Video vermessen (Parameter unten).
- Deckel: ALUTEC Art.-Nr. 05090 (EAN 4014688050901), Auflagedeckel für Eurobehälter 600 × 400.
- Bowlingball nach USBC-Maßen.
- Kamera: Sony FX6 (ILME-FX6), vereinfacht nach den Sony-Maßen; Cine-Linse als Platzhalter. Objektiv und V-Mount
  folgen (EAN).
Alle Maße in mm, Z nach oben. Längsachsen entlang X, Schieberichtung +X.
"""

import math

from build123d import *
from kevcad import animation, lager, param, show, step

aussen_d = param("aussen_d", 12)
wand = param("wand", 1)
laenge = param("laenge", 1000)
anzahl = int(param("anzahl", 4))
luecke = param("luecke", 10)  # lichter Abstand zwischen zwei Teilen einer Reihe

nudel_d = param("nudel_d", 70)
nudel_laenge = param("nudel_laenge", 1600)
nudel_anzahl = int(param("nudel_anzahl", 2))
reihen_abstand = param("reihen_abstand", 30)  # lichter Abstand zwischen Rohren und Schwimmnudeln

# Die Rohre liegen nicht mehr lose da: Sie sind im Kugelschieber verbaut; Reste und unbenutzte Rohre liegen
# am alten Lagerplatz (ganz unten).
teilung = aussen_d + luecke

step("Schwimmnudeln")
# PE-Schaum gibt es nicht im Materialkatalog; ohne material bleibt die Masse offen statt falsch
nudel = Rot(0, 90, 0) * Cylinder(nudel_d / 2, nudel_laenge)
rohre_rand = (anzahl - 1) / 2 * teilung + aussen_d / 2
farben = ["#F2C230", "#E8607A", "#4FB0E0", "#6CC070"]
for i in range(nudel_anzahl):
    y = rohre_rand + reihen_abstand + nudel_d / 2 + i * (nudel_d + luecke)
    show(Pos(0, y, nudel_d / 2) * nudel, f"Schwimmnudeln/Schwimmnudel {i + 1}", color=farben[i % len(farben)])

# Rollwagen nach Kevins Video vermessen (21.10.2026, zwei Draufsichten, Kamera aus dem Rechteck 610 × 410).
# Unsicherheit steht am Parameter; „Annahme“ heißt: im Video nicht bestimmbar.
wagen_l = param("wagen_l", 610)  # Hersteller
wagen_b = param("wagen_b", 410)  # Hersteller
rad_d = param("rad_d", 100)  # Hersteller
rad_b = param("rad_b", 32)  # Annahme
rolle_h = param("rolle_h", 120)  # Bauhöhe der Lenkrolle = Unterkante Rahmen, ±6
rahmen_h = param("rahmen_h", 31)  # Unterkante Schürze bis Plattenoberseite, ±7
platte_d = param("platte_d", 4)  # Annahme
wand_d = param("wand_d", 3.5)  # Schürzen und Rippen, Annahme
rand_h = param("rand_h", 19)  # aufgestellter Rand über der Platte, ±2
rand_d = param("rand_d", 5)  # ±2
rand_ende_lang = param("rand_ende_lang", 30)  # Rand endet vor der gedachten Ecke (Längsseite 550 lang), ±4
rand_ende_stirn = param("rand_ende_stirn", 25)  # dasselbe an der Stirnseite (360 lang), ±4
eck_fase = param("eck_fase", 20)  # Außenecken 45° gefast, ±5
oeff_l, oeff_b = param("oeff_l", 493), param("oeff_b", 295)  # achteckige Öffnung, ±6 / ±3
oeff_fase_x, oeff_fase_y = param("oeff_fase_x", 103), param("oeff_fase_y", 101.5)  # Schenkel der Eckschrägen, ±3
schraube_rand = param("schraube_rand", 63)  # Rollenschraube von beiden Außenkanten, ±3
dom_d = param("dom_d", 80)  # Eckdom unter der Platte, geschätzt
nachlauf = param("nachlauf", 26)  # Drehachse bis Radachse, unsicher (±7)
drehkopf_d = param("drehkopf_d", 63)  # ±5
wagen_abstand = param("wagen_abstand", 100)  # lichter Abstand zu den Rohren

boden = (Align.CENTER, Align.CENTER, Align.MIN)
wagen_y = -(rohre_rand + wagen_abstand + wagen_b / 2)
platte_oben = rolle_h + rahmen_h


def achteck(l: float, b: float, fx: float, fy: float) -> Face:
    """Rechteck l × b mit Eckschrägen (Schenkel fx in x, fy in y), Mitte im Ursprung."""
    hx, hy = l / 2, b / 2
    punkte = [(hx - fx, hy), (hx, hy - fy), (hx, -hy + fy), (hx - fx, -hy), (-hx + fx, -hy), (-hx, -hy + fy),
              (-hx, hy - fy), (-hx + fx, hy)]
    return Polygon(*reversed(punkte), align=None)  # gegen den Uhrzeigersinn: Normale +z, extrude geht nach oben


step("Rollwagen: Rahmen")
umriss = achteck(wagen_l, wagen_b, eck_fase, eck_fase)
oeffnung = achteck(oeff_l, oeff_b, oeff_fase_x, oeff_fase_y)
rahmen = Pos(0, 0, platte_oben - platte_d) * extrude(umriss - oeffnung, amount=platte_d)
schuerzen = (umriss - offset(umriss, amount=-wand_d, kind=Kind.INTERSECTION)) + \
            (offset(oeffnung, amount=wand_d, kind=Kind.INTERSECTION) - oeffnung)
rahmen += Pos(0, 0, rolle_h) * extrude(schuerzen, amount=rahmen_h - platte_d + 0.5)
rippe_h = rahmen_h - platte_d + 0.5
rollen_pos = [(sx * (wagen_l / 2 - schraube_rand), sy * (wagen_b / 2 - schraube_rand)) for sx in (1, -1) for sy in (1, -1)]
rippen = []
for x, y in rollen_pos:  # Eckdom mit sternförmigen Rippen (Anzahl und Lage geschätzt)
    sx, sy = math.copysign(1, x), math.copysign(1, y)
    rippen.append(Pos(x, y, rolle_h) * Cylinder(dom_d / 2, rippe_h, align=boden))
    for winkel in (0 if sx > 0 else 180, 90 if sy > 0 else -90,  # zu den Außenschürzen
                   math.degrees(math.atan2(sy, sx)),  # zur Eckfase
                   math.degrees(math.atan2(-sy * oeff_fase_x, -sx * oeff_fase_y))):  # zur Schräge der Öffnung
        rippen.append(Pos(x, y, rolle_h) * Rot(0, 0, winkel) * Pos(100, 0, 0) * Box(200, wand_d, rippe_h, align=boden))
for s in (1, -1):  # Querrippen in den Kanälen (Anzahl geschätzt)
    rippen.append(Pos(s * wagen_l / 2, 0, rolle_h) * Box(200, wand_d, rippe_h, align=boden))
    for x in (-80, 80):
        rippen.append(Pos(x, s * wagen_b / 2, rolle_h) * Box(wand_d, 200, rippe_h, align=boden))
rippen_teil = rippen[0]
for r in rippen[1:]:
    rippen_teil += r
# Rippen enden an den Schürzen: alles auf die Rahmenfläche zwischen Außenkontur und Öffnung begrenzen
rahmen += rippen_teil & (Pos(0, 0, rolle_h) * extrude(umriss - oeffnung, amount=rippe_h))
for x, y in rollen_pos:  # Rückenloch für die Rollenschraube
    rahmen -= Pos(x, y, rolle_h - 1) * Cylinder(6, rahmen_h + 2, align=boden)
for sy in (1, -1):  # aufgestellter Rand, außenbündig, an den Ecken unterbrochen
    rahmen += Pos(0, sy * (wagen_b / 2 - rand_d / 2), platte_oben - 0.5) * \
        Box(wagen_l - 2 * rand_ende_lang, rand_d, rand_h + 0.5, align=boden)
    rahmen += Pos(sy * (wagen_l / 2 - rand_d / 2), 0, platte_oben - 0.5) * \
        Box(rand_d, wagen_b - 2 * rand_ende_stirn, rand_h + 0.5, align=boden)
show(Pos(0, wagen_y, 0) * rahmen, "Rollwagen/Rahmen", color="#2F6DB5", material="polypropylen")

step("Rollwagen: Lenkrollen")
# Lenkrollen mit Rückenloch nach dem Video: verzinkter Drehkopf mit Kugellaufring, gepresste Gabel aus Stahlblech,
# graues Rad mit hellgrauer Felge, Achsschraube mit Muttern, Feststeller an beiden Rollen der hinteren Stirnseite.
# Gemessen: Bauhöhe, Drehkopf, Nachlauf (unsicher). Radbreite, Blechdicke, Gabelform und Pedal sind geschätzt.
# Die Rollen werden festgestellt, alle in Fahrtrichtung x; jede Gabel zeigt zur nächsten Stirnseite.
achse_z = rad_d / 2
blech = 3  # Stahlblech der Gabel, Annahme
gabel_innen = rad_b + 6  # lichte Weite zwischen den Schenkeln, Annahme
kopf_h = 16
krone_z = rolle_h - kopf_h - blech  # Gabelkrone unter dem Drehkopf


def in_xz(punkte: list, dicke: float, y: float) -> Part:
    """Blechteil: Umriss in der x-z-Ebene (Punkte als (x, z)), dicke in y, mittig bei y."""
    t = extrude(Plane.XZ * Polygon(*punkte, align=None), amount=dicke)
    return Pos(0, y - t.bounding_box().center().Y, 0) * t


def quer(r: float, l: float, x: float, y: float, z: float) -> Part:
    """Zylinder mit Achse in y."""
    return Pos(x, y, z) * Rot(90, 0, 0) * Cylinder(r, l)


gabel = Pos(0, 0, rolle_h - 5) * Cylinder(drehkopf_d / 2, 5, align=boden)  # obere Laufplatte am Rahmen
gabel += Pos(0, 0, rolle_h - kopf_h) * Cylinder(drehkopf_d / 2 - 5, kopf_h - 5 + 0.5, align=boden)  # Kugellaufring
gabel += Pos(-nachlauf / 2 - 11, 0, krone_z) * Box(nachlauf + 74, gabel_innen + 2 * blech, blech + 0.5, align=boden)
schenkel = [(24, krone_z + 0.5), (-nachlauf - 24, krone_z + 0.5), (-nachlauf - 17, achse_z), (-nachlauf + 17, achse_z)]
for sy in (1, -1):
    y_s = sy * (gabel_innen + blech) / 2
    gabel += in_xz(schenkel, blech, y_s) + quer(17, blech, -nachlauf, y_s, achse_z)  # Schenkel mit Achsauge
    mutter = extrude(RegularPolygon(radius=9.2, side_count=6), amount=6)
    gabel += Pos(-nachlauf, sy * (gabel_innen / 2 + blech + 3), achse_z) * Rot(90, 0, 0) * Pos(0, 0, -3) * mutter
gabel += quer(5, gabel_innen + 2 * blech + 14, -nachlauf, 0, achse_z)  # Achsschraube
lauf = fillet(Cylinder(rad_d / 2, rad_b).edges(), radius=7) - Cylinder(rad_d / 2 - 13, rad_b + 2)
felge = Cylinder(rad_d / 2 - 13, rad_b - 4) + Cylinder(15, gabel_innen - 1) - Cylinder(5.2, gabel_innen + 2)
rad_lauf = Pos(-nachlauf, 0, achse_z) * Rot(90, 0, 0) * lauf
rad_felge = Pos(-nachlauf, 0, achse_z) * Rot(90, 0, 0) * felge
rad = rad_lauf + rad_felge
feststeller = Pos(-nachlauf - 24 - 18 + 0.5, 0, krone_z) * Box(36, 40, blech, align=boden)  # Pedal hinter der Gabel
feststeller = fillet(feststeller.edges().filter_by(Axis.Z), radius=6)
schraube = Pos(0, 0, rolle_h) * Cylinder(5.5, rahmen_h, align=boden) + Pos(0, 0, platte_oben) * Cylinder(10, 4, align=boden)
rollen_lagen = [Pos(x, wagen_y + y, 0) * Rot(0, 0, 180 if x > 0 else 0) for x, y in rollen_pos]
for i, ((x, y), lage) in enumerate(zip(rollen_pos, rollen_lagen)):
    show(lage * gabel, f"Rollwagen/Lenkrolle {i + 1}/Gabel", color="#C9CDD2", material="stahl")
    show(lage * rad_lauf, f"Rollwagen/Lenkrolle {i + 1}/Rad", color="#8A8F96", material="gummi")
    show(lage * rad_felge, f"Rollwagen/Lenkrolle {i + 1}/Felge", color="#D5D8DC", material="polypropylen")
    show(lage * schraube, f"Rollwagen/Lenkrolle {i + 1}/Schraube", color="#C9CDD2", material="stahl")
    if x < 0:
        show(lage * feststeller, f"Rollwagen/Lenkrolle {i + 1}/Feststeller", color="#C9CDD2", material="stahl")

spiel = param("spiel", 0.2)  # Luft zwischen Druckteilen und den Teilen, an denen sie anliegen


def aussparen(teil: Part, koerper: Part, luft: float) -> Part:
    """teil ohne koerper, rundum um luft größer ausgespart (koerper in ±x, ±y, ±z verschoben abgezogen): Druckteile
    liegen so nirgends deckungsgleich auf und lassen sich aufschieben."""
    bb = teil.bounding_box()
    lokal = koerper & Pos(bb.center()) * Box(bb.size.X + 4, bb.size.Y + 4, bb.size.Z + 4)
    if lokal.volume < 1e-6:
        return teil
    for v in ((0, 0, 0), (luft, 0, 0), (-luft, 0, 0), (0, luft, 0), (0, -luft, 0), (0, 0, luft), (0, 0, -luft)):
        teil -= Pos(*v) * lokal
    return teil


step("Rollwagen: Lenksperren")
# Lenksperre (Druck): sitzt auf dem äußeren Ende der Gabelkrone, umgreift Krone und Schenkel seitlich und steckt oben
# in der Rippe vom Eckdom zur Stirnseite. Krone, Schenkel, Drehkopf und Rippe sind ausgespart (formschlüssig), die
# Gabel kann sich nicht mehr drehen. Einbau (geprüft in der Montageprüfung): Lenkrolle abschrauben (vorhandene
# Schraube), Sperre waagerecht von außen über das Kronenende bis an den Drehkopf schieben, Rolle samt Sperre senkrecht
# von unten einsetzen (Rippe und Dom gleiten in die senkrechten Aussparungen), Schraube wieder anziehen.
sperre_h = param("sperre_h", 18)  # so tief greift die Sperre in Rippe und Dom
x_a, x_b = -nachlauf - 22 - 6, -drehkopf_d / 2 - 0.5  # vom Kronenende bis an den Drehkopf
breite_kopf = gabel_innen + 2 * blech
sperre = Pos((x_a + x_b) / 2, 0, krone_z + blech) * Box(x_b - x_a, breite_kopf + 6, rolle_h + sperre_h - krone_z - blech,
                                                         align=boden)
for sy in (1, -1):  # Wangen seitlich an Krone und Schenkeln
    sperre += Pos((x_a + x_b) / 2, sy * (breite_kopf / 2 + 1.5), krone_z - 3) * Box(x_b - x_a, 3, blech + 3.5, align=boden)
lenksperren, sperr_griff = [], []
for lage in rollen_lagen:
    s_welt = lage * sperre
    sperr_griff.append(round((s_welt & (Pos(0, wagen_y, 0) * rahmen)).volume))
    lenksperren.append(aussparen(aussparen(s_welt, Pos(0, wagen_y, 0) * rahmen, spiel), lage * gabel, spiel))
if min(sperr_griff) <= 0:
    raise ValueError("Eine Lenksperre greift nicht in den Rahmen")
for i, s_teil in enumerate(lenksperren):
    show(s_teil, f"Rollwagen/Lenkrolle {i + 1}/Lenksperre (Druck)", color="#F28C28", material="petg")

# Bowlingball nach USBC: Durchmesser 215,9 bis 218,3 mm, höchstens 16 lb (7,26 kg). Kein Herstellermodell verfügbar.
# Masse über PMMA (1,18 g/cm³): ergibt rund 6,3 kg, also einen üblichen 14-lb-Ball. Kern nicht modelliert.
ball_d = param("ball_d", 217)
daumen_d = param("daumen_d", 25)  # Daumenloch, üblich etwa 1 Zoll
finger_d = param("finger_d", 20)  # Fingerlöcher, üblich etwa 3/4 bis 13/16 Zoll
daumen_tiefe = param("daumen_tiefe", 65)
finger_tiefe = param("finger_tiefe", 55)
spanne = param("spanne", 105)  # Bogenlänge Mitte Daumen bis Mitte Fingerpaar
steg_finger = param("steg_finger", 6)  # Brücke zwischen den Fingerlöchern, etwa 1/4 Zoll

step("Bowlingball")
r_ball = ball_d / 2
ball = Sphere(r_ball)


def loch(d: float, tiefe: float, bogen_y: float, bogen_x: float = 0) -> Part:
    """Bohrung radial zur Ballmitte, Lage als Bogenlänge auf der Oberfläche ab dem Pol (+Z)."""
    bohrer = Pos(0, 0, r_ball + 5) * Cylinder(d / 2, tiefe + 5, align=(Align.CENTER, Align.CENTER, Align.MAX))
    return Rot(-math.degrees(bogen_y / r_ball), math.degrees(bogen_x / r_ball), 0) * bohrer


ball -= loch(daumen_d, daumen_tiefe, -spanne / 2)
for seite in (1, -1):
    ball -= loch(finger_d, finger_tiefe, spanne / 2, seite * (finger_d + steg_finger) / 2)

# Deckel: ALUTEC Art.-Nr. 05090 (EAN 4014688050901), Auflagedeckel für Eurobehälter 600 × 400, Polypropylen grau.
# Belegt ist nur das Außenmaß 600 × 400 (ALUTEC-Prospekt); Höhe, Wand und Zentrierrand sind angenommen.
# Er liegt auf dem Rollwagen, innerhalb dessen Führungsrand.
deckel_h = param("deckel_h", 20)  # Annahme
deckel_wand = param("deckel_wand", 2.5)  # Annahme
deckel_platte = param("deckel_platte", 3)  # Annahme
zentrier_einzug = param("zentrier_einzug", 12)  # Abstand des Zentrierrands vom Außenrand, Annahme

step("Deckel")
deckel = Box(600, 400, deckel_h, align=boden)
deckel = fillet(deckel.edges().filter_by(Axis.Z), radius=8)
deckel -= Pos(0, 0, -1) * Box(600 - 2 * deckel_wand, 400 - 2 * deckel_wand, deckel_h - deckel_platte + 1, align=boden)
zi_l, zi_b = 600 - 2 * zentrier_einzug, 400 - 2 * zentrier_einzug
zentrierrand = Box(zi_l, zi_b, 8.5, align=boden) - Pos(0, 0, -1) * Box(zi_l - 4, zi_b - 4, 10.5, align=boden)
deckel += Pos(0, 0, deckel_h - deckel_platte - 8) * zentrierrand  # greift in den Behälterrand
show(Pos(0, wagen_y, rolle_h + rahmen_h) * deckel, "Deckel 05090", color="#8C9196", material="polypropylen")

# Kugelschieber: schiebt den Bowlingball vor dem Kamerawagen her (Vorbild: Bowling-Ball-Rig von @newyorkkeygrip).
# Nur aus den vier ALFER-Rohren (ungekürzt oder abgelängt, nie verlängert) und 3D-Druckteilen, ohne Schrauben.
# - Zwei Seitenstangen tragen sich selbst: Sie stecken in vier Stangenhaltern unter dem Wagen, gleiten darin, lassen
#   sich herausziehen und werden mit Exzenter-Spannhebeln festgestellt (stangen_vorschub: wie weit sie vorstehen).
#   Die Halter werden von unten auf die schrägen Innenschürzen der Öffnung gesteckt und sitzen formschlüssig.
# - Der Ball berührt nur zwei Laufrollen: hinten die Schieberolle, vorn die Fangrolle. Ihre Achsen liegen quer, so
#   rollen sie mit der Balloberfläche ab; die leichte Einschnürung hält den Ball mittig.
# - Jede Rolle sitzt auf einer eigenen Querstange mit zwei Schlitten, die auf den Seitenstangen gleiten und mit
#   Spannhebeln klemmen: hinten stellt den Abstand Ball–Kamera ein (kamera_ball), vorn das Spiel (vorn_luft).
# Lage im Wagen-System: x entlang der Wagenlänge (Schieberichtung +x), y quer, z nach oben.
rig_versatz = param("rig_versatz", 0)  # quer verschieben; 0 = am Wagen
kamera_ball = param("kamera_ball", 200)  # Wagenvorderkante (etwa Objektiv) bis Ballrückseite: Lage der Schieberolle
vorn_luft = param("vorn_luft", 4)  # Spiel zwischen Ball und Fangrolle: Lage der Fangrolle
stangen_vorschub = param("stangen_vorschub", 440)  # Seitenstangen ragen so weit vor die Wagenvorderkante
rollen_luft = param("rollen_luft", 2)  # Stangen und Halter zu Rad und Gabel der Lenkrollen
ball_luft = param("ball_luft", 5)  # Seitenstange zum Ball
boden_min = param("boden_min", 4)  # kleinster Abstand aller Teile zum Boden
stangen_z_wunsch = param("stangen_z", 40)  # Achshöhe der Seitenstangen; begrenzt durch den Ball
laufrolle_l = param("laufrolle_l", 100)  # Länge der Laufrollen
laufrolle_r = param("laufrolle_r", 12)  # kleinster Radius der Laufrollen (Mitte der Einschnürung)
einschnuerung_r = param("einschnuerung_r", 2 * r_ball)  # Krümmung der Einschnürung, größer = flacher
schieber_luft = param("schieber_luft", 0.5)  # Schieberolle zum Ball
klemme_h = param("klemme_h", 18)  # so hoch umgreift der Stangenhalter Schürze und Rippe
saege = 2  # Schnittbreite beim Ablängen

step("Kugelschieber: Lage")
# Festgestellte Lenkrollen: unten nur das Rad im Weg der Stangen, oben Gabel und Drehkopf im Weg der Halter
rolle_y = min(abs(y) for _, y in rollen_pos)
rad_halb = rad.bounding_box().max.Y
gabel_halb = max(gabel.bounding_box().max.Y, feststeller.bounding_box().max.Y)
ys = min(rolle_y - rad_halb - rollen_luft - aussen_d / 2,  # Stange neben dem Rad
         rolle_y - gabel_halb - rollen_luft - 13)  # Halter (26 breit) neben Gabel und Drehkopf
abstand_ball = r_ball + aussen_d / 2 + ball_luft
z_max = r_ball - math.sqrt(abstand_ball ** 2 - ys ** 2) if ys < abstand_ball else 2 * r_ball
stangen_z = min(z_max, stangen_z_wunsch)
if stangen_z - aussen_d / 2 < boden_min:
    raise ValueError(f"Stangen passen nicht: bei {ys:.1f} mm Achsabstand müssten sie auf {stangen_z:.1f} mm Höhe, "
                     f"die Unterkante läge {stangen_z - aussen_d / 2:.1f} mm über dem Boden (mindestens {boden_min})")
bohr = aussen_d / 2 + 0.15  # Rohre stecken mit Spiel in den Druckteilen
gleit = aussen_d / 2 + 0.3  # Halter und Schlitten gleiten auf den Seitenstangen
lauf = aussen_d / 2 + 0.25  # Laufrollen drehen auf der Querstange
rahmen_unten = rolle_h  # Unterkante des Wagenrahmens


def rohr(l: float, achse: str) -> Part:
    """ALFER-Rohr der Länge l, mittig um den Ursprung, Achse 'x' oder 'y'."""
    r = Cylinder(aussen_d / 2, l) - Cylinder(aussen_d / 2 - wand, l + 2)
    return Rot(0, 90, 0) * r if achse == "x" else Rot(90, 0, 0) * r


def schraege_x(y: float) -> float:
    """x der Öffnungsschräge (Seite +x) in der Höhe y."""
    return oeff_l / 2 - oeff_fase_x + (oeff_b / 2 - abs(y)) / oeff_fase_y * oeff_fase_x


linie = 0.42  # Linienbreite der 0,4-mm-Düse (Bambu Lab P1P): Wände in Vielfachen davon


def tropfen(r: float, l: float, achse: str) -> Part:
    """Waagerechte Bohrung als Tropfen (Spitze nach oben, 45°): druckt ohne Stützen. Mittig, Achse 'x' oder 'y'."""
    profil = Circle(r) + Polygon((-r * 0.7071, r * 0.7071), (r * 0.7071, r * 0.7071), (0, r * 1.4142), align=None)
    t = extrude((Plane.YZ if achse == "x" else Plane.XZ) * profil, amount=l)
    m = t.bounding_box().center()  # nur längs der Achse mittig: der Kreis bleibt auf der Achse
    return Pos(-m.X, 0, 0) * t if achse == "x" else Pos(0, -m.Y, 0) * t


def exzenterklemme(nah: float, fern: float, l: float) -> tuple[Part, dict]:
    """Exzenter-Schnellspanner für eine Ø12-Stange, ganz aus Druckteilen (Prinzip Fahrrad-Schnellspanner).

    Lokales System: Stangenachse = x, Klemmschlitz und Spannbolzen auf der Seite +z, der Klemmkörper reicht in y von
    -fern bis nah. Ein 3 mm breiter Schlitz teilt den Körper von der Bohrung bis zur Außenseite. Der Spannbolzen läuft
    quer (y) über den Schlitz, sein Kopf sitzt versenkt auf der Seite -fern; auf der Seite +nah trägt sein Auge den
    Querstift, um den der gegabelte Hebel mit zwei Kurvenscheiben dreht. Kurvenscheibe Radius 7, Exzentrizität 1,25:
    Umlegen zieht den Bolzen um 2,5 mm an. Das schließt den Schlitz, hebt das Gleitspiel (0,3 mm) auf und klemmt.
    Druck: Klemmkörper wie eingebaut, Bohrungen als Tropfen; Bolzen liegend (Fasern längs, Biegung und Zug);
    Hebel flach auf einer Kurvenscheibe; Querstift liegend, mit 0,1 mm Übermaß ins Auge gedrückt.
    Liefert (Aussparung für den Klemmkörper, Teile {Name: Körper}) im lokalen System.
    """
    h = gleit + 5 * linie + 3.2  # Bolzenachse über der Stangenachse: Bohrung, 5 Linien Wand, Bolzenloch
    e, rd, d_kopf = 1.25, 7, 12
    aus = Pos(0, 0, (h + 10) / 2) * Box(l + 2, 3, h + 10)  # Klemmschlitz
    aus += Pos(0, (nah - fern) / 2, h) * tropfen(3.2, nah + fern + 2, "y")  # Bolzenloch
    aus += Pos(0, -fern + 1.25, h) * Rot(90, 0, 0) * Cylinder(d_kopf / 2 + 0.3, 4.5)  # Senkung für den Kopf
    dreh_y = nah + rd + e  # Querstift: im geschlossenen Zustand liegt die Kurvenscheibe an der Fläche +nah an
    y0, y1, y_flach = -fern + 3.5, dreh_y + 4, nah  # ab der Anlagefläche flach
    bolzen = Pos(0, (y0 + y_flach) / 2, h) * Rot(90, 0, 0) * Cylinder(3, y_flach - y0)  # runder Schaft im Körper
    bolzen += Pos(0, -fern + 2, h) * Rot(90, 0, 0) * Cylinder(d_kopf / 2, 3)  # Kopf
    bolzen += Pos(0, (y_flach + y1) / 2, h) * Box(10, y1 - y_flach, 4)  # flache Zunge zwischen den Kurvenscheiben
    bolzen -= Pos(0, dreh_y, h) * Cylinder(2.1, 6)
    stift = Pos(0, dreh_y, h) * Cylinder(2, 4 + 2 * (0.3 + 3))
    hebel = None
    for sz in (1, -1):  # zwei Kurvenscheiben links und rechts vom Auge
        scheibe = Pos(0, dreh_y - e, h + sz * (2 + 0.3 + 1.5)) * Cylinder(rd, 3)
        hebel = scheibe if hebel is None else hebel + scheibe
    hebel += Pos(-rd - 22.5 + 1, dreh_y - e, h) * Box(45, 6, 2 * (2 + 0.3 + 3))  # Griff verbindet beide Scheiben
    hebel -= Pos(0, dreh_y, h) * Cylinder(2.25, 20)  # Lagerbohrung, 0,25 mm Spiel
    return aus, {"Spannbolzen": bolzen, "Spannhebel": hebel, "Querstift": stift}


step("Kugelschieber: Stangenhalter")
xk = schraege_x(ys) + wand_d  # Halter mittig unter der schrägen Innenschürze
halter, halter_klemme, halter_griff = [], [], []
klemm_aus, klemm_teile = exzenterklemme(13, 13, 30)
klemm_h = gleit + 5 * linie + 3.2 + 3.2 + 6 * linie  # Hülse reicht so weit über den Spannbolzen hinaus
for sx in (1, -1):
    for sy in (1, -1):
        x, y = sx * xk, sy * ys
        oben_huelse = stangen_z + 11
        h = Pos(x, y, stangen_z + (11 - klemm_h) / 2) * Box(30, 26, 11 + klemm_h)  # Hülse um die Seitenstange
        h += Pos(x, y, (oben_huelse + rahmen_unten) / 2) * Box(20, 26, rahmen_unten - oben_huelse + 0.5)  # Säule
        kopf = Pos(x, y, rahmen_unten - 8) * Box(40, 26, 8 + klemme_h, align=boden)
        halter_griff.append(round((kopf & rahmen).volume))  # so viel Rahmen umgreift der Kopf
        h = aussparen(h + kopf, rahmen, spiel)  # Form von Schürze und Rippe mit Luft aussparen
        h -= Pos(x, y, stangen_z) * tropfen(gleit, 32, "x")  # Stange gleitet durch, herausziehbar
        # Klemme unten, Hebel zur Wagenmitte: lokal y zeigt nach innen, z nach unten
        lage_k = Pos(x, y, stangen_z) * (Rot(180, 0, 0) if sy > 0 else Rot(0, 0, 180) * Rot(180, 0, 0))
        h -= lage_k * klemm_aus
        halter.append(h)
        halter_klemme.append({n: lage_k * t for n, t in klemm_teile.items()})
if min(halter_griff) <= 0:
    raise ValueError("Ein Stangenhalter greift nicht um den Rahmen")
seite_x1 = wagen_l / 2 + stangen_vorschub  # Vorderende der Seitenstangen
seite_x0 = seite_x1 - laenge
if seite_x0 > -xk - 15 - 3:
    raise ValueError(f"stangen_vorschub {stangen_vorschub}: die Stangen kämen aus dem hinteren Halter; höchstens "
                     f"{math.floor(laenge - xk - 18 - wagen_l / 2)} mm")

step("Kugelschieber: Laufrollen")
rolle_l = min(laufrolle_l, 2 * (ys - 25 - 1) - 2 * 9)  # Platz zwischen den Schlitten, abzüglich Stellringe
rolle_r_ende = laufrolle_r + einschnuerung_r - math.sqrt(einschnuerung_r ** 2 - (rolle_l / 2) ** 2)
quer_z = rolle_r_ende + boden_min  # Querstangen so tief, dass die Rollen gerade frei vom Boden laufen
laufrolle = Cylinder(rolle_r_ende, rolle_l) - Torus(laufrolle_r + einschnuerung_r, einschnuerung_r)
laufrolle = Rot(90, 0, 0) * (laufrolle - Cylinder(lauf, rolle_l + 2))  # Achse quer (y)
# Stellring als Sprengclip (Druck): von unten auf die Querstange geklipst, hält die Rolle seitlich; Öffnung 9 mm
stellring = Cylinder(aussen_d / 2 + 5, 8) - Cylinder(bohr, 10) - Pos(0, -(aussen_d / 2 + 5), 0) * Box(9, aussen_d + 10, 10)
stellring = Rot(90, 0, 0) * stellring


def rollen_x(luft: float) -> float:
    """Abstand der Querstange zur Ballmitte in x, wenn die Rolle mit luft am Ball liegt."""
    return math.sqrt((r_ball + laufrolle_r + luft) ** 2 - (r_ball - quer_z) ** 2)


step("Kugelschieber: Rollenschlitten")
schlitten_l = 36
xq_h_rel, xq_v_rel = -rollen_x(schieber_luft), rollen_x(vorn_luft)
# Grenzen: Schieberschlitten vor den vorderen Haltern und Ball vor dem Objektiv, Fangschlitten noch auf den Stangen
bx_min = max(xk + 15 + 2 + schlitten_l / 2 - xq_h_rel, wagen_l / 2 + 10 + r_ball)
bx_max = seite_x1 - 1 - schlitten_l / 2 - xq_v_rel
ball_bereich = (math.ceil(bx_min - r_ball - wagen_l / 2), math.floor(bx_max - r_ball - wagen_l / 2))
if not ball_bereich[0] <= kamera_ball <= ball_bereich[1]:
    raise ValueError(f"kamera_ball {kamera_ball} liegt außerhalb von {ball_bereich[0]} bis {ball_bereich[1]} mm "
                     f"(bei stangen_vorschub {stangen_vorschub} und vorn_luft {vorn_luft})")
bx = wagen_l / 2 + kamera_ball + r_ball  # Ballmitte in x
xq_hinten, xq_vorn = bx + xq_h_rel, bx + xq_v_rel
z_unten = max(boden_min, min(quer_z, stangen_z) - 11)
z_oben = stangen_z + klemm_h
schlitten, schlitten_hebel = {}, {}
s_aus, s_teile = exzenterklemme(9, 12, schlitten_l)
for rolle, xq in (("Schieber", xq_hinten), ("Fänger", xq_vorn)):
    for sy, seite in ((1, "links"), (-1, "rechts")):
        y_innen, y_aussen = ys - 25, ys + 9
        z_mitte = max(quer_z, stangen_z)
        s = Pos(xq, sy * (y_innen + y_aussen) / 2, (z_unten + z_mitte) / 2) * Box(schlitten_l, y_aussen - y_innen,
                                                                                   z_mitte - z_unten)
        s += Pos(xq, sy * (ys - 12 + y_aussen) / 2, (z_mitte - 1 + z_oben) / 2) * Box(schlitten_l, y_aussen - ys + 12,
                                                                                       z_oben - z_mitte + 1)
        s -= Pos(xq, sy * ys, stangen_z) * tropfen(gleit, schlitten_l + 2, "x")  # gleitet auf der Stange
        s -= Pos(xq, sy * ((y_innen + ys - 8) / 2 - 0.5), quer_z) * tropfen(bohr, ys - 8 - y_innen + 1, "y")
        lage_k = Pos(xq, sy * ys, stangen_z) * (Rot(0, 0, 0) if sy > 0 else Rot(0, 0, 180))  # Hebel nach außen, oben
        s -= lage_k * s_aus
        for n, t in s_teile.items():
            schlitten_hebel[f"{n} {rolle} {seite}"] = lage_k * t
        schlitten[f"{rolle}schlitten {seite}"] = s

step("Kugelschieber: Rohre")
l_quer = math.floor(2 * (ys - 8))  # endet 2 mm vor der Bohrung der Seitenstange
zuschnitt = {  # Rohr-Nr. -> Stücke (Name, Länge); ganze Rohre bleiben ungekürzt
    1: [("Seitenstange links", laenge)],
    2: [("Seitenstange rechts", laenge)],
    3: [("Querstange hinten", l_quer), ("Querstange vorn", l_quer)],
    4: [],
}
reste = {}
for nr, stuecke in zuschnitt.items():
    rest = laenge - sum(l for _, l in stuecke) - saege * len(stuecke)
    if rest < 0 and rest + saege >= 0:
        rest = 0  # das letzte Stück ist das Rohrende, ein Schnitt weniger
    if rest < 0:
        raise ValueError(f"Rohr {nr} reicht nicht: {[l for _, l in stuecke]} mm plus Schnitte > {laenge} mm")
    reste[nr] = rest

rohrteile = {
    "Seitenstange links (Rohr 1)": Pos((seite_x0 + seite_x1) / 2, ys, stangen_z) * rohr(laenge, "x"),
    "Seitenstange rechts (Rohr 2)": Pos((seite_x0 + seite_x1) / 2, -ys, stangen_z) * rohr(laenge, "x"),
    "Querstange hinten (Rohr 3)": Pos(xq_hinten, 0, quer_z) * rohr(l_quer, "y"),
    "Querstange vorn (Rohr 3)": Pos(xq_vorn, 0, quer_z) * rohr(l_quer, "y"),
}
druckteile = {
    "Schieberolle": Pos(xq_hinten, 0, quer_z) * laufrolle,
    "Fangrolle": Pos(xq_vorn, 0, quer_z) * laufrolle,
}
for name, xq in (("hinten", xq_hinten), ("vorn", xq_vorn)):
    for sy, seite in ((1, "links"), (-1, "rechts")):
        druckteile[f"Stellring {name} {seite}"] = Pos(xq, sy * (rolle_l / 2 + 4.5), quer_z) * stellring
druckteile.update(schlitten)
druckteile.update(schlitten_hebel)
for i, (h, (sx, sy)) in enumerate(zip(halter, [(1, 1), (1, -1), (-1, 1), (-1, -1)])):
    name = f"Stangenhalter {'vorn' if sx > 0 else 'hinten'} {'links' if sy > 0 else 'rechts'}"
    druckteile[name] = h
    for n, t in halter_klemme[i].items():
        druckteile[f"{n} {name[14:]}"] = t

rig = Pos(0, wagen_y + rig_versatz, 0)
for name, teil in rohrteile.items():
    show(rig * teil, f"Kugelschieber/{name}", color="#C9CDD2", material="aluminium")
for name, teil in druckteile.items():
    show(rig * teil, f"Kugelschieber/{name} (Druck)", color="#F28C28", material="petg")
kugel = Pos(bx, 0, r_ball)
show(rig * kugel * ball, "Bowlingball", color="#5B2A86", material="pmma")

step("Kugelschieber: Montageprüfung")
# Regel: Jedes Teil muss sich einbauen lassen. Hier steht die Ausbaufolge (umgekehrt = Einbau) mit Weg und Richtung;
# jeder Weg wird in Schritten abgefahren und gegen alles geprüft, was dann noch verbaut ist.
# montage_pruefen = 1 schaltet die Prüfung ein (dauert einige Sekunden); Kollisionen stehen in montage_befund.
montage_pruefen = param("montage_pruefen", 0)
montage_befund = []


def zusammen(teile: list) -> Part:
    """Mehrere Teile als ein Körper (Baugruppe)."""
    g = teile[0]
    for t in teile[1:]:
        g += t
    return g


def ueberlappen(a: Part, b: Part) -> bool:
    """Grober Vorfilter über die Hüllquader."""
    pa, pb = a.bounding_box(), b.bounding_box()
    return (pa.min.X < pb.max.X and pb.min.X < pa.max.X and pa.min.Y < pb.max.Y and pb.min.Y < pa.max.Y
            and pa.min.Z < pb.max.Z and pb.min.Z < pa.max.Z)


def ausbauweg(name: str, teil: Part, richtung: tuple, weg: float, hindernisse: dict, schritt: float = 5) -> None:
    """Fährt teil um weg mm in richtung und meldet die erste Kollision mit einem Hindernis."""
    laenge_r = math.sqrt(sum(c * c for c in richtung))
    n = max(1, math.ceil(weg / schritt))
    for i in range(1, n + 1):
        s = weg * i / n
        t = Pos(*(c / laenge_r * s for c in richtung)) * teil
        for h_name, h in hindernisse.items():
            if ueberlappen(t, h) and (t & h).volume > 0.05:
                montage_befund.append(f"{name}: stößt nach {s:.0f} mm an {h_name}")
                return


if montage_pruefen:
    welt = lambda t: rig * t  # noqa: E731
    fest = {"Rahmen": Pos(0, wagen_y, 0) * rahmen}
    for i, lage in enumerate(rollen_lagen):
        fest[f"Lenkrolle {i + 1}"] = lage * (gabel + rad)
        fest[f"Lenksperre {i + 1}"] = lenksperren[i]
    gruppen = {  # Baugruppen in Ausbaufolge: (Teile, Richtung, Weg, Schrittweite)
        "Bowlingball": ([kugel * ball], (0, 0, 1), 2 * r_ball + 20, 10),
        "Fängerschlitten mit Rolle": ([druckteile[k] for k in druckteile if "Fänger" in k or k == "Fangrolle"
                                       or k.startswith("Stellring vorn")] + [rohrteile["Querstange vorn (Rohr 3)"]],
                                      (1, 0, 0), seite_x1 - xq_vorn + schlitten_l, 10),
        "Schieberschlitten mit Rolle": ([druckteile[k] for k in druckteile if "Schieber" in k
                                         or k.startswith("Stellring hinten")] + [rohrteile["Querstange hinten (Rohr 3)"]],
                                        (1, 0, 0), seite_x1 - xq_hinten + schlitten_l, 10),
        "Seitenstange links": ([rohrteile["Seitenstange links (Rohr 1)"]], (1, 0, 0), laenge + 40, 25),
        "Seitenstange rechts": ([rohrteile["Seitenstange rechts (Rohr 2)"]], (1, 0, 0), laenge + 40, 25),
    }
    for k in druckteile:
        if k.startswith("Stangenhalter"):
            gruppen[k] = ([druckteile[k]] + [druckteile[f"{n} {k[14:]}"] for n in klemm_teile], (0, 0, -1),
                          klemme_h + 12, 4)
    namen = list(gruppen)
    for i, name in enumerate(namen):
        teile, richtung, weg, schritt = gruppen[name]
        noch_verbaut = {**fest, **{n: welt(zusammen(gruppen[n][0])) for n in namen[i + 1:]}}
        ausbauweg(name, welt(zusammen(teile)), richtung, weg, noch_verbaut, schritt)
    # Lenkrollen mit Sperre: Schraube nach oben heraus, Rolle samt Sperre nach unten, dann Sperre vom Kronenende
    for i, lage in enumerate(rollen_lagen):
        andere = {n: h for n, h in fest.items() if n not in (f"Lenkrolle {i + 1}", f"Lenksperre {i + 1}")}
        ausbauweg(f"Rollenschraube {i + 1}", lage * schraube, (0, 0, 1), rahmen_h + 10,
                  {"Rahmen": fest["Rahmen"]}, 5)
        ausbauweg(f"Lenkrolle {i + 1} mit Sperre", lage * (gabel + rad) + lenksperren[i], (0, 0, -1), sperre_h + 12,
                  andere, 4)
        aussen_x = 1 if rollen_pos[i][0] > 0 else -1  # Kronenende zeigt zur nächsten Stirnseite
        ausbauweg(f"Lenksperre {i + 1} vom Kronenende", lenksperren[i], (aussen_x, 0, 0), 40,
                  {"Gabel und Rad": lage * (gabel + rad)}, 4)
    if montage_befund:
        raise ValueError("Montage nicht möglich: " + "; ".join(montage_befund))

step("Inventar: Reste")
# Am alten Lagerplatz der Rohre: was vom Zuschnitt übrig bleibt
for nr, rest in reste.items():
    y = (nr - 1 - (anzahl - 1) / 2) * teilung
    name = f"Rohr {nr} unbenutzt" if not zuschnitt[nr] else f"Rohr {nr} Rest {rest:.0f} mm"
    if rest > 0:
        show(Pos(-laenge / 2 + rest / 2, y, aussen_d / 2) * rohr(rest, "x"), f"Inventar/{name}", color="#C9CDD2",
             material="aluminium")

# Kamera: Sony FX6 (ILME-FX6), vereinfacht. Belegt (Sony): Body ohne Anbauten 114 × 116 × 153 mm (B × H × T), 890 g.
# Lage und Größe von Bajonett, Tragegriff, Monitor und Handgriff sind geschätzt. Das Objektiv ist ein Platzhalter für
# eine große Cine-Linse (Frontdurchmesser 114 mm wie bei Kompendien üblich), bis Kevins EAN kommt; V-Mount folgt.
# Die Objektivfront liegt an der Wagenvorderkante (kamera_ball). Eine gedruckte Kameraplatte hebt die Kamera so weit,
# dass die Linse über dem Deckel frei ist. Ohne material: Kein Werkstoff im Katalog ergibt 890 g auf diesem Volumen.
fx6_b, fx6_h, fx6_t = 114, 116, 153
bildachse_z = param("bildachse_z", 52)  # Höhe der Bildachse über der Unterkante, geschätzt
objektiv_l = param("objektiv_l", 220)  # Platzhalter Cine-Linse: Länge ab Auflage
objektiv_d = param("objektiv_d", 114)  # Platzhalter Cine-Linse: Frontdurchmesser
objektiv_platz = 8 + objektiv_l  # Bajonett plus Objektiv vor dem Body
kameraplatte_h = max(param("kameraplatte_min", 5), objektiv_d / 2 + 3 - bildachse_z)

step("Kamera FX6")
vorne = (Align.MAX, Align.CENTER, Align.MIN)  # Vorderseite bei x = 0, Unterkante bei z = 0
fx6 = {}
body = Box(fx6_t, fx6_b, fx6_h, align=vorne)
fx6["Body"] = fillet(body.edges().filter_by(Axis.X), radius=8)
ring = Cylinder(31, 8, align=boden) - Pos(0, 0, -1) * Cylinder(23, 10, align=boden)
fx6["Bajonett"] = Pos(0, 0, bildachse_z) * Rot(0, 90, 0) * ring  # E-Mount, steht 8 mm vor
griff = Pos(-15, 0, fx6_h) * Box(16, 24, 31, align=vorne) + Pos(-120, 0, fx6_h) * Box(16, 24, 31, align=vorne)
griff += Pos(8, 0, fx6_h + 30) * Box(160, 24, 16, align=vorne)
fx6["Tragegriff"] = griff
fx6["Monitor"] = Pos(22, fx6_b / 2 - 10, fx6_h + 22) * Box(18, 95, 62, align=boden)
handgriff = Box(60, 48, 110, align=boden)
fx6["Handgriff"] = Pos(-32, -(fx6_b / 2 + 24), 6) * fillet(handgriff.edges().filter_by(Axis.Z), radius=14)


def abschnitt(x0: float, laenge_x: float, d: float) -> Part:
    """Zylinder entlang der Bildachse von x0 bis x0 + laenge_x."""
    return Pos(x0, 0, 0) * Rot(0, 90, 0) * Cylinder(d / 2, laenge_x, align=boden)


front_l = 45
linse = abschnitt(0, 25, 80) + abschnitt(24, objektiv_l - 24 - front_l + 1, objektiv_d - 16)  # Auflage, Tubus
linse += abschnitt(objektiv_l - front_l, front_l, objektiv_d)  # Frontteil
linse -= abschnitt(objektiv_l - 8, 10, objektiv_d - 18)  # Frontlinse liegt vertieft
zahnringe = None
for x0 in (0.2, 0.42, 0.62):  # Fokus, Blende, Zoom als 0,8-Modul-Zahnkränze, vereinfacht als Ringe
    z = abschnitt(x0 * objektiv_l, 16, objektiv_d - 6)
    zahnringe = z if zahnringe is None else zahnringe + z
zahnringe -= linse  # Ringe sitzen auf dem Tubus
fx6["Cine-Objektiv (Platzhalter)"] = Pos(8, 0, bildachse_z) * linse
fx6["Cine-Objektiv (Platzhalter)/Zahnringe"] = Pos(8, 0, bildachse_z) * zahnringe
farben_fx6 = {"Body": "#2B2D30", "Bajonett": "#B9BEC4", "Tragegriff": "#2B2D30", "Monitor": "#1E1F21",
              "Handgriff": "#3A3C40", "Cine-Objektiv (Platzhalter)": "#151617",
              "Cine-Objektiv (Platzhalter)/Zahnringe": "#3C3F44"}
deckel_oben = rolle_h + rahmen_h + deckel_h
kamera = Pos(wagen_l / 2 - objektiv_platz, wagen_y, deckel_oben + kameraplatte_h)
for name, teil in fx6.items():
    show(kamera * teil, f"Kamera FX6/{name}", color=farben_fx6[name])
kameraplatte = Pos(wagen_l / 2 - objektiv_platz, wagen_y, deckel_oben) * Box(fx6_t, fx6_b, kameraplatte_h, align=vorne)
show(kameraplatte, "Kamera FX6/Kameraplatte (Druck)", color="#F28C28", material="petg")

# Optische Kamera (Phase 5, Kameras): die FX6 aus dem Katalog mit einem 35-mm-Objektiv, Bajonett-Auflage an der Front
# des Bajonettrings, Blick nach vorn, Fokus auf die Ballrückseite. Sie hängt am Body und fährt deshalb in der
# Animation mit (Taste 0 und animation_video(kamera="FX6") zeigen ihr Bild). Das Platzhalter-Objektiv blendet die App
# beim Blick durch die Kamera aus.
fx6_kamera = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", blende=2.8, name="FX6")
bajonett_welt = kamera.position + Vector(8, 0, bildachse_z)
fx6_kamera.an("Kamera FX6/Body", punkt=bajonett_welt, richtung=(1, 0, 0), bezug="bajonett")
fx6_kamera.einstellen(fokus=bx - r_ball - fx6_kamera.position[0])


# ---------------------------------------------------------------------------------------------------------------------
# Animation (Phase 5): Spuren auf den gezeigten Teilen; Baugruppen über das Präfix ("Rollwagen" = alle "Rollwagen/…")
# ---------------------------------------------------------------------------------------------------------------------
step("Animation")
strecke = param("strecke", 2000)  # so weit rollt der Wagen
fahrt = animation(dauer=8, fps=30, name="Fahrt")
fahrt.bewege("Rollwagen", nach=(strecke, 0, 0), von=1, bis=7, kurve="weich")
for i in range(1, 5):  # Lenkrollen: Rad und Felge rollen auf dem Boden ab (Drehwinkel = Strecke / Radius)
    for teil in ("Rad", "Felge"):
        fahrt.rolle(f"Rollwagen/Lenkrolle {i}/{teil}", auf="Rollwagen", radius=rad_d / 2, achse="y")
for name in ("Deckel 05090", "Kamera FX6", "Kugelschieber"):
    fahrt.folge(name, "Rollwagen")
# Der Ball rollt frei vor dem Schieber her; die Laufrollen drehen gegenläufig mit seiner Oberfläche
fahrt.rolle("Bowlingball", auf="Rollwagen", radius=r_ball)
for rolle_name in ("Schieberolle", "Fangrolle"):
    fahrt.drehe(f"Kugelschieber/{rolle_name} (Druck)", achse="y", winkel=-math.degrees(strecke / laufrolle_r),
                von=1, bis=7, kurve="weich")
# Kamerafahrt: fährt mit dem Wagen mit und schwenkt von schräg hinten nach vorn auf den Ball
fahrt.ansicht(0, lage=(-900, wagen_y - 1100, 700), ziel=(250, wagen_y, 150), mit="Rollwagen/Rahmen")
fahrt.ansicht(4, lage=(300, wagen_y - 1500, 450), ziel=(300, wagen_y, 150), mit="Rollwagen/Rahmen")
fahrt.ansicht(8, lage=(1800, wagen_y - 900, 500), ziel=(400, wagen_y, 150), mit="Rollwagen/Rahmen")

# Verstellen: die vier Spannhebel der Rollenschlitten öffnen (Drehgelenke), beide Rollenschlitten mit dem Ball als
# Schubgelenk in den Grenzen des Verstellbereichs (ball_bereich) verschieben, Hebel wieder schließen. Der Ball rollt
# dabei auf dem Boden.
verstellen = animation(dauer=6, fps=30, name="Verstellen")
fuehrung = "Kugelschieber/Schieberschlitten links (Druck)"
weg_min, weg_max = ball_bereich[0] - kamera_ball, ball_bereich[1] - kamera_ball
verstellen.gelenk(fuehrung, art="schub", achse="x", grenzen=(weg_min, weg_max),
                  werte={0: 0, 1: 0, 2.5: weg_max, 4: weg_min, 5: 0})
schlittenteile = ["Querstange hinten (Rohr 3)", "Querstange vorn (Rohr 3)", "Schieberolle (Druck)", "Fangrolle (Druck)"]
schlittenteile += [f"Stellring {lage} {seite} (Druck)" for lage in ("hinten", "vorn") for seite in ("links", "rechts")]
schlittenteile += [f"{rolle}schlitten {seite} (Druck)" for rolle in ("Schieber", "Fänger") for seite in ("links", "rechts")]
schlittenteile += [f"{n} {rolle} {seite} (Druck)" for n in ("Spannbolzen", "Querstift") for rolle in ("Schieber", "Fänger")
                   for seite in ("links", "rechts")]
for teil in schlittenteile:
    if f"Kugelschieber/{teil}" != fuehrung:
        verstellen.folge(f"Kugelschieber/{teil}", fuehrung)
verstellen.rolle("Bowlingball", auf=fuehrung, radius=r_ball)
for rolle in ("Schieber", "Fänger"):
    for seite in ("links", "rechts"):  # Hebel schwenken nach außen auf (um -z)
        drehpunkt = (rig * schlitten_hebel[f"Querstift {rolle} {seite}"]).center()
        verstellen.gelenk(f"Kugelschieber/Spannhebel {rolle} {seite} (Druck)", art="dreh",
                          achse=(drehpunkt, (0, 0, -1)), grenzen=(0, 120), werte={0: 0, 0.8: 100, 5.2: 100, 6: 0},
                          eltern=fuehrung)
