#!/usr/bin/env bash
# WP-12E — unit-like shell tests for embedded scene/video frame harness
# Product path: scripts/tests/test-embedded-scene-video.sh (Plugin worktree)
#
# Catalog VERIFY: bash scripts/tests/test-embedded-scene-video.sh
# Assert exit codes + stderr failure signatures (fail-closed).
# Host-only RED/GREEN offline path; never forges device E4 PASS.
#
# Usage:
#   ./test-embedded-scene-video.sh           # run all assertions
#   ./test-embedded-scene-video.sh --help
#
# Exit codes:
#   0  all assertions passed (pass count ≥ 10 expected)
#   1  one or more assertions failed
#   2  usage / environment error
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
SCRIPTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FIXTURES_DIR="${SCRIPT_DIR}/fixtures"
VERIFY="${SCRIPTS_DIR}/verify-embedded-scene-video.sh"
ANALYZE="${SCRIPTS_DIR}/analyze-frame-nonblack.py"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME}

WP-12E embedded scene/video frame host harness (catalog RED/GREEN + fixtures).

Catalog cases:
  --case frame-negative           → exit 1, stderr BLACK_FRAME
  --case frame-positive-offline   → exit 0 (no device E4 claim)

Fixtures (schema wp12e-scene-video-e4/v1):
  - frame-black.json
  - frame-single-sample.json
  - frame-e4-pass-offline.json

Pixel analysis (analyze-frame-nonblack.py) covered via synthetic PNGs.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

[[ -f "${VERIFY}" ]] || {
  echo "ERROR: missing verifier: ${VERIFY}" >&2
  exit 2
}
[[ -f "${ANALYZE}" ]] || {
  echo "ERROR: missing analyzer: ${ANALYZE}" >&2
  exit 2
}
chmod +x "${VERIFY}" "${ANALYZE}" 2>/dev/null || true

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 required" >&2
  exit 2
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/wp12e-test.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT

PASS=0
FAIL=0
SKIP=0

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }

# assert_cmd EXPECT_RC EXPECT_STDERR_TOKEN DESCRIPTION -- command...
# EXPECT_STDERR_TOKEN may be empty or "A|B|C" (any one match).
assert_cmd() {
  local expect_rc="$1"
  local expect_token="$2"
  local desc="$3"
  shift 3
  local out_rc=0
  local stderr_file="${TMP}/stderr.${PASS}.${FAIL}.txt"
  set +e
  "$@" >"${TMP}/stdout.txt" 2>"${stderr_file}"
  out_rc=$?
  set -e
  local ok=1
  if [[ "${out_rc}" -ne "${expect_rc}" ]]; then
    log "FAIL: ${desc} (rc=${out_rc} expected ${expect_rc})"
    ok=0
  fi
  if [[ -n "${expect_token}" ]]; then
    local matched=0
    local tok
    IFS='|' read -r -a toks <<<"${expect_token}"
    for tok in "${toks[@]}"; do
      if grep -qF "${tok}" "${stderr_file}"; then
        matched=1
        break
      fi
    done
    if [[ "${matched}" -ne 1 ]]; then
      log "FAIL: ${desc} (stderr missing token ${expect_token})"
      log "----- stderr -----"
      cat "${stderr_file}" >&2 || true
      log "------------------"
      ok=0
    fi
  fi
  if [[ "${ok}" -eq 1 ]]; then
    log "PASS: ${desc}"
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
  fi
}

require_fixture() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    log "ERROR: missing fixture: ${path}"
    exit 2
  fi
}

# Write a minimal RGB PNG (8-bit) via pure python (no PIL required).
write_png() {
  local out_path="$1"
  local r="$2"
  local g="$3"
  local b="$4"
  local w="${5:-4}"
  local h="${6:-4}"
  python3 - "${out_path}" "${r}" "${g}" "${b}" "${w}" "${h}" <<'PY'
import struct, sys, zlib
from pathlib import Path

out, r, g, b, w, h = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])

def chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

raw = bytearray()
row = bytes([0]) + bytes([r, g, b] * w)  # filter 0 + RGB pixels
for _ in range(h):
    raw.extend(row)
idat = zlib.compress(bytes(raw), 9)
ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
Path(out).write_bytes(png)
PY
}

log "WORKDIR=${TMP}"
log "VERIFY=${VERIFY}"
log "ANALYZE=${ANALYZE}"
log "REPO_ROOT=${REPO_ROOT}"

BLACK_FIX="${FIXTURES_DIR}/frame-black.json"
SINGLE_FIX="${FIXTURES_DIR}/frame-single-sample.json"
PASS_OFFLINE_FIX="${FIXTURES_DIR}/frame-e4-pass-offline.json"

require_fixture "${BLACK_FIX}"
require_fixture "${SINGLE_FIX}"
require_fixture "${PASS_OFFLINE_FIX}"

# --- catalog RED / GREEN cases ---------------------------------------------
log "--- catalog cases ---"

assert_cmd 1 "BLACK_FRAME" \
  "catalog --case frame-negative → exit 1 + BLACK_FRAME" \
  bash "${VERIFY}" --case frame-negative

assert_cmd 0 "" \
  "catalog --case frame-positive-offline → exit 0 (contract dry-run)" \
  bash "${VERIFY}" --case frame-positive-offline

# Offline positive must not forge device E4 claim
set +e
bash "${VERIFY}" --case frame-positive-offline >"${TMP}/pos.out" 2>"${TMP}/pos.err"
POS_RC=$?
set -e
if [[ "${POS_RC}" -eq 0 ]] && ! grep -qE 'deviceE4Claim=true|FORGED_E4|E4_SEALED_PASS' "${TMP}/pos.err" "${TMP}/pos.out" 2>/dev/null; then
  log "PASS: offline positive does not forge device E4 claim"
  PASS=$((PASS + 1))
else
  log "FAIL: offline positive must not claim device E4 (rc=${POS_RC})"
  FAIL=$((FAIL + 1))
fi

# --- fixture inventories ----------------------------------------------------
log "--- fixture inventories ---"

assert_cmd 1 "BLACK_FRAME" \
  "fixture negative-black" \
  bash "${VERIFY}" --inventory "${BLACK_FIX}" --mode negative-black

assert_cmd 1 "SINGLE_SAMPLE" \
  "fixture negative-single-sample" \
  bash "${VERIFY}" --inventory "${SINGLE_FIX}" --mode negative-single-sample

assert_cmd 0 "" \
  "fixture positive offline pass" \
  bash "${VERIFY}" --inventory "${PASS_OFFLINE_FIX}" --mode positive

# positive mode must fail-closed on each negative fixture
assert_cmd 1 "BLACK_FRAME" \
  "black fixture fails positive mode" \
  bash "${VERIFY}" --inventory "${BLACK_FIX}" --mode positive

assert_cmd 1 "SINGLE_SAMPLE" \
  "single-sample fixture fails positive mode" \
  bash "${VERIFY}" --inventory "${SINGLE_FIX}" --mode positive

# wrong negative mode should still be non-zero
assert_cmd 1 "EXPECTED_FAILURE_NOT_FOUND" \
  "wrong negative mode surfaces EXPECTED_FAILURE_NOT_FOUND" \
  bash "${VERIFY}" --inventory "${PASS_OFFLINE_FIX}" --mode negative-black

# invalid schema
cat >"${TMP}/invalid.json" <<'JSON'
{
  "schemaVersion": "not-a-real-schema",
  "samples": {}
}
JSON
assert_cmd 2 "INVALID_INVENTORY" \
  "invalid schemaVersion → exit 2" \
  bash "${VERIFY}" --inventory "${TMP}/invalid.json" --mode positive

# forged E4 claim on dry-run must not PASS
python3 - "${PASS_OFFLINE_FIX}" "${TMP}/forged-e4.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
doc = json.loads(open(src, encoding="utf-8").read())
doc["deviceE4Claim"] = True
doc["contractDryRun"] = True
open(dst, "w", encoding="utf-8").write(json.dumps(doc, indent=2) + "\n")
PY
assert_cmd 1 "BLACK_FRAME" \
  "forged deviceE4Claim on dry-run fails closed" \
  bash "${VERIFY}" --inventory "${TMP}/forged-e4.json" --mode positive

# interval too short
python3 - "${PASS_OFFLINE_FIX}" "${TMP}/short-interval.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
doc = json.loads(open(src, encoding="utf-8").read())
doc["intervalSeconds"] = 1
doc["samples"]["scene"]["frames"][0]["capturedAt"] = "2026-08-07T12:00:00Z"
doc["samples"]["video"]["frames"][0]["capturedAt"] = "2026-08-07T12:00:01Z"
open(dst, "w", encoding="utf-8").write(json.dumps(doc, indent=2) + "\n")
PY
assert_cmd 1 "FRAME_INTERVAL_TOO_SHORT" \
  "interval < 3s fails positive mode" \
  bash "${VERIFY}" --inventory "${TMP}/short-interval.json" --mode positive

# --- analyze-frame-nonblack.py pixel path ----------------------------------
log "--- analyze-frame-nonblack.py ---"

write_png "${TMP}/black.png" 0 0 0
write_png "${TMP}/solid-red.png" 200 10 10
# non-solid: checker-like via two-tone rows is still solid if uniform per image;
# build a true multi-color PNG with noise pattern.
python3 - "${TMP}/noisy.png" <<'PY'
import struct, sys, zlib
from pathlib import Path
out = Path(sys.argv[1])
w = h = 8

def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

raw = bytearray()
for y in range(h):
    raw.append(0)
    for x in range(w):
        # vary RGB so variance is high
        raw.extend([(x * 30 + y * 17) % 256, (x * 11 + y * 41) % 256, (x * 7 + y * 53) % 256])
idat = zlib.compress(bytes(raw), 9)
ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
out.write_bytes(png)
PY

assert_cmd 1 "BLACK_FRAME" \
  "analyzer: black PNG → BLACK_FRAME" \
  python3 "${ANALYZE}" "${TMP}/black.png"

assert_cmd 1 "SOLID_COLOR" \
  "analyzer: solid red PNG → SOLID_COLOR" \
  python3 "${ANALYZE}" "${TMP}/solid-red.png"

assert_cmd 0 "" \
  "analyzer: noisy PNG → exit 0 non-black non-solid" \
  python3 "${ANALYZE}" "${TMP}/noisy.png"

assert_cmd 1 "SINGLE_SAMPLE" \
  "analyzer: single image with --require-dual → SINGLE_SAMPLE" \
  python3 "${ANALYZE}" --require-dual "${TMP}/noisy.png"

assert_cmd 0 "" \
  "analyzer: dual noisy images --require-dual → exit 0" \
  python3 "${ANALYZE}" --require-dual "${TMP}/noisy.png" "${TMP}/noisy.png"

assert_cmd 1 "BLACK_FRAME" \
  "analyzer: inventory frame-black → BLACK_FRAME" \
  python3 "${ANALYZE}" --inventory "${BLACK_FIX}" --require-dual

assert_cmd 1 "SINGLE_SAMPLE" \
  "analyzer: inventory single-sample → SINGLE_SAMPLE" \
  python3 "${ANALYZE}" --inventory "${SINGLE_FIX}" --require-dual

assert_cmd 0 "" \
  "analyzer: inventory pass-offline → exit 0" \
  python3 "${ANALYZE}" --inventory "${PASS_OFFLINE_FIX}" --require-dual

# missing frame path
assert_cmd 1 "MISSING_FRAME" \
  "analyzer: missing image path → MISSING_FRAME" \
  python3 "${ANALYZE}" "${TMP}/does-not-exist.png"

log "summary: pass=${PASS} fail=${FAIL} skip=${SKIP}"
if [[ "${PASS}" -lt 10 ]]; then
  log "FAIL: pass count ${PASS} < 10"
  exit 1
fi
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
