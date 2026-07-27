#!/usr/bin/env bash
# Rebuild patched official WE from Motif sandbox apktool-out (or WE_APKTOOL_OUT)
# and install on car. Requires JAVA_HOME, apktool, Android build-tools.
set -euo pipefail

SER="${1:-LD249H019625}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Default: Motif monorepo sandbox (where full decompile lives)
APKTOOL_OUT="${WE_APKTOOL_OUT:-$HOME/Codex/Motif/sandbox/we-android/apktool-out}"
OUT_DIR="${WE_PATCH_OUT:-$ROOT/we-official/dist}"
BT="${ANDROID_BUILD_TOOLS:-$HOME/Library/Android/sdk/build-tools/35.0.0}"
KS="${WE_DEBUG_KEYSTORE:-$HOME/.android/debug.keystore}"
ADB="${ADB:-adb}"
INSTALLER=com.huawei.appinstaller.car
PKG=io.wallpaperengine.weclient

if [[ ! -d "$APKTOOL_OUT" ]]; then
  echo "Missing apktool-out: $APKTOOL_OUT" >&2
  echo "Set WE_APKTOOL_OUT= or decompile official APK first." >&2
  exit 1
fi

export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}"
export PATH="$JAVA_HOME/bin:$PATH"

mkdir -p "$OUT_DIR"
UNSIGNED="$OUT_DIR/we-car-unsigned.apk"
ALIGNED="$OUT_DIR/we-car-aligned.apk"
SIGNED="$OUT_DIR/we-car-patched.apk"

echo "apktool b $APKTOOL_OUT → $UNSIGNED"
apktool b -f -o "$UNSIGNED" "$APKTOOL_OUT"

echo "zipalign + apksigner"
"$BT/zipalign" -f -p 4 "$UNSIGNED" "$ALIGNED"
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$SIGNED" "$ALIGNED"
"$BT/apksigner" verify "$SIGNED" >/dev/null

echo "Install on $SER (uninstall first if signature changed)"
REMOTE=/data/local/tmp/we-car-patched.apk
"$ADB" -s "$SER" push "$SIGNED" "$REMOTE"
"$ADB" -s "$SER" shell pm uninstall --user 12 "$PKG" 2>/dev/null || true
"$ADB" -s "$SER" shell pm uninstall --user 0 "$PKG" 2>/dev/null || true
"$ADB" -s "$SER" shell pm disable-user --user 12 com.android.packageinstaller || true
"$ADB" -s "$SER" shell pm disable-user --user 0 com.android.packageinstaller || true
"$ADB" -s "$SER" shell pm install -r -d -g -t -i "$INSTALLER" --user 12 "$REMOTE"
"$ADB" -s "$SER" shell pm install -r -d -g -t -i "$INSTALLER" --user 0 "$REMOTE" || true
"$ADB" -s "$SER" shell pm enable --user 12 com.android.packageinstaller || true
"$ADB" -s "$SER" shell pm enable --user 0 com.android.packageinstaller || true
"$ADB" -s "$SER" shell pm path --user 12 "$PKG"
echo "OK: patched WE installed. Re-bind wallpaper:"
echo "  $ROOT/scripts/we-bind-only.sh $SER 12"
