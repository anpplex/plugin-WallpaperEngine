#!/usr/bin/env bash
# WP-12B — unit-like shell tests for native lib import/verify
# Product path: scripts/tests/test-native-libs.sh (Plugin worktree)
#
# Catalog RED harness: native fixtures under scripts/tests/fixtures/
# (basenames from runtime-import/FIXTURES.md) plus inline outline cases.
# Assert exit codes + stderr failure signatures (fail-closed).
#
# Usage:
#   ./test-native-libs.sh           # run catalog + outline tests
#   ./test-native-libs.sh --help
#
# Optional smoke: OFFICIAL_WE_APK (or default Motif sandbox APK path)
#   import-native-libs.sh → verify --mode positive
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
VERIFY="${SCRIPTS_DIR}/verify-native-libs.sh"
IMPORT="${SCRIPTS_DIR}/import-native-libs.sh"
SCHEMA="${REPO_ROOT}/runtime-import/native-libs.schema.json"
FIXTURES_DIR="${SCRIPT_DIR}/fixtures"
DEFAULT_OFFICIAL_APK="/Users/anpple/Codex/Motif/sandbox/we-android/wallpaper-engine.apk"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME}

WP-12B native import/verify harness (catalog fixtures + outline).

Catalog fixtures (scripts/tests/fixtures/, FIXTURES.md basenames):
  1. native-missing-needed.json
       → negative-missing-needed, exit 1, stderr MISSING_NEEDED
  2. native-wrong-abi.json
       → negative-wrong-abi, exit 1, stderr WRONG_ABI

Outline (inline TMP inventories):
  - positive clean arm64 inventory → exit 0
  - EMPTY_ARM64 / DUPLICATE_SONAME negatives

Optional smoke: import-native-libs.sh → verify --mode positive
when OFFICIAL_WE_APK or default Motif sandbox APK is present.
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
chmod +x "${IMPORT}" 2>/dev/null || true

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 required" >&2
  exit 2
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/wp12b-test.XXXXXX")"
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

write_clean_native() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12b-native-libs/v1",
  "packageName": "io.wallpaperengine.weclient",
  "apkSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "versionCode": 1,
  "versionName": "0.0.0-test",
  "abis": [
    {
      "name": "arm64-v8a",
      "libs": [
        {
          "name": "libscenejni.so",
          "path": "lib/arm64-v8a/libscenejni.so",
          "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "sizeBytes": 1024,
          "soname": "libscenejni.so",
          "needed": ["libc.so", "libm.so", "libdl.so", "liblog.so", "libandroid.so"],
          "elfClass": "ELFCLASS64",
          "elfMachine": "EM_AARCH64"
        }
      ]
    }
  ],
  "jniLoadLibs": ["scenejni"],
  "closure": {
    "missingNeeded": [],
    "wrongAbi": [],
    "duplicateSoname": [],
    "systemNeeded": ["libc.so", "libm.so", "libdl.so", "liblog.so", "libandroid.so"]
  },
  "failClosed": {
    "ok": true,
    "failures": []
  }
}
JSON
}

write_empty_arm64() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12b-native-libs/v1",
  "packageName": "io.wallpaperengine.weclient",
  "apkSha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "abis": [
    {
      "name": "x86_64",
      "libs": [
        {
          "name": "libfoo.so",
          "path": "lib/x86_64/libfoo.so",
          "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
          "sizeBytes": 100,
          "soname": "libfoo.so",
          "needed": ["libc.so"],
          "elfClass": "ELFCLASS64",
          "elfMachine": "EM_X86_64"
        }
      ]
    }
  ],
  "jniLoadLibs": ["foo"],
  "closure": {
    "missingNeeded": [],
    "wrongAbi": [],
    "duplicateSoname": [],
    "systemNeeded": ["libc.so"]
  },
  "failClosed": {
    "ok": false,
    "failures": [
      {
        "code": "EMPTY_ARM64",
        "message": "no arm64-v8a native libraries"
      }
    ]
  }
}
JSON
}

write_duplicate_soname() {
  cat >"$1" <<'JSON'
{
  "schemaVersion": "wp12b-native-libs/v1",
  "packageName": "io.wallpaperengine.weclient",
  "apkSha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "abis": [
    {
      "name": "arm64-v8a",
      "libs": [
        {
          "name": "liba.so",
          "path": "lib/arm64-v8a/liba.so",
          "sha256": "1111111111111111111111111111111111111111111111111111111111111111",
          "sizeBytes": 10,
          "soname": "libshared.so",
          "needed": ["libc.so"],
          "elfClass": "ELFCLASS64",
          "elfMachine": "EM_AARCH64"
        },
        {
          "name": "libb.so",
          "path": "lib/arm64-v8a/libb.so",
          "sha256": "2222222222222222222222222222222222222222222222222222222222222222",
          "sizeBytes": 10,
          "soname": "libshared.so",
          "needed": ["libc.so"],
          "elfClass": "ELFCLASS64",
          "elfMachine": "EM_AARCH64"
        }
      ]
    }
  ],
  "jniLoadLibs": ["a", "b"],
  "closure": {
    "missingNeeded": [],
    "wrongAbi": [],
    "duplicateSoname": [
      {
        "abi": "arm64-v8a",
        "soname": "libshared.so",
        "libs": ["liba.so", "libb.so"]
      }
    ],
    "systemNeeded": ["libc.so"]
  },
  "failClosed": {
    "ok": false,
    "failures": [
      {
        "code": "DUPLICATE_SONAME",
        "message": "arm64-v8a SONAME libshared.so claimed by liba.so, libb.so"
      }
    ]
  }
}
JSON
}

log "WORKDIR=${TMP}"
log "FIXTURES_DIR=${FIXTURES_DIR}"
log "SCHEMA=${SCHEMA}"

if [[ ! -f "${SCHEMA}" ]]; then
  log "FAIL: missing schema ${SCHEMA}"
  FAIL=$((FAIL + 1))
fi

if [[ ! -d "${FIXTURES_DIR}" ]]; then
  log "FAIL: missing fixtures dir: ${FIXTURES_DIR}"
  FAIL=$((FAIL + 1))
else
  log "--- catalog negatives (wp12b-native-libs/v1) ---"

  assert_cmd 1 "MISSING_NEEDED" \
    "catalog native-missing-needed.json → MISSING_NEEDED" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/native-missing-needed.json" \
      --mode negative-missing-needed

  assert_cmd 1 "WRONG_ABI" \
    "catalog native-wrong-abi.json → WRONG_ABI" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/native-wrong-abi.json" \
      --mode negative-wrong-abi

  # positives must fail-closed on negative fixtures
  assert_cmd 1 "MISSING_NEEDED" \
    "catalog missing-needed fails positive mode" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/native-missing-needed.json" \
      --mode positive

  assert_cmd 1 "WRONG_ABI" \
    "catalog wrong-abi fails positive mode" \
    bash "${VERIFY}" --inventory "${FIXTURES_DIR}/native-wrong-abi.json" \
      --mode positive
fi

log "--- outline cases ---"

CLEAN="${TMP}/clean.json"
EMPTY="${TMP}/empty-arm64.json"
DUP="${TMP}/dup-soname.json"
write_clean_native "${CLEAN}"
write_empty_arm64 "${EMPTY}"
write_duplicate_soname "${DUP}"

assert_cmd 0 "" \
  "outline positive clean native inventory exits 0" \
  bash "${VERIFY}" --inventory "${CLEAN}" --mode positive

assert_cmd 1 "EMPTY_ARM64" \
  "outline empty arm64 fails positive" \
  bash "${VERIFY}" --inventory "${EMPTY}" --mode positive

assert_cmd 1 "EMPTY_ARM64" \
  "outline empty arm64 via negative-wrong-abi accepts EMPTY_ARM64" \
  bash "${VERIFY}" --inventory "${EMPTY}" --mode negative-wrong-abi

assert_cmd 1 "DUPLICATE_SONAME" \
  "outline negative-duplicate-soname" \
  bash "${VERIFY}" --inventory "${DUP}" --mode negative-duplicate-soname

assert_cmd 1 "DUPLICATE_SONAME" \
  "outline duplicate soname fails positive" \
  bash "${VERIFY}" --inventory "${DUP}" --mode positive

# --- optional APK smoke -----------------------------------------------------
APK_PATH="${OFFICIAL_WE_APK:-}"
if [[ -z "${APK_PATH}" && -f "${DEFAULT_OFFICIAL_APK}" ]]; then
  APK_PATH="${DEFAULT_OFFICIAL_APK}"
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
    log "FAIL: import-native-libs failed (rc=${imp_rc}) on ${APK_PATH}"
    cat "${TMP}/import-stderr.txt" >&2 || true
    FAIL=$((FAIL + 1))
  elif [[ ! -f "${SMOKE_OUT}/native-inventory.json" ]]; then
    log "FAIL: import produced no native-inventory.json"
    FAIL=$((FAIL + 1))
  else
    log "import smoke stdout: $(head -c 400 "${TMP}/import-stdout.txt" || true)"
    assert_cmd 0 "" \
      "optional: imported official APK native inventory passes positive" \
      bash "${VERIFY}" --inventory "${SMOKE_OUT}/native-inventory.json" --mode positive
    # apkSha256 must match file
    set +e
    python3 - "${SMOKE_OUT}/native-inventory.json" "${APK_PATH}" <<'PY'
import hashlib, json, sys
from pathlib import Path
inv = json.loads(Path(sys.argv[1]).read_text())
h = hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest()
assert inv.get("apkSha256") == h, (inv.get("apkSha256"), h)
assert inv.get("schemaVersion") == "wp12b-native-libs/v1"
arm = [a for a in inv.get("abis", []) if a.get("name") == "arm64-v8a"]
assert arm and arm[0].get("libs"), "arm64-v8a must be non-empty"
print("apkSha256-ok arm64-libs=%d" % len(arm[0]["libs"]))
PY
    py_rc=$?
    set -e
    if [[ "${py_rc}" -eq 0 ]]; then
      log "PASS: official APK apkSha256 + arm64 non-empty"
      PASS=$((PASS + 1))
    else
      log "FAIL: official APK inventory integrity checks"
      FAIL=$((FAIL + 1))
    fi
  fi
else
  log "SKIP: no OFFICIAL_WE_APK / default Motif APK for import smoke"
  SKIP=$((SKIP + 1))
fi

log "summary: pass=${PASS} fail=${FAIL} skip=${SKIP}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
