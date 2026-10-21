# Kev CAD · Statik, Stabilität und Simulation

Stand: 21.10.2026 (Kevins Wunsch vom selben Tag). Projekt für später; baut auf den Prüfungen (Schweben, Kippen), den
Zwangsbedingungen (Gelenke) und der Animation auf.

## Ziel

Kev CAD rechnet aus, ob eine Konstruktion hält und sich vernünftig verhält: bei Eigengewicht, Nutzlast, Schieben,
Bremsen, Schräglage, Stoß. Es spielt Belastungsszenarien durch, auch viele Varianten auf einmal, und sagt klar, was
sinnvoll ist und was Unsinn: zu schwach, kippt, rutscht, biegt sich zu stark, oder deutlich überdimensioniert und
unnötig schwer und teuer. Ergebnisse erscheinen im Viewer (Farbverlauf, überhöhte Verformung, Ablauf in der Zeitleiste)
und als Befunde wie bei der Prüfung.

**Fertig, wenn (am Kugelschieber):**

1. „Was passiert, wenn ich mit 1 m/s schiebe und abrupt bremse?“ → Simulation zeigt, ob der Ball aus dem Schieber
   springt und ob das FX6-Rig kippt, als Ablauf in der Zeitleiste, mit Kippreserve und Rutschgrenze in Zahlen.
2. „Hält der Rohrrahmen, wenn ich mich mit 30 kg draufstütze?“ → Verformung, Spannung, Sicherheitsfaktor, Ampel, in
   unter einer Sekunde.
3. Ein gedruckter Halter mit Last quer zur Schicht bekommt rot und den Hinweis „drehen oder verstärken“.
4. Ein Rahmen aus 40 × 40 × 3 mit Sicherheitsfaktor 25 bekommt „überdimensioniert, 30 × 30 × 2 aus dem Lager reicht,
   spart 2,1 kg und 6 €“ (Vorschlag nur aus dem Inventar).

## Bausteine (geprüft am 21.10.2026: auf dem Mac verfügbar)

| Stufe | Werkzeug | Lizenz | Wofür | Tempo |
|---|---|---|---|---|
| S0 sofort | eigener Code (numpy, scipy) | – | Schwerpunkt, Kippwinkel, Rutschen über Reibwert, einfache Träger, Schraubenlast | Millisekunden |
| S1 Rahmen | **PyNite** (PyNiteFEA 3.2) | MIT | Stabwerk aus den Lagerteilen (Querschnittswerte aus dem Katalog), Lastfälle und Kombinationen, Verformung, Spannungen, Auflagerkräfte, P-Delta; Knicken über Eigenwerte (scipy) | unter 1 s |
| S2 Dynamik | **MuJoCo** (3.16) | Apache-2.0 | Starrkörper mit Masse und Trägheit aus build123d, Gelenke aus den Zwangsbedingungen, Reibung, Kontakt; Schieben, Bremsen, Neigen, Stoß, Fallen; `mujoco.rollout` rechnet viele Varianten parallel auf allen Kernen | deutlich schneller als Echtzeit |
| S2 Kollisionsformen | **CoACD** (1.0) | MIT | zerlegt Teile in konvexe Stücke für schnellen, stabilen Kontakt | einmal je Teilstand, zwischengespeichert |
| S3 Festkörper | **Gmsh** (4.15, eigener Prozess) | GPL | Tetraedernetze direkt aus STEP | Sekunden |
| S3 Festkörper | **scikit-fem** (12) mit **pyamg** (5.3) | BSD, MIT | lineare Elastizität bis einige 100.000 Freiheitsgrade: Spannung (von Mises), Verformung, Sicherheitsfaktor | Sekunden |
| S3 später | **CalculiX** (eigener Prozess) | GPL | Kontakt, Plastizität, Beulen; nicht in Homebrew, über conda-forge oder selbst gebaut | Sekunden bis Minuten |

GPL-Werkzeuge laufen nur als eigene Prozesse; für Kevins eigenes Werkzeug unproblematisch.

**Beschleunigung, ehrlich:** Auf dem Mac bringt Mehrkern-CPU am meisten (MuJoCo-Rollouts parallel, Accelerate/BLAS
für die Löser). GPU-Wege für FEM sind auf dem Mac experimentell (JAX-Metal) oder fehlen für das aktuelle Python
(Taichi). Falls scipy zu langsam wird: Apples Accelerate-Sparse-Cholesky über ein kleines Swift-Hilfsprogramm. Dazu
gilt immer: erst die schnelle Stufe, die genaue nur auf Nachfrage oder im Hintergrund; Zwischenspeicher je Teilstand.

## Entscheidungen (Vorschlag)

| Nr. | Entscheidung | Begründung |
|---|---|---|
| T1 | **Drei Stufen statt einer großen FEM:** S0 bei jedem Lauf, S1/S2 auf Anfrage in unter einer Sekunde bis wenigen Sekunden, S3 im Hintergrund | Schnelle Antworten im Gespräch, Genauigkeit wo sie zählt |
| T2 | **Stabwerk aus Lagerteilen automatisch:** Rohre und Profile aus Phase 2 werden zu Stäben mit bekannten Querschnittswerten, Verbindungen aus den Zwangsbedingungen (fest, gelenkig) | Gestelle sind der häufigste Fall, Stabwerke rechnen tausendfach schneller als Volumen-FEM |
| T3 | **Szenarien in model.py:** `szenario("Bremsen", ...)`, `last(teil, kraft=..., punkt=...)`, `beschleunigung`, `neigung`, `stoss`; dazu typische Szenarien je Gegenstand von selbst (Möbel: Sitzlast, seitlicher Stoß; Kamera-Rig: Anfahren und Bremsen; Regal: volle Fachlast) | Kevin muss keine Lastfälle erfinden, kann sie aber genau vorgeben |
| T4 | **Animation und Simulation teilen die Zeitleiste:** Spuren der Animation treiben die Simulation (Schieben mit Geschwindigkeit), das Ergebnis ist eine Animation (Lagen je Zeitschritt) mit Kontaktkräften; Video-Ausgabe wie bei der Animation | Ein Ablauf, zwei Modi: „vorgegeben“ (Kinematik) und „simuliert“ (Physik) |
| T5 | **Klare Urteile:** Ampel je Szenario aus Sicherheitsfaktor gegen Zielwert (statisch 2, dynamisch 3, 3D-Druck 4 wegen der Schichten), Kippreserve, Rutschgrenze, Durchbiegung (Standard L/200); „überdimensioniert“ ab Faktor 10 mit leichterem Vorschlag aus dem Lager | Sinnvoll oder Unsinn auf einen Blick, Vorschläge halten die Inventar-Regel ein |
| T6 | **Materialdaten im Katalog:** E-Modul, Querkontraktion, Streckgrenze, Zugfestigkeit, Reibwerte je Paarung; Druckmaterialien mit verminderter Festigkeit quer zur Schicht | Ohne Werkstoffdaten keine Statik |
| T7 | **Ehrliche Grenzen:** vereinfachte Modelle (Schweißnähte und Schrauben vereinfacht, linear-elastisch), kein Ersatz für einen Statiker bei sicherheitsrelevanten Dingen; das steht bei jedem Ergebnis dabei | Hinweise sollen helfen, nicht falsche Sicherheit geben |

## Arbeitspakete

| Paket | Inhalt |
|---|---|
| T-A | S0, Szenario-API, Materialdaten im Katalog, Befunde in der Prüfung, MCP `statik`, `szenario_rechnen` |
| T-B | S1 Stabwerk mit PyNite: Aufbau aus Lagerteilen und Bedingungen, Lastfälle, Knicken, Darstellung als Farbverlauf an den Rohren |
| T-C | S2 MuJoCo: Szene aus build123d (Massen, Trägheiten, CoACD), Gelenke, Reibung, Szenarien, parallele Varianten, Ergebnis als Animation |
| T-D | S3 Festkörper: Gmsh und scikit-fem, Farbverlauf (von Mises, Verformung) im Viewer, Hintergrundrechnung mit Fortschritt |

## Zu beachten

- Platz auf der Systemplatte ist knapp (am 21.10.2026 noch 18 GB frei); die Bausteine brauchen zusammen einige hundert
  MB.
- Abhängigkeit von Prüfungen (Kontaktgraph, Schwerpunkt), Zwangsbedingungen (Gelenke, Verbindungen) und Animation
  (Zeitleiste, Video): erst nach deren Übernahme starten.
