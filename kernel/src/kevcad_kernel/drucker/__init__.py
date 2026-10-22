"""Phase 8: aus Kev CAD drucken auf Kevins Bambu Lab P1P (PLAN-PHASE8-DRUCK.md, Vertrag in DRUCKVORSCHAU.md).

Weg A (Kevins Entscheidung, Standard): Platten mit der CLI von Bambu Studio fertig slicen und in Bambu Studio öffnen;
Status nur lesend über MQTT. Weg B (LAN-only + Developer Mode): gesperrt, nicht ausgebaut, nur gegen Attrappen getestet.

Module:
- ``status``: Berichte des Druckers zusammenführen (Deltas), Modus aus ``print.fun``, HMS, Fortschritt.
- ``befehle``: MQTT-Befehle; ``art`` trennt Lesen (pushall, get_version) von Steuern.
- ``sperre``: Bedingungen vor jedem Steuerbefehl (verbindlich).
- ``mqtt``: Verbindung (paho-mqtt), einzige Stelle, die etwas an den Drucker schickt.
- ``ftps``: Upload (Weg B).
- ``ssdp``: passives Erkennen im LAN (nur zuhören).
- ``schluesselbund``: Zugangsdaten lesen (nur beim Verbinden, nie ausgeben).
- ``profile``, ``slicen``: Profile von Bambu Studio auflösen, CLI, Zwischenspeicher.
- ``dienst``: Einstellungen, Verbindung, Aufträge, PRINTER_STATUS.
- ``laufzeit``: Mixin für die Kernel-Laufzeit (App-Nachrichten, KernelService).
- ``bericht``: Text des MCP-Werkzeugs ``drucker_status``.
"""
