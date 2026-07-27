#!/usr/bin/env bash
# Install LaunchAgent: Mac login → watch car ADB → re-bind WE on online.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SER="${1:-LD249H019625}"
USER_ID="${2:-12}"
LOG_DIR="${WE_CAR_LOG_DIR:-$HOME/Library/Logs/we-car}"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LABEL=com.wallpaperengine.car.adb-watch
PLIST="$LAUNCH_DIR/$LABEL.plist"
WATCH="$ROOT/watch-we-adb.sh"

mkdir -p "$LOG_DIR" "$LAUNCH_DIR"
chmod +x "$ROOT/watch-we-adb.sh" "$ROOT/we-boot-rebind.sh" "$ROOT/we-bind-only.sh" \
  "$ROOT/we-apply-shell.sh" "$ROOT/install-mac-we-watch.sh"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${WATCH}</string>
    <string>${SER}</string>
    <string>${USER_ID}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd-stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd-stderr.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>WE_CAR_LOG_DIR</key>
    <string>${LOG_DIR}</string>
  </dict>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl enable "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_NUM/$LABEL" 2>/dev/null || true

echo "Installed LaunchAgent: $PLIST"
echo "  serial=$SER user=$USER_ID"
echo "  logs: $LOG_DIR/"
echo
echo "Uninstall:"
echo "  launchctl bootout gui/\$(id -u)/$LABEL"
echo "  rm -f $PLIST"
