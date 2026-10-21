# Aufzeichnungen für den Spiegel (iPhone-Live-Ansicht)

Echte Läufe zum Testen ohne laufende Kev-CAD-App, für VoiceBridge (M2/M3) und den Spiegel-Simulator (M1). Vertrag:
[MIRROR.md](../../MIRROR.md).

| Datei | Inhalt |
|---|---|
| `gestell.kcadrec` | Kernel-Rahmen, wie die App sie bekommt: `samples/gestell`, 17 Teile, 27.148 Dreiecke, 1,1 MB |
| `gestell.kcadmirror` | daraus Spiegel-Rahmen Version 1: Handschlag, Szene, alle Netze in Blöcken, Zustand, Drehteller mit 90 Kamerastände, Auswahl, Hervorhebung, Ausblenden, Isolieren, Röntgen, neuer Lauf, Befehle; 0,3 MB |
| `kugelschieber.kcadrec` | Kevins Kugelschieber (Rollwagen, FX6, Ball), 112 Teile, 131.950 Dreiecke, 6,0 MB; nicht im Git |
| `kugelschieber.kcadmirror` | dasselbe als Spiegel-Rahmen, Szene über drei Seiten, 119 Netzblöcke, 1,3 MB; nicht im Git |

Beide Formate: Rahmen hintereinander, je `u32 LE` Länge des JSON-Kopfes, JSON, `u32 LE` Länge der Nutzlast, Nutzlast.
Jeder Kopf trägt zusätzlich `rec_t_ms` (Zeitpunkt in ms) zum Abspielen in Echtzeit; das Feld gehört nicht zum
Protokoll und wird beim Abspielen ignoriert.

In `.kcadmirror` stehen auch die Befehle vom iPhone (`CMD`) als Beispiele, obwohl sie in Wirklichkeit in die andere
Richtung laufen. Der Hash jedes Netzes ist geprüft: Blöcke aneinanderhängen, mit LZFSE auf `roh_bytes` entpacken,
SHA-256, die ersten 16 Hex-Zeichen.

Neu erzeugen (im Ordner `kernel/`):

```bash
.venv/bin/python tools/record_session.py ../samples/gestell ../samples/mirror-recordings/gestell.kcadrec
```

```bash
.venv/bin/python tools/mirror_demo.py ../samples/mirror-recordings/gestell.kcadrec ../samples/mirror-recordings/gestell.kcadmirror
```

`record_session.py` arbeitet auf einer Kopie des Projekts; das Original bleibt unberührt. `--slow-ms 200` zeichnet in
Zeitlupe auf, damit der Aufbau Teil für Teil gut zu sehen ist.
