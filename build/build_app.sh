#!/usr/bin/env bash
# ==============================================================================
# Assembla "Forensic Tools.app" (Apple Silicon) — vedi BLUEPRINT.md §3
#   ./build/build_app.sh            → dist/Forensic Tools.app
#   ./build/build_app.sh --zip      → anche ~/Desktop/Forensic_Tools.zip
# Prerequisiti (una tantum): ~/.ft-build/py-aarch64/python con requirements.txt installati,
# ~/.ft-build/tools-arm64 (build/bundle_tools.py), models/ e lib/Ollama.app nel repository.
# ==============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$HOME/.ft-build"
PY="$BUILD/py-aarch64/python"
TOOLS="$BUILD/tools-arm64"
OLLAMA_RES="$REPO/lib/Ollama.app/Contents/Resources"
APP="$REPO/dist/Forensic Tools.app"
VERSION="1.0.0"

step() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }
for p in "$PY/bin/python3" "$TOOLS/bin/tesseract" "$OLLAMA_RES/ollama" "$REPO/models/manifests"; do
  [ -e "$p" ] || { echo "Manca: $p (vedi BLUEPRINT.md §3)"; exit 1; }
done

step "Struttura del bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/runtime/arm64" "$APP/Contents/Resources/app"
cp "$REPO/build/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Forensic Tools</string>
  <key>CFBundleDisplayName</key><string>Forensic Tools</string>
  <key>CFBundleIdentifier</key><string>it.forensictools.app</string>
  <key>CFBundleExecutable</key><string>Forensic Tools</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
  <key>NSHumanReadableCopyright</key><string>Forensic Tools · uso interno · 100% offline</string>
  <key>NSAppleEventsUsageDescription</key><string>Serve per convertire documenti con Microsoft Word, se installato.</string>
</dict></plist>
PLIST

step "Launcher nativo"
clang -arch arm64 -O2 -mmacosx-version-min=13.0 -o "$APP/Contents/MacOS/Forensic Tools" "$REPO/build/launcher.c"

step "Codice dell'app"
rsync -a --exclude '__pycache__' --exclude '*.pyc' \
  "$REPO/main.py" "$REPO/server" "$REPO/core" "$REPO/forensic" "$REPO/ui" "$APP/Contents/Resources/app/"

step "Runtime Python 3.11 (con librerie)"
rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude 'test/' --exclude 'tests/' \
  --exclude 'idlelib' --exclude 'tkinter' --exclude 'turtledemo' "$PY/" "$APP/Contents/Resources/runtime/arm64/python/"

step "Strumenti: Tesseract, Ghostscript, pango"
rsync -a "$TOOLS/" "$APP/Contents/Resources/runtime/arm64/tools/"

step "Motore Ollama"
mkdir -p "$APP/Contents/Resources/ollama"
rsync -a --exclude '*.png' --exclude '*.svg' --exclude '*.icns' --exclude 'Ollama' \
  "$OLLAMA_RES/" "$APP/Contents/Resources/ollama/"

step "Modelli IA (cloni APFS: nessuno spazio aggiuntivo)"
cp -cR "$REPO/models" "$APP/Contents/Resources/models"

step "Firma ad-hoc"
find "$APP/Contents/Resources" -type f \( -name '*.dylib' -o -name '*.so' \) -exec codesign -f -s - {} \; 2>/dev/null || true
codesign --force --deep -s - "$APP"
xattr -cr "$APP" 2>/dev/null || true

du -sh "$APP" | awk '{print "App pronta: " $2 " (" $1 ")"}'

if [ "${1:-}" = "--zip" ]; then
  step "Archivio zip sulla Scrivania (richiede alcuni minuti)"
  rm -f "$HOME/Desktop/Forensic_Tools.zip"
  ditto -c -k --keepParent "$APP" "$HOME/Desktop/Forensic_Tools.zip"
  du -sh "$HOME/Desktop/Forensic_Tools.zip"
fi
