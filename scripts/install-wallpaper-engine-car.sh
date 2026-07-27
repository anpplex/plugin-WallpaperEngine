#!/usr/bin/env bash
# Compatibility wrapper (Motif name) → install-car.sh
exec "$(cd "$(dirname "$0")" && pwd)/install-car.sh" "$@"
