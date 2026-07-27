#!/usr/bin/env bash
# Only bind official WE live wallpaper component (no prefs write).
# Use when user already tapped official ✓ (prefs may already have selectedWallpaper)
# or when su is unavailable for prefs XML.
#
# Usage: ./we-bind-only.sh [serial] [userId]
set -euo pipefail

SER="${1:-LD249H019625}"
USER_ID="${2:-12}"
ADB="${ADB:-adb}"
PKG=io.wallpaperengine.weclient
SERVICE=io.wallpaperengine.weclient.WEWallpaperService
ROOT="$(cd "$(dirname "$0")" && pwd)"
DEX_LOCAL="$ROOT/setwp_user.dex"
DEX_REMOTE=/data/local/tmp/setwp_user.dex

if ! "$ADB" -s "$SER" get-state >/dev/null 2>&1; then
  echo "Device not ready: $SER" >&2
  exit 2
fi

if [[ ! -f "$DEX_LOCAL" ]]; then
  echo "Missing $DEX_LOCAL" >&2
  exit 1
fi

"$ADB" -s "$SER" push "$DEX_LOCAL" "$DEX_REMOTE" >/dev/null
echo "Binding $PKG/$SERVICE user=$USER_ID …"
"$ADB" -s "$SER" shell "export CLASSPATH=$DEX_REMOTE; app_process /system/bin SetWpUser $PKG $SERVICE $USER_ID"

echo "--- dumpsys wallpaper ---"
"$ADB" -s "$SER" shell dumpsys wallpaper | grep -E 'User |mWallpaperComponent' | head -20 || true
echo "OK: bind-only done"
