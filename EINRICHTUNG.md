# Kev CAD einrichten

Diese Anleitung bringt Kev CAD auf einem fremden Mac zum Laufen: bauen, installieren, mit einem KI-Agenten über MCP
verbinden. Sie ist so geschrieben, dass ein Agent (etwa Claude Code) sie Schritt für Schritt ausführen kann. Jeder
Schritt hat einen Befehl und eine Prüfung. Schlägt eine Prüfung fehl, hilft der Abschnitt [Fehlerbehebung](#fehlerbehebung).

Kurzfassung für einen Agenten:

> Richte Kev CAD nach `EINRICHTUNG.md` in diesem Repo ein: Voraussetzungen prüfen und installieren, `./build.sh`
> ausführen, den MCP-Server `kevcad` und den Skill `kev-cad` für Claude Code einrichten und zum Schluss mit dem
> Werkzeug `status` prüfen, ob App und Kernel verbunden sind. Optionale Teile (CalculiX, Blender, Bambu Studio,
> iPhone-App Kev Scan) nur nach Rückfrage.

## Was installiert wird

| Was | Wohin | Wozu |
|---|---|---|
| `Kev CAD.app` | `~/Applications/Tools/` | Viewer (SwiftUI, Metal) |
| Kernel, Skill, Zusatzumgebungen | `~/Library/Application Support/de.upvis.kevcad/install/` | Python-Kernel (build123d) mit MCP-Server, Leitfaden für den Agenten, fotomess (Vermessen), scan (iPhone-Scans auswerten), kevcad-capture (Object Capture) |
| Projekte | `~/Documents/Kev CAD/` | ein Ordner je Projekt mit `model.py` |
| Einstellungen, Lagerkatalog | `~/Library/Application Support/de.upvis.kevcad/` | eigener Katalog, Filamente, Drucker |
| Zwischenspeicher, Modellgewichte | `~/Library/Caches/de.upvis.kevcad/` | PromptDA-Gewichte (laden beim ersten Scan) |

Die installierte App und der MCP-Server nutzen nur die Kopie unter `install/`, nicht den Arbeitsstand des Repos.
Nach `git pull` also erneut `./build.sh` ausführen.

Platzbedarf: rund 8 GB. Je 2,4 GB brauchen die Python-Umgebungen im Repo und in der Installation (OpenCASCADE, torch
für PromptDA), 1,4 GB die PromptDA-Gewichte und rund 1 GB die Metal-Toolchain; dazu kommt der Zwischenspeicher von uv.
Der erste Bau dauert je nach Netz 15 bis 30 Minuten, spätere wenige Minuten.

## 1 Voraussetzungen

| Was | Prüfen | Erwartet |
|---|---|---|
| Mac mit Apple Silicon | `uname -m` | `arm64` |
| macOS 15 oder neuer | `sw_vers -productVersion` | `15.0` oder höher |
| Xcode (nicht nur die Command Line Tools), einmal geöffnet und Lizenz bestätigt | `xcodebuild -version` | aktuelles Xcode; gebaut und getestet mit Xcode 27, ältere Fassungen ungeprüft |
| Metal-Toolchain (ab Xcode 26 ein eigener Download) | `xcrun metal --version` | eine Versionszeile |
| Homebrew | `brew --version` | eine Versionszeile |
| XcodeGen | `xcodegen --version` | `Version: 2.4x` |
| librsvg (für das App-Symbol) | `rsvg-convert --version` | eine Versionszeile |
| uv (Python-Umgebungen) | `uv --version` | `uv 0.5` oder neuer |
| git | `git --version` | eine Versionszeile |

Fehlende Teile installieren:

```bash
xcode-select -p || xcode-select --install          # danach Xcode aus dem App Store, einmal öffnen
sudo xcodebuild -license accept                     # einmalig, braucht das Passwort
xcodebuild -downloadComponent MetalToolchain        # rund 840 MB, ohne Passwort
brew install xcodegen librsvg
curl -LsSf https://astral.sh/uv/install.sh | sh     # oder: brew install uv
```

Python selbst ist nicht nötig: uv holt Python 3.12 von selbst.

## 2 Klonen

```bash
git clone https://github.com/UPVIS/kev-cad.git
cd kev-cad
```

Prüfen: `ls build.sh kernel app` zeigt alle drei.

## 3 Bauen und installieren

```bash
./build.sh
```

`build.sh` baut der Reihe nach:

1. die Kernel-Umgebung (`kernel/.venv`),
2. fotomess und scan,
3. kevcad-capture (Swift-Paket für Apple Object Capture),
4. das App-Symbol,
5. das Xcode-Projekt (XcodeGen) und die App (Release, ad hoc signiert, kein Apple-Konto nötig).

Danach installiert es App, Kernel, Skill und Zusatzumgebungen wie in der Tabelle oben.

Prüfen:

```bash
ls ~/Applications/Tools/"Kev CAD.app"
ls ~/Library/Application\ Support/de.upvis.kevcad/install/kernel/.venv/bin/kevcad-mcp
```

Am Ende meldet `build.sh` „Fertig: … (Stand, Build, Bauzeit: …)“. Hinweise wie „Achtung: Umgebung von scan nicht
gebaut“ betreffen nur diese Zusatzfunktion; der Rest läuft.

Starten: `open ~/Applications/Tools/"Kev CAD.app"`. Ein Agent muss die App nicht selbst starten: Der MCP-Server
startet sie beim ersten Werkzeugaufruf.

Andere Bauarten (Kopf von `build.sh`):
- `./build.sh --no-install` baut nur nach `build/`.
- `./build.sh --test` baut eine Testvariante mit eigenem Namen, eigener Kennung und eigenem Port.
- `./build.sh --core-tests` führt die Tests aus.

## 4 Mit einem KI-Agenten verbinden (MCP)

Kev CAD bringt einen MCP-Server (stdio) mit. Der Agent schreibt `model.py`, ruft `run` auf, misst, exportiert und
sieht die Prüfbefunde. Der Server liegt in der installierten Kopie:

```
~/Library/Application Support/de.upvis.kevcad/install/kernel/.venv/bin/kevcad-mcp
```

### Claude Code

```bash
claude mcp add kevcad -s user -e KEVCAD_LAUNCH_ON_START=0 \
  -- "$HOME/Library/Application Support/de.upvis.kevcad/install/kernel/.venv/bin/kevcad-mcp"
mkdir -p ~/.claude/skills
ln -sfn "$HOME/Library/Application Support/de.upvis.kevcad/install/skill/kev-cad" ~/.claude/skills/kev-cad
```

Prüfen: `claude mcp list` zeigt `kevcad` als verbunden. In einer neuen Sitzung ruft der Agent das Werkzeug `status`
auf und bekommt `"kernel": "ready"` und `"app_connected": true`, sobald die App läuft. Erster Auftrag zum Ausprobieren:

> Leg in Kev CAD ein Projekt Regalwinkel an und bau einen Winkel aus 4-mm-Stahlblech mit zwei Bohrungen.

### Andere MCP-Clients (Claude Desktop, Cursor, …)

In der MCP-Konfiguration des Clients (bei Claude Desktop
`~/Library/Application Support/Claude/claude_desktop_config.json`, bei Cursor `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "kevcad": {
      "command": "/Users/<name>/Library/Application Support/de.upvis.kevcad/install/kernel/.venv/bin/kevcad-mcp",
      "env": { "KEVCAD_LAUNCH_ON_START": "0" }
    }
  }
}
```

Der Pfad muss ausgeschrieben sein, `~` und `$HOME` lösen die meisten Clients nicht auf. Der Leitfaden für den Agenten
liegt in `install/skill/kev-cad/SKILL.md` (mit `3d-druck.md`, `statik.md` und weiteren Dateien). Clients ohne Skills
bekommen die Grundregeln über die Server-Anweisungen des MCP-Servers mit; den Leitfaden dort als Regeldatei
einbinden, wo der Client das kann.

`KEVCAD_LAUNCH_ON_START=0` heißt: Der Server startet die App erst beim ersten Werkzeugaufruf, nicht schon beim
Verbinden. Weitere Schalter (Ports, Projektordner, Pfade zu Zusatzprogrammen) stehen unter
[Umgebungsvariablen](#umgebungsvariablen).

## 5 Optional: Zusatzprogramme

Alle sind freiwillig. Fehlt eines, meldet die betroffene Funktion das klar; alles andere läuft weiter.

| Programm | Wofür | Einrichten |
|---|---|---|
| **Bambu Studio** | Druckexport als fertig geslictes Bambu-Projekt (`druck_export`, Druckvorschau mit echter Zeit) | von bambulab.com nach `/Applications/BambuStudio.app`, sonst `KEVCAD_BAMBU_APP` setzen. Die Druckregeln sind auf einen Bambu Lab P1P zugeschnitten |
| **Blender** | Renderings in Fotoqualität (`render(qualitaet="foto")`, Cycles); „Schnell“ geht ohne | von blender.org nach `/Applications/Blender.app`, sonst `KEVCAD_BLENDER` |
| **CalculiX** | Statik Stufe 4: Kontakt, Plastizität, Traglast, Beulen (`festigkeit(verfahren="ccx")`); Stufe 0 bis 3 gehen ohne | siehe unten |
| **PromptDA-Gewichte** | Auswertung von iPhone-Scans | laden beim ersten Scan von selbst (Hugging Face, rund 1,4 GB) |

**CalculiX** kommt von conda-forge in einen eigenen Ordner. Bei Kevin liegt der auf einer externen Platte; auf
anderen Rechnern den Ort einmal festlegen und einrichten:

```bash
mkdir -p ~/Library/Application\ Support/de.upvis.kevcad
echo '{"ordner": "'"$HOME"'/Library/Application Support/de.upvis.kevcad/calculix"}' \
  > ~/Library/Application\ Support/de.upvis.kevcad/calculix.json
cd ~/Library/Application\ Support/de.upvis.kevcad/install/kernel
.venv/bin/python -m kevcad_kernel.statik.ccx.installation
```

Prüfen: `.venv/bin/python -m kevcad_kernel.statik.ccx.installation --pruefen` nennt Version und Pfad von `ccx`.

## 6 Optional: iPhone-App Kev Scan

Kev Scan nimmt einen Gegenstand mit LiDAR, Kameralagen und Fotos auf. Der Scan geht per WLAN an Kev CAD und wird dort
zu einem maßstäblichen Netz. Damit vermisst Kev CAD die Maße des Modells. Die App ist freiwillig und braucht:

- ein iPhone oder iPad mit LiDAR (iPhone Pro ab 12, iPad Pro), iOS 18 oder neuer,
- ein Apple-Konto in Xcode (ein kostenloses reicht für eigene Geräte, die App läuft dann 7 Tage), das Gerät per Kabel
  oder WLAN mit dem Mac gekoppelt und im Entwicklermodus (iPhone: Einstellungen > Datenschutz & Sicherheit >
  Entwicklermodus).

Bauen und aufspielen, mit eigener Team-ID und eigener Kennung:

```bash
KEVSCAN_TEAM=<Team-ID> KEVSCAN_BUNDLE_ID=com.<name>.kevscan tools/kevscan.sh alles
```

Die Team-ID steht in Xcode unter Settings > Accounts > (Konto) > Team. Prüfen: `tools/kevscan.sh alles` endet mit
„Auf dem iPhone installiert.“; danach in Kev Scan einen Scan aufnehmen und senden. Er erscheint in Kev CAD unter
„Referenzen“ und im MCP-Werkzeug `scans`. iPhone und Mac müssen im selben WLAN sein (Bonjour `_kevscan._tcp`).
Vertrag und Format: [SCAN.md](SCAN.md).

## 7 Aktualisieren

```bash
git pull
./build.sh
```

Wer Kev CAD selbst weiterentwickelt, kann die Git-Hooks einschalten. Dann baut und installiert jeder neue Stand auf
`main` von selbst im Hintergrund, aus einer sauberen Arbeitskopie (`tools/auto-update.sh`, Protokoll
`~/Library/Logs/Kev CAD/update.log`):

```bash
git config core.hooksPath .githooks
```

## 8 Tests

```bash
./build.sh --core-tests        # swift test (KevCADCore) und pytest (Kernel), rund 20 Minuten
cd fotomess && uv run pytest   # Vermessen
```

Kernel-Tests nutzen eigene Sockets und Ports und stören eine laufende App nicht.

## Umgebungsvariablen

Für den MCP-Server bzw. den Kernel. Keine ist nötig.

| Variable | Wirkung |
|---|---|
| `KEVCAD_LAUNCH_ON_START` | `0`: App erst beim ersten Werkzeugaufruf starten |
| `KEVCAD_PROJECTS_DIR` | Ordner für Projekte statt `~/Documents/Kev CAD` |
| `KEVCAD_PORT` | Port des Kernels (Vorgabe 47823) |
| `KEVCAD_APP_PATH` | andere App, etwa eine Testvariante |
| `KEVCAD_BAMBU_APP`, `KEVCAD_BLENDER` | Pfade zu Bambu Studio bzw. Blender |
| `KEVCAD_CALCULIX_DIR`, `KEVCAD_CCX` | Ordner der CalculiX-Umgebung bzw. das Programm `ccx` direkt |
| `KEVCAD_SCANS_DIR` | Ablage empfangener Scans statt `~/Documents/Kev CAD/Scans` |

## Fehlerbehebung

| Meldung | Ursache und Abhilfe |
|---|---|
| `xcodegen fehlt` | `brew install xcodegen` |
| `rsvg-convert fehlt` | `brew install librsvg` |
| `uv fehlt` | uv installieren (siehe oben), neues Terminal öffnen |
| `error: cannot execute tool 'metal' due to missing Metal Toolchain` | `xcodebuild -downloadComponent MetalToolchain` |
| `xcode-select: error: tool 'xcodebuild' requires Xcode` | Xcode installieren, dann `sudo xcode-select -s /Applications/Xcode.app` |
| Kompilieren scheitert, Details in `build/xcodebuild.log` | Xcode aktualisieren; das Swift-Paket OCCTSwiftViewport ist auf einen festen Stand gepinnt und lädt beim ersten Bau von GitHub |
| macOS: „Kev CAD kann nicht geöffnet werden“ | Kommt nur vor, wenn die App von einem anderen Rechner kopiert wurde (ad hoc signiert, Quarantäne). Selbst bauen oder `xattr -dr com.apple.quarantine ~/Applications/Tools/"Kev CAD.app"` |
| MCP: `app_connected: false` | App starten (`open ~/Applications/Tools/"Kev CAD.app"`); läuft sie, den Agenten neu verbinden. Port 47823 belegt: `lsof -i :47823` |
| MCP-Werkzeuge fehlen im Client | Pfad im Client-Eintrag ausgeschrieben? Den Client nach der Änderung neu starten |
| `scan_importieren`: PromptDA-Gewichte | Der erste Scan lädt sie aus dem Netz; ohne Netz geht nur die LiDAR-Tiefe |
| Statik Stufe 4: „CalculiX nicht verfügbar“ | CalculiX einrichten (Abschnitt 5) |
| `tools/kevscan.sh`: „No Account for Team“ | `KEVSCAN_TEAM` und `KEVSCAN_BUNDLE_ID` setzen (Abschnitt 6) |

## Was nur Kevin betrifft

Kev CAD ist Kevins eigenes Werkzeug. Einiges darin ist auf seine Umgebung zugeschnitten und lässt sich auf anderen
Rechnern ignorieren:

- `tools/fern.sh` baut auf Kevins Mac mini. Ohne Mini baut es von selbst hier; Fremde nehmen `./build.sh`.
- `CLAUDE.md` enthält Kevins Arbeitsregeln für Agenten in diesem Repo (Bauen über `tools/fern.sh`, zweiter Monitor,
  Sperrdatei mit VoiceBridge). Sie gelten für seinen Rechner.
- Die Live-Ansicht und die Freigaben vom iPhone laufen über Kevins App VoiceBridge ([MIRROR.md](MIRROR.md)); ohne sie
  bleibt der Spiegel-Dienst still.
- **Lagerkatalog und Regeln:**
  - Der mitgelieferte Lagerkatalog und die Regeln stammen aus Kevins Werkstatt: Kaufteile aus dem Baumarkt, 3D-Druck
    auf einem Bambu Lab P1P.
  - Die Inventar-Regel (nur aus dem Katalog bauen) ist an. Eigene Lagerteile legt man mit dem Agenten an und gibt sie
    in der App frei.
- Texte für Agenten und in der Oberfläche sprechen den Nutzer als „Kevin“ an. Das ist nur Text; die Funktionen sind
  dieselben.
- Bundle-IDs beginnen mit `de.upvis`. Für die Mac-App spielt das keine Rolle (ad hoc signiert); für Kev Scan setzt man
  eine eigene Kennung (Abschnitt 6).
