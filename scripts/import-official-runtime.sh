#!/usr/bin/env bash
# WP-12A — official APK runtime import inventory
# Product path: scripts/import-official-runtime.sh (Plugin worktree)
#
# Produces out/inventory.json with package metadata, declared components,
# dex listing, and APK sha256. Static analysis only; does not install or run.
#
# Dependencies (at least one APK inspector required):
#   - aapt   (Android SDK build-tools)  preferred for badging + xmltree + list
#   - aapt2  (Android SDK build-tools)  fallback for badging / dump
#   - apkanalyzer (Android SDK cmdline-tools) optional enrichment only
#   - shasum or sha256sum               required for sha256
#   - python3                           required for JSON assembly / parsing
#   - unzip (optional)                  fallback dex listing if aapt list fails
#
# Usage:
#   import-official-runtime.sh --apk PATH --out DIR
#   import-official-runtime.sh --help
#
# Exit codes:
#   0  success (inventory.json written)
#   1  usage / missing args / missing APK / no usable tools / critical dump failure
#   2  unexpected internal error
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --apk PATH --out DIR

Dump a static runtime-import inventory for an official (or candidate) APK.

Options:
  --apk PATH   Path to the APK file (required)
  --out DIR    Output directory; writes inventory.json (required)
  -h, --help   Show this help and exit

Dependencies: aapt and/or aapt2 (and optionally apkanalyzer), python3,
shasum|sha256sum. See header comments for details.
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
mkdir -p "${WORKDIR}"
trap 'rm -rf "${WORKDIR}"' EXIT

log "apk=${APK}"
log "out=${OUT}"
log "tools: aapt=${AAPT:-none} aapt2=${AAPT2:-none} apkanalyzer=${APKANALYZER:-none}"

# --- dump surfaces ----------------------------------------------------------
BADGING="${WORKDIR}/badging.txt"
XMLTREE="${WORKDIR}/manifest-xmltree.txt"
LISTING="${WORKDIR}/list.txt"
APKANALYZER_LOG="${WORKDIR}/apkanalyzer.txt"
TOOLS_USED=()
CRITICAL_OK=0

dump_badging() {
  if [[ -n "${AAPT}" ]]; then
    if "${AAPT}" dump badging "${APK}" >"${BADGING}" 2>"${WORKDIR}/aapt-badging.err"; then
      TOOLS_USED+=("aapt:dump-badging")
      return 0
    fi
    log "aapt dump badging failed: $(tr '\n' ' ' <"${WORKDIR}/aapt-badging.err" | head -c 200)"
  fi
  if [[ -n "${AAPT2}" ]]; then
    # aapt2 supports dump badging on modern build-tools
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
    # older aapt2 variants
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
  if command -v unzip >/dev/null 2>&1; then
    if unzip -Z1 "${APK}" >"${LISTING}" 2>"${WORKDIR}/unzip-list.err"; then
      TOOLS_USED+=("unzip:list")
      return 0
    fi
  fi
  return 1
}

# optional apkanalyzer enrichment (non-fatal)
if [[ -n "${APKANALYZER}" ]]; then
  {
    echo "# apkanalyzer optional probe"
    # Ensure SDK env if missing so apkanalyzer can find build-tools
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
  CRITICAL_OK=1
else
  die "critical failure: could not dump badging via aapt/aapt2"
fi

if dump_xmltree; then
  :
else
  # components empty but package/version still usable from badging — still fail critically
  # because inventory requires component arrays derived from manifest
  die "critical failure: could not dump AndroidManifest.xml via aapt/aapt2"
fi

if ! dump_list; then
  log "warning: could not list APK entries; dexFiles will be empty"
  : >"${LISTING}"
fi

SHA256="$(sha256_of "${APK}")"
log "sha256=${SHA256}"

# --- parse + write inventory.json -------------------------------------------
INVENTORY="${OUT}/inventory.json"
export WP12A_APK="${APK}"
export WP12A_SHA256="${SHA256}"
export WP12A_BADGING="${BADGING}"
export WP12A_XMLTREE="${XMLTREE}"
export WP12A_LISTING="${LISTING}"
export WP12A_OUT_JSON="${INVENTORY}"
# bash array → newline list for python
printf '%s\n' "${TOOLS_USED[@]+"${TOOLS_USED[@]}"}" >"${WORKDIR}/tools-used.txt"
export WP12A_TOOLS_FILE="${WORKDIR}/tools-used.txt"

python3 <<'PY'
import json
import os
import re
import sys
from pathlib import Path

badging = Path(os.environ["WP12A_BADGING"]).read_text(errors="replace")
xmltree = Path(os.environ["WP12A_XMLTREE"]).read_text(errors="replace")
listing = Path(os.environ["WP12A_LISTING"]).read_text(errors="replace")
tools = [ln.strip() for ln in Path(os.environ["WP12A_TOOLS_FILE"]).read_text().splitlines() if ln.strip()]
apk = os.environ["WP12A_APK"]
sha256 = os.environ["WP12A_SHA256"]
out_json = Path(os.environ["WP12A_OUT_JSON"])

package_name = ""
version_name = ""
version_code = None

# package: name='...' versionCode='...' versionName='...'
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
            version_code = m.group(2)
    version_name = m.group(3) or ""

if not package_name:
    # fallback from xmltree package="..."
    m2 = re.search(r'package="([^"]+)"', xmltree)
    if m2:
        package_name = m2.group(1)
if not version_name:
    m3 = re.search(r'android:versionName(?:\([^)]*\))?="([^"]+)"', xmltree)
    if m3:
        version_name = m3.group(1)

permissions = []
seen_perm = set()
for line in badging.splitlines():
    pm = re.search(r"uses-permission(?:-sdk[^:]*)?:\s*name='([^']+)'", line)
    if pm:
        p = pm.group(1)
        if p not in seen_perm:
            seen_perm.add(p)
            permissions.append(p)

def resolve_name(name: str, pkg: str) -> str:
    if not name:
        return name
    if name.startswith("."):
        return (pkg + name) if pkg else name
    if "." not in name and pkg:
        # bare class name relative to package
        return pkg + "." + name
    return name

# Parse components from xmltree: only under E: application
activities = []
services = []
providers = []
receivers = []
seen = {k: set() for k in ("activity", "service", "provider", "receiver")}

comp_re = re.compile(r"^(\s*)E:\s*(activity-alias|activity|service|receiver|provider)\b")
name_re = re.compile(r'A:\s*android:name(?:\([^)]*\))?="([^"]+)"')
app_re = re.compile(r"^(\s*)E:\s*application\b")
elem_re = re.compile(r"^(\s*)E:\s+")

in_application = False
app_indent = None
pending_kind = None
pending_indent = None

def add_comp(kind: str, name: str):
    name = resolve_name(name, package_name)
    if not name or name in seen[kind]:
        return
    seen[kind].add(name)
    if kind == "activity":
        activities.append(name)
    elif kind == "service":
        services.append(name)
    elif kind == "provider":
        providers.append(name)
    elif kind == "receiver":
        receivers.append(name)

for line in xmltree.splitlines():
    am = app_re.match(line)
    if am and not in_application:
        in_application = True
        app_indent = len(am.group(1))
        pending_kind = None
        continue

    if in_application:
        em = elem_re.match(line)
        if em:
            ind = len(em.group(1))
            if ind <= app_indent:
                # left application scope
                in_application = False
                app_indent = None
                pending_kind = None
                # fall through — may still match something else, but ignore outside app
            # if a new element starts at same or less indent than pending, clear pending
            if pending_kind is not None and ind <= pending_indent:
                pending_kind = None

    if not in_application:
        pending_kind = None
        continue

    cm = comp_re.match(line)
    if cm:
        kind = cm.group(2)
        if kind == "activity-alias":
            kind = "activity"
        pending_kind = kind
        pending_indent = len(cm.group(1))
        continue

    if pending_kind is not None:
        # only accept android:name that is a direct attribute of the component
        # (indent > pending_indent). First match wins.
        nm = name_re.search(line)
        if nm:
            # ensure this line is nested under the component
            lead = len(line) - len(line.lstrip(" "))
            if lead > pending_indent:
                add_comp(pending_kind, nm.group(1))
                pending_kind = None
            continue
        # stop waiting if we hit another element without finding name
        if elem_re.match(line):
            pending_kind = None

# dex files from listing
dex_files = []
for line in listing.splitlines():
    entry = line.strip().lstrip("./")
    # aapt list may show "classes.dex" or paths; unzip -Z1 same
    base = entry.split()[0] if entry else ""
    # normalize: take last path segment match for *.dex at archive root-ish
    if re.search(r"(^|/)classes\d*\.dex$", base) or re.fullmatch(r"classes\d*\.dex", base):
        # prefer basename for multi-dex at root
        bn = base.split("/")[-1]
        if bn not in dex_files:
            dex_files.append(bn)
    elif base.endswith(".dex") and "/" not in base.rstrip("/"):
        if base not in dex_files:
            dex_files.append(base)

# stable-ish order: classes.dex, classes2.dex, ...
def dex_key(n: str):
    m = re.match(r"classes(\d*)\.dex$", n)
    if not m:
        return (1, n)
    num = int(m.group(1) or "1")
    return (0, num)

dex_files.sort(key=dex_key)

if not package_name:
    print("ERROR: failed to parse packageName from badging/xmltree", file=sys.stderr)
    sys.exit(1)

inventory = {
    "packageName": package_name,
    "versionName": version_name,
    "permissions": permissions,
    "activities": activities,
    "services": services,
    "providers": providers,
    "receivers": receivers,
    "dexFiles": dex_files,
    "sha256": sha256,
    # draft-only extras (non-breaking for consumers that ignore unknown keys)
    "versionCode": version_code,
    "apkPath": apk,
    "toolsUsed": tools,
    "schema": "wp-12a-import-inventory/draft-1",
}

out_json.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n")
print(
    f"wrote {out_json} packageName={package_name} versionName={version_name} "
    f"perms={len(permissions)} activities={len(activities)} services={len(services)} "
    f"providers={len(providers)} receivers={len(receivers)} dex={len(dex_files)}",
    file=sys.stderr,
)
PY

# Validate required keys exist
python3 - "${INVENTORY}" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text())
required = [
    "packageName", "versionName", "permissions", "activities", "services",
    "providers", "receivers", "dexFiles", "sha256",
]
missing = [k for k in required if k not in data]
if missing:
    raise SystemExit(f"inventory missing keys: {missing}")
for k in ("permissions", "activities", "services", "providers", "receivers", "dexFiles"):
    if not isinstance(data[k], list):
        raise SystemExit(f"{k} must be an array")
if not data["packageName"] or not data["sha256"]:
    raise SystemExit("packageName and sha256 must be non-empty")
print(f"inventory ok: {p}", file=sys.stderr)
PY

log "done: ${INVENTORY}"
exit 0
