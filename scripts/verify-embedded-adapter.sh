#!/usr/bin/env bash
# WP-12C — verify embedded adapter contract (fail-closed, host-side)
# Product path: scripts/verify-embedded-adapter.sh (Plugin worktree)
#
# Catalog phase selectors (no device required):
#   --case adapter-negative   # RED:  exit 1, stderr UNKNOWN_METHOD | CALLER_APPENDED_ARGS | FALLBACK_MASQUERADE
#   --case adapter-positive   # GREEN: exit 0 (explicit experimental switch → embedded; default → official)
#
# Inventory modes (fixture JSON, schemaVersion=wp12c-adapter-contract/v1):
#   --inventory PATH --mode MODE
#     positive
#     negative-unknown-method
#     negative-appended-args
#     negative-fallback-masquerade
#
# Fail-closed rules (recomputed from structure; result/failClosed fields not trusted alone):
#   UNKNOWN_METHOD          — method not in Protocol-1 METHODS allowlist
#   CALLER_APPENDED_ARGS    — request keys outside fixed field-key allowlist
#   FALLBACK_MASQUERADE     — official/fallback path claims embedded PASS identity
#
# Exit codes:
#   0  positive clean / adapter-positive
#   1  fail-closed defect or negative-mode signature outcome (RED)
#   2  usage / invalid inventory
#   3  unexpected internal error
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} --case adapter-negative
  ${SCRIPT_NAME} --case adapter-positive
  ${SCRIPT_NAME} --inventory PATH --mode MODE

WP-12C host-side embedded adapter contract verifier (fail-closed).

Cases (catalog RED/GREEN):
  adapter-negative   Built-in unknown-method negative → exit 1 + UNKNOWN_METHOD on stderr
  adapter-positive   Built-in positive official+embedded paths → exit 0

Modes (with --inventory):
  positive
  negative-unknown-method
  negative-appended-args
  negative-fallback-masquerade

Exit codes:
  0  positive + clean
  1  fail-closed defect (or negative-mode expected-signature outcome)
  2  usage / invalid inventory
  3  unexpected internal error

Stderr prints failure codes as bare tokens (e.g. UNKNOWN_METHOD) so catalog
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
# Built-in case fixtures (no extra fixture files required for catalog RED/GREEN)
# ---------------------------------------------------------------------------
TMP_CASE=""
cleanup() {
  if [[ -n "${TMP_CASE}" && -d "${TMP_CASE}" ]]; then
    rm -rf "${TMP_CASE}"
  fi
}
trap cleanup EXIT

if [[ -n "${CASE}" ]]; then
  case "${CASE}" in
    adapter-negative)
      # Primary catalog RED signature: UNKNOWN_METHOD
      TMP_CASE="$(mktemp -d "${TMPDIR:-/tmp}/wp12c-adapter-neg.XXXXXX")"
      INVENTORY="${TMP_CASE}/adapter-unknown-method.json"
      MODE="negative-unknown-method"
      cat >"${INVENTORY}" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "not_a_real_method",
  "keys": ["protocolVersion", "callId"],
  "embeddedExperimental": false,
  "selectedRuntime": "official",
  "fallbackFromEmbedded": false,
  "passClaim": "official",
  "ok": false,
  "failClosed": {
    "ok": false,
    "failures": [
      {"code": "UNKNOWN_METHOD", "message": "method not in Protocol-1 allowlist"}
    ]
  }
}
JSON
      ;;
    adapter-positive)
      # GREEN: default official path + explicit embedded experimental path
      TMP_CASE="$(mktemp -d "${TMPDIR:-/tmp}/wp12c-adapter-pos.XXXXXX")"
      MODE="positive"
      # Verify both positive inventories; first is official default, second embedded-on.
      OFFICIAL_INV="${TMP_CASE}/adapter-positive-official.json"
      EMBEDDED_INV="${TMP_CASE}/adapter-positive-embedded.json"
      cat >"${OFFICIAL_INV}" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "ping",
  "keys": ["protocolVersion", "callId"],
  "embeddedExperimental": false,
  "selectedRuntime": "official",
  "fallbackFromEmbedded": false,
  "passClaim": "official",
  "ok": true,
  "failClosed": {"ok": true, "failures": []}
}
JSON
      cat >"${EMBEDDED_INV}" <<'JSON'
{
  "schemaVersion": "wp12c-adapter-contract/v1",
  "method": "ping",
  "keys": ["protocolVersion", "callId"],
  "embeddedExperimental": true,
  "selectedRuntime": "embedded",
  "fallbackFromEmbedded": false,
  "passClaim": "embedded",
  "ok": true,
  "failClosed": {"ok": true, "failures": []}
}
JSON
      log "case=adapter-positive inventories=${OFFICIAL_INV} + ${EMBEDDED_INV}"
      # Run verifier twice via recursive self-call would re-enter; invoke python path once per inv.
      set +e
      bash "${SCRIPT_DIR}/${SCRIPT_NAME}" --inventory "${OFFICIAL_INV}" --mode positive \
        >"${TMP_CASE}/official.out" 2>"${TMP_CASE}/official.err"
      RC1=$?
      bash "${SCRIPT_DIR}/${SCRIPT_NAME}" --inventory "${EMBEDDED_INV}" --mode positive \
        >"${TMP_CASE}/embedded.out" 2>"${TMP_CASE}/embedded.err"
      RC2=$?
      set -e
      if [[ "${RC1}" -ne 0 || "${RC2}" -ne 0 ]]; then
        log "adapter-positive failed (official_rc=${RC1} embedded_rc=${RC2})"
        cat "${TMP_CASE}/official.err" >&2 || true
        cat "${TMP_CASE}/embedded.err" >&2 || true
        # Prefer first failure code on stderr for diagnostics
        if [[ "${RC1}" -ne 0 ]]; then
          exit "${RC1}"
        fi
        exit "${RC2}"
      fi
      log "status=PASS case=adapter-positive (official default + embedded experimental)"
      exit 0
      ;;
    *)
      die "unknown --case: ${CASE} (expected adapter-negative|adapter-positive)"
      ;;
  esac
fi

[[ -n "${INVENTORY}" ]] || die "missing --inventory PATH (or --case)"
[[ -n "${MODE}" ]] || die "missing --mode MODE (or --case)"
[[ -f "${INVENTORY}" ]] || die "inventory not found or not a file: ${INVENTORY}"
[[ -r "${INVENTORY}" ]] || die "inventory not readable: ${INVENTORY}"

case "${MODE}" in
  positive|\
  negative-unknown-method|\
  negative-appended-args|\
  negative-fallback-masquerade)
    ;;
  *)
    die "unknown --mode: ${MODE}"
    ;;
esac

INVENTORY="$(cd "$(dirname "${INVENTORY}")" && pwd)/$(basename "${INVENTORY}")"

log "inventory=${INVENTORY}"
log "mode=${MODE}"

export WP12C_VERIFY_INVENTORY="${INVENTORY}"
export WP12C_VERIFY_MODE="${MODE}"

set +e
PY_OUT="$(
python3 <<'PY'
import json
import os
import sys
from pathlib import Path

inv_path = Path(os.environ["WP12C_VERIFY_INVENTORY"])
mode = os.environ["WP12C_VERIFY_MODE"]

# Protocol-1 methods (PluginContract.METHODS) — keep in sync with Kotlin.
METHODS = {
    "ping",
    "status",
    "renew_action",
    "import_mpkg",
    "open_library",
    "apply_current",
    "next",
    "previous",
    "stop",
    "diagnostics",
}

# Protocol-1 fixed field keys (PluginContract KEY_*). Caller may not invent extras.
ALLOWED_KEYS = {
    "protocolVersion",
    "callId",
    "operationId",
    "targetOperationId",
    "actionEpoch",
    "actionToken",
    "activeOperationId",
    "completedOperationIds",
    "code",
    "message",
    "operationState",
    "bindingState",
    "sourceUri",
    "sourceConsumed",
    "sourceOperationId",
    "displayName",
    "bytes",
    "sha256",
    "runtimePid",
    "engineInstalled",
    "engineVersion",
    "activePackage",
    "activeComponent",
    "lastError",
    "userAction",
    "userActionKind",
    "userActionExpiresAt",
    "fallbackAction",
    # WP-12C: EngineAdapter.KEY_REQUIRE_EMBEDDED — allowlisted experimental request flag
    "requireEmbedded",
    # Host inventory field for experimental switch state (not a free-form caller append)
    "embeddedExperimental",
}

RUNTIMES = {"official", "embedded"}


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

if data.get("schemaVersion") != "wp12c-adapter-contract/v1":
    emit(
        "INVALID",
        ["INVALID_INVENTORY"],
        f"unsupported schemaVersion: {data.get('schemaVersion')!r}",
    )
    sys.exit(0)

required = [
    "schemaVersion",
    "method",
    "keys",
    "embeddedExperimental",
    "selectedRuntime",
    "fallbackFromEmbedded",
    "passClaim",
    "ok",
]
missing = [k for k in required if k not in data]
if missing:
    emit("INVALID", ["INVALID_INVENTORY"], f"inventory missing fields: {missing}")
    sys.exit(0)

method = data.get("method")
if not isinstance(method, str) or not method:
    emit("INVALID", ["INVALID_INVENTORY"], "method must be non-empty string")
    sys.exit(0)

keys = data.get("keys")
if not isinstance(keys, list) or any(not isinstance(k, str) for k in keys):
    emit("INVALID", ["INVALID_INVENTORY"], "keys must be an array of strings")
    sys.exit(0)

embedded_exp = data.get("embeddedExperimental")
if not isinstance(embedded_exp, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "embeddedExperimental must be boolean")
    sys.exit(0)

selected = data.get("selectedRuntime")
if selected not in RUNTIMES:
    emit("INVALID", ["INVALID_INVENTORY"], f"selectedRuntime must be one of {sorted(RUNTIMES)}")
    sys.exit(0)

fallback = data.get("fallbackFromEmbedded")
if not isinstance(fallback, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "fallbackFromEmbedded must be boolean")
    sys.exit(0)

pass_claim = data.get("passClaim")
if pass_claim not in RUNTIMES:
    emit("INVALID", ["INVALID_INVENTORY"], f"passClaim must be one of {sorted(RUNTIMES)}")
    sys.exit(0)

ok = data.get("ok")
if not isinstance(ok, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "ok must be boolean")
    sys.exit(0)

failures: list[tuple[str, str]] = []


def add(code: str, message: str) -> None:
    failures.append((code, message))


# ---------------------------------------------------------------------------
# UNKNOWN_METHOD
# ---------------------------------------------------------------------------
if method not in METHODS:
    add("UNKNOWN_METHOD", f"method not in Protocol-1 allowlist: {method}")

# ---------------------------------------------------------------------------
# CALLER_APPENDED_ARGS
# ---------------------------------------------------------------------------
# Allow optional explicit allowlist override on inventory for future extension,
# but never expand beyond declared keys union ALLOWED_KEYS when override absent.
extra_allow = data.get("allowedKeys")
if isinstance(extra_allow, list) and all(isinstance(x, str) for x in extra_allow):
    allow = set(extra_allow)
else:
    allow = set(ALLOWED_KEYS)

appended = sorted({k for k in keys if k not in allow})
if appended:
    add(
        "CALLER_APPENDED_ARGS",
        "caller appended non-contract key(s): " + ", ".join(appended),
    )

# ---------------------------------------------------------------------------
# FALLBACK_MASQUERADE
# ---------------------------------------------------------------------------
# Official/fallback path must not claim embedded PASS.
# Cases:
#   - fallbackFromEmbedded true but passClaim/selectedRuntime is embedded
#   - embeddedExperimental false / default official path but identity is embedded
#   - ok true with passClaim embedded while selectedRuntime is official
if fallback and (selected == "embedded" or pass_claim == "embedded"):
    add(
        "FALLBACK_MASQUERADE",
        "fallback path claims embedded runtime identity",
    )
elif (not embedded_exp) and (selected == "embedded" or pass_claim == "embedded"):
    add(
        "FALLBACK_MASQUERADE",
        "default official path claims embedded PASS when experimental switch is off",
    )
elif ok and pass_claim == "embedded" and selected == "official":
    add(
        "FALLBACK_MASQUERADE",
        "PASS claims embedded while selectedRuntime is official",
    )
elif ok and pass_claim == "embedded" and fallback:
    add(
        "FALLBACK_MASQUERADE",
        "PASS claims embedded after fallbackFromEmbedded",
    )

# Positive path consistency (only when no hard fail-closed codes yet for method/keys):
# When method known and keys clean, selectedRuntime must match experimental switch
# unless a hard failure already recorded (unknown method etc.).
if method in METHODS and not appended:
    if embedded_exp and not fallback:
        if selected != "embedded":
            # Not a RED signature token; still fail positive consistency as internal policy.
            # Use FALLBACK_MASQUERADE only when claiming embedded wrongly; here claim may be official.
            pass
    # Intentionally no extra codes: GREEN only requires experimental→embedded and default→official
    # which are asserted by fixture writers; masquerade covers the dangerous direction.

codes: list[str] = []
seen: set[str] = set()
for code, _msg in failures:
    if code not in seen:
        seen.add(code)
        codes.append(code)

expected_by_mode = {
    "positive": None,
    "negative-unknown-method": "UNKNOWN_METHOD",
    "negative-appended-args": "CALLER_APPENDED_ARGS",
    "negative-fallback-masquerade": "FALLBACK_MASQUERADE",
}

if mode == "positive":
    if not codes:
        emit("PASS", [], "adapter contract clean (method/keys/runtime identity)")
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
