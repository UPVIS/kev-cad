# Kev CAD V2 · Abnahme

Diese Liste ist für einen Abend gedacht, rund eine Stunde. Du spielst V2 in einer eigenen Testfassung durch, deine
installierte App und deine Projekte bleiben dabei unberührt. Was am Ende nicht stimmt, sagst du einem Agenten, und erst
wenn alles passt, geht V2 nach `main`.

## Vorbereiten

Im Arbeitsordner von V2 (`.claude/worktrees/v2` im Repo) startest du:

```bash
tools/abnahme.sh
```

Das baut die Testfassung „Kev CAD Test abnahme“, legt Kopien von Katalog und Kugelschieber nach
`~/Documents/Kev CAD Abnahme` und startet die App. Zum Schluss steht im Terminal, wie du einen Agenten mit dieser
Fassung verbindest. Weil sie neu signiert ist, kann macOS beim ersten Sprechen nach Mikrofon und Spracherkennung fragen.

Öffne für die Punkte 2 bis 5 mit ⌘O den Kugelschieber aus diesem Ordner, damit du ein großes Modell vor dir hast.

## Durchspielen

**1. Start.** Das Fenster steht in etwa einer Sekunde, ohne Dialog. Du siehst „Neues Projekt · noch nicht gesichert“ und
„Was soll entstehen?“. Sobald die Fassung ein Projekt kennt, liegt beim Start die Karte „Zuletzt geöffnet“ darüber; mit esc
schiebst du sie weg, mit ⇧⌘O holst du sie zurück. ⌘N legt ohne Formular ein neues leeres Projekt an, ein Doppelklick auf den
Titel benennt es.

**2. Maus und Tasten.** Das Modell dreht sich um den Punkt unter der Maus, wenn du mit der mittleren Taste oder mit ⌥ und
der linken Taste ziehst, auf dem Trackpad mit zwei Fingern. ⇧ dazu verschiebt, das Rad zoomt zur Maus. Beim Drehen darf
nichts stocken, auch mit Kanten und Schatten nicht (Z wählt die Darstellung). Probier 1, 3 und 7 für die Ansichten, mit ⌃
die Gegenseite, 5 für perspektivisch oder parallel, F für die Auswahl, Pos1 für alles. Dann A, ⌥A, H, ⌥H, / zum Isolieren,
Tab für Flächen und Kanten, S für den Schnitt, E für die Explosion und M zum Messen; beim Messen zeigt die Vorschau den
Wert schon beim Darüberfahren. ? zeigt alle Tasten. Tippst du in ein Textfeld, landen die Buchstaben dort und kein Befehl
feuert.

**3. Viewer und Kopfleiste.** Der Viewer reicht bis an die Oberkante, die Kopfleiste liegt ohne eigenen Grund darüber:
links der Schalter für die Objekte und der Projektname, rechts die Darstellung wie in Blender (Röntgen, Drahtgitter, Solid,
Material, Technisch und die Optionen im Pfeil), Foto, Video, Messen, Isolieren, An den Rand und ganz außen der Schalter für
die Eigenschaften. Auf hellem Bild (Technisch) bleibt alles lesbar. Leere Stellen der Kopfleiste ziehen das Fenster, ein
Doppelklick zoomt es. Links steht leise die Gliederung, rechts unten die Agentenspur. ⌃⌥→ schiebt das Fenster schmal an den
rechten Rand neben deinen Chat, noch einmal stellt Größe und Lage wieder her. Der Viewer flackert dabei nicht.

**4. Leisten.** ⌘1 schaltet die Objekte links, ⌘2 die Eigenschaften rechts, dasselbe tun die beiden Symbole oben. Rechts
wählt ein Klick ein Teil, ein Doppelklick benennt es um, und der neue Name steht danach in model.py. Änderst du unter „Maße
des Modells“ einen Wert, landet er ebenfalls in model.py, und „vorher …“ zeigt den alten Wert.

**5. Kacheln.** ⌃⌘1 bis ⌃⌘0 öffnen Stückliste, Zuschnitt, Zeichnung, zweite Ansicht, Material, Simulation, Versionen, Details,
Druck und Animation, Bauplan und Rendern stehen im Menü Kacheln. Höchstens vier sind offen und nummeriert, eine fünfte
verdrängt die älteste. ⌥⌘2 macht Kachel 2 groß und wieder klein, ⇧⌘W schließt die aktive. ⌘3 (oder das Kachelsymbol oben rechts) zeigt nur
das Modell und holt die Kacheln wieder zurück. Ein Wechsel soll sofort wirken.
Die Zeichnung zeigt groß Seitenleiste und Inspektor. Buche im Menü Modell › Material einmal „Gebaut …“: Oben erscheint das Band
mit „Rückgängig“, das beim Umbau kurz verloren gegangen war.

**6. Sprechen.** Drücke V, der Viewer bekommt einen roten Rahmen, und dein Text läuft unten mit. Sag „das hier“, während die Maus
über einem Teil steht, und zieh mit der linken Taste einen Strich aufs Modell. V hält an, ↩ schickt alles an den Agenten,
esc verwirft es. Achte darauf, wie schnell die Wörter erscheinen: Das Ziel war unter 0,3 s, gerechnet sind 0,2 bis 0,6 s,
und mit echtem Mikrofon hat das noch niemand gemessen. Sag, ob es sich gut anfühlt.

**7. Agent am Viewer.** Verbinde einen Agenten wie im Terminal beschrieben und lass ihn etwas bauen. Teile erscheinen einzeln,
sobald sie fertig sind, und die Agentenspur nennt seine Schritte. Lass ihn ein Maß ändern: Es sollte in rund zwei Sekunden
stehen, und am Teil erscheint kurz „alt → neu“. Sag dann „zeig mir die Stückliste“ und „Kachel 2 groß“: Die Fläche folgt ihm.
Gib ihm Sprach-Feedback wie in Punkt 6, er sollte wissen, welches Teil du gemeint hast.

Falls beim Drehen etwas ruckt, beende die Testfassung und lass sie einmal selbst messen:

```bash
kernel/.venv/bin/python kernel/tools/selbsttests.py "build/Kev CAD Test abnahme.app" \
  "$HOME/Documents/Kev CAD Abnahme/Kugelschieber Variante B" viewer --sichtbar
```

Das Fenster läuft dann rund eine Minute von selbst, und `selbsttests/viewer/selftest-viewer.txt` nennt die Bilder je Sekunde an
deinem Monitor. Diese Zahl kannst nur du messen, denn ohne zweiten Monitor am MacBook und am Mini kommt kein Bild auf einem
Bildschirm an.

## Was beim Wechsel nach main passiert

Der Wechsel ist ein einziger Merge von `v2` nach `main` im Hauptordner. Der Git-Hook startet dann das Update: Der Mini baut,
das MacBook signiert und installiert App, Kernel und Skill. Eine laufende App beendet sich und öffnet dein Projekt mit derselben
Kamera wieder. Das Protokoll steht in `~/Library/Logs/Kev CAD/update.log`.

**Rechte.** Die App trägt ab dann die Signatur deines Teams, vorher war sie ad hoc signiert. macOS sieht sie deshalb als neues
Programm und fragt einmal neu nach, etwa nach Mikrofon, Spracherkennung und dem Zugriff auf Ordner. Danach bleiben die Rechte
auch über spätere Updates erhalten, was vorher nicht so war.

**Signatur.** Signiert wird auf dem MacBook, weil dein Zertifikat nur dort liegt. Ist der Schlüsselbund gesperrt, signiert das
Update ad hoc weiter und nennt das im Protokoll. Die App läuft dann, nur Wortlaut hört nicht zu, und Apples Erkennung springt ein.

**Werkzeugnamen.** Agentensitzungen, die schon laufen, rufen noch die alten Namen. Sie bekommen als Antwort den neuen Aufruf mit
ihren Argumenten, ausgeführt wird dabei nichts. Damit ihr Client die neuen Werkzeuge kennt, braucht es `/mcp` zum Neuverbinden
oder eine neue Sitzung. Der Eintrag des MCP-Servers selbst bleibt, wie er ist, der Skill kommt mit dem Update.

**Projekte und VoiceBridge.** model.py und dein Katalog bleiben unverändert, es gibt keine Umwandlung. Der erste Lauf eines
Projekts rechnet einmal alles, danach hilft das Rechengedächtnis. VoiceBridge und der Spiegel aufs iPhone sprechen das gleiche
Protokoll wie bisher.

**Rückweg.** Der Wechsel lief am 06.11.2026 als Vorlauf (fast-forward) ohne Merge-Commit; der alte Stand trägt das Tag
`vor-v2`. Gefällt dir V2 im Alltag nicht, setzt `git restore --source=vor-v2 --staged --worktree :/` mit einem Commit auf
`main` den alten Stand wieder ein, und der Hook installiert wieder die alte Fassung. macOS fragt dann noch einmal nach den Rechten, weil die alte Fassung ad hoc signiert ist.
Projekte bleiben nutzbar. Entwürfe aus V2 liegen weiter im Datenordner, die alte App zeigt sie nur nicht an.
