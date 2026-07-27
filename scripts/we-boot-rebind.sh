#!/usr/bin/env bash
# Re-bind official WE after car reboot (counter CB-FAIL).
# Same as bind-only; call from Mac LaunchAgent when adb device appears,
# or from car shell at boot if available.
#
# Usage: ./we-boot-rebind.sh [serial] [userId]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/we-bind-only.sh" "${1:-LD249H019625}" "${2:-12}"
