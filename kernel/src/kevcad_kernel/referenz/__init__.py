"""Phase 4: Foto und Video als Referenz (PLAN-PHASE4-REFERENZ.md, fotomess/STRATEGIE.md „Einbindung in Kev CAD“).

Eine Referenz ist ein eigenes Objekt neben dem Modell (R4), abgelegt in ``<projekt>/referenzen/<name>/``:

```
referenz.json            Quelle (Video oder Fotos), Einstellungen, Zustand der Läufe
capture/                 Apple Object Capture (kevcad-capture): netz_mm.obj, poses.json, bilder/, bericht.json
messung/                 fotomess: messung.json (Maße mit Sigma, Kameras, Empfehlungen), bilder/, masken/, kontrolle/
fotos/                   Fotos in Arbeitsgröße (Referenz aus Fotos)
```

Module:

- ``ablage``: Ordner, ``referenz.json``, Werkzeuge finden (kevcad-capture, fotomess).
- ``capture``: kevcad-capture als Unterprozess mit Fortschritt.
- ``netz``: OBJ und poses.json lesen, Kameras umrechnen, Netz an die Messung anlegen.
- ``varianten``: eigener Prozess in der Kernel-Umgebung, rechnet model.py mit überschriebenen ``param``-Werten
  (Grundstand und je freiem Maß eine Variante) und sammelt die gezeigten Teile flächenweise (Bauer für fotomess).
- ``vermessen``: Ablauf von ``referenz_vermessen`` (Varianten, dann fotomess als eigener Prozess).
- ``uebernehmen``: gemessene Maße in die ``param``-Aufrufe von model.py schreiben (nur auf Kevins Klick).
- ``laufzeit``: ``ReferenzRuntimeMixin`` der Kernel-Laufzeit (MCP-Dienst, Nachrichten an die App).
"""
