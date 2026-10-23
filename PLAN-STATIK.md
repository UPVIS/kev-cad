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
| S4 (gebaut, siehe „Stand Stufe 4“) | **CalculiX** 2.23 (eigener Prozess) | GPL | Kontakt, Plastizität, Traglast, Beulen; von conda-forge über micromamba auf der externen Platte UPVIS ULTRA | Sekunden bis Minuten |

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

## Nachbesserung: Lastaufteilung und innere Kräfte (Zweig `statik-nach`, 22.10.2026)

Zwei Befunde aus der Arbeit am Kugelschieber (Sitzung KevCup, Build 391): Im Szenario „Ball drückt 100 N“ bekam der
rechte Fängerschlitten die ganzen 100 N, der linke fast nichts (FEM 1,7 gegen Ziel 4); und die als äußere `st.last`
gerechnete Kraft des Balls ließ den ganzen Wagen „rutschen“ (nötig μ = 0,9).

Ursache des ersten Befunds war nicht die Regel „gehalten vom Stab mit der größten Kraft“ im Festkörper, sondern das
Stabwerk: Der linke Schlitten hängt über `schiebegelenk(…, bereich=(…))` an der Seitenstange (der rechte über
`verbinde(…, "klemmung")`), und S1 rechnete jedes Schiebegelenk als freie Hülse. Längs der Führung (in Fahrtrichtung,
genau die Richtung der Ballkraft) hielt der linke Schlitten also nichts, die ganze Kraft lief über den rechten. Gleich
ging es der Seitenstange im vorderen Stangenhalter (Schiebegelenk mit Bereich, in Wirklichkeit mit Sterngriff
geklemmt).

| Nr. | Entscheidung | Begründung |
|---|---|---|
| T30 | Gelenke mit `bereich` sind auch im Stabwerk (S1) festgestellt, also feste Anschlüsse (wie T15 in S2); frei bleiben nur Gelenke ohne `bereich` (Hülse, Laufrolle). Quelle des Anschlusses: „Gelenk (schiebe) mit Bereich: festgestellt“ | Einstellgelenke (Schlitten, Stange im Halter, Kopf) sind im Betrieb geklemmt; frei gerechnet verteilt sich die Last falsch und der Leiterrahmen trägt nicht mit. Eine Stufe, eine Regel |
| T31 | Verbinder zwischen Stäben (im Stabwerk starr) bekommen ihre Kräfte je Anschluss aus S1 (Endkräfte der starren Glieder, statisch unbestimmt nach Steifigkeit verteilt) und werden damit als Kragträger nachgewiesen (`rechnen._verbinderteile`, Bauteil mit `aus_verbinder`): eingespannt an der Berührung mit dem Stab mit der größten Kraft, belastet von den übrigen Stäben (Resultierende mit Moment). Der Festkörper nimmt dieselben Kräfte (wie T26), der Kragträger ist dort nur der Vergleich | Bisher galt ein Verbinder als starr und wurde in S0/S1 gar nicht nachgewiesen; jetzt dieselben Lasten in S0, S1 und S3 |
| T32 | Kraftpaare für innere Kräfte: `st.last(teil, kraft, punkt, gegen=…)` oder `st.kraftpaar(a, b, kraft, punkt)` (auch in `szenario_rechnen`: `"gegen"`). Kraft auf `teil`, Gegenkraft −kraft am selben Punkt auf `gegen`. Kippen, Rutschen und Abheben des Ganzen lassen beide weg; Stabwerk, Kragträger, lose Teile, Schrauben und Festkörper bekommen jede Seite auf ihre Teile (eine Seite auf einem geerdeten Teil, etwa dem Ball auf dem Boden, trägt der Boden; ein Gegenstück ohne Festigkeitswerte bekommt kein graues Urteil). Im Ergebnis je Szenario `lasten` mit Angriffspunkt, `gegen` und `paar` (STATICS additiv); die App zeichnet Lasten als blaue Pfeile zum Angriffspunkt, ein Kraftpaar als zwei gegeneinander gerichtete violette Pfeile, und listet sie im Statik-Abschnitt | Der Ball drückt gegen die Fangrolle und die Fangrolle gegen den Ball; als äußere Last gerechnet rutscht oder kippt das Ganze scheinbar |

Nachweise (Tests in `kernel/tests/test_statik_nach.py`):

| Probe | Handrechnung | Stabwerk |
|---|---|---|
| Stange (Stahlrohr 21,3 × 2) in zwei gleichen Haltern an der Wand, 100 N in der Mitte | je 50 N | 50,00 / 50,00 N |
| dieselbe, 150 mm neben der Mitte, gesteckt (eingespannt): R = P a² (a + 3b) / L³ mit a = 450, b = 150, L = 600 mm | 84,38 / 15,62 N | 84,38 / 15,63 N |
| dieselbe, aufgelegt (gelenkig), Hebelgesetz R = P a / L | 75,00 / 25,00 N | 75,00 / 25,00 N |
| Querstange in zwei Schlitten (Verbinder) auf zwei auskragenden Seitenstangen, einer über Schiebegelenk mit Bereich, einer geklemmt, 100 N in der Mitte | je 50 N | 50,0 / 50,0 N (vorher 100 / 0) |
| dieselbe, 75 mm neben der Mitte: Träger auf zwei Stützen mit Drehfedern k = E I / L_s der Seitenstangen | 75,90 / 24,10 N | 75,49 / 24,51 N |

Gegenprobe: dasselbe Schiebegelenk ohne Bereich läuft frei, dann trägt der andere Schlitten 100 N.

Kugelschieber (Kopie von „Kugelschieber Variante B“ im Scratchpad, eigener Katalog und FEM-Speicher):

| Szenario „Ball drückt 100 N …“ | vorher | Gelenk festgestellt (T30, T31) | dazu als Kraftpaar mit dem Ball (T32) |
|---|---|---|---|
| Fänger: Kraft der Querstange auf den Schlitten rechts / links | 100 / 0 N (Moment 6 640 Nmm rechts) | 50 / 50 N (Moment 369 Nmm) | gleich |
| Fänger: Festkörper Fängerschlitten rechts / links (Ziel 4) | 1,69 rot / 56,7 | 8,31 / 8,49 grün | 8,41 / 8,73 grün |
| Fänger: Kragträger der Fängerschlitten (neu) | – | 34,5 / 34,5 | gleich |
| Schieber: Festkörper Schieberschlitten rechts / links | 4,37 / 526 | 23,3 / 23,9 | 23,4 / 23,8 |
| Durchbiegung Seitenstangen (zulässig 4,8 mm) | Fänger 14,7 / 14,4 mm, Schieber 11,5 / 12,8 mm, rot | Fänger 1,81 mm, Schieber 3,07 mm, grün | gleich |
| Sicherheit Seitenstange rechts | Fänger 1,42, Schieber 1,88 (gelb) | 7,04 bzw. 6,39 | gleich |
| Rutschen des Ganzen | rot, nötig μ = 0,90 (Rad auf Beton 0,6) | rot, 0,90 | kein Urteil (nötig μ = 0) |
| Kippreserve | 4,19 bzw. 10,2 | gleich | 9,0 (nur Eigengewicht) |
| Ampel des Szenarios | rot | rot (nur noch Rutschen) | grün |

Handrechnung der Seitenstange als Kragarm (Alurohr 12 × 1, E = 70 000 N/mm², I = 527 mm⁴, eingespannt im vorderen
Stangenhalter, 482 mm bis zum Ende; Schieberschlitten bei 273 mm, Fängerschlitten bei 458 mm):

- Eigengewicht: Rohr q L⁴ / (8 E I) = 0,17 mm, Schieber-Einheit 1,9 N bei 273 mm 0,75 mm, Fänger-Einheit 1,7 N bei
  458 mm 1,59 mm, zusammen 2,51 mm (Stabwerk 2,50 mm).
- Ball 100 N: je Seitenstange 50 N längs der Achse (Dehnung 0,01 mm) und, weil die Querstange 4,2 mm unter der
  Stangenachse liegt, ein Moment M = 50 N · 4,2 mm = 210 Nmm; Spitze M a (L − a/2) / (E I): Schieber 0,54 mm,
  Fänger 0,66 mm (Stabwerk 0,56 bzw. 0,69 mm, Vorzeichen nach Richtung). Zusammen 3,05 bzw. 1,85 mm, gerechnet 3,07
  bzw. 1,81 mm.
- Das Moment um die Hochachse (die Querstange gibt ihre Endmomente an die Schlitten) trägt der Leiterrahmen aus beiden
  Seitenstangen und beiden Querstangen als Normalkraft der Querstangen ab (Querverschiebung unter 0,06 mm).
- Die 11 bis 15 mm von vorher waren eine Folge der frei gerechneten Gelenke: die ganze Kraft über die rechte Stange mit
  rund 9 200 Nmm um die Hochachse (100 N mal 92 mm Hebel), dazu die im vorderen Halter drehbar gelagerte Stange
  (Eigengewicht allein: Spitze vorher 4,7 mm tief, davon 2,2 mm aus der Drehung im Halter, jetzt 2,5 mm; gewertet wird
  in beiden Fällen die Biegung gegen die starre Fortsetzung, 2,5 mm). Real sind beide Schlitten und beide Halter
  geklemmt.

Offen:

- Ein Gelenk mit Bereich, das im Betrieb wirklich frei läuft (Schublade, Tür ohne Feststeller), rechnet die Statik
  jetzt fest; ein Schalter dafür (etwa `frei=True` am Gelenk) fehlt noch.
- Der Kragträger nimmt bei einem Schnitt durch eine Bohrung nur das Stück auf einer Seite (grob): bei den beiden
  gleichen Schlitten im Test 10,2 gegen 11,7; am Kugelschieber liegt der Kragträger der Fängerschlitten (34,5) weit
  über der FEM (8,3), die die Spitze in der Schichtfuge findet. Maßgebend ist die FEM.
- Kraftpaare gelten in S0, S1 und S3; ein Ablauf (S2) rechnet seine Kontaktkräfte selbst und nimmt `st.last` nicht.
- Testvariante „Kev CAD Test sn“: an einer Probe ohne Animation (Wagen mit Fänger, Ball davor) zeigt der Viewer das
  Kraftpaar als zwei violette Pfeile, die sich an der Fängerfläche treffen. Am Kugelschieber ist die Animation „Fahrt“
  gesetzt; solange eine Animation gesetzt ist, blendet die Szene alle Statik-Körper aus (Farbverlauf, Geist, jetzt auch
  die Pfeile; bestehendes Verhalten in `SceneStore`). Ohne `punkt` liegt der Angriffspunkt in der Mitte der Querstange,
  also in der Fangrolle; mit `punkt` an der Berührstelle Ball–Rolle steht das Paar sichtbar zwischen beiden.
- Der Kugelschieber selbst rechnet die Ballkraft noch als äußere Last: in seinem model.py `gegen="Bowlingball"`
  ergänzen (nicht in diesem Zweig, Kevins Projekt bleibt unberührt).

## Restpunkte: freie Gelenke, Befunde in der Prüfung, Drehfedern (Zweig `rest-statik-render`, 23.10.2026)

Kevin am 22.10.2026: „Mach weiter, so dass wir mit dem Projekt ganz fertig werden.“ Dazu der Befund von KevCup am
Kugelschieber (Build 427, V86): Seit T30 nehmen die vorderen Stangenhalter (PLA, Klemmung mit Sterngriff um Alurohr
12 × 1) das ganze Kragmoment der rund 460 mm auskragenden Seitenstange; `festigkeit` meldet 0,30 bis 0,48 (75 N/mm²
von Mises), vorher 8 bis 26.

| Nr. | Entscheidung | Begründung |
|---|---|---|
| T33 | **Gelenk mit `bereich`, das frei läuft:** `frei=True` am Gelenk (`drehgelenk`, `schiebegelenk`, `zylindergelenk`, Prüfung `frei` muss ein Wahrheitswert sein). Standard bleibt festgestellt (T30). Mit `frei=True` rechnet das Stabwerk das Gelenk als Gelenk (Hülse, Drehgelenk; Quelle „Gelenk (schiebe) frei“), der Ablauf lässt es laufen und hält es an den Enden von `bereich` an (MuJoCo-Grenzen ab der Lage in model.py, Anschlag überkritisch gedämpft `solreflimit 0,004 2`, Lagerreibung 3 % des Gewichts, bei Drehgelenken am Radius 10 mm). Zwischen zwei Nicht-Stäben (Schublade im Korpus) bleibt es in S0/S1 ein Körper (wie am Anschlag), mit Hinweis | Kevins Gelenke mit Bereich sind meist geklemmt; Schublade und Tür ohne Feststeller laufen wirklich. Ohne Dämpfung federte der Anschlag zurück (Schublade bei 87 mm, dann zurück auf 8 mm) und ohne Reibung driftete sie schon beim Fahren |
| T34 | **Befunde aus Ablauf (S2) und Festkörper (S3) in der Prüfung:** Rechnen sie nach dem Lauf noch, geht das CHECK als `teilweise` mit `statik_im_hintergrund` hinaus (das Muster des Bewegungsraums); sind sie fertig oder abgebrochen, setzt die Laufzeit das CHECK desselben Laufs neu zusammen (`statik/laufzeit.py`, `_statik_in_check`): Befunde `statik_*` neu aus dem Ergebnis der Laufzeit, nur aus den Szenarien des Laufs, `statik_dyn_*` und `statik_festkoerper` dazu (rot Warnung, gelb Hinweis, nie Exportverbot, T10), neu nummeriert, und schickt es mit `done` (bzw. weiter `teilweise`, solange der Bewegungsraum rechnet). Bloßer Fortschritt schickt kein CHECK. `run` wartet nicht, `pruefen(warten=True)` schon, die Export-Sperre nicht | Eine Prüfung, in der alle Befunde stehen; der Lauf bleibt so schnell wie vorher. Szenarien auf Anfrage (`szenario_rechnen`, `dynamik`) sind Fragen des Agenten, keine Befunde des Modells |
| T35 | **Drehfeder an festen Anschlüssen an Druckteile** (`statik/feder.py`): Klemmung, Steck, Spiel, festgestelltes Gelenk oder Schraube eines Stabs an ein Druckteil ist im Stabwerk nicht starr, sondern hat für die beiden Drehungen quer zum Stab je eine Feder (Verschiebungen und Drehung um die Stabachse starr). Nachgiebigkeit in Reihe: Bettung in der Bohrung k = E · L_b³ / 12 (Bettung E / d angenommen) und Biegung und Torsion des Teils bis zu seinem Lager an denselben Schnitten wie der Kragträger (Δs / (E I), Δs / (G I_t), I_t ≈ A⁴ / (40 I_p), quer zur Schicht `e_modul_z`); bei Verbindern zwischen Stäben je Anschluss der Anteil 1 / n. Im Stabwerk zwei kurze Glieder (2 mm) längs der Hauptachsen, starr bis auf die Torsion G J / L = k. Die Lagerkraft samt Moment durch die Feder geht wie bisher in Kragträger und Festkörper | Starr nahm ein weicher Halter das ganze Kragmoment, gelenkig keines; real teilt es sich nach Steifigkeit. Geometrie und E-Modul reichen im Rechenprozess (Millisekunden, keine FEM im Lauf, T21) |

Nachweise (Tests in `kernel/tests/test_statik_rest.py`, Handrechnung als Euler-Bernoulli-Balken mit Federn,
`test_statik_nach.balken`):

| Probe | Handrechnung | Stabwerk |
|---|---|---|
| Edelstahlrohr 12 × 1 in zwei Pfosten 300 mm auseinander, 400 mm Kragarm, 50 N an der Spitze; Pfosten aus Stahl (starr): Lager B nimmt P · L_k | R_A 0, R_B 50 N, M_B 20 000 Nmm | 0,00 / 50,00 N, 20 000 Nmm |
| dieselbe, aufgelegt (gelenkig): Durchlaufträger mit Kragarm | R_A −66,67, R_B 116,67 N, keine Momente | −66,67 / 116,67 N, 0 |
| dieselbe, Pfosten PLA 40 × 30 × 95 mm stehend gedruckt (federnd): k = 1 / (1 / (E L_b³ / 12) + 1 / (E_z I / H)) = 1,66 · 10⁶ Nmm/rad, Feder aus dem Modell innerhalb 3 % | R_A −37,33, R_B 87,33 N, M_A 2 621, M_B 11 421 Nmm | −37,36 / 87,35 N, 2 622 / 11 416 Nmm |
| Stange (Stahlrohr 21,3 × 2) in zwei PETG-Haltern, gesteckt, 150 mm neben der Mitte (T30-Probe): jetzt mit Feder, zwischen Hebelgesetz (75 / 25) und Einspannung (84,38 / 15,62) | 75,46 / 24,54 N | 75,47 / 24,54 N |
| Querstange in zwei PETG-Schlitten, 75 mm neben der Mitte: Federn der Seitenstangen und beider Bohrungen der Schlitten in Reihe | 75,23 / 24,77 N | 75,08 / 24,92 N |
| Kommode mit Schublade auf `schiebegelenk(…, bereich=(0, 80), frei=True)`, Bremsen aus 1 m/s abrupt | fährt bis an den Anschlag | größter Weg 81,3 mm, am Ende 79,1 mm; festgestellt 0 mm |

Kugelschieber (Kopie von „Kugelschieber Variante B“ im Scratchpad, eigener Katalog und FEM-Speicher), Szenario „Ball
drückt 100 N auf den Fänger“ (bzw. „… Schieber“):

| | starr (T30, wie KevCup) | mit Drehfeder (T35) |
|---|---|---|
| Feder Stangenhalter vorn (Bohrung 40 mm, Hebel 98 mm bis zum Rahmen, PLA, Biegung quer zur Schicht) | – | 1,13 · 10⁶ Nmm/rad um y (Drehung der Stange in der senkrechten Ebene) |
| Moment im Stangenhalter vorn links | 15 989 Nmm | 12 813 Nmm (Stangenhalter hinten jetzt 1 286 statt 19) |
| Kragträger Stangenhalter vorn links / rechts (Ziel 4) | 2,09 / 2,09 (Schieber 2,71) | 2,40 / 2,53 (Schieber 3,04 / 3,24) |
| Festkörper Stangenhalter vorn links / rechts (Ziel 4, Schichtfuge maßgebend) | 0,30 / 0,31, 75 N/mm² (Schieber 0,46 / 0,47) | 0,37 / 0,38, 62 N/mm² (Schieber 0,56 / 0,57) |
| Seitenstange (Sicherheit) | 0,867 | 0,859 |

Ehrlich dazu: Der Halter ist auch federnd viel steifer als das Rohr. Die Seitenstange (Alurohr 12 × 1, E I = 3,7 · 10⁷
Nmm²) spannt rund 500 mm bis zum hinteren Halter, ihre Drehsteifigkeit dort ist etwa 3 E I / L = 2,2 · 10⁵ Nmm/rad;
der vordere Halter (ein 116 mm hoher Pfosten unter dem Rahmen) hat aus Geometrie 1,13 · 10⁶ und behält damit rund
80 % des Moments. Eine einmalige Festkörper-Messung desselben Halters (Kräftepaar in der Bohrung, Drehung der Bohrung
aus den Verschiebungen) ergibt 5,8 · 10⁵ Nmm/rad, also etwa halb so steif wie die Balkenrechnung (örtliche
Nachgiebigkeit an Schlitz und Bohrung); damit blieben rund 70 % im Halter und der Festkörper etwa bei 0,42 bis 0,45.
Die Handrechnung „gelenkig, S0 etwa 2 bis 3“ setzt voraus, dass der Halter kein Moment nimmt; das tut er elastisch nur,
wenn die Klemmung rutscht oder das Rohr Spiel hat. Der Halter bleibt rot; maßgebend ist die Schichtfuge (stehend
gedruckt, Biegung quer zur Schicht): drehen (liegend drucken) oder verstärken, wie die Drucklagen des Festkörpers
zeigen.

Erledigt aus den offenen Punkten oben: Befunde `statik_dyn_*` und `statik_festkoerper` in der Prüfung (S2, S3),
Schalter für frei laufende Gelenke mit Bereich (Nachbesserung).

### Ehrliche Grenzen (Stand 23.10.2026)

- ~~Bewusst offen: Kontakt mit Abheben und Reibung, Plastizität und Beulen (CalculiX).~~ Seit Stufe 4 gebaut
  (Abschnitt „Stand Stufe 4“ unten): auf Anfrage (`festigkeit(…, verfahren="ccx")`) oder aus model.py
  (`st.festigkeit`). Der Festkörper der Stufe 3 spannt weiter fest ein und rechnet linear-elastisch; er bleibt die
  schnelle Stufe nach jedem Lauf.
- Drehfedern ohne Spiel und ohne Rutschen der Klemmung, aus der Balkenrechnung (am Kugelschieber etwa doppelt so steif
  wie im Festkörper gemessen); eine Feder aus einer kleinen FEM des Halters im Hintergrund mit zweitem Stabwerk-Durchgang
  wäre die nächste Stufe.
- Freie Gelenke zwischen Nicht-Stäben (Schublade im Korpus) sind in S0/S1 ein Körper wie am Anschlag; erst der Ablauf
  lässt sie laufen. Festkörper spannen die Gleitfläche fest ein.
- Weiter wie oben: Rückprall, Rollwiderstand, Lagerreibung der Laufrollen, federnde Stäbe im Ablauf; Füllung und Wände
  der Druckteile; gekrümmte Elemente; Kraftpaare nicht im Ablauf.

## Stand Stufe 4: Kontakt, Plastizität, Traglast, Beulen (Zweig `statik4`, 23.10.2026)

Kevin am 23.10.2026: „Bau doch auch die anderen Sachen, diese Kontakt- und Plastizität-Geschichten.“ Umgesetzt in
`kernel/src/kevcad_kernel/statik/ccx/` (Übersicht im Docstring von `__init__.py`), MCP `festigkeit` mit
`verfahren="ccx"`, `kontakt`, `plastisch`, `traglast`, `beulen`, `klemmkraft`, `reibwert` (additiv), in model.py
`st.kontakt(a, b, reibwert=, klemmkraft=, spiel=)` und `st.festigkeit(teil, kontakt=, plastisch=, traglast=, beulen=)`,
STATICS und STATICS_FIELD additiv (PROTOCOL.md „CalculiX (Stufe 4, additiv)“). App: im Festkörper des
Statik-Abschnitts „CalculiX (S4)“, Traglast, Sicherheit unter Last, Kontakt je Partner, Klemmkraft, Plastizität, Beulen,
„rutscht“ und die Auswahl „Farbfeld“ (Ausnutzung, Kontaktdruck, plastische Dehnung, Klaffen, Schlupf). Skill
`statik.md`, Abschnitt „Kontakt, Plastizität, Traglast, Beulen“. Tests `kernel/tests/test_statik4.py` und
`StatikFestkoerperTests.swift`.

| Nr. | Entscheidung | Begründung |
|---|---|---|
| T36 | **CalculiX 2.23 von conda-forge** (Paket `calculix`, osx-arm64, mit ARPACK, OpenBLAS, libgfortran, llvm-openmp; SPOOLES eingebaut) über **micromamba** (statisches Programm von conda-forge) in eine eigene Umgebung auf der **externen Platte**: `/Volumes/UPVIS ULTRA/#PROGRAMME_DO-NOT-DELETE#/Kev CAD/calculix/` mit `LIESMICH.txt` (wofür, wer, neu einrichten, Quelle, GPL), `bin/micromamba`, `env/bin/ccx`, `mamba/pkgs` (Paket-Zwischenspeicher), `stand.json`. Belegt 55 MB (micromamba 14 MB, Umgebung 26 MB, Zwischenspeicher 15 MB), rund 25 MB Download, 14 s. Übersteuerbar mit `KEVCAD_CALCULIX_DIR` bzw. `KEVCAD_CCX` oder der Einstellung `calculix.json` in Application Support. `build.sh` richtet es bei jeder Installation ein, falls es fehlt (nie fatal), sonst Kev CAD beim ersten Gebrauch | Kevins Vorgabe: externe Programme auf UPVIS ULTRA, die Systemplatte ist knapp. conda-forge baut ccx reproduzierbar mit allen Bibliotheken; Homebrew hat keine Formel, selbst bauen bräuchte gfortran, SPOOLES und ARPACK. Fehlt die Platte, meldet Stufe 4 „CalculiX nicht verfügbar (externe Platte UPVIS ULTRA nicht angeschlossen)“, S0 bis S3 laufen weiter, das Update scheitert nicht |
| T37 | **Dieselben Fälle und Netze wie S3:** Der S4-Auftrag ist der Auftrag der Stufe 3 (Teil, Lasten, Lager aus dem Statikmodell) plus Verbindungsarten, Kontaktkörper, Klemmschrauben und Fließkurven (`ccx/auftrag.py`); das Netz ist das P2-Netz der Stufe 3 (Gmsh, scikit-fem) als C3D10, die Lasten dieselben konsistenten Knotenkräfte (RBE3-Verteilung). ccx rechnet in einem eigenen Prozess (`python -m kevcad_kernel.statik.ccx.prozess`), Fortschritt aus seiner Ausgabe über ein Pseudo-Terminal, Abbruch beendet die Prozessgruppe | Linear und ohne Kontakt gleicht S4 der Stufe 3 (Wandhalter: 1,835 und 1,835, Durchbiegung 2,435 mm): Unterschiede kommen nur aus Kontakt und Plastizität. Quer zur Schicht weicher über technische Konstanten mit eigener Orientierung |
| T38 | **Kontaktpaare** statt fester Einspannung, wo die Verbindung abheben oder gleiten kann: Klemmung, Steck, Aufliegen, Gelenke, bloße Berührung und Spiel, dazu `st.kontakt`; fest bleiben `schraube`, `kleben`, `formschluss` und an der Umgebung `befestigt` Teile. Lager-Partner sind starr (Zuschnitt um das Teil plus 3 mm, alle Knoten fest); Stäbe, die Last einleiten, sind elastische Körper (Zuschnitt um das Teil plus max(15 mm, 1,5 Durchmesser)) und bekommen an ihren Schnittflächen Kraft und Moment beider Seiten aus dem Stabwerk (`auflager[i].seiten`, neu in S1). Fläche zu Fläche nach dem Strafverfahren, Drucksteifigkeit 2 E je mm des weicheren Werkstoffs, Haftsteifigkeit ein Fünfzigstel davon, Haftreibwert der Paarung aus `reibwerte.json` (sonst 0,3). Kontaktzonen nur aus zugewandten Flächen (Normalen gegeneinander, bis 0,3 mm plus Toleranz). Die Kantenmitten der C3D10 liegen auf der echten Geometrie (Gmsh zweiter Ordnung, eigener Netzspeicher; Stufe 3 behält ihr Netz) | So kommt die Last dort an, wo sie im Bauteil herkommt (über die Bohrung, nicht als Ersatzkraft auf der Fläche). Ohne die Richtungsprüfung kamen Stirn- und Innenflächen des Rohrs als Kontaktflächen dazu (36 000 Kontaktelemente statt einiger Tausend). Mit geraden Kantenmitten durchdrangen sich Bohrung und Rohr um die Pfeilhöhe (am Rohr Ø 12 bei h 2 mm 0,11 mm, mehr als das Spiel): schon die Klemmung allein gab 35 N/mm² mittleren Druck statt 6 |
| T39 | **Halte-Federn** für Körper ohne feste Knoten (Stab im Kontakt, Teil nur auf Kontakt gelagert): je Knoten und Richtung eine Feder gegen den Boden, zusammen 0,1 % der Last je mm (mindestens 1e-8 · E · Größe); das erste Inkrement eines Schritts, in dem ein frei gelagerter Körper Last bekommt, 0,01 % der Last (nach einer Vorspannung 5 %); Inkremente wachsen nach leichter Konvergenz um das Dreifache (CalculiX `D_D`, sonst 1,5). Tragen die Federn mehr als 5 % der Last oder bewegt sich der Körper mehr als 0,1 mm über das Zehnfache des linear Erwarteten, **rutscht** er | Ohne Federn ist das System singulär, solange der Kontakt offen ist. Zu weiche Federn mit großem ersten Inkrement schoben die Kugel 13 m aus der Kontaktzone; zu steife (2 % je mm) nahmen am Kugelschieber 20 % der Last auf, weil das Rohr mit dem nachgiebigen Halter 2 mm mitwandert, und meldeten fälschlich „rutscht“. Das Dreifache halbiert die Zahl der Inkremente |
| T40 | **Klemmschrauben** aus den Verbindungen: `verbinde(…, art="schraube", mit=[…])` innerhalb des Teils samt eingeschmolzener oder geklebter Teile (Sterngriffklemme: Halter, Einsatz, Schraube, Scheibe). Kräftepaar in einem eigenen ersten Schritt „Vorspannung“: Kopfseite (Flächen an Scheibe bzw. Kopf, Richtung senkrecht zur Auflage) in das Teil, Mutterseite (Einsatz, Mutter) dagegen; liegt die Mutterseite nicht am Teil (im starren Lager), nur die Kopfseite. Klemmkraft ohne Angabe „handfest“ 120 N je mm Gewinde (M6: 720 N), sonst `klemmkraft=` in model.py oder im Werkzeug. Die Teile der Klemmung sind kein Lager (Stufe 3 nimmt sie, weil sie das Teil berühren) | Der Schlitz schließt sich, die Backen pressen das Rohr: das ist die Klemmung, die S3 und die Drehfeder T35 nur annähern. Die Kante zwischen Halter und Einsatz kennt nur die zuletzt erklärte Art, darum aus der Liste der Verbindungen; die Richtung aus den Schwerpunkten allein kippte die Kraft um 2° (Rutschgrenze −4 %) |
| T41 | **Plastizität** isotrop nach von Mises: Metalle von Rp0,2 auf Rm bei angenommener Gleichmaßdehnung (Stahl 15 %, Edelstahl 30 %, Aluminium 6 %, Buntmetall 20 %), danach ideal plastisch; Druckteile ideal plastisch ab der Zugfestigkeit (Drucklage bekannt) bzw. ab `quer_zur_schicht` · Zugfestigkeit (unbekannt), die Schichtfuge bleibt spröde (Kriterium wie S3). Nach der Last wird entlastet: **bleibende Verformung** | Der Katalog hat Rp0,2 und Rm, aber keine Bruch- oder Gleichmaßdehnung; CalculiX hat keine richtungsabhängige Fließgrenze ohne eigenes Werkstoffmodell, die Schichtfuge bricht spröde: eine Näherung mit ehrlicher Kennzeichnung |
| T42 | **Traglast** (Standard mit Plastizität, sonst auf Wunsch, etwa die Rutschgrenze einer Klemmung): eigener Lauf mit einer Rampe bis λ_max = max(2, 3 · Ziel, 3 · Sicherheit unter Last) ≤ 50 in Schritten von höchstens 5 %, dann bis zu zwei Läufe in der Klammer des maßgebenden Kriteriums (zügig bis an ihren Anfang, dann 16 Schritte), bis die Klammer schmaler als 2 % ist. Kriterien: plastische Grenzdehnung 5 % (Metall, DIN EN 1993-1-5 Anhang C) bzw. 2 % (Druckteil), Schichtfuge, Festigkeit (elastische Werkstoffe), Rutschen, Kollaps; ccx wird beendet, wenn die Verschiebung springt oder davonläuft. Traglast aus Fließen × 0,95 | Bei Stufe 4 **ist die Sicherheit der Traglastfaktor** (gleiche Ziele, T5). Klammer statt Interpolation, weil Rutschen springt (ein grober Lauf gab 2,19 statt 3,00). Tetraeder zweiter Ordnung liegen voll plastisch zu hoch: am symmetrisch gelagerten Kragbalken +5,7 %, netzunabhängig (h 3 und 1,7 mm), daher × 0,95 |
| T43 | **Beulen** als eigener linearer Lauf (`*BUCKLE`, Lager wie S3, Last λ = 1); der kleinste positive Beulfaktor zählt als Sicherheit, wenn er kleiner ist | Einfach und genau (Kragstütze +0,1 %), für Bleche und Profile unter Druck |
| T44 | **Urteil** wie S3 (Urteil `festkoerper`, Ampel über Ziel / Sicherheit, T9), dazu mindestens gelb, wenn das Teil schon unter der Last bleibend fließt (über 0,2 %), rot bei Grenzdehnung unter Last oder wenn ein Partner schon unter der Last rutscht („Klemmkraft erhöhen oder Formschluss“). Ergebnis je Teil additiv in `festkoerper.teile[i]`, Feld mit Zusatzwerten; Befunde in der Prüfung wie S3 (T34, kein Exportverbot, T10) | Eine Farbsprache für alle Stufen; die Zahlen der Stufe 4 ersetzen die der Stufe 3 desselben Teils im Szenario |
| T45 | **Hintergrund aus model.py:** `st.festigkeit(teil, …)` rechnet nach jedem Lauf nach dem Festkörper der Stufe 3 (Stand „Stufe 4 (CalculiX) folgt“, damit die Prüfung nicht zwischendurch fertig meldet), je Auftrag ein CalculiX-Lauf; ohne `st.festigkeit` nur auf Anfrage. Zwischenspeicher je Fall (Schlüssel aus dem Fall der Stufe 3, Optionen, Verbindungen, Kontaktkörpern, Klemmungen, Stabkräften) unter `<Bundle-Cache>/festkoerper/ccx` | Stufe 4 dauert Sekunden bis Minuten: nicht für jedes Teil nach jedem Lauf, sondern wo Kevin oder der Agent es will; gleiche Fälle sofort |

Nachweise (Tests in `kernel/tests/test_statik4.py`, CalculiX 2.23 auf dem MacBook, Zeiten einschließlich Vernetzen
und aller Läufe):

| Probe | Handrechnung bzw. Literatur | CalculiX (S4) | Abweichung | Netz, Zeit |
|---|---|---|---|---|
| S4 linear gleich S3: Wandhalter PETG stehend gedruckt, 20 N | S3 1,835 | 1,835 | 0 | 537 Tetraeder, 1,2 s |
| Reibschluss: Block 20 × 20 × 10 mm (Stahl) auf starrer Platte, Klemmkraft 1000 N über Scheibe und Mutter, Querkraft in halber Höhe steigt, μ = 0,3: Rutschgrenze μ F_k / F_q | 3,000 | 3,002 | +0,1 % | 937 Tetraeder, drei Läufe, 112 s |
| Kragbalken S235 10 × 10 mm, 100 mm, ideal plastisch: F_pl = Rp0,2 · b h² / 4 / L | 587,5 N | 652,5 N roh, 619,9 N abgemindert | +11,1 % roh, +5,5 % | h 3 mm, 17 s |
| derselbe bei 500 N (über der Fließlast 391,7 N) | fließt an der Einspannung, bleibt verbogen | plastische Dehnung an der Einspannung, bleibend 0,017 mm | | |
| Kragstütze 10 × 10 × 300 mm, unten eingespannt: F_k = π² E I / (4 L²) | 4 798 N | 4 803 N | +0,1 % | h 5 mm, 1,4 s |
| Hertz: Kugelkappe R 20 mm auf Block 30 × 30 × 10 mm, PLA, 1000 N (μ 0,3; bei gleichen Werkstoffen ohne Einfluss auf den Druck): p0 = 3 F / (2 π a²), aus einer Ausgleichsgeraden von p² über r² | 102,0 N/mm² | 93,6 N/mm² | −8,2 % | an der Berührung h 0,7 mm (3 Elemente über a), 4 274 Tetraeder im Block, 35 343 Freiheitsgrade, 198 s |
| derselbe: a = (3 F R / (4 E*))^(1/3) | 2,163 mm | 2,254 mm | +4,2 % | |
| derselbe: Kraft aus dem Kontaktdruck | 1000 N | 1030 N | +3 % | |
| derselbe: Abplattung als Annäherung zweier Punkte auf der Achse in 2 a Tiefe (Halbraum, Johnson Gl. 3.45; δ = a² / R = 0,234 mm für weit entfernte Punkte) | 0,153 mm | 0,148 mm | −3,2 % | |

Ehrlich zum Kragbalken: Die +11 % roh setzen sich aus der Versteifung der Tetraeder im voll plastischen Zustand (+5,7 %
am symmetrisch gelagerten Balken, gleich bei h 3 und 1,7 mm) und der starren Einspannung zusammen, die die
Querdehnung an der Wand behindert und das Fließgelenk etwas vor die Wand schiebt (bei 200 mm Hebel nur noch +7 % roh).
Abgemindert bleibt die Traglast an starren Einspannungen einige Prozent über der Balkenrechnung.

Kugelschieber (Kopie von „Kugelschieber Variante B“ im Scratchpad, eigener Katalog und Speicher, ohne App über die
Laufzeit, 23.10.2026): vorderer Stangenhalter links (PLA, stehend gedruckt), Szenario „Ball drückt 100 N auf den
Fänger“. Stufe 4 findet die Sterngriffklemme von selbst (Halter, Einsatz, Sterngriffschraube M6 × 25, Scheibe), spannt
sie handfest mit 720 N vor und rechnet das Alurohr 12 × 1 als Zuschnitt (Halter plus 18 mm je Seite) mit den Kräften
beider Seiten der Seitenstange aus dem Stabwerk, Reibwert PLA auf Aluminium 0,2 aus dem Katalog, Halter am Rahmen fest
(verschraubt).

| | S3 (fest eingespannt, Drehfeder T35) | S4 (Kontakt mit Klemmung, 720 N) |
|---|---|---|
| Sicherheit (Ziel 4, Druckteil), Kriterium | 0,37, Schichtfuge | 0,57 unter Last, Schichtfuge |
| größte Vergleichsspannung | 61,6 N/mm² | 30,6 N/mm² |
| Kontakt Halter ↔ Rohr | – (verklebt) | Druck bis 56 N/mm² (an den Backenspitzen), im Mittel 6,7 N/mm², trägt auf 76 % der Bohrung |
| Gleiten unter der Last | – | bis 0,26 mm; auf rund 65 % der tragenden Fläche an der Haftgrenze |
| größte Verschiebung | 1,85 mm | 2,11 mm |
| Netz, Zeit | 4 499 Tetraeder, 25 905 Freiheitsgrade, Zwischenspeicher | Halter 4 513 und Rohr rund 3 200 Tetraeder, 45 252 Freiheitsgrade, 326 s (Vorspannung 4, Last 5 Inkremente) |

Deutung: Mit Kontakt nimmt die Klemmung das Kragmoment der Seitenstange über Kantenpressung an den Enden der Bohrung
auf, nicht als starre Einspannung; die Spannung im Halter halbiert sich gegenüber S3, er bleibt aber rot (0,57 gegen
Ziel 4, Schichtfuge der stehend gedruckten Säule). Die Klemmung selbst ist knapp: Unter 100 N Ballkraft liegt mehr
als die Hälfte der tragenden Fläche an der Haftgrenze und das Rohr gleitet im Halter bis 0,26 mm. Fester anziehen
(`klemmkraft=`) oder ein Anschlag hilft der Klemmung, dem Halter helfen liegend drucken (Drucklage) oder verstärken.


### Ehrliche Grenzen (Stand Stufe 4)

- **Kontakt** nach dem Strafverfahren (Fläche zu Fläche) mit kleinen Verformungen; die Partner sind Zuschnitte um das
  Teil, ein lasteinleitender Stab bekommt die Kräfte aus dem Stabwerk, ohne Rückwirkung auf das Stabwerk (die
  Verteilung der Last zwischen mehreren Haltern rechnet weiter S1 mit den Drehfedern T35). Lager-Partner sind starr.
- **Klemmkraft** ohne Angabe angenommen („handfest“); Schraubverbindungen zu den Lagern bleiben fest eingespannt, ihre
  Vorspannung und das Gewinde nicht einzeln.
- **Plastizität** isotrop; Metalle mit angenommener Gleichmaßdehnung, Druckteile ideal plastisch mit spröder
  Schichtfuge, ohne richtungsabhängige Fließgrenze, Füllung voll. Traglast aus Fließen mit Tetraedern einige Prozent zu
  hoch (abgemindert × 0,95; an starren Einspannungen bleiben einige Prozent).
- **Beulen** linear (Verzweigung), ohne Imperfektionen und ohne Plastizität: eine obere Schranke für dünne Teile.
- **Dauer**: CalculiX löst mit SPOOLES; bei 40 000 Freiheitsgraden mit Kontakt einige Sekunden je Iteration, ein Fall
  mit Klemmung und Traglast Minuten. Deshalb nur auf Anfrage oder für Teile mit `st.festigkeit`.
- Weiter wie oben: Rückprall, Rollwiderstand, Lagerreibung der Laufrollen, federnde Stäbe im Ablauf; gekrümmte
  Elemente; Kraftpaare nicht im Ablauf.
