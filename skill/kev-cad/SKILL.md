---
name: kev-cad
description: Leitfaden für Kev CAD, Kevins nativen CAD-Viewer auf dem Mac (MCP-Server „kevcad“, Werkzeuge wie run, screenshot, measure). Verwenden, sobald Kevin in Kev CAD ein 3D-Modell bauen, ändern, vermessen, ansehen oder exportieren will – Halter, Gehäuse, Bauteile, Möbel, Baugruppen als model.py mit build123d, die sich live im Viewer aufbauen. Auch bei „bau mir …“, „mach die Bohrung größer“, „wie weit ist das vom Rand weg“, „zeig mir die Lasche von der Seite“, „was hab ich angeklickt“, „exportier als STEP/STL/3MF“ in einem Kev-CAD-Projekt, ebenso bei Lagerteilen (Rohre, Profile, Platten, Holz, Schrauben aus dem Katalog), Stückliste, Zuschnitt, Gewicht und Kosten („was kostet das“, „wie viele Stangen“), 3D-Druckteilen, Zukaufteilen per Shop-Link, Herstellernummer oder EAN („bau diesen Auszug ein: https://…“, Hersteller-CAD, STEP aus den Downloads übernehmen), Kameras („setz die FX6 mit 35 mm auf den Wagen“, „zeig mir ihr Bild“, „rendere das Kamerabild in 4K“) und Animationen („lass den Wagen rollen“, „Kollision prüfen“, „mach ein Video aus Sicht der FX6“).
---

# Kev CAD

Ein Modell ist `model.py` im Projektordner (build123d, Millimeter, Z nach oben). Der Kernel führt die Datei aus, jedes
`show()` erscheint sofort im Viewer, Kevin sieht beim Bauen zu. Die Datei ist die Quelle der Wahrheit: Änderungen immer
dort, nie nur per `execute`.

## Konstruktionsregeln (Kevin, 21.10.2026, gilt immer)

Jedes Design folgt den 15 Regeln in [konstruktion.md](konstruktion.md), vor der ersten Zeile Geometrie lesen.
Optimiert wird für Einzelstücke und kleine Stückzahlen; notwendige Funktionen, Schnittstellen und Sicherheit bleiben
erhalten. Kurz: Anforderungen vor Geometrie (fehlende Angaben erfragen, Annahmen kennzeichnen), Wirkprinzip
hinterfragen, Weglassen vor Optimieren, Gesamtaufwand bewerten, Standardteile vor Sonderteilen, Druckorientierung
früh, Kräfte führen statt Material häufen, Montage und Wartung mitkonstruieren, nichts als geprüft behaupten, was
nicht nachgewiesen ist. Auf „prüfe das Design kritisch“ folgt das Design-Review mit den fünf wichtigsten
Verbesserungen im festen Format (konstruktion.md).

## Prüfen vor dem Fertigmelden (Kevin, 21.10.2026, gilt immer)

Nichts darf physikalisch unmöglich sein. Kev CAD prüft jeden Lauf selbst (Durchdringung, Schweben, Standsicherheit,
Einbaubarkeit), `run` wartet auf das Ergebnis; `pruefen` zeigt alles samt Stand und Montage. Befunde beheben, nicht nur
melden:

- **Keine Durchdringungen:** Teile dürfen sich berühren, aber nicht ineinander stecken (gemeldet ab 0,001 mm³
  Schnittvolumen und 0,01 mm Tiefe). Verbindungselemente sind keine Ausnahme: Scheibe in Scheibe, Kopf in Scheibe,
  Schraube in einer zu kleinen Durchgangsbohrung. Die einzige Ausnahme erkennt Kev CAD selbst: echter
  Gewindeeingriff (Schraube in Mutter oder Kern-/Gewindeloch, gleiche Achse, nur im Gewindeband).
- Befunde kommen als isError mit Ort, Volumen, Tiefe und einer Lösung je Befund. Kevin sieht die Teile rot und das
  Schnittvolumen als roten Körper; Export ist gesperrt, bis alles behoben ist.
- **Beheben, nicht wegerklären:** Spiel oder Bohrung vorsehen, Teil verschieben, Maß korrigieren, dann wieder `run`.
  Gewollte Überlappungen (Presspassung, nachgiebiger Schaum) nur nach Rückfrage bei Kevin und mit Grund in model.py:
  `erlaubt_ueberlappung(a, b, grund="Presspassung, mit Kevin abgestimmt")` (`from kevcad import erlaubt_ueberlappung`;
  a und b als Name aus `show()`, Gruppe oder Form). Ohne Grund gilt sie nicht.
- **Nichts schwebt, alles ist befestigt:** Jedes Teil berührt sein Gegenstück oder steht auf dem Boden, und zu jedem
  Teil ist konstruiert, **wie es befestigt ist** (Schraube mit Bohrung und Gewinde bzw. Mutter, Klemmung, Steckverbindung,
  Formschluss, Kleben oder nur Aufliegen). Die Befestigung steht als Kommentar am Teil und lässt sich mit Werkzeug
  montieren. Nie Teile einfach in den Raum setzen. Mit `bed.verbinde(...)` (Abschnitt „Teile über Bedingungen
  setzen“) prüft Kev CAD bei jedem Lauf, dass die Befestigung physisch da ist und alles über Verbindungen am Boden
  hängt. Modelle ganz ohne Bedingungen prüft die eingebaute Prüfung trotzdem auf Schweben: Gruppen ohne Kontakt zum
  Boden kommen mit Fallweg („fiele 12 mm auf Rahmen“); Spielpassungen bis 0,5 mm zählen als Verbindung, „berührt“
  heißt bis 0,05 mm. Boden ist der tiefste Punkt oder `boden(z)`. Hängt etwas an Wand oder Decke:
  `befestigt(teil, grund="an der Wand verschraubt")`, nur nach Rückfrage bei Kevin.
- **Steht sicher:** Je Gruppe auf dem Boden rechnet die Prüfung Masse (Materialdichte, sonst angenommen 1 g/cm³ mit
  Hinweis), Schwerpunkt, Standfläche und Kippwinkel. Liegt der Schwerpunkt außerhalb: Fehler; unter 3° Kippwinkel:
  Warnung. Lösung: Standfläche verbreitern, Schwerpunkt senken, Gegengewicht.
- **Lässt sich einbauen:** siehe „Montagegerecht konstruieren“.
- **Nachgiebige Teile** (Material mit `nachgiebig` im Katalog: PE-Schaum, Gummi, TPU) dürfen bis zur halben Dicke
  zusammengedrückt werden; das ist ein Hinweis („verformt“), kein Fehler.
- **Bewegungsraum:** Alles, was man bedient oder was sich bewegt (Hebel, Klappen, Griffe, Schlitten, Räder, Lenkrollen),
  muss seinen ganzen Weg ohne Kollision schaffen, mit Platz für Finger und Werkzeug. Die Quelle sind die **Gelenke in
  model.py** mit `bereich=…` und `bedienung=…` (Kevin, 22.10.2026); `run` prüft sie bei jedem Lauf (Befunde
  „Bewegungsraum“ mit freiem Bereich). `<projekt>/bewegungen.json` gilt nur noch für Teile ohne Gelenk. Zum Ausloten
  weiter Bereiche einmalig `cd "/Users/kevinschwed/Code Experiments/Kev CAD/kernel" && .venv/bin/python
  tools/check_motion.py "<Projektordner>" --teile … --drehen …`. Reicht der freie Bereich nicht für die Bedienung, wird
  umkonstruiert, nicht der Bereich verkleinert. Hat das Projekt eine Animation, zusätzlich `kollision_pruefen(name)`
  für jede Animation (siehe „Animation“).
- **Druckteile:** Die Druckprüfung läuft bei jedem Lauf für jedes `lager.druckteil` mit; `druckpruefung` zeigt
  Ausrichtung, Kennzahlen und alle Hinweise (siehe 3d-druck.md).
- Befestigung (`bed.verbinde`), Bewegungsraum, Schweben, Standsicherheit und Einbaubarkeit prüft Kev CAD bei jedem
  Lauf; `pruefen` zeigt das ganze Ergebnis, `montage_reihenfolge` die Einbaufolge.

## Montagegerecht konstruieren (Kevin, 21.10.2026, gilt immer)

Teile nicht irgendwo platzieren, sondern so, dass man sie vernünftig einbauen kann. Die Prüfung zerlegt jedes Modell
gedanklich (Montage durch Demontage): Ein Teil muss sich auf geradem Weg (±X, ±Y, ±Z, Achsen von Bohrungen und Bolzen,
erklärte Richtungen) aus dem Rest herausziehen lassen, dann das nächste. Umgekehrt ist das die Montagereihenfolge mit
Einführrichtung je Teil (`montage_reihenfolge`; Kevin sieht sie im Prüfband unter „Montage“ Schritt für Schritt).

- **Einbaulage mitdenken:** Jedes Teil so konstruieren und platzieren, wie es eingesetzt wird; Reihenfolge und
  Einführrichtung beim Konstruieren festlegen und im Kommentar nennen.
- **Schrauben:** nur entlang ihrer Achse einführbar (Durchgangsbohrung bis zum Kopf), und beim Einsetzen braucht das
  Werkzeug Platz über dem Kopf (Inbus: Ø Kopf + 2 mm, mindestens 30 mm bzw. 5·d lang; Steckschlüssel: Ø 1,6·SW + 4 mm;
  sonst Gabelschlüssel von der Seite). Fehlt der Platz: Durchgang für das Werkzeug, Schraube von der anderen Seite oder vor dem Hindernis einsetzen.
- **Spiel vorsehen**, damit Teile ohne Gewalt hineingehen (Druckteile 0,2–0,3 mm je Seite).
- **Keine eingesperrten Teile:** Ein Teil in einem geschlossenen Gehäuse ist nicht einbaubar; Gehäuse teilen (Deckel),
  Öffnung vorsehen.
- **Unlösbares vermeiden:** Bolzen mit zwei Köpfen aus einem Stück, Ringe auf Achsen ohne Ende, Klemmbolzen, deren
  Kopf und Zunge beide nicht durch die Bohrung passen: lösbar konstruieren (Achse als eigenes Teil, Sicherungsring,
  Teilung).
- **Befunde beheben statt wegerklären.** Erklärungen nur, wo sie stimmen, und im Code kommentiert:
  `montage("Rollwagen/Lenkrolle 1", baugruppe=True)` für Zukaufteile, die fertig montiert geliefert werden;
  `montage(clip, schnappt=True)` für Schnappverbindungen; `montage(mutter, eingedruckt=True)` für Muttern, die beim
  Druck eingelegt werden (Druckpause); `montage(teil, richtung="-z", nach=[...], werkzeug="inbus 6")` für Richtung,
  Reihenfolge und Werkzeug eigener Teile.

## Teile über Bedingungen setzen (Kevin, 21.10.2026, gilt immer)

Wie in CAD-Programmen hängt jedes Teil über Bedingungen an seinem Gegenstück, nicht an frei gewählten Koordinaten.
Feste Regel neben Prüfungen, Druckregeln und Inventar-Regel: **Teile werden mit `platziere` gesetzt, jedes Teil ist mit
`verbinde` befestigt, Bewegliches ist ein Gelenk mit Bereich.** Kev CAD prüft alle Bedingungen nach jedem Lauf gegen
die echte Geometrie; verletzte sind Befunde wie eine Durchdringung (`run` isError, rot im Viewer, Export gesperrt).

```python
import kevcad.bedingungen as bed   # als Modul: kollidiert nicht mit eigenen Namen wie spiel, winkel, boden

platte = Box(200, 120, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Pos(60, 0, 5) * Cylinder(4.5, 20)
show(platte, "Halter/Platte")
klotz = Box(40, 30, 20)                                    # im eigenen System bauen, dann setzen
klotz = bed.platziere(klotz,
                      bed.auf((klotz, "unten"), (platte, "oben")),            # Fläche auf Fläche
                      bed.mittig((klotz, "mitte"), (platte, "mitte"), "xy"),   # mittig in X und Y
                      bed.parallel((klotz, "vorn"), (platte, "vorn")))        # nicht verdreht
show(klotz, "Halter/Klotz")
schraube = lager.teil("schraube-iso4762-m8").verbauen(laenge=25, name="Halter/Schraube")
schraube = bed.platziere(schraube, bed.in_bohrung(schraube, bed.bezug(platte, "bohrung", nahe=(60, 0, 0))))
show(schraube, "Halter/Schraube")
bed.verbinde(klotz, platte, art="kleben")                 # Befestigung (Pflicht für jedes Teil)
bed.verbinde(platte, bed.boden, art="aufliegen")
wand = param("wand", 2.0, min=1.2)                        # Grenzen: 0,8 ist ein Befund mit Soll, Ist und Lösung
```

- **Bezüge** über Namen, nie über Flächennummern: als Tupel `(teil, "unten")` oder `bed.bezug(teil, …)` mit
  `oben`/`unten` (±Z), `rechts`/`links` (±X), `hinten`/`vorn` (±Y, vorn = −Y), `mitte`, `schwerpunkt`, `achse`
  (größter Zylinder), `achse_x/y/z`, `bohrung` (mit `nahe=(x, y, z)`), `teil`; eigene Auswahl
  `bed.bezug(teil, "Auflage", teil.faces().sort_by(Axis.Z)[0])` oder `lambda t: …`, dazu `Plane`, `Axis`, `Location`
  und Bezugspunkte aus dem Katalog; Teile auch über ihren Namen aus `show()` (`bed.verbinde("Gestell/Bein 1", …)`).
  `bed.boden` ist die Ebene z = 0. **Der erste Bezug gehört zum Teil, das sich anpasst** (bei `platziere` das bewegte).
- **Montage:** `auf` (Flächen gegenüber, `abstand=` für Luft), `buendig`, `konzentrisch`, `parallel`, `senkrecht`,
  `abstand(a, b, wert)`, `winkel(a, b, grad)`, `tangential` (Zylinder/Kugel an Ebene oder Zylinder), `mittig(…, "xy")`,
  `in_bohrung(schraube, bohrung, gewinde=False)` (konzentrisch, Kopf liegt auf, Durchmesser ISO 273 bzw. Kernloch und
  Länge geprüft). Teile im eigenen System bauen, mit `bed.platziere(teil, …)` setzen, danach erst bohren ist erlaubt
  (die Prüfung findet das Teil wieder); was danach noch verschoben wird, verschiebt seine Bezüge mit.
- **Gelenke** (Grundlage build123d-Joints, Freiheitsgrade für Animation und Prüfung): `drehgelenk(achse_bewegt,
  achse_fest, winkel=0, bereich=(min, max))`, `schiebegelenk(…, weg=0, bereich=…)`, `zylindergelenk`, `kugelgelenk`,
  `fest`. Mit `bereich` prüft jeder Lauf den ganzen Weg auf Kollision (`mitbewegt=[…]` für Teile, die mitfahren,
  `ignorieren=[…]`); Bedienteile mit `bedienung="finger" | "hand" | "werkzeug"` oder `freiraum=mm` am `griff`.
  `gelenk.fuer_animation()` liefert Art, Achse und Grenzen für `animation.gelenk`.
- **Befestigung (B9):** jedes Teil `bed.verbinde(a, b, art="schraube" | "klemmung" | "steck" | "formschluss" |
  "kleben" | "aufliegen", mit=[schraube, mutter, scheibe])`. Geprüft wird, dass es die Verbindung wirklich gibt
  (Kontakt bzw. Spielpassung bis 0,5 mm; bei Schrauben fluchtende Bohrungen in beiden Teilen, Kopf und Mutter liegen
  auf) und dass alle Teile über Verbindungen am Boden hängen. Gelenke, `in_bohrung` und `auf` von oben zählen mit.
  Kevin, 22.10.2026: Solange ein Modell kein `verbinde` nutzt, ist fehlende Befestigung nur ein Hinweis; sobald es
  `verbinde` nutzt, ist jede fehlende Angabe ein Fehler mit Exportsperre. Bei neuen Modellen gleich alles verbinden.
- **Bewegungen:** Die Gelenke in model.py sind die Quelle dafür, was sich wie bewegt (Bereich, Bedienung,
  mitbewegte Teile). `<projekt>/bewegungen.json` gilt nur noch für Teile ohne Gelenk; Einträge für Teile mit Gelenk
  werden übergangen (Kevin, 22.10.2026).
- **Maße:** `param(name, wert, min=, max=)`, `bed.gleich(a, b)`, `bed.spiel(deckel, gehaeuse, min=0.2)`,
  `bed.min_abstand(a, b, wert)`, `bed.min_wand(teil, 1.2)`.
- **Prüfen:** `run` meldet Befunde mit Soll, Ist, Zeile und Lösung; `bedingungen` zeigt alle Bedingungen, Freiheitsgrade
  je Teil (unterbestimmt = Hinweis), Widersprüche (Fehler mit den beteiligten Bedingungen), Befestigung und
  Bewegungsraum (`bedingungen(part="…", alle=true)` für ein Teil). Jeden Fehler beheben, bevor du fertig meldest; die
  Lösung steht im Befund. Beispiel mit Kevins Kugelschieber: `samples/kugelschieber-bedingungen/model.py`.

## 3D-Druckteile konstruieren (Kevin, 21.10.2026, immer beachten)

Drucker: Bambu Lab **P1P** (offen, ohne Gehäuse und Kammer; von Kevin am 21.10.2026 bestätigt), Bauraum
256 × 256 × 250 mm (vorne links 18 × 28 mm gesperrt), Düse 0,4 mm, Schicht 0,2 mm. Standardmaterial PLA oder PETG; ABS, ASA, PC und PA nur mit
Einhausung. Die Druckausrichtung beim Konstruieren
mitdenken und im Bericht nennen. Kurzfassung; das ganze Regelwerk mit Zahlen, Quellen und geprüften build123d-Rezepten
(Tropfenbohrung, Bettfase, Passungen, Gewindeeinsatz, Muttertasche, Opferschicht, Schnapphaken, Teilung) steht in
[3d-druck.md](3d-druck.md), vor jedem Druckteil lesen:

- **Wände** als Vielfache der Linienbreite (~0,42 mm): mindestens 1,2 mm, tragend 2–3 mm; Merkmale nicht unter 0,8 mm.
- **Überhänge** bis 45° ohne Stütze; Unterseiten fasen statt runden; Brücken höchstens ~15 mm.
- **Waagrechte Bohrungen** als Tropfenform (Spitze nach oben); Bohrungen drucken etwa 0,1–0,2 mm zu klein, Ø vorhalten.
- **Bettseite** mit Fase 0,4–0,6 mm gegen Elefantenfuß; eine ebene, große Auflagefläche einplanen.
- **Spiel** je Seite: Presspassung 0,1, Spielpassung 0,2, beweglich/Print-in-Place 0,3–0,5 mm.
- **Gewinde**: Gewindeeinsätze (Tasche nach Herstellermaß, z. B. M3 Ø 4,0–4,2 mm) oder eingeschlossene Muttern
  (Sechskant +0,2–0,3 mm, Einführschräge); Kernlöcher für Schrauben direkt ins Teil etwa 0,8 × d.
- **Gegenbohrungen und Senkungen**, die nach unten zeigen, mit Opferschicht (0,2 mm) drucken, sonst Stütze nötig.
- **Festigkeit**: Last längs der Schichten führen, nicht quer (Schichtfugen sind die Schwachstelle); Innenkanten
  verrunden; Schnapphaken in Schichtrichtung legen.
- **Verzug** bei ABS/ASA/PA: große ebene Flächen und spitze Ecken vermeiden, Ecken verrunden.
- **Z-Maße** möglichst als Vielfache von 0,2 mm; Schrift mindestens 0,6 mm erhaben, Strich ab 0,8 mm.
- **Größer als der Bauraum**: teilen, mit Passstiften oder Schwalbenschwanz und ebenen Fügeflächen.

**Druckprüfung bei jedem Lauf:** Jedes Teil aus `lager.druckteil(...)` prüft der Kernel nach jedem `run` automatisch
für den P1P (Prüfer „druck“ der gemeinsamen Prüfung, Befunde `druck_*` mit ids `dr1`, `dr2` …, Teil, Fläche
`Teil#f<n>`, Ort und Abhilfe). **Fehler** (Export gesperrt) nur aus harten Gründen: passt nicht in den Bauraum (samt
Sperrfläche vorne links), Harzdruck, Material nur mit gehärteter Düse (CF). Überhänge, Brücken, Auskragungen,
waagrechte Bohrungen, dünne Wände, Verzug sind **Warnungen** (beheben oder Kevin begründen), der Rest **Hinweise**
(abwägen). `run` nennt Fehler und Warnungen und je Druckteil die gewählte Ausrichtung mit Begründung;
**`druckpruefung`** (alle Teile) bzw. `druckpruefung(teil="…")` liefert die Einzelheiten: Ausrichtung, Fläche auf
dem Bett, Kennzahlen (Maße auf dem Bett, Schichten, Stützfläche, Auflage, Volumen), alle Hinweise mit Referenzen und
die Materialeinstellungen. Die Ausrichtung wählt die Prüfung selbst; muss die Hauptlast in die Schichtebene, mit
`lager.druckteil(form, name, material="petg", ausrichtung="-z")` vorgeben (`"+x"` usw. = diese Seite aufs Bett,
ebene Flächennummer, Vektor oder `Rot(...)`, bezogen auf die Form, wie sie an `druckteil` geht). Unveränderte Teile
kommen aus dem Zwischenspeicher; der Live-Aufbau wartet nie auf die Prüfung. Kevin die Ausrichtung neuer Druckteile
nennen.

## Arbeitsablauf

1. `status`: offenes Projekt, Pfad von model.py, letzter Lauf, Kevins Auswahl, Inventar-Regel.
2. Kein Projekt: `project_new("Wandhalter")` oder `project_open("Wandhalter")`. Ein bloßer Name landet in
   `~/Documents/Kev CAD/<Name>`.
3. Teile im Lager suchen: `stock_search("vierkantrohr 40x40x3")`, Materialien mit `material_list` (siehe
   Inventar-Regel).
4. model.py mit den eigenen Dateiwerkzeugen schreiben oder ändern (Pfad aus `status`). `model_write` nur, wenn es keine
   Dateiwerkzeuge gibt.
5. `run`: liefert jedes Teil mit Hüllmaß, Volumen und Masse und kurz die Summen der Stückliste. Ein Fehler kommt als
   isError mit Zeile, Auszug und Hinweis; die letzte gute Geometrie bleibt stehen. Korrigieren, wieder `run`.
6. Prüfen: Befunde der Prüfung aus `run` beheben (siehe „Prüfen vor dem Fertigmelden“), Zahlen aus `run` mit der
   Aufgabe vergleichen, wichtige Sollmaße mit `measure` nachmessen, `bom` für Stückliste und Zuschnitt, `bedingungen` für
   Bedingungen, Freiheitsgrade, Befestigung und Bewegungsraum. Kevin keine
   Screenshots schicken; Bilder nur zur eigenen Analyse (siehe „Bilder“).
7. Kevin kurz berichten: was gebaut ist, Hauptmaße, Masse, Kosten (Richtpreise), offene Annahmen. Bei Bedarf `focus`,
   `highlight`, `annotate` nutzen, damit er es im Viewer sieht.

Speichert Kevin model.py selbst und ist Auto-Lauf an, rechnet der Kernel von allein. `run` wartet dann auf diesen Lauf,
statt doppelt zu rechnen.

## Inventar-Regel

Standard für jedes Projekt: **Gebaut wird nur aus dem Inventar.**

- Jedes Teil in `show()` stammt aus `lager.teil(...).verbauen(...)`, aus einem freigegebenen Zukaufteil
  (`lager.zukauf(...).verbauen(...)`, siehe „Zukaufteile“) oder ist ausdrücklich ein 3D-Druckteil:
  `lager.druckteil(form, "Halter/Schelle", material="petg")`. Druckmaterial muss freigegeben und druckbar sein
  (`material_list` zeigt „druckbar“: PLA, PETG, ABS, ASA, TPU 95A, PA, PA-CF, PC-Filament, PLA-CF, Standardharz);
  `verfahren="3d-druck"` (Standard) oder `"harzdruck"`.
- Materialien nur aus dem Katalog (id oder Alias), auch bei `show(material=...)`. Unbekannte oder nur vorgeschlagene
  Materialien brechen den Lauf mit Vorschlägen ab.
- Nichts erfinden. Fehlt ein Teil oder Material: erst `stock_search` mit anderen Wörtern, dann Kevin fragen. Nur auf
  seinen Wunsch mit `stock_define` bzw. `material_define` vorschlagen. Ein Vorschlag „wartet auf Kevins Freigabe im
  Lagerkatalog“ und lässt sich vorher nicht verbauen; Kevin gibt ihn im Lagerkatalog-Fenster frei oder lehnt ab.
  Freigegebene Einträge ändert nur Kevin.
- Verstöße: `run` meldet „Inventar-Regel: 2 Teile sind nicht aus dem Inventar: …“ als isError. Die Geometrie ist zu
  sehen, aber Export (STEP, STL, 3MF, Stückliste) wird verweigert. Passendes Lagerteil verbauen, als Druckteil
  kennzeichnen oder Kevin bitten, das Lagerteil anzulegen.
- Abschalten kann nur Kevin, je Projekt (kevcad.json `"inventar_regel": false`, etwa für Nachbauten aus Fotos). Diese
  Einstellung nie selbst ändern. Ist die Regel aus, gelten auch Materialnamen aus build123d (`aluminum`, `oak`, …) und
  frei modellierte Teile mit Material erscheinen als „Eigenteil“.

## Gerüst von model.py

```python
from build123d import *
from kevcad import lager, param, show, step

hoehe = param("hoehe", 120)        # Länge der Grundplatte
abstand = param("abstand", 70)     # Wand bis Rohrmitte
loch = param("loch", 6.6)          # Durchgangsbohrung M6, mittel
schelle_h = param("schelle_h", 30)
wand = param("wand", 4)

flach = lager.teil("flach", b=40, s=5, material="stahl-s235")   # vorher mit stock_search gefunden
rohr = lager.teil("rohr-en10220-42.4x2.0")
blech, rohr_d = flach.masse["s"], rohr.masse["d"]

step("Grundplatte")
platte = Pos(0, blech / 2, -hoehe / 2) * flach.verbauen(laenge=hoehe, name="Halter/Grundplatte")
show(platte, "Halter/Grundplatte")

step("Bohrungen")
for z in (-40, 40):
    platte -= Pos(0, 0, z) * Rot(90, 0, 0) * Cylinder(loch / 2, 3 * blech)
show(platte, "Halter/Grundplatte")   # gleicher Name: ersetzt, man sieht das Teil wachsen; bleibt Lagerteil

step("Lasche")
ring_r = rohr_d / 2 + wand
lasche = flach.verbauen(laenge=abstand - ring_r - blech, name="Halter/Lasche")
show(Pos(0, blech, 0) * Rot(-90, 0, 0) * lasche, "Halter/Lasche")   # erst drehen, dann schieben

step("Schelle")
ring = Pos(0, abstand, 0) * (Cylinder(ring_r, schelle_h) - Cylinder(rohr_d / 2, schelle_h + 2))
show(lager.druckteil(ring, "Halter/Schelle", material="petg"), "Halter/Schelle")

step("Rohr")
show(Pos(0, abstand, -150) * rohr.verbauen(laenge=300, name="Rohr"), "Rohr")
```

## API von kevcad

| Aufruf | Wirkung |
|---|---|
| `param(name, wert, min=None, max=None)` | benannter Parameter (mm). Liefert den Vorgabewert oder den Wert aus `run(params={"breite": 140})`. Alle Parameter oben in der Datei. |
| `step("Bohrungen")` | Bauschritt, erscheint in Kevins Statusleiste. Vor jedem Schritt aufrufen. |
| `show(obj, name, color=None, material=None)` | zeigt Part, Compound, Sketch, Kanten oder ein Builder-Ergebnis (`bp.part`) sofort an. Gleicher Name ersetzt. `/` im Namen bildet den Baum. |
| `lager.teil(id)` / `lager.teil(art, **maße, material=None)` | Lagerteil aus dem Katalog, genau passend, sonst Fehler mit Vorschlägen. |
| `lager.suche("rohr 42,4")` | Liste von Lagerteilen (zum Ausprobieren in `execute`). |
| `teil.verbauen(...)` | build123d-Teil mit Name, Farbe und Material, dazu eine Stücklistenzeile (siehe unten). |
| `lager.druckteil(form, name, material, verfahren="3d-druck", ausrichtung=None)` | selbst konstruiertes Druckteil; Material druckbar; Druckprüfung bei jedem Lauf, `ausrichtung` gibt die Lage aufs Bett vor (None = automatisch). |
| `lager.zukauf(id)` → `.verbauen(name)`, `.bezugspunkt(name)` | Zukaufteil mit Hersteller-CAD, Skript oder Ersatzkörper (siehe „Zukaufteile“). |
| `erlaubt_ueberlappung(a, b, grund="…")` | gewollte Überlappung, nur nach Rückfrage bei Kevin (siehe „Prüfen vor dem Fertigmelden“). |
| `montage(teil, richtung=, nach=, werkzeug=, baugruppe=, schnappt=, eingedruckt=)` | Einbau erklären, wo die Prüfung es nicht selbst wissen kann (siehe „Montagegerecht konstruieren“). |
| `befestigt(teil, grund="…")`, `boden(z)` | an Wand/Decke befestigt (nur nach Rückfrage), Bodenebene. |
| `import kevcad.bedingungen as bed` | Bezüge, Bedingungen, Gelenke, Befestigung, `bed.platziere(teil, …)` (Abschnitt „Teile über Bedingungen setzen“). |

- `color`: Hex wie `"#B8BEC4"`; Lager- und Druckteile haben schon die Farbe ihres Materials.
- `material`: id oder Alias aus dem Katalog (`material_list`), z. B. `stahl-s235`, `edelstahl`, `alu`,
  `multiplex-birke`, `petg`. Lagerteile tragen ihr Material selbst, `material=` ist dort nicht nötig.
- Langsam aufbauen, wenn Kevin zuschauen soll: `run(slow_ms=400)`.

## Lagerteile verbauen

- Stangenware (Rohr, Vierkant-/Rechteckrohr, Flach-, Rund-, Vierkantstahl, Winkel, U-Profil, Nutprofil, Holz):
  `teil.verbauen(laenge=842, name="Gestell/Bein vorn links", gehrung=(0, 0))`. Das Teil liegt entlang +Z ab z = 0,
  der Querschnitt mittig. `laenge` ist das **Zuschnittmaß an der längsten Kante**. `gehrung=(anfang, ende)` in Grad um
  die lokale X-Achse: positiv lässt die Kante bei +Y lang (Rahmenleiste mit Außenkante bei +Y), negativ die bei -Y.
  `drehung=90` dreht den Querschnitt vorher um Z (Gehrung über die andere Seite). Querschnitte: Breite b in X,
  Höhe h bzw. Dicke s in Y; Winkel mit Schenkel a nach +Y und b nach +X; U-Profil nach +X offen.
- Platten: `platte.verbauen(breite=800, tiefe=600, name="Deckel")` in der XY-Ebene ab z = 0, mittig; oder
  `form=Rectangle(800, 600) - Circle(40)` (Skizze in XY).
- Schrauben: `schraube.verbauen(laenge=60, name="Schrauben/M8x60 1")` (bd_warehouse, Kopf auf z = 0, Schaft nach -Z,
  ohne Gewinde); Muttern und Scheiben ohne `laenge`.
- **Name in `show()` gleich wie in `verbauen()`.** Dann kennt die Stückliste das gezeigte Teil, auch nach Verschieben,
  Drehen oder Bohren. Gleiche Teile durchnummerieren: „Schrauben/M8x60 1“ … „8“.
- Rahmen mit Gehrung: Leiste mit `gehrung=(45, 45)` verbauen, erst um die eigene Achse drehen (lange Kante nach außen),
  dann hinlegen, dann schieben. Beispiel: `samples/gestell/model.py`.
- Jede `verbauen`-Zeile steht in der Stückliste, auch wenn das Teil später gebohrt wird. Gleiche Lagerteile mit
  gleicher Länge und Gehrung werden zusammengefasst.

## Stückliste

- `bom`: Positionen (Anzahl, Maße, Gehrung, Material, kg, €), Zuschnitt je Stangenware („Stange 1: 882 + 882 + … =
  5.394 mm, Rest 606 mm“, Sägeschnitt 3 mm, Verschnitt in %), Summen mit Richtpreis-Hinweis, Hinweise (etwa nicht
  zugeordnete Lagerteile). `bom(format="csv")` liefert CSV, `export(["bom_csv"])` schreibt die Datei.
- Preise sind Richtwerte mit Stand; so auch an Kevin weitergeben.

## Zukaufteile

Fertig gekaufte Teile mit Hersteller und Nummer (Schubladenauszug, Scharnier, Rolle, Rollwagen). Sie zählen zum
Inventar, sobald Kevin sie freigegeben hat. Kameras, Objektive und Kamera-Zubehör: siehe „Kameras“.

```python
wagen = lager.zukauf("alutec-05200")          # nach id; sonst lager.zukauf(mpn="05200", hersteller="ALUTEC") oder gtin=
rw = wagen.verbauen("Rollwagen")              # Hersteller-CAD, Skript-Geometrie oder Ersatzkörper
show(Pos(0, y, 0) * rw, "Rollwagen")          # gleicher Name wie in verbauen
oben = wagen.bezugspunkt("oben")              # Location im System des verbauten Teils
show(Pos(0, y, 0) * oben * ball, "Ball")      # auf die Ladefläche gesetzt
```

- Das verbaute Teil liegt mit seinem **Einbaupunkt** im Ursprung (Standard: Mitte der Unterseite, Z oben).
  Bezugspunkte (`bezugspunkte` im Katalog) gelten im selben System; Lage daraus ableiten statt Zahlen abzuschreiben.
- Hersteller-CAD mit Baugruppe erscheint als Baum („Rollwagen/Platte“, „Rollwagen/Rolle_1“). Ohne Modell ist es ein
  **Ersatzkörper** (Quader oder Zylinder aus den Shop-Maßen), halbtransparent und mit „(vereinfacht)“ im Namen.
  **Vereinfachte Teile im Bericht an Kevin immer nennen.**
- Die Prüfung behandelt Zukaufteile wie alle Teile: Hersteller-CAD und Ersatzkörper dürfen nichts durchdringen.
  Überlappt ein Zukaufteil sein Gegenstück nur, weil das Modell vereinfacht ist (Gewinde als Vollzylinder,
  Ersatzquader), ist das trotzdem ein Befund: im Modell lösen oder `erlaubt_ueberlappung(…, grund=…)` erst nach
  Rückfrage bei Kevin.
- Skript-Geometrie (`cad.quelle: "skript"` mit `datei`/`modul` und `funktion`): `verbauen(name, **kwargs)` reicht
  Schlüsselwörter an die Funktion weiter.

Ablauf, wenn Kevin einen Link, eine Herstellernummer oder eine EAN nennt:

1. **Seite selbst lesen** (Browser oder WebFetch). Kev CAD lädt keine Shop-Seiten und umgeht keinen Bot-Schutz. Bei
   einer EAN erst den Artikel suchen.
2. **Normteil?** „ISO 4762 M6×20“, „DIN 934 M8“: kein Zukaufteil, sondern `stock_search` und `lager.teil(...)`
   (`zukauf_anlegen` leitet selbst um).
3. **Anlegen:** HTML an `zukauf_html(url, html)` (wertet JSON-LD, Microdata und Open Graph aus) oder die gelesenen
   Felder an `zukauf_anlegen(url, felder={name, hersteller, mpn, gtin, preis {je_stueck, waehrung, brutto}, masse {l,
   b, h} bzw. {d, l}, gewicht, bild})`. Preis immer mit brutto/netto wie im Shop. Kevin Hersteller, Nummer, Preis und
   Maße bestätigen lassen (`zu_pruefen` in der Antwort). Das Teil ist ein **Vorschlag**, bis Kevin es im Lagerkatalog
   freigibt; vorher lässt es sich nicht verbauen.
4. **CAD suchen:** `cad_suchen(id)`. Mit Kevins TraceParts-Schlüssel kommt das STEP automatisch („powered by
   TraceParts“ nennen). Sonst liefert es Links (Produktseite, Herstellerportal, TraceParts, 3Dfindit, Websuche):
   **Kevin bitten, das STEP (oder ein ZIP mit STEP) mit seinem Konto herunterzuladen.** Die App beobachtet derweil
   `~/Downloads` und fragt ihn selbst.
5. **Übernehmen:** `cad_uebernehmen(id)` ohne Pfad nimmt die neueste passende Datei aus `~/Downloads` (auch aus ZIP).
   Zoll, Zentimeter und „Y oben“ werden erkannt und korrigiert (steht im Ergebnis); passt das Hüllmaß nicht zu den
   Katalogmaßen, wird abgelehnt (falsche Datei? Maße prüfen; `erzwingen=True` nur nach Rückfrage). Die Datei liegt
   danach in `<projekt>/zukauf/<id>/` (nie im Git, Herstellerbedingungen).
6. `run`, prüfen wie immer, `bom` zeigt das Teil mit Hersteller, Nummer, Stückpreis mit Datum, Link und CAD-Quelle.

`zukauf_liste` zeigt alle Zukaufteile mit Freigabe und CAD-Stand. Die Summe der Stückliste mischt Richtpreise (netto)
und Shoppreise (oft brutto); die Stückliste sagt das dazu, so auch an Kevin weitergeben.

## Kameras

Kameras wie am Set: Gehäuse, Objektiv und Aufnahmeformat aus dem Katalog (`kamera_katalog`), gesetzt in model.py.
Beispiel: `samples/kamerawagen/model.py`; Felder in KATALOG.md, Abschnitt „Kameras und Objektive“.

```python
fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", blende=2.8, fokus=1500,
                   name="FX6")                              # format: ff-uhd, ff-dci, ff-hd, ff-uhd-120, s35-hd
fx6.setzen((0, -400, 180), blick_auf=(800, 0, 108))         # Sensormitte, Blick auf einen Punkt (Fokus = Abstand)
fx6.an("Rollwagen/Deckel", punkt=(150, 0, 40), richtung=(1, 0, 0), bezug="stativ_1_4", lokal=True)  # folgt dem Teil
show(fx6.koerper(), "Kamera FX6")                           # Gehäuse und Objektiv, zählt als Inventar
platte = lager.kamerazubehoer("tilta-es-t20-qrbp")          # Rig-Teile mit Bezugspunkten
show(platte.verbauen("Rig/Baseplate", an=fx6.bezugspunkt("stativ_1_4"), bezug="kamera_1_4"), "Rig/Baseplate")
```

- `bezug` ist ein Bezugspunkt der Kamera, der an der angegebenen Stelle liegt. Gültig sind genau diese Namen:
  `sensor`, `bajonett`, `front_unten`, `stativ_1_4`, `stativ_3_8`, `akkuschacht`, dazu eingebaut `auge` und `front`
  (`fx6.bezugspunkte()` listet sie). Andere Schreibweisen wie `gewinde_14` oder `gewinde_38` gibt es nicht.
  `richtung` oder `blick_auf` geben den Blick, `roll` kippt (Grad). Brennweite bei Zooms innerhalb des Bereichs,
  Blende nicht offener als die Lichtstärke (Fehler mit Erklärung), `fokus` in mm ab Sensorebene oder `"unendlich"`.
  Der Lauf meldet Bildwinkel, Schärfe von–bis und Warnungen (Naheinstellgrenze, Vignettierung bei Super-35-Objektiven
  an Vollformat).
- `an(teil, …, lokal=True)` nach dem `show` des Teils aufrufen; die Kamera wandert dann mit dem Teil, auch in
  Animationen (siehe „Kamera und Animation“). An ein Teil hängen, nicht an eine Baugruppe. Kamera setzen, nicht
  `Pos(...) * fx6.koerper()` verschieben.
- Werkzeuge: `kamera_liste`, `kamera_info(name)` (alle Werte), `kamera_ansicht(name)` bzw. `"aus"` (Viewer schaut
  durch die Kamera, mit Formatrahmen und Sicherheitsbereichen), `kamera_bild(name, breite)` speichert ein PNG unter
  output/kameras/ und nennt nur den Pfad (Bild nur mit `bild_zeigen=true`, wenn Kevin es hier sehen will),
  `kamera_vorschlag_aus_ansicht(name)` liefert die setzen-Zeile für Kevins aktuelle Ansicht (in der App Strg+Alt+0).
- Kevin: Taste 0 schaut durch die gewählte Kamera, noch einmal 0 zurück; Kameras stehen im Teilebaum unter „Kameras“.
- Kevins Kamera ist die FX6 (Tilta-Käfig ES-T20). Objektive, Akkus und Platten im Katalog sind Beispiele, bis Kevin
  seine nennt; fehlt etwas, fragen und erst auf seinen Wunsch per `stock_define` vorschlagen.

## build123d: Kurzreferenz und Fallen

**Algebra-Modus bevorzugen** (Objekte und Operatoren). Builder (`with BuildPart() as bp:`) nur, wo er klar hilft, etwa
für Bohrungen auf einer Fläche. Ergebnis eines Builders ist `bp.part`, nicht `bp`.

- **Ausrichtung:** `Box`, `Cylinder` und `Sphere` sind standardmäßig um den Ursprung **zentriert** (eine Box der Höhe 10
  reicht von z = −5 bis +5). Auf die XY-Ebene stellen: `align=(Align.CENTER, Align.CENTER, Align.MIN)`.
- **Lage:** `Pos(x, y, z) * teil` verschiebt, `Rot(x, y, z) * teil` dreht in Grad um den Ursprung. Gelesen wird von
  rechts nach links: `Pos(100, 0, 0) * Rot(0, 0, 90) * teil` dreht erst und schiebt dann. Andersherum kreist das Teil um
  den Ursprung. `Rot(90, 0, 0)` legt die Z-Achse eines Zylinders auf −Y.
- **Boolesch:** `a + b` vereinigen, `a - b` abziehen, `a & b` Schnittmenge. Listen gehen auch: `platte -= [Pos(x, 0, 0)
  * zyl for x in xs]` oder `platte -= GridLocations(40, 20, 2, 2) * Cylinder(3, 10)`.
- **Werkzeugkörper überstehen lassen:** Durchgangsbohrungen und Schlitze länger als das Material machen (z. B.
  `dicke + 2`, um 1 nach unten versetzt). Genau bündige Flächen hinterlassen sonst Häute oder kaputte Flächen.
  Beim Vereinigen gilt dasselbe: Teile leicht überlappen lassen, nicht nur berühren.
- **Kanten und Flächen wählen:**
  - `teil.edges().filter_by(Axis.Z)`: Kanten parallel zu Z (senkrechte Ecken)
  - `teil.edges().group_by(Axis.Z)[-1]`: oberste Kanten, `[0]` unterste
  - `teil.faces().sort_by(Axis.Z)[-1]`: oberste Fläche
  - `teil.edges().filter_by(GeomType.CIRCLE)`: Kreiskanten (Bohrungsränder)
  - `teil.edges().filter_by(Axis.Z).group_by(SortBy.DISTANCE)[-1]`: nur die äußersten senkrechten Kanten
  - Kurzformen: `|` = filter_by, `>` = sort_by, `>>` = group_by(...)[-1], `<<` = group_by(...)[0]
- **Fillet und Fase:** `teil = fillet(kanten, radius=4)` und `teil = chamfer(kanten, length=1)`. Das Ergebnis neu
  zuweisen. Der Radius muss kleiner sein als die halbe Wandstärke dort. `filter_by(Axis.Z)` erfasst nach dem Bohren
  auch die Nahtkanten der Bohrungen; deshalb Ecken vor dem Bohren runden oder die Auswahl eingrenzen. Scheitert ein
  Fillet („command not done“), ist meist der Radius zu groß oder die Auswahl zu breit.
- **Skizzen:** `extrude(Plane.XY.offset(10) * (Rectangle(40, 20) - Circle(5)), amount=5)`,
  `revolve(Plane.XZ * Pos(20, 0) * Rectangle(4, 10), Axis.Z)`, `mirror(teil, about=Plane.YZ)`,
  `Text("KEV", font_size=10)`.
- **Bohrungen im Builder** (Bohrung geht von der gewählten Fläche ins Material):

  ```python
  with BuildPart() as bp:
      Box(60, 40, 10)
      with Locations(bp.faces().sort_by(Axis.Z)[-1]):
          with GridLocations(40, 20, 2, 2):
              CounterBoreHole(radius=3.3, counter_bore_radius=5.5, counter_bore_depth=6.4)
  show(bp.part, "Deckel")
  ```

  `Hole(radius)`, `CounterBoreHole(...)` und `CounterSinkHole(radius, counter_sink_radius, counter_sink_angle=90)` gehen
  nur im Builder. **Falle:** `CounterSinkHole` nimmt standardmäßig 82° (Zoll-Norm). Metrische Senkschrauben brauchen
  `counter_sink_angle=90`.

### Löcher für Schrauben (Durchmesser in mm)

| Gewinde | Durchgang mittel (ISO 273) | Kernloch für Gewinde | Senkung Zylinderkopf ISO 4762 (Ø × Tiefe) | Senkung 90° ISO 10642 (Ø) |
|---|---|---|---|---|
| M3 | 3,4 | 2,5 | 6,5 × 3,4 | 6,7 |
| M4 | 4,5 | 3,3 | 8 × 4,4 | 9,0 |
| M5 | 5,5 | 4,2 | 10 × 5,4 | 11,2 |
| M6 | 6,6 | 5,0 | 11 × 6,4 | 13,4 |
| M8 | 9,0 | 6,8 | 15 × 8,6 | 17,9 |
| M10 | 11,0 | 8,5 | 18 × 10,6 | 22,4 |

Für den 3D-Druck Löcher 0,2 bis 0,3 mm größer und Passungen mit Spiel. Rohrmaße sind Außendurchmesser (42,4 mm =
DN 32, 1¼ Zoll).

## Benennung und Baugruppen

- Jedes echte Teil bekommt einen sprechenden deutschen Namen: „Grundplatte“, „Lasche“, „Schelle“.
- Baugruppen über `/`: „Halter/Grundplatte“, „Halter/Schelle“. Gleiche Teile nummerieren: „Schrauben/M6x20 1“.
- Ein Teil nach jedem Bauschritt mit demselben Namen erneut zeigen. So sieht Kevin es wachsen.
- Hilfsgeometrie (Werkzeugkörper, Schnittkörper) nicht zeigen.
- Lagerteile und Druckteile tragen Material, Farbe und Masse; die Masse steht in `run`, `parts` und `measure`.

## Referenzen und Auswahl

- `Halter/Lasche` ist das Teil, `Halter/Lasche#f3` Fläche 3, `#e2` Kante 2, `#v1` Punkt 1. Die Nummer folgt
  `teil.faces()`, `teil.edges()` und `teil.vertices()` des zuletzt gezeigten Objekts.
- Referenzen gelten **nur für einen Lauf**. Nach jedem `run` neu holen, nie alte Nummern wiederverwenden.
- Flächennummer finden: `execute("[(i, f.geom_type.name, round(f.area, 1), f.center()) for i, f in
  enumerate(platte.faces())]")` mit der Variablen des gezeigten Teils.
- Sagt Kevin „diese Bohrung“, „hier“ oder „das da“: zuerst `selection`. Sie liefert seine angeklickten Referenzen samt
  Werten (Typ, Fläche, Radius).

## Messen

- `measure(["Grundplatte#f3"])`: Eigenschaften eines Elements (Fläche, Normale, Radius, Länge, Lage, beim Teil Hüllmaß,
  Volumen, Masse).
- `measure(["Lasche#f2", "Grundplatte#f0"])`: kleinster Abstand mit dx, dy, dz und beiden Punkten, Winkel, Abstand
  paralleler Flächen. Zwei Bohrungswände (Zylinderflächen) ergeben den Achsabstand.
- `show=True` (Standard) blendet das Maß im Viewer ein. Werte stimmen exakt (OCCT), nicht aus dem Bild schätzen.
- Rechnungen und Abfragen im Modell mit `execute` (z. B. `platte.volume`, `schelle.bounding_box()`), ohne model.py zu
  ändern.

## Kevin etwas zeigen

| Werkzeug | Zweck |
|---|---|
| `focus(["Halter/Lasche"])` | Kamera fährt hin (animiert) |
| `highlight(refs, color="orange", label="M6")` | einfärben, beschriften; `clear=True` entfernt alte |
| `annotate("dimension", [[x,y,z],[x,y,z]])` | Maßlinie (Text = Abstand, wenn leer); auch `arrow`, `label` |
| `clear_annotations()` | alle Anmerkungen weg (oder `ids=[...]`) |
| `visibility("isolate", ["Halter/Lasche"])` | nur diese Teile; `show_all` stellt alles wieder her |
| `section(True, axis="y", offset=0)` | Schnitt; `section(False)` hebt ihn auf |
| `view(standard="front", projection="orthographic", fit=True)` | Standardansicht, Darstellung (`xray`, `wireframe`), `explode=0.6` |

„Zoom auf die Lasche und zeig sie von der Seite“: `view(standard="right", projection="orthographic")`, dann
`focus(["Halter/Lasche"])`. Kevin sieht das Ergebnis selbst im Viewer.

## Bilder

Kevin keine Screenshots schicken, außer er will ausdrücklich ein Bild: Er sieht den Viewer beim Arbeiten selbst, und
jedes Bild hält die Generierung auf.

Zur eigenen Analyse sind Bilder aus mehreren Blickwinkeln ausdrücklich erlaubt, wenn sie zu einer besseren Entscheidung
führen (Kevin, 21.10.2026): Durchdringungen und Einbaubarkeit beurteilen, Proportionen und Lage prüfen, mit
Referenzfotos vergleichen. Dann gezielt: wenige Offscreen-Ansichten in kleiner Auflösung in einem Zug (etwa iso, vorn,
rechts, oben), nicht nach jedem Schritt. Erste Quelle bleiben die Zahlen aus `run`, `parts`, `measure` und der Prüfung.

- `ansichten()` liefert mehrere Offscreen-Ansichten in einem Aufruf (Standard iso, vorn, rechts, oben, 640 × 400),
  frei wählbare Blickrichtungen (`richtungen=[[1, 1, -1]]`), auf Teile (`ziel`) oder einen Punkt (`punkt`, `radius`)
  eingepasst, mit Röntgen (`darstellung="xray"`) für verdeckte Teile, rot hervorgehobenen Teilen und den roten
  Schnittkörpern der Prüfung. Kevins Kamera und Darstellung bleiben unverändert.
- `pruefen(bilder=True)` zeigt die schlimmsten Befunde aus zwei, drei Richtungen von nah, mit Schnittvolumen.
- `screenshot()` zeigt genau Kevins Ansicht, 1280 × 800 px. Größer nur, wenn Details fehlen.
- `mm_per_px` gibt es nur in paralleler Projektion. Maße trotzdem mit `measure` bestätigen.

## Animation

Bewegungen gehören wie die Geometrie in `model.py`: `from kevcad import animation`, am Ende nach allen `show()`.
Ziele sind Teilnamen oder Baugruppenpräfixe („Rollwagen“ bewegt alle „Rollwagen/…“). Zeiten in s, Längen in mm,
Winkel in Grad. Der Kernel rechnet daraus je Bild die Lage jedes Teils, die App spielt flüssig ab (Zeitleiste unter dem
Viewport, Leertaste, Pfeiltasten, Umschalt+Pfeil für Anfang und Ende).

```python
fahrt = animation(dauer=8, fps=30, name="Fahrt")          # mehrere Animationen je Projekt mit eigenem Namen
fahrt.bewege("Rollwagen", nach=(2000, 0, 0), von=1, bis=7, kurve="weich")
for i in range(1, 5):                                     # Räder drehen mit: Winkel = Strecke / Radius
    fahrt.rolle(f"Rollwagen/Lenkrolle {i}/Rad", auf="Rollwagen", radius=50, achse="y")
fahrt.folge("Kugelschieber", "Rollwagen")                 # fährt starr mit
fahrt.rolle("Bowlingball", auf="Rollwagen", radius=108.5) # rollt frei vor dem Schieber
fahrt.ansicht(0, lage=(-900, -1800, 700), ziel=(300, -340, 150), mit="Rollwagen/Rahmen")  # Kamerafahrt
```

| Spur | Wirkung |
|---|---|
| `bewege(name, nach=(dx,dy,dz), von, bis, kurve)` | verschieben; `kurve` `"linear"`, `"weich"`, `"ein"`, `"aus"` |
| `drehe(name, achse, winkel, von, bis, kurve)` | drehen; `achse=((x,y,z),(dx,dy,dz))`, `Axis`, Richtung oder `"x"/"y"/"z"` durch die Teilmitte |
| `pfad(name, punkte, von, bis, ausrichten=False, spline=False)` | entlang Polylinie oder Spline, gleichmäßig nach Bogenlänge |
| `rolle(name, auf, radius, achse=None)` | Rollbedingung; mit Achse wie ein Rad, ohne frei wie eine Kugel |
| `folge(name, eltern)` | Kind folgt allen Bewegungen des Elternteils |
| `gelenk(name, art="dreh"/"schub", achse, werte={t: wert}, grenzen=(min, max), eltern)` | Gelenkwinkel/-weg über die Zeit, an den Grenzen begrenzt (Warnung) |
| `sichtbar(name, an, zeit)` / `ansicht(zeit, lage, ziel, bildwinkel, mit)` / `erlaube(a, b)` | ein-/ausblenden, Kamerafahrt, gewollte Berührung |

Drehachsen gelten in der Ruhelage (Koordinaten wie in model.py); Drehungen wirken vor Verschiebungen, beides vor der
Bewegung des Elternteils. Ein unbekanntes Teil oder eine Zeit außerhalb der Dauer bricht den Lauf mit Zeile ab.

- `kollision_pruefen(name)` prüft jedes 3. Bild exakt (OCCT-Schnittvolumen, Berühren ist erlaubt) und meldet Zeit,
  Teilpaar, Eindringtiefe und Volumen; die App markiert sie auf der Zeitleiste und färbt das Paar rot. **Jede
  Durchdringung muss gelöst werden**, gewollte Anlage mit `erlaube` oder Luft im Modell. Eine Überlappung, die die
  eingebaute Prüfung über `erlaubt_ueberlappung(a, b, grund=…)` zulässt, gilt auch in der Animation als erlaubt. Die
  eingebaute Prüfung nach jedem Lauf sieht nur die Ruhelage; ihre roten Schnittkörper blendet die App beim Abspielen
  aus.
- `animation_abspielen(name, an=True, schleife=False)`, `animation_springen(zeit)`, `animation_liste()`.
- `animation_video(name, breite=1920)` schreibt ein H.264-MP4 (oder `format="prores"`) nach
  `<Projekt>/output/animationen/` aus der Viewer-Sicht bzw. der Kamerafahrt.

### Kamera und Animation

Eine Kamera mit `an(teil)` fährt mit ihrem Teil: beim Abspielen (Pyramide), beim Blick durch die Kamera (Taste 0
bleibt beim Abspielen aktiv) und im Video. Eine frei gesetzte Kamera mit gezeigtem `koerper()` folgt ihrem Gehäuse.

```python
fx6 = lager.kamera("sony-fx6", objektiv="sigma-ff-hs-35-t1.5-e", format="ff-uhd", name="FX6")
fx6.an("Rollwagen/Deckel", punkt=(150, 0, 40), richtung=(1, 0, 0), bezug="stativ_1_4", lokal=True)
show(fx6.koerper(), "Kamera FX6")      # fährt in jeder Animation von selbst mit dem Deckel mit
fahrt = animation(dauer=8, fps=30, name="Fahrt")
fahrt.bewege("Rollwagen", nach=(2000, 0, 0), von=1, bis=7, kurve="weich")
fahrt.folge("Rig", "Rollwagen/Deckel")  # Rig-Zubehör hängt nicht an der Kamera: eigene Spur
```

- `animation_video("Fahrt", kamera="FX6")` rendert durch die Kamera (Bildwinkel der Kamera, Seitenverhältnis ihres
  Formats, eigenes Objektiv ausgeblendet) nach `output/animationen/Fahrt_FX6.mp4`. `animation_liste` und `run` nennen
  je Animation die Kameras, die mitfahren.
- Kevin: Taste 0, dann Leertaste; das Video aus Menü oder Zeitleiste entsteht beim Blick durch eine Kamera aus ihrer
  Sicht.
- Den Körper bewegt der Kernel nur, wenn keine eigene Spur ihn bewegt; Werte von `kamera_info` gelten für die Ruhelage.

## Export

`export(["step", "stl", "3mf"])` schreibt nach `<Projekt>/output/`, `export(["bom_csv"])` die Stückliste als CSV. STEP für CAD und Fertigung, STL oder 3MF für den
Bambu-Drucker, GLB für Ansichten. `parts=["Halter/Schelle"]` exportiert nur diese Teile.

## Wenn etwas hakt

| Meldung | Bedeutung |
|---|---|
| Lauf fehlgeschlagen in Zeile N | Fehler in model.py; Auszug lesen, korrigieren, `run` |
| Unbekannte oder veraltete Referenz | nach dem letzten Lauf neu holen (`parts`, `selection`, `execute`) |
| App nicht verbunden | der Kernel läuft, die App hängt (noch) nicht an ihm; kurz warten, sonst Kevin bitten, Kev CAD zu öffnen |
| Kev CAD läuft nicht – bitte starten | die Brücke erreicht die App nicht; Kevin bitten, Kev CAD zu starten |
| Inventar-Regel: … nicht aus dem Inventar | Teil ohne `verbauen`/`druckteil` gezeigt; Lagerteil suchen, Druckteil kennzeichnen oder Kevin fragen |
| … wartet auf Kevins Freigabe im Lagerkatalog | Vorschlag aus `stock_define`/`material_define`; Kevin gibt ihn im Lagerkatalog frei |
| Material '…' gibt es im Katalog nicht | nur Katalogmaterialien (`material_list`); fehlt eins, Kevin fragen |
| Lagerteil „…“ ist keinem gezeigten Teil zugeordnet | Name in `show()` anders als in `verbauen()`; gleich benennen |
| Export verweigert | erst die Verstöße gegen die Inventar-Regel beheben |
| Prüfung: 2 Durchdringungen … | Teile stecken ineinander; je Befund die Lösung umsetzen (Spiel, Bohrung, verschieben), `run` |
| … schwebt: … fiele 12 mm auf … | Teil absenken oder mit dem tragenden Teil verbinden |
| … kippt / steht knapp | Standfläche verbreitern, Schwerpunkt senken |
| … lässt sich nicht einbauen / nur als Baugruppe / eingesperrt | umkonstruieren (Reihenfolge, Teilung, Öffnung, lösbare Verbindung); Zukaufteil als Baugruppe erklären |
| … Werkzeug kommt nicht hin | Freiraum für den Schlüssel schaffen oder Schraube anders setzen |
| Export verweigert. Prüfung: … | erst die Befunde der Prüfung beheben |
| Bedingungen: … verletzt (Soll …, Ist …) | Teil nicht von Hand verschieben, sondern mit `bed.platziere` aus den Bedingungen setzen; Lösung im Befund |
| Widerspruch beim Platzieren | die genannten Bedingungen passen nicht zusammen; eine weglassen oder Werte angleichen |
| … ist unterbestimmt (Hinweis) | freie Freiheitsgrade: weitere Bedingung (konzentrisch, mittig, parallel, abstand) |
| … nicht befestigt / Nicht am Boden | `bed.verbinde(teil, gegenstück, art=…)` angeben und die Befestigung konstruieren |
| Bewegungsraum: stößt bei … an … | Platz schaffen oder umkonstruieren; den Bereich nur verkleinern, wenn die Bedienung das erlaubt |
| … nicht geprüft: Teil … nicht gefunden | Bezug nach der letzten Änderung nehmen oder das Teil über seinen Namen angeben |
