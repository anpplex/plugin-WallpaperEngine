#!/usr/bin/env bash
# Watch ADB: when car comes online, re-bind official WE live wallpaper.
# Counters CB-FAIL (reboot steals wallpaper back to Motif/OEM).
#
# Usage:
#   bash scripts/watch-we-adb.sh [serial] [user]
#   nohup bash scripts/watch-we-adb.sh LD249H019625 12 &
set -uo pipefail

SER="${1:-LD249H019625}"
USER_ID="${2:-12}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
ADB="${ADB:-adb}"
LOG_DIR="${WE_CAR_LOG_DIR:-$HOME/Library/Logs/we-car}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/watch.log"
COOLDOWN_SEC="${WE_CAR_COOLDOWN:-90}"
LAST_OK=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "watch-we start serial=$SER user=$USER_ID cooldown=${COOLDOWN_SEC}s"
"$ADB" start-server >/dev/null 2>&1 || true

was_online=0
while true; do
  if "$ADB" -s "$SER" get-state 2>/dev/null | grep -qx device; then
    if (( was_online == 0 )); then
      now=$(date +%s)
      if (( now - LAST_OK >= COOLDOWN_SEC )); then
        log "device online → we-boot-rebind"
        # Wait for boot settle (WMS ready)
        sleep "${WE_CAR_SETTLE:-15}"
        if bash "$ROOT/we-boot-rebind.sh" "$SER" "$USER_ID" >>"$LOG" 2>&1; then
          LAST_OK=$now
          log "rebind success"
        else
          log "rebind failed (exit $?)"
        fi
      else
        log "online but cooldown ($((COOLDOWN_SEC - (now - LAST_OK)))s left)"
      fi
      was_online=1
    fi
  else
    if (( was_online == 1 )); then
      log "device offline"
    fi
    was_online=0
  fi
  sleep 3
done
