#!/usr/bin/env bash
# Apply official WE wallpaper on car without in-app ✓.
#
# Official path:
#   1) SharedPreferences selectedWallpaper = relative path e.g. downloads/xxx.mpkg
#   2) setWallpaperComponent(WEWallpaperService)
#   3) optional force-stop so Engine reloads prefs
#
# Usage:
#   ./we-apply-shell.sh [serial] [downloads/xxx.mpkg]
#   ./we-apply-shell.sh LD249H019625 downloads/1994794519_mobile.mpkg
#
set -euo pipefail

SER="${1:-LD249H019625}"
REL_PATH="${2:-}"
USER_ID="${3:-12}"
ADB="${ADB:-adb}"
PKG=io.wallpaperengine.weclient
SERVICE=io.wallpaperengine.weclient.WEWallpaperService
DEX_LOCAL="$(cd "$(dirname "$0")" && pwd)/setwp_user.dex"
DEX_REMOTE=/data/local/tmp/setwp_user.dex
# PreferenceManager default file for the app package
PREF_XML="/data/user/${USER_ID}/${PKG}/shared_prefs/${PKG}_preferences.xml"

if ! "$ADB" -s "$SER" get-state >/dev/null 2>&1; then
  echo "Device not ready: $SER (car offline?)" >&2
  echo "When connected, re-run with: $0 $SER downloads/your.mpkg $USER_ID" >&2
  exit 2
fi

if [[ -z "$REL_PATH" ]]; then
  echo "Usage: $0 <serial> <downloads/file.mpkg> [userId]" >&2
  echo "Example: $0 $SER downloads/1994794519_mobile.mpkg 12" >&2
  exit 1
fi

# Normalize: must be relative under WE filesDir
REL_PATH="${REL_PATH#/}"
if [[ "$REL_PATH" != downloads/* ]]; then
  # allow bare filename
  REL_PATH="downloads/$(basename "$REL_PATH")"
fi

echo "serial=$SER user=$USER_ID selectedWallpaper=$REL_PATH"

# --- 1) Write selectedWallpaper into WE default SharedPreferences ---
# Prefer root; fall back to run-as (fails if not debuggable).
write_prefs() {
  # Write PreferenceManager default XML (selectedWallpaper = relative path under filesDir).
  "$ADB" -s "$SER" shell su 0 sh -c "
    XML='$PREF_XML'
    DIR=\$(dirname \"\$XML\")
    mkdir -p \"\$DIR\"
    TMP=/data/local/tmp/we_sel_${USER_ID}.xml
    if [ -f \"\$XML\" ]; then
      grep -v selectedWallpaper \"\$XML\" > \"\$TMP\" || cp \"\$XML\" \"\$TMP\"
    else
      printf '%s\n' '<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\" ?>' '<map>' '</map>' > \"\$TMP\"
    fi
    # insert entry before closing map
    sed -i 's|</map>|  <string name=\"selectedWallpaper\">$REL_PATH</string>\n</map>|' \"\$TMP\"
    cp \"\$TMP\" \"\$XML\"
    PKG_UID=\$(stat -c %u /data/user/${USER_ID}/${PKG} 2>/dev/null || true)
    if [ -n \"\$PKG_UID\" ]; then chown \"\$PKG_UID:\$PKG_UID\" \"\$XML\"; fi
    chmod 660 \"\$XML\" 2>/dev/null || true
    echo '--- prefs head ---'
    head -30 \"\$XML\"
  "
}

if write_prefs; then
  echo "prefs: wrote selectedWallpaper via su"
else
  echo "prefs: su write failed — try after import via official ✓, or root the shell" >&2
fi

# --- 2) Bind live wallpaper component ---
if [[ -f "$DEX_LOCAL" ]]; then
  "$ADB" -s "$SER" push "$DEX_LOCAL" "$DEX_REMOTE" >/dev/null
  "$ADB" -s "$SER" shell "export CLASSPATH=$DEX_REMOTE; app_process /system/bin SetWpUser $PKG $SERVICE $USER_ID" || true
else
  echo "Missing $DEX_LOCAL — bind skipped" >&2
fi

# --- 3) Restart WE process so Engine reloads prefs (optional but reliable) ---
"$ADB" -s "$SER" shell am force-stop --user "$USER_ID" "$PKG" 2>/dev/null || true
sleep 1
# Re-bind after stop so WMS restarts service with new prefs
if [[ -f "$DEX_LOCAL" ]]; then
  "$ADB" -s "$SER" shell "export CLASSPATH=$DEX_REMOTE; app_process /system/bin SetWpUser $PKG $SERVICE $USER_ID" || true
fi

echo "--- dumpsys wallpaper (user components) ---"
"$ADB" -s "$SER" shell dumpsys wallpaper | grep -E 'User |mWallpaperComponent' | head -20 || true
echo "OK: apply attempted for $REL_PATH"
