#!/usr/bin/env bash
# WP-12A — verify imported runtime inventory
# Product path: scripts/verify-imported-runtime.sh (Plugin worktree)
#
# Fail-closed static verifier for inventory.json produced by
# import-official-runtime.sh (draft-1 shape) or fixture inventories
# conforming to manifest-map.schema.json (schema shape).
#
# Scaffolded from verification runs/wp-12a-draft; fail-closed verifier.
#
# Usage:
#   verify-imported-runtime.sh --inventory PATH --mode MODE
#   verify-imported-runtime.sh --help
#
# Modes:
#   positive
#       Inventory must pass all fail-closed rules → exit 0.
#       Any rule fire → exit 1 with failure codes on stderr.
#   negative-missing-dex
#       Expect MISSING_DEX among failures → exit 1 (RED non-zero) + code on stderr.
#       If not detected → exit 1 with EXPECTED_FAILURE_NOT_FOUND (wrong signature).
#   negative-auth-conflict
#       Expect AUTHORITY_CONFLICT (same exit policy as above).
#   negative-unknown-signature-permission
#       Expect UNKNOWN_SIGNATURE_PERMISSION.
#   negative-resource-id-conflict
#       Expect RESOURCE_ID_CONFLICT.
#
# Fail-closed rules (always evaluated):
#   MISSING_DEX
#     - draft: empty/missing dexFiles, or no classes.dex entry
#     - schema: dex.count==0, empty dex.entries, or no classes.dex
#   AUTHORITY_CONFLICT
#     - duplicate authority strings (case-sensitive) in authorities[]
#   UNKNOWN_SIGNATURE_PERMISSION
#     - signature / signatureOrSystem permission name not in signatureKnown
#       (skipped when inventory lacks protectionLevel / signatureKnown)
#   RESOURCE_ID_CONFLICT
#     - duplicate resources.entries[].id (skipped when no resources map)
#
# Exit codes:
#   0  positive mode and inventory is clean (failClosed.ok equivalent)
#   1  fail-closed rule fired (positive), or expected negative signature
#      present / absent handling (always non-zero for negative modes when
#      inventory is structurally valid — RED records real non-zero + stderr)
#   2  usage error, missing args, unreadable inventory, JSON parse error,
#      or inventory missing required fields
#   3  unexpected internal error
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --inventory PATH --mode MODE

Verify a WP-12A runtime-import inventory (fail-closed).

Options:
  --inventory PATH   Path to inventory JSON (required)
  --mode MODE        One of:
                       positive
                       negative-missing-dex
                       negative-auth-conflict
                       negative-unknown-signature-permission
                       negative-resource-id-conflict
  -h, --help         Show this help and exit

Exit codes:
  0  positive + clean inventory
  1  fail-closed defect (or negative-mode expected-signature outcome)
  2  usage / invalid inventory / missing required fields
  3  unexpected internal error

Stderr always prints failure codes as bare tokens (e.g. MISSING_DEX) so
catalog failureSignaturePolicy can match stderr.
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
  negative-missing-dex|\
  negative-auth-conflict|\
  negative-unknown-signature-permission|\
  negative-resource-id-conflict)
    ;;
  *)
    die "unknown --mode: ${MODE}"
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 is required"
fi

# Resolve absolute path for stable logging
INVENTORY="$(cd "$(dirname "${INVENTORY}")" && pwd)/$(basename "${INVENTORY}")"

log "inventory=${INVENTORY}"
log "mode=${MODE}"

# Python does structural validation + fail-closed scan.
# Protocol on stdout (one line): STATUS|<comma-codes>|<message>
# Failure code tokens also printed alone on stderr for signature match.
# Exit of python: 0 structural+scan ok path; non-zero only for internal.
#
# Shell maps STATUS to process exit codes documented above.
export WP12A_VERIFY_INVENTORY="${INVENTORY}"
export WP12A_VERIFY_MODE="${MODE}"

set +e
PY_OUT="$(
python3 <<'PY'
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

inv_path = Path(os.environ["WP12A_VERIFY_INVENTORY"])
mode = os.environ["WP12A_VERIFY_MODE"]

def emit(status: str, codes: list[str], message: str) -> None:
    # bare tokens on stderr for failureSignaturePolicy
    for c in codes:
        print(c, file=sys.stderr)
    # machine line for the shell
    print(f"{status}|{','.join(codes)}|{message}")

try:
    raw = inv_path.read_text(encoding="utf-8")
    data = json.loads(raw)
except json.JSONDecodeError as e:
    emit("INVALID", ["INVALID_INVENTORY"], f"JSON parse error: {e}")
    sys.exit(0)
except OSError as e:
    emit("INVALID", ["INVALID_INVENTORY"], f"read error: {e}")
    sys.exit(0)

if not isinstance(data, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "inventory root must be a JSON object")
    sys.exit(0)

# Detect shape: schema (manifest-map) vs draft-1 importer
is_schema = (
    data.get("schemaVersion") == "wp12a-manifest-map/v1"
    or ("dex" in data and isinstance(data.get("dex"), dict))
    or ("manifest" in data and isinstance(data.get("manifest"), dict))
)

failures: list[tuple[str, str]] = []  # (code, message)

def add(code: str, message: str) -> None:
    failures.append((code, message))

# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------
if is_schema:
    required = [
        "schemaVersion",
        "packageName",
        "apkSha256",
        "manifest",
        "dex",
        "resources",
        "authorities",
        "permissions",
        "components",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        emit("INVALID", ["INVALID_INVENTORY"], f"schema inventory missing fields: {missing}")
        sys.exit(0)
    if data.get("schemaVersion") not in (None, "wp12a-manifest-map/v1"):
        # allow missing already handled; wrong const is invalid
        if data.get("schemaVersion") != "wp12a-manifest-map/v1":
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
    for key in ("manifest", "dex", "resources", "permissions", "components"):
        if not isinstance(data[key], dict):
            emit("INVALID", ["INVALID_INVENTORY"], f"{key} must be an object")
            sys.exit(0)
    if not isinstance(data["authorities"], list):
        emit("INVALID", ["INVALID_INVENTORY"], "authorities must be an array")
        sys.exit(0)
else:
    # draft-1 from import-official-runtime.sh
    required = [
        "packageName",
        "versionName",
        "permissions",
        "activities",
        "services",
        "providers",
        "receivers",
        "dexFiles",
        "sha256",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        emit("INVALID", ["INVALID_INVENTORY"], f"draft inventory missing fields: {missing}")
        sys.exit(0)
    if not isinstance(data["packageName"], str) or not data["packageName"]:
        emit("INVALID", ["INVALID_INVENTORY"], "packageName must be non-empty string")
        sys.exit(0)
    sha = data.get("sha256") or ""
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        emit("INVALID", ["INVALID_INVENTORY"], "sha256 must be 64-char lowercase hex")
        sys.exit(0)
    for key in (
        "permissions",
        "activities",
        "services",
        "providers",
        "receivers",
        "dexFiles",
    ):
        if not isinstance(data[key], list):
            emit("INVALID", ["INVALID_INVENTORY"], f"{key} must be an array")
            sys.exit(0)

# ---------------------------------------------------------------------------
# MISSING_DEX
# ---------------------------------------------------------------------------
def check_missing_dex() -> None:
    if is_schema:
        dex = data.get("dex") or {}
        entries = dex.get("entries")
        count = dex.get("count")
        if not isinstance(entries, list):
            add("MISSING_DEX", "dex.entries missing or not an array")
            return
        names = []
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("name"), str):
                names.append(e["name"])
            elif isinstance(e, str):
                names.append(e)
        if count is not None and isinstance(count, int) and count == 0:
            add("MISSING_DEX", "dex.count == 0")
            return
        if len(entries) == 0 or len(names) == 0:
            add("MISSING_DEX", "dex.entries is empty")
            return
        if "classes.dex" not in names:
            add("MISSING_DEX", "no classes.dex entry in dex.entries")
            return
    else:
        dex_files = data.get("dexFiles")
        if not isinstance(dex_files, list):
            add("MISSING_DEX", "dexFiles missing or not an array")
            return
        # empty dexFiles → fail
        if len(dex_files) == 0:
            add("MISSING_DEX", "dexFiles is empty")
            return
        names = [n for n in dex_files if isinstance(n, str) and n]
        if not names:
            add("MISSING_DEX", "dexFiles has no non-empty string names")
            return
        if "classes.dex" not in names:
            add("MISSING_DEX", "no classes.dex entry in dexFiles")
            return

# ---------------------------------------------------------------------------
# AUTHORITY_CONFLICT
# ---------------------------------------------------------------------------
def extract_authorities() -> list[str]:
    """Authority strings for conflict counting.

    Policy (FIXTURES.md): two or more authorities[].authority values equal.
    When top-level authorities[] is non-empty, use only that list (do not also
    re-count components.providers[].authorities — same authority on the same
    provider is listed in both places on full v1 inventories).

    When top-level is absent/empty, fall back to components.providers[].
    Pair-merge is not needed for the top-level-primary path; provider fallback
    expands multi-authority ";" strings.
    """
    auth_list: list[str] = []
    raw = data.get("authorities")
    if isinstance(raw, list) and len(raw) > 0:
        for item in raw:
            if isinstance(item, str) and item:
                auth_list.append(item)
            elif isinstance(item, dict):
                a = item.get("authority")
                if isinstance(a, str) and a:
                    auth_list.append(a)
        return auth_list
    # Fallback: schema components.providers[].authorities only when top-level empty
    comps = data.get("components")
    if isinstance(comps, dict):
        providers = comps.get("providers")
        if isinstance(providers, list):
            for p in providers:
                if not isinstance(p, dict):
                    continue
                aa = p.get("authorities")
                if isinstance(aa, list):
                    for a in aa:
                        if isinstance(a, str) and a:
                            auth_list.append(a)
                elif isinstance(aa, str) and aa:
                    for part in aa.split(";"):
                        part = part.strip()
                        if part:
                            auth_list.append(part)
    return auth_list

def check_authority_conflict() -> None:
    auth_list = extract_authorities()
    # No authorities field at all on draft inventory: only fire when at least
    # one authority is present (positive drafts without authorities stay clean).
    # negative-auth-conflict fixtures must supply authorities[].
    if not auth_list:
        # Draft importer inventories may omit authorities. Positive stays clean.
        # negative-auth-conflict fixtures must supply duplicate authorities[]
        # so EXPECTED_FAILURE_NOT_FOUND fires if they do not.
        return
    counts = Counter(auth_list)
    dups = sorted([a for a, n in counts.items() if n > 1])
    if dups:
        add(
            "AUTHORITY_CONFLICT",
            "duplicate authority string(s): " + ", ".join(dups),
        )

# ---------------------------------------------------------------------------
# UNKNOWN_SIGNATURE_PERMISSION
# ---------------------------------------------------------------------------
def check_unknown_signature_permission() -> None:
    perms = data.get("permissions")
    if perms is None:
        return
    # draft: permissions is list of strings — no protectionLevel → skip
    if isinstance(perms, list):
        # if items are objects with protectionLevel, still scan
        items = perms
        signature_known: set[str] = set()
        # optional top-level signatureKnown
        sk = data.get("signatureKnown")
        if isinstance(sk, list):
            signature_known = {x for x in sk if isinstance(x, str)}
        has_levels = any(isinstance(i, dict) and "protectionLevel" in i for i in items)
        if not has_levels:
            return
        for i in items:
            if not isinstance(i, dict):
                continue
            name = i.get("name")
            level = i.get("protectionLevel")
            if level in ("signature", "signatureOrSystem") and isinstance(name, str):
                if name not in signature_known:
                    add(
                        "UNKNOWN_SIGNATURE_PERMISSION",
                        f"signature permission not allowlisted: {name}",
                    )
        return
    if not isinstance(perms, dict):
        return
    declared = perms.get("declared") or []
    uses = perms.get("uses") or []
    known = perms.get("signatureKnown") or []
    if not isinstance(known, list):
        known = []
    signature_known = {x for x in known if isinstance(x, str)}
    # Build uses→level map only from declared; uses may lack level.
    # Policy (FIXTURES.md): declared OR uses with protectionLevel in
    # {signature, signatureOrSystem} whose name ∉ signatureKnown.
    declared_level: dict[str, str] = {}
    if isinstance(declared, list):
        for d in declared:
            if not isinstance(d, dict):
                continue
            name = d.get("name")
            level = d.get("protectionLevel")
            if isinstance(name, str) and isinstance(level, str):
                declared_level[name] = level
                if level in ("signature", "signatureOrSystem") and name not in signature_known:
                    add(
                        "UNKNOWN_SIGNATURE_PERMISSION",
                        f"declared signature permission not allowlisted: {name}",
                    )
    if isinstance(uses, list):
        for u in uses:
            if not isinstance(u, dict):
                continue
            name = u.get("name")
            if not isinstance(name, str):
                continue
            level = u.get("protectionLevel")
            if level is None:
                level = declared_level.get(name)
            if level in ("signature", "signatureOrSystem") and name not in signature_known:
                # avoid duplicate if already added from declared
                if not any(
                    c == "UNKNOWN_SIGNATURE_PERMISSION" and name in m
                    for c, m in failures
                ):
                    add(
                        "UNKNOWN_SIGNATURE_PERMISSION",
                        f"uses signature permission not allowlisted: {name}",
                    )

# ---------------------------------------------------------------------------
# RESOURCE_ID_CONFLICT
# ---------------------------------------------------------------------------
def check_resource_id_conflict() -> None:
    resources = data.get("resources")
    if resources is None:
        return
    entries = None
    if isinstance(resources, dict):
        entries = resources.get("entries")
    elif isinstance(resources, list):
        entries = resources
    else:
        return
    if not isinstance(entries, list) or not entries:
        return
    ids: list[str] = []
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("id"), str):
            ids.append(e["id"])
    counts = Counter(ids)
    dups = sorted([i for i, n in counts.items() if n > 1])
    if dups:
        add(
            "RESOURCE_ID_CONFLICT",
            "duplicate resource id(s): " + ", ".join(dups),
        )

check_missing_dex()
check_authority_conflict()
check_unknown_signature_permission()
check_resource_id_conflict()

# Stable unique codes in first-seen order
codes: list[str] = []
seen: set[str] = set()
for code, _msg in failures:
    if code not in seen:
        seen.add(code)
        codes.append(code)

expected_by_mode = {
    "positive": None,
    "negative-missing-dex": "MISSING_DEX",
    "negative-auth-conflict": "AUTHORITY_CONFLICT",
    "negative-unknown-signature-permission": "UNKNOWN_SIGNATURE_PERMISSION",
    "negative-resource-id-conflict": "RESOURCE_ID_CONFLICT",
}
expected = expected_by_mode[mode]

if mode == "positive":
    if not codes:
        emit("PASS", [], "inventory clean")
    else:
        detail = "; ".join(f"{c}: {m}" for c, m in failures)
        emit("FAIL", codes, detail)
    sys.exit(0)

# negative modes
assert expected is not None
if expected in seen:
    # RED wants non-zero + signature on stderr
    detail = "; ".join(f"{c}: {m}" for c, m in failures if c == expected)
    # emit expected code first for reliable signature match
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

# Parse STATUS|codes|message from last non-empty stdout line
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
CODES="${REST%%|*}"
MSG="${REST#*|}"
# If no second pipe, MSG may equal REST
if [[ "${REST}" == "${MSG}" && "${REST}" != *"|"* ]]; then
  CODES=""
  MSG="${REST}"
fi

log "status=${STATUS} codes=${CODES:-none} msg=${MSG}"

case "${STATUS}" in
  PASS)
    # positive clean
    exit 0
    ;;
  FAIL)
    # fail-closed defect present (positive or negative with expected code)
    exit 1
    ;;
  EXPECTED_MISSING)
    # negative mode but expected signature not detected
    exit 1
    ;;
  INVALID)
    exit 2
    ;;
  *)
    log "internal error: unknown status ${STATUS}"
    printf 'INTERNAL_ERROR\n' >&2
    exit 3
    ;;
esac
