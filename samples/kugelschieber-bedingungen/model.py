"""Inventar und Kugelschieber: ein Bowlingball, den eine Vorrichtung vor dem Kamerawagen herschiebt.

Beispiel für Zwangsbedingungen (PLAN-BEDINGUNGEN.md): Kopie von Kevins Projekt „Neues Projekt“ (Stand 21.10.2026,
23:03). Geändert ist nur der Rollwagen: Der Rahmen entsteht in seinem eigenen System und sitzt über
bed.auf(...) und bed.konzentrisch(...) auf den Lenkrollen (Schritt „Rollwagen: Rahmen auf die Lenkrollen“); ändert
sich rolle_h, folgt der Rahmen und alles, was an platte_oben hängt. Dazu die Befestigung des Rollwagens über
bed.verbinde(...) (am Ende des Abschnitts Stangenhalter). bewegungen.json fehlt hier mit Absicht (siehe Kevins Projekt).

Regel: Gebaut wird nur aus dem Inventar plus 3D-Druckteilen. Fehlt etwas, kommt es zuerst ins Inventar.

Inventar
- 4 Rohre: ALFER Art.-Nr. 01023 (EAN 4001116010231), Aluminium, silbern eloxiert, Ø 12 × 1 mm, 1 m lang.
- Rollwagen: ALUTEC Art.-Nr. 05200 (EAN 4014688052004) für Eurobehälter 600 × 400, Kunststoff blau, 610 × 410 mm,
  vier Lenkrollen Ø 100 mm, zwei davon mit Feststeller. Aufbau und Maße aus Kevins Video vermessen (Parameter unten).
- Deckel: ALUTEC Art.-Nr. 05090 (EAN 4014688050901), Auflagedeckel für Eurobehälter 600 × 400.
- Bowlingball nach USBC-Maßen.
- Neu zu beschaffen (Kevin hat Schrauben vorgeschlagen): 8 Linsenkopfschrauben ISO 7380 M6 × 25, 8 Muttern ISO 4032
  M6, 8 Karosseriescheiben ISO 7093 6,4 × 18 für die Stangenhalter; dazu 8 Bohrungen Ø 6,6 in der Wagenplatte.
- Fluidkopf Manfrotto MVH502AH mit Schnellwechselplatte 504PLONG (geometrie/manfrotto_mvh502ah.py).
- Zweite Kamera Blackmagic Pocket Cinema Camera 6K Pro (EF) mit Sigma 18-35 f/1.8 Art als Beispielobjektiv
  (geometrie/blackmagic_pocket6kpro.py), im Lager.
- Kamerasystem (kamera_fx6.py): Sony FX6 (ILME-FX6) nach Sony-Maßzeichnung, Tilta-Baseplate ES-T20-QRBP mit zwei
  15-mm-Rods (150 mm), Tilta-Akkuplatte V-Mount; Beispiele bis zur EAN: Akku IDX DUO-C98P, Objektiv Fujinon MK18-55.
Alle Maße in mm, Z nach oben. Längsachsen entlang X, Schieberichtung +X.
"""

import math

from build123d import *
from kevcad import param, show, step
import kevcad.bedingungen as bed  # Zwangsbedingungen (als Modul: boden, spiel, winkel, fest sind hier Variablen)

aussen_d = param("aussen_d", 12)
wand = param("wand", 1)
laenge = param("laenge", 1000)
anzahl = int(param("anzahl", 4))
luecke = param("luecke", 10)  # lichter Abstand zwischen zwei Teilen einer Reihe

# Die Rohre liegen nicht mehr lose da: Sie sind im Kugelschieber verbaut; Reste und unbenutzte Rohre liegen
# am alten Lagerplatz (ganz unten).
teilung = aussen_d + luecke
rohre_rand = (anzahl - 1) / 2 * teilung + aussen_d / 2  # Rand des Lagerplatzes der Rohre

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
# Der Rahmen entsteht in seinem eigenen System (Unterkante z = 0) und sitzt über Bedingungen auf den Lenkrollen;
# platte_oben ergibt sich erst danach aus der Lage des Rahmens (ändert sich rolle_h, folgt der Rahmen).
r_u, r_po = 0.0, rahmen_h  # Unterkante und Plattenoberseite im System des Rahmens


def achteck(l: float, b: float, fx: float, fy: float) -> Face:
    """Rechteck l × b mit Eckschrägen (Schenkel fx in x, fy in y), Mitte im Ursprung."""
    hx, hy = l / 2, b / 2
    punkte = [(hx - fx, hy), (hx, hy - fy), (hx, -hy + fy), (hx - fx, -hy), (-hx + fx, -hy), (-hx, -hy + fy),
              (-hx, hy - fy), (-hx + fx, hy)]
    return Polygon(*reversed(punkte), align=None)  # gegen den Uhrzeigersinn: Normale +z, extrude geht nach oben


step("Rollwagen: Rahmen")
umriss = achteck(wagen_l, wagen_b, eck_fase, eck_fase)
oeffnung = achteck(oeff_l, oeff_b, oeff_fase_x, oeff_fase_y)
rahmen = Pos(0, 0, r_po - platte_d) * extrude(umriss - oeffnung, amount=platte_d)
schuerzen = (umriss - offset(umriss, amount=-wand_d, kind=Kind.INTERSECTION)) + \
            (offset(oeffnung, amount=wand_d, kind=Kind.INTERSECTION) - oeffnung)
rahmen += Pos(0, 0, r_u) * extrude(schuerzen, amount=rahmen_h - platte_d + 0.5)
rippe_h = rahmen_h - platte_d + 0.5
rollen_pos = [(sx * (wagen_l / 2 - schraube_rand), sy * (wagen_b / 2 - schraube_rand)) for sx in (1, -1) for sy in (1, -1)]
rippen = []
for x, y in rollen_pos:  # Eckdom mit sternförmigen Rippen (Anzahl und Lage geschätzt)
    sx, sy = math.copysign(1, x), math.copysign(1, y)
    rippen.append(Pos(x, y, r_u) * Cylinder(dom_d / 2, rippe_h, align=boden))
    for winkel in (0 if sx > 0 else 180, 90 if sy > 0 else -90,  # zu den Außenschürzen
                   math.degrees(math.atan2(sy, sx)),  # zur Eckfase
                   math.degrees(math.atan2(-sy * oeff_fase_x, -sx * oeff_fase_y))):  # zur Schräge der Öffnung
        rippen.append(Pos(x, y, r_u) * Rot(0, 0, winkel) * Pos(100, 0, 0) * Box(200, wand_d, rippe_h, align=boden))
for s in (1, -1):  # Querrippen in den Kanälen (Anzahl geschätzt)
    rippen.append(Pos(s * wagen_l / 2, 0, r_u) * Box(200, wand_d, rippe_h, align=boden))
    for x in (-80, 80):
        rippen.append(Pos(x, s * wagen_b / 2, r_u) * Box(wand_d, 200, rippe_h, align=boden))
rippen_teil = rippen[0]
for r in rippen[1:]:
    rippen_teil += r
# Rippen enden an den Schürzen: alles auf die Rahmenfläche zwischen Außenkontur und Öffnung begrenzen
rahmen += rippen_teil & (Pos(0, 0, r_u) * extrude(umriss - oeffnung, amount=rippe_h))
for x, y in rollen_pos:  # Rückenloch für die Rollenschraube
    rahmen -= Pos(x, y, r_u - 1) * Cylinder(6, rahmen_h + 2, align=boden)
for sy in (1, -1):  # aufgestellter Rand, außenbündig, an den Ecken unterbrochen
    rahmen += Pos(0, sy * (wagen_b / 2 - rand_d / 2), r_po - 0.5) * \
        Box(wagen_l - 2 * rand_ende_lang, rand_d, rand_h + 0.5, align=boden)
    rahmen += Pos(sy * (wagen_l / 2 - rand_d / 2), 0, r_po - 0.5) * \
        Box(rand_d, wagen_b - 2 * rand_ende_stirn, rand_h + 0.5, align=boden)

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
feststeller = Pos(-nachlauf - 48 - 18, 0, krone_z) * Box(36, 40, blech, align=boden)  # Pedal hinter dem Kronenende
feststeller = fillet(feststeller.edges().filter_by(Axis.Z), radius=6)

step("Rollwagen: Rahmen auf die Lenkrollen")
# Bedingungen statt Koordinaten: Die Unterseite des Rahmens liegt auf den Laufplatten der Lenkrollen, die
# Rückenlöcher sitzen konzentrisch über den Drehachsen der ersten beiden Rollen (das legt Lage und Drehung fest).
# Gerechnet wird im System des Wagens (ohne wagen_y); gezeigt wird alles um wagen_y verschoben.
rollen_wagen = [Pos(x, y, 0) * Rot(0, 0, 180 if x > 0 else 0) for x, y in rollen_pos]
gabeln_w = [lage * gabel for lage in rollen_wagen]
drehachsen = [bed.bezug(g, "Drehachse", Axis((x, y, 0), (0, 0, 1))) for g, (x, y) in zip(gabeln_w, rollen_pos)]
rahmen = bed.platziere(
    rahmen,
    bed.auf((rahmen, "unten"), (gabeln_w[0], "oben")),
    bed.konzentrisch((rahmen, "bohrung", {"nahe": (*rollen_pos[0], 0)}), drehachsen[0]),
    bed.konzentrisch((rahmen, "bohrung", {"nahe": (*rollen_pos[1], 0)}), drehachsen[1]),
)
rahmen_unten = bed.bezug(rahmen, "unten").p[2]  # folgt der Rollenhöhe
platte_oben = rahmen_unten + rahmen_h
show(Pos(0, wagen_y, 0) * rahmen, "Rollwagen/Rahmen", color="#2F6DB5", material="polypropylen")

schraube = Pos(0, 0, rahmen_unten) * Cylinder(5.5, rahmen_h, align=boden) + \
    Pos(0, 0, platte_oben) * Cylinder(10, 4, align=boden)
rollen_lagen = [Pos(0, wagen_y, 0) * lage for lage in rollen_wagen]
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


linie = 0.42  # Linienbreite der 0,4-mm-Düse (Bambu Lab P1P): Wände in Vielfachen davon
SCHICHT = 0.2  # Schichthöhe: Tiefen von Sacklöchern im Raster


def tropfen(r: float, l: float, achse: str) -> Part:
    """Waagerechte Bohrung als Tropfen (Spitze nach oben, 45°): druckt ohne Stützen. Mittig, Achse 'x' oder 'y'."""
    profil = Circle(r) + Polygon((-r * 0.7071, r * 0.7071), (r * 0.7071, r * 0.7071), (0, r * 1.4142), align=None)
    t = extrude((Plane.YZ if achse == "x" else Plane.XZ) * profil, amount=l)
    m = t.bounding_box().center()  # nur längs der Achse mittig: der Kreis bleibt auf der Achse
    return Pos(-m.X, 0, 0) * t if achse == "x" else Pos(0, -m.Y, 0) * t


# Klemmsystem für alle Stangenklemmen: Gewindeeinsatz, Gewindestift, Scheibe und Flügelmutter, alles M4.
# M4 reicht: Eine Flügelmutter von Hand (etwa 0,5 Nm) spannt mit rund 600 N, die Hülse hält damit ein Mehrfaches der
# Kräfte am Rig; M5 und M6 bräuchten mehr Wand um den Einsatz, die Klemmen würden höher und lägen näher am Bild.
EINSATZ_M4 = {"bohrung": 5.8, "l": 8.1, "aussen": 6.3}  # ruthex M4: 8,1 × 6,3; Bohrung 5,6 + 0,2 (CNC Kitchen)
FLUEGEL_M4 = {"e": 20, "h": 10.5, "m": 4.6, "d1": 8, "g": 1.9}  # DIN 315 M4, Höchstmaße
SCHEIBE_M4 = {"d": 4.3, "D": 9, "s": 0.8}  # ISO 7089
STIFT_L = 30  # Gewindestift ISO 4026 M4 × 30 (oder Gewindestange M4, abgelängt)
KL_NAH, KL_FERN = 9, 12  # Backe mit Durchgangsloch / Backe mit Einsatz, ab Stangenachse


def klemm_oben(r_stange: float | None = None) -> tuple[float, float]:
    """(Achshöhe des Gewindestifts, Oberkante der Backen) über der Stangenachse: Bohrung, 5 Linien Wand (= 2,1 mm,
    Mindestwand um einen M4-Einsatz), Einsatzbohrung, 5 Linien Wand."""
    g = (aussen_d / 2 if r_stange is None else r_stange) + 0.25
    rb = EINSATZ_M4["bohrung"] / 2
    h = g + 5 * linie + rb
    return h, h + rb + 5 * linie


def fluegelmutter() -> Part:
    """Flügelmutter DIN 315 M4 mit runden Flügeln, vereinfacht. Achse z, Auflage bei z = 0, Flügel längs x."""
    e, h, m, d1, g = (FLUEGEL_M4[k] for k in ("e", "h", "m", "d1", "g"))
    mutter = Cylinder(d1 / 2, m, align=boden)
    for s in (1, -1):
        punkte = [(s * (d1 / 2 - 1), 0.5), (s * (e / 2 - 2.5), 1.5), (s * e / 2, 4), (s * e / 2, h - 2.5),
                  (s * (e / 2 - 2.5), h), (s * (d1 / 2 - 1), h - 1)]
        mutter += in_xz(punkte, g, 0)
    return mutter - Cylinder(2.05, 3 * h)


def fluegelklemme(l: float, r_stange: float | None = None, nah: float = KL_NAH, fern: float = KL_FERN,
                  spitze: int = 1) -> tuple[Part, Part, dict]:
    """Klemmbacken mit Flügelmutter für eine Ø12-Stange (Ø 15 mit r_stange), Standard für alle Klemmen im Projekt.

    Lokales System: Stangenachse = x, Klemmschlitz (3 mm) zur Seite +z, die Backen reichen in y von -fern bis nah. Der
    Gewindestift läuft quer (y) über den Schlitz. Die Backe -fern trägt den Gewindeeinsatz M4, von ihrer Außenfläche
    eingeschmolzen, mit 2,4 mm Steg zum Schlitz. Der Stift ist darin mit mittelfester Schraubensicherung eingeklebt
    (Befestigung: Gewinde und Kleben); er geht durch ein Loch Ø 4,5 in der Backe +nah, außen sitzen Scheibe und
    Flügelmutter. Anziehen schließt den Schlitz und hebt das Gleitspiel (0,5 mm im Durchmesser) auf: Reibschluss.
    Lösen: eine halbe Umdrehung, die Stange gleitet wieder. Flügel in Ruhe längs der Stange, das hält die Klemme flach.
    spitze: +1, wenn lokal +z beim Druck oben liegt, sonst -1 (die Tropfenspitze der Querbohrungen zeigt nach oben).
    Der Einsatz ist im Modell so dick wie seine Bohrung (5,8); eingeschmolzen ist er 6,3.
    Liefert (Backen, Aussparung, Teile {Name: Körper}) im lokalen System.
    """
    h, oben = klemm_oben(r_stange)
    rb, l_e = EINSATZ_M4["bohrung"] / 2, EINSATZ_M4["l"]
    dreh = Rot(0, 180, 0) if spitze < 0 else Rot(0, 0, 0)
    backen = Pos(0, (nah - fern) / 2, (oben - 0.5) / 2) * Box(l, nah + fern, oben + 0.5)  # 0,5 unter die Achse: ein Körper
    aus = Pos(0, 0, (oben + 5) / 2) * Box(l + 2, 3, oben + 5)  # Klemmschlitz
    aus += Pos(0, -fern + (l_e - 1) / 2, h) * dreh * tropfen(rb, l_e + 1, "y")  # Einsatz, bündig mit der Außenfläche
    y0, y1 = -fern + l_e - 0.5, nah + 1
    aus += Pos(0, (y0 + y1) / 2, h) * dreh * tropfen(2.25, y1 - y0, "y")  # Durchgangsloch Ø 4,5
    achse_y = Rot(90, 0, 0)  # Zylinderachse in y
    einsatz = Pos(0, -fern + l_e / 2, h) * achse_y * (Cylinder(rb, l_e) - Cylinder(2.05, l_e + 2))
    s0 = -fern + 0.3
    stift = Pos(0, s0 + STIFT_L / 2, h) * achse_y * Cylinder(2, STIFT_L)
    sd = SCHEIBE_M4["s"]
    scheibe = Pos(0, nah + sd / 2, h) * achse_y * (Cylinder(SCHEIBE_M4["D"] / 2, sd) - Cylinder(SCHEIBE_M4["d"] / 2, 2))
    mutter = Location(Plane(origin=(0, nah + sd, h), x_dir=(1, 0, 0), z_dir=(0, 1, 0))) * fluegelmutter()
    return backen, aus, {"Gewindeeinsatz M4": einsatz, "Gewindestift M4x30": stift, "Scheibe M4": scheibe,
                         "Flügelmutter M4": mutter}


def zeige_normteil(teil: Part, name: str) -> None:
    """Kaufteil: Gewindeeinsätze aus Messing, alles andere Stahl verzinkt."""
    if "Gewindeeinsatz" in name:
        show(teil, name, color="#C9A55C", material="messing")
    else:
        show(teil, name, color="#AEB4BA", material="stahl")


step("Rollwagen: Lenksperren")
# Lenksperre (Druck), für alle vier Rollen gleich: Ein Klotz sitzt vor dem Drehkopf (zur Wagenmitte hin) und steckt oben
# formschlüssig zwischen Eckdom und Rippen. Zwei Wangen laufen außen an den Gabelschenkeln entlang, die Gabel kann so
# nicht mehr schwenken. Kronenende und Feststeller (hintere Rollen) bleiben frei, die Bremse ist weiter bedienbar.
# Befestigung: Im Klotz steckt oben ein Gewindeeinsatz M4 mit eingeklebtem Gewindestift M4 × 20; der Stift geht durch
# eine Bohrung Ø 4,5 in der Wagenplatte, oben zieht eine Flügelmutter mit Scheibe den Klotz an die Plattenunterseite.
# Einbau ohne Abschrauben der Rolle: Klotz samt Stift senkrecht von unten einschieben, Mutter von oben aufdrehen
# (geprüft in der Montageprüfung). Rahmen, Drehkopf und Gabel sind mit 0,2 mm Luft ausgespart.
x_a, x_b = drehkopf_d / 2 + 0.5, drehkopf_d / 2 + 24  # Klotz vor dem Drehkopf
breite_gabel = gabel_innen + 2 * blech  # Außenmaß über die Schenkel
wange_d2 = 3.2
z_wange = achse_z + 20  # Unterkante der Wangen
sperre_oben = platte_oben - platte_d - spiel  # liegt an der Plattenunterseite an
sperre_h = sperre_oben - rolle_h  # so tief greift die Sperre in Dom und Rippen
sperre = Pos((x_a + x_b) / 2, 0, z_wange) * Box(x_b - x_a, breite_gabel + 2 * (spiel + wange_d2),
                                                sperre_oben - z_wange, align=boden)
for sy in (1, -1):  # Wangen außen an den Schenkeln, bis unter die Krone
    sperre += Pos((8 + x_a + 1) / 2, sy * (breite_gabel / 2 + spiel + wange_d2 / 2), z_wange) * \
        Box(x_a + 1 - 8, wange_d2, krone_z - spiel - z_wange, align=boden)
x_e = (dom_d / 2 + spiel + x_b) / 2  # Einsatz mittig zwischen Eckdom und Klotzende: dort ist der Klotz voll
einsatz_tiefe_m4 = math.ceil((EINSATZ_M4["l"] + 1) / SCHICHT - 1e-9) * SCHICHT
sperre -= Pos(x_e, 0, sperre_oben + 1) * Cylinder(EINSATZ_M4["bohrung"] / 2, einsatz_tiefe_m4 + 1,
                                                  align=(Align.CENTER, Align.CENTER, Align.MAX))
sperr_stift_l = 20  # ISO 4026 M4 × 20
sperr_teile = {  # im System der Rolle
    "Gewindeeinsatz M4": Pos(x_e, 0, sperre_oben) * (Cylinder(EINSATZ_M4["bohrung"] / 2, EINSATZ_M4["l"],
                                                              align=(Align.CENTER, Align.CENTER, Align.MAX))
                                                     - Cylinder(2.05, 30)),
    "Gewindestift M4x20": Pos(x_e, 0, sperre_oben - EINSATZ_M4["l"] + 0.5) * Cylinder(2, sperr_stift_l, align=boden),
    "Scheibe M4": Pos(x_e, 0, platte_oben) * (Cylinder(SCHEIBE_M4["D"] / 2, SCHEIBE_M4["s"], align=boden)
                                              - Cylinder(SCHEIBE_M4["d"] / 2, 5)),
    "Flügelmutter M4": Pos(x_e, 0, platte_oben + SCHEIBE_M4["s"]) * fluegelmutter(),
}
lenksperren, sperr_griff, sperr_normteile = [], [], []
for lage in rollen_lagen:
    s_welt = lage * sperre
    sperr_griff.append(round((s_welt & (Pos(0, wagen_y, 0) * rahmen)).volume))
    lenksperren.append(aussparen(aussparen(s_welt, Pos(0, wagen_y, 0) * rahmen, spiel), lage * (gabel + rad), spiel))
    sperr_normteile.append({n: lage * t for n, t in sperr_teile.items()})
if min(sperr_griff) <= 0:
    raise ValueError("Eine Lenksperre greift nicht in den Rahmen")
for x, y in rollen_pos:  # Bohrungen Ø 4,5 in der Wagenplatte für die Gewindestifte
    xs = x - math.copysign(x_e, x)  # Einsatz liegt zur Wagenmitte hin (Rolle vorn um 180° gedreht)
    rahmen -= Pos(xs, y, platte_oben - platte_d - 1) * Cylinder(2.25, platte_d + 2, align=boden)
for i, s_teil in enumerate(lenksperren):
    show(s_teil, f"Rollwagen/Lenkrolle {i + 1}/Lenksperre (Druck)", color="#F28C28", material="petg")
    for n, t in sperr_normteile[i].items():
        zeige_normteil(t, f"Rollwagen/Lenkrolle {i + 1}/{n}")

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
# Als Kameraunterlage zu weich; er liegt im Lager neben den Rohrresten.
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
deckel_lage = Pos(0, rohre_rand + 60 + 200, 0)  # im Lager
show(deckel_lage * deckel, "Deckel 05090", color="#8C9196", material="polypropylen")

# Kugelschieber: schiebt den Bowlingball vor dem Kamerawagen her (Vorbild: Bowling-Ball-Rig von @newyorkkeygrip).
# Nur aus den vier ALFER-Rohren (ungekürzt oder abgelängt, nie verlängert) und 3D-Druckteilen, ohne Schrauben.
# - Zwei Seitenstangen tragen sich selbst: Sie stecken in vier Stangenhaltern unter dem Wagen, gleiten darin, lassen
#   sich herausziehen und werden mit Flügelmutterklemmen festgestellt (stangen_vorschub: wie weit sie vorstehen).
#   Die Halter sitzen unter den Eckzwickeln der Wagenplatte und sind von oben verschraubt (M6, siehe unten).
# - Der Ball berührt nur zwei Laufrollen: hinten die Schieberolle, vorn die Fangrolle. Ihre Achsen liegen quer, so
#   rollen sie mit der Balloberfläche ab; die leichte Einschnürung hält den Ball mittig.
# - Jede Rolle sitzt auf einer eigenen Querstange mit zwei Schlitten, die auf den Seitenstangen gleiten und mit
#   Flügelmuttern klemmen: hinten stellt den Abstand Ball–Kamera ein (kamera_ball), vorn das Spiel (vorn_luft).
# Lage im Wagen-System: x entlang der Wagenlänge (Schieberichtung +x), y quer, z nach oben.
rig_versatz = param("rig_versatz", 0)  # quer verschieben; 0 = am Wagen
kamera_ball = param("kamera_ball", 200)  # Wagenvorderkante (etwa Objektiv) bis Ballrückseite: Lage der Schieberolle
vorn_luft = param("vorn_luft", 4)  # Spiel zwischen Ball und Fangrolle: Lage der Fangrolle
stangen_vorschub = param("stangen_vorschub", 420)  # Seitenstangen ragen so weit vor die Wagenvorderkante
rollen_luft = param("rollen_luft", 2)  # Stangen und Halter zu Rad und Gabel der Lenkrollen
ball_luft = param("ball_luft", 5)  # Seitenstange zum Ball
boden_min = param("boden_min", 10)  # kleinster Abstand zum Boden für alles außer den Teilen am Ball
boden_ball = param("boden_ball", 4)  # am Ball: Rollen und Schlitten bleiben so tief, damit sie nicht ins Bild ragen
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
gleit = aussen_d / 2 + 0.25  # Halter und Schlitten gleiten auf den Seitenstangen (Passung „lose“, Ø +0,5)
lauf = aussen_d / 2 + 0.25  # Laufrollen drehen auf der Querstange
# rahmen_unten (Unterkante des Wagenrahmens) stammt aus der Lage des Rahmens auf den Lenkrollen (oben)


def rohr(l: float, achse: str) -> Part:
    """ALFER-Rohr der Länge l, mittig um den Ursprung, Achse 'x' oder 'y'."""
    r = Cylinder(aussen_d / 2, l) - Cylinder(aussen_d / 2 - wand, l + 2)
    return Rot(0, 90, 0) * r if achse == "x" else Rot(90, 0, 0) * r


def schraege_x(y: float) -> float:
    """x der Öffnungsschräge (Seite +x) in der Höhe y."""
    return oeff_l / 2 - oeff_fase_x + (oeff_b / 2 - abs(y)) / oeff_fase_y * oeff_fase_x


step("Kugelschieber: Stangenhalter")
# Stangenhalter (Druck) unter den Eckzwickeln der Wagenplatte, von oben verschraubt: je zwei Linsenkopfschrauben
# ISO 7380 M6 × 16 mit Karosseriescheibe 6,4 × 18 gehen durch Bohrungen Ø 6,6 in der Platte in Gewindeeinsätze M6, die
# von oben in die Säule eingeschmolzen sind (Befestigung: Schraube in Einsatz). Dort ist die Platte voll und frei von
# Rippen; den Eckdom spart der Halter mit Luft aus. Die Seitenstangen gleiten durch die Hülse und klemmen mit der
# Flügelmutterklemme: Schlitz unten, Flügelmutter zur Wagenmitte, von der Stirnseite her unter dem Wagen erreichbar.
# Druck: wie eingebaut, Säule oben; Querbohrungen als Tropfen.
xk = param("halter_x", 250)  # Halter unter den Eckzwickeln
schraube_dx, schraube_dy = 10, -3  # zwei Schrauben je Halter, 20 mm auseinander (Scheiben Ø 18), weg vom Eckdom
platte_unten = platte_oben - platte_d
scheibe_d, scheibe_h, schraube_l = 18, 1.6, 16
EINSATZ_M6 = {"bohrung": 8.2, "l": 12.7}  # ruthex M6: 12,7 × 8,7; Bohrung 8,0 + 0,2
einsatz_tiefe = math.ceil((EINSATZ_M6["l"] + 1) / SCHICHT - 1e-9) * SCHICHT  # Sackloch: Länge + 1 mm, im Raster
klemm_hoehe, klemm_h = klemm_oben()  # Gewindestift und Außenkante der Backen, ab der Stangenachse
halter, halter_normteile, bohrungen = [], [], []
schraube_m6 = Pos(0, 0, scheibe_h) * (Cylinder(5.25, 3.3, align=boden) + Pos(0, 0, -schraube_l) *
                                      Cylinder(3, schraube_l, align=boden))  # Kopf auf der Scheibe, Schaft nach unten
scheibe_m6 = Cylinder(scheibe_d / 2, scheibe_h, align=boden) - Cylinder(3.2, 5)
oben_ende = (Align.CENTER, Align.CENTER, Align.MAX)
einsatz_m6 = Cylinder(EINSATZ_M6["bohrung"] / 2, EINSATZ_M6["l"], align=oben_ende) - Cylinder(3.05, 40)  # Modell: Ø Bohrung
h_backen, h_aus, h_teile = fluegelklemme(30, spitze=-1)  # lokal +z zeigt nach unten
for sx in (1, -1):
    for sy in (1, -1):
        x, y = sx * xk, sy * ys
        oben_huelse = stangen_z + 11
        saeule_oben = platte_unten - spiel
        h = Pos(x, y, stangen_z + 11 / 2) * Box(30, 26, 11)  # Hülse über der Stange
        h += Pos(x, y, (oben_huelse - 0.5 + saeule_oben) / 2) * Box(40, 26, saeule_oben - oben_huelse + 0.5)  # Säule
        # Klemmbacken unter der Stange: lokal z nach unten, lokal y (Flügelmutter) zur Wagenmitte
        lage_k = Pos(x, y, stangen_z) * (Rot(180, 0, 0) if sy > 0 else Rot(0, 0, 180) * Rot(180, 0, 0))
        h += lage_k * h_backen
        h = aussparen(h, rahmen, spiel)  # Eckdom und Rippen mit Luft aussparen
        h -= Pos(x, y, stangen_z) * tropfen(gleit, 32, "x")  # Stange gleitet durch, herausziehbar
        h -= lage_k * h_aus
        teile_n = {n: lage_k * t for n, t in h_teile.items()}
        for i, dx in enumerate((-schraube_dx, schraube_dx)):
            sx_, sy_ = x + dx, y + sy * schraube_dy
            h -= Pos(sx_, sy_, saeule_oben + 1) * Cylinder(EINSATZ_M6["bohrung"] / 2, einsatz_tiefe + 1, align=oben_ende)
            bohrungen.append(Pos(sx_, sy_, platte_unten - 1) * Cylinder(3.3, platte_d + 2, align=boden))
            teile_n[f"Schraube M6x16 {i + 1}"] = Pos(sx_, sy_, platte_oben) * schraube_m6
            teile_n[f"Scheibe 6,4x18 {i + 1}"] = Pos(sx_, sy_, platte_oben) * scheibe_m6
            teile_n[f"Gewindeeinsatz M6 {i + 1}"] = Pos(sx_, sy_, saeule_oben) * einsatz_m6
        halter.append(h)
        halter_normteile.append(teile_n)
for b in bohrungen:  # Bohrungen Ø 6,6 in der Wagenplatte
    rahmen -= b
show(Pos(0, wagen_y, 0) * rahmen, "Rollwagen/Rahmen", color="#2F6DB5", material="polypropylen")

# Befestigung (Pflicht für jedes Teil, PLAN-BEDINGUNGEN.md B9) für den Rollwagen: Der Rahmen liegt auf den Laufplatten
# der Lenkrollen (die Rollenschraube steckt im Rückenloch und zieht ihn an), die Felge steckt auf der Achsschraube der
# Gabel, der Laufring sitzt formschlüssig auf der Felge, die Räder stehen auf dem Boden. Teile über ihre Namen aus show().
for i in range(4):
    rolle = f"Rollwagen/Lenkrolle {i + 1}"
    bed.verbinde("Rollwagen/Rahmen", f"{rolle}/Gabel", art="aufliegen")
    bed.verbinde(f"{rolle}/Schraube", "Rollwagen/Rahmen", art="steck")
    bed.verbinde(f"{rolle}/Felge", f"{rolle}/Gabel", art="steck")
    bed.verbinde(f"{rolle}/Rad", f"{rolle}/Felge", art="formschluss")
seite_x1 = wagen_l / 2 + stangen_vorschub  # Vorderende der Seitenstangen
seite_x0 = seite_x1 - laenge
if seite_x0 > -xk - 15 - 3:
    raise ValueError(f"stangen_vorschub {stangen_vorschub}: die Stangen kämen aus dem hinteren Halter; höchstens "
                     f"{math.floor(laenge - xk - 18 - wagen_l / 2)} mm")

step("Kugelschieber: Laufrollen")
rolle_l = min(laufrolle_l, 2 * (ys - 25 - 1) - 2 * 9)  # Platz zwischen den Schlitten, abzüglich Stellringe
rolle_r_ende = laufrolle_r + einschnuerung_r - math.sqrt(einschnuerung_r ** 2 - (rolle_l / 2) ** 2)
quer_z = rolle_r_ende + boden_ball  # Querstangen so tief, dass die Rollen gerade frei vom Boden laufen
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
z_unten = max(boden_ball, min(quer_z, stangen_z) - 11)
z_oben = stangen_z + klemm_h
schlitten, schlitten_normteile = {}, {}
# Klemme oben, Flügelmutter außen (lokal y = nah zeigt nach außen); Flügel in Ruhe längs der Stange, dann ragt nichts
# über die Backen hinaus
s_backen, s_aus, s_teile = fluegelklemme(schlitten_l)
for rolle, xq in (("Schieber", xq_hinten), ("Fänger", xq_vorn)):
    for sy, seite in ((1, "links"), (-1, "rechts")):
        y_innen, y_aussen = ys - 25, ys + KL_NAH
        z_mitte = max(quer_z, stangen_z)
        s = Pos(xq, sy * (y_innen + y_aussen) / 2, (z_unten + z_mitte) / 2) * Box(schlitten_l, y_aussen - y_innen,
                                                                                   z_mitte - z_unten)
        lage_k = Pos(xq, sy * ys, stangen_z) * (Rot(0, 0, 0) if sy > 0 else Rot(0, 0, 180))
        s += lage_k * s_backen
        s -= Pos(xq, sy * ys, stangen_z) * tropfen(gleit, schlitten_l + 2, "x")  # gleitet auf der Stange
        s -= Pos(xq, sy * ((y_innen + ys - 8) / 2 - 0.5), quer_z) * tropfen(bohr, ys - 8 - y_innen + 1, "y")
        s -= lage_k * s_aus
        for n, t in s_teile.items():
            schlitten_normteile[f"{n} {rolle} {seite}"] = lage_k * t
        schlitten[f"{rolle}schlitten {seite}"] = s

step("Kugelschieber: Rohre")
l_quer = math.floor(2 * (ys - 8))  # endet 2 mm vor der Bohrung der Seitenstange
zuschnitt = {  # Rohr-Nr. -> Stücke (Name, Länge); ganze Rohre bleiben ungekürzt
    1: [("Seitenstange links", laenge)],
    2: [("Seitenstange rechts", laenge)],
    3: [("Querstange hinten", l_quer), ("Querstange vorn", l_quer)],
    4: [],
}
rohrteile = {
    "Seitenstange links (Rohr 1)": Pos((seite_x0 + seite_x1) / 2, ys, stangen_z) * rohr(laenge, "x"),
    "Seitenstange rechts (Rohr 2)": Pos((seite_x0 + seite_x1) / 2, -ys, stangen_z) * rohr(laenge, "x"),
    "Querstange hinten (Rohr 3)": Pos(xq_hinten, 0, quer_z) * rohr(l_quer, "y"),
    "Querstange vorn (Rohr 3)": Pos(xq_vorn, 0, quer_z) * rohr(l_quer, "y"),
}
normteile = {}  # Schrauben, Scheiben, Einsätze und Flügelmuttern der Stangenhalter (neu zu beschaffen)
druckteile = {
    "Schieberolle": Pos(xq_hinten, 0, quer_z) * laufrolle,
    "Fangrolle": Pos(xq_vorn, 0, quer_z) * laufrolle,
}
for name, xq in (("hinten", xq_hinten), ("vorn", xq_vorn)):
    for sy, seite in ((1, "links"), (-1, "rechts")):
        druckteile[f"Stellring {name} {seite}"] = Pos(xq, sy * (rolle_l / 2 + 4.5), quer_z) * stellring
druckteile.update(schlitten)
for i, (h, (sx, sy)) in enumerate(zip(halter, [(1, 1), (1, -1), (-1, 1), (-1, -1)])):
    name = f"Stangenhalter {'vorn' if sx > 0 else 'hinten'} {'links' if sy > 0 else 'rechts'}"
    druckteile[name] = h
    for n, t in halter_normteile[i].items():
        normteile[f"{n} {name[14:]}"] = t

rig = Pos(0, wagen_y + rig_versatz, 0)
for name, teil in rohrteile.items():
    show(rig * teil, f"Kugelschieber/{name}", color="#C9CDD2", material="aluminium")
for name, teil in druckteile.items():
    show(rig * teil, f"Kugelschieber/{name} (Druck)", color="#F28C28", material="petg")
for name, teil in {**normteile, **schlitten_normteile}.items():
    zeige_normteil(rig * teil, f"Kugelschieber/{name}")
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
        "Fängerschlitten mit Rolle": ([t for k, t in {**druckteile, **schlitten_normteile}.items()
                                       if "Fänger" in k or k == "Fangrolle" or k.startswith("Stellring vorn")]
                                      + [rohrteile["Querstange vorn (Rohr 3)"]],
                                      (1, 0, 0), seite_x1 - xq_vorn + schlitten_l, 10),
        "Schieberschlitten mit Rolle": ([t for k, t in {**druckteile, **schlitten_normteile}.items()
                                         if "Schieber" in k or k.startswith("Stellring hinten")]
                                        + [rohrteile["Querstange hinten (Rohr 3)"]],
                                        (1, 0, 0), seite_x1 - xq_hinten + schlitten_l, 10),
        "Seitenstange links": ([rohrteile["Seitenstange links (Rohr 1)"]], (1, 0, 0), laenge + 40, 25),
        "Seitenstange rechts": ([rohrteile["Seitenstange rechts (Rohr 2)"]], (1, 0, 0), laenge + 40, 25),
    }
    for k in druckteile:
        if k.startswith("Stangenhalter"):  # erst die Schrauben samt Scheibe nach oben, dann der Halter mit Klemme
            for i in (1, 2):
                gruppen[f"Schraube {i} {k[14:]}"] = ([normteile[f"Schraube M6x16 {i} {k[14:]}"],
                                                      normteile[f"Scheibe 6,4x18 {i} {k[14:]}"]], (0, 0, 1), 30, 5)
    for k in druckteile:
        if k.startswith("Stangenhalter"):  # Einsätze und Klemme bleiben im Halter
            gruppen[k] = ([druckteile[k]] + [normteile[f"{n} {k[14:]}"] for n in h_teile]
                          + [normteile[f"Gewindeeinsatz M6 {i} {k[14:]}"] for i in (1, 2)], (0, 0, -1), 25, 4)
    namen = list(gruppen)
    for i, name in enumerate(namen):
        teile, richtung, weg, schritt = gruppen[name]
        noch_verbaut = {**fest, **{n: welt(zusammen(gruppen[n][0])) for n in namen[i + 1:]}}
        ausbauweg(name, welt(zusammen(teile)), richtung, weg, noch_verbaut, schritt)
    for i, lage in enumerate(rollen_lagen):  # Flügelmutter nach oben ab, dann die Sperre samt Stift nach unten heraus
        n_t = sperr_normteile[i]
        ausbauweg(f"Flügelmutter Lenksperre {i + 1}", zusammen([n_t["Flügelmutter M4"], n_t["Scheibe M4"]]), (0, 0, 1),
                  20, {"Rahmen": fest["Rahmen"], "Gewindestift": n_t["Gewindestift M4x20"]}, 2)
        stift_oben = n_t["Gewindestift M4x20"].bounding_box().max.Z
        ausbauweg(f"Lenksperre {i + 1}", zusammen([lenksperren[i], n_t["Gewindeeinsatz M4"], n_t["Gewindestift M4x20"]]),
                  (0, 0, -1), stift_oben - rolle_h + 10,
                  {"Rahmen": fest["Rahmen"], "Gabel und Rad": lage * (gabel + rad + feststeller)}, 4)
    if montage_befund:
        raise ValueError("Montage nicht möglich: " + "; ".join(montage_befund))

# Kamera: Sony-FX6-System (kamera_fx6.py) auf Kevins Manfrotto-Fluidkopf MVH502AH, so tief wie möglich.
# Ziel: Bei gerader Kamera liegt die Unterkante der Linse etwa auf Höhe der Randoberkante an der Wagenvorderseite.
# - Der Kopfschlitten (Druck) läuft auf den beiden Seitenstangen des Kugelschiebers und klemmt mit zwei
#   Flügelmutterklemmen; die Muttern zeigen nach außen und sind von der Längsseite unter dem Wagen erreichbar. Zwei
#   Querwände tragen die Last auf kurzem Weg in die Hülsen, die Bodenplatte hat eine Zentriermulde für die Kopfbasis.
#   Tragfähigkeit: Kopf und Kamera (rund 5,3 kg) biegen die zwei Rohre Ø 12 × 1 zwischen den Stangenhaltern
#   (500 mm) um 0,5 mm (eingespannt) bis 1,8 mm (gelenkig); Biegespannung rund 40 N/mm², für Aluminium unkritisch.
# - Ein gedruckter 3/8"-16-Gewindezapfen steckt mit rundem Flansch von unten im Schlitten; auf ihn wird der Kopf
#   geschraubt (wie auf ein Stativ). Der Kopf ragt durch die achteckige Öffnung nach oben.
# - Die Kamera sitzt ohne Tilta-Baseplate direkt auf der Schnellwechselplatte 504PLONG des Kopfes (deren 3/8"-Schraube
#   im Stativgewinde der FX6), sonst läge sie 14 mm höher.
# Druck Kopfschlitten: PETG, Bodenplatte auf dem Druckbett, 4 Wände, 40 % Gyroid; Bohrungen als Tropfen, Gleitspiel
# 0,5 mm im Durchmesser auf der Stange, Mulde 0,2 mm größer als die Kopfbasis, Flanschtasche 0,2 mm Spiel. Die Auflage
# ist 130 × 191 mm: über 180 mm verzieht sich PETG auf dem offenen P1P, deshalb mit Brim drucken.
import kamera_fx6
from geometrie import blackmagic_pocket6kpro as pocket
from geometrie import manfrotto_mvh502ah as mvh

kamera_vorschub = param("kamera_vorschub", 0)  # Objektivfront vor (+) oder hinter (−) der Wagenvorderkante
linse_ziel = param("linse_ziel", platte_oben + rand_h)  # gewünschte Höhe der Linsenunterkante bei gerader Kamera
kopf_teile_lokal = {k: v for k, v in mvh.manfrotto_mvh502ah().items() if k != "Schwenkarm"}
# Schwenkarm abgenommen: so tief stößt er in jeder 10°-Raste an Boden oder Wagen; geneigt wird über den Neigeknopf
kopf_basis_r = kopf_teile_lokal["Basis"].bounding_box().max.X  # Basis des MVH502AH (geometrie/manfrotto_mvh502ah.py)
kopf_hoehe = mvh.HOEHE  # Unterseite Basis bis Oberseite Schnellwechselplatte
kopfschlitten_l = param("kopfschlitten_l", 130)
boden_platte = param("schlitten_boden_d", 6)  # Bodenplatte des Kopfschlittens
mulde_t = 1  # Zentriermulde für die Kopfbasis
flansch_d, flansch_h = 30, 3  # Flansch des Gewindezapfens

step("Kamera: Lage")
cam_teile_alle, cam_bezug, cam_massen = kamera_fx6.fx6_system()
cam_teile = {k: v for k, v in cam_teile_alle.items() if k not in ("Tilta-Baseplate", "Rod links", "Rod rechts")}
cam_gesamt = sum(cam_massen[k] for k in cam_teile)
sp_x = sum(cam_massen[k] * cam_teile[k].center().X for k in cam_teile) / cam_gesamt  # Schwerpunkt im Kamera-System
objektiv_r = cam_teile["Objektiv"].bounding_box().size.Z / 2
front_lokal = cam_bezug["front"].position.X
kopf_x = wagen_l / 2 + kamera_vorschub - (front_lokal - sp_x)  # Schwenkachse unter dem Schwerpunkt der Kamera
platte_z0 = boden_min  # Unterseite des Kopfschlittens
kopf_basis_z = platte_z0 + boden_platte - mulde_t  # Kopfbasis sitzt in der Mulde
kamera_boden = kopf_basis_z + kopf_hoehe
achse_z_welt = kamera_boden + kamera_fx6.ACHSE_UEBER_BODEN
linse_unten = achse_z_welt - objektiv_r
# Verstellbereich in x: Kopfschlitten zwischen den Stangenhaltern (Säule 40 breit)
x_min = -xk + 20 + 2 + kopfschlitten_l / 2
x_max = xk - 20 - 2 - kopfschlitten_l / 2
vorschub_bereich = (math.ceil(x_min - kopf_x + kamera_vorschub), math.floor(x_max - kopf_x + kamera_vorschub))
if not x_min <= kopf_x <= x_max:
    raise ValueError(f"kamera_vorschub {kamera_vorschub}: Kopfschlitten stieße an die Stangenhalter; möglich "
                     f"{vorschub_bereich[0]} bis {vorschub_bereich[1]} mm")

step("Kamera: Kopfschlitten")
sl = kopfschlitten_l
huelse_unten = gleit + 5 * linie  # Wand unter der Stange
# Flügelmutterklemme oben, Mutter außen: von der Längsseite unter dem Wagen erreichbar (innen stünde der Kopf im Weg).
# Der Einsatz sitzt in der inneren Backe und wird von der Wagenmitte her eingeschmolzen.
kk_backen, kk_aus, kk_teile = fluegelklemme(sl)
kopfschlitten = Pos(kopf_x, 0, platte_z0) * Box(sl, 2 * (ys - 9), boden_platte, align=boden)  # Bodenplatte
for sx in (1, -1):  # Querwände von der Bodenplatte bis zur Stangenachse
    kopfschlitten += Pos(kopf_x + sx * (sl / 2 - 4), 0, platte_z0) * Box(8, 2 * ys, stangen_z - platte_z0, align=boden)
klemm_lagen = {}
for sy in (1, -1):  # Hülsen um die Seitenstangen; lokal y zeigt nach außen
    lage_k = Pos(kopf_x, sy * ys, stangen_z) * (Rot(0, 0, 0) if sy > 0 else Rot(0, 0, 180))
    kopfschlitten += lage_k * kk_backen
    kopfschlitten += lage_k * Pos(0, (KL_NAH - KL_FERN) / 2, -huelse_unten / 2) * \
        Box(sl, KL_NAH + KL_FERN, huelse_unten)  # Wand unter der Stange
    klemm_lagen[sy] = lage_k
kopf_klemme = {}
for sy, lage_k in klemm_lagen.items():
    kopfschlitten -= Pos(kopf_x, sy * ys, stangen_z) * tropfen(gleit, sl + 2, "x")
    kopfschlitten -= lage_k * kk_aus
    for n, t in kk_teile.items():
        kopf_klemme[f"{n} Kopfschlitten {'links' if sy > 0 else 'rechts'}"] = lage_k * t
kopfschlitten -= Pos(kopf_x, 0, kopf_basis_z) * Cylinder(kopf_basis_r + 0.2, mulde_t + 1, align=boden)  # Mulde
# Gewindezapfen 3/8"-16 (Druck, liegend gedruckt): runder Flansch Ø 30 steckt von unten in einer Tasche, der Kopf
# wird aufgeschraubt und zieht den Flansch an die Tasche (Befestigung: Formschluss und Gewinde)
from bd_warehouse.thread import IsoThread  # noqa: E402

zapfen_l = 9  # so tief greift er in die Kopfbasis
zapfen = Cylinder(flansch_d / 2, flansch_h, align=boden)
zapfen += Pos(0, 0, flansch_h) * Cylinder(3.9, kopf_basis_z - platte_z0 - flansch_h + zapfen_l, align=boden)
zapfen += Pos(0, 0, kopf_basis_z - platte_z0) * IsoThread(major_diameter=9.525, pitch=25.4 / 16, length=zapfen_l,
                                                          external=True, end_finishes=("fade", "fade"))
zapfen = Pos(kopf_x, 0, platte_z0) * zapfen
kopfschlitten -= Pos(kopf_x, 0, platte_z0 - 0.01) * Cylinder(flansch_d / 2 + spiel, flansch_h + spiel, align=boden)
kopfschlitten -= Pos(kopf_x, 0, platte_z0) * Cylinder(4.9 + spiel, 20, align=boden)
kopf_teile = {"Kopfschlitten": kopfschlitten, "Gewindezapfen 3/8 Zoll": zapfen, **kopf_klemme}

step("Kamera: Fluidkopf und Kamera")
# Fluidkopf Manfrotto MVH502AH (Inventar) auf dem Gewindezapfen; die Bohrung für den Zapfen ist auf Gewinde-
# Außenmaß erweitert, damit sich Zapfen und Kopf im Modell nicht durchdringen
kopf_lage = Pos(kopf_x, 0, kopf_basis_z)
fluidkopf_teile = {k: kopf_lage * v for k, v in kopf_teile_lokal.items()}
fluidkopf_teile["Basis"] -= Pos(kopf_x, 0, kopf_basis_z - 1) * Cylinder(4.9, zapfen_l + 1.5, align=boden)
fluidkopf = zusammen(list(fluidkopf_teile.values()))
kamera_lage = Pos(kopf_x - sp_x, 0, kamera_boden + kamera_fx6.ACHSE_UEBER_BODEN)

halter_welt = Pos(0, wagen_y, 0)
for name, t in kopf_teile.items():
    if name in kopf_klemme:
        zeige_normteil(halter_welt * t, f"Kamerahalter/{name}")
    else:
        show(halter_welt * t, f"Kamerahalter/{name} (Druck)", color="#F28C28", material="petg")
kopf_farben = {"Basis": "#2A2C30", "Schwenkteil": "#2A2C30", "Neigeteil": "#33363B", "Plattenaufnahme": "#2A2C30",
               "Schnellwechselplatte": "#5A5F66"}
for name, t in fluidkopf_teile.items():
    show(halter_welt * t, f"Kamerahalter/Fluidkopf MVH502AH/{name}", color=kopf_farben[name])
cam_farben = {"Gehäuse": "#2B2D30", "Tragegriff": "#2B2D30", "Monitor": "#1E1F21", "Handgriff": "#3A3C40",
              "V-Mount-Platte": "#3B3E43", "V-Mount-Akku": "#202225", "Objektiv": "#151617"}
for name, t in cam_teile.items():
    show(halter_welt * kamera_lage * t, f"Kamera FX6/{name}", color=cam_farben[name])

# Der Kamerakörper liegt tiefer als die Wagenplatte und muss in der Öffnung bleiben: Anstoßen am Rahmen, an den
# Stangenhaltern oder Lenksperren bricht ab und nennt den freien Bereich (nur dann wird er gesucht).
rahmen_welt = Pos(0, wagen_y, 0) * rahmen
bewegt = [halter_welt * t for t in [fluidkopf, *kopf_teile.values()]] + \
    [halter_welt * kamera_lage * t for t in cam_teile.values()]
halter_feste = [rig * t for n_h, t in druckteile.items() if n_h.startswith("Stangenhalter")]
halter_feste += [rig * t for t in normteile.values()]  # Klemmen, Schrauben und Einsätze der Stangenhalter
halter_feste += lenksperren + [t for n_t in sperr_normteile for t in n_t.values()]


def kopf_frei(dx: float) -> bool:
    for t in bewegt:
        tt = Pos(dx, 0, 0) * t
        if ueberlappen(tt, rahmen_welt) and (tt & rahmen_welt).volume > 0.05:
            return False
        if any(ueberlappen(tt, h) and (tt & h).volume > 0.05 for h in halter_feste):
            return False
    return True


if not kopf_frei(0):
    grenzen = []
    for richtung in (-1, 1):  # von kamera_vorschub = 0 aus nach hinten und vorn halbieren
        lo, hi = 0.0, 400.0
        while hi - lo > 1:
            m = (lo + hi) / 2
            lo, hi = (m, hi) if kopf_frei(richtung * m - kamera_vorschub) else (lo, m)
        grenzen.append(round(richtung * lo))
    raise ValueError(f"kamera_vorschub {kamera_vorschub}: Kopf oder Kamera stößt an den Wagen; frei etwa "
                     f"{grenzen[0]} bis {grenzen[1]} mm")

if montage_pruefen:  # Kamera nach oben, Kopf vom Zapfen nach oben; der Schlitten kommt nach den Seitenstangen heraus
    welt_k = lambda t: halter_welt * t  # noqa: E731
    fest_k = {"Rahmen": Pos(0, wagen_y, 0) * rahmen}
    for i, lage in enumerate(rollen_lagen):
        fest_k[f"Lenkrolle {i + 1}"] = lage * (gabel + rad + feststeller)
        fest_k[f"Lenksperre {i + 1}"] = lenksperren[i]
    for n_r, t in {**rohrteile, **druckteile}.items():
        fest_k[f"Schieber {n_r}"] = rig * t
    kamera_k = zusammen([kamera_lage * t for t in cam_teile.values()])
    unterbau = zusammen(list(kopf_teile.values()))
    ausbauweg("Kamera", welt_k(kamera_k), (0, 0, 1), 260,
              {**fest_k, "Fluidkopf": welt_k(fluidkopf), "Kopfschlitten": welt_k(unterbau)}, 10)
    ausbauweg("Fluidkopf", welt_k(fluidkopf), (0, 0, 1), zapfen_l + 150,
              {**fest_k, "Kopfschlitten": welt_k(unterbau)}, 10)
    ohne_stangen = {n: h for n, h in fest_k.items() if "Seitenstange" not in n}  # Stangen sind vorher heraus
    # danach seitlich zwischen den Lenkrollen hindurch unter dem Wagen heraus
    ausbauweg("Kopfschlitten", welt_k(unterbau), (0, 1, 0), wagen_b / 2 + ys + 60, ohne_stangen, 10)
    if montage_befund:
        raise ValueError("Montage nicht möglich: " + "; ".join(montage_befund))

step("Inventar: Blackmagic Pocket 6K Pro")
# Zweite Kamera mit Sigma 18-35 Art (EF), im Lager neben dem Deckel (geometrie/blackmagic_pocket6kpro.py)
pocket_lage = Pos(500, rohre_rand + 60 + 200, pocket.ACHSE_UEBER_BODEN)  # steht auf dem Boden
pocket_teile = dict(pocket.bmpcc_6k_pro())
pocket_teile["Objektiv Sigma 18-35"] = Pos(pocket.AUFLAGEMASS, 0, 0) * pocket.sigma_18_35_art_ef()
for name, t in pocket_teile.items():
    show(pocket_lage * t, f"Lager/Blackmagic Pocket 6K Pro/{name}", color="#2B2D30" if name != "Monitor" else "#1E1F21")

step("Inventar: Zuschnitt und Reste")
reste = {}
for nr, stuecke in zuschnitt.items():
    rest = laenge - sum(l for _, l in stuecke) - saege * len(stuecke)
    if rest < 0 and rest + saege >= 0:
        rest = 0  # das letzte Stück ist das Rohrende, ein Schnitt weniger
    if rest < 0:
        raise ValueError(f"Rohr {nr} reicht nicht: {[l for _, l in stuecke]} mm plus Schnitte > {laenge} mm")
    reste[nr] = rest
step("Inventar: Reste")
# Am alten Lagerplatz der Rohre: was vom Zuschnitt übrig bleibt
for nr, rest in reste.items():
    y = (nr - 1 - (anzahl - 1) / 2) * teilung
    name = f"Rohr {nr} unbenutzt" if not zuschnitt[nr] else f"Rohr {nr} Rest {rest:.0f} mm"
    if rest > 0:
        show(Pos(-laenge / 2 + rest / 2, y, aussen_d / 2) * rohr(rest, "x"), f"Inventar/{name}", color="#C9CDD2",
             material="aluminium")
