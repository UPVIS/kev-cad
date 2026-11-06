# Ergebnisse auf Zuruf: Kacheln, Leisten, Rand

Teil des Skills kev-cad. Kevin sagt, was er sehen will, und das Ergebnis erscheint wie in einem Fenstermanager neben dem
Modell. Du erzeugst das Ergebnis und stellst die Fläche mit `view`; alles geht im selben Aufruf, Kevin klickt nichts.

## Auf Zuruf

| Kevin sagt | Du tust |
|---|---|
| „3D-Druck ready“, „druckfertig“, „Druck“ | `druck(aktion="vorschau")`, Befunde ansehen und beheben, `view(kacheln=["druck"])`. Die Kachel zeigt Platten, Filament, Zeit, Kosten und Befunde. Vor einem Export nach dem Filament fragen; gedruckt wird nur auf sein ausdrückliches Wort, dann `druck(aktion="drucken")` (öffnet den Dialog). |
| „Zeichnungen“, „Zeichnung vom Rohr“ | Fehlt ein Blatt: `zeichnung(aktion="erstellen")`. Dann `view(kacheln=["zeichnung"])`, mit `blatt="Rohr"` (Titel, Nummer oder Kennung) genau dieses Blatt. |
| „Bauplan“, „Anleitung“ | `bauplan(aktion="zeigen")`, `view(kacheln=["bauplan"])`. |
| „Stückliste“, „was kostet das“ | `parts(stueckliste=true)`, `view(kacheln=["stueckliste"])`. |
| „Zuschnitt“ | `view(kacheln=["zuschnitt"])`; `["material"]` zeigt alles zu Material, Bestand und Einkauf. |
| „Animation“, „lass es laufen“ | `animation(aktion="abspielen", …)`, `view(kacheln=["animation"])`: Die Zeitleiste steht als Streifen unter dem Modell, das Video kommt von dort. Steht der Viewer allein (auch am Rand), reicht `view(zeitleiste=true)`; beim Abspielen erscheint sie dort von selbst. |
| „Rendern“, „mach ein schönes Bild“ | `view(kacheln=["render"])`; Kevin stellt Szene und Größe dort ein, oder du rufst `render(…)`. |
| „zeig das von vorn daneben“ | `view(zweite_ansicht="front")` öffnet die zweite Ansicht. Sie folgt deinen Kamerabefehlen: `view(focus=[…])` zeigt dasselbe Ziel aus ihrer Richtung. |
| „Kachel 2 groß“, „wieder alle“ | `view(kachel_gross=2)`, `view(kachel_gross="aus")` |
| „mach die Stückliste zu“, „alles zu“ | `view(kachel_zu=["stueckliste"])` oder Nummern, `view(kachel_zu="alle")` |
| „nur Modell und Druck nebeneinander“ | `view(kacheln=["modell", "druck"], kacheln_nur=true)` |
| „nur das Modell“, „Kacheln weg“ | `view(kachel_gross="modell")`: Der Viewer steht allein, die Kacheln bleiben eingeklappt. `view(kachel_gross="aus")` holt sie zurück. |
| „Objekte zeigen“, „Eigenschaften“, „Leiste weg“ | `view(leiste_links=true)` bzw. `false` (Objekte), `view(leiste_rechts=true)` bzw. `false` (Eigenschaften und Maße des Modells) |
| „an den Rand“, „wieder groß“ | `view(rand="rechts")` bzw. `"links"`, `view(rand="aus")` |

## Was man wissen muss

- Höchstens vier Kacheln, nummeriert 1 bis 4 in der Reihenfolge, wie Kevin sie sieht. `status` nennt sie: „Fläche:
  1 Modell, 2 Druck (groß), Objekte links, Fenster am rechten Rand“. Eine fünfte verdrängt die älteste außer dem Modell.
- Ohne Kacheln reicht der Viewer bis an die Fensterkante, die Kopfleiste schwebt darüber, die Objekte stehen leise links im
  Bild. Eine Kachel holt die Kachelfläche dazu: Die Objekte werden zur Spalte links, daneben stehen Modell und Kacheln.
  Am Rand bleibt das Fenster schmal, die Kacheln stehen übereinander, die rechte Leiste geht zu.
- Es gibt keine Modi mehr, nur die beiden Leisten (Kevin schaltet sie oben links und rechts oder mit ⌘1 und ⌘2). Ältere
  Aufrufe mit `modus` gehen weiter: `fokus` ist nur das Modell ohne rechte Leiste, `werkstatt` Kacheln mit rechter Leiste.
- `kacheln` fügt hinzu; mit `kacheln_nur=true` sind es genau diese. `animation` bringt `modell` mit.
- Kachelnamen: `modell`, `zeichnung`, `bauplan`, `stueckliste`, `zuschnitt`, `druck`, `animation`, `ansicht`, `material`,
  `simulation`, `versionen`, `details`, `render`.
- Eine ältere App meldet, dass sie die Kacheln nicht kennt: Sag Kevin, dass Kev CAD aktualisiert werden muss.

## Entwurf benennen

Ein neues Projekt startet als Entwurf „Neues Projekt“. Sobald klar ist, was entsteht, gibst du ihm einen Namen:
`projekt(name="Kugelschieber")`. Der Entwurf zieht nach `~/Documents/Kev CAD/<Name>`, die Antwort nennt den neuen Pfad von
model.py; ab dann nur noch diesen Pfad benutzen. Hat Kevin selbst umbenannt oder ein anderes Projekt geöffnet, beginnt dein
nächstes Ergebnis mit „Achtung, das offene Projekt ist jetzt …“ und dem neuen Pfad: Dann gilt dein alter Pfad nicht mehr.
