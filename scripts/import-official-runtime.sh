#!/usr/bin/env bash
# WP-12A — official APK runtime import inventory
# Product path: scripts/import-official-runtime.sh (Plugin worktree)
#
# Produces out/inventory.json conforming to runtime-import/manifest-map.schema.json
# (schemaVersion=wp12a-manifest-map/v1): manifest, DEX, resources, authorities,
# permissions, components, failClosed. Static analysis only; does not install
# or run the APK.
#
# Dependencies (at least one APK inspector required):
#   - aapt   (Android SDK build-tools)  preferred for badging + xmltree + list + resources
#   - aapt2  (Android SDK build-tools)  fallback for badging / dump
#   - apkanalyzer (Android SDK cmdline-tools) optional enrichment only
#   - shasum or sha256sum               required for sha256
#   - python3                           required for JSON assembly / parsing
#   - unzip                             required for DEX/manifest/arsc extraction
#
# Usage:
#   import-official-runtime.sh --apk PATH --out DIR
#   import-official-runtime.sh --help
#
# Exit codes:
#   0  success (inventory.json written; failClosed may still report defects)
#   1  usage / missing args / missing APK / no usable tools / critical dump failure
#   2  unexpected internal error
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --apk PATH --out DIR

Dump a static runtime-import inventory (wp12a-manifest-map/v1) for an
official (or candidate) APK.

Options:
  --apk PATH   Path to the APK file (required)
  --out DIR    Output directory; writes inventory.json (required)
  -h, --help   Show this help and exit

Dependencies: aapt and/or aapt2 (and optionally apkanalyzer), python3,
shasum|sha256sum, unzip. See header comments for details.
EOF
}

log()  { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

APK=""
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apk)
      [[ $# -ge 2 ]] || die "--apk requires a path"
      APK="$2"
      shift 2
      ;;
    --out)
      [[ $# -ge 2 ]] || die "--out requires a directory"
      OUT="$2"
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

[[ -n "${APK}" ]] || die "missing --apk PATH"
[[ -n "${OUT}" ]] || die "missing --out DIR"
[[ -f "${APK}" ]] || die "apk not found or not a file: ${APK}"
[[ -r "${APK}" ]] || die "apk not readable: ${APK}"

# Resolve absolute APK path for stable inventory fields
APK="$(cd "$(dirname "${APK}")" && pwd)/$(basename "${APK}")"

# --- locate tools -----------------------------------------------------------
resolve_cmd() {
  local name="$1"
  if command -v "${name}" >/dev/null 2>&1; then
    command -v "${name}"
    return 0
  fi
  local sdk_root=""
  if [[ -n "${ANDROID_HOME:-}" ]]; then
    sdk_root="${ANDROID_HOME}"
  elif [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
    sdk_root="${ANDROID_SDK_ROOT}"
  elif [[ -d "${HOME}/Library/Android/sdk" ]]; then
    sdk_root="${HOME}/Library/Android/sdk"
  elif [[ -d "${HOME}/Android/Sdk" ]]; then
    sdk_root="${HOME}/Android/Sdk"
  fi
  if [[ -n "${sdk_root}" && -d "${sdk_root}/build-tools" ]]; then
    local bt
    # newest build-tools first
    while IFS= read -r bt; do
      if [[ -x "${bt}/${name}" ]]; then
        printf '%s\n' "${bt}/${name}"
        return 0
      fi
    done < <(find "${sdk_root}/build-tools" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V -r)
  fi
  if [[ -n "${sdk_root}" ]]; then
    local found
    found="$(find "${sdk_root}" -type f -name "${name}" 2>/dev/null | head -n 1 || true)"
    if [[ -n "${found}" && -x "${found}" ]]; then
      printf '%s\n' "${found}"
      return 0
    fi
  fi
  return 1
}

AAPT=""
AAPT2=""
APKANALYZER=""
AAPT="$(resolve_cmd aapt || true)"
AAPT2="$(resolve_cmd aapt2 || true)"
APKANALYZER="$(resolve_cmd apkanalyzer || true)"

if [[ -z "${AAPT}" && -z "${AAPT2}" && -z "${APKANALYZER}" ]]; then
  die "no APK inspector found (need aapt, aapt2, or apkanalyzer on PATH or under Android SDK)"
fi

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 is required to write inventory.json"
fi

if ! command -v unzip >/dev/null 2>&1; then
  die "unzip is required to extract DEX/manifest/arsc for hashing"
fi

sha256_of() {
  local f="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${f}" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${f}" | awk '{print $1}'
  else
    die "neither shasum nor sha256sum found"
  fi
}

mkdir -p "${OUT}"
OUT="$(cd "${OUT}" && pwd)"
WORKDIR="${OUT}/.wp12a-work"
rm -rf "${WORKDIR}"
mkdir -p "${WORKDIR}/extract"
trap 'rm -rf "${WORKDIR}"' EXIT

log "apk=${APK}"
log "out=${OUT}"
log "tools: aapt=${AAPT:-none} aapt2=${AAPT2:-none} apkanalyzer=${APKANALYZER:-none}"

# --- dump surfaces ----------------------------------------------------------
BADGING="${WORKDIR}/badging.txt"
XMLTREE="${WORKDIR}/manifest-xmltree.txt"
LISTING="${WORKDIR}/list.txt"
RESOURCES="${WORKDIR}/resources.txt"
APKANALYZER_LOG="${WORKDIR}/apkanalyzer.txt"
TOOLS_USED=()

dump_badging() {
  if [[ -n "${AAPT}" ]]; then
    if "${AAPT}" dump badging "${APK}" >"${BADGING}" 2>"${WORKDIR}/aapt-badging.err"; then
      TOOLS_USED+=("aapt:dump-badging")
      return 0
    fi
    log "aapt dump badging failed: $(tr '\n' ' ' <"${WORKDIR}/aapt-badging.err" | head -c 200)"
  fi
  if [[ -n "${AAPT2}" ]]; then
    if "${AAPT2}" dump badging "${APK}" >"${BADGING}" 2>"${WORKDIR}/aapt2-badging.err"; then
      TOOLS_USED+=("aapt2:dump-badging")
      return 0
    fi
    log "aapt2 dump badging failed: $(tr '\n' ' ' <"${WORKDIR}/aapt2-badging.err" | head -c 200)"
  fi
  return 1
}

dump_xmltree() {
  if [[ -n "${AAPT}" ]]; then
    if "${AAPT}" dump xmltree "${APK}" AndroidManifest.xml >"${XMLTREE}" 2>"${WORKDIR}/aapt-xmltree.err"; then
      TOOLS_USED+=("aapt:dump-xmltree")
      return 0
    fi
    log "aapt dump xmltree failed: $(tr '\n' ' ' <"${WORKDIR}/aapt-xmltree.err" | head -c 200)"
  fi
  if [[ -n "${AAPT2}" ]]; then
    if "${AAPT2}" dump xmltree --file AndroidManifest.xml "${APK}" >"${XMLTREE}" 2>"${WORKDIR}/aapt2-xmltree.err"; then
      TOOLS_USED+=("aapt2:dump-xmltree")
      return 0
    fi
    if "${AAPT2}" dump xmltree "${APK}" AndroidManifest.xml >"${XMLTREE}" 2>>"${WORKDIR}/aapt2-xmltree.err"; then
      TOOLS_USED+=("aapt2:dump-xmltree")
      return 0
    fi
    log "aapt2 dump xmltree failed"
  fi
  return 1
}

dump_list() {
  if [[ -n "${AAPT}" ]]; then
    if "${AAPT}" list "${APK}" >"${LISTING}" 2>"${WORKDIR}/aapt-list.err"; then
      TOOLS_USED+=("aapt:list")
      return 0
    fi
  fi
  if unzip -Z1 "${APK}" >"${LISTING}" 2>"${WORKDIR}/unzip-list.err"; then
    TOOLS_USED+=("unzip:list")
    return 0
  fi
  return 1
}

dump_resources() {
  if [[ -n "${AAPT}" ]]; then
    if "${AAPT}" dump resources "${APK}" >"${RESOURCES}" 2>"${WORKDIR}/aapt-resources.err"; then
      TOOLS_USED+=("aapt:dump-resources")
      return 0
    fi
    log "aapt dump resources failed: $(tr '\n' ' ' <"${WORKDIR}/aapt-resources.err" | head -c 200)"
  fi
  if [[ -n "${AAPT2}" ]]; then
    if "${AAPT2}" dump resources "${APK}" >"${RESOURCES}" 2>"${WORKDIR}/aapt2-resources.err"; then
      TOOLS_USED+=("aapt2:dump-resources")
      return 0
    fi
    log "aapt2 dump resources failed"
  fi
  : >"${RESOURCES}"
  return 1
}

# optional apkanalyzer enrichment (non-fatal)
if [[ -n "${APKANALYZER}" ]]; then
  {
    echo "# apkanalyzer optional probe"
    if [[ -z "${ANDROID_HOME:-}" && -z "${ANDROID_SDK_ROOT:-}" ]]; then
      if [[ -d "${HOME}/Library/Android/sdk" ]]; then
        export ANDROID_HOME="${HOME}/Library/Android/sdk"
        export ANDROID_SDK_ROOT="${ANDROID_HOME}"
      elif [[ -d "${HOME}/Android/Sdk" ]]; then
        export ANDROID_HOME="${HOME}/Android/Sdk"
        export ANDROID_SDK_ROOT="${ANDROID_HOME}"
      fi
    fi
    "${APKANALYZER}" apk summary "${APK}" 2>&1 || true
    echo "---"
    "${APKANALYZER}" manifest application-id "${APK}" 2>&1 || true
    echo "---"
    "${APKANALYZER}" manifest permissions "${APK}" 2>&1 || true
  } >"${APKANALYZER_LOG}" || true
  if grep -qE '^[a-zA-Z0-9_.]+$' "${APKANALYZER_LOG}" 2>/dev/null || grep -qi 'package' "${APKANALYZER_LOG}" 2>/dev/null; then
    if ! grep -qi 'IllegalStateException\|Cannot locate' "${APKANALYZER_LOG}" 2>/dev/null; then
      TOOLS_USED+=("apkanalyzer")
    else
      log "apkanalyzer present but unusable (SDK/build-tools resolution failed); continuing with aapt/aapt2"
    fi
  else
    log "apkanalyzer present but produced no usable output; continuing with aapt/aapt2"
  fi
fi

if dump_badging; then
  :
else
  die "critical failure: could not dump badging via aapt/aapt2"
fi

if dump_xmltree; then
  :
else
  die "critical failure: could not dump AndroidManifest.xml via aapt/aapt2"
fi

if ! dump_list; then
  log "warning: could not list APK entries; dex inventory may be incomplete"
  : >"${LISTING}"
fi

if ! dump_resources; then
  log "warning: could not dump resources; resource entries will be empty (idIndex empty)"
fi

# --- extract zip members for content hashes ---------------------------------
EXTRACT_DIR="${WORKDIR}/extract"
# Extract known members if present (quiet; non-fatal missing)
unzip -qo "${APK}" "AndroidManifest.xml" "resources.arsc" "classes*.dex" -d "${EXTRACT_DIR}" 2>"${WORKDIR}/unzip-extract.err" || true
# Also try root-level multi-dex names that globs may miss on some unzip
for n in classes.dex classes2.dex classes3.dex classes4.dex classes5.dex; do
  if [[ ! -f "${EXTRACT_DIR}/${n}" ]]; then
    unzip -qo "${APK}" "${n}" -d "${EXTRACT_DIR}" 2>/dev/null || true
  fi
done

SHA256="$(sha256_of "${APK}")"
log "sha256=${SHA256}"

MANIFEST_SHA256=""
if [[ -f "${EXTRACT_DIR}/AndroidManifest.xml" ]]; then
  MANIFEST_SHA256="$(sha256_of "${EXTRACT_DIR}/AndroidManifest.xml")"
else
  log "warning: AndroidManifest.xml not extracted; manifest.sha256 will be zeros placeholder"
  MANIFEST_SHA256="0000000000000000000000000000000000000000000000000000000000000000"
fi

ARSC_SHA256=""
if [[ -f "${EXTRACT_DIR}/resources.arsc" ]]; then
  ARSC_SHA256="$(sha256_of "${EXTRACT_DIR}/resources.arsc")"
else
  ARSC_SHA256=""
fi

# Build DEX meta TSV: name\tsha256\tsizeBytes
DEX_META="${WORKDIR}/dex-meta.tsv"
: >"${DEX_META}"
# Discover dex from extract dir + listing
{
  if [[ -d "${EXTRACT_DIR}" ]]; then
    find "${EXTRACT_DIR}" -maxdepth 1 -type f -name 'classes*.dex' -print 2>/dev/null || true
  fi
} >"${WORKDIR}/dex-paths.txt"

# Also record names from listing for ones we failed to extract
while IFS= read -r line; do
  entry="$(echo "${line}" | awk '{print $1}' | sed 's|^\./||')"
  base="$(basename "${entry}")"
  if [[ "${base}" =~ ^classes([2-9]|[1-9][0-9]+)?\.dex$ ]] || [[ "${base}" == "classes.dex" ]]; then
    if [[ ! -f "${EXTRACT_DIR}/${base}" ]]; then
      unzip -qo "${APK}" "${entry}" -d "${EXTRACT_DIR}" 2>/dev/null || \
        unzip -qo "${APK}" "${base}" -d "${EXTRACT_DIR}" 2>/dev/null || true
      # if nested path, move to extract root
      if [[ -f "${EXTRACT_DIR}/${entry}" && ! -f "${EXTRACT_DIR}/${base}" ]]; then
        mv "${EXTRACT_DIR}/${entry}" "${EXTRACT_DIR}/${base}" 2>/dev/null || true
      fi
    fi
  fi
done <"${LISTING}"

for dex_path in "${EXTRACT_DIR}"/classes*.dex; do
  [[ -f "${dex_path}" ]] || continue
  bn="$(basename "${dex_path}")"
  dsha="$(sha256_of "${dex_path}")"
  dsz="$(wc -c <"${dex_path}" | tr -d ' ')"
  printf '%s\t%s\t%s\n' "${bn}" "${dsha}" "${dsz}" >>"${DEX_META}"
done

# --- parse + write inventory.json (wp12a-manifest-map/v1) -------------------
INVENTORY="${OUT}/inventory.json"
export WP12A_APK="${APK}"
export WP12A_SHA256="${SHA256}"
export WP12A_MANIFEST_SHA256="${MANIFEST_SHA256}"
export WP12A_ARSC_SHA256="${ARSC_SHA256}"
export WP12A_BADGING="${BADGING}"
export WP12A_XMLTREE="${XMLTREE}"
export WP12A_LISTING="${LISTING}"
export WP12A_RESOURCES="${RESOURCES}"
export WP12A_DEX_META="${DEX_META}"
export WP12A_OUT_JSON="${INVENTORY}"
printf '%s\n' "${TOOLS_USED[@]+"${TOOLS_USED[@]}"}" >"${WORKDIR}/tools-used.txt"
export WP12A_TOOLS_FILE="${WORKDIR}/tools-used.txt"

python3 <<'PY'
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

badging = Path(os.environ["WP12A_BADGING"]).read_text(errors="replace")
xmltree = Path(os.environ["WP12A_XMLTREE"]).read_text(errors="replace")
listing = Path(os.environ["WP12A_LISTING"]).read_text(errors="replace")
resources_dump = Path(os.environ["WP12A_RESOURCES"]).read_text(errors="replace")
dex_meta_text = Path(os.environ["WP12A_DEX_META"]).read_text(errors="replace")
tools = [ln.strip() for ln in Path(os.environ["WP12A_TOOLS_FILE"]).read_text().splitlines() if ln.strip()]
apk = os.environ["WP12A_APK"]
apk_sha256 = os.environ["WP12A_SHA256"]
manifest_sha256 = os.environ["WP12A_MANIFEST_SHA256"]
arsc_sha256 = os.environ.get("WP12A_ARSC_SHA256") or None
if arsc_sha256 == "":
    arsc_sha256 = None
out_json = Path(os.environ["WP12A_OUT_JSON"])

# ---------------------------------------------------------------------------
# Platform signature / signatureOrSystem allowlist (AOSP common set + binder)
# Used so uses of well-known platform signature perms stay clean if ever leveled.
# ---------------------------------------------------------------------------
PLATFORM_SIGNATURE_KNOWN = sorted({
    "android.permission.BIND_WALLPAPER",
    "android.permission.BIND_INPUT_METHOD",
    "android.permission.BIND_ACCESSIBILITY_SERVICE",
    "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE",
    "android.permission.BIND_VPN_SERVICE",
    "android.permission.BIND_DEVICE_ADMIN",
    "android.permission.BIND_JOB_SERVICE",
    "android.permission.BIND_REMOTEVIEWS",
    "android.permission.BIND_AUTOFILL_SERVICE",
    "android.permission.BIND_TEXT_SERVICE",
    "android.permission.BIND_VOICE_INTERACTION",
    "android.permission.BIND_CHOOSER_TARGET_SERVICE",
    "android.permission.BIND_CONDITION_PROVIDER_SERVICE",
    "android.permission.BIND_QUICK_SETTINGS_TILE",
    "android.permission.BIND_SCREENING_SERVICE",
    "android.permission.BIND_TELECOM_CONNECTION_SERVICE",
    "android.permission.BIND_VR_LISTENER_SERVICE",
    "android.permission.BIND_CARRIER_SERVICES",
    "android.permission.BIND_CARRIER_MESSAGING_SERVICE",
    "android.permission.BIND_INCALL_SERVICE",
    "android.permission.BIND_CONNECTION_SERVICE",
    "android.permission.BIND_PRINT_SERVICE",
    "android.permission.BIND_NFC_SERVICE",
    "android.permission.BIND_DREAM_SERVICE",
    "android.permission.BIND_TV_INPUT",
    "android.permission.BIND_ROUTE_PROVIDER",
    "android.permission.BIND_MIDI_DEVICE_SERVICE",
    "android.permission.DUMP",
    "android.permission.STATUS_BAR",
    "android.permission.STATUS_BAR_SERVICE",
    "android.permission.FORCE_STOP_PACKAGES",
    "android.permission.DELETE_PACKAGES",
    "android.permission.INSTALL_PACKAGES",
    "android.permission.CLEAR_APP_USER_DATA",
    "android.permission.CHANGE_COMPONENT_ENABLED_STATE",
    "android.permission.INTERACT_ACROSS_USERS",
    "android.permission.INTERACT_ACROSS_USERS_FULL",
    "android.permission.MANAGE_USERS",
    "android.permission.WRITE_SECURE_SETTINGS",
    "android.permission.READ_LOGS",
    "android.permission.PACKAGE_USAGE_STATS",
    "android.permission.UPDATE_DEVICE_STATS",
    "android.permission.BATTERY_STATS",
    "android.permission.ACCESS_SURFACE_FLINGER",
    "android.permission.READ_FRAME_BUFFER",
    "android.permission.INJECT_EVENTS",
    "android.permission.SET_ACTIVITY_WATCHER",
    "android.permission.SHUTDOWN",
    "android.permission.REBOOT",
    "android.permission.MASTER_CLEAR",
    "android.permission.MOVE_PACKAGE",
    "android.permission.CONFIRM_FULL_BACKUP",
    "android.permission.BACKUP",
    "android.permission.BIND_REMOTE_DISPLAY",
    "android.permission.CONTROL_KEYGUARD",
    "android.permission.CONTROL_VPN",
    "android.permission.MANAGE_APP_TOKENS",
    "android.permission.MANAGE_ACTIVITY_STACKS",
    "android.permission.MANAGE_DEVICE_ADMINS",
    "android.permission.NETWORK_STACK",
    "android.permission.NETWORK_SETTINGS",
    "android.permission.OBSERVE_GRANT_REVOKE_PERMISSIONS",
    "android.permission.PROVIDE_TRUST_AGENT",
    "android.permission.SET_TIME",
    "android.permission.SET_TIME_ZONE",
    "android.permission.UPDATE_APP_OPS_STATS",
    "android.permission.WATCH_APPOPS",
})

# protectionLevel base values (Android)
# normal=0, dangerous=1, signature=2, signatureOrSystem=3, internal=4
# flags may be OR'd (privileged=0x10, development=0x20, appop=0x40, ...)
def map_protection_level(raw) -> str:
    if raw is None:
        return "unknown"
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("normal", "dangerous", "signature", "signatureorsystem", "signature|system", "internal", "unknown"):
            if s in ("signatureorsystem", "signature|system"):
                return "signatureOrSystem"
            return s if s != "signatureorsystem" else "signatureOrSystem"
        # hex string?
        try:
            if s.startswith("0x"):
                raw = int(s, 16)
            else:
                raw = int(s)
        except ValueError:
            return "unknown"
    if not isinstance(raw, int):
        return "unknown"
    base = raw & 0xF
    return {
        0: "normal",
        1: "dangerous",
        2: "signature",
        3: "signatureOrSystem",
        4: "internal",
    }.get(base, "unknown")


def android_bool(raw) -> bool | None:
    """Parse aapt xmltree boolean: type 0x12 value 0x0 / 0xffffffff."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "1", "0xffffffff", "0xffffffffffffffff", "-1"):
        return True
    if s in ("false", "0", "0x0", "0x00000000"):
        return False
    try:
        v = int(s, 0)
        return v != 0
    except ValueError:
        return None


def resolve_name(name: str, pkg: str) -> str:
    if not name:
        return name
    if name.startswith("."):
        return (pkg + name) if pkg else name
    if "." not in name and pkg:
        return pkg + "." + name
    return name


def parse_hex_int(s: str):
    s = s.strip()
    try:
        return int(s, 0)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# badging: package / sdk / uses-permission
# ---------------------------------------------------------------------------
package_name = ""
version_name = ""
version_code = None
min_sdk = None
target_sdk = None

m = re.search(
    r"package:\s*name='([^']+)'(?:\s+versionCode='([^']*)')?(?:\s+versionName='([^']*)')?",
    badging,
)
if m:
    package_name = m.group(1) or ""
    if m.group(2):
        try:
            version_code = int(m.group(2))
        except ValueError:
            version_code = None
    version_name = m.group(3) or ""

m_sdk = re.search(r"sdkVersion:'(\d+)'", badging)
if m_sdk:
    min_sdk = int(m_sdk.group(1))
m_tsdk = re.search(r"targetSdkVersion:'(\d+)'", badging)
if m_tsdk:
    target_sdk = int(m_tsdk.group(1))

uses_from_badging: list[dict] = []
seen_uses: set[str] = set()
for line in badging.splitlines():
    pm = re.search(
        r"uses-permission(?:-sdk[^:]*)?:\s*name='([^']+)'(?:\s+maxSdkVersion='([^']*)')?",
        line,
    )
    if pm:
        p = pm.group(1)
        if p in seen_uses:
            continue
        seen_uses.add(p)
        max_sdk = None
        if pm.group(2):
            try:
                max_sdk = int(pm.group(2))
            except ValueError:
                max_sdk = None
        uses_from_badging.append({"name": p, "maxSdkVersion": max_sdk})

# ---------------------------------------------------------------------------
# xmltree parse: permissions, components, application process, sdk fallback
# ---------------------------------------------------------------------------
# Attribute patterns (aapt dump xmltree)
#   A: android:name(0x01010003)="foo" (Raw: "foo")
#   A: android:protectionLevel(0x01010009)=(type 0x11)0x2
#   A: android:exported(0x01010010)=(type 0x12)0x0
#   A: package="io..." (Raw: "...")
attr_str_re = re.compile(
    r'A:\s*(?:android:)?([A-Za-z:]+)\([^)]*\)="([^"]*)"'
)
attr_raw_re = re.compile(
    r'A:\s*(?:android:)?([A-Za-z:]+)(?:\([^)]*\))?=(?:\(type\s+(0x[0-9a-f]+)\)\s*)?(0x[0-9a-f]+|true|false|-?\d+|"[^"]*")',
    re.I,
)
# Simpler per-line extractors
def attr_string(line: str, local: str):
    # match android:local="value" or local="value"
    m = re.search(
        rf'A:\s*(?:android:)?{re.escape(local)}(?:\([^)]*\))?="([^"]*)"',
        line,
    )
    if m:
        return m.group(1)
    return None


def attr_typed_value(line: str, local: str):
    """Return (raw_token, type_hex_or_None) for typed aapt attrs."""
    m = re.search(
        rf'A:\s*(?:android:)?{re.escape(local)}(?:\([^)]*\))?='
        rf'(?:\(type\s+(0x[0-9a-f]+)\)\s*)?(0x[0-9a-f]+|-?\d+|true|false)',
        line,
        re.I,
    )
    if m:
        return m.group(2), m.group(1)
    m2 = re.search(
        rf'A:\s*(?:android:)?{re.escape(local)}(?:\([^)]*\))?="([^"]*)"',
        line,
        re.I,
    )
    if m2:
        return m2.group(1), None
    return None, None


elem_re = re.compile(r"^(\s*)E:\s*([A-Za-z0-9_.:-]+)")
app_re = re.compile(r"^(\s*)E:\s*application\b")
comp_kinds = {
    "activity": "activities",
    "activity-alias": "activities",
    "service": "services",
    "receiver": "receivers",
    "provider": "providers",
}

# Fallbacks from xmltree package / uses-sdk
if not package_name:
    m2 = re.search(r'package="([^"]+)"', xmltree)
    if m2:
        package_name = m2.group(1)
if not version_name:
    m3 = re.search(r'android:versionName(?:\([^)]*\))?="([^"]+)"', xmltree)
    if m3:
        version_name = m3.group(1)
if version_code is None:
    m4 = re.search(
        r'android:versionCode(?:\([^)]*\))?=\(type\s+0x10\)(0x[0-9a-f]+)',
        xmltree,
        re.I,
    )
    if m4:
        version_code = int(m4.group(1), 16)

if min_sdk is None:
    m5 = re.search(
        r'android:minSdkVersion(?:\([^)]*\))?=\(type\s+0x10\)(0x[0-9a-f]+)',
        xmltree,
        re.I,
    )
    if m5:
        min_sdk = int(m5.group(1), 16)
if target_sdk is None:
    m6 = re.search(
        r'android:targetSdkVersion(?:\([^)]*\))?=\(type\s+0x10\)(0x[0-9a-f]+)',
        xmltree,
        re.I,
    )
    if m6:
        target_sdk = int(m6.group(1), 16)

# Defaults if still missing (schema requires integers >= 1)
if min_sdk is None:
    min_sdk = 1
if target_sdk is None:
    target_sdk = min_sdk

declared_perms: list[dict] = []
uses_from_xml: list[dict] = []
seen_declared: set[str] = set()
seen_uses_xml: set[str] = set()

components = {
    "activities": [],
    "services": [],
    "receivers": [],
    "providers": [],
}
seen_comp: dict[str, set[str]] = {k: set() for k in components}

authorities: list[dict] = []
seen_auth_rows: set[tuple] = set()

application_process = None
in_application = False
app_indent = None

# Generic element stack for scoped permission / component parsing
# pending open element: kind, indent, attrs dict, has_intent_filter
pending = None  # type: dict | None


def flush_pending():
    global pending
    if not pending:
        return
    kind = pending["kind"]
    attrs = pending["attrs"]
    name = attrs.get("name")
    if kind == "permission":
        if name and name not in seen_declared:
            seen_declared.add(name)
            pl_raw = attrs.get("protectionLevel")
            if pl_raw is None:
                level = "normal"  # Android default for permission
            else:
                # may be hex int string
                try:
                    level = map_protection_level(int(str(pl_raw), 0))
                except ValueError:
                    level = map_protection_level(pl_raw)
            declared_perms.append({"name": name, "protectionLevel": level})
    elif kind == "uses-permission":
        if name and name not in seen_uses_xml:
            seen_uses_xml.add(name)
            max_sdk = attrs.get("maxSdkVersion")
            max_sdk_i = None
            if max_sdk is not None:
                try:
                    max_sdk_i = int(str(max_sdk), 0)
                except ValueError:
                    max_sdk_i = None
            uses_from_xml.append({"name": name, "maxSdkVersion": max_sdk_i})
    elif kind in comp_kinds:
        bucket = comp_kinds[kind]
        if not name:
            pending = None
            return
        full = resolve_name(name, package_name)
        if full in seen_comp[bucket]:
            pending = None
            return
        seen_comp[bucket].add(full)
        exp = attrs.get("exported")
        if exp is None:
            # Infer: true if intent-filter present (legacy default), else false
            exp = bool(pending.get("has_intent_filter"))
        else:
            exp = bool(exp)
        entry = {
            "name": full,
            "exported": exp,
            "process": attrs.get("process"),
            "permission": attrs.get("permission"),
        }
        if bucket == "providers":
            auth_raw = attrs.get("authorities") or ""
            auth_list = [a.strip() for a in auth_raw.split(";") if a.strip()]
            entry["authorities"] = auth_list
            grant = attrs.get("grantUriPermissions")
            if grant is None:
                grant = False
            for a in auth_list:
                key = (a, full)
                if key not in seen_auth_rows:
                    seen_auth_rows.add(key)
                    authorities.append({
                        "authority": a,
                        "componentName": full,
                        "exported": exp,
                        "grantUriPermissions": bool(grant),
                    })
        components[bucket].append(entry)
    pending = None


lines = xmltree.splitlines()
for line in lines:
    em = elem_re.match(line)
    if em:
        ind = len(em.group(1))
        ename = em.group(2)

        # Leaving application?
        if in_application and app_indent is not None and ind <= app_indent and ename != "application":
            flush_pending()
            in_application = False
            app_indent = None

        # New element closes pending if at same-or-shallower indent
        if pending is not None and ind <= pending["indent"]:
            flush_pending()

        am = app_re.match(line)
        if am and not in_application:
            in_application = True
            app_indent = len(am.group(1))
            pending = {
                "kind": "application",
                "indent": app_indent,
                "attrs": {},
                "has_intent_filter": False,
            }
            continue

        if ename in ("permission", "uses-permission", "uses-permission-sdk-23"):
            kind = "uses-permission" if ename.startswith("uses-permission") else "permission"
            pending = {
                "kind": kind,
                "indent": ind,
                "attrs": {},
                "has_intent_filter": False,
            }
            continue

        if ename in comp_kinds and in_application:
            pending = {
                "kind": ename,
                "indent": ind,
                "attrs": {},
                "has_intent_filter": False,
            }
            continue

        if pending and ename == "intent-filter" and ind > pending["indent"]:
            pending["has_intent_filter"] = True
            continue

        # Nested elements under pending that are not interesting: leave pending open
        continue

    # Attribute lines for pending element
    if pending is None:
        continue
    # Only attrs nested under pending (indent > pending indent)
    lead = len(line) - len(line.lstrip(" "))
    if lead <= pending["indent"]:
        continue

    # String attrs
    for key in ("name", "authorities", "permission", "process"):
        # process may be android:process
        val = attr_string(line, key)
        if val is not None and key not in pending["attrs"]:
            pending["attrs"][key] = val

    # package on manifest — handled elsewhere
    # Typed: exported, grantUriPermissions, protectionLevel, maxSdkVersion
    for key in ("exported", "grantUriPermissions"):
        token, _typ = attr_typed_value(line, key)
        if token is not None and key not in pending["attrs"]:
            b = android_bool(token)
            if b is not None:
                pending["attrs"][key] = b

    token, _typ = attr_typed_value(line, "protectionLevel")
    if token is not None and "protectionLevel" not in pending["attrs"]:
        pending["attrs"]["protectionLevel"] = token

    token, _typ = attr_typed_value(line, "maxSdkVersion")
    if token is not None and "maxSdkVersion" not in pending["attrs"]:
        pending["attrs"]["maxSdkVersion"] = token

    # application process
    if pending["kind"] == "application":
        proc = attr_string(line, "process")
        if proc is not None:
            application_process = proc

flush_pending()

# Merge uses: prefer badging order, fill maxSdk from xml when present
uses_map: dict[str, dict] = {}
for u in uses_from_badging:
    uses_map[u["name"]] = dict(u)
for u in uses_from_xml:
    if u["name"] in uses_map:
        if uses_map[u["name"]].get("maxSdkVersion") is None and u.get("maxSdkVersion") is not None:
            uses_map[u["name"]]["maxSdkVersion"] = u["maxSdkVersion"]
    else:
        uses_map[u["name"]] = dict(u)
uses_list = list(uses_map.values())

# ---------------------------------------------------------------------------
# DEX inventory from meta TSV (+ listing fallback without hash)
# ---------------------------------------------------------------------------
dex_entries = []
seen_dex = set()
for line in dex_meta_text.splitlines():
    parts = line.split("\t")
    if len(parts) != 3:
        continue
    name, dsha, dsz = parts
    if not re.fullmatch(r"classes([2-9]|[1-9][0-9]+)?\.dex", name) and name != "classes.dex":
        # schema pattern: ^classes([2-9]|[1-9][0-9]+)?\.dex$
        # classes.dex: classes + optional empty group — pattern is classes([2-9]|[1-9][0-9]+)?\.dex
        # which matches classes.dex (optional group absent). Good.
        if not re.fullmatch(r"classes([2-9]|[1-9][0-9]+)?\.dex", name):
            continue
    if name in seen_dex:
        continue
    seen_dex.add(name)
    try:
        size_bytes = int(dsz)
    except ValueError:
        size_bytes = 0
    dex_entries.append({
        "name": name,
        "sha256": dsha.lower(),
        "sizeBytes": size_bytes,
    })

# Listing fallback: names only if extract missed them (sha of empty placeholder not OK —
# skip unhashed entries to avoid fake hashes; report count from extract only)
if not dex_entries:
    for line in listing.splitlines():
        entry = line.strip().lstrip("./")
        base = entry.split()[0] if entry else ""
        bn = base.split("/")[-1]
        if re.fullmatch(r"classes([2-9]|[1-9][0-9]+)?\.dex", bn) and bn not in seen_dex:
            # Cannot invent sha256; leave empty → MISSING_DEX if nothing else
            pass


def dex_key(e):
    m = re.match(r"classes(\d*)\.dex$", e["name"])
    if not m:
        return (1, e["name"])
    num = int(m.group(1) or "1")
    return (0, num)


dex_entries.sort(key=dex_key)
dex_obj = {"count": len(dex_entries), "entries": dex_entries}

# ---------------------------------------------------------------------------
# Resources from aapt dump resources
# ---------------------------------------------------------------------------
# Lines like:
#   spec resource 0x7f010000 io.wallpaperengine.weclient:anim/abc_fade_in: flags=0x00000000
spec_re = re.compile(
    r"spec resource (0x[0-9a-fA-F]+)\s+\S+:([^:/]+)/([^:]+):"
)
res_entries = []
id_index: dict[str, str] = {}
id_to_names: dict[str, list[str]] = {}
seen_res_keys: set[tuple] = set()

for line in resources_dump.splitlines():
    rm = spec_re.search(line)
    if not rm:
        continue
    rid = rm.group(1).lower()
    # normalize to 0x + 8 hex
    try:
        rid = f"0x{int(rid, 16):08x}"
    except ValueError:
        continue
    rtype = rm.group(2)
    rname = rm.group(3)
    key = (rid, rtype, rname)
    if key in seen_res_keys:
        continue
    seen_res_keys.add(key)
    qualified = f"{rtype}/{rname}"
    id_to_names.setdefault(rid, []).append(qualified)
    # Content hash: deterministic identity hash (resource table dump has no per-entry bytes)
    identity = f"{rid}:{qualified}".encode()
    rsha = hashlib.sha256(identity).hexdigest()
    res_entries.append({
        "id": rid,
        "type": rtype,
        "name": rname,
        "sha256": rsha,
    })

# idIndex only for unique IDs (built after conflict scan — still populate unique)
resource_id_conflicts = []
for rid, names in sorted(id_to_names.items()):
    uniq = list(dict.fromkeys(names))
    if len(uniq) > 1:
        resource_id_conflicts.append((rid, uniq))
    else:
        id_index[rid] = uniq[0]

resources_obj = {
    "arscSha256": arsc_sha256,
    "entries": res_entries,
    "idIndex": id_index,
}

# ---------------------------------------------------------------------------
# signatureKnown: platform set + APK-declared signature(-or-system) perms
# ---------------------------------------------------------------------------
signature_known_set = set(PLATFORM_SIGNATURE_KNOWN)
for d in declared_perms:
    if d["protectionLevel"] in ("signature", "signatureOrSystem"):
        signature_known_set.add(d["name"])
signature_known = sorted(signature_known_set)

permissions_obj = {
    "declared": declared_perms,
    "uses": uses_list,
    "signatureKnown": signature_known,
}

# ---------------------------------------------------------------------------
# failClosed scan (same rules as verify-imported-runtime.sh)
# ---------------------------------------------------------------------------
failures = []


def add_failure(code: str, message: str, detail: str | None = None):
    item = {"code": code, "message": message}
    if detail is not None:
        item["detail"] = detail
    failures.append(item)


# MISSING_DEX
dex_names = [e["name"] for e in dex_entries]
if dex_obj["count"] == 0 or not dex_entries:
    add_failure("MISSING_DEX", "dex.count == 0 or dex.entries is empty")
elif "classes.dex" not in dex_names:
    add_failure("MISSING_DEX", "no classes.dex entry in dex.entries")

# AUTHORITY_CONFLICT
auth_strings = [a["authority"] for a in authorities]
# also providers' authorities arrays
for p in components["providers"]:
    for a in p.get("authorities") or []:
        auth_strings.append(a)
counts = Counter(auth_strings)
dups = sorted([a for a, n in counts.items() if n > 1])
# Note: authority list includes both top-level authorities and provider lists,
# so each authority appears twice by design if we double-count. Only count
# top-level authorities[] for conflict (unique provider authorities).
auth_only = [a["authority"] for a in authorities]
counts = Counter(auth_only)
dups = sorted([a for a, n in counts.items() if n > 1])
if dups:
    add_failure(
        "AUTHORITY_CONFLICT",
        "duplicate authority string(s): " + ", ".join(dups),
        detail=",".join(dups),
    )

# UNKNOWN_SIGNATURE_PERMISSION
known = set(signature_known)
declared_level = {}
for d in declared_perms:
    declared_level[d["name"]] = d["protectionLevel"]
    if d["protectionLevel"] in ("signature", "signatureOrSystem") and d["name"] not in known:
        add_failure(
            "UNKNOWN_SIGNATURE_PERMISSION",
            f"declared signature permission not allowlisted: {d['name']}",
        )
for u in uses_list:
    name = u["name"]
    level = declared_level.get(name)
    if level in ("signature", "signatureOrSystem") and name not in known:
        if not any(
            f["code"] == "UNKNOWN_SIGNATURE_PERMISSION" and name in f["message"]
            for f in failures
        ):
            add_failure(
                "UNKNOWN_SIGNATURE_PERMISSION",
                f"uses signature permission not allowlisted: {name}",
            )

# RESOURCE_ID_CONFLICT
if resource_id_conflicts:
    dup_ids = [rid for rid, _ in resource_id_conflicts]
    add_failure(
        "RESOURCE_ID_CONFLICT",
        "duplicate resource id(s): " + ", ".join(dup_ids[:20])
        + ("..." if len(dup_ids) > 20 else ""),
        detail=str(len(dup_ids)),
    )

fail_closed = {
    "ok": len(failures) == 0,
    "failures": failures,
}

if not package_name:
    print("ERROR: failed to parse packageName from badging/xmltree", file=sys.stderr)
    sys.exit(1)

inventory = {
    "schemaVersion": "wp12a-manifest-map/v1",
    "packageName": package_name,
    "apkSha256": apk_sha256.lower(),
    "versionCode": version_code if isinstance(version_code, int) else 0,
    "versionName": version_name or "",
    "manifest": {
        "packageName": package_name,
        "applicationProcess": application_process,
        "minSdk": int(min_sdk),
        "targetSdk": int(target_sdk),
        "sha256": manifest_sha256.lower(),
    },
    "dex": dex_obj,
    "resources": resources_obj,
    "authorities": authorities,
    "permissions": permissions_obj,
    "components": components,
    "failClosed": fail_closed,
}

# Optional non-schema notes for operators (must NOT be in output — additionalProperties:false)
# Keep pure v1 only.

out_json.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n")
print(
    f"wrote {out_json} schemaVersion=wp12a-manifest-map/v1 "
    f"packageName={package_name} versionName={version_name} "
    f"dex={dex_obj['count']} resources={len(res_entries)} "
    f"authorities={len(authorities)} "
    f"declaredPerms={len(declared_perms)} usesPerms={len(uses_list)} "
    f"activities={len(components['activities'])} "
    f"services={len(components['services'])} "
    f"receivers={len(components['receivers'])} "
    f"providers={len(components['providers'])} "
    f"failClosed.ok={fail_closed['ok']} "
    f"tools={tools}",
    file=sys.stderr,
)
PY

# Validate required v1 keys + optional jsonschema if installed
python3 - "${INVENTORY}" <<'PY'
import json
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
data = json.loads(p.read_text())
required = [
    "schemaVersion", "packageName", "apkSha256", "manifest", "dex",
    "resources", "authorities", "permissions", "components", "failClosed",
]
missing = [k for k in required if k not in data]
if missing:
    raise SystemExit(f"inventory missing keys: {missing}")
if data.get("schemaVersion") != "wp12a-manifest-map/v1":
    raise SystemExit(f"bad schemaVersion: {data.get('schemaVersion')!r}")
if not re.fullmatch(r"[a-f0-9]{64}", data.get("apkSha256") or ""):
    raise SystemExit("apkSha256 must be 64-char lowercase hex")
manifest = data["manifest"]
for k in ("packageName", "minSdk", "targetSdk", "sha256"):
    if k not in manifest:
        raise SystemExit(f"manifest missing {k}")
dex = data["dex"]
if "count" not in dex or "entries" not in dex:
    raise SystemExit("dex requires count+entries")
res = data["resources"]
if "entries" not in res or "idIndex" not in res:
    raise SystemExit("resources requires entries+idIndex")
perms = data["permissions"]
for k in ("declared", "uses", "signatureKnown"):
    if k not in perms:
        raise SystemExit(f"permissions missing {k}")
comps = data["components"]
for k in ("activities", "services", "receivers", "providers"):
    if k not in comps:
        raise SystemExit(f"components missing {k}")
fc = data["failClosed"]
if "ok" not in fc or "failures" not in fc:
    raise SystemExit("failClosed requires ok+failures")

# Soft schema check via jsonschema if available
import os
found = None
env_schema = os.environ.get("WP12A_SCHEMA", "")
if env_schema and Path(env_schema).is_file():
    found = Path(env_schema)
else:
    here = p.resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / "runtime-import" / "manifest-map.schema.json"
        if cand.is_file():
            found = cand
            break
if found is not None:
    try:
        import jsonschema  # type: ignore
        schema = json.loads(found.read_text())
        jsonschema.validate(data, schema)
        print(f"inventory ok (jsonschema): {p}", file=sys.stderr)
    except ImportError:
        print(f"inventory ok (structural; jsonschema not installed): {p}", file=sys.stderr)
    except Exception as e:
        raise SystemExit(f"jsonschema validation failed: {e}")
else:
    print(f"inventory ok (structural): {p}", file=sys.stderr)
PY

log "done: ${INVENTORY}"
exit 0
