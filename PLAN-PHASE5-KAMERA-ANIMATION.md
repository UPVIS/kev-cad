# Kev CAD · Phase 5: Kamerasimulation und Animation

Stand: 21.10.2026 (Kevins Wunsch vom selben Tag). Baut auf Phase 2 auf (Zweig `phase2`). Zwei Stränge parallel.

## Ziel

**Kameras** wie am Set: echte Kameras mit Sensorformat und Objektiv an bestimmte Punkte setzen (frei im Raum oder an
einem Teil, etwa auf der FX6 auf dem Kamerawagen), alles einstellbar. Durch jede Kamera schauen, ihr Bild rendern, den
Bildausschnitt im Viewer als Rahmen sehen. Alles auch über MCP.

**Animation** wie in CAD-Programmen: Teile bewegen, drehen, entlang eines Pfads fahren, Räder rollen lassen, Gelenke
bewegen, Kamerafahrten; abspielen im Viewer, Kollisionen prüfen, als Video ausgeben.

**Fertig, wenn:**

1. „Setz die FX6 mit einem 35-mm-Objektiv auf den Wagen und zeig mir ihr Bild auf den Ball“ → Kamera sitzt am Bajonett
   der FX6 (Sensorebene mit Auflagemaß), Kev CAD zeigt den Bildausschnitt im Viewer und durch die Kamera (Taste 0 wie in
   Blender), mit Rahmen für das gewählte Format (UHD, DCI 4K, Full Frame oder Super 35) und Angaben zu Brennweite,
   Bildwinkel und Schärfentiefe.
2. „Rendere das Kamerabild in 4K“ → PNG im Projektordner, genau mit dieser Kamera.
3. „Lass den Wagen 2 m nach vorn rollen und schiebe dabei den Ball“ → Räder drehen sich passend zur Strecke, der Ball
   rollt mit, Abspielen im Viewer mit Zeitleiste, Kollisionen werden gemeldet.
4. „Mach daraus ein Video aus Sicht der FX6“ → MP4 im Projektordner.

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| K1 | **Kameras und Objektive als Katalogeinträge** (`art: "kamera"` mit Sensorformaten und Auflösungen je Modus, `art: "objektiv"` mit Brennweite bzw. Zoombereich, Blende, Naheinstellgrenze, Bildkreis, Bajonett, Auflagemaß); die Sony FX6 und gängige Objektive als Startbestand | Inventar-Regel: auch Kameras kommen aus dem Inventar; Kevin ergänzt seine Objektive per EAN wie andere Zukaufteile |
| K2 | **`lager.kamera(...)` in model.py** liefert eine Kamera mit Lage (frei, `an=` Teil plus Bezugspunkt, `blick_auf=`), Format, Brennweite, Blende, Fokus; mehrere Kameras je Projekt | Kameras gehören zum parametrischen Modell und folgen ihm |
| K3 | **Bildwinkel aus Sensorbreite und Brennweite**, Format bestimmt Seitenverhältnis und Ausschnitt; Schärfentiefe nach Zerstreuungskreis des Formats | Wie am Set rechnen, nicht schätzen |
| K4 | **Durch die Kamera schauen** im Viewer (Taste 0, Kamera-Liste), Rahmen mit Formatlinien und Sicherheitsbereichen, Kamera als Pyramide im Raum; Bild rendern über den vorhandenen Offscreen-Renderer | Vorhandene Bausteine, kein neuer Renderer |
| A1 | **Animation als Spuren im model.py** (`animation(dauer, fps)` mit `bewege`, `drehe`, `pfad`, `rolle`, `gelenk`, `kamera`), der Kernel liefert Schlüsselbilder und Lagen je Teil, die App spielt flüssig ab (nur Matrizen, kein Neuvernetzen) | Schnell, reproduzierbar, über MCP steuerbar |
| A2 | **Rollen ist eine Bedingung**, keine Physik: Drehwinkel = Strecke / Radius, Drehachse aus Lage des Rads | Genau und ohne Physik-Engine |
| A3 | **Kollisionen** im Kernel an Zeitschritten (OCCT-Abstand der Formen), Meldung mit Zeit und Teilpaar | Wie die Bewegungsstudie in CAD-Programmen |
| A4 | **Video** aus Offscreen-Bildern je Zeitschritt, zusammengesetzt mit ffmpeg (H.264, optional ProRes), aus Viewer-Sicht oder durch eine Kamera | ffmpeg ist da, der Renderer auch |

## Stränge

| Strang | Inhalt |
|---|---|
| **KAM Kameras** | Katalog (FX6 und Objektive), `lager.kamera`, Protokoll (CAMERA_UPSERT, Ansicht durch Kamera, Kamerabild), App (Kamera-Pyramide, Taste 0, Formatrahmen, Kameraliste, Einstellungen im Inspektor), MCP (`kamera_liste`, `kamera_setzen`, `kamera_ansicht`, `kamera_bild`) |
| **ANI Animation** | `animation(...)`-API, Spuren und Bedingungen, Protokoll (ANIM_DEF, Zeitstand), Zeitleiste in der App (Leertaste spielt ab, Pfeiltasten Bild für Bild, Umschalt+Pfeil Anfang/Ende wie in Blender), Kollisionsprüfung, Video-Ausgabe, MCP (`animation_abspielen`, `animation_springen`, `animation_video`, `kollision_pruefen`) |

Beispiel und Abnahme: Kevins Kugelschieber (Rollwagen, FX6, Bowlingball) aus `~/Documents/Kev CAD/Neues Projekt`.
