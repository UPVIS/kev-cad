# Benchmark der KI-CAD-Pipeline

Misst Auftrag rein, fertiges Modell raus: Gesamtzeit, Zeit bis zur ersten Geometrie, Modell- und Werkzeugaufrufe,
Tokens, Kosten, Korrektheit (Orakel) und Qualität (neue Befunde der Prüfung, Konventionen in model.py). Plan, Achsen und
Ergebnisse: [PLAN-PIPELINE.md](../PLAN-PIPELINE.md).

## Teile

| Datei | Inhalt |
|---|---|
| `aufgaben.py` | Aufgaben t1 bis t7 (Auftrag, Musterlösung, Orakel), Ketten k1, k2 (Neubau, dann Änderung) |
| `orakel.py` | misst die B-Rep-Formen der Szene selbst: Hüllquader, Zylinder (innen/außen), Bohrbilder, Kegel, Schnittvolumen |
| `lauf.py` | ein Lauf je Variante: Kernel im Prozess (Stand aus `kernel_src` der Variante), MCP über HTTP, Test-App versteckt, Agent als `claude -p` |
| `runde.py` | verschränkte Runde: je Aufgabe alle Varianten (Reihenfolge je Aufgabe gedreht), dann die nächste Aufgabe |
| `auswertung.py` | Tabelle je Lauf, Matrix je Aufgabe, Verhältnis zur Baseline (geometrisches Mittel), Ketten |
| `varianten/*.json` | Skill, Kernel-Stand, Modell, Denktiefe, Systemprompt, Werkzeuge, Lagebild im Auftrag |
| `referenzen/t7.json` | Fingerabdruck aller 132 Teile des geänderten Kugelschiebers (Musterlösung) |

## Ablauf

```bash
tools/fern.sh testbau bench                                   # Test-App "Kev CAD Test bench"
kernel/.venv/bin/python -u benchmark/lauf.py --referenz --aufgaben alle --ohne-app   # Stufe A: Musterlösungen
kernel/.venv/bin/python -u benchmark/runde.py --aufgaben t7,t5,t1 --varianten baseline,skill-neu,skill-neu-sonnet
kernel/.venv/bin/python benchmark/auswertung.py ~/Library/Caches/de.upvis.kevcad-bench
```

- **Verschränkt messen, nie in Blöcken:** Die Wartezeit der Modelle schwankt mit der Last bei Anthropic (Opus am
  06.11.2026 zwischen 2 und 24 s bis zum ersten Zeichen). Vergleiche nur innerhalb derselben Aufgabe.
- **Budgetwächter:** Jeder Lauf meldet die Auslastung des Wochenlimits; ab `--budget` (Vorgabe 0,75) startet keiner mehr.
- **Nichts von Kevin:** Katalog als Kopie, Projekte, Druckablagen und Bambu Studio umgelenkt, eigene Test-App mit
  eigenem Socket; Kevins Kugelschieber wird nur kopiert. Agenten laufen ohne Kevins Regeln und Hooks (außer `voll`),
  ohne Bash, Web und Unteragenten, ohne das Feedback-Werkzeug.
- **Ketten (Stufe D):** `--aufgaben k1` baut erst, ändert dann in derselben Sitzung (`--resume`) und frisch an einer
  Kopie desselben Stands; Ergebnisse als Aufgaben `k1:erst`, `k1:fort`, `k1:frisch`.
- **Nachprüfen:** `lauf.py --nachpruefen <Ablage>` bewertet gespeicherte model.py mit dem heutigen Orakel neu.
- **Feste Stände:** In einer Variante kann `skill`, `referenz` oder `kernel_src` als `@<Tag>:<Pfad>` stehen; `lauf.py`
  entpackt den Stand einmal per `git archive` in den Zwischenspeicher. Tags: `pipeline-baseline` (Stand vor dem
  Experiment), `pipeline-k1k3`, `pipeline-k4` (Experimentstände). `main` und `main-sonnet` messen den aktuellen Checkout
  und sind die Baseline für spätere Experimente.
- **Laufende Runde umsteuern:** `benchmark/STOP` (Aufgaben mit Komma, leer = alle) überspringt Läufe, `benchmark/BUDGET`
  (Zahl) ändert die Grenze des Wochenlimits; beide liest jeder Lauf beim Start, beide stehen in `.gitignore`.
- **Nie zwei Runden zugleich:** Alle Läufe teilen sich die Test-App und ihren Socket. Hintergrundketten nur über das
  Werkzeug starten, das sie verfolgt, nie mit `&` in einer Shell, die gleich endet (06.11.2026: zwei Ketten liefen
  parallel, die Läufe sind ungültig).

Die Ablage (`~/Library/Caches/de.upvis.kevcad-bench/<Zeit>-<Variante>/`) enthält je Lauf JSON, Ereignisstrom (JSONL mit
eigenen Zeitstempeln) und die model.py.
