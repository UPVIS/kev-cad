# Messung V2-6 Sprach-Feedback

Stand 06.11.2026, MacBook M2 Pro unter fremder Last (Last 50 bis 100), Kugelschieber Variante B (134 Teile) als Kopie,
Testvariante mit Team-Signatur, Fenster hinter dem Schreibtischbild (`KEVCAD_TEST_VERSTECKT`). Aufruf:

```bash
tools/fern.sh testbau sprache
kernel/.venv/bin/python -u kernel/tools/feedback_selbsttest.py "$HOME/Documents/Kev CAD/Kugelschieber Variante B" [--pause]
```

Der Ton ist eine Tondatei (`say`, 5,1 s) über den Testeingang, also Apples Erkennung. Wortlaut lässt sich ohne Mikrofon nicht
messen; vom echten Dienst ist nur die Begrüßung geprüft (`KEVCAD_SELFTEST=wortlaut`: „Dienst Fassung 1: Begrüßung
angenommen“).

| Was | Budget | Messung |
|---|---|---|
| ↩ bis Paket beim Agenten (`feedback`, wartet über MCP) | unter 1 s | 142, 184, 243 ms |
| ↩ bis Datei geschrieben | | 138, 165, 207 ms |
| ↩ bis Hintergrundbefehl `kevcad-feedback` endet | | 172, 456 ms |
| wie oben, ↩ 0,5 s nach dem Weitersprechen (die Erkennung läuft neu an) | unter 1 s | 873, 992, 993 ms |
| Wort als Text nach Wortende, Apple-Rückfall, je Lauf | unter 0,3 s | Median 448 bis 473 ms, 90 % 915 bis 1647 ms, schlechtester Wert 1857 ms |
| `run` während Kevin spricht antwortet | | 4 bis 7 ms |

Das Wortbudget hält Apples Erkennung nicht: Sie liefert Zwischenstände im Schub. Wortlaut rechnet Zwischenstände im Takt von
0,4 s; ein Wort erscheint damit rechnerisch 0,2 bis 0,6 s nach dem Sprechen, auch das liegt über 0,3 s.

Drehen im Viewer, 2 s, ohne Sitzung gegen während des Sprechens (Bilder, Hauptfaden je Bild, GPU je Bild):

| Lauf | ohne Sitzung | beim Sprechen |
|---|---|---|
| 1 | 204, 1,17 ms, 5,93 ms | 228, 1,17 ms, 6,24 ms |
| 2 | 241, 1,13 ms, 5,26 ms | 258, 1,13 ms, 5,07 ms |
| 3 | 225, 1,11 ms, 10,17 ms | 241, 1,15 ms, 9,08 ms |

`KEVCAD_SELFTEST=viewer` im Wechsel gegen `v2` (`a0008c4`), Bilder ohne Bildschirmtakt je Sekunde und Hauptfaden je Bild:

| Darstellung | Basis (2 Läufe) | V2-6 (2 Läufe) |
|---|---|---|
| Solid ohne Verdeckung, ohne Kanten | 354, 309; 1,00, 0,93 ms | 340, 411; 0,89, 0,92 ms |
| Solid mit allem und Schatten | 84, 108; 1,71, 1,52 ms | 126, 154; 1,61, 1,40 ms |
| Material mit Verdeckung | 134, 154; 1,22, 1,24 ms | 160, 168; 1,23, 1,19 ms |
| Technisch | 109, 146; 1,28, 1,25 ms | 164, 169; 1,23, 1,15 ms |

Im Rahmen der Streuung unter Last gleich: Solange niemand spricht, läuft kein neuer Code im Bildtakt.
