# Sprach-Feedback

Kevin baut mit dir über Sprache. Er drückt V im Viewer, spricht, zeigt mit der Maus, zeichnet Striche aufs Modell und
beendet mit ↩. Solange er das nicht tut, gilt nichts davon als Auftrag: Sprache allein löst nichts aus.

## Abwarten

- **Du bist in einer Runde:** `feedback()` wartet, bis Kevin fertig ist, und gibt sein Feedback zurück (Vorgabe 600 s,
  höchstens `warten_s=1800`). Läuft die Zeit ab, ist das kein Fehler: Die Antwort sagt, was er gerade tut. Dann noch
  einmal `feedback()`. Für „sag mir, was du willst“ `feedback()` statt einer Frage im Chat, wenn er am Viewer sitzt.
- **Deine Runde endet: immer zuhören** (Kevin, 07.11.2026: „egal was ist … immer im Hintergrund listening“). Starte
  vor dem Ende jeder Runde den Befehl aus `status` oder `feedback()` als Hintergrund-Shell mit der längsten Zeitgrenze
  (in Claude Code `run_in_background`, `timeout` 7200000; die Vorgabe beendet ihn nach 30 Minuten). Er endet genau dann,
  wenn Feedback da ist, und weckt dich; dann `feedback()`, danach wieder starten. Der Befehl holt selbst nichts ab. Endet
  er an der Zeitgrenze ohne Feedback, sofort neu starten. Der Stop-Hook `kevcad-feedback --stop-hook` hält eine Runde an,
  die enden will, während die App verbunden ist und niemand zuhört; `kevcad-feedback --zuhoerer` zeigt, ob jemand wartet.
- **`status`** nennt, ob Kevin gerade spricht und ob Feedback wartet. Ein offenes Paket liefert `feedback()` sofort,
  auch aus einer früheren Sitzung. `feedback(nochmal=true)` liefert das zuletzt abgeholte noch einmal.

## Was zurückkommt

```
Kevin ist fertig: 2 Sätze, 1 Strich, 0:34 (fb-20261105-223011, Lauf 7)
1. [0:01] „Mach das hier höher.“
   → „hier“ = Halter/Lasche#f3 bei (120; 4; 62); Strich 1 auf Halter/Lasche, 84 mm
2. [0:06] „Und den Rest lass so.“
Im Bild: 12 Teile, 3 ausgeblendet
Einzelheiten (Wörter, Mausweg, Striche): …/feedback/fb-20261105-223011.json

Lagebild (status und Gliederung, beim Abholen erhoben): Projekt Wandhalter
Letzter Lauf 7: ok, 12 Teile
Prüfung (Lauf 7): 2 Hinweise
model.py (…/model.py): 84 Zeilen, 2913 Zeichen
Parameter (5):
  Z9 hoehe = 60  # Lasche
…
```

Dazu ein Bild der Ansicht mit seinen Strichen und einer Nummer je Satz am Zeiger. Das Lagebild darunter ersetzt `status`
und `modell(gliederung=true)`: gleich ändern (`modell(setze=…)` oder die Zeilen lesen, die du brauchst), dann `run`.

- „Das hier“, „da“, „dieser“ meinen das Teil unter der Maus in diesem Moment: Das steht in der Zeile unter dem Satz.
- Refs gelten für den genannten Lauf. Lief das Modell seitdem neu, stimmen die Teilnamen weiter, Flächen und Kanten
  suchst du neu (`parts`, `measure`).
- Text kann Erkennungsfehler haben. Wirkt ein Wort falsch, nimm den Sinn und Kevins Zeiger; frag nur, wenn beides
  nicht reicht.
- Die JSON-Datei hat alles auf einer Uhr: Wörter mit Zeiten, Mausweg, Kamera je Satz, Striche als 3D-Punkte. Nur lesen,
  wenn der Text nicht reicht.

## Während Kevin spricht

Nichts Neues beginnt, Laufendes läuft zu Ende, die Kamera gehört ihm:

- `run`, `view` (Kamera, Sichtbarkeit, Schnitt, Explosion) und `projekt` antworten sofort mit „Kevin spricht gerade“.
  Dann nicht wiederholen, sondern `feedback()`.
- Ein Auto-Lauf nach dem Speichern wartet, bis er aufhört. Du darfst weiter Dateien schreiben.
- Anmerkungen, Hervorhebungen und Lesen gehen weiter.
- Drückt er V, um kurz anzuhalten (Pause), arbeitest du normal weiter. Die Sitzung bleibt offen, bis er ↩ oder esc
  drückt; verwirft er sie, kommt nichts.
