# Arbeitsablauf, Versionen, wenn etwas hakt

Teil des Skills kev-cad (Verzeichnis in SKILL.md). Der Ablauf einer Aufgabe in Kev CAD, die Versionen und die häufigsten Meldungen.

## Arbeitsablauf

1. `status`: offenes Projekt, Pfad von model.py, letzter Lauf, offene Befunde, Kevins Auswahl mit Werten, seine Kamera
   und was ausgeblendet ist. Nach jedem Kontextwechsel wieder `status`, nicht raten.
2. Kein Projekt: `projekt("Wandhalter", neu=true)` oder `projekt("Wandhalter")`. Ein bloßer Name landet in
   `~/Documents/Kev CAD/<Name>`.
3. Teile im Lager suchen: `katalog(suche="vierkantrohr 40x40x3")`, Materialien mit `katalog(art="material")` (siehe
   Inventar-Regel in [lager.md](lager.md)).
4. model.py mit den eigenen Dateiwerkzeugen schreiben oder ändern (Pfad aus `status`). `modell(code)` nur, wenn es keine
   Dateiwerkzeuge gibt.
5. `run` antwortet knapp mit dem, was sich seit dem letzten Lauf geändert hat, den du gesehen hast:
   - Kopfzeile mit Zahl der Teile, neuen, geänderten, entfernten und unveränderten Teilen; der erste Lauf einer Sitzung
     (oder nach `projekt`) nennt stattdessen die Baugruppen und alle Parameter (Namen für `run(params=…)`).
   - geänderte Teile mit Unterschied („24 × 24 × 90 mm (vorher … 100 mm), 51 g (−10,1 g)“, „verschoben um (1; 0; 0)“),
     über 25 Stück je Baugruppe gezählt;
   - Inventar-Regel und neue oder geänderte Befunde zuerst, mit Lösung, gleichartige zusammengefasst („Ebenso 11× bei
     …“); bekannte Befunde nur gezählt, behobene gezählt; Hinweise nur gezählt (`pruefen(hinweise=true)`);
   - Prüfstand (fertig, teilweise oder läuft noch), Statik, Stückliste und Version je eine Zeile, wenn sie sich
     geändert haben, dazu die Zeiten.
   Mehr auf Abruf: `run(detail="teile")` (jedes Teil), `run(detail="voll")` (alles wie früher), `parts`, `pruefen`.
   Ein Fehler kommt vollständig als isError mit Zeile, Auszug und Hinweis; die letzte gute Geometrie bleibt stehen.
   Korrigieren, wieder `run`. Bei größeren Änderungen mit `titel` (siehe „Versionen“).
6. **Maße ändern als Operation:** `run(params={"laufrolle_l": 90})` rechnet mit dem geänderten `param()`-Wert, ohne
   model.py anzufassen; mit dem Rechengedächtnis ist das in rund 2 s durch, und die Antwort nennt genau die Teile, die
   sich dadurch ändern. So Varianten durchprobieren; den gewählten Wert erst in model.py übernehmen, wenn Kevin ihn
   will. Ein `run` ohne `params` rechnet wieder mit den Werten aus der Datei.
7. Prüfen: Befunde beheben (siehe [pruefung.md](pruefung.md); meldet `run` die Prüfung als „läuft noch“ oder den
   Bewegungsraum als „wird im Hintergrund fertig gerechnet“, vorher `pruefen()` abwarten), Zahlen mit der Aufgabe
   vergleichen, wichtige Sollmaße mit `measure` nachmessen, `parts(stueckliste=true)` für Stückliste und Zuschnitt,
   `pruefen(thema="bedingungen")` für Bedingungen, Freiheitsgrade, Befestigung und Bewegungsraum. Kevin keine
   Screenshots schicken; Bilder nur zur eigenen Analyse (siehe [ansicht.md](ansicht.md)).
8. Meilenstein setzen (gilt immer): der letzte `run` der Aufgabe bekommt `meilenstein="Kurzer Titel"` und
   `notiz="Ein, zwei Sätze, was sich geändert hat und warum"`; er setzt ihn, wenn der Lauf fehlerfrei ist. Für einen
   schon gerechneten Stand geht weiter `versionen(aktion="meilenstein", titel=…, notiz=…)`.
9. Kevin kurz berichten: was gebaut ist, Hauptmaße, Masse, Kosten (Richtpreise), offene Annahmen, vereinfachte
   Zukaufteile, Einkaufsliste. Bei Bedarf `view(focus=…, hervorheben=…)` oder `view(anmerkung=…)`, damit er es im
   Viewer sieht.

Speichert Kevin model.py selbst und ist Auto-Lauf an, rechnet der Kernel von allein. `run` wartet dann auf diesen Lauf,
statt doppelt zu rechnen; die Antwort vergleicht trotzdem mit dem Stand, den du zuletzt gesehen hast.

## Versionen (Kevin, 21.10.2026, gilt immer)

Kev CAD versioniert wie Onshape oder Fusion: Jeder erfolgreiche Lauf, der eine Projektdatei geändert hat, wird eine
Version V<n> (alle Projektdateien: model.py, Hilfsmodule, `geometrie/`, `bewegungen.json`, `katalog.json`,
`kevcad.json`, `zukauf/`; nicht `output/` und `bestand.json`). Kevin sieht sie in der Leiste „Versionen“ mit
Vorschaubild, Zeit, wer (Kevin oder Agent), Teilen, Masse, Kosten und Prüfstand.

- **Titel:** Jede Version bekommt automatisch einen Titel aus dem Inhalt der Änderung („breite 120 → 140“,
  „+ Flügelschraube M4 (4×)“, „Rahmen, Schlitten geändert“, „Code aufgeräumt (ohne Wirkung)“). Bei größeren
  Änderungen `run(titel="Laufrollen auf Kugellager umgestellt")` in Kevins Worten mitgeben: Das wird der Titel der
  Version, der automatische steht darunter. Kleine Korrekturen brauchen keinen.
- **Am Ende jeder Aufgabe ein Meilenstein:** am letzten `run(meilenstein=…, notiz=…)` oder einzeln mit
  `versionen(aktion="meilenstein", titel=…, notiz=…)`, mit kurzem deutschem Titel
  („Stangenhalter mit Gewindeeinsätzen“) und einer Notiz in ein, zwei Sätzen. Erst nach dem letzten erfolgreichen
  Lauf, nicht auf einen kaputten Stand. Hat Kevin die Version selbst benannt, bleibt sein Name (`versionen(aktion="meilenstein")`
  meldet das, dein Titel steht dann darunter); `ersetzen=true` nur, wenn Kevin ausdrücklich darum bittet.
- `versionen(aktion="liste")` zeigt die Geschichte; `versionen(aktion="vergleichen", a="V12")` vergleicht mit dem aktuellen Stand (Parameter,
  Teile, Stückliste, Prüfstand, Code) und zeigt Kevin die alte Geometrie als Geisterkörper im Viewer.
- `versionen(aktion="wiederherstellen", version="V12")` nur auf Kevins Wunsch. Es ist nie zerstörend: ungesicherte Änderungen werden
  vorher eine Version, der Rückweg ist ein weiteres Wiederherstellen.
- `versionen(aktion="variante_anlegen", name="Leichtbau")` für Ideen, die den Hauptstand nicht anfassen sollen; `versionen(aktion="variante_wechseln", name="Hauptstand")` zurück. Kein Zusammenführen: Kevin entscheidet, wo es weitergeht.
- Kein eigenes Git im Projektordner anlegen und `.kevcad/` nicht anfassen; die Versionen verwaltet Kev CAD.

## Wenn etwas hakt

| Meldung | Bedeutung |
|---|---|
| Lauf fehlgeschlagen in Zeile N | Fehler in model.py; Auszug lesen, korrigieren, `run` |
| Unbekannte oder veraltete Referenz | nach dem letzten Lauf neu holen (`parts`, `measure()` ohne refs, `execute`) |
| App nicht verbunden | der Kernel läuft, die App hängt (noch) nicht an ihm; kurz warten, sonst Kevin bitten, Kev CAD zu öffnen |
| Kev CAD läuft nicht – bitte starten | die Brücke erreicht die App nicht; Kevin bitten, Kev CAD zu starten |
| Inventar-Regel: … nicht aus dem Inventar | Teil ohne `verbauen`/`druckteil` gezeigt; Lagerteil suchen, Druckteil kennzeichnen oder Kevin fragen |
| … wartet auf Kevins Freigabe | Vorschlag aus `lager(aktion="teil_vorschlagen")`/`lager(aktion="material_vorschlagen")`/`lager(aktion="zukauf_anlegen")`; `lager(aktion="freigabe", ids=[id], grund)` öffnet den Dialog im Projektfenster |
| Material '…' gibt es im Katalog nicht | nur Katalogmaterialien (`katalog(art="material")`); fehlt eins, Kevin fragen |
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
