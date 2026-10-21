# Kev CAD · Phase 5, Strang ANI: Animation (Umsetzung)

Stand: 21.10.2026. Ergänzt [PLAN-PHASE5-KAMERA-ANIMATION.md](https://github.com/UPVIS/kev-cad/blob/main/PLAN-PHASE5-KAMERA-ANIMATION.md)
(Entscheidungen A1–A4) um das, was beim Bauen entschieden wurde. Protokoll: [PROTOCOL.md](PROTOCOL.md), Abschnitt
„Phase 5: Animation“. Beispiel und Abnahme: `samples/kugelschieber-animation/` (Kopie von Kevins Kugelschieber mit den
Animationen „Fahrt“ und „Verstellen“).

## Aufbau

| Teil | Datei |
|---|---|
| API in model.py (`from kevcad import animation`) | `kernel/src/kevcad/bewegung.py` |
| Auswertung je Bild (numpy), Packen der Nutzlast | `kernel/src/kevcad_kernel/animation.py` |
| Kollisionsprüfung (eigene kleine Funktion, siehe unten) | `kernel/src/kevcad_kernel/anim_kollision.py` |
| Laufzeit: Ablage, Nachrichten, Dienstmethoden (Mixin in `KernelRuntime`) | `kernel/src/kevcad_kernel/anim_runtime.py` |
| MCP-Werkzeuge | `kernel/src/kevcad_kernel/mcp_tools/animation_tools.py` |
| Protokoll, Clip, Lage zur Zeit t | `app/KevCADCore/Sources/KevCADCore/Animation/AnimationMessages.swift` |
| Zustand für die Oberfläche, Aktionen | `…/Animation/AnimationModel.swift` (`AnimationModel`, `AnimationClock`, `AnimationActions`) |
| Abspielen | `…/Animation/AnimationPlayer.swift` |
| Video (OffscreenRenderer → ffmpeg) | `…/Animation/AnimationVideo.swift` |
| App-Kern | `…/Kernel/AppController+Animation.swift` |
| Zeitleiste, Menü und Tasten | `app/Sources/KevCAD/Animation/` |

## Entscheidungen

| Nr. | Entscheidung | Begründung |
|---|---|---|
| N1 | **Ausgewertet wird im Rechenprozess direkt nach model.py**, nicht in der App: Ergebnis sind fertige Matrizen je Bild und Teil (`ANIM_DEF`, float32 N × P × 12) | Fehler (unbekanntes Teil, Kreis bei `folge`) kommen als Lauffehler mit Zeile in model.py; die App rechnet nichts nach. Kugelschieber: 75 bewegte Teile × 241 Bilder in 8–12 ms |
| N2 | **Objekte und Baum**: jedes Ziel einer Spur ist ein Objekt; ein Teil gehört zum genauesten Objekt, Eltern sind das nächste umfassende Objekt oder ausdrücklich `folge`/`rolle(auf=)`/`gelenk(eltern=)` (nur wenn das Elternteil nicht ohnehin darüber liegt) | „Wagen“ bewegt alle „Wagen/…“, ein Rad darunter rollt zusätzlich, ohne doppelt zu fahren |
| N3 | **Reihenfolge je Objekt**: Lage = Eltern · Verschiebungen · Drehungen · Rollen; Achsen in der Ruhelage | Achsen stehen so, wie sie in model.py konstruiert sind, unabhängig von der Reihenfolge der Spuren |
| N4 | **Rollen (A2)** je Bildschritt aufsummiert: mit fester Achse dreht sich die Achse mit dem Elternteil (Winkel = Weg · (Achse × Z) / r), ohne Achse rollt das Teil frei wie eine Kugel (Achse = Z × Fahrtrichtung) | genau für gerade und gekrümmte Fahrten, ohne Physik |
| N5 | **Gelenke** nehmen Achse und Bereich als Daten: `gelenk(name, art, achse=(Punkt, Richtung) \| Axis, werte={t: wert}, grenzen=(min, max), eltern)`; Werte außerhalb werden begrenzt (Warnung) | Strang „Bedingungen“ hängt später seine Gelenke (build123d-Joints) an dieselbe Schnittstelle |
| N6 | **Pfad**: ohne `bezug` fährt die Mitte des Teils die Form des Pfads nach (Versatz = Pfadpunkt − erster Punkt), mit `bezug` sitzt dieser Punkt auf dem Pfad; gleichmäßig nach Bogenlänge, Spline = zentripetaler Catmull-Rom; `ausrichten` mit Z oben | vorhersehbar, kein Sprung am Anfang |
| N7 | **Sichtbarkeit**: vor dem ersten Eintrag gilt das Gegenteil des ersten (`sichtbar(an=True, zeit=2)` = erscheint bei 2 s) | so meint man es |
| N8 | **Abspielen nur über Matrizen**: `SceneStore.setAnimationPose` setzt die Lage der vorhandenen Körper (Basislage · Animation · Explosion), kein Neuvernetzen; Zwischenbilder bei 120 Hz durch Quaternionen-Slerp mit gerade geführter Teilmitte | flüssig; lineares Mischen ließ schnell drehende Rollen wandern (gefunden beim Abspielen) |
| N9 | **Zeit, Bild und Videofortschritt in `AnimationClock`**, getrennt von `AnimationModel` | bei 120 Hz zeichnet nur der Schieber neu, nicht Menüs und Fenster |
| N10 | **Kollision (A3)** auf Abruf (`kollision_pruefen`, Knopf in der Zeitleiste), jedes 3. Bild und das letzte; nur Paare, deren Lage zueinander sich ändert; Berühren erlaubt (Volumen < 0,5 mm³ oder Dicke < 0,05 mm), `erlaube(a, b)` für gewollte Anlage | Kevins Regel: jede Durchdringung wird gemeldet und muss gelöst werden |
| N11 | **Schnell ohne Abstriche**: Hüllquader je Bild vektorisiert; drehsymmetrische Teile, die sich nur um ihre Achse drehen (Rad, Rolle), zählen als starr (geprüft per Schnittvolumen mit sich selbst gedreht, Achse über den Schwerpunkt nachgeführt); dreht sich ein Teil nur um seine Mitte (rollende Kugel) und liegt das andere außerhalb seiner Hüllkugel, ist das Paar frei; gleiche relative Lagen nur einmal exakt | Kugelschieber „Fahrt“ 0,6–0,8 s statt 7 s, „Verstellen“ 1,2–3 s |
| N12 | **Eindringtiefe** = kleinste Ausdehnung des Schnittkörpers (Näherung), dazu Volumen und Ort | ehrlich benannt, ohne teure Abstandsrechnung |
| N13 | **Video (A4)** in der App: OffscreenRenderer je Bild, RGBA roh an ffmpeg (libx264 CRF 18 yuv420p bzw. prores_ks Profil 2, 10 Bit 4:2:2), Bild für Bild auf dem Hauptthread mit eigener Schreibwarteschlange; Ziel `<projekt>/output/animationen/<name>.mp4`, erst unter Hilfsnamen, dann umbenannt | App bleibt bedienbar, Fortschritt in Zeitleiste und Statusleiste; 1920 × 1080 × 241 Bilder in 9 s |
| N14 | **Kamera** für Videos: Parameter `kamera` ist da; `AppController.setAnimationCameraResolver` nimmt vom Strang KAM eine Funktion (Name, Zeit) → Kamera; bis dahin Viewer-Kamera bzw. Kamerafahrt aus `anim.ansicht` mit Hinweis | parallele Arbeit ohne gemeinsame Dateien |
| N15 | **Tasten wie in Blender** über ein eigenes Menü „Animation“: Leertaste, ←/→, Umschalt+←/→; KeyboardGuard schickt sie an Textfelder und die Pfeile an Listen (Teilebaum, Stückliste) | Textfelder und Listen bleiben bedienbar |

## Schnittstellen für das Zusammenführen

**Kollisionsprüfung** (Strang „Prüfungen“, soll auf `pruefung/kollision.py` umgestellt werden):

```python
pruefe_kollisionen(formen: Mapping[str, Shape], lagen: Mapping[str, ndarray (N, 4, 4)], zeiten: Sequence[float], *,
                   bilder=None, paare=None, huellen=None, kugeln=None, toleranz=0.05, min_volumen=0.5,
                   sichtbar=None, zeitlimit_s=None) -> tuple[list[Befund], dict]
Befund(zeit, bild, teile: tuple[str, str], volumen, tiefe, ort: (x, y, z))
```

Vorstufen in der Laufzeit (`anim_runtime.collision_check`): Lagen je Teil (für drehsymmetrische Teile ohne die eigene
Drehung), `bewegte_paare` (ohne starr verbundene und erlaubte Paare), Hüllkugeln, danach `zusammenfassen` zu Zeitspannen.

**Gelenke** (Strang „Bedingungen“): `Animation.gelenk(name, art="dreh"|"schub", achse=((x, y, z), (dx, dy, dz)) oder
Axis, werte={zeit: wert} oder [(zeit, wert), …], grenzen=(min, max) mit None für offen, eltern=None, kurve="weich")`.
Auswertung in `animation._Eval.track_matrix` (Art `gelenk`) und `joint_values`.

## Offen

- Messen und Referenzen beziehen sich weiter auf die Ruhelage aus model.py, auch wenn Teile animiert stehen.
- Benannte Kameras (KAM) für Video und Kamerafahrt anbinden (`setAnimationCameraResolver`, `kamera`-Parameter).
- Kollisionen nur auf Abruf; für sehr lange Animationen gilt ein Zeitlimit von 120 s (Meldung `abgebrochen`).
