"""Scan mit dem iPhone (Kev Scan, SCAN.md): Empfang im Kernel, Auswertung als eigener Prozess, Referenz im Projekt.

- ``ablage``: Ordner der empfangenen Scans (``~/Documents/Kev CAD/Scans/<datum>_<name>/``, Testvarianten im eigenen
  Datenordner), Liste mit Zustand, sicheres Entpacken, Werkzeug ``kevscan`` (eigene uv-Umgebung ``scan/``) finden.
- ``empfang``: HTTP auf einem freien Port (``GET /``, ``POST /scan``), Bonjour ``_kevscan._tcp`` über ``dns-sd``.
- ``vermessen``: Quelle für fotomess aus einer Scan-Referenz (bekannte Kameras, Tiefe, Masken).
- ``laufzeit``: ``ScanRuntimeMixin`` der Kernel-Laufzeit (MCP ``scans``, ``scan_importieren``, Empfänger starten).

Die Auswertung (PromptDA, TSDF) läuft nie im Kernel-Prozess: ``scan/.venv/bin/python -m kevscan auswerten``.
"""
