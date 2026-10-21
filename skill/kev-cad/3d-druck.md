# 3D-Druckteile konstruieren (Bambu Lab P2S, FDM)

Zusatz zum Skill `kev-cad`. Gilt für jedes neue Druckteil (`lager.druckteil(form, name, material)`). Zuerst nach
diesen Regeln konstruieren, dann prüfen lassen (`pruefe_druckteil`, Abschnitt 15) und die Hinweise abarbeiten.
Standard: Düse 0,4 mm, Schicht 0,2 mm, PETG. Zahlen mit Quelle in eckigen Klammern (Liste am Ende);
**EW** = Erfahrungswert, nicht direkt belegt, bewusst vorsichtig. Die Daten stehen auch maschinenlesbar in
`kevcad_kernel/druck/regeln.py`.

## 1 Drucker

| Größe | Wert |
|---|---|
| Bauraum | 256 × 256 × 256 mm [B-FAQ]; 5 mm Rand für Brim lassen, mit AMS kommt ein Prime Tower 35 mm dazu [BS-P] |
| Düse | 0,4 mm gehärteter Stahl (auch CF-Filamente); 0,2/0,6/0,8 möglich [B-FAQ, BS-P] |
| Linienbreite | außen 0,42, innen und Füllung 0,45, erste Schicht 0,50 mm [BS-P] |
| Schichthöhe | 0,20 Standard, 0,08–0,28; erste Schicht 0,20 [BS-P] |
| Profil „0.20 Standard“ | 2 Wände, 5 Deck- (≥ 1 mm) und 3 Bodenschichten, 15 % Grid, Stützen aus, Brim 5 mm [BS-P] |
| Stützenschwelle | 30° vom Waagrechten bei 0,20 mm (15° bei 0,08 … 35° bei 0,24) = Überhang bis 60° von der Senkrechten [BS-P] |
| Elefantenfuß-Ausgleich | 0,15 mm im Profil [BS-P] |
| Temperaturen | Düse bis 300 °C, Bett bis 110 °C; Kammer geschlossen, **nicht aktiv beheizt** (passiv ca. 50 °C) [B-FAQ, CK-P2S] |
| AMS | AMS 2 Pro (Combo), AMS HT, AMS 1. Gen.; kein AMS Hub [B-FAQ] |

Überhangwinkel in dieser Datei immer **von der Senkrechten**: 0° = Wand, 90° = waagrechte Unterseite.

## 2 Wände, Merkmale, Z-Maße

Wandstärke = Vielfaches der Linienbreite. Bambu rechnet den Bahnabstand als Breite − Schicht · (1 − π/4) [BS-Flow]:

| Bahnen | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Wand bei 0,2 mm Schicht | 0,42 | **0,83** | **1,23** | **1,64** mm |

| Regel | Wert |
|---|---|
| Mindestwand | 0,8 mm (2 Bahnen) [H-Info]; darunter druckt der Slicer eine Bahn oder nichts („Dünne Wände erkennen“ ist aus) [BS-P] |
| tragende Wand | 1,2 mm (3 Bahnen), besser 1,6 (4) [H-Info, X, HR] |
| Mindestmerkmal (Rippe, Steg) | 2 mm [H-Info], Untergrenze 1,2 [X] |
| Stift | Ø ≥ 3 mm [H-Info]; unter Ø 5 nur Wandbahnen, schwach, Fuß verrunden [H-FDM] |
| Bohrung | Ø ≥ 2 mm [H-Info]; unter 1 mm setzt sie zu [X] – kleine Bohrungen nachbohren |
| waagrechte Platte | ≥ 3 Schichten (0,6 mm); 1 Schicht hält nicht |
| Z-Maße | Vielfache der Schichthöhe (0,2): Absätze, Taschentiefen, Plattendicken; sonst rundet der Slicer um bis zu 0,1 mm |
| Toleranz Dienstleister | ±0,5 %, mindestens ±0,5 mm [H-Info, X]; der P2S schafft eng konstruiert ca. ±0,1–0,2 mm (EW) |

## 3 Ausrichtung und Festigkeit

Ein FDM-Teil ist in Schichtrichtung (Z) am schwächsten. Beim Konstruieren schon festlegen, wie es auf dem Bett liegt.

| Material | Zug in Z / in XY | Quelle |
|---|---|---|
| PLA | 31 / 63 MPa ≈ 50 % (45° geneigt: 40 MPa) | [CK-45] |
| PETG | ≈ 39 % | [CK-45] |
| ABS | 54 % offen, 59 % passiv geschlossen (wie P2S), 75 % mit 65 °C Kammer | [CK-Kammer] |
| ASA | ≈ 38 % | [CK-45] |
| PC | ≈ 68 % | [CK-45] |

- Hauptlast (Zug, Biegung, Hebel, Haken, Laschen) in die Schichtebene legen; Haken und Stifte flach statt stehend.
- Wände bringen mehr Festigkeit als Füllung: Funktionsteile mit 3–4 Wänden und 20–40 % Füllung drucken [HR, CK-Grad].
- Innenkanten verrunden (R ≥ 0,5 · Wanddicke), Kerben an Schichtübergängen reißen zuerst [BAY, H-FDM].
- Auflage: große ebene Fläche aufs Bett, möglichst wenig Höhe, keine Stützen, waagrechte Bohrungen senkrecht stellen.
  Das wägt die automatische Ausrichtung der Prüfung ab; Lastrichtung kennt sie nicht – dann Ausrichtung vorgeben.

## 4 Überhänge, Brücken, Stützen vermeiden

| Material | Überhang ohne Stütze | Brücke gut / max. | Quelle |
|---|---|---|---|
| PLA | 60° | 10 / 30 mm | [BS-P]; Brücke max. EW |
| PLA-CF, PETG, ABS, ASA, PA-CF | 55° | 10 / 20–25 mm | EW; PETG überbrückt schlechter als PLA [P-PETG] |
| PC, PA | 50° | 10 / 15 mm | EW |
| TPU 95A | 45° | 5 / 8 mm | sehr schlechte Brücken und Überhänge [P-Flex] |

Faustregel ohne Materialwissen: 45° und 10 mm Brücke, unter 5 mm ohne Durchhang [H-FDM, H-Info, X, HR]. Feinere Schichten
erlauben steilere Überhänge (Bambu: 75° bei 0,08 mm) [BS-P]. Waagrecht frei auskragend: höchstens ca. 1 mm (EW).

So kommt man ohne Stützen aus:

- **Unterseiten fasen, oben runden:** Eine Rundung an der Unterkante beginnt waagrecht (90° Überhang); eine 45°-Fase
  druckt sauber [P-Mod, H-FDM].
- **Waagrechte Bohrungen als Tropfen:** 45°-Spitze nach oben, Spitze r · √2 über der Mitte (BOSL2-Standard); oder oben
  ca. 0,3 mm abflachen [HR]. Kleine Bohrungen (Ø ≤ 3) gehen meist auch rund, werden aber oben 0,1–0,3 mm enger.
- **Gegenbohrung/Senkung zur Bettseite:** Opferschicht (Bohrung beginnt eine Schicht über der Senkung, nach dem Druck
  durchstechen) oder Brückentrick (Schicht 1 Schlitz in Bohrungsbreite, Schicht 2 Quadrat, dann rund) [HR].
- **Gestufte Überhänge:** Kragarme mit 45°-Schräge oder Treppen aus kurzen Brücken (< 5 mm) unterfüttern.
- **Decken über Hohlräumen:** unter 10 mm Spannweite bleiben, sonst Rippe einziehen oder als 45°-Dach/Bogen formen.
- **Teil drehen oder teilen**, bevor man Stützen einplant. Stützen kosten Zeit, Material und Oberfläche.

## 5 Bettseite: Elefantenfuß, Auflage, Verzug

- **Elefantenfuß:** Die erste Schicht wird breitgequetscht, Außenmaße unten +0,1–0,2 mm, Bohrungen enger [P-EF]. Bambu
  gleicht 0,15 mm aus [BS-P]. Unterkanten 0,4–0,5 mm × 45° fasen (EW), Bohrungsränder an der Bettseite 0,3–0,5 mm.
- **Auflage:** mindestens ca. 25 mm² (EW), sonst Brim; schlanke Teile (Höhe > 10 · √Auflage) wackeln (EW).
- **Verzug** entsteht durch Schwund beim Abkühlen; er wächst mit Länge der Auflage, spitzen Ecken und dichter Füllung.

| Material | Verzug | Schwund linear | kritisch ab Auflagelänge (EW) |
|---|---|---|---|
| PLA, PLA-CF, TPU | kaum | 0,2–0,3 % (EW) | – |
| PETG | gering, „does not shrink or warp“ [P-PETG] | ca. 0,4 % (EW) | 200 mm |
| ASA | mittel, weniger als ABS [P-ASA] | 0,4–0,6 % [RJG] | 100 mm |
| ABS | stark [P-ABS] | 0,5–0,7 % [RJG], FDM bis 1–2 % [P-ABS] | 80 mm |
| PC | stark [P-PC] | 0,8 % [RJG] | 80 mm |
| PA | stark, CF-Typen deutlich weniger [P-PA] | 0,5–2 % [RJG] | 80 mm (PA-CF 150) |

Gegen Verzug: Ecken der Grundfläche mit R ≥ 4 mm, Bodenfase ca. 0,3 mm [HR]; Mouse Ears (Scheiben Ø 10–15 mm,
0,4 mm hoch) oder Brim 5–10 mm; große Flächen in Rippen auflösen; bei PC weniger Füllung [P-PC]. Auf dem P2S Bett
10 min vorheizen und Tür zu, weil die Kammer nicht aktiv heizt. Bambu skaliert Schwund nicht (100 %) [BS-F, B-Shr].

## 6 Bohrungen, Passungen, Spiele

Gedruckte Bohrungen fallen zu klein aus: Polygon-Effekt [NOP] und Schmelzbahn. CNC Kitchen hat bei Ø 4 mm im Mittel
−0,25 mm gemessen [CK-DS]. Bambu gleicht Bohrungen ab Werk nicht aus (X-Y-Lochkompensation 0); kalibrieren mit einer
M6-Schraube in 0,1-mm-Schritten [B-XY].

| Nenn-Ø | < 3 | 3–10 | 10–30 | > 30 mm |
|---|---|---|---|---|
| Zugabe im CAD (senkrecht, EW nach [CK-DS]) | +0,3 | +0,25 | +0,2 | +0,15 |

Passungen: Zugabe auf den Wellen-Ø für die gedruckte Bohrung (Welle Metall oder Druckteil, ohne Slicer-Kompensation):

| Passung | Ø-Zugabe | Quelle |
|---|---|---|
| Presspassung (hält ohne Kleber) | 0 bis +0,05 (Bohrung druckt ja 0,25 kleiner) | EW nach [CK-DS] |
| fest, von Hand fügbar | +0,15 | EW, [HR] 0,1 eng |
| Spielpassung (dreht, gleitet) | +0,3 | [P-Mod] ≥ 0,3 |
| lose / bewegliche Teile | +0,5 | [H-Info, X] |
| Print-in-Place (in einem Stück gedruckt) | Spalt 0,3–0,5 je Seite, in Z ≥ 0,3 | [P-Mod, H-Info], Z EW |
| Bambu-Schnittwerkzeug (Stifte, Schwalbenschwanz) | 0,1 | [BS-Cut] |

Schraubendurchgang wie im Skill (ISO 273 mittel: M3 3,4 · M4 4,5 · M5 5,5 · M6 6,6) – das hat schon genug Spiel.

## 7 Gewinde: Einsätze, Muttern, Schrauben

**Gewindeeinsätze** (Heat-Set), Maße in mm. Bohrung gerade, nicht konisch, keine Fase; Sackloch mindestens Länge + 1 mm;
Durchgangsloch nicht länger als der Einsatz [CK-Tips, RX]. Einsetzen mit Lötkolben 10–20 °C über Drucktemperatur
(PLA 225, PETG 245, ABS 265 °C), 90 % einschmelzen, Rest eindrücken [CK-Tips].

| Größe | ruthex L × Außen-Ø | ruthex Bohrung | CNC Kitchen L | CNC Kitchen Bohrung | Wand min. |
|---|---|---|---|---|---|
| M2 | 4,0 × 3,6 | 3,2 | 3,0 | 3,2 | 1,3 |
| M2,5 | 5,7 × 4,6 | 4,0 | 4,0 | 4,0 | 1,6 |
| M3 (kurz) | 5,7 (4,0) × 4,6 | 4,0 | 5,7 (3,0) | 4,0 | 1,6 |
| M3 Voron | 4,0 × 5,0 | 4,4 | 4,0 | 4,4 | 1,3–1,6 |
| M4 (kurz) | 8,1 (4,0) × 6,3 | 5,6 | 8,1 (4,0) | 5,7 | 2,1 |
| M5 (kurz) | 9,5 (5,8) × 7,1 | 6,4 | 9,5 (5,8) | 6,5 | 2,6 |
| M6 (kurz) | 12,7 (6,8) × 8,7 | 8,0 | 12,7 | 8,1 | 3,3 |
| M8 | 12,7 × 10,1 | 9,6 | 12,7 | 9,7 | 4,5 |
| M10 | 12,7 × 12,6 | 12,0 | 12,7 | 12,0 | 6,0 |

Quellen [RX, CK-Tab]. CNC Kitchen 2026: bei M3 ist **4,2 mm im CAD** der beste Kompromiss (Einsatz steckt vor, kein
Grat, ca. 90 % Festigkeit), Faustregel Nennbohrung + 0,2–0,3 [CK-DS]. Ausreißkraft M3 in PLA bis ca. 1400 N.

**Muttern** (ISO 4032) als Sechskanttasche: Schlüsselweite + 0,3, Tiefe Höhe + 0,3, aufs Schichtraster runden (EW,
Praxis 0,2–0,4). Eckmaß im CAD = SW / cos 30° = 1,155 · SW. Waagrecht liegende Tasche mit Flachseite oben (kurze Brücke
statt 60°-Spitze); eingeschlossene Tasche (Schlitz von der Seite) mit Opferschicht über der Tasche.

| | M2 | M2,5 | M3 | M4 | M5 | M6 | M8 | M10 |
|---|---|---|---|---|---|---|---|---|
| SW | 4 | 5 | 5,5 | 7 | 8 | 10 | 13 | 16 |
| Höhe | 1,6 | 2,0 | 2,4 | 3,2 | 4,7 | 5,2 | 6,8 | 8,4 |

Festigkeit M3 in PETG [CK-Nut]: direkt eingeschraubt 1 Nm / 118 kg, Mutter seitlich 2 Nm / 86 kg, Mutter von unten
2 Nm / 166 kg, Gewindeeinsatz 3 Nm / 119 kg. Für oft gelöste Schrauben Einsatz oder Mutter, nie direkt.

**Selbstschneidende Schrauben** direkt ins Druckteil (Kernloch im CAD, senkrecht gedruckt; liegend +0,1):

| | M2 | M2,5 | M3 | Tubus-Ø | Einschraubtiefe |
|---|---|---|---|---|---|
| Bambu BT in PLA [B-BT] | 1,80 | 2,17 | 2,57 | 2 · d | 2 · d |
| Bambu BT in PETG [B-BT] | 1,77 | 2,07 | 2,55 | 2 · d | 2 · d |

Kunststoffschrauben (Würth WÜPLAST) [W]: Kernloch ABS 0,8 · d, ASA 0,78 · d, PA/PET 0,75 · d, PC 0,85 · d;
Tubus-Ø 1,85–2,5 · d, Einschraubtiefe 1,7–2,2 · d. Gedruckte Gewinde erst ab ca. M5 sinnvoll [HR].

## 8 Schnapphaken und Filmscharniere

Zulässige Auslenkung (Hakentiefe) eines Biegebalkens nach Bayer [BAY], l = Armlänge, h = Dicke an der Wurzel:

- rechteckig, konstanter Querschnitt: **y = 0,67 · ε · l² / h**
- Dicke zur Spitze auf h/2 verjüngt: y = 1,09 · ε · l² / h (gleichmäßigere Spannung, über 60 % mehr Weg)
- Fügekraft P = b · h² · E · ε / (6 · l)

| Material | ε einmalig (FDM, EW) | Bezug |
|---|---|---|
| PLA | 1,5 % | spröde, für Schnapphaken ungeeignet [H-Snap] |
| PLA-CF, PA-CF | 1,0–1,5 % | steif und spröde |
| ABS, ASA | 2,0 % | Bayer PC/ABS 2,5 % [BAY] |
| PETG | 2,5 % | |
| PC | 3,0 % | Bayer PC 4 % (Spritzguss) [BAY] |
| PA | 4,0 % | zäh, beste Wahl |

Bei häufigem Lösen ca. 60 % davon [BAY]. Beispiel PETG, l = 15, h = 2: y = 0,67 · 0,025 · 225 / 2 = 1,9 mm.
Weitere Regeln: l ≥ 5 · h (EW); Wurzel verrunden R ≈ 0,6 · h [BAY], mindestens 0,5 · h [H-Snap]; Breite ≥ 5 mm,
Spiel 0,5 mm [H-Snap]; Einführschräge 30° [BAY]; Rückhaltefläche 90° = unlösbar, ≤ 45° = lösbar (EW). Haken **flach**
drucken (biegt in der Schichtebene), nie stehend in Z [H-Snap].

**Filmscharniere:** 0,4–0,6 mm dick, mindestens 2 Schichten, als durchgehende Bahnen quer über das Scharnier;
so legen, dass die Scharnierbreite Schicht für Schicht aufgebaut wird (oft stehend) [H-LH]. Material: PA (Nylon), TPU,
bedingt PETG; PLA und ABS ungeeignet [H-LH, MH]. Spritzguss-Maße 0,25–0,38 mm sind für FDM zu dünn [MH].

## 9 Text und Prägungen

| Regel | Wert |
|---|---|
| Strichbreite erhaben | ≥ 0,9 mm (2 Bahnen) [HR] |
| Strichbreite vertieft | ≥ 0,5 mm [HR, X] |
| Höhe/Tiefe | ≥ 0,5 mm [X], im Schichtraster: 0,6 (3 Schichten) |
| Zeichenhöhe | ≥ 3,5 mm, besser 5 mm [X] |

Fette, serifenlose Schrift. Am besten auf der Oberseite (sauberste Fläche) oder an senkrechten Wänden. Auf der
Bettseite tief vertieft (≥ 0,6) und gespiegelt lesbar planen; der Elefantenfuß verschmiert feine Striche.

## 10 Große Teile teilen

- Ebene Fügeflächen, die beim Drucken auf dem Bett liegen oder oben abschließen. Trennfuge dorthin, wo keine Last quer
  zur Fuge wirkt; zusätzlich verschrauben, wenn es tragen muss.
- Ausrichten mit Passstiften: Metallstift Ø 3–5 in Bohrung + 0,1 [BS-Cut], je Seite ≥ 1,5 · d tief (EW); gedruckte
  Stifte erst ab Ø 5 [H-FDM]. Bambu-Schnittwerkzeug: Stift, Dübel oder Schnapper, Toleranz 0,1 mm [BS-Cut].
- Schwalbenschwanz: Toleranz 0,1 mm in Breite und Tiefe [BS-Cut], Schräge in der Schichtebene.
- Kleben: glatte, fettfreie Flächen, leicht anschleifen [P-Mod]; Fase 0,3 mm an der Fuge verdeckt Versatz (EW).

## 11 Materialien

| Material | Düse / Bett (P2S-Profil) | Kammer | Trocknen | AMS | Besonderheit |
|---|---|---|---|---|---|
| PLA | 220 / 55 °C | Deckel ab Bett 45 °C öffnen | 55 °C 8 h | ja | weich ab ca. 55 °C |
| PLA-CF | 230 / 55 °C | wie PLA | 55 °C 8 h | ja | steif, spröde |
| PETG | 250 / 70 °C | geschlossen (Lagenhaftung) | 65 °C 12 h | ja | zäh, gut für Clips |
| ABS | 270 / 90 °C | zu, vorheizen | 80 °C 8 h | ja | Verzug, Lagentrennung |
| ASA | 270 / 100 °C | zu, vorheizen | 80 °C 8 h | ja | UV-fest, für draußen |
| PC | 280 / 100 °C | zu, vorheizen | 80 °C 8 h, Pflicht | ja | starker Verzug |
| PA / PA-CF | 275–290 / 100 °C, Klebestift | zu, vorheizen | 80 °C 8–12 h, Pflicht | AMS HT | Maße ändern sich mit Feuchte |
| TPU 95A | 230 / 35 °C | offen | 70 °C 8 h, Pflicht | **nein** | siehe unten |

Quellen [BS-F, B-Fil, P-…]. Harzdruck (Standardharz) kann der P2S nicht; die Prüfung rechnet dafür nur grob.

**TPU 95A:** Bambu druckt TPU ab 85A [B-TPU]. Nicht über AMS 2 Pro oder AMS 1; nur AMS HT mit eigenem TPU-Ausgang oder
externe Spule („TPU for AMS“ ist die Ausnahme) [B-TPU]. Max. 3,6 mm³/s (ca. 40 mm/s), Flow-Dynamics-Kalibrierung aus,
Lagerung unter 20 % rF [BS-F, B-TPU]. Konstruktiv: keine Brücken und Überhänge [P-Flex], Wand ≥ 1,2 mm, Passungen mit
0,3–0,5 mm Spiel (EW); Teil so legen, dass nichts überhängt.

## 12 Mehrfarbe mit dem AMS

- Farbwechsel passieren schichtweise: Farbgrenzen in Z aufs Schichtraster legen; farbige Bereiche ≥ 2 Bahnen breit
  (0,9 mm) und ≥ 2 Schichten hoch (EW).
- Prime Tower ist an (35 mm breit) und wächst bis zum letzten Farbwechsel [BS-P, B-PT]. Wechsel nach unten legen spart:
  im Bambu-Beispiel 14,8 → 9,1 g Turm [B-Waste]. Spülen ins Innere/Füllung möglich, Spülfaktor 0,8–0,9 [B-Waste].
- Günstigste Mehrfarbe: Schrift oder Logo erhaben (0,6 mm) auf der Oberseite – nur die obersten Schichten wechseln.
- In model.py je Farbe ein eigener Körper (eigenes `show`/`druckteil`), im Slicer dem Filament zuordnen.

## 13 Druckeinstellungen, die zur Konstruktion gehören

- Funktionsteile: 3–4 Wände (1,2–1,6 mm), 20–40 % Füllung (Gyroid), statt Standard 2 Wände / 15 % [BS-P, HR].
- Dünnwandige Teile bestehen nur aus Wänden: Wandstärke = Vielfaches der Bahnbreite (Abschnitt 2).
- Feinere Schicht (0,12–0,16) für steilere Überhänge und feine Details, gröbere (0,24) für große, einfache Teile.
- Lochkompensation einmal kalibrieren [B-XY]; Elefantenfuß-Ausgleich 0,15 bleibt an.
- ABS/ASA/PC/PA: trocknen, vorheizen, Brim; PETG/PLA: Bett sauber, ohne Brim.

## 14 Rezepte (build123d)

Werkzeugkörper werden vom Teil abgezogen (`teil -= Pos(...) * werkzeug`). Alle Rezepte sind getestet
(`kernel/tests/test_druck_rezepte.py` führt jeden Block mit `# Rezept:` aus und prüft das Ergebnis).

```python
# Rezept: Grundlagen
import math
from build123d import *

UNTEN = (Align.CENTER, Align.CENTER, Align.MIN)   # auf die XY-Ebene stellen
SCHICHT = 0.2


def z_raster(h, schicht=SCHICHT):
    """Z-Maß aufs Schichtraster runden."""
    return round(round(h / schicht) * schicht, 4)
```

```python
# Rezept: Tropfenbohrung
def tropfenbohrung(d, laenge, kappe=None):
    """Werkzeug: waagrechte Bohrung entlang Y, mittig im Ursprung, 45°-Spitze nach +Z (Spitze r·√2 über der Mitte).
    kappe: Spitze so hoch über dem Kreis flach abschneiden (kurze Brücke statt Spitze), z. B. 0.0 oder 0.3."""
    r = d / 2
    q = r / math.sqrt(2)
    profil = Circle(r) + Polygon((-q, q), (0, r * math.sqrt(2)), (q, q), (0, 0), align=None)
    if kappe is not None:
        profil -= Pos(0, r + kappe + d) * Rectangle(3 * d, 2 * d)
    return extrude(Plane.XZ * profil, amount=laenge / 2, both=True)

# entlang X: Rot(0, 0, 90) * tropfenbohrung(...)
```

```python
# Rezept: Bettfase
def bettfase(teil, fase=0.5):
    """Alle Unterkanten (auch Bohrungsränder) 45° fasen gegen Elefantenfuß. Oben darf es rund sein."""
    return chamfer(teil.edges().group_by(Axis.Z)[0], length=fase)
```

```python
# Rezept: Passungsparameter
SPIEL = {"press": 0.0, "fest": 0.15, "spiel": 0.3, "lose": 0.5}   # Ø-Zugabe der gedruckten Bohrung


def bohrung_fuer(welle_d, passung="spiel"):
    """CAD-Ø der Bohrung für eine Welle/einen Stift mit Nenn-Ø welle_d."""
    return welle_d + SPIEL[passung]
```

```python
# Rezept: Gewindeeinsatz-Tasche
EINSATZ = {  # ruthex: Bohrung, Länge, Außen-Ø, Mindestwand (mm)
    "M2": (3.2, 4.0, 3.6, 1.3), "M2.5": (4.0, 5.7, 4.6, 1.6), "M3": (4.0, 5.7, 4.6, 1.6),
    "M4": (5.6, 8.1, 6.3, 2.1), "M5": (6.4, 9.5, 7.1, 2.6), "M6": (8.0, 12.7, 8.7, 3.3), "M8": (9.6, 12.7, 10.1, 4.5),
}


def einsatz_tasche(groesse="M3", plus=0.2):
    """Werkzeug: Sackloch für einen Gewindeeinsatz, Öffnung bei z = 0 nach unten, Tiefe = Länge + 1 mm (im Raster).
    plus=0.2: CNC-Kitchen-Empfehlung (M3 → 4,2); plus=0 für die Herstellerbohrung."""
    d, laenge, _, _ = EINSATZ[groesse]
    tiefe = math.ceil((laenge + 1) / SCHICHT - 1e-9) * SCHICHT
    return Pos(0, 0, 1) * Cylinder((d + plus) / 2, tiefe + 1, align=(Align.CENTER, Align.CENTER, Align.MAX))


def einsatz_dom(groesse="M3", hoehe=None):
    """Dom ab z = 0 mit Mindestwand um den Einsatz."""
    _, laenge, aussen, wand = EINSATZ[groesse]
    return Cylinder(aussen / 2 + wand, hoehe or laenge + 2, align=UNTEN)
```

```python
# Rezept: Mutterntasche
MUTTER = {"M2": (4.0, 1.6), "M2.5": (5.0, 2.0), "M3": (5.5, 2.4), "M4": (7.0, 3.2), "M5": (8.0, 4.7),
          "M6": (10.0, 5.2), "M8": (13.0, 6.8)}   # ISO 4032: Schlüsselweite, Höhe


def mutter_tasche(groesse="M3", spiel=0.3, fase=0.4, schlitz=0.0):
    """Werkzeug: Sechskanttasche von z = 0 nach unten, Flachseiten parallel zu X.
    schlitz=0: oben offen, 1 mm Überstand, Einführschräge fase.
    schlitz>0: eingeschlossen, endet bei z = 0, um schlitz in +X verlängert (Mutter seitlich einschieben);
    das Schraubenloch darüber erst eine Schicht höher beginnen lassen (Opferschicht)."""
    sw, m = MUTTER[groesse]
    sw += spiel
    tiefe = math.ceil((m + spiel) / SCHICHT - 1e-9) * SCHICHT
    sechskant = RegularPolygon(sw / 2, 6, major_radius=False)   # Radius = halbe Schlüsselweite
    tasche = extrude(sechskant, amount=-tiefe)
    if schlitz:
        return tasche + Box(schlitz, sw, tiefe, align=(Align.MIN, Align.CENTER, Align.MAX))
    tasche += extrude(sechskant, amount=1)
    if fase:
        tasche += extrude(RegularPolygon(sw / 2 + fase, 6, major_radius=False), amount=-fase, taper=45)
    return tasche
```

```python
# Rezept: Gegenbohrung mit Opferschicht
def gegenbohrung_unten(d_loch, d_kopf, t_kopf, laenge, art="opfer"):
    """Werkzeug: Senkung von der Bettseite (z = 0 nach oben) plus Bohrung.
    art="opfer": eine Schicht bleibt stehen, nach dem Druck durchstechen.
    art="bruecke": Brückentrick – Schicht 1 Schlitz (Bohrungsbreite), Schicht 2 Quadrat, dann rund."""
    w = Pos(0, 0, -1) * Cylinder(d_kopf / 2, t_kopf + 1, align=UNTEN)
    if art == "opfer":
        return w + Pos(0, 0, t_kopf + SCHICHT) * Cylinder(d_loch / 2, laenge, align=UNTEN)
    e = 0.01   # Überlappung, damit keine Häute entstehen
    w += Pos(0, 0, t_kopf - e) * Box(d_loch, d_kopf, SCHICHT + e, align=UNTEN)
    w += Pos(0, 0, t_kopf + SCHICHT - e) * Box(d_loch, d_loch, SCHICHT + e, align=UNTEN)
    return w + Pos(0, 0, t_kopf + 2 * SCHICHT - e) * Cylinder(d_loch / 2, laenge, align=UNTEN)
```

```python
# Rezept: Schnapphaken
DEHNUNG = {"pla": 1.5, "petg": 2.5, "abs": 2.0, "asa": 2.0, "pa": 4.0, "pc-filament": 3.0}   # % einmalig


def schnapphaken(laenge=15, dicke=2.0, breite=6, material="petg", oft_loesen=False, einfuehr=30, halt=90):
    """Haken mit Sockel, flach in der XY-Ebene (federt in Y, Haken nach +Y), Höhe = breite (Z). So drucken, wie er liegt.
    Hakentiefe y = 0,67 · ε · l² / h (Bayer), Wurzel R = 0,6 · h. Gibt (teil, y) zurück."""
    eps = DEHNUNG[material] / 100 * (0.6 if oft_loesen else 1.0)
    y = 0.67 * eps * laenge ** 2 / dicke
    xb = laenge - y / math.tan(math.radians(einfuehr))                  # Einführschräge
    xc = xb - (y / math.tan(math.radians(halt)) if halt < 90 else 0.0)   # Rückhaltefläche
    arm = Pos(-0.5, 0, 0) * Box(laenge + 0.5, dicke, breite, align=(Align.MIN, Align.MIN, Align.MIN))
    zahn = extrude(Polygon((laenge, dicke - 0.01), (xb, dicke + y), (xc, dicke - 0.01), align=None), amount=breite)
    sockel = Pos(-5, -2, 0) * Box(5, dicke + 4, breite, align=(Align.MIN, Align.MIN, Align.MIN))
    teil = arm + zahn + sockel
    wurzel = teil.edges().filter_by(Axis.Z).filter_by(
        lambda e: abs(e.center().X) < 1e-3 and -1e-3 < e.center().Y < dicke + 1e-3)
    return fillet(wurzel, 0.6 * dicke), y
```

```python
# Rezept: Teilung mit Passstiften
def teilen(teil, z, stifte, d=4.0, tiefe=6.0, spiel=0.1, fase=0.3):
    """Teil bei Höhe z waagrecht teilen; beide Hälften mit Bohrungen für Metall-Passstifte Ø d (Bohrung d + spiel,
    je Seite tiefe) und Fase an der Fuge. Beide Hälften so drucken, wie sie liegen (Schnittfläche eben)."""
    ebene = Plane.XY.offset(z)
    unten = split(teil, bisect_by=ebene, keep=Keep.BOTTOM)
    oben = split(teil, bisect_by=ebene, keep=Keep.TOP)
    for x, y in stifte:
        loch = Pos(x, y, z) * Cylinder((d + spiel) / 2, 2 * tiefe)
        unten, oben = unten - loch, oben - loch
    unten = chamfer(unten.edges().group_by(Axis.Z)[-1], fase)   # Fuge oben am unteren Teil
    oben = chamfer(oben.edges().group_by(Axis.Z)[0], fase)      # Fuge unten am oberen Teil (zugleich Bettfase)
    return unten, oben
```

```python
# Rezept: Beispiel Halter (Gewindeeinsätze, Tropfenbohrung, Bettfase, Spielpassung)
halter = fillet(Box(40, 24, 16, align=UNTEN).edges().filter_by(Axis.Z), 4)
halter = bettfase(halter, 0.5)
halter -= Pos(0, 0, 8) * tropfenbohrung(bohrung_fuer(5, "spiel"), 50)     # Welle Ø 5 quer, Spitze nach oben
halter -= [Pos(x, 0, 16) * einsatz_tasche("M3") for x in (-13, 13)]      # zwei M3-Einsätze von oben
# in model.py: show(lager.druckteil(halter, "Halter", material="petg"), "Halter")
```

## 15 Prüfung im Kernel

```python
from kevcad_kernel.druck import pruefe_druckteil, als_warnungen
ergebnis = pruefe_druckteil(halter, material="petg")           # ausrichtung=None: automatisch
ergebnis = pruefe_druckteil(halter, "petg", ausrichtung="-z")  # wie modelliert; "+x" = +X-Seite aufs Bett,
                                                               # Flächennummer, Richtungsvektor oder Rot(...)
```

Rückgabe: `ok` (kein Fehler), `zusammenfassung`, `ausrichtung` (`unten`, `drehung` für `Rot(*drehung) * form`,
`liegt_auf`, `begruendung`, `kandidaten`), `hinweise` (je `art`, `schwere` fehler/warnung/hinweis, `text` = Befund +
Abhilfe, `flaeche` = Index in `form.faces()`, `flaechen`, `punkt`, `werte`), `kennzahlen` (Stützfläche mm², Auflage,
Höhe, Schichten, Abmessungen, Bauraum-Ausnutzung, Masse voll, Laufzeit) und `druckhinweise` (Material, Festigkeit).

| `art` | prüft |
|---|---|
| `bauraum` | passt in 256³ mit Rand, notfalls diagonal; sonst Fehler mit Teilungsvorschlag |
| `auflage` | Auflage < 25 mm², Kante/Punkt, schlanke Teile |
| `ueberhang` | Flächen steiler als die Materialgrenze, nicht auf dem Bett (schmale ≤ 1 mm ausgenommen) |
| `bruecke`, `kragarm`, `freie_unterseite` | waagrechte Unterseiten: Spannweite in einer Brückenrichtung, frei auskragend, ohne Halt |
| `gegenbohrung_unten`, `opferschicht` | Senkung zur Bettseite ohne bzw. mit Opferschicht |
| `waagrechte_bohrung`, `bohrung_klein`, `bohrung_mass` | Tropfenform nötig, Ø < 2 / < 1 mm, glattes Nennmaß ohne Zugabe |
| `stift` | Stifte Ø < 3 mm (stehend: Bruch zwischen Schichten) |
| `wand` | Wandstärke (Strahlen ins Material, nur parallele Gegenfläche): < 1 Bahn Fehler, < 0,8 Warnung, < 1,2 Hinweis; waagrecht < 1/2/3 Schichten |
| `elefantenfuss`, `rundung_unten` | scharfe Unterkanten, Rundungen an der Bettkante |
| `verzug`, `verzug_ecken` | lange Auflage und spitze Ecken bei ABS, ASA, PC, PA (PETG ab 200 mm) |
| `schichtraster` | waagrechte Flächen außerhalb des 0,2-mm-Rasters |

## Quellen

- [B-FAQ] Bambu Lab Wiki, P2S FAQ – https://wiki.bambulab.com/en/p2s/manual/p2s-faq
- [BS-P], [BS-F] Bambu Studio, Prozess- und Filamentprofile P2S – https://github.com/bambulab/BambuStudio/tree/master/resources/profiles/BBL
- [BS-Cut] Bambu Studio, Schnittwerkzeug (GLGizmoAdvancedCut) – https://github.com/bambulab/BambuStudio/tree/master/src
- [BS-Flow] Bambu Studio, Flow.cpp – https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Flow.cpp
- [B-Shr] Bambu Lab Wiki, 3D Prints Shrinkage – https://wiki.bambulab.com/en/knowledge-sharing/3d-prints-shrinkage
- [B-XY] Bambu Lab Wiki, XY Hole/Contour Compensation – https://wiki.bambulab.com/en/software/bambu-studio/xy-hole-contour-compensation
- [B-Fil] Bambu Lab Wiki, Filament Guide – https://wiki.bambulab.com/en/general/filament-guide-material-table
- [B-TPU] Bambu Lab Wiki, TPU Printing Guide – https://wiki.bambulab.com/en/knowledge-sharing/tpu-printing-guide
- [B-PT] Bambu Lab Wiki, Prime Tower – https://wiki.bambulab.com/en/software/bambu-studio/parameter/prime-tower
- [B-Waste] Bambu Lab Wiki, Reduce Waste – https://wiki.bambulab.com/en/software/bambu-studio/reduce-wasting-during-filament-change
- [B-BT] Bambu Lab Store, BT2.6 Self-Tapping Screw – https://eu.store.bambulab.com/products/bt2-6-socket-head-cap-self-tapping-screw-shcs
- [P-Mod] Prusa, Modeling with 3D printing in mind – https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135
- [P-EF] Prusa, Elephant foot compensation – https://help.prusa3d.com/article/elephant-foot-compensation_114487
- [P-PETG], [P-ABS], [P-ASA], [P-PC], [P-PA], [P-Flex] Prusa-Materialseiten – https://help.prusa3d.com/article/petg_2059 ·
  https://help.prusa3d.com/article/abs_2058 · https://help.prusa3d.com/article/asa_1809 ·
  https://help.prusa3d.com/article/polycarbonate-pc_165812 · https://help.prusa3d.com/article/polyamide-nylon_167188 ·
  https://help.prusa3d.com/article/flexible-materials_2057
- [H-FDM] Hubs, How to design parts for FDM – https://www.hubs.com/knowledge-base/how-design-parts-fdm-3d-printing/
- [H-Info] 3D Hubs, Design Rules for 3D Printing – https://www.core77.com/posts/74401/Design-Rules-for-3D-Printing
- [H-Snap] Hubs, Snap-fit joints – https://www.hubs.com/knowledge-base/how-design-snap-fit-joints-3d-printing/
- [H-LH] Hubs, Living hinges – https://www.hubs.com/knowledge-base/how-design-living-hinges-3d-printing/
- [X] Xometry, Quick Design Guide FDM – https://xometry.pro/en/?p=154421
- [HR] Hydra Research, Design Rules – https://www.hydraresearch3d.com/design-rules
- [RX] ruthex, Gewindeeinsätze – https://www.ruthex.de/collections/gewindeeinsatze
- [CK-Tab] CNC Kitchen Store, Heat-Set Inserts – https://cnckitchen.store
- [CK-DS] CNC Kitchen, Are our heat-set insert datasheets wrong? – https://www.cnckitchen.com/blog/are-our-heat-set-insert-datasheets-wrong
- [CK-Tips] CNC Kitchen, Tips and tricks for heat-set inserts – https://www.cnckitchen.com/blog/tips-and-tricks-for-heat-set-inserts
- [CK-Nut] CNC Kitchen, Helicoils, threaded inserts and embedded nuts – https://www.cnckitchen.com/blog/helicoils-threaded-insets-and-embedded-nuts-in-3d-prints-strength-amp-strength-assessment
- [CK-45] CNC Kitchen, Stop printing flat – https://www.cnckitchen.com/blog/stop-printing-flat-the-45-secret-for-stronger-parts
- [CK-Kammer] CNC Kitchen, Does a heated chamber make prints stronger? – https://www.cnckitchen.com/blog/does-a-heated-chamber-make-your-3d-prints-stronger
- [CK-Grad] CNC Kitchen, Gradient infill – https://www.cnckitchen.com/blog/gradient-infill-for-3d-prints
- [CK-P2S] CNC Kitchen, Bambu Lab P2S review – https://www.cnckitchen.com/blog/bambu-lab-p2s-review
- [BAY] Bayer MaterialScience, Snap-Fit Joints for Plastics – https://cdn.sparkfun.com/assets/home_page_posts/1/4/1/0/Plastic_Snap_fit_design.pdf
- [MH] MatterHackers, Living hinge design – https://www.matterhackers.com/news/living-hinge:--design-guidelines-and-material-selection
- [W] Würth, DINO Kapitel 9 – https://www.wuerth-industrie.com/web/media/de/pictures/wuerthindustrie/technikportal/dinokapitel/Kapitel_09_DINO_techn_Teil.pdf
- [NOP] nophead, Polyholes – https://hydraraptor.blogspot.com/2011/02/polyholes.html
- [RJG] Schwindmaße gängiger Kunststoffe (Spritzguss) – https://rjcmold.com/wp-content/uploads/Shrinkage-Rates-for-Common-Plastics.pdf
- Tropfenform-Standard (45°): BOSL2 – https://github.com/BelfrySCAD/BOSL2/wiki/shapes3d.scad
