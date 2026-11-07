# Prüfen und montagegerecht konstruieren

Teil des Skills kev-cad. Was die eingebaute Prüfung nach jedem Lauf prüft und wie Befunde behoben werden; lesen, bevor du ein Modell als fertig meldest.

## Prüfen vor dem Fertigmelden (Kevin, 21.10.2026, gilt immer)

Nichts darf physikalisch unmöglich sein. Kev CAD prüft jeden Lauf selbst (Durchdringung, Schweben, Standsicherheit,
Einbaubarkeit). `run` wartet höchstens `warten_s` auf das Ergebnis (Vorgabe nach der Dauer des Laufs: bis rund 2,4 s
ab dem Start des Laufs, mindestens 0,4 s, nach einem langen Lauf bis 3 s). Ist die Prüfung bis dahin fertig, stehen ihre
neuen Befunde in der Antwort. Nach einer Änderung an einem größeren Modell kommt sie in Stufen: erst Durchdringung,
Bedingungen und Stand, dann Druck, Montage, Statik und Bewegungsraum („Druck, Montage, Statik und Bewegungsraum rechnen
noch im Hintergrund“, Zustand `teilweise`). Ist auch die erste Stufe noch nicht da, sagt `run` „Prüfung läuft noch im Hintergrund“
und nennt vorläufig die Befunde der Bedingungen. Die Prüfung rechnet in jedem Fall ohne neuen Lauf weiter (Kevin sieht sie
im Prüfband). `pruefen()` wartet auf den Endstand und zeigt alles samt Stand und Montage. Befunde beheben, nicht nur
melden:

- **Vor dem Fertigmelden auf den Endstand warten** (Prüftempo, 22.10.2026; V2-1): Sagt `run` „Prüfung läuft noch im
  Hintergrund“, „… rechnen noch im Hintergrund“ oder schafft der Bewegungsraum sein Zeitlimit nicht („Bewegungsraum: 2
  Gelenke noch nicht geprüft (Zeitlimit), wird im Hintergrund fertig gerechnet“, Zustand `teilweise`), ist das kein
  fertiges Ergebnis.
  Kev CAD rechnet ohne neuen Lauf weiter; `pruefen()` (wartet standardmäßig, `warten=true`) bzw.
  `pruefen(thema="bedingungen")` zeigt den Endstand. Erst wenn dort keine Fehler mehr stehen, fertig melden. Nicht
  einfach `run` wiederholen, das verwirft das Fertigrechnen und beginnt von vorn.
- Große Modelle: `run(timeout_s=…)` (höchstens 900 s) hebt das Zeitlimit für model.py an, wenn ein Lauf daran scheitert.

- **Keine Durchdringungen:** Teile dürfen sich berühren, aber nicht ineinander stecken (gemeldet ab 0,001 mm³
  Schnittvolumen und 0,01 mm Tiefe). Verbindungselemente sind keine Ausnahme: Scheibe in Scheibe, Kopf in Scheibe,
  Schraube in einer zu kleinen Durchgangsbohrung. Die einzige Ausnahme erkennt Kev CAD selbst: echter
  Gewindeeingriff (Schraube in Mutter, Einsatz oder Kern-/Gewindeloch, gleiche Achse, nur im Gewindeband), metrisch
  und Zoll (UNC/UNF, etwa 1/4"-20 und 3/8"-16 an Kameras und Stativen). Innengewinde dafür als Kernloch modellieren
  (M4 3,3, M6 5,0, 1/4"-20 5,1, 3/8"-16 7,94; Tabelle unten). Ohne App (im geklonten Repo, bei Kevin
  `~/Code Experiments/Kev CAD`): `cd "<Repo>/kernel" && .venv/bin/python tools/check_interference.py
  "<Projektordner>" [--kontakte] [--gewinde]` rechnet eine Kopie mit genau dieser Prüfung (gleiche Schwellen,
  Gewindeeingriff, `erlaubt_ueberlappung`).
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
  „Bewegungsraum“ mit freiem Bereich). Was schon in der Ausgangslage im Gewinde greift, sperrt den Weg entlang bzw. um
  die Gewindeachse nicht (herausdrehen), quer dazu schon. Ein unveränderter Stand kommt aus dem Zwischenspeicher, bei
  Änderungen rechnen nur die betroffenen Gelenke neu. `<projekt>/bewegungen.json` gilt nur noch für Teile ohne Gelenk. Zum Ausloten
  weiter Bereiche einmalig `cd "<Repo>/kernel" && .venv/bin/python
  tools/check_motion.py "<Projektordner>" --teile … --drehen …`. Reicht der freie Bereich nicht für die Bedienung, wird
  umkonstruiert, nicht der Bereich verkleinert. Hat das Projekt eine Animation, zusätzlich `animation(aktion="kollision", name=…)`
  für jede Animation (siehe „Animation“).
- **Druckteile:** Die Druckprüfung läuft bei jedem Lauf für jedes `lager.druckteil` mit; `druck(aktion="pruefung")` zeigt
  Ausrichtung, Kennzahlen und alle Hinweise (siehe 3d-druck.md). Jedem Druckteil seinen Zweck geben
  (`lager.druckteil(…, zweck="tragend")`: zier, funktion, tragend, bewegt, aussen); `druck(aktion="vorschau")` sagt danach
  Filament, Zeit, Platten, Kosten und empfohlene Einstellungen (3d-druck.md, Abschnitt 16).
- Befestigung (`bed.verbinde`), Bewegungsraum, Schweben, Standsicherheit und Einbaubarkeit prüft Kev CAD bei jedem
  Lauf; `pruefen` zeigt das ganze Ergebnis, `pruefen(thema="montage")` die Einbaufolge.

## Montagegerecht konstruieren (Kevin, 21.10.2026, gilt immer)

Teile nicht irgendwo platzieren, sondern so, dass man sie vernünftig einbauen kann. Die Prüfung zerlegt jedes Modell
gedanklich (Montage durch Demontage): Ein Teil muss sich auf geradem Weg (±X, ±Y, ±Z, Achsen von Bohrungen und Bolzen,
erklärte Richtungen) aus dem Rest herausziehen lassen, dann das nächste. Umgekehrt ist das die Montagereihenfolge mit
Einführrichtung je Teil (`pruefen(thema="montage")`; Kevin sieht sie im Prüfband unter „Montage“ Schritt für Schritt).

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
- **Zukaufteile** kommen fertig montiert: Alle gezeigten Teile derselben Zukauf-Instanz (eine Stücklistenzeile, etwa
  Rahmen und Lenkrollen aus `lager.zukauf("alutec-05200").verbauen("Rollwagen")`) sind automatisch eine Baugruppe.
  Erklärte und gelieferte Baugruppen zählen auch in der übergeordneten Gruppe als ein Körper.
- **Befunde beheben statt wegerklären.** Erklärungen nur, wo sie stimmen, und im Code kommentiert:
  `montage("Rollwagen/Lenkrolle 1", baugruppe=True)` für Teile, die fertig montiert geliefert werden;
  `montage(clip, schnappt=True)` für Schnappverbindungen; `montage(mutter, eingedruckt=True)` für Muttern, die beim
  Druck eingelegt werden (Druckpause); `montage(teil, richtung="-z", nach=[...], werkzeug="inbus 6")` für Richtung,
  Reihenfolge und Werkzeug eigener Teile.
- **Zukaufteil rastet in ein Druckteil** (Rastzunge im Halter, 07.11.2026): `schnappt=True` wirkt nicht zusammen mit
  `baugruppe=True` (der Baugruppen-Zweig übergeht es). Richtung an der Baugruppe erklären und das Schnappen an dem
  Kind, das die Rastnocke berührt: `montage("Audio/Empfänger", richtung=…, nach="Halter", baugruppe=True)` plus
  `montage("Audio/Empfänger/Blitzschuh", schnappt=True)`. `richtung` ist die Bewegung beim Einsetzen.
