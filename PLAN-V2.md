# Kev CAD · Plan V2 (KI-first)

Stand 05.11.2026. Arbeitszweig `v2` (Arbeitskopie `.claude/worktrees/v2`). V2 geht erst als Ganzes nach `main`, wenn
Kevin es abgenommen hat. Bis dahin bleibt seine installierte Fassung unberührt.

## 1. Ziel

Kevin, 05.11.2026 (diktiert, sinngemäß): Kev CAD soll ein vollwertiges CAD werden, mit dem man zusammen mit der KI
alles Mögliche entwirft, nur über Sprache. Dafür muss es extrem schnell sein. Die Oberfläche ist ihm zu umständlich:
direkt im Programm starten, eine aufgeräumte Grundansicht, zwei Modi, eine eigene Oberfläche, ein sehr guter Viewer und
Live-Zusammenarbeit mit Sprach-Feedback. Wörtlich: „mein Hauptziel ist es, damit Sachen zu bauen, möglichst komplexe
Sachen zu bauen“.

Drei Maßstäbe für jede Entscheidung:

1. **Tempo** in jedem Schritt der Schleife: Kevin spricht, der Agent versteht, das Modell ändert sich, Kevin sieht es.
2. **Gemeinsames Lagebild:** Der Agent weiß, was Kevin sieht und meint. Kevin sieht, was der Agent tut.
3. **Ruhe:** Die Oberfläche zeigt nur, was gerade zählt. Alles andere kommt auf Zuruf.

## 2. Entscheidungen

| Nr. | Entscheidung | Grund |
|---|---|---|
| V1 | Das Modell bleibt ein Rezept in Python (`model.py`, build123d). Schnell wird es über ein Rechengedächtnis je Operation, nicht über eine andere Sprache. | Gemessen am warmen Lauf des Kugelschiebers (7,6 s, 134 Teile): Booleans 42 % (OpenCascade, schon C++), Dateizugriffe 23 % (ein Fehler, behoben), der Rest Python-Logik. Modelle in C++ hätten eine Übersetzung bei jeder Änderung, drei- bis fünfmal mehr Code, Abstürze statt Fehlermeldungen mit Zeile und bräuchten erst eine eigene Bibliothek wie build123d. Kevins Idee „Operationen vom MCP gecastet“ setzt V2 als Gedächtnis je Operation plus Maßänderungen per `run(params)` um. |
| V2 | Nativer Code dort, wo wir selbst rechnen und es auf den Bildtakt ankommt: Viewer, Messen, Hover-Maße, Vorfilter der Kollisionsprüfung (Swift und Metal, C++ wo nötig). | Dort bringt Tempo am meisten, und keine fremde Bibliothek rechnet es schon. |
| V3 | Start ohne Dialog direkt in ein leeres Projekt. Alte Projekte über ein Overlay, das man wegschiebt. | Kevin |
| V4 | Grundansicht: nur Gruppen und Objekte. Stückliste, Zuschnitt, Druck, Zeichnungen und Animation erscheinen auf Zuruf als Kacheln. | Kevin |
| V5 | Zwei Modi: **Fokus** (ultraminimal, Fenster schmal am Bildschirmrand neben dem Chat) und **Werkstatt** (mehr Informationen, von Hand nachjustieren). | Kevin |
| V6 | Eigene Oberfläche mit eigenen Gestaltungswerten und Bausteinen statt macOS-Standardbausteinen. Tastatur, Zugänglichkeit und Bildtakt bleiben auf dem Niveau einer guten Mac-App. Gewählt ist **Graphit** (`docs/v2-entwurf/`), dazu aus Sucher der rote Rahmen um den Viewer, solange Kevin spricht, und nummerierte Kacheln; Zeichnungsblätter im Stil Reißbrett. | Kevin, 05.11.2026: „Wir folgen hier mal deinen Empfehlungen“ |
| V7 | Keine Manipulatoren. Änderungen macht der Agent, in der Werkstatt auch über Felder. Umbenennen bleibt. | Kevin |
| V8 | Steuerung wie Blender: Tastenbelegung, Hinweisleiste, Isolieren mit `/`. | Kevin |
| V9 | Live statt hingeworfen: Teile erscheinen, sobald sie fertig sind. Die Schritte des Agenten laufen knapp mit (Agentenspur), Maße und Befunde zeigen sich kurz am Teil. | Kevin |
| V10 | Sprach-Feedback wie in Sichtung: sprechen, zeigen, zeichnen, der Text erscheint live. Der Agent wartet, bis Kevin fertig ist, und bekommt ein Paket mit 3D-Kontext (Kamera, sichtbare Teile, Auswahl, Mausweg, Striche, Bild). | Kevin |
| V11 | Schlanke Agenten-Schnittstelle: ein Kernsatz von Werkzeugen, knappe Antworten, Details auf Abruf. | gemessen: 95 Werkzeuge, ein `run` rund 33.000 Tokens |
| V12 | Spiegelung aufs iPhone (KevCADWire, MIRROR.md) und VoiceBridge bleiben lauffähig. Eine Protokolländerung hält KevCADWire kompatibel oder zieht beide Seiten im selben Commit mit. | bestehender Vertrag |

## 3. Messwerte

Kugelschieber Variante B (134 Teile), gemessen mit `kernel/tools/messen.py`, Einzelheiten in `kernel/tools/MESSUNG.md`.
„Vorher“ ist main `f136caa`, „jetzt“ ist V2-1 mit `warten_s` 3.

| Lauf | `run()` vorher | `run()` jetzt | alle Teile im Viewer (jetzt) |
|---|---|---|---|
| erster Lauf | 29,9 s | 11,8 s | 7,1 s |
| nichts geändert | 7,9 s | 2,3 s | 1,4 s |
| nur Kommentar | 7,7 s | 2,3 s | 1,3 s |
| Maß geändert (28 von 599 Booleans neu) | 15,6 s | 5,1 s (2,2 s mit `warten_s=0`) | 1,7 s |

Schnittstelle auf main:
- **Werkzeuge:** 95, `tools/list` hat 137.092 Zeichen.
- **Anweisungen und Skill:** Server-Anweisungen 29.617 Zeichen, Skill rund 171.000 Zeichen.
- **Ein `run`:** 116.200 Zeichen, rund 33.000 Tokens.

Jeder Lauf schickt alle Teile neu an die App:
- 6,95 MB Teile
- 1,63 MB Statik
- 1,53 MB Animation
- bei einer neuen Version zusätzlich 5,9 MB Versionsbild

Ganze Rahmen gezählt (Kopf und Nutzlast, V2-5a) sind es 11,3 MB je unverändertem Lauf; dazu kommen große JSON-Köpfe
(Prüfung 404 KB, Statik bis 198 KB, Bedingungen 86 KB). Mit `delta-1` (V2-5) 44 KB, Einzelheiten in
`kernel/tools/MESSUNG.md`.

## 4. Budgets

| Was | Ziel | Stand |
|---|---|---|
| Maßänderung: erste geänderte Teile im Viewer | unter 1 s | 0,2 s für das erste, 1,7 s für das letzte Teil |
| Maßänderung: `run()` zurück | unter 2,5 s | 5,1 s (2,2 s mit `warten_s=0`) |
| unveränderter Lauf: `run()` zurück | unter 1,5 s | 2,3 s |
| Antwort von `run`: unverändert / kleine Änderung / erster Lauf mit 134 Teilen | 1.500 / 4.000 / 8.000 Zeichen | 490 / 2.389 / 1.449 Zeichen |
| Server-Anweisungen | höchstens 6.000 Zeichen | rund 5.000 Zeichen |
| Übertragung je unverändertem Lauf | unter 50 KB | 11,3 MB; mit `delta-1` 44 KB (Kernel fertig, App V2-5b offen) |
| App-Start bis bedienbares leeres Projekt | unter 1 s | offen |
| Drehen im Viewer (134 Teile) | 120 fps, mit SSAO mindestens 60 fps | am 60-Hz-Monitor 58 bis 60 Bilder/s, Technisch 41 (Hänger auf dem Hauptfaden); ohne Bildschirmtakt 383 bis 469 Bilder/s ohne SSAO, 153 bis 216 mit; 120 Hz noch nicht gemessen |
| Sprach-Feedback: Wort erscheint als Text | unter 0,3 s | offen |
| Feedback-Paket beim Agenten nach Ende des Sprechens | unter 1 s | offen |

## 5. Pakete

| Paket | Inhalt | Strang | hängt ab von | Stand |
|---|---|---|---|---|
| V2-1 Tempo im Kernel | Rechengedächtnis je Operation (Booleans, Aufräumen, Volumen, Hüllquader, Abstände), Leerlauf entfernt, `run` wartet höchstens `warten_s` auf die Prüfung, Nachlauf aus dem Auftragsfaden, Zeiten je Phase | Kernel | – | fertig, auf `v2` (`31618fd`) |
| V2-2 Agenten-Schnittstelle | Kernsatz von 10 bis 15 Werkzeugen plus je ein Fachwerkzeug mit `aktion`, knappes Laufergebnis, Anweisungen höchstens 6.000 Zeichen, Skill nach Themen, `status` als Lagebild, Maßänderungen per `run(params)` | MCP | V2-1 | fertig, auf `v2` (`541e1fc`), Zahlen in `kernel/tools/MESSUNG-V2-2.md` |
| V2-3 Neue Oberfläche | Gestaltungssystem, Start ohne Dialog, Projekt-Overlay, Fokus und Werkstatt, Gliederung nur mit Gruppen und Objekten, Kachelfläche, Fenster an den Rand | Oberfläche | Gestaltungsentwurf (gewählt: Graphit) | läuft |
| V2-4 Viewer | Xcode-Zwischenspeicher, Steuerung wie Blender, Hinweisleiste, Isolieren, Shading-Modi, Messen mit Vorschau beim Darüberfahren, Bild und Video mit einem Klick, keine Manipulatoren, Bildzeiten | App-Kern | – | fertig, auf `v2` (`d255717`); offen: Hänger auf dem Hauptfaden, Messung an 120 Hz, echte Eingaben von Kevin prüfen |
| V2-5 Live | Delta-Übertragung, Teile live, Agentenspur, Live-Maße und Befunde am Teil, Lagebild von der App zum Kernel (Einzelheiten unten) | Protokoll, beide Seiten | V2-1, V2-2 | V2-5a (Protokoll und Kernel-Seite) fertig, auf `v2` (`0388a41`); V2-5b (App-Seite) als Nächstes |
| V2-6 Sprach-Feedback | Spracherkennung, eine gemeinsame Uhr, Zeigen und Zeichnen, Paket mit 3D-Kontext, Werkzeug „auf Feedback warten“ (Einzelheiten unten) | App und MCP | Hülle aus V2-3, Lagebild aus V2-5 | Erkennung kann vorher starten |
| V2-7 Ergebnisse als Kacheln | Druck, Zeichnungen, Animation, Stückliste, Zuschnitt und zweite Ansicht als Kacheln statt eigener Fenster und Dialoge; Anordnen per Sprache und Werkzeug | Oberfläche, MCP | V2-3 | später |
| V2-8 Aufräumen und Abnahme | alte Dialoge und Bereiche raus, Doku und Skill nachziehen, Testsuite sauber, Übergang der Werkzeugnamen, Abnahme mit Kevin, nach main | alle | alle | zuletzt |

### V2-5 Live (Entwurf, das Paket legt es fest)

Festgelegt in PROTOCOL.md, Abschnitt „V2-5 Live“ (V2-5a); Befunde am Teil und die Spiegelung aufs iPhone sind dort noch
nicht enthalten.

- **Delta-Übertragung:** Der Kernel kennt je Teil den Inhaltsschlüssel (Tessellierungs-Schlüssel) und die Attribute, die
  er zuletzt geschickt hat. Unveränderte Teile schickt er nicht neu. Am Laufende nennt er die Liste der Teile, die es
  noch gibt, damit die App entfernte Teile löscht. Statikfeld, Animation und Versionsbild gehen nur, wenn sie sich
  geändert haben. Die Spiegelung aufs iPhone bekommt dieselbe Logik (V12).
- **Teile live:** Unveränderte Teile stehen sofort aus dem Gedächtnis. Ein Teil, das neu gerechnet wird, ist im Viewer
  markiert, bis es fertig ist. Zwischenstände einzelner Operationen nur, wenn sie das Tempo nicht drücken (gedrosselt,
  höchstens alle 0,3 s).
- **Agentenspur:** Heute setzt `ActivityTracker` (mcp_tools/tracking.py) eine Tätigkeitszeile je Werkzeug. Daraus wird
  eine Spur mit Schritten und Zeiten: Werkzeugaufrufe, Phasen des Laufs und optional ein kurzes `absicht`-Feld an jedem
  Werkzeug, ohne zusätzliche Runde. Zu prüfen ist, das Ende des Gesprächsverlaufs des Agenten von der Platte zu lesen
  (kostet den Agenten nichts, das Format ist aber intern und kann sich ändern).
- **Live-Maße:** Eine Maßänderung per `run(params)` zeigt den geänderten Wert kurz am Teil („Laufrolle 80 → 90 mm“).
  Dafür werden die Werkzeuge `annotate` und `highlight` genutzt; der Agent kann damit auch selbst ein Maß kurz zeigen
  („2 cm vom Rand“).
- **Befunde am Teil:** Die Befunde der Prüfung erscheinen als Marke am Teil statt nur in einer Liste.
- **Lagebild App → Kernel:** Kamera, sichtbare Teile, Auswahl, Teil und 3D-Punkt unter der Maus. Die App liefert das auf
  Anfrage (`status`) in unter 50 ms, damit nichts dauernd gesendet wird.

### V2-6 Sprach-Feedback (Entwurf, das Paket legt es fest)

Vorbild ist Sichtung (HyperFrames-Zentrale, `sichtung/`): Kevin spricht, zeigt und zoomt, das Feedback kommt mit Zeit
und Bezug als Anweisung zum Agenten.

- **Erkennung:** Wortlaut (Parakeet, eigener XPC-Dienst) mit Apple DictationTranscriber als Rückfall. Wortlaut verlangt
  die Signatur mit Kevins Team (2GX7UC98J6). Kev CAD signiert bisher ad hoc; das muss Kevin entscheiden.
- **Eine Uhr** für Wörter, Mausweg, Striche, Kamera und Auswahl. Jeder Satz bekommt, worauf Kevin beim Sprechen gezeigt
  hat („das hier“ ist das Teil unter der Maus in diesem Moment).
- **Paket** wie `sichtung-feedback/1`: Wörter mit Zeiten, Sätze mit Bezügen (Teile, Punkte, Striche), Kamera je Satz, ein
  Bild mit den Strichen, sichtbare Teile und Auswahl. Geschrieben wird atomar (temporäre Datei, dann umbenennen).
- **Warten:** Ein MCP-Werkzeug wartet lang auf das Ende des Feedbacks (kein Abfragen im Takt) und gibt das Paket
  zurück. Kevin beendet mit einer Taste oder einem Knopf.

## 6. Parallel arbeiten

- **Python** (Kernel, MCP) läuft parallel, solange der Speicher reicht (16 GB, andere Sitzungen laufen mit).
- **Swift-Bauten** laufen seit 05.11.2026 wieder auf Mac mini und MacBook (Kevin: „Mini und MacBook können gerne beide
  bauen“). Der Mini hat zwei Bauplätze; sind beide belegt, baut `tools/fern.sh testbau` hier unter der gemeinsamen
  Sperre `/tmp/vb-xcodebuild.lock`. Bis zu drei Bau-Agenten gleichzeitig.
- **Kernel-Tests** voll nur über `tools/fern.sh tests` (Testplatz auf dem Mini) oder lokal einzeln: Einige Tests nutzen
  feste Ports (etwa 40146, 47999), zwei volle Läufe gleichzeitig auf einem Rechner stören sich.
- **Verträge zuerst:** Pakete, die Kernel und App zugleich betreffen (V2-5, V2-6), beginnen mit einem Protokollentwurf
  in `PROTOCOL.md` samt Testdateien. Danach arbeitet je ein Agent an jeder Seite.
- **Zusammenführen:** Jedes Paket hat einen eigenen Zweig. Der Hauptagent prüft es und führt es auf `v2` zusammen.
- **Bauzeit:** V2-4 schaltet zuerst den Xcode-Zwischenspeicher ein, damit jeder weitere Swift-Bau aus dem Cache kommt.

## 7. Offene Punkte und Risiken

- **Tests:** 16 Statik- und Simulationstests mit CalculiX scheitern im vollen Lauf aus einer Agenten-Shell mit
  `UnicodeDecodeError` (ASCII). Auf der Basis `f136caa` ist das genauso. Einzeln laufen sie grün, auch unter
  `LANG=C.UTF-8` (`test_statik4.py::test_hertz_kugel_auf_platte`, 05.11.2026). Vermutlich stellt etwas im vollen Lauf die
  Locale des Testprozesses um. Das klärt V2-8 (Testsuite sauber).
- **Gedächtnis:** Es hängt an build123d 0.13.0 und schaltet sich bei einer anderen Fassung selbst ab (Prüfsumme der
  Quelle). Bei einem Update von build123d die nachgebauten Methoden in `gedaechtnis.py` prüfen.
- **Nachlauf im Hintergrund:** Bauplan, Blätter und Versionen entstehen nach `run` im Hintergrund. Wer `dokumente/`
  direkt nach einem Lauf ändert, kann damit kollidieren.
- **Warmer Lauf 2,3 s:** Den Rest kostet model.py selbst:
  - Gedächtnis-Aufwand 0,39 s
  - Verschiebungen mit Kopie der B-Rep 0,2 s
  - Fasen und Verrundungen 0,15 s
  - Zukaufteile 0,15 s
  - dazu die Statik der Prüfung mit 0,54 s

  Nächste Kandidaten: Fasen und Verrundungen ins Gedächtnis, Verschiebungen ohne Kopie, Statik je Modell merken.
- **Werkzeugnamen:** Neue Namen aus V2-2 brechen laufende Agentensitzungen, sobald V2 nach main geht. Den Übergang plant
  V2-8.
- **Fast Mode:** Fast Mode für Agenten greift nur mit Nutzungsguthaben auf claude.ai. Das entscheidet Kevin.

## 8. Fragen an Kevin

1. Wortlaut mit Signatur über sein Team oder nur Apples Erkennung?

Entschieden (05.11.2026): Gestaltungsrichtung Graphit mit zwei Teilen aus Sucher (siehe V6); Mac mini und MacBook bauen
beide (siehe Abschnitt 6).
