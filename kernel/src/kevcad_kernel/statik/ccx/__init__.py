"""Statik Stufe 4 (PLAN-STATIK.md, „Stand Stufe 4“): Kontakt, Plastizität, Traglast und Beulen mit CalculiX.

Stufe 3 spannt Lagerflächen fest ein und rechnet linear-elastisch. Stufe 4 rechnet dieselben Fälle (Teil, Lasten,
Lager aus dem Statikmodell) nichtlinear mit CalculiX (``ccx``, GPL, nur als eigenes Programm): Kontaktpartner heben ab
und gleiten (Klemmung, Rohr in der Bohrung, aufliegende Platte), Klemmschrauben spannen vor, Metalle fließen mit
Verfestigung, Druckteile ideal plastisch mit spröder Schichtfuge; dazu Traglast (Lastfaktor bis zum Versagen) und
Beulfaktor.

| Modul | Läuft in | Inhalt |
|---|---|---|
| ``installation`` | überall | ccx finden (externe Platte UPVIS ULTRA, ``KEVCAD_CALCULIX_DIR``, ``KEVCAD_CCX``), einrichten (micromamba, conda-forge), prüfen |
| ``auftrag`` | Rechenprozess | S3-Auftrag plus Verbindungsarten, Kontaktkörper (zugeschnitten), Klemmschrauben, Fließkurven, Kräfte beider Stabseiten |
| ``deck`` | S4-Prozess | CalculiX-Eingabe: C3D10, Werkstoffe (auch quer zur Schicht), Kontaktpaare, Halte-Federn, Schritte |
| ``lauf`` | S4-Prozess | ccx starten, Fortschritt mitlesen, bei Kollaps beenden |
| ``frd`` | S4-Prozess | Ergebnisse lesen (``.frd``, ``.dat``) |
| ``prozess`` | eigener Prozess | ``python -m kevcad_kernel.statik.ccx.prozess auftrag.json ergebnis.json``: alles oben, Zwischenspeicher |
| ``urteil`` | Laufzeit | Kurzfassung je Teil (STATICS ``festkoerper.teile[i]`` mit ``verfahren: "ccx"``), Texte, Ampel |

Der Einstieg ist dasselbe MCP-Werkzeug wie S3: ``festigkeit(…, verfahren="ccx", kontakt=True, plastisch=True)``; in
model.py ``st.kontakt(a, b, …)`` und ``st.festigkeit(teil, …)`` (rechnet nach jedem Lauf im Hintergrund nach S3).
Einheiten: mm, N, N/mm².
"""

from __future__ import annotations

VERSION = 1  # Rechenstand der Stufe 4 (Zwischenspeicher)

GRENZEN_S4 = [
    "CalculiX (S4): Kontakt nach dem Strafverfahren (Fläche zu Fläche, Coulomb-Reibung mit Haftreibwert der "
    "Paarung), kleine Verformungen; Kontaktpartner nur als Zuschnitt um das Teil, Stäbe mit den Kräften beider Seiten "
    "aus dem Stabwerk (ohne Rückwirkung auf das Stabwerk), Lager-Partner starr.",
    "Plastizität isotrop nach von Mises; Metalle mit Verfestigung bis Rm bei angenommener Gleichmaßdehnung, "
    "Druckteile ideal plastisch ab der Zugfestigkeit mit spröder Schichtfuge (Näherung, keine richtungsabhängige "
    "Fließgrenze). Tetraeder zweiter Ordnung versteifen voll plastisch um einige Prozent (Traglast am Kragbalken "
    "+5 bis +7 % über M_pl).",
    "Klemmkraft ohne Angabe „handfest“ angenommen (120 N je mm Gewindedurchmesser); Schraubverbindungen zu den Lagern "
    "bleiben fest eingespannt, ihre Vorspannung wird nicht einzeln gerechnet.",
]
