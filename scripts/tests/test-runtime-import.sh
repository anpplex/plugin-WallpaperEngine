#!/usr/bin/env bash
# WP-12A — unit-like shell tests for runtime import/verify
# Product path: scripts/tests/test-runtime-import.sh (Plugin worktree)
#
# Scaffolded from verification runs/wp-12a-draft outline harness.
#
# Intent:
#   - Exercise verify-imported-runtime.sh modes against tiny JSON fixtures
#     (inline under $TMP, not catalog basenames yet).
#   - Assert exit codes + stderr failure signatures (fail-closed).
#   - Optional smoke: import-official-runtime.sh → verify --mode positive
#     when OFFICIAL_WE_APK or wp-12a-assets/base.apk is present.
#
# Usage:
#   ./test-runtime-import.sh           # run outline tests
#   ./test-runtime-import.sh --help
#
# Exit codes:
#   0  all outline assertions passed
#   1  one or more assertions failed
#   2  usage / environment error
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
# Layout: scripts/tests/this → scripts/{import,verify}-*.sh ; repo root two levels up
SCRIPTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VERIFY="${SCRIPTS_DIR}/verify-imported-runtime.sh"
IMPORT="${SCRIPTS_DIR}/import-official-runtime.sh"
SCHEMA="${REPO_ROOT}/runtime-import/manifest-map.schema.json"
# Optional APK: OFFICIAL_WE_APK preferred; else local verification assets (host-only)
ASSETS_APK="${REPO_ROOT}/work/runtime/base.apk"
if [[ ! -f "${ASSETS_APK}" ]]; then
  ASSETS_APK="/Users/anpple/Codex/Mineradio/android-car/verification/wallpaper-plugin/runs/wp-12a-assets/base.apk"
fi

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME}

Minimal unit-like outline for WP-12A import/verify (worktree scaffold).

Assertions (outline):
  1. positive + minimal clean inventory            → exit 0
  2. negative-missing-dex + empty dexFiles         → exit 1, stderr MISSING_DEX
  3. negative-auth-conflict + duplicate authority  → exit 1, stderr AUTHORITY_CONFLICT
  4. positive + empty dexFiles                     → exit 1, stderr MISSING_DEX
  5. invalid inventory (missing fields)            → exit 2
  6. (optional) real APK import → positive verify  → exit 0

Does not yet wire catalog fixture basenames from FIXTURES.md; those land
in the Plugin worktree RED harness.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

[[ -x "${VERIFY}" || -f "${VERIFY}" ]] || {
  echo "ERROR: missing verifier: ${VERIFY}" >&2
  exit 2
}
chmod +x "${VERIFY}" 2>/dev/null || true
chmod +x "${IMPORT}" 2>/dev/null || true

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 required" >&2
  exit 2
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/wp12a-test.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT

PASS=0
FAIL=0
SKIP=0

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }

# assert_cmd EXPECT_RC EXPECT_STDERR_TOKEN DESCRIPTION -- command...
assert_cmd() {
  local expect_rc="$1"
  local expect_token="$2"
  local desc="$3"
  shift 3
  # remaining: command
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
    if ! grep -qF "${expect_token}" "${stderr_file}"; then
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

# --- fixture writers --------------------------------------------------------
write_clean_draft() {
  # Minimal draft-1 inventory that should pass positive mode.
  # authorities unique; dexFiles non-empty with classes.dex.
  cat >"$1" <<'JSON'
{
  "packageName": "io.wallpaperengine.weclient",
  "versionName": "0.0.0-test",
  "permissions": ["android.permission.INTERNET"],
  "activities": ["io.wallpaperengine.weclient.BrowseActivity"],
  "services": ["io.wallpaperengine.weclient.WEWallpaperService"],
  "providers": ["androidx.core.content.FileProvider"],
  "receivers": [],
  "dexFiles": ["classes.dex"],
  "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "authorities": [
    {"authority": "io.wallpaperengine.weclient.fileprovider", "componentName": "androidx.core.content.FileProvider"}
  ],
  "schema": "wp-12a-import-inventory/draft-1"
}
JSON
}

write_missing_dex() {
  cat >"$1" <<'JSON'
{
  "packageName": "io.wallpaperengine.weclient",
  "versionName": "0.0.0-test",
  "permissions": [],
  "activities": [],
  "services": [],
  "providers": [],
  "receivers": [],
  "dexFiles": [],
  "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "authorities": [
    {"authority": "io.wallpaperengine.weclient.fileprovider", "componentName": "androidx.core.content.FileProvider"}
  ]
}
JSON
}

write_auth_conflict() {
  cat >"$1" <<'JSON'
{
  "packageName": "io.wallpaperengine.weclient",
  "versionName": "0.0.0-test",
  "permissions": [],
  "activities": [],
  "services": [],
  "providers": [
    "androidx.core.content.FileProvider",
    "com.example.DupProvider"
  ],
  "receivers": [],
  "dexFiles": ["classes.dex"],
  "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "authorities": [
    {"authority": "io.wallpaperengine.weclient.fileprovider", "componentName": "androidx.core.content.FileProvider"},
    {"authority": "io.wallpaperengine.weclient.fileprovider", "componentName": "com.example.DupProvider"}
  ]
}
JSON
}

write_invalid_missing_fields() {
  cat >"$1" <<'JSON'
{
  "packageName": "io.wallpaperengine.weclient"
}
JSON
}

# --- outline cases ----------------------------------------------------------
log "WORKDIR=${TMP}"

CLEAN="${TMP}/clean.json"
MISS="${TMP}/missing-dex.json"
AUTH="${TMP}/auth-conflict.json"
BAD="${TMP}/invalid.json"

write_clean_draft "${CLEAN}"
write_missing_dex "${MISS}"
write_auth_conflict "${AUTH}"
write_invalid_missing_fields "${BAD}"

assert_cmd 0 "" \
  "positive clean inventory exits 0" \
  bash "${VERIFY}" --inventory "${CLEAN}" --mode positive

assert_cmd 1 "MISSING_DEX" \
  "negative-missing-dex empty dexFiles" \
  bash "${VERIFY}" --inventory "${MISS}" --mode negative-missing-dex

assert_cmd 1 "AUTHORITY_CONFLICT" \
  "negative-auth-conflict duplicate authorities" \
  bash "${VERIFY}" --inventory "${AUTH}" --mode negative-auth-conflict

assert_cmd 1 "MISSING_DEX" \
  "positive mode fail-closed on empty dexFiles" \
  bash "${VERIFY}" --inventory "${MISS}" --mode positive

assert_cmd 2 "INVALID_INVENTORY" \
  "missing required fields → exit 2" \
  bash "${VERIFY}" --inventory "${BAD}" --mode positive

# Outline placeholders for remaining fixture classes (schema-shaped).
# Uncomment / flesh out when RED fixtures land under runtime-import/.
#
# write_unknown_sig / write_resource_conflict →
#   assert_cmd 1 UNKNOWN_SIGNATURE_PERMISSION ...
#   assert_cmd 1 RESOURCE_ID_CONFLICT ...

# --- optional APK smoke -----------------------------------------------------
APK_PATH="${OFFICIAL_WE_APK:-}"
if [[ -z "${APK_PATH}" && -f "${ASSETS_APK}" ]]; then
  APK_PATH="${ASSETS_APK}"
fi

if [[ -n "${APK_PATH}" && -f "${APK_PATH}" && -f "${IMPORT}" ]]; then
  SMOKE_OUT="${TMP}/import-out"
  mkdir -p "${SMOKE_OUT}"
  set +e
  bash "${IMPORT}" --apk "${APK_PATH}" --out "${SMOKE_OUT}" \
    >"${TMP}/import-stdout.txt" 2>"${TMP}/import-stderr.txt"
  imp_rc=$?
  set -e
  if [[ "${imp_rc}" -ne 0 ]]; then
    log "SKIP: import-official-runtime failed (rc=${imp_rc}); optional smoke"
    SKIP=$((SKIP + 1))
  elif [[ ! -f "${SMOKE_OUT}/inventory.json" ]]; then
    log "SKIP: import produced no inventory.json"
    SKIP=$((SKIP + 1))
  else
    assert_cmd 0 "" \
      "optional: imported real APK inventory passes positive" \
      bash "${VERIFY}" --inventory "${SMOKE_OUT}/inventory.json" --mode positive
  fi
else
  log "SKIP: no OFFICIAL_WE_APK / assets base.apk for import smoke"
  SKIP=$((SKIP + 1))
fi

log "summary: pass=${PASS} fail=${FAIL} skip=${SKIP}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
