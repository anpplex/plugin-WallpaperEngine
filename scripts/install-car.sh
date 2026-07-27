#!/usr/bin/env bash
# Install Wallpaper Engine car shell APK on Avatr/Huawei HU.
# Same PackageInstaller bypass as Motif install-motif-car.sh.
set -euo pipefail

SER="${1:-LD249H019625}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APK="${2:-$ROOT/app/build/outputs/apk/debug/app-debug.apk}"
if [[ ! -f "$APK" ]]; then
  APK="$ROOT/app/build/outputs/apk/debug/WallpaperEngine-Car-app-debug.apk"
fi
# AGP names by module
if [[ ! -f "$APK" ]]; then
  APK="$(ls "$ROOT"/app/build/outputs/apk/debug/*.apk 2>/dev/null | head -1 || true)"
fi
REMOTE=/data/local/tmp/we-car-shell.apk
PKG=com.motif.wallpaperengine
ACTIVITY=com.motif.wallpaperengine/.MainActivity
ADB="${ADB:-adb}"
INSTALLER=com.huawei.appinstaller.car
PACKAGE_INSTALLER=com.android.packageinstaller

if [[ ! -f "$APK" ]]; then
  echo "APK missing. Build: cd $ROOT && ./gradlew :app:assembleDebug" >&2
  exit 1
fi

if ! "$ADB" -s "$SER" get-state >/dev/null 2>&1; then
  echo "Device not ready: $SER" >&2
  "$ADB" devices -l >&2 || true
  exit 1
fi

cleanup() {
  "$ADB" -s "$SER" shell pm enable --user 12 "$PACKAGE_INSTALLER" >/dev/null 2>&1 || true
  "$ADB" -s "$SER" shell pm enable --user 0 "$PACKAGE_INSTALLER" >/dev/null 2>&1 || true
  "$ADB" -s "$SER" shell rm -f "$REMOTE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Push $(du -h "$APK" | awk '{print $1}') → $REMOTE"
"$ADB" -s "$SER" push "$APK" "$REMOTE"
"$ADB" -s "$SER" shell pm disable-user --user 12 "$PACKAGE_INSTALLER" || true
"$ADB" -s "$SER" shell pm disable-user --user 0 "$PACKAGE_INSTALLER" || true
"$ADB" -s "$SER" shell pm install -r -d -g -t -i "$INSTALLER" --user 12 "$REMOTE"
"$ADB" -s "$SER" shell pm install -r -d -g -t -i "$INSTALLER" --user 0 "$REMOTE" || true
"$ADB" -s "$SER" shell pm enable --user 12 "$PKG" || true
"$ADB" -s "$SER" shell am start --user 12 -n "$ACTIVITY" || true
"$ADB" -s "$SER" shell dumpsys package "$PKG" | grep -E 'versionName|versionCode' | head -6
echo "OK: $PKG"
