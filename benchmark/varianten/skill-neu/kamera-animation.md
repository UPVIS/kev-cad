# Kameras und Animation

Teil des Skills kev-cad. Filmkameras aus dem Inventar in model.py und Animationen samt Kollisionsprüfung und Video.

## Kameras

Kameras wie am Set: Gehäuse, Objektiv und Aufnahmeformat aus dem Katalog (`kamera(aktion="katalog")`), gesetzt in model.py.
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
- Werkzeuge: `kamera(aktion="liste")`, `kamera(aktion="info", name=…)` (alle Werte), `kamera(aktion="ansicht", name=…)` bzw. `"aus"` (Viewer schaut
  durch die Kamera, mit Formatrahmen und Sicherheitsbereichen), `kamera(aktion="bild", name=…, breite=…)` speichert ein PNG unter
  output/kameras/ und nennt nur den Pfad (Bild nur mit `bild_zeigen=true`, wenn Kevin es hier sehen will),
  `kamera(aktion="vorschlag", name=…)` liefert die setzen-Zeile für Kevins aktuelle Ansicht (in der App Strg+Alt+0).
- Kevin: Taste 0 schaut durch die gewählte Kamera, noch einmal 0 zurück; Kameras stehen in der Kachel Details unter „Kameras“.
- Kevins Kamera ist die FX6 (Tilta-Käfig ES-T20). Objektive, Akkus und Platten im Katalog sind Beispiele, bis Kevin
  seine nennt; fehlt etwas, fragen und erst auf seinen Wunsch per `lager(aktion="teil_vorschlagen")` vorschlagen.

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

- `animation(aktion="kollision", name=…)` prüft jedes 3. Bild exakt (OCCT-Schnittvolumen, Berühren ist erlaubt) und meldet Zeit,
  Teilpaar, Eindringtiefe und Volumen; die App markiert sie auf der Zeitleiste und färbt das Paar rot. **Jede
  Durchdringung muss gelöst werden**, gewollte Anlage mit `erlaube` oder Luft im Modell. Eine Überlappung, die die
  eingebaute Prüfung über `erlaubt_ueberlappung(a, b, grund=…)` zulässt, gilt auch in der Animation als erlaubt. Die
  eingebaute Prüfung nach jedem Lauf sieht nur die Ruhelage; ihre roten Schnittkörper blendet die App beim Abspielen
  aus.
- `animation(aktion="abspielen", name=…, an=True, schleife=False)`, `animation(aktion="springen", zeit=…)`, `animation(aktion="liste")`.
- `animation(aktion="video", name=…, breite=1920)` schreibt ein H.264-MP4 (oder `format="prores"`) nach
  `<Projekt>/output/animationen/` aus der Viewer-Sicht bzw. der Kamerafahrt.

### Aufbau-Video auf Zuruf

„Mach ein Aufbau-Video“, „das Modell soll sich aufbauen“: `animation(aktion="aufbau", …)`. Kein Code in model.py nötig;
der Kernel rechnet das Modell noch einmal und hängt die Aufbau-Animationen nur für diesen Lauf an.

```python
animation(aktion="aufbau", dauer_s=20, blickwinkel=["orbit", "iso", "schnitt"],
          schritte=["Drohne/Rahmen", "Drohne/Motor *", "Drohne/Stack", "Drohne/GoPro"],
          zeichnen=[{"vor": "Drohne/GoPro", "punkte": [[-30, -20, 52], [30, -20, 52], [30, 20, 52]]}])
```

- Je Blickwinkel ein MP4 mit denselben Zeiten (wie mehrere Kameras): `orbit` kreist (`umdrehungen`, `hoehe_grad`),
  `iso`, `vorne`, `rechts`, `oben` … stehen mit leichter Drift, `schnitt` schneidet hart zwischen den übrigen Einträgen,
  der Schnitt rückt auf das nächste Teil, das erscheint (`wechsel_s`).
- `schritte`: Teilname, Baugruppe als Präfix oder Muster mit `*`; Ungenanntes kommt am Ende. Ohne Liste in der Reihenfolge
  von `show()`, Teile einer Baugruppe zusammen. Sehr viele Schritte werden zusammengelegt (mindestens 0,08 s Abstand).
  Mit Musik: `{"auf": "Drohne/Motor *", "landet": 7.38}` lässt den Schritt genau auf einem Schlag landen (Schläge aus
  `hf-beats`), Schritte ohne Zeit liegen gleichmäßig dazwischen; `einflug_s` (Vorgabe dann 0,5) ist die Flugzeit davor.
- `einflug`: `oben` (fällt von oben ein), `explosion` (von außen zur Mitte), `keiner`. Kulisse steht von Anfang an.
- `details`: weitere Videos mit denselben Zeiten, die Kamera auf eine Baugruppe gerichtet, etwa dorthin, wo gezeichnet
  wird: `[{"auf": "Drohne/O4/Antenne*", "richtung": "iso_hinten_links"}]`.
- `zeichnen`: vor einem Schritt entsteht ein Strich in Kevins Lichtblau (ohne `von` endet er gerade, bevor das Teil
  erscheint), wie wenn er beim Sprechen zeichnet, dann kommt
  das Teil dazu. Punkte in mm auf der Fläche, der Strich hebt sich selbst etwas ab.
- Hochformat (Reels, Stories): `breite=1080, hoehe=1920`. Die Kamera rahmt dann nach der schmalen Breite, damit das
  Modell seitlich nicht angeschnitten wird; Zeiten und Zeitplan bleiben wie im Querformat (beide Fassungen schneiden
  sich gleich).
- Die Antwort nennt die Videos und den Zeitplan (wann welcher Schritt erscheint), zusätzlich als
  `output/animationen/<name>_zeitplan.json`: Daraus setzt man im Schnitt Texte genau auf die Teile.
- Nach dem nächsten normalen `run` sind die Aufbau-Animationen wieder weg.

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

- `animation(aktion="video", name="Fahrt", kamera="FX6")` rendert durch die Kamera (Bildwinkel der Kamera, Seitenverhältnis ihres
  Formats, eigenes Objektiv ausgeblendet) nach `output/animationen/Fahrt_FX6.mp4`. `animation(aktion="liste")` und `run` nennen
  je Animation die Kameras, die mitfahren.
- Kevin: Taste 0, dann Leertaste; das Video aus Menü oder Zeitleiste entsteht beim Blick durch eine Kamera aus ihrer
  Sicht.
- Den Körper bewegt der Kernel nur, wenn keine eigene Spur ihn bewegt; Werte von `kamera(aktion="info")` gelten für die Ruhelage.
