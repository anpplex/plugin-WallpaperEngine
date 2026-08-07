#!/usr/bin/env bash
# WP-12B — official APK native/JNI library inventory
# Product path: scripts/import-native-libs.sh (Plugin worktree)
#
# Produces out/native-inventory.json conforming to
# runtime-import/native-libs.schema.json (schemaVersion=wp12b-native-libs/v1):
# per-ABI ELF map, SONAME/DT_NEEDED, transitive local-needed closure, failClosed.
# Static analysis only; does not install or run the APK. Never stages .so blobs.
#
# Dependencies:
#   - readelf  (prefer /opt/homebrew/opt/binutils/bin/readelf; else PATH)
#   - unzip, python3, shasum|sha256sum
#   - aapt or aapt2 (optional; packageName/version when available)
#
# Usage:
#   import-native-libs.sh --apk PATH --out DIR
#   import-native-libs.sh --help
#
# Exit codes:
#   0  success (native-inventory.json written; failClosed may still report defects)
#   1  usage / missing args / missing APK / no readelf / critical failure
#   2  unexpected internal error
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --apk PATH --out DIR

Dump a static native/JNI inventory (wp12b-native-libs/v1) for an official
(or candidate) APK: extract lib/**/*.so, readelf SONAME/NEEDED/machine,
write out/native-inventory.json. Prefer arm64-v8a as primary; include all ABIs.

Options:
  --apk PATH   Path to the APK file (required)
  --out DIR    Output directory; writes native-inventory.json (required)
  -h, --help   Show this help and exit

Dependencies: readelf (binutils), python3, unzip, shasum|sha256sum;
optional aapt/aapt2 for packageName/version.
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

APK="$(cd "$(dirname "${APK}")" && pwd)/$(basename "${APK}")"

# --- tools ------------------------------------------------------------------
READELF=""
if [[ -x /opt/homebrew/opt/binutils/bin/readelf ]]; then
  READELF="/opt/homebrew/opt/binutils/bin/readelf"
elif command -v readelf >/dev/null 2>&1; then
  READELF="$(command -v readelf)"
elif [[ -x /usr/local/opt/binutils/bin/readelf ]]; then
  READELF="/usr/local/opt/binutils/bin/readelf"
else
  die "readelf not found (install binutils; expected /opt/homebrew/opt/binutils/bin/readelf)"
fi

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 is required to write native-inventory.json"
fi
if ! command -v unzip >/dev/null 2>&1; then
  die "unzip is required to extract lib/**/*.so"
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
    while IFS= read -r bt; do
      if [[ -x "${bt}/${name}" ]]; then
        printf '%s\n' "${bt}/${name}"
        return 0
      fi
    done < <(find "${sdk_root}/build-tools" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V -r)
  fi
  return 1
}

AAPT="$(resolve_cmd aapt || true)"
AAPT2="$(resolve_cmd aapt2 || true)"

mkdir -p "${OUT}"
OUT="$(cd "${OUT}" && pwd)"
WORKDIR="${OUT}/.wp12b-native-work"
rm -rf "${WORKDIR}"
mkdir -p "${WORKDIR}/extract"
trap 'rm -rf "${WORKDIR}"' EXIT

log "apk=${APK}"
log "out=${OUT}"
log "tools: readelf=${READELF} aapt=${AAPT:-none} aapt2=${AAPT2:-none}"

APK_SHA="$(sha256_of "${APK}")"
log "apkSha256=${APK_SHA}"

# package / version (best-effort)
PACKAGE_NAME=""
VERSION_CODE=""
VERSION_NAME=""
BADGING="${WORKDIR}/badging.txt"
if [[ -n "${AAPT}" ]]; then
  "${AAPT}" dump badging "${APK}" >"${BADGING}" 2>/dev/null || true
elif [[ -n "${AAPT2}" ]]; then
  "${AAPT2}" dump badging "${APK}" >"${BADGING}" 2>/dev/null || true
fi
if [[ -s "${BADGING}" ]]; then
  # package: name='...' versionCode='...' versionName='...'
  PACKAGE_NAME="$(sed -n "s/^package: name='\\([^']*\\)'.*/\\1/p" "${BADGING}" | head -n1)"
  VERSION_CODE="$(sed -n "s/^package:.*versionCode='\\([^']*\\)'.*/\\1/p" "${BADGING}" | head -n1)"
  VERSION_NAME="$(sed -n "s/^package:.*versionName='\\([^']*\\)'.*/\\1/p" "${BADGING}" | head -n1)"
fi
if [[ -z "${PACKAGE_NAME}" ]]; then
  PACKAGE_NAME="unknown.package"
  log "WARN: could not resolve packageName from aapt; using ${PACKAGE_NAME}"
fi

# Extract only lib/**/*.so (keep zip paths)
log "extracting lib/**/*.so"
set +e
unzip -q -o "${APK}" "lib/*/*.so" -d "${WORKDIR}/extract" 2>"${WORKDIR}/unzip.err"
unzip_rc=$?
set -e
# unzip returns 11 when some members not matched; 0 is full success; 1 some warnings
if [[ "${unzip_rc}" -ne 0 && "${unzip_rc}" -ne 1 && "${unzip_rc}" -ne 11 ]]; then
  log "WARN: unzip rc=${unzip_rc}: $(tr '\n' ' ' <"${WORKDIR}/unzip.err" | head -c 200)"
fi

# Enumerate extracted .so files → TSV: apk_rel_path \t abs_path \t size \t sha256
SO_TSV="${WORKDIR}/so.tsv"
: >"${SO_TSV}"
if [[ -d "${WORKDIR}/extract/lib" ]]; then
  while IFS= read -r -d '' so_abs; do
    # apk-relative path: strip extract prefix
    rel="${so_abs#${WORKDIR}/extract/}"
    # only lib/<abi>/<name>.so
    case "${rel}" in
      lib/*/*.so) ;;
      *) continue ;;
    esac
    sz="$(wc -c <"${so_abs}" | tr -d ' ')"
    sh="$(sha256_of "${so_abs}")"
    printf '%s\t%s\t%s\t%s\n' "${rel}" "${so_abs}" "${sz}" "${sh}" >>"${SO_TSV}"
  done < <(find "${WORKDIR}/extract/lib" -type f -name '*.so' -print0 2>/dev/null | sort -z)
fi

SO_COUNT="$(wc -l <"${SO_TSV}" | tr -d ' ')"
log "found ${SO_COUNT} native .so entr(y/ies)"

# Per-lib readelf dumps: write JSONL lines for python assembly
ELF_JSONL="${WORKDIR}/elf.jsonl"
: >"${ELF_JSONL}"

while IFS=$'\t' read -r rel abs sz sha; do
  [[ -n "${rel}" ]] || continue
  hdr="${WORKDIR}/hdr.$(basename "${rel}").$$.txt"
  dyn="${WORKDIR}/dyn.$(basename "${rel}").$$.txt"
  set +e
  "${READELF}" -h "${abs}" >"${hdr}" 2>"${hdr}.err"
  hrc=$?
  "${READELF}" -d "${abs}" >"${dyn}" 2>"${dyn}.err"
  drc=$?
  set -e
  if [[ "${hrc}" -ne 0 ]]; then
    log "WARN: readelf -h failed for ${rel}: $(tr '\n' ' ' <"${hdr}.err" | head -c 120)"
  fi
  if [[ "${drc}" -ne 0 ]]; then
    log "WARN: readelf -d failed for ${rel}: $(tr '\n' ' ' <"${dyn}.err" | head -c 120)"
  fi
  # Append one JSON object via python for safe escaping
  export WP12B_REL="${rel}"
  export WP12B_SZ="${sz}"
  export WP12B_SHA="${sha}"
  export WP12B_HDR="${hdr}"
  export WP12B_DYN="${dyn}"
  python3 >>"${ELF_JSONL}" <<'PY'
import json, os, re, sys

rel = os.environ["WP12B_REL"]
sz = int(os.environ["WP12B_SZ"])
sha = os.environ["WP12B_SHA"].lower()
hdr = open(os.environ["WP12B_HDR"], encoding="utf-8", errors="replace").read()
dyn = open(os.environ["WP12B_DYN"], encoding="utf-8", errors="replace").read()

# Class: ELF64 / ELF32
elf_class = None
m = re.search(r"^\s*Class:\s+(\S+)", hdr, re.M)
if m:
    c = m.group(1)
    if c == "ELF64":
        elf_class = "ELFCLASS64"
    elif c == "ELF32":
        elf_class = "ELFCLASS32"
    else:
        elf_class = c

# Machine
machine_raw = None
m = re.search(r"^\s*Machine:\s+(.+)$", hdr, re.M)
if m:
    machine_raw = m.group(1).strip()

MACHINE_MAP = {
    "AArch64": "EM_AARCH64",
    "ARM": "EM_ARM",
    "Intel 80386": "EM_386",
    "Advanced Micro Devices X86-64": "EM_X86_64",
    "RISC-V": "EM_RISCV",
    "EM_AARCH64": "EM_AARCH64",
    "EM_ARM": "EM_ARM",
    "EM_386": "EM_386",
    "EM_X86_64": "EM_X86_64",
    "EM_RISCV": "EM_RISCV",
}
elf_machine = MACHINE_MAP.get(machine_raw or "", machine_raw or "UNKNOWN")

# SONAME
soname = None
m = re.search(r"\(SONAME\)\s+Library soname:\s+\[([^\]]+)\]", dyn)
if m:
    soname = m.group(1)

# NEEDED
needed = re.findall(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]", dyn)

parts = rel.split("/")
# lib/<abi>/<name>
abi = parts[1] if len(parts) >= 3 else "unknown"
name = parts[-1]

obj = {
    "name": name,
    "path": rel,
    "abi": abi,
    "sha256": sha,
    "sizeBytes": sz,
    "soname": soname,
    "needed": needed,
    "elfClass": elf_class or "ELFCLASS64",
    "elfMachine": elf_machine,
}
print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
PY
done <"${SO_TSV}"

export WP12B_ELF_JSONL="${ELF_JSONL}"
export WP12B_APK_SHA="${APK_SHA}"
export WP12B_PACKAGE="${PACKAGE_NAME}"
export WP12B_VERSION_CODE="${VERSION_CODE}"
export WP12B_VERSION_NAME="${VERSION_NAME}"
export WP12B_OUT_JSON="${OUT}/native-inventory.json"

python3 <<'PY'
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

elf_path = Path(os.environ["WP12B_ELF_JSONL"])
apk_sha = os.environ["WP12B_APK_SHA"].lower()
package = os.environ["WP12B_PACKAGE"]
version_code_raw = os.environ.get("WP12B_VERSION_CODE") or ""
version_name = os.environ.get("WP12B_VERSION_NAME") or ""
out_json = Path(os.environ["WP12B_OUT_JSON"])

# Public Android / Bionic / NDK system shared libs (not vendor/private).
# Unresolved needed not in this set and not present locally → MISSING_NEEDED.
SYSTEM_LIBS = {
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
    "libnativehelper.so",
    "libicuuc.so",
    "libicui18n.so",
    "libandroid_runtime.so",
    "libutils.so",
    "libcutils.so",
    "libbinder.so",
    "libhwui.so",
    "libgui.so",
    "libui.so",
    "libsqlite.so",
    "libcrypto.so",
    "libssl.so",
    "libjpeg.so",
    "libpng.so",
    "libwebviewchromium_plat_support.so",
    "libheif.so",
    "libimage_processing_util_jni.so",
}

ABI_EXPECT = {
    "arm64-v8a": ("EM_AARCH64", "ELFCLASS64"),
    "armeabi-v7a": ("EM_ARM", "ELFCLASS32"),
    "armeabi": ("EM_ARM", "ELFCLASS32"),
    "x86": ("EM_386", "ELFCLASS32"),
    "x86_64": ("EM_X86_64", "ELFCLASS64"),
    "riscv64": ("EM_RISCV", "ELFCLASS64"),
}

ABI_ORDER = ["arm64-v8a", "armeabi-v7a", "armeabi", "x86_64", "x86", "riscv64"]

libs_raw = []
if elf_path.is_file() and elf_path.stat().st_size > 0:
    for line in elf_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        libs_raw.append(json.loads(line))

by_abi: dict[str, list[dict]] = defaultdict(list)
for lib in libs_raw:
    abi = lib.get("abi") or "unknown"
    entry = {
        "name": lib["name"],
        "path": lib["path"],
        "sha256": lib["sha256"],
        "sizeBytes": int(lib["sizeBytes"]),
        "soname": lib.get("soname"),
        "needed": list(lib.get("needed") or []),
        "elfClass": lib.get("elfClass") or "ELFCLASS64",
        "elfMachine": lib.get("elfMachine") or "UNKNOWN",
    }
    by_abi[abi].append(entry)

# Prefer arm64-v8a first; then remaining known ABIs; then any extras.
ordered_abis = []
seen_abi = set()
for a in ABI_ORDER:
    if a in by_abi:
        ordered_abis.append(a)
        seen_abi.add(a)
for a in sorted(by_abi.keys()):
    if a not in seen_abi:
        ordered_abis.append(a)
        seen_abi.add(a)

abis = []
for a in ordered_abis:
    libs = sorted(by_abi[a], key=lambda x: x["name"])
    abis.append({"name": a, "libs": libs})

# Local resolve sets per ABI: basenames + sonames
def local_names(libs: list[dict]) -> set[str]:
    names: set[str] = set()
    for L in libs:
        if L.get("name"):
            names.add(L["name"])
        sn = L.get("soname")
        if isinstance(sn, str) and sn:
            names.add(sn)
    return names

missing_needed = []
wrong_abi = []
duplicate_soname = []
system_needed_set: set[str] = set()

for abi_row in abis:
    abi = abi_row["name"]
    libs = abi_row["libs"]
    local = local_names(libs)

    # duplicate SONAME within ABI
    soname_map: dict[str, list[str]] = defaultdict(list)
    for L in libs:
        sn = L.get("soname")
        if isinstance(sn, str) and sn:
            soname_map[sn].append(L["name"])
    for sn, claimants in sorted(soname_map.items()):
        uniq = sorted(set(claimants))
        if len(uniq) >= 2:
            duplicate_soname.append({"abi": abi, "soname": sn, "libs": uniq})

    # ABI / ELF match
    expect = ABI_EXPECT.get(abi)
    for L in libs:
        machine = L.get("elfMachine") or ""
        klass = L.get("elfClass") or ""
        if expect is None:
            # unknown ABI directory — treat machine mismatch as wrong if class/machine empty
            continue
        exp_m, exp_c = expect
        if machine != exp_m or klass != exp_c:
            wrong_abi.append(
                {
                    "abi": abi,
                    "name": L["name"],
                    "path": L["path"],
                    "elfMachine": machine,
                    "elfClass": klass,
                    "expectedMachine": exp_m,
                }
            )

    # DT_NEEDED resolution
    for L in libs:
        for need in L.get("needed") or []:
            if not isinstance(need, str) or not need:
                continue
            if need in local:
                continue
            if need in SYSTEM_LIBS:
                system_needed_set.add(need)
                continue
            # basename form of system (already basenames typically)
            missing_needed.append(
                {"abi": abi, "from": L["name"], "needed": need}
            )

system_needed = sorted(system_needed_set)

# jniLoadLibs: strip lib/ and .so from primary ABI sonames/names
jni: list[str] = []
seen_jni: set[str] = set()
primary_libs = []
for abi_row in abis:
    if abi_row["name"] == "arm64-v8a":
        primary_libs = abi_row["libs"]
        break
if not primary_libs and abis:
    primary_libs = abis[0]["libs"]
for L in primary_libs:
    base = L.get("soname") or L.get("name") or ""
    if not base:
        continue
    n = base
    if n.startswith("lib"):
        n = n[3:]
    if n.endswith(".so"):
        n = n[:-3]
    if n and n not in seen_jni:
        seen_jni.add(n)
        jni.append(n)

# EMPTY_ARM64
arm64_libs = []
for abi_row in abis:
    if abi_row["name"] == "arm64-v8a":
        arm64_libs = abi_row["libs"]
        break
empty_arm64 = len(arm64_libs) == 0

failures = []
for m in missing_needed:
    failures.append(
        {
            "code": "MISSING_NEEDED",
            "message": (
                f"{m['abi']} {m['from']} DT_NEEDED {m['needed']} "
                "not resolved in package libs or public systemNeeded"
            ),
            "detail": f"from={m['from']} needed={m['needed']} abi={m['abi']}",
        }
    )
for w in wrong_abi:
    exp = ABI_EXPECT.get(w["abi"], (w.get("expectedMachine"), "?"))
    failures.append(
        {
            "code": "WRONG_ABI",
            "message": (
                f"{w['abi']}/{w['name']} ELF machine {w['elfMachine']} class {w['elfClass']} "
                f"does not match ABI {w['abi']} (expected {exp[0]}/{exp[1]})"
            ),
            "detail": f"path={w.get('path', '')}",
        }
    )
for d in duplicate_soname:
    failures.append(
        {
            "code": "DUPLICATE_SONAME",
            "message": (
                f"{d['abi']} SONAME {d['soname']} claimed by multiple libs: "
                + ", ".join(d["libs"])
            ),
            "detail": f"abi={d['abi']} soname={d['soname']}",
        }
    )
if empty_arm64:
    failures.append(
        {
            "code": "EMPTY_ARM64",
            "message": "no arm64-v8a native libraries found in APK lib/ tree",
            "detail": "arm64-v8a.libs empty or missing",
        }
    )

inventory = {
    "schemaVersion": "wp12b-native-libs/v1",
    "packageName": package,
    "apkSha256": apk_sha,
    "abis": abis,
    "jniLoadLibs": jni,
    "closure": {
        "missingNeeded": missing_needed,
        "wrongAbi": wrong_abi,
        "duplicateSoname": duplicate_soname,
        "systemNeeded": system_needed,
    },
    "failClosed": {
        "ok": len(failures) == 0,
        "failures": failures,
    },
}
if version_code_raw.isdigit():
    inventory["versionCode"] = int(version_code_raw)
if version_name:
    inventory["versionName"] = version_name

text = json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
out_json.write_text(text, encoding="utf-8")
print(
    json.dumps(
        {
            "ok": True,
            "out": str(out_json),
            "apkSha256": apk_sha,
            "packageName": package,
            "totalSo": sum(len(a["libs"]) for a in abis),
            "abiCounts": {a["name"]: len(a["libs"]) for a in abis},
            "failClosedOk": inventory["failClosed"]["ok"],
            "failureCodes": sorted({f["code"] for f in failures}),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
)
PY

log "wrote ${OUT}/native-inventory.json"
exit 0
