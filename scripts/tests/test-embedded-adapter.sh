#!/usr/bin/env bash
# WP-12C — unit-like shell tests for embedded adapter contract harness
# Product path: scripts/tests/test-embedded-adapter.sh (Plugin worktree)
#
# Catalog VERIFY: bash scripts/tests/test-embedded-adapter.sh
# Assert exit codes + stderr failure signatures (fail-closed).
# Host-only — no device / full APK required.
#
# Usage:
#   ./test-embedded-adapter.sh           # run all assertions
#   ./test-embedded-adapter.sh --help
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
VERIFY="${SCRIPTS_DIR}/verify-embedded-adapter.sh"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME}

WP-12C embedded adapter host harness (catalog RED/GREEN cases + outline).

Catalog cases:
  --case adapter-negative  → exit 1, stderr UNKNOWN_METHOD
  --case adapter-positive  → exit 0

Outline inventories (inline TMP, schema wp12c-adapter-contract/v1):
  - positive official default + embedded experimental
  - negative UNKNOWN_METHOD / CALLER_APPENDED_ARGS / FALLBACK_MASQUERADE
  - positive mode fails closed on each negative fixture
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

TMP="$(mktemp -d "${TMPDIR:-/tmp}/wp12c-test.XXXXXX")"
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
    # Support alternation: TOK_A|TOK_B
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

write_unknown_method() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "launch_embedded_secret",
  "keys": ["protocolVersion", "callId"],
  "embeddedExperimental": true,
  "selectedRuntime": "embedded",
  "fallbackFromEmbedded": false,
  "passClaim": "embedded",
  "ok": false,
  "failClosed": {
    "ok": false,
    "failures": [
      {"code": "UNKNOWN_METHOD", "message": "method not in Protocol-1 allowlist"}
    ]
  }
}
JSON
}

write_appended_args() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "ping",
  "keys": ["protocolVersion", "callId", "x_caller_debug_hook", "extraPayload"],
  "embeddedExperimental": false,
  "selectedRuntime": "official",
  "fallbackFromEmbedded": false,
  "passClaim": "official",
  "ok": false,
  "failClosed": {
    "ok": false,
    "failures": [
      {"code": "CALLER_APPENDED_ARGS", "message": "caller appended non-contract keys"}
    ]
  }
}
JSON
}

write_fallback_masquerade() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "ping",
  "keys": ["protocolVersion", "callId"],
  "embeddedExperimental": false,
  "selectedRuntime": "official",
  "fallbackFromEmbedded": true,
  "passClaim": "embedded",
  "ok": true,
  "failClosed": {
    "ok": false,
    "failures": [
      {
        "code": "FALLBACK_MASQUERADE",
        "message": "fallback path claims embedded PASS"
      }
    ]
  }
}
JSON
}

write_positive_official() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "status",
  "keys": ["protocolVersion", "callId", "operationId"],
  "embeddedExperimental": false,
  "selectedRuntime": "official",
  "fallbackFromEmbedded": false,
  "passClaim": "official",
  "ok": true,
  "failClosed": {"ok": true, "failures": []}
}
JSON
}

write_positive_embedded() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "apply_current",
  "keys": ["protocolVersion", "callId", "operationId"],
  "embeddedExperimental": true,
  "selectedRuntime": "embedded",
  "fallbackFromEmbedded": false,
  "passClaim": "embedded",
  "ok": true,
  "failClosed": {"ok": true, "failures": []}
}
JSON
}

write_invalid_schema() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "not-a-real-schema",
  "method": "ping"
}
JSON
}

log "WORKDIR=${TMP}"
log "VERIFY=${VERIFY}"
log "REPO_ROOT=${REPO_ROOT}"

# --- catalog RED / GREEN cases ---------------------------------------------
log "--- catalog cases (argv frozen in WP-12C phaseCommands) ---"

assert_cmd 1 "UNKNOWN_METHOD|CALLER_APPENDED_ARGS|FALLBACK_MASQUERADE" \
  "catalog --case adapter-negative → exit 1 + RED signature" \
  bash "${VERIFY}" --case adapter-negative

assert_cmd 0 "" \
  "catalog --case adapter-positive → exit 0" \
  bash "${VERIFY}" --case adapter-positive

# --- outline inventories ----------------------------------------------------
log "--- outline contract inventories ---"

UNK="${TMP}/unknown-method.json"
APP="${TMP}/appended-args.json"
MASQ="${TMP}/fallback-masquerade.json"
POS_OFF="${TMP}/positive-official.json"
POS_EMB="${TMP}/positive-embedded.json"
BAD="${TMP}/invalid.json"

write_unknown_method "${UNK}"
write_appended_args "${APP}"
write_fallback_masquerade "${MASQ}"
write_positive_official "${POS_OFF}"
write_positive_embedded "${POS_EMB}"
write_invalid_schema "${BAD}"

assert_cmd 1 "UNKNOWN_METHOD" \
  "outline negative-unknown-method" \
  bash "${VERIFY}" --inventory "${UNK}" --mode negative-unknown-method

assert_cmd 1 "CALLER_APPENDED_ARGS" \
  "outline negative-appended-args" \
  bash "${VERIFY}" --inventory "${APP}" --mode negative-appended-args

assert_cmd 1 "FALLBACK_MASQUERADE" \
  "outline negative-fallback-masquerade" \
  bash "${VERIFY}" --inventory "${MASQ}" --mode negative-fallback-masquerade

assert_cmd 0 "" \
  "outline positive official default (experimental off)" \
  bash "${VERIFY}" --inventory "${POS_OFF}" --mode positive

assert_cmd 0 "" \
  "outline positive embedded (experimental on)" \
  bash "${VERIFY}" --inventory "${POS_EMB}" --mode positive

# positive mode must fail-closed on each negative fixture
assert_cmd 1 "UNKNOWN_METHOD" \
  "outline unknown-method fails positive mode" \
  bash "${VERIFY}" --inventory "${UNK}" --mode positive

assert_cmd 1 "CALLER_APPENDED_ARGS" \
  "outline appended-args fails positive mode" \
  bash "${VERIFY}" --inventory "${APP}" --mode positive

assert_cmd 1 "FALLBACK_MASQUERADE" \
  "outline fallback-masquerade fails positive mode" \
  bash "${VERIFY}" --inventory "${MASQ}" --mode positive

assert_cmd 2 "INVALID_INVENTORY" \
  "outline invalid schemaVersion → exit 2" \
  bash "${VERIFY}" --inventory "${BAD}" --mode positive

# wrong negative mode should still be non-zero (EXPECTED_FAILURE_NOT_FOUND)
assert_cmd 1 "EXPECTED_FAILURE_NOT_FOUND" \
  "outline wrong negative mode surfaces EXPECTED_FAILURE_NOT_FOUND" \
  bash "${VERIFY}" --inventory "${POS_OFF}" --mode negative-unknown-method

# Optional: if Kotlin adapter sources land, note presence (do not require — harness-only PR)
ADAPTER_KT="${REPO_ROOT}/app/src/main/java/com/motif/wallpaperengine/plugin/EmbeddedEngineAdapter.kt"
if [[ -f "${ADAPTER_KT}" ]]; then
  log "NOTE: EmbeddedEngineAdapter.kt present — host harness remains fixture-based for RED exit 1"
  SKIP=$((SKIP + 0))
else
  log "SKIP: EmbeddedEngineAdapter.kt not present yet (host harness independent of Kotlin agent)"
  SKIP=$((SKIP + 1))
fi

log "summary: pass=${PASS} fail=${FAIL} skip=${SKIP}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
