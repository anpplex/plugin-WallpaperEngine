#!/usr/bin/env bash
# WP-12D — unit-like shell tests for embedded runtime device harness
# Product path: scripts/tests/test-embedded-runtime-device.sh (Plugin worktree)
#
# Catalog VERIFY: bash scripts/tests/test-embedded-runtime-device.sh
# Assert exit codes + stderr failure signatures (fail-closed).
# Host-only for RED/GREEN offline path; device-positive optional skip if no adb.
#
# Usage:
#   ./test-embedded-runtime-device.sh           # run all assertions
#   ./test-embedded-runtime-device.sh --help
#
# Exit codes:
#   0  all assertions passed
#   1  one or more assertions failed
#   2  usage / environment error
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
SCRIPTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FIXTURES_DIR="${SCRIPT_DIR}/fixtures"
VERIFY="${SCRIPTS_DIR}/verify-embedded-runtime-device.sh"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME}

WP-12D embedded runtime device host harness (catalog RED/GREEN + fixtures).

Catalog cases:
  --case device-negative          → exit 1, stderr RED signature
  --case device-positive-offline  → exit 0 (no device E3 claim)

Fixtures (schema wp12d-device-e2e3/v1):
  - device-missing-serial.json
  - device-wrong-user.json
  - device-official-as-embedded-host.json
  - device-e2e3-pass-offline.json

Optional: device-positive skipped when no adb device (fail-closed, not forged PASS).
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
chmod +x "${VERIFY}" 2>/dev/null || true

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 required" >&2
  exit 2
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/wp12d-test.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT

PASS=0
FAIL=0
SKIP=0

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }

# assert_cmd EXPECT_RC EXPECT_STDERR_TOKEN DESCRIPTION -- command...
# EXPECT_STDERR_TOKEN may be empty (no token check) or "A|B|C" meaning any one match.
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

log "WORKDIR=${TMP}"
log "VERIFY=${VERIFY}"
log "REPO_ROOT=${REPO_ROOT}"

MISSING_SERIAL_FIX="${FIXTURES_DIR}/device-missing-serial.json"
WRONG_USER_FIX="${FIXTURES_DIR}/device-wrong-user.json"
OFFICIAL_HOST_FIX="${FIXTURES_DIR}/device-official-as-embedded-host.json"
PASS_OFFLINE_FIX="${FIXTURES_DIR}/device-e2e3-pass-offline.json"

require_fixture "${MISSING_SERIAL_FIX}"
require_fixture "${WRONG_USER_FIX}"
require_fixture "${OFFICIAL_HOST_FIX}"
require_fixture "${PASS_OFFLINE_FIX}"

# --- catalog RED / GREEN cases ---------------------------------------------
log "--- catalog cases (argv frozen in WP-12D phaseCommands) ---"

assert_cmd 1 "MISSING_SERIAL|WRONG_USER|OFFICIAL_AS_EMBEDDED_HOST|DEVICE_OFFLINE|MISSING_APK" \
  "catalog --case device-negative → exit 1 + RED signature" \
  bash "${VERIFY}" --case device-negative

assert_cmd 0 "" \
  "catalog --case device-positive-offline → exit 0 (contract dry-run)" \
  bash "${VERIFY}" --case device-positive-offline

# Ensure offline positive does not claim device E3 on stderr/stdout
set +e
bash "${VERIFY}" --case device-positive-offline >"${TMP}/pos.out" 2>"${TMP}/pos.err"
POS_RC=$?
set -e
if [[ "${POS_RC}" -eq 0 ]] && ! grep -qiE 'device E3 claim|deviceE3Claim=true|E3_PASS|forged' "${TMP}/pos.err" "${TMP}/pos.out" 2>/dev/null; then
  # Positive: logs may mention "no device E3 claim" — that is fine; forbid forged pass markers.
  if grep -qE 'deviceE3Claim=true|FORGED_E3|E3_SEALED_PASS' "${TMP}/pos.err" "${TMP}/pos.out" 2>/dev/null; then
    log "FAIL: offline positive must not claim device E3"
    FAIL=$((FAIL + 1))
  else
    log "PASS: offline positive does not forge device E3 claim"
    PASS=$((PASS + 1))
  fi
else
  if [[ "${POS_RC}" -ne 0 ]]; then
    log "FAIL: offline positive re-check rc=${POS_RC}"
    FAIL=$((FAIL + 1))
  else
    log "PASS: offline positive does not forge device E3 claim"
    PASS=$((PASS + 1))
  fi
fi

# --- fixture inventories ----------------------------------------------------
log "--- fixture inventories ---"

assert_cmd 1 "MISSING_SERIAL" \
  "fixture negative-missing-serial" \
  bash "${VERIFY}" --inventory "${MISSING_SERIAL_FIX}" --mode negative-missing-serial

assert_cmd 1 "WRONG_USER" \
  "fixture negative-wrong-user" \
  bash "${VERIFY}" --inventory "${WRONG_USER_FIX}" --mode negative-wrong-user

assert_cmd 1 "OFFICIAL_AS_EMBEDDED_HOST" \
  "fixture negative-official-as-embedded-host" \
  bash "${VERIFY}" --inventory "${OFFICIAL_HOST_FIX}" --mode negative-official-as-embedded-host

assert_cmd 0 "" \
  "fixture positive offline pass" \
  bash "${VERIFY}" --inventory "${PASS_OFFLINE_FIX}" --mode positive

# positive mode must fail-closed on each negative fixture
assert_cmd 1 "MISSING_SERIAL" \
  "missing-serial fails positive mode" \
  bash "${VERIFY}" --inventory "${MISSING_SERIAL_FIX}" --mode positive

assert_cmd 1 "WRONG_USER" \
  "wrong-user fails positive mode" \
  bash "${VERIFY}" --inventory "${WRONG_USER_FIX}" --mode positive

assert_cmd 1 "OFFICIAL_AS_EMBEDDED_HOST" \
  "official-as-embedded-host fails positive mode" \
  bash "${VERIFY}" --inventory "${OFFICIAL_HOST_FIX}" --mode positive

# wrong negative mode should still be non-zero
assert_cmd 1 "EXPECTED_FAILURE_NOT_FOUND" \
  "wrong negative mode surfaces EXPECTED_FAILURE_NOT_FOUND" \
  bash "${VERIFY}" --inventory "${PASS_OFFLINE_FIX}" --mode negative-missing-serial

# invalid schema
cat >"${TMP}/invalid.json" <<'JSON'
{
  "schemaVersion": "not-a-real-schema",
  "packageIdentities": {}
}
JSON
assert_cmd 2 "INVALID_INVENTORY" \
  "invalid schemaVersion → exit 2" \
  bash "${VERIFY}" --inventory "${TMP}/invalid.json" --mode positive

# forged E3 claim on dry-run must not PASS
cat >"${TMP}/forged-e3.json" <<'JSON'
{
  "schemaVersion": "wp12d-device-e2e3/v1",
  "serial": "SYNTHETIC_FORGED_E3",
  "targetUser": 12,
  "observedUser": 12,
  "deviceOnline": false,
  "contractDryRun": true,
  "deviceE3Claim": true,
  "apkPresent": {"mineradio": true, "plugin": true, "officialWe": true},
  "packageIdentities": {
    "mineradio": "com.mineradio.app",
    "plugin": "com.motif.wallpaperengine",
    "officialWe": "io.wallpaperengine.weclient",
    "embeddedHost": "com.motif.wallpaperengine"
  },
  "signatures": {
    "mineradio": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "plugin": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "officialWe": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "pluginPid": 7777,
  "surface": {"present": true, "ownerPid": 7777, "name": "EmbeddedPreview"},
  "realCaller": {
    "package": "com.mineradio.app",
    "uid": 1012345,
    "isShell": false,
    "isMineradio": true
  },
  "officialNotEmbeddedHost": true,
  "failClosed": {"ok": true, "failures": []}
}
JSON
assert_cmd 1 "DEVICE_OFFLINE" \
  "forged deviceE3Claim on dry-run fails closed" \
  bash "${VERIFY}" --inventory "${TMP}/forged-e3.json" --mode positive

# --- optional device-positive (live collect + verify; skip if no adb) -------
log "--- device-positive (optional; gated on adb + env) ---"

# Always assert fail-closed when SERIAL unset
assert_cmd 1 "MISSING_SERIAL|MISSING_APK|DEVICE_OFFLINE" \
  "device-positive without env → non-zero fail-closed" \
  env -u SERIAL -u TARGET_USER -u MINERADIO_APK -u PLUGIN_APK -u OFFICIAL_WE_APK \
    bash "${VERIFY}" --case device-positive

has_device=0
if command -v adb >/dev/null 2>&1; then
  if adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {found=1} END{exit !found}'; then
    has_device=1
  fi
fi

if [[ "${has_device}" -eq 0 ]]; then
  log "SKIP: no adb device online — device-positive live path not run"
  SKIP=$((SKIP + 1))
elif [[ -n "${SERIAL:-}" && -n "${TARGET_USER:-}" \
    && -n "${MINERADIO_APK:-}" && -n "${PLUGIN_APK:-}" && -n "${OFFICIAL_WE_APK:-}" ]]; then
  # Full env + online device: live collect must pass hard checks (exit 0).
  assert_cmd 0 "" \
    "device-positive with env + online device → exit 0 (live hard checks green)" \
    bash "${VERIFY}" --case device-positive
else
  log "NOTE: adb device present but SERIAL/TARGET_USER/APK env incomplete — expect fail-closed"
  assert_cmd 1 "MISSING_SERIAL|MISSING_APK|DEVICE_OFFLINE|WRONG_USER" \
    "device-positive partial env → non-zero fail-closed" \
    bash "${VERIFY}" --case device-positive
fi

log "summary: pass=${PASS} fail=${FAIL} skip=${SKIP}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
