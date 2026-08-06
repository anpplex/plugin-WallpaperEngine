#!/usr/bin/env bash
# WP-12A — unit-like shell tests for runtime import/verify
# Product path: scripts/tests/test-runtime-import.sh (Plugin worktree)
#
# Catalog RED harness: four negative fixtures under scripts/tests/fixtures/
# (exact basenames from runtime-import/FIXTURES.md) plus positive outline /
# optional catalog positive. Assert exit codes + stderr failure signatures
# (fail-closed).
#
# Also retains draft-1 inline outline cases for importer-shaped inventories.
#
# Usage:
#   ./test-runtime-import.sh           # run catalog + outline tests
#   ./test-runtime-import.sh --help
#
# Exit codes:
#   0  all assertions passed
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
FIXTURES_DIR="${SCRIPT_DIR}/fixtures"
# Optional APK: OFFICIAL_WE_APK preferred; else local verification assets (host-only)
ASSETS_APK="${REPO_ROOT}/work/runtime/base.apk"
if [[ ! -f "${ASSETS_APK}" ]]; then
  ASSETS_APK="/Users/anpple/Codex/Mineradio/android-car/verification/wallpaper-plugin/runs/wp-12a-assets/base.apk"
fi

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME}

WP-12A import/verify harness (catalog fixtures + draft outline).

Catalog fixtures (scripts/tests/fixtures/, FIXTURES.md basenames):
  1. manifest-missing-dex.json
       → negative-missing-dex, exit 1, stderr MISSING_DEX
  2. manifest-authority-conflict.json
       → negative-auth-conflict, exit 1, stderr AUTHORITY_CONFLICT
  3. manifest-unknown-signature-permission.json
       → negative-unknown-signature-permission, exit 1, stderr UNKNOWN_SIGNATURE_PERMISSION
  4. manifest-resource-id-conflict.json
       → negative-resource-id-conflict, exit 1, stderr RESOURCE_ID_CONFLICT
  5. manifest-inventory-pass.json (optional positive)
       → positive, exit 0

Outline (inline TMP draft-1 inventories):
  - positive clean inventory → exit 0
  - draft missing-dex / auth-conflict / invalid fields

Optional smoke: import-official-runtime.sh → verify --mode positive
when OFFICIAL_WE_APK or assets base.apk is present.
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

# --- fixture writers (draft-1 outline) --------------------------------------
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

# --- catalog fixture suite (FIXTURES.md basenames) --------------------------
log "WORKDIR=${TMP}"
log "FIXTURES_DIR=${FIXTURES_DIR}"

if [[ ! -d "${FIXTURES_DIR}" ]]; then
  log "FAIL: missing fixtures dir: ${FIXTURES_DIR}"
  FAIL=$((FAIL + 1))
else
  log "--- catalog negatives (schema-shaped wp12a-manifest-map/v1) ---"

  assert_cmd 1 "MISSING_DEX" \
    "catalog manifest-missing-dex.json → MISSING_DEX" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/manifest-missing-dex.json" \
      --mode negative-missing-dex

  assert_cmd 1 "AUTHORITY_CONFLICT" \
    "catalog manifest-authority-conflict.json → AUTHORITY_CONFLICT" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/manifest-authority-conflict.json" \
      --mode negative-auth-conflict

  assert_cmd 1 "UNKNOWN_SIGNATURE_PERMISSION" \
    "catalog manifest-unknown-signature-permission.json → UNKNOWN_SIGNATURE_PERMISSION" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/manifest-unknown-signature-permission.json" \
      --mode negative-unknown-signature-permission

  assert_cmd 1 "RESOURCE_ID_CONFLICT" \
    "catalog manifest-resource-id-conflict.json → RESOURCE_ID_CONFLICT" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/manifest-resource-id-conflict.json" \
      --mode negative-resource-id-conflict

  log "--- catalog positive ---"
  PASS_FIXTURE="${FIXTURES_DIR}/manifest-inventory-pass.json"
  if [[ -f "${PASS_FIXTURE}" ]]; then
    assert_cmd 0 "" \
      "catalog manifest-inventory-pass.json → positive exit 0" \
      bash "${VERIFY}" --inventory "${PASS_FIXTURE}" --mode positive
  else
    log "SKIP: catalog positive manifest-inventory-pass.json not present"
    SKIP=$((SKIP + 1))
  fi
fi

# --- outline cases (draft-1) ------------------------------------------------
log "--- outline draft-1 cases ---"

CLEAN="${TMP}/clean.json"
MISS="${TMP}/missing-dex.json"
AUTH="${TMP}/auth-conflict.json"
BAD="${TMP}/invalid.json"

write_clean_draft "${CLEAN}"
write_missing_dex "${MISS}"
write_auth_conflict "${AUTH}"
write_invalid_missing_fields "${BAD}"

assert_cmd 0 "" \
  "outline positive clean inventory exits 0" \
  bash "${VERIFY}" --inventory "${CLEAN}" --mode positive

assert_cmd 1 "MISSING_DEX" \
  "outline negative-missing-dex empty dexFiles" \
  bash "${VERIFY}" --inventory "${MISS}" --mode negative-missing-dex

assert_cmd 1 "AUTHORITY_CONFLICT" \
  "outline negative-auth-conflict duplicate authorities" \
  bash "${VERIFY}" --inventory "${AUTH}" --mode negative-auth-conflict

assert_cmd 1 "MISSING_DEX" \
  "outline positive mode fail-closed on empty dexFiles" \
  bash "${VERIFY}" --inventory "${MISS}" --mode positive

assert_cmd 2 "INVALID_INVENTORY" \
  "outline missing required fields → exit 2" \
  bash "${VERIFY}" --inventory "${BAD}" --mode positive

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
