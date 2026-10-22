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

## Stand Stufe 1 (T-A, T-B; Zweig `statik`, 22.10.2026)

Umgesetzt in `kernel/src/kevcad_kernel/statik/` (Übersicht im Docstring von `__init__.py`), API `kevcad.statik`,
MCP `statik` und `szenario_rechnen` (`mcp_tools/statik_tools.py`), Nachricht `STATICS` (PROTOCOL.md, Abschnitt
„Statik“), Materialdaten `mechanik` und `reibwerte.json` (KATALOG.md, Abschnitt „Mechanik“), App: Abschnitt „Statik“ im
Inspektor, Farbverlauf und Verformung im Viewer (`KevCADCore/Statik/`), Skill `skill/kev-cad/statik.md`.

Entscheidungen, die beim Bauen dazukamen:

| Nr. | Entscheidung | Begründung |
|---|---|---|
| T8 | S0 und S1 laufen beide nach jedem Lauf als letzter Prüfer (Stabwerk unter 100 ms bei üblichen Gestellen, PyNite wird beim Start des Rechenprozesses vorgeladen); Szenarien auf Anfrage rechnet der Rechenprozess mit dem Modell des letzten Laufs (`statik/dienst.py`) | Kevin sieht die Ampel nach jedem Lauf; Fragen „hält das, wenn …“ ohne neuen Lauf in unter einer Sekunde |
| T9 | Ampel über die Ausnutzung a = Ziel / Sicherheit: bis 1 grün, bis 2 gelb, darüber rot; Kippen und Rutschen über die Reserve (rot unter 1, gelb unter 1,5); Durchbiegung je Feld (L/200) bzw. Kragarm (2 L/200) gegen die Sehne bzw. die starre Fortsetzung, damit starre Bewegungen nicht zählen | Eine Rechenvorschrift für alle Urteile, Farbverlauf direkt aus derselben Zahl |
| T10 | Rote und gelbe Urteile sind Befunde `statik_*` als Warnung bzw. Hinweis; sie sperren den Export nicht | Vereinfachte Modelle (T7) sollen beraten, nicht blockieren |
| T11 | Verbinder (Druckteile, Platten, Zukaufteile) sind im Stabwerk starr, Gelenke sitzen in kurzen Gelenkgliedern quer zum Stab; Anschlüsse an Teile, die auf dem Boden stehen, sind feste Lager; Steck und Spiel gelten als fest | Robust ohne Volumen-FEM; die Verbinder selbst prüft der Kragträger-Nachweis, sobald eine Last auf ihnen liegt |
| T12 | Leichtere oder stärkere Lagerteile nur aus dem Inventar und nur desselben Werkstoffs; geschätzt über Widerstandsmoment, Fläche und Steifigkeit, die aussichtsreichsten mit dem ganzen Stabwerk nachgerechnet | Inventar-Regel; Fügen und Optik bleiben gleich; schnell |
| T13 | Kugeln und Walzen, die frei rollen, nehmen nicht an Kippen und Rutschen teil (das zeigt S2) | Sonst hieße es „Ball kippt“ |

Werkstoffdaten (T6, Strang „Bestand Stufe 2“, 22.10.2026): Mechanik für Multiplex Birke, MDF, Spanplatte P2, Messing,
Kupfer und die Druckmaterialien ABS, ASA, TPU 95A, PC, PA (nass), PA-CF, PLA-CF; Reibwert Stahl auf Beton 0,2 (statt
der Annahme 0,3); Auszugkraft von Gewindeeinsätzen (`einsatz_auszug`, M3 und M6 in PLA und PETG) als Nachweis in S0
(Schraubenlast im Druckteil, Ziel 4, `statik/s0.einsatz_nachweis`, Urteil in `bewertung`). Werte, Quellen und Lücken
in KATALOG.md. Offen: M4 und M5 (keine belegten Auszugkräfte), Siebdruckplatte, Querkontraktion der Buntmetalle,
feuchte Werte für PA-CF, Einfluss von Wänden und Füllung auf den Einsatz.

Naht für S2 und S3: `statik.NAHT` nennt die Stufen; beide setzen auf `modell.StatikModell` (Teile mit Masse und
Schwerpunkt, Starrkörper, Anschlüsse mit Gelenkart und Achse, Lager) und `szenario.Szenario` (Beschleunigungsfeld,
Lasten) auf und liefern Urteile im Format von `bewertung.urteil`, die `rechnen.rechne_alles` wie S0/S1 in Ampel,
Befunde und `STATICS` übernimmt. Offen für S2: Ablauf (Bremsen aus 1 m/s, springt der Ball aus dem Schieber) als
Animation, Kontaktkräfte, CoACD-Kollisionsformen. Offen für S3: Volumen-FEM für Druckteile und Verbinder (statt
Kragträger und starrer Verbinder), von Mises als Farbverlauf auf dem Netz.

## Stand Stufe 2 (T-C; Zweig `statik2`, 22.10.2026)

Umgesetzt in `kernel/src/kevcad_kernel/statik/dynamik/` (Übersicht im Docstring von `__init__.py`), API
`st.szenario(…, geschwindigkeit=, bremsen=, dauer=, animation=, antrieb=, angriff=, fahrtrichtung=)` (additiv), MCP
`dynamik`, `dynamik_grenze`, `szenario_rechnen(…, dynamik=True)`, STATICS mit Feld `ablauf` je Szenario (PROTOCOL.md,
„Ablauf (Stufe 2)“), Animation „Ablauf: <Name>“ über das vorhandene ANIM_DEF, App: Ablauf im Statik-Abschnitt, „Ablauf
zeigen“, Kontaktkräfte als Pfeile. MuJoCo 3.16 (Apache-2.0) und CoACD 1.0 (MIT) per `uv add`.

| Nr. | Entscheidung | Begründung |
|---|---|---|
| T14 | Der Rechenprozess baut nur die Szene (Datei, unter einer Sekunde); MuJoCo und CoACD laufen in einem eigenen Prozess (`python -m kevcad_kernel.statik.dynamik.prozess`), immer nur einer zugleich, Varianten mit `mujoco.rollout` auf höchstens 4 Fäden | model.py bleibt ungestört, ein abstürzender Ablauf reißt nichts mit, der Mac bleibt bedienbar |
| T15 | Starrkörper: fest sind `verbinde` mit Schraube, Klemmung, Steck, Formschluss, Kleben samt `mit`; Gelenke mit `bereich` gelten als festgestellt (Klemmen, Kopf); frei laufen Gelenke ohne `bereich` und Räder (Achse aus `anim.rolle(…, achse=…)`, sonst Rad/Rolle im Namen und Zylinderachse); `aufliegen` verbindet nicht, außer andere Teile klemmen das Teil ein; Teile ohne jede Bedingung hängen wie in Stufe 1 an dem, was sie berühren | Fest verschraubte Baugruppen werden ein Körper (Kugelschieber: 132 Teile → 8 Körper), Einstellgelenke sind im Betrieb geklemmt |
| T16 | Kollisionsformen je Teil: Kugel (Grundform), Drehteil (Stapel aus Kegelstümpfen, die Einschnürung bleibt), Zylinder für Laufflächen von Rädern, sonst konvexe Hülle; CoACD nur, wo eine Mulde zählt (Punkte eines Nachbarkörpers in der Hülle, ohne das Teil zu berühren), zwischengespeichert je Formschlüssel unter `~/Library/Caches/de.upvis.kevcad/dynamik/coacd` | Gegen den Boden ist die Hülle exakt; die Hülle der Laufrolle wäre an der Einschnürung 5,8 mm zu dick, der Ball läge falsch |
| T17 | Antrieb: der schwerste Körper auf Rädern (oder `antrieb=`) folgt einer Sollbahn (fahren mit `geschwindigkeit`, nach 0,3 s bremsen; `"abrupt"` = Stillstand in 0,1 s, `"anprall"` = 0,02 s; oder die Bahn einer Animation), geführt von einem Regler mit Vorsteuerung am Boden unter dem Schwerpunkt, quer, senkrecht und in der Drehung frei; Füße des geschobenen Körpers gleiten reibungsfrei | Ungünstigster Fall fürs Kippen nach vorn (wie blockierte Räder), deckt sich mit der Handrechnung a = g·b/h; ohne Vorsteuerung schwingt der Regler über (6 % zu früh), ohne reibungsfreie Füße hüpfen gleitende Füße auf den weichen Kontakten |
| T18 | Urteile `dyn_kippen` (Kippreserve = Verzögerung, ab der er hinten über 2 mm abhebt, durch die Verzögerung im Szenario), `dyn_ladung` (Versatz über die halbe Größe oder am Ende über ein Fünftel: springt heraus), `dyn_rutschen` (μ·g mit blockierten Rädern); Grenzen über eine k-fache Teilung mit Rollouts (8 Werte, dann je Kriterium 4, drei Runden); Plausibilität: Simulation ohne Ladung bei anhaltender Verzögerung gegen g·b/h | Gleiche Ampel wie Stufe 1 (Reserve 1 und 1,5), Zahlen statt Ja/Nein, Kontrolle gegen eine Handrechnung bei jedem Ablauf |
| T19 | Ergebnis als gewöhnliche Animation (ANIM_DEF „Ablauf: <Name>“, Bilder genau auf k/fps); im Szenario weichen Kippen und Rutschen aus S0 den Urteilen des Ablaufs, die Festigkeit rechnen S0/S1 mit der größten Verzögerung als ruhender Last | Kein neues Protokoll zum Abspielen, Video und Kamera wie bei jeder Animation |
| T20 | Abläufe aus model.py rechnet die Laufzeit nach jedem Lauf im Hintergrund (STATICS erst „läuft“, dann „done“); Ergebnisse eines überholten Laufs verfallen | Kevin sieht den Ablauf ohne Nachfrage, der Lauf wartet nie darauf |

Nachweis am Kugelschieber (Kopie von „Kugelschieber Variante B“, 22.10.2026): Bremsen aus 1 m/s, abrupt (10 m/s²):
der Wagen hebt hinten 16 bis 17 mm ab (1,7°) und fällt zurück, die Fangrolle setzt auf dem Boden auf; er hebt schon ab
2,5 m/s² ab (Kippreserve 0,25), weil der Ball beim Bremsen auf die tief liegende Fangrolle drückt, bei abruptem Bremsen
schon ab 0,29 m/s. Der Ball bleibt knapp im Schieber (steigt 30 mm an der Fangrolle hoch) und springt ab 1,12 m/s
heraus. Handrechnung ohne Ball a = g·b/h = 9,81 · 169 / 118 = 14,1 m/s², Simulation ohne Ball 13,9 m/s² (−1,3 %).
Rutschgrenze mit blockierten Rädern 5,9 m/s² (EPDM auf Beton, μ = 0,6).

Offen für S3 und später:

- S3 wie geplant (Gmsh, scikit-fem), dazu die Kontaktkräfte aus S2 als Lastfall für S1/S3 (Ball an der Fangrolle
  rund 100 N auf Schlitten und Querstange).
- Rückprall je Materialpaarung (Stöße sind vollplastisch), Rollwiderstand, Lagerreibung der Laufrollen, federnde Stäbe
  (die Seitenstangen federn in Wirklichkeit).
- Befunde `statik_dyn_*` stehen in STATICS und im Ergebnis von `dynamik`, noch nicht in der Prüfung (CHECK) des Laufs.
- Massen aus dem Katalog statt angenommen (Bowlingball 5,3 kg bei 1 g/cm³ statt 6 bis 7,3 kg, Kamera); die
  Grenzgeschwindigkeit des Balls hängt stark an Masse und Reibwert Ball/Boden (angenommen 0,3).
- Kontaktpfeile auch im Video; Schieben am Griff als eigene Bremsart neben `angriff=` (Höhe in mm).

## Stand Stufe 3 (T-D; Zweig `statik3`, 22.10.2026)

Umgesetzt in `kernel/src/kevcad_kernel/statik/festkoerper/` (Übersicht im Docstring von `__init__.py`), MCP
`festigkeit` (mit `abbrechen=True` zum Beenden), STATICS mit Feld `festkoerper` je Szenario und Urteil `festkoerper`,
neue Nachrichten `STATICS_FIELD` (Kernel → App, Oberflächennetz mit Ausnutzung, Spannung und Verschiebung als
Nutzlast) und `STATICS_CANCEL` (App → Kernel), PROTOCOL.md „Festkörper (Stufe 3)“. App: Festkörper im Statik-Abschnitt
(Fortschritt mit Abbruch, je Teil Ampel, Sicherheit, Kriterium, Drucklagen, Netz, Farbskala), Farbverlauf in Bändern
auf dem Netz des Teils (das Teil selbst ist dann ausgeblendet) und die überhöhte Verformung als Geist
(`KevCADCore/Statik/StatikFeld.swift`). Gmsh 4.15.2 (GPL, nur im eigenen Prozess), scikit-fem 12.0.2 (BSD) und pyamg
5.3.0 (MIT) per `uv add`. Skill `skill/kev-cad/statik.md`, Abschnitt „Festkörper“.

| Nr. | Entscheidung | Begründung |
|---|---|---|
| T21 | Die FEM läuft nur im eigenen Prozess (`python -m kevcad_kernel.statik.festkoerper.prozess`): Der Rechenprozess schreibt nur den Auftrag (Teil als BREP in Weltlage, Netze der Nachbarn auf den Hüllquader zugeschnitten, Lastfälle; Millisekunden), die Laufzeit startet den Prozess, liest den Fortschritt (JSON-Zeilen) und beendet ihn bei einem neuen Lauf oder auf `STATICS_CANCEL`; immer nur einer zugleich, höchstens 4 Fäden | Gmsh ist GPL; model.py und die Prüfung bleiben ungestört, S0 und S1 werden nicht langsamer (die Prüfung schreibt nur Last und Lager ins Bauteil-Ergebnis mit) |
| T22 | Tetraeder zweiter Ordnung (P2) auf geraden Kanten: Gmsh vernetzt erster Ordnung, die Kantenmitten kommen aus scikit-fem. Netzgröße aus der mittleren Wandstärke 2 V / A (ein Element über die Dicke genügt P2), höchstens 8 000 Tetraeder (fein 40 000), Löcher über die Krümmung verfeinert (18 bzw. 32 Elemente je Kreis) | Kragbalken mit einem Element über die Höhe: Durchbiegung −1,2 %, Wurzelspannung −0,6 %; Tempo vor feinstem Netz, `fein=True` für Kerben |
| T23 | Steifigkeit über einen eigenen vektorisierten Kern (4-Punkt-Regel, beliebige 6×6-Steifigkeit), geprüft gegen `skfem.asm(linear_elasticity)` (gleiche Matrix bis 1e-9); scikit-fem liefert Topologie, Freiheitsgrade, Flächenlasten und die Starrkörperbewegungen | 3- bis 6-mal schneller als `asm`; quer zur Schicht weichere Druckteile ohne eigene Form |
| T24 | Löser: SuperLU (symmetrische Ordnung) bis 25 000 Freiheitsgrade und für dünne Teile (Größe / Wandstärke über 25) bis 150 000; sonst pyamg (Smoothed Aggregation in 3×3-Blöcken, sechs Starrkörperbewegungen als Nahkern, CG); kommt AMG nach 150 Iterationen nicht unter 1e-6, rechnet SuperLU nach | Mit Tetraedern konvergiert AMG bei dünnen Platten nicht (Platte 400 × 100 × 5: 500 Iterationen ohne Ziel), SuperLU zerlegt sie in 3 s und rechnet alle Lastfälle mit einer Zerlegung |
| T25 | Lager sind die Randdreiecke, deren Schwerpunkt höchstens 0,3 mm (Spiel: 0,75 mm) vom Netz eines tragenden Nachbarn liegt (dieselben Nachbarn wie beim Kragträger), fest eingespannt. Gewertet wird ab dem ersten Knoten neben der Lagerfläche; die Spitze auf ihr steht als `sicherheit_lagerrand` daneben | Auf der Lagerfläche ist die starre Einspannung eine Idealisierung (Querdehnung behindert, Kante singulär); beim Wandhalter läge die Sicherheit dort 18 % niedriger, ohne dass ein echtes Teil so bricht |
| T26 | Lasten: Kraft an einem Punkt wie ein RBE3 auf der B-Rep-Fläche um den Punkt verteilt (Radius 10 % der Teilgröße, 3 bis 25 mm, Summe und Moment genau), ohne Punkt gleichmäßig über das Volumen (wie „am Schwerpunkt“), Lagerkräfte und -momente der Stäbe aus S1 über die Kontaktfläche zum Stab, bei Verbindern zwischen Stäben (im Stabwerk starr) Kraft und Moment jedes Stabs am Anschluss (Endkräfte des starren Glieds, neu in S1: `verbinder`), gehalten vom Stab mit der größten Kraft; immer das Eigengewicht im Beschleunigungsfeld des Szenarios; Kontaktkräfte eines Ablaufs (S2) nur auf Wunsch (`festigkeit(…, ablauf=True)`), dann allein: alle Kontakte auf das Teil im Bild mit der größten Summe, über die Lage des Teils in diesem Bild zurück in die Ruhelage | Gleiche Lasten wie S0/S1, Gleichgewicht je Fall geprüft (`gleichgewicht_n`); die Kontaktkraft ist die Last des Ablaufs, die ruhende Ersatzlast käme doppelt dazu |
| T27 | Druckteile: Steifigkeit quer zur Schicht aus `e_modul_z` (angenommen ν_zp = ν, G_zp = E_z / (2 (1 + ν))), Festigkeit max(von Mises / f, Schichtfuge √((σ_n⁺ / q f)² + 3 (τ / q f)²)) mit q = `quer_zur_schicht`, Ziel wie S0 (statisch 4); unbekannte Drucklage überall mit q. Die Sicherheit in den anderen Drucklagen (`ausrichtung` −z, −y, −x) kommt aus demselben Spannungsfeld | Für einachsigen Zug quer zur Schicht dasselbe wie S0; der Hinweis „drehen oder verstärken“ bekommt einen FEM-Beleg ohne zweite Rechnung (der Einfluss der Steifigkeit auf die Verteilung ist bei E_z / E = 0,8 klein) |
| T28 | Ergebnis: Urteil `festkoerper` ersetzt im Szenario den Kragträger (`bauteil`) desselben Teils, Ampel über die Ausnutzung wie T9; das Feld je Teil als STATICS_FIELD, die App zeichnet Bänder der Ausnutzung (0,1 breit, Farben wie an den Stäben) und blendet das Teil aus, die Verformung erscheint als 8 % der Teilgröße | Eine Farbsprache für Stäbe und Volumen; Bänder statt Farbe je Dreieck, weil der Viewport nur eine Farbe je Körper schattiert |
| T29 | Im Hintergrund nach jedem Lauf nur Szenarien mit Last und höchstens 8 Teile (die nach S0 am stärksten ausgelasteten zuerst), dazu nach `szenario_rechnen` und `dynamik` das neue Szenario; Zwischenspeicher je Fall (Schlüssel aus Teilstand, Nachbarn, Lasten, Werkstoff, Netzeinstellung) und je Netz unter `~/Library/Caches/<Bundle-ID>/festkoerper` | Unveränderte Teile kosten nach dem nächsten Lauf nur den Prozessstart (0,2 bis 0,8 s); die Testvarianten haben eigene Speicher |

Nachweise (Tests in `kernel/tests/test_festkoerper.py`, Werkstoffwerte aus dem Katalog):

| Probe | Handrechnung | FEM | Abweichung | Netz, Zeit |
|---|---|---|---|---|
| Kragbalken 100 × 10 × 10 mm PLA, 100 N am Ende, Durchbiegung F L³ / (3 E I) | 14,925 mm | 14,912 mm | −0,1 % | 3 776 Tetraeder, 20 616 Freiheitsgrade, 2,5 s |
| derselbe, Randfaser bei x = 25 mm, M / W | 45,00 N/mm² | 45,06 N/mm² | +0,1 % | |
| derselbe, Einspannung, F L / W | 60,00 N/mm² | 60,29 N/mm² | +0,5 % | |
| Lochplatte 400 × 100 × 5 mm, Loch Ø 20, 1000 N Zug, K_t σ_netto mit K_t = 2 + (1 − d/W)³ (Heywood) | 6,280 N/mm² | 6,172 N/mm² | −1,7 % | fein, 23 114 Tetraeder, 138 816 Freiheitsgrade, SuperLU, 17 s |
| Wandhalter PETG 80 × 20 × 8 mm stehend gedruckt (Schichten quer zur Last), 20 N bei 78 mm: Sicherheit q f / (M / W) | 1,86 | 1,87 (Kragträger S0: 1,98) | +0,5 % | 532 Tetraeder, 1,4 s, aus dem Zwischenspeicher 0,2 s |

Der Wandhalter ist rot (Ziel 4); flach gedruckt (`ausrichtung="-z"`) hätte er laut FEM Sicherheit 4,85, also grün:
das ist der FEM-Beleg für „drehen“. Die Durchbiegung (2,4 mm) passt zur Handrechnung mit E_z (stehend gedruckt).

Praxisfall Kugelschieber (Kopie von „Kugelschieber Variante B“ im Scratchpad, eigener Katalog und Speicher,
22.10.2026, ohne App über die Laufzeit):

- Nach dem Lauf (33 bis 52 s wie bisher, die FEM hält ihn nicht auf) rechnet der Hintergrund das Szenario „Bremsen“
  (Standard, 3 m/s²) für 8 Teile: die vier Stangenhalter mit den Lagerkräften der Seitenstangen und die vier Schlitten
  als Verbinder zwischen Querstange und Seitenstange; 18 s (ohne Zwischenspeicher 34 s), alle grün.
- Ablauf „Bremsen aus 1 m/s“ (abrupt), dann `festigkeit(szenario="Bremsen aus 1 m/s", ablauf=True)`: Im Bild mit der
  größten Last drückt der Ball mit 83 N auf die Fangrolle (Druck), die zugleich mit 122 N auf dem Boden aufsetzt (der
  Wagen hebt hinten ab). FEM: Sicherheit 7,3 gegen Ziel 6 (dynamisch, Druckteil), grün; 5 907 Tetraeder, 1,9 s. Die
  Schieberolle hat 164.
- Szenario „Ball drückt 100 N“ (100 N in Fahrtrichtung auf die Querstange vorn, `szenario_rechnen`, 0,2 s), dann
  `festigkeit(szenario=…)` für 8 Teile in 16 s: **Fängerschlitten rechts (Druck) rot**, Sicherheit 1,7 gegen Ziel 4,
  Schichtfuge maßgebend bei (704; −412; 32), Lösung „verstärken um etwa 54 %“; drehen hilft hier nicht (−x 1,47, −y
  1,21). Im Stabwerk geht die Längskraft der Querstange ganz über den rechten Schlitten (links 0 N); bisher galt er als
  starr und wurde gar nicht nachgewiesen. Stangenhalter hinten links gelb mit 2,88 (Kragträger S0: 6,47), hinten
  rechts 3,34 (S0: 4,99): Die FEM findet die Spitze an der Bohrung, die der Kragträger nicht sieht.
- Rechenzeiten: Stangenhalter 4 400 Tetraeder, 26 000 Freiheitsgrade, SuperLU, 1,4 bis 2,0 s; Schlitten 7 000
  Tetraeder, 39 000 Freiheitsgrade, pyamg mit 90 bis 120 Iterationen, 3,6 bis 4,6 s; aus dem Zwischenspeicher je Fall
  Millisekunden, der Prozessstart rund 0,2 bis 0,8 s.

Testvariante „Kev CAD Test s3“ (Kopie des Wandhalters im Scratchpad, nur über MCP der Testvariante): Nach dem Lauf
zeigt der Statik-Abschnitt „Festkörper läuft“ mit Fortschritt (0 %, 45 %, fertig nach gut 1 s), danach je Teil „FEM
1,86 / 4“, Schichtfuge maßgebend, Drucklagen, Netz und die Farbskala; `festigkeit` kommt aus dem Zwischenspeicher
(0,25 s). Das Bild (offscreen) zeigt den Halter in Bändern rot an der Wand bis grün an der Spitze, auf der Seitenfläche
grün an der neutralen Faser, das Teil selbst ausgeblendet, darunter den verformten Geist. Der Geist sitzt je Dreieck
0,4 % der Teilgröße nach innen versetzt, sonst flimmerte er am Lager mit dem Farbverlauf.

Offen für später:

- Drehbar gelagerte Rollen (Fangrolle auf der Querstange) und Klemmungen (Schlitten auf der Seitenstange) rechnet die
  FEM wie fest eingespannte Kontaktflächen; Kontaktkräfte aus dem Ablauf nur für Körper aus einem Teil; Verbinder aus
  mehreren Teilen mit Hinweis (die Kraft über die übrigen Teile landet im Lager).
- Kontakt mit Abheben und Reibung statt fester Einspannung, Schrauben und Gewindeeinsätze als eigene Lager
  (Vorspannung), Plastizität und Beulen (CalculiX, eigener Prozess).
- Füllung und Wände der Druckteile (heute volle Füllung); orthotrope Festigkeit statt eines Faktors.
- Gekrümmte Elemente (P2 mit gebogenen Kanten) für sehr kleine Löcher; adaptive Verfeinerung an der Spitze statt
  `fein`.
- Befunde `statik_festkoerper` stehen in STATICS und im Ergebnis von `festigkeit`, noch nicht in der Prüfung (CHECK).
- Falls SuperLU bei großen, gedrungenen Teilen zu langsam wird: Accelerate-Cholesky über ein Swift-Hilfsprogramm.
