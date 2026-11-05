# Referenzen aus Video, Fotos und Scan

Teil des Skills kev-cad. Den echten Gegenstand aus Handyvideo, Fotos oder einem Scan mit Kev Scan vermessen.

## Referenzen aus Video und Fotos (Phase 4)

Kevin gibt ein Handyvideo oder einige Fotos des echten Gegenstands. Daraus entstehen ein maßstäbliches Referenznetz
(Apple Object Capture) und die gemessenen `param()`-Werte des Modells (fotomess), beides in
`<projekt>/referenzen/<name>/`. Beispiel mit Messmodell: `samples/scarlett/model.py`.

1. `referenz(aktion="video", pfad=…, masz={"laenge": 180}, auflage=True)` startet Object Capture im Hintergrund (rund 1 min);
   `referenz(aktion="liste", name=…, warten_s=300)` wartet. Ein echtes Maß ist Pflicht für den Maßstab (`laenge` = längste waagrechte
   Ausdehnung, sonst `breite`, `hoehe`, `grund_laenge`, `grund_breite`); `auflage=True`, wenn der Gegenstand auf einer
   Scheibe oder einem Tisch liegt; `von`/`bis` (s) schneiden das Video zu (etwa vor dem Umdrehen). Das Ergebnis nennt
   Hülle mit Anbauten und Grundkörper ohne Anbauten getrennt. Object Capture ist nicht deterministisch; misslingt die
   Freistellung, rechnet der Kernel selbst bis zu dreimal.
2. model.py als Messmodell bauen: ein Teil je sichtbarem Bauteil, Maße als `param()`, Teile, die sich nicht messen
   lassen (Unterseite, Füße), fest. Gemessen wird nur, was die Bilder zeigen; ein Modellfehler (falscher Rand,
   fehlender Knopf) verfälscht die Maße – die Kontrollbilder zeigen ihn (rote Punkte ohne Partner).
3. Optional `messmodell()` in model.py (wird nur zum Vermessen gelesen):

```python
def messmodell(p):                       # p: alle param()-Werte des Grundstands
    return dict(
        frei=["tiefe", "hoehe", "kanten_r"],            # zu messen
        bekannt={"breite": 180.0},                      # fest, gibt den Maßstab (von Hand gemessen)
        farbteile=lambda teil, flaeche: teil == "Gehaeuse",   # oder ["Gehaeuse"]: Flächen in der Objektfarbe
        zwillinge=["z180"],                             # vorn und hinten sehen gleich aus
        maske=dict(maske="vision+farbe", farbe_hsv=[[168, 4], 70, 25],   # Objektfarbe (OpenCV-HSV, über 0 hinweg)
                   ausschluss_hsv=[[6, 24], 50, 45], gehaeuse=True),     # Farbe der Unterlage, Blenden einfassen
        vorgaben={"tiefe": (110, 25)}, grenzen={"tiefe": (80, 130)},     # weich (Mittel, Sigma) und hart (mm)
        hoehen=[0, 80],                                 # Grobsuche: Kamerahöhen (Grad); kopfueber=True bei Unterseite
    )
```

4. `referenz(aktion="vermessen", quelle=…, freie_masse=None, bekannte_masse=None, bilder=8)` (ohne Angaben aus `messmodell()`):
   rund 1 min, Ergebnis Maße mit Sigma, Hülle und Grundkörper des eingepassten Modells, Hinweise (welches Maß von Hand
   nachmessen, welche Zusatzaufnahme). Liegt Object Capture zum selben Video vor, erkennt der Kernel Bilder, in denen
   das Modell gedreht liegt (Zwillingslage), rechnet sie neu und legt das Netz genau an das Modell an.
5. Prüfen: `referenz(aktion="fotoansicht", name=…, foto=n, bild_zeigen=true)` für dich selbst (nie an Kevin schicken), sonst die
   Kontrollbilder aus dem Ergebnis. Stimmen vorn und hinten nicht, Modell oder Messmodell korrigieren und neu messen;
   Bilder ohne Object-Capture-Kamera nennt das Ergebnis eigens.
6. Werte nicht selbst in model.py schreiben: Kevin übernimmt sie in der App mit „Maße übernehmen“ (auf 0,1 mm). Nur
   wenn er es ausdrücklich sagt, die `param()`-Werte selbst ändern. Unsicherheiten ehrlich nennen (Sigma) und das
   empfohlene Nachmessen vorschlagen.
7. **Abweichung:** `referenz(aktion="abweichung", name=…, zeigen=False, auf="modell")` nennt je Teil die mittlere, die 95-%- und
   die größte Abweichung zum Referenznetz, den Versatz mit Vorzeichen (**positiv = der echte Gegenstand ragt über das
   Modell hinaus, das Modell ist dort zu klein**; negativ = Modell zu groß) und den abgedeckten Anteil (Stellen ohne
   Referenz in der Nähe, etwa die Unterseite eines Scans, zählen nicht). Der Kernel rechnet sie nach jedem Lauf im
   Hintergrund (rund 1 s); `referenz(aktion="liste", name=…)` zeigt die Kurzfassung. Sinnvoll erst, wenn das Netz am Modell anliegt
   (nach `referenz(aktion="vermessen")`), sonst steckt der Lagefehler mit drin (das Ergebnis sagt es). `zeigen=true` schaltet
   bei Kevin die Farbkarte ein (blau Modell zu groß, grün passt, rot Modell zu klein, grau ohne Referenz, Legende in
   mm), `auf="referenz"` färbt stattdessen das Netz; `skala_mm` legt die Legende fest, 0 wieder automatisch. Nutze die
   Zahlen, um gezielt nachzubessern (größte Abweichung mit Ort), und nenne Kevin die Teile mit großer Abweichung.
8. **Maßstab nachträglich:** Hatte das Video kein oder ein falsches Maß, `referenz(aktion="massstab", mm=…, name=…, punkte=[[x, y, z],
   [x, y, z]])` mit zwei Punkten am Netz (Weltkoordinaten wie im Viewer, werden aufs Netz gezogen) oder
   `kante="laenge"` (Hülle: `laenge`, `breite`, `hoehe`, `grund_laenge`, `grund_breite`) bzw. dem Namen eines
   gemessenen `param`. Netz, Punktwolke, Kameras von Object Capture und Bericht skalieren mit, die Vermessung nur bei
   einem gemessenen `param` (dann gilt es beim nächsten Vermessen als bekannt). Scans vom iPhone sind metrisch und
   werden nicht skaliert. Kevin macht dasselbe in der App mit „Maßstab …“ (zwei Punkte anklicken, Maß eintragen).

- Kevin: Video oder Fotos auf das Fenster ziehen öffnet „Referenz hinzufügen“ (bekanntes Maß, Unterlage, Abschnitt);
  im Inspektor unter „Referenzen“ Netz mit Deckkraft, „Abweichung“ (Farbkarte auf Modell oder Netz, Legende in mm
  unten links im Viewer), „Maßstab …“, „Fotoansicht“ (Foto durch die eingepasste Kamera hinter dem Modell, Differenz
  rot nur Foto, blau nur Modell), „Vermessen …“ und „Maße übernehmen“.
- macOS fragt beim ersten Zugriff auf Downloads oder ein Wechselmedium, ob Kev CAD darf; bis Kevin antwortet, bricht
  `referenz(aktion="video")` mit einer Meldung ab. Dann Kevin bitten zu erlauben oder die Datei ins Projekt zu legen.

## Scan mit dem iPhone (Kev Scan)

Kevins iPhone-App Kev Scan nimmt LiDAR-Tiefe, ARKit-Kameralagen, Video und hochaufgelöste Fotos auf und schickt den
Scan per WLAN an Kev CAD (Bonjour, Ablage `~/Documents/Kev CAD/Scans/<datum>_<name>/`, Vertrag SCAN.md). Gegenüber
`referenz(aktion="video")` sind die Kameras bekannt und der Scan ist metrisch: kein bekanntes Maß nötig.

1. `referenz(aktion="scans")` zeigt die empfangenen Scans (Kennung, Fotos, Videobilder, ob eine Box gesetzt ist, wohin übernommen).
2. `referenz(aktion="scan_importieren", scan=…, name=None, schnell=False, warten_s=600)`: wertet im Hintergrund aus (alle Fotos plus
   Videobilder nach Abstand und Winkel, Prompt Depth Anything mit der LiDAR-Tiefe als Prompt, TSDF etwa 2 mm, größte
   Komponente; Boden z = 0, Mitte x = y = 0, lange Seite = X) und legt eine Referenz an, Netz halbdurchsichtig im
   Viewer. `schnell=True` (kleines Modell, weniger Bilder) als Vorschau in ein bis zwei Minuten; genau braucht etwa
   2 s je Bild (typisch 2 bis 4 min). Ohne WLAN: ZIP per AirDrop, dann
   `referenz(aktion="scan_importieren", scan="/Users/…/Downloads/x.kevscan.zip")`.
3. Messmodell bauen wie bei Phase 4, dann `referenz(aktion="vermessen", quelle=…, freie_masse=[…])`: fotomess nimmt die
   ARKit-Kameras als feste Startwerte (nur fein nachgeführt), passt die Modellkanten an die Bilder und das Modell an die
   gemessene Tiefe (robust, nach Konfidenz gewichtet) und legt das Netz an das Modell. `bekannte_masse` sind nicht
   nötig; wenn Kevin ein Maß sicher kennt, darf es trotzdem fest sein.
4. Ergebnis wie bei Phase 4 prüfen (Kontrollbilder, Sigma, `referenz(aktion="abweichung")`) und Kevin „Maße übernehmen“
   lassen.

In der App: Ein neu empfangener Scan erscheint als Band „Neuer Scan empfangen: <Name>“ mit „Scan übernehmen“
(Schnell oder Genau) ins offene Projekt, dasselbe wie `referenz(aktion="scan_importieren")`; im Inspektor unter „Referenzen“ steht die
Liste der Scans, die laufende Auswertung zeigt „Scan wird ausgewertet …“ mit Phase und Fortschritt.

Ehrliche Grenzen: LiDAR misst nur bis etwa 5 m und schlecht auf Glas, Spiegeln, sehr dunklen und glänzenden Flächen;
dort fehlt Tiefe (Konfidenz 0) und das Netz hat Löcher. Dünne Teile unter etwa 5 mm (Kabel, Bleche von der Kante)
fallen in der TSDF weg. Lagen von ARKit driften bei langen Aufnahmen um einige Millimeter; das Nachführen in fotomess
fängt das bei den Maßen ab, das Netz selbst bleibt so genau wie die Aufnahme. Die Unterseite fehlt immer. Bewegliche
Teile (Deckel, Räder) müssen während der Aufnahme stillstehen.
