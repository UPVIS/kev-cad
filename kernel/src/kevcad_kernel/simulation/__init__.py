"""Bereich „Simulation“ (PLAN-SIMULATION.md): Lastfälle, Kräfte und Lager, die Kevin in der App per Klick anlegt.

| Modul | Inhalt |
|---|---|
| ``datei`` | ``<projekt>/simulation.json``: Format, Lesen und Schreiben, Operationen (App ``SIM_EDIT`` und MCP gleich) |
| ``kraft`` | vom Klick zur Kraft: Richtung (Normale, Achse, frei) und Betrag (N, kg) |
| ``zuordnung`` | Lasten und Lager gegen den aktuellen Stand des Modells: Fläche wiederfinden, „nicht mehr zuordenbar“; Lagerflächen |
| ``grenze`` | „Grenze suchen“: wie viel Last, wie steil (S0 und S1, Halbierung) |
| ``laufzeit`` | Mixin der Laufzeit: Nachrichten SIM und SIM_JOB, Anfragen der App, MCP ``simulation_*`` |

Die Statik lädt ``simulation.json`` bei jedem Lauf zusätzlich zu den Szenarien aus model.py
(``statik/anbindung.py``); gleiche Namen: die App gewinnt. Einheiten: mm, N, Grad, m/s².
"""
