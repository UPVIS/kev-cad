#!/usr/bin/env bash
# Baut "Kev CAD.app" und legt sie in ~/Applications/Tools ab (Tools-Stapel im Dock).
#
#   ./build.sh              bauen und installieren: App nach ~/Applications/Tools, Kernel und Skill als eigene Kopie nach
#                           ~/Library/Application Support/de.upvis.kevcad/install (die installierte App hängt damit
#                           nicht am Arbeitsstand des Repos). Automatisch nach jedem neuen Stand auf main, siehe
#                           tools/auto-update.sh und .githooks/
#   ./build.sh --no-install nur bauen (build/Kev CAD.app)
#   ./build.sh --test [zusatz]
#                           Testvariante "Kev CAD Test" (mit Zusatz z. B. "Kev CAD Test ui") mit eigener Bundle-ID,
#                           eigenem Datenordner und Port; wird nicht installiert, Fenster öffnet auf dem zweiten Monitor
#   ./build.sh --core-tests nur die Tests von KevCADCore (swift test) und vom Kernel (pytest)
set -euo pipefail

cd "$(dirname "$0")"
REPO="$(pwd)"
MODE="${1:-}"

APP_NAME="Kev CAD"
BUNDLE_ID="de.upvis.kevcad"
PORT=47823
if [ "$MODE" = "--test" ]; then
  SUFFIX="${2:-}"
  APP_NAME="Kev CAD Test${SUFFIX:+ $SUFFIX}"
  BUNDLE_ID="de.upvis.kevcad.test${SUFFIX:+.$SUFFIX}"
  # je Testvariante ein eigener Port, damit mehrere nebeneinander laufen können
  PORT=$((47824 + $(printf '%s' "$SUFFIX" | cksum | cut -d' ' -f1) % 100 * (${#SUFFIX} > 0)))
fi
INSTALL_DIR="$HOME/Applications/Tools"
INSTALL_ROOT="$HOME/Library/Application Support/de.upvis.kevcad/install"
BUILD="$REPO/build"
INSTALLING=0
[ -z "$MODE" ] && INSTALLING=1
APP_REPO="$REPO"
BUILD_NUMBER=$(git rev-list --count HEAD 2>/dev/null || echo 1)
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "")
[ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ] && COMMIT="$COMMIT+"

echo "==> Kernel-Umgebung"
command -v uv >/dev/null || { echo "uv fehlt (https://docs.astral.sh/uv/)"; exit 1; }
(cd kernel && uv sync -q)

if [ "$MODE" = "--core-tests" ]; then
  echo "==> Tests KevCADCore"
  (cd app/KevCADCore && swift test 2>&1 | tail -5)
  echo "==> Tests Kernel"
  (cd kernel && .venv/bin/python -m pytest -q)
  exit 0
fi

echo "==> Icon"
mkdir -p app/Resources
ICNS="app/Resources/AppIcon.icns"
if [ ! -f "$ICNS" ] || [ app/icon.svg -nt "$ICNS" ]; then
  ICONSET="$BUILD/AppIcon.iconset"
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  render() { rsvg-convert -w "$1" -h "$1" app/icon.svg -o "$ICONSET/$2"; }
  render 16 icon_16x16.png
  render 32 icon_16x16@2x.png
  render 32 icon_32x32.png
  render 64 icon_32x32@2x.png
  render 128 icon_128x128.png
  render 256 icon_128x128@2x.png
  render 256 icon_256x256.png
  render 512 icon_256x256@2x.png
  render 512 icon_512x512.png
  render 1024 icon_512x512@2x.png
  iconutil -c icns "$ICONSET" -o "$ICNS"
  rm -rf "$ICONSET"
fi

if [ "$INSTALLING" = 1 ]; then
  echo "==> Kernel und Skill installieren nach $INSTALL_ROOT"
  mkdir -p "$INSTALL_ROOT"
  rsync -a --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude tests --exclude tools \
    kernel/ "$INSTALL_ROOT/kernel/"
  (cd "$INSTALL_ROOT/kernel" && uv sync -q --frozen --no-dev)
  rsync -a --delete skill/ "$INSTALL_ROOT/skill/"
  printf '%s %s %s\n' "$COMMIT" "$BUILD_NUMBER" "$(date '+%Y-%m-%d %H:%M')" > "$INSTALL_ROOT/VERSION"
  APP_REPO="$INSTALL_ROOT"
fi

echo "==> Xcode-Projekt erzeugen"
command -v xcodegen >/dev/null || { echo "xcodegen fehlt (brew install xcodegen)"; exit 1; }
xcodegen generate --spec app/project.yml --quiet

echo "==> Kompiliere ($APP_NAME)"
mkdir -p "$BUILD"
LOG="$BUILD/xcodebuild.log"
if ! xcodebuild -project app/KevCAD.xcodeproj -scheme KevCAD -configuration Release \
  -destination "platform=macOS,arch=arm64" -derivedDataPath "$BUILD/DerivedData" \
  KEVCAD_APP_NAME="$APP_NAME" KEVCAD_BUNDLE_ID="$BUNDLE_ID" KEVCAD_REPO="$APP_REPO" KEVCAD_PORT="$PORT" \
  KEVCAD_BUILD="$BUILD_NUMBER" KEVCAD_COMMIT="$COMMIT" \
  build -quiet > "$LOG" 2>&1; then
  grep -E "error:|\*\* BUILD FAILED" "$LOG" | grep -v "^Failed frontend" | head -30
  echo "Build fehlgeschlagen, vollständiges Protokoll: $LOG"
  exit 1
fi

SRC="$BUILD/DerivedData/Build/Products/Release/$APP_NAME.app"
[ -d "$SRC" ] || { echo "Build fehlgeschlagen: $SRC fehlt"; exit 1; }
rm -rf "$BUILD/$APP_NAME.app"
cp -R "$SRC" "$BUILD/$APP_NAME.app"
APP="$BUILD/$APP_NAME.app"
codesign --force --deep --sign - --timestamp=none "$APP" >/dev/null 2>&1
# Build-Kopien bei Launch Services abmelden, sonst startet `open -b de.upvis.kevcad` womöglich eine davon statt der
# installierten App.
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSREGISTER" -u "$SRC" >/dev/null 2>&1 || true
"$LSREGISTER" -u "$APP" >/dev/null 2>&1 || true

if [ "$MODE" = "--no-install" ] || [ "$MODE" = "--test" ]; then
  echo "==> Fertig (nicht installiert): $APP (Bundle-ID $BUNDLE_ID, MCP-Port $PORT)"
  exit 0
fi

echo "==> Installiere nach $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/$APP_NAME.app"
cp -R "$APP" "$INSTALL_DIR/"
# Ohne das Zurücksetzen zeigt der Finder häufig noch das alte Symbol.
touch "$INSTALL_DIR/$APP_NAME.app"
"$LSREGISTER" -f "$INSTALL_DIR/$APP_NAME.app" >/dev/null 2>&1 || true

echo "==> Fertig: $INSTALL_DIR/$APP_NAME.app (Build $BUILD_NUMBER, $COMMIT)"
du -sh "$INSTALL_DIR/$APP_NAME.app"
