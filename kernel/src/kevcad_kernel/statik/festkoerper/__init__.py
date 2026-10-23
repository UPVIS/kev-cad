"""Statik Stufe 3 (PLAN-STATIK.md, Paket T-D): Festkörper-FEM für Bauteile. „Hält der gedruckte Halter, wenn …?“

Teile, die im Stabwerk starr sind oder als Kragträger nachgewiesen werden (Druckteile, Platten, Verbinder), rechnet
Kev CAD als Volumen: Gmsh vernetzt die B-Rep, scikit-fem und ein eigener vektorisierter Kern bauen die Steifigkeit
aus Tetraedern zweiter Ordnung (P2), pyamg löst (kleine Systeme und dünne Teile SuperLU). Lager sind die
Kontaktflächen zu den tragenden Nachbarn, Lasten kommen aus den Szenarien (Einzellasten, Lagerkräfte des Stabwerks,
Eigengewicht, auf Wunsch Kontaktkräfte eines Ablaufs der Stufe 2).

| Modul | Läuft in | Inhalt |
|---|---|---|
| ``auftrag`` | Rechenprozess (auf Anfrage) | Lastfälle je Teil aus dem Modell des letzten Laufs, Teil als BREP, Nachbarnetze für die Lager, Schlüssel für den Zwischenspeicher → Ordner |
| ``werkstoff`` | FEM-Prozess | Steifigkeit (isotrop oder quer zur Schicht weicher), von Mises, Schichtkriterium |
| ``kontakt`` | FEM-Prozess | Abstand Punkte ↔ Dreiecke: Lagerflächen und Lastflächen auf dem Netz |
| ``netz`` | FEM-Prozess | Gmsh: BREP → Tetraeder, Netzgröße aus Wandstärke und Elementzahl, Flächen je B-Rep-Fläche |
| ``loeser`` | FEM-Prozess | P2-Steifigkeit, Lasten (verteilt wie ein RBE3), Lager, pyamg, Spannung an den Knoten |
| ``prozess`` | eigener Prozess | ``python -m kevcad_kernel.statik.festkoerper.prozess auftrag.json``: alles oben, Fortschritt als Zeilen, Zwischenspeicher |
| ``urteil`` | Laufzeit | Urteile im Format von ``bewertung.urteil``, Einbau ins Szenario, Texte |
| ``laufzeit`` | Laufzeit | MCP ``festigkeit``, Hintergrund nach dem Lauf, Abbruch, STATICS und STATICS_FIELD |

Gmsh ist GPL und läuft deshalb nur im eigenen FEM-Prozess, nie im Rechenprozess von model.py und nie in der Laufzeit.
Einheiten: mm, N, N/mm² (MPa).
"""

from __future__ import annotations

VERSION = 1  # Rechenstand: ändert er sich, gelten alte Einträge im Zwischenspeicher nicht mehr

GRENZEN_S3 = [
    "Festkörper (S3) linear-elastisch mit kleinen Verformungen: kein Fließen, kein Kontakt mit Abheben, Lagerflächen "
    "fest eingespannt (wie verklebt), Schrauben und Gewinde nicht einzeln (Kontakt und Plastizität mit CalculiX "
    "bewusst nicht).",
    "Druckteile mit voller Füllung gerechnet; quer zur Schicht weicher (E-Modul Z aus dem Katalog) und schwächer "
    "(Anteil quer_zur_schicht), Wände, Füllmuster und Nähte nicht einzeln.",
    "Spannungsspitzen an scharfen Innenkanten und am Rand der Einspannung hängen vom Netz ab; Kev CAD nimmt den "
    "Knotenmittelwert.",
]
