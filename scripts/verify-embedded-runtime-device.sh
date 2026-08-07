#!/usr/bin/env bash
# WP-12D — verify embedded runtime device E2/E3 contract (fail-closed)
# Product path: scripts/verify-embedded-runtime-device.sh (Plugin worktree)
#
# Catalog phase selectors:
#   --case device-negative          # RED:  exit 1, stderr MISSING_SERIAL|WRONG_USER|
#                                   #       OFFICIAL_AS_EMBEDDED_HOST|DEVICE_OFFLINE|MISSING_APK
#   --case device-positive-offline  # GREEN: exit 0 contract dry-run (no adb, no E3 claim)
#   --case device-positive          # live collect → verify positive (exit 0 when device green)
#
# Inventory modes (fixture JSON, schemaVersion=wp12d-device-e2e3/v1):
#   --inventory PATH --mode MODE
#     positive
#     negative-missing-serial
#     negative-wrong-user
#     negative-official-as-embedded-host
#
# Fail-closed rules (recomputed from structure; failClosed field not trusted alone):
#   MISSING_SERIAL              — serial null/empty
#   WRONG_USER                  — observedUser present and != targetUser
#   OFFICIAL_AS_EMBEDDED_HOST   — official WE package claims embedded host role
#   DEVICE_OFFLINE              — device not online (non dry-run / real adb path)
#   MISSING_APK                 — required APK absent from inventory or filesystem
#
# Exit codes:
#   0  positive clean / device-positive-offline
#   1  fail-closed defect or negative-mode signature outcome (RED)
#   2  usage / invalid inventory
#   3  unexpected internal error
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES_DIR="${SCRIPT_DIR}/tests/fixtures"

EXPECTED_PLUGIN_PKG="com.motif.wallpaperengine"
EXPECTED_OFFICIAL_PKG="io.wallpaperengine.weclient"
EXPECTED_MINERADIO_PKG="com.mineradio.app"

usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} --case device-negative
  ${SCRIPT_NAME} --case device-positive-offline
  ${SCRIPT_NAME} --case device-positive
  ${SCRIPT_NAME} --inventory PATH --mode MODE

WP-12D host-side embedded runtime device verifier (fail-closed).

Cases (catalog RED/GREEN + gated device path):
  device-negative           Primary negative inventory → exit 1 + RED signature
  device-positive-offline   Synthetic positive fixture dry-run → exit 0 (no E3 claim)
  device-positive           Live collect via collect-wp12-evidence.py --mode e2-e3
                            then verify --mode positive (env SERIAL TARGET_USER
                            MINERADIO_APK PLUGIN_APK OFFICIAL_WE_APK); exit 0 when green

Modes (with --inventory):
  positive
  negative-missing-serial
  negative-wrong-user
  negative-official-as-embedded-host

Exit codes:
  0  positive + clean
  1  fail-closed defect (or negative-mode expected-signature outcome)
  2  usage / invalid inventory
  3  unexpected internal error

Stderr prints failure codes as bare tokens (e.g. MISSING_SERIAL) so catalog
failureSignaturePolicy can match stderr.
EOF
}

log()  { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }
die()  { log "ERROR: $*"; exit 2; }

CASE=""
INVENTORY=""
MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --case)
      [[ $# -ge 2 ]] || die "--case requires a value"
      CASE="$2"
      shift 2
      ;;
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

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 is required"
fi

# ---------------------------------------------------------------------------
# device-positive: live collect → inventory → verify --mode positive
# Exit 0 when device green (hard checks pass). Never forges PASS offline.
# ---------------------------------------------------------------------------
run_device_positive() {
  local missing=0
  local COLLECT="${SCRIPT_DIR}/collect-wp12-evidence.py"

  if [[ -z "${SERIAL:-}" ]]; then
    printf 'MISSING_SERIAL\n' >&2
    log "status=FAIL codes=MISSING_SERIAL msg=SERIAL env required for device-positive"
    exit 1
  fi

  for var in TARGET_USER MINERADIO_APK PLUGIN_APK OFFICIAL_WE_APK; do
    if [[ -z "${!var:-}" ]]; then
      log "missing required env: ${var}"
      missing=1
    fi
  done
  if [[ "${missing}" -ne 0 ]]; then
    # Prefer MISSING_APK when APK paths absent; else treat as usage after serial present.
    if [[ -z "${MINERADIO_APK:-}" || -z "${PLUGIN_APK:-}" || -z "${OFFICIAL_WE_APK:-}" ]]; then
      printf 'MISSING_APK\n' >&2
      log "status=FAIL codes=MISSING_APK msg=required APK env vars missing"
      exit 1
    fi
    die "TARGET_USER is required for device-positive"
  fi

  for apk_var in MINERADIO_APK PLUGIN_APK OFFICIAL_WE_APK; do
    local path="${!apk_var}"
    if [[ "${path#/}" == "${path}" ]]; then
      printf 'MISSING_APK\n' >&2
      log "status=FAIL codes=MISSING_APK msg=${apk_var} must be absolute path"
      exit 1
    fi
    if [[ ! -f "${path}" ]]; then
      printf 'MISSING_APK\n' >&2
      log "status=FAIL codes=MISSING_APK msg=${apk_var} not found: ${path}"
      exit 1
    fi
  done

  if ! command -v adb >/dev/null 2>&1; then
    printf 'DEVICE_OFFLINE\n' >&2
    log "status=FAIL codes=DEVICE_OFFLINE msg=adb not available"
    exit 1
  fi

  if [[ ! -f "${COLLECT}" ]]; then
    printf 'DEVICE_OFFLINE\n' >&2
    log "status=FAIL codes=DEVICE_OFFLINE msg=collector missing: ${COLLECT}"
    exit 1
  fi

  # TMP_CASE cleaned by shared EXIT trap below.
  TMP_CASE="$(mktemp -d "${TMPDIR:-/tmp}/wp12d-device-positive.XXXXXX")"
  local live_tmp="${TMP_CASE}"

  # Minimal transaction receipt so collector can write raw (not task EffectiveDone).
  cat >"${live_tmp}/txn.json" <<'TXN'
{
  "taskId": "WP-12D",
  "transactionId": "device-positive-live",
  "runUuid": "device-positive-live",
  "state": "TREE_FROZEN",
  "EffectiveDone": false
}
TXN

  local raw_out="${live_tmp}/raw.json"
  local collect_rc=0
  set +e
  python3 "${COLLECT}" \
    --mode e2-e3 \
    --serial "${SERIAL}" \
    --user "${TARGET_USER}" \
    --mineradio-apk "${MINERADIO_APK}" \
    --plugin-apk "${PLUGIN_APK}" \
    --official-apk "${OFFICIAL_WE_APK}" \
    --transaction "${live_tmp}/txn.json" \
    --attempt-no 1 \
    --out "${raw_out}" >"${live_tmp}/collect.stdout" 2>"${live_tmp}/collect.stderr"
  collect_rc=$?
  set -e

  if [[ "${collect_rc}" -ne 0 ]]; then
    # Propagate collector hard-fail codes to stderr for catalog matching.
    local reason
    reason="$(
      python3 - "${live_tmp}/collect.stdout" "${live_tmp}/collect.stderr" <<'PY'
import json, sys
for path in sys.argv[1:]:
    try:
        text = open(path, encoding="utf-8").read().strip()
    except OSError:
        continue
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict) and doc.get("failureReason"):
            print(doc["failureReason"])
            raise SystemExit(0)
print("")
PY
    )"
    if [[ -z "${reason}" ]]; then
      reason="DEVICE_OFFLINE"
    fi
    printf '%s\n' "${reason}" >&2
    log "status=FAIL codes=${reason} msg=live collect failed (fail-closed; no PASS forged)"
    if [[ -s "${live_tmp}/collect.stderr" ]]; then
      log "collect.stderr=$(tail -c 400 "${live_tmp}/collect.stderr" | tr '\n' ' ')"
    fi
    exit 1
  fi

  if [[ ! -f "${raw_out}" ]]; then
    printf 'DEVICE_OFFLINE\n' >&2
    log "status=FAIL codes=DEVICE_OFFLINE msg=collector produced no raw evidence"
    exit 1
  fi

  local inv_out="${live_tmp}/live-inventory.json"
  python3 - "${raw_out}" "${inv_out}" <<'PY'
import json, sys
raw_path, inv_path = sys.argv[1], sys.argv[2]
raw = json.loads(open(raw_path, encoding="utf-8").read())
inv = raw.get("inventory")
if not isinstance(inv, dict):
    raise SystemExit("raw missing inventory object")
open(inv_path, "w", encoding="utf-8").write(json.dumps(inv, indent=2, sort_keys=True) + "\n")
PY

  log "case=device-positive live inventory=${inv_out} (collector e2-e3; soft surface/pid)"
  INVENTORY="${inv_out}"
  MODE="positive"
  # Fall through to shared inventory verifier below (do not exit).
}

TMP_CASE=""
cleanup() {
  if [[ -n "${TMP_CASE}" && -d "${TMP_CASE}" ]]; then
    rm -rf "${TMP_CASE}"
  fi
}
trap cleanup EXIT

if [[ -n "${CASE}" ]]; then
  case "${CASE}" in
    device-negative)
      # Primary catalog RED signature: MISSING_SERIAL via fixture inventory.
      if [[ -f "${FIXTURES_DIR}/device-missing-serial.json" ]]; then
        INVENTORY="${FIXTURES_DIR}/device-missing-serial.json"
      else
        TMP_CASE="$(mktemp -d "${TMPDIR:-/tmp}/wp12d-device-neg.XXXXXX")"
        INVENTORY="${TMP_CASE}/device-missing-serial.json"
        cat >"${INVENTORY}" <<'JSON'
{
  "schemaVersion": "wp12d-device-e2e3/v1",
  "serial": "",
  "targetUser": 12,
  "observedUser": null,
  "deviceOnline": false,
  "contractDryRun": true,
  "deviceE3Claim": false,
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
  "pluginPid": 0,
  "surface": {"present": false, "ownerPid": 0, "name": null},
  "realCaller": {"package": null, "uid": null, "isShell": false, "isMineradio": false},
  "officialNotEmbeddedHost": true,
  "failClosed": {
    "ok": false,
    "failures": [{"code": "MISSING_SERIAL", "message": "device serial missing or empty"}]
  }
}
JSON
      fi
      MODE="negative-missing-serial"
      log "case=device-negative inventory=${INVENTORY} mode=${MODE}"
      ;;
    device-positive-offline)
      if [[ -f "${FIXTURES_DIR}/device-e2e3-pass-offline.json" ]]; then
        INVENTORY="${FIXTURES_DIR}/device-e2e3-pass-offline.json"
      else
        TMP_CASE="$(mktemp -d "${TMPDIR:-/tmp}/wp12d-device-pos.XXXXXX")"
        INVENTORY="${TMP_CASE}/device-e2e3-pass-offline.json"
        cat >"${INVENTORY}" <<'JSON'
{
  "schemaVersion": "wp12d-device-e2e3/v1",
  "serial": "SYNTHETIC_SERIAL_OFFLINE_PASS",
  "targetUser": 12,
  "observedUser": 12,
  "deviceOnline": false,
  "contractDryRun": true,
  "deviceE3Claim": false,
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
      fi
      MODE="positive"
      log "case=device-positive-offline inventory=${INVENTORY} (contract dry-run; no device E3 claim)"
      ;;
    device-positive)
      log "case=device-positive (live collect + verify positive)"
      run_device_positive
      ;;
    *)
      die "unknown --case: ${CASE} (expected device-negative|device-positive-offline|device-positive)"
      ;;
  esac
fi

[[ -n "${INVENTORY}" ]] || die "missing --inventory PATH (or --case)"
[[ -n "${MODE}" ]] || die "missing --mode MODE (or --case)"
[[ -f "${INVENTORY}" ]] || die "inventory not found or not a file: ${INVENTORY}"
[[ -r "${INVENTORY}" ]] || die "inventory not readable: ${INVENTORY}"

case "${MODE}" in
  positive|\
  negative-missing-serial|\
  negative-wrong-user|\
  negative-official-as-embedded-host)
    ;;
  *)
    die "unknown --mode: ${MODE}"
    ;;
esac

INVENTORY="$(cd "$(dirname "${INVENTORY}")" && pwd)/$(basename "${INVENTORY}")"

log "inventory=${INVENTORY}"
log "mode=${MODE}"

export WP12D_VERIFY_INVENTORY="${INVENTORY}"
export WP12D_VERIFY_MODE="${MODE}"
export WP12D_EXPECTED_PLUGIN_PKG="${EXPECTED_PLUGIN_PKG}"
export WP12D_EXPECTED_OFFICIAL_PKG="${EXPECTED_OFFICIAL_PKG}"
export WP12D_EXPECTED_MINERADIO_PKG="${EXPECTED_MINERADIO_PKG}"

set +e
PY_OUT="$(
python3 <<'PY'
import json
import os
import re
import sys
from pathlib import Path

inv_path = Path(os.environ["WP12D_VERIFY_INVENTORY"])
mode = os.environ["WP12D_VERIFY_MODE"]
PKG_PLUGIN = os.environ["WP12D_EXPECTED_PLUGIN_PKG"]
PKG_OFFICIAL = os.environ["WP12D_EXPECTED_OFFICIAL_PKG"]
PKG_MINERADIO = os.environ["WP12D_EXPECTED_MINERADIO_PKG"]

SCHEMA = "wp12d-device-e2e3/v1"
HEX64 = re.compile(r"^[a-f0-9]{64}$")


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

if data.get("schemaVersion") != SCHEMA:
    emit(
        "INVALID",
        ["INVALID_INVENTORY"],
        f"unsupported schemaVersion: {data.get('schemaVersion')!r}",
    )
    sys.exit(0)

required = [
    "schemaVersion",
    "packageIdentities",
    "signatures",
    "pluginPid",
    "surface",
    "realCaller",
    "officialNotEmbeddedHost",
    "failClosed",
]
missing = [k for k in required if k not in data]
if missing:
    emit("INVALID", ["INVALID_INVENTORY"], f"inventory missing fields: {missing}")
    sys.exit(0)

package_identities = data.get("packageIdentities")
if not isinstance(package_identities, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "packageIdentities must be an object")
    sys.exit(0)

signatures = data.get("signatures")
if not isinstance(signatures, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "signatures must be an object")
    sys.exit(0)

surface = data.get("surface")
if not isinstance(surface, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "surface must be an object")
    sys.exit(0)

real_caller = data.get("realCaller")
if not isinstance(real_caller, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "realCaller must be an object")
    sys.exit(0)

fail_closed = data.get("failClosed")
if not isinstance(fail_closed, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "failClosed must be an object")
    sys.exit(0)

official_not_host = data.get("officialNotEmbeddedHost")
if not isinstance(official_not_host, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "officialNotEmbeddedHost must be boolean")
    sys.exit(0)

plugin_pid = data.get("pluginPid")
if not isinstance(plugin_pid, int) or isinstance(plugin_pid, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "pluginPid must be an integer")
    sys.exit(0)

failures: list[tuple[str, str]] = []


def add(code: str, message: str) -> None:
    failures.append((code, message))


# ---------------------------------------------------------------------------
# MISSING_SERIAL
# ---------------------------------------------------------------------------
serial = data.get("serial", None)
if serial is None or (isinstance(serial, str) and serial.strip() == ""):
    add("MISSING_SERIAL", "device serial missing or empty")
elif not isinstance(serial, str):
    emit("INVALID", ["INVALID_INVENTORY"], "serial must be string or null")
    sys.exit(0)

# ---------------------------------------------------------------------------
# WRONG_USER
# ---------------------------------------------------------------------------
target_user = data.get("targetUser")
observed_user = data.get("observedUser", None)
if target_user is not None and not isinstance(target_user, int):
    emit("INVALID", ["INVALID_INVENTORY"], "targetUser must be int when present")
    sys.exit(0)
if observed_user is not None and not isinstance(observed_user, int):
    emit("INVALID", ["INVALID_INVENTORY"], "observedUser must be int or null")
    sys.exit(0)
if (
    isinstance(target_user, int)
    and isinstance(observed_user, int)
    and observed_user != target_user
):
    add(
        "WRONG_USER",
        f"observed user {observed_user} does not match target user {target_user}",
    )

# ---------------------------------------------------------------------------
# OFFICIAL_AS_EMBEDDED_HOST
# ---------------------------------------------------------------------------
embedded_host = package_identities.get("embeddedHost")
official_pkg = package_identities.get("officialWe") or PKG_OFFICIAL
if official_not_host is False:
    add(
        "OFFICIAL_AS_EMBEDDED_HOST",
        "officialNotEmbeddedHost is false",
    )
elif isinstance(embedded_host, str) and embedded_host == official_pkg:
    add(
        "OFFICIAL_AS_EMBEDDED_HOST",
        f"embeddedHost equals official package {official_pkg}",
    )
elif isinstance(embedded_host, str) and embedded_host == PKG_OFFICIAL:
    add(
        "OFFICIAL_AS_EMBEDDED_HOST",
        f"embeddedHost is official WE package {PKG_OFFICIAL}",
    )

# ---------------------------------------------------------------------------
# MISSING_APK
# ---------------------------------------------------------------------------
apk_present = data.get("apkPresent")
if isinstance(apk_present, dict):
    for role in ("mineradio", "plugin", "officialWe"):
        val = apk_present.get(role)
        if val is False:
            add("MISSING_APK", f"apkPresent.{role} is false")
        elif val is not True and val is not None:
            emit(
                "INVALID",
                ["INVALID_INVENTORY"],
                f"apkPresent.{role} must be boolean when present",
            )
            sys.exit(0)

# ---------------------------------------------------------------------------
# DEVICE_OFFLINE
# ---------------------------------------------------------------------------
# Contract dry-run (offline GREEN) may set deviceOnline=false without claiming
# DEVICE_OFFLINE — only non-dry-run inventories fail closed on offline state.
contract_dry_run = data.get("contractDryRun")
if contract_dry_run is not None and not isinstance(contract_dry_run, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "contractDryRun must be boolean when present")
    sys.exit(0)
device_online = data.get("deviceOnline")
if device_online is not None and not isinstance(device_online, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "deviceOnline must be boolean when present")
    sys.exit(0)
if contract_dry_run is not True and device_online is False:
    add("DEVICE_OFFLINE", "deviceOnline is false outside contract dry-run")

# ---------------------------------------------------------------------------
# deviceE3Claim must not be true on contract dry-run (must NOT claim device E3)
# ---------------------------------------------------------------------------
device_e3_claim = data.get("deviceE3Claim")
if device_e3_claim is not None and not isinstance(device_e3_claim, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "deviceE3Claim must be boolean when present")
    sys.exit(0)
if contract_dry_run is True and device_e3_claim is True:
    # Not a catalog RED token; still fail-closed so offline path cannot forge E3.
    add(
        "DEVICE_OFFLINE",
        "contract dry-run must not set deviceE3Claim=true (no forged device E3)",
    )

# ---------------------------------------------------------------------------
# Positive structural integrity (when serial present — soft consistency)
# Only add hard RED tokens already defined; additional defects map to existing
# codes or are checked only under positive mode via fail if any codes remain.
# ---------------------------------------------------------------------------
# For positive inventories we require full identity/caller/surface integrity.
# Defects that are not catalog RED tokens still cause positive FAIL via codes
# list; negative modes only assert their expected signature.

positive_defects: list[tuple[str, str]] = []


def pos_add(code: str, message: str) -> None:
    positive_defects.append((code, message))


# packageIdentities expected packages (when keys present)
id_mineradio = package_identities.get("mineradio")
id_plugin = package_identities.get("plugin")
id_official = package_identities.get("officialWe")
if id_mineradio is not None and id_mineradio != PKG_MINERADIO:
    pos_add("MISSING_SERIAL", f"packageIdentities.mineradio unexpected: {id_mineradio}")
if id_plugin is not None and id_plugin != PKG_PLUGIN:
    pos_add("MISSING_SERIAL", f"packageIdentities.plugin unexpected: {id_plugin}")
if id_official is not None and id_official != PKG_OFFICIAL:
    pos_add("MISSING_SERIAL", f"packageIdentities.officialWe unexpected: {id_official}")

# signatures: when present, expect 64-char hex for each role
for role in ("mineradio", "plugin", "officialWe"):
    sig = signatures.get(role)
    if sig is None:
        continue
    if not isinstance(sig, str) or not HEX64.fullmatch(sig):
        pos_add("MISSING_APK", f"signatures.{role} must be 64-char lowercase hex")

# realCaller / pluginPid / surface integrity for positive path.
# Offline contract dry-run: strict synthetic shape (pid/surface present, no E3 claim).
# Live inventory (deviceOnline=true, contractDryRun!=true): soft surface/pid;
# deviceE3Claim/deviceEvidenceClaimed may be true when hard checks passed.
surface_present = surface.get("present")
owner_pid = surface.get("ownerPid")
is_live = device_online is True and contract_dry_run is not True
if mode == "positive":
    if is_live:
        # Soft: pluginPid/surface recorded but not required for PASS.
        if real_caller.get("isShell") is True:
            pos_add("DEVICE_OFFLINE", "realCaller must not be shell for live positive")
        if real_caller.get("isMineradio") is not True:
            pos_add(
                "DEVICE_OFFLINE",
                "live positive requires realCaller.isMineradio true (Mineradio installed)",
            )
        caller_pkg = real_caller.get("package")
        if caller_pkg is not None and caller_pkg != PKG_MINERADIO:
            pos_add("DEVICE_OFFLINE", f"realCaller.package unexpected: {caller_pkg}")
        if official_not_host is not True:
            pos_add("OFFICIAL_AS_EMBEDDED_HOST", "live positive requires officialNotEmbeddedHost")
        # Live claim is allowed (and expected) when hard checks pass.
        device_evidence_claimed = data.get("deviceEvidenceClaimed")
        if device_e3_claim is False and device_evidence_claimed is False:
            pos_add(
                "DEVICE_OFFLINE",
                "live positive expects deviceEvidenceClaimed/deviceE3Claim true when green",
            )
    else:
        if not (isinstance(plugin_pid, int) and plugin_pid > 0):
            pos_add("DEVICE_OFFLINE", "positive requires pluginPid > 0")
        if surface_present is not True:
            pos_add("DEVICE_OFFLINE", "positive requires surface.present true")
        elif not (isinstance(owner_pid, int) and owner_pid == plugin_pid):
            pos_add("DEVICE_OFFLINE", "surface.ownerPid must match pluginPid")
        if real_caller.get("isShell") is True:
            pos_add("DEVICE_OFFLINE", "realCaller must not be shell for positive")
        if real_caller.get("isMineradio") is not True:
            pos_add("DEVICE_OFFLINE", "realCaller.isMineradio must be true for positive")
        caller_pkg = real_caller.get("package")
        if caller_pkg is not None and caller_pkg != PKG_MINERADIO:
            pos_add("DEVICE_OFFLINE", f"realCaller.package unexpected: {caller_pkg}")
        # Offline contract dry-run may leave deviceOnline false; require dry-run flag.
        if device_online is False and contract_dry_run is not True:
            # already covered by DEVICE_OFFLINE above; keep positive clean
            pass
        if device_e3_claim is True:
            pos_add("DEVICE_OFFLINE", "positive inventory must not forge deviceE3Claim")
# Merge positive-only defects only for positive mode (avoid polluting negative
# signature ordering with unrelated codes).
if mode == "positive":
    for code, msg in positive_defects:
        add(code, msg)

codes: list[str] = []
seen: set[str] = set()
for code, _msg in failures:
    if code not in seen:
        seen.add(code)
        codes.append(code)

expected_by_mode = {
    "positive": None,
    "negative-missing-serial": "MISSING_SERIAL",
    "negative-wrong-user": "WRONG_USER",
    "negative-official-as-embedded-host": "OFFICIAL_AS_EMBEDDED_HOST",
}

if mode == "positive":
    if not codes:
        if is_live:
            emit(
                "PASS",
                [],
                "device e2e3 live hard checks clean (surface/pluginPid soft; EffectiveDone false)",
            )
        else:
            emit(
                "PASS",
                [],
                "device e2e3 contract clean (offline dry-run; no device E3 claim)",
            )
    else:
        detail = "; ".join(f"{c}: {m}" for c, m in failures)
        emit("FAIL", codes, detail)
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
    exit 1
    ;;
  EXPECTED_MISSING)
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
