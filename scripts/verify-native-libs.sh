#!/usr/bin/env bash
# WP-12B — verify native/JNI inventory (fail-closed)
# Product path: scripts/verify-native-libs.sh (Plugin worktree)
#
# Fail-closed static verifier for native-inventory.json produced by
# import-native-libs.sh or fixture inventories conforming to
# runtime-import/native-libs.schema.json (schemaVersion=wp12b-native-libs/v1).
#
# Usage:
#   verify-native-libs.sh --inventory PATH --mode MODE
#   verify-native-libs.sh --help
#
# Modes:
#   positive
#       Inventory must pass all fail-closed rules → exit 0.
#       Requires failClosed.ok-equivalent, non-empty arm64-v8a, no MISSING_NEEDED.
#   negative-missing-needed
#       Expect MISSING_NEEDED among failures → exit 1 + code on stderr.
#   negative-wrong-abi
#       Expect WRONG_ABI or EMPTY_ARM64 → exit 1 + code on stderr.
#   negative-duplicate-soname
#       Expect DUPLICATE_SONAME → exit 1 + code on stderr (optional harness).
#
# Fail-closed rules (always re-evaluated from structure; failClosed field is not trusted alone):
#   MISSING_NEEDED   — needed[] entry not in same-ABI libs/sonames and not systemNeeded
#   WRONG_ABI        — elfMachine/elfClass mismatch vs ABI directory
#   DUPLICATE_SONAME — same non-null soname claimed by ≥2 libs in one ABI
#   EMPTY_ARM64      — missing arm64-v8a row or empty libs[]
#
# Exit codes:
#   0  positive mode and inventory is clean
#   1  fail-closed rule fired (positive) or negative-mode signature outcome
#   2  usage / invalid inventory / missing required fields
#   3  unexpected internal error
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --inventory PATH --mode MODE

Verify a WP-12B native-libs inventory (fail-closed).

Options:
  --inventory PATH   Path to native-inventory JSON (required)
  --mode MODE        One of:
                       positive
                       negative-missing-needed
                       negative-wrong-abi
                       negative-duplicate-soname
  -h, --help         Show this help and exit

Exit codes:
  0  positive + clean inventory
  1  fail-closed defect (or negative-mode expected-signature outcome)
  2  usage / invalid inventory
  3  unexpected internal error

Stderr prints failure codes as bare tokens (e.g. MISSING_NEEDED) so catalog
failureSignaturePolicy can match stderr.
EOF
}

log()  { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }
die()  { log "ERROR: $*"; exit 2; }

INVENTORY=""
MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --inventory)
      [[ $# -ge 2 ]] || die "--inventory requires a path"
      INVENTORY="$2"
      shift 2
      ;;
    --mode)
      [[ $# -ge 2 ]] || die "--mode requires a value"
      MODE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1 (try --help)"
      ;;
  esac
done

[[ -n "${INVENTORY}" ]] || die "missing --inventory PATH"
[[ -n "${MODE}" ]] || die "missing --mode MODE"
[[ -f "${INVENTORY}" ]] || die "inventory not found or not a file: ${INVENTORY}"
[[ -r "${INVENTORY}" ]] || die "inventory not readable: ${INVENTORY}"

case "${MODE}" in
  positive|\
  negative-missing-needed|\
  negative-wrong-abi|\
  negative-duplicate-soname)
    ;;
  *)
    die "unknown --mode: ${MODE}"
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 is required"
fi

INVENTORY="$(cd "$(dirname "${INVENTORY}")" && pwd)/$(basename "${INVENTORY}")"

log "inventory=${INVENTORY}"
log "mode=${MODE}"

export WP12B_VERIFY_INVENTORY="${INVENTORY}"
export WP12B_VERIFY_MODE="${MODE}"

set +e
PY_OUT="$(
python3 <<'PY'
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

inv_path = Path(os.environ["WP12B_VERIFY_INVENTORY"])
mode = os.environ["WP12B_VERIFY_MODE"]

ABI_EXPECT = {
    "arm64-v8a": ("EM_AARCH64", "ELFCLASS64"),
    "armeabi-v7a": ("EM_ARM", "ELFCLASS32"),
    "armeabi": ("EM_ARM", "ELFCLASS32"),
    "x86": ("EM_386", "ELFCLASS32"),
    "x86_64": ("EM_X86_64", "ELFCLASS64"),
    "riscv64": ("EM_RISCV", "ELFCLASS64"),
}


def emit(status: str, codes: list[str], message: str) -> None:
    for c in codes:
        print(c, file=sys.stderr)
    print(f"{status}|{','.join(codes)}|{message}")


try:
    data = json.loads(inv_path.read_text(encoding="utf-8"))
except json.JSONDecodeError as e:
    emit("INVALID", ["INVALID_INVENTORY"], f"JSON parse error: {e}")
    sys.exit(0)
except OSError as e:
    emit("INVALID", ["INVALID_INVENTORY"], f"read error: {e}")
    sys.exit(0)

if not isinstance(data, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "inventory root must be a JSON object")
    sys.exit(0)

required = [
    "schemaVersion",
    "packageName",
    "apkSha256",
    "abis",
    "jniLoadLibs",
    "closure",
    "failClosed",
]
missing = [k for k in required if k not in data]
if missing:
    emit("INVALID", ["INVALID_INVENTORY"], f"inventory missing fields: {missing}")
    sys.exit(0)

if data.get("schemaVersion") != "wp12b-native-libs/v1":
    emit(
        "INVALID",
        ["INVALID_INVENTORY"],
        f"unsupported schemaVersion: {data.get('schemaVersion')!r}",
    )
    sys.exit(0)

if not isinstance(data["packageName"], str) or not data["packageName"]:
    emit("INVALID", ["INVALID_INVENTORY"], "packageName must be non-empty string")
    sys.exit(0)

apk_sha = data.get("apkSha256") or ""
if not isinstance(apk_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", apk_sha):
    emit("INVALID", ["INVALID_INVENTORY"], "apkSha256 must be 64-char lowercase hex")
    sys.exit(0)

if not isinstance(data["abis"], list):
    emit("INVALID", ["INVALID_INVENTORY"], "abis must be an array")
    sys.exit(0)
if not isinstance(data["jniLoadLibs"], list):
    emit("INVALID", ["INVALID_INVENTORY"], "jniLoadLibs must be an array")
    sys.exit(0)
if not isinstance(data["closure"], dict):
    emit("INVALID", ["INVALID_INVENTORY"], "closure must be an object")
    sys.exit(0)
if not isinstance(data["failClosed"], dict):
    emit("INVALID", ["INVALID_INVENTORY"], "failClosed must be an object")
    sys.exit(0)

# System allowlist: union of declared systemNeeded + well-known public NDK/Bionic.
DEFAULT_SYSTEM = {
    "libc.so",
    "libm.so",
    "libdl.so",
    "liblog.so",
    "libz.so",
    "libandroid.so",
    "libjnigraphics.so",
    "libEGL.so",
    "libGLESv1_CM.so",
    "libGLESv2.so",
    "libGLESv3.so",
    "libOpenSLES.so",
    "libOpenMAXAL.so",
    "libmediandk.so",
    "libcamera2ndk.so",
    "libaaudio.so",
    "libamidi.so",
    "libbinder_ndk.so",
    "libnativewindow.so",
    "libsync.so",
    "libvulkan.so",
    "libstdc++.so",
    "libstdc++.so.6",
    "libneuralnetworks.so",
}
declared_system = data["closure"].get("systemNeeded") or []
system_set = set(DEFAULT_SYSTEM)
if isinstance(declared_system, list):
    for s in declared_system:
        if isinstance(s, str) and s:
            system_set.add(s)

failures: list[tuple[str, str]] = []


def add(code: str, message: str) -> None:
    failures.append((code, message))


# EMPTY_ARM64
arm64_libs: list[dict] = []
arm64_seen = False
for row in data["abis"]:
    if not isinstance(row, dict):
        continue
    if row.get("name") == "arm64-v8a":
        arm64_seen = True
        libs = row.get("libs")
        if isinstance(libs, list):
            arm64_libs = [x for x in libs if isinstance(x, dict)]
        break
if not arm64_seen or len(arm64_libs) == 0:
    add("EMPTY_ARM64", "no arm64-v8a native libraries (empty or missing ABI row)")

# Per-ABI checks
for row in data["abis"]:
    if not isinstance(row, dict):
        continue
    abi = row.get("name")
    if not isinstance(abi, str) or not abi:
        continue
    libs = row.get("libs")
    if not isinstance(libs, list):
        continue
    lib_dicts = [x for x in libs if isinstance(x, dict)]

    local: set[str] = set()
    for L in lib_dicts:
        n = L.get("name")
        if isinstance(n, str) and n:
            local.add(n)
        sn = L.get("soname")
        if isinstance(sn, str) and sn:
            local.add(sn)

    # DUPLICATE_SONAME
    soname_map: dict[str, list[str]] = defaultdict(list)
    for L in lib_dicts:
        sn = L.get("soname")
        name = L.get("name") if isinstance(L.get("name"), str) else "?"
        if isinstance(sn, str) and sn:
            soname_map[sn].append(name)
    for sn, claimants in sorted(soname_map.items()):
        uniq = sorted(set(claimants))
        if len(uniq) >= 2:
            add(
                "DUPLICATE_SONAME",
                f"{abi} SONAME {sn} claimed by: " + ", ".join(uniq),
            )

    # WRONG_ABI
    expect = ABI_EXPECT.get(abi)
    if expect is not None:
        exp_m, exp_c = expect
        for L in lib_dicts:
            machine = L.get("elfMachine") or ""
            klass = L.get("elfClass") or ""
            name = L.get("name") or "?"
            if machine != exp_m or klass != exp_c:
                add(
                    "WRONG_ABI",
                    f"{abi}/{name} ELF machine {machine} class {klass} "
                    f"!= expected {exp_m}/{exp_c}",
                )

    # MISSING_NEEDED
    for L in lib_dicts:
        name = L.get("name") or "?"
        needed = L.get("needed") or []
        if not isinstance(needed, list):
            continue
        for need in needed:
            if not isinstance(need, str) or not need:
                continue
            if need in local:
                continue
            if need in system_set:
                continue
            add(
                "MISSING_NEEDED",
                f"{abi} {name} DT_NEEDED {need} not resolved locally or as system",
            )

# Also accept precomputed closure arrays if structural scan missed (should not),
# but do not skip recomputation — fail-closed prefers structure above.
# If inventory failClosed lists codes we did not recompute (malformed libs), still surface them
# only when structural scan is empty and failClosed.ok is false? Prefer structure only.

codes: list[str] = []
seen: set[str] = set()
for code, _msg in failures:
    if code not in seen:
        seen.add(code)
        codes.append(code)

expected_by_mode = {
    "positive": None,
    "negative-missing-needed": "MISSING_NEEDED",
    "negative-wrong-abi": None,  # WRONG_ABI or EMPTY_ARM64
    "negative-duplicate-soname": "DUPLICATE_SONAME",
}

if mode == "positive":
    if not codes:
        emit("PASS", [], "native inventory clean (arm64 present, closure ok)")
    else:
        detail = "; ".join(f"{c}: {m}" for c, m in failures)
        emit("FAIL", codes, detail)
    sys.exit(0)

if mode == "negative-wrong-abi":
    # Accept WRONG_ABI or EMPTY_ARM64 as the RED signature for this mode.
    if "WRONG_ABI" in seen:
        ordered = ["WRONG_ABI"] + [c for c in codes if c != "WRONG_ABI"]
        detail = "; ".join(f"{c}: {m}" for c, m in failures if c == "WRONG_ABI")
        emit("FAIL", ordered, detail or "WRONG_ABI")
    elif "EMPTY_ARM64" in seen:
        ordered = ["EMPTY_ARM64"] + [c for c in codes if c != "EMPTY_ARM64"]
        detail = "; ".join(f"{c}: {m}" for c, m in failures if c == "EMPTY_ARM64")
        emit("FAIL", ordered, detail or "EMPTY_ARM64")
    else:
        emit(
            "EXPECTED_MISSING",
            ["EXPECTED_FAILURE_NOT_FOUND", *codes],
            f"mode {mode} expected WRONG_ABI or EMPTY_ARM64 but failures={codes}",
        )
    sys.exit(0)

expected = expected_by_mode[mode]
assert expected is not None
if expected in seen:
    detail = "; ".join(f"{c}: {m}" for c, m in failures if c == expected)
    ordered = [expected] + [c for c in codes if c != expected]
    emit("FAIL", ordered, detail or expected)
else:
    emit(
        "EXPECTED_MISSING",
        ["EXPECTED_FAILURE_NOT_FOUND", *codes],
        f"mode {mode} expected {expected} but failures={codes}",
    )
sys.exit(0)
PY
)"
PY_RC=$?
set -e

if [[ "${PY_RC}" -ne 0 ]]; then
  log "internal python error (rc=${PY_RC})"
  printf 'INTERNAL_ERROR\n' >&2
  exit 3
fi

STATUS_LINE=""
while IFS= read -r line; do
  [[ -n "${line}" ]] && STATUS_LINE="${line}"
done <<<"${PY_OUT}"

if [[ -z "${STATUS_LINE}" ]]; then
  log "internal error: empty verifier result"
  printf 'INTERNAL_ERROR\n' >&2
  exit 3
fi

STATUS="${STATUS_LINE%%|*}"
REST="${STATUS_LINE#*|}"
CODES_FIELD="${REST%%|*}"
MESSAGE="${REST#*|}"
if [[ "${MESSAGE}" == "${REST}" ]]; then
  MESSAGE=""
fi

log "status=${STATUS} codes=${CODES_FIELD} msg=${MESSAGE}"

case "${STATUS}" in
  PASS)
    exit 0
    ;;
  FAIL)
    # negative modes and positive defects → exit 1 (RED / fail-closed)
    exit 1
    ;;
  EXPECTED_MISSING)
    # expected negative signature not found — still non-zero; emit token already on stderr
    exit 1
    ;;
  INVALID)
    exit 2
    ;;
  *)
    log "unknown status: ${STATUS}"
    printf 'INTERNAL_ERROR\n' >&2
    exit 3
    ;;
esac
