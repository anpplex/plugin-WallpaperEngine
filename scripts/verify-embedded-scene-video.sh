#!/usr/bin/env bash
# WP-12E — verify embedded scene/video E4 frame contract (fail-closed)
# Product path: scripts/verify-embedded-scene-video.sh (Plugin worktree)
#
# Catalog phase selectors:
#   --case frame-negative           # RED:  exit 1, stderr BLACK_FRAME (primary)
#   --case frame-positive-offline   # GREEN: exit 0 synthetic dual-frame dry-run
#                                   #        (no device E4 claim)
#
# Inventory modes (fixture JSON, schemaVersion=wp12e-scene-video-e4/v1):
#   --inventory PATH --mode MODE
#     positive
#     negative-black
#     negative-single-sample
#
# Fail-closed rules (recomputed from structure; failClosed field not trusted alone):
#   BLACK_FRAME               — samples.*.nonBlack is false (or pixel analysis)
#   SOLID_COLOR               — samples.*.nonSolid is false (or pixel analysis)
#   SINGLE_SAMPLE             — only scene or only video present when dual required
#   MISSING_FRAME             — frames absent / path+sha256 both missing
#   FRAME_INTERVAL_TOO_SHORT  — intervalSeconds < 3 or dual capturedAt gap < 3s
#
# Exit codes:
#   0  positive clean / frame-positive-offline
#   1  fail-closed defect or negative-mode signature outcome (RED)
#   2  usage / invalid inventory
#   3  unexpected internal error
#
# Never forges EffectiveDone / device E4 PASS offline. Offline GREEN is a
# contract dry-run only (deviceE4Claim must remain false).
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES_DIR="${SCRIPT_DIR}/tests/fixtures"
ANALYZE="${SCRIPT_DIR}/analyze-frame-nonblack.py"

SCHEMA="wp12e-scene-video-e4/v1"
MIN_INTERVAL_SECONDS="3"

usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} --case frame-negative
  ${SCRIPT_NAME} --case frame-positive-offline
  ${SCRIPT_NAME} --inventory PATH --mode MODE

WP-12E host-side scene/video frame non-black verifier (fail-closed).

Cases (catalog RED/GREEN offline):
  frame-negative            Primary negative inventory → exit 1 + BLACK_FRAME
  frame-positive-offline    Synthetic dual-frame dry-run → exit 0 (no E4 claim)

Modes (with --inventory):
  positive
  negative-black
  negative-single-sample

Exit codes:
  0  positive + clean
  1  fail-closed defect (or negative-mode expected-signature outcome)
  2  usage / invalid inventory
  3  unexpected internal error

Stderr prints failure codes as bare tokens (e.g. BLACK_FRAME) so catalog
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

TMP_CASE=""
cleanup() {
  if [[ -n "${TMP_CASE}" && -d "${TMP_CASE}" ]]; then
    rm -rf "${TMP_CASE}"
  fi
}
trap cleanup EXIT

if [[ -n "${CASE}" ]]; then
  case "${CASE}" in
    frame-negative)
      # Primary catalog RED signature: BLACK_FRAME via fixture inventory.
      if [[ -f "${FIXTURES_DIR}/frame-black.json" ]]; then
        INVENTORY="${FIXTURES_DIR}/frame-black.json"
      else
        TMP_CASE="$(mktemp -d "${TMPDIR:-/tmp}/wp12e-frame-neg.XXXXXX")"
        INVENTORY="${TMP_CASE}/frame-black.json"
        cat >"${INVENTORY}" <<'JSON'
{
  "schemaVersion": "wp12e-scene-video-e4/v1",
  "contractDryRun": true,
  "deviceE4Claim": false,
  "pluginPid": 0,
  "surface": {"present": false, "ownerPid": 0, "name": null},
  "intervalSeconds": 4,
  "samples": {
    "scene": {
      "frames": [
        {
          "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "capturedAt": "2026-08-07T12:00:00Z"
        }
      ],
      "nonBlack": false,
      "nonSolid": false
    },
    "video": {
      "frames": [
        {
          "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "capturedAt": "2026-08-07T12:00:05Z"
        }
      ],
      "nonBlack": false,
      "nonSolid": false
    }
  },
  "failClosed": {
    "ok": false,
    "failures": [
      {"code": "BLACK_FRAME", "message": "scene/video frame mean luminance near 0"}
    ]
  },
  "humanReadableOk": false
}
JSON
      fi
      MODE="negative-black"
      log "case=frame-negative inventory=${INVENTORY} mode=${MODE}"
      ;;
    frame-positive-offline)
      if [[ -f "${FIXTURES_DIR}/frame-e4-pass-offline.json" ]]; then
        INVENTORY="${FIXTURES_DIR}/frame-e4-pass-offline.json"
      else
        TMP_CASE="$(mktemp -d "${TMPDIR:-/tmp}/wp12e-frame-pos.XXXXXX")"
        INVENTORY="${TMP_CASE}/frame-e4-pass-offline.json"
        cat >"${INVENTORY}" <<'JSON'
{
  "schemaVersion": "wp12e-scene-video-e4/v1",
  "contractDryRun": true,
  "deviceE4Claim": false,
  "pluginPid": 8888,
  "surface": {"present": true, "ownerPid": 8888, "name": "EmbeddedPreview"},
  "intervalSeconds": 5,
  "samples": {
    "scene": {
      "frames": [
        {
          "sha256": "1111111111111111111111111111111111111111111111111111111111111111",
          "capturedAt": "2026-08-07T12:00:00Z"
        }
      ],
      "nonBlack": true,
      "nonSolid": true
    },
    "video": {
      "frames": [
        {
          "sha256": "2222222222222222222222222222222222222222222222222222222222222222",
          "capturedAt": "2026-08-07T12:00:05Z"
        }
      ],
      "nonBlack": true,
      "nonSolid": true
    }
  },
  "failClosed": {"ok": true, "failures": []},
  "humanReadableOk": true
}
JSON
      fi
      MODE="positive"
      log "case=frame-positive-offline inventory=${INVENTORY} (contract dry-run; no device E4 claim)"
      ;;
    *)
      die "unknown --case: ${CASE} (expected frame-negative|frame-positive-offline)"
      ;;
  esac
fi

[[ -n "${INVENTORY}" ]] || die "missing --inventory PATH (or --case)"
[[ -n "${MODE}" ]] || die "missing --mode MODE (or --case)"
[[ -f "${INVENTORY}" ]] || die "inventory not found or not a file: ${INVENTORY}"
[[ -r "${INVENTORY}" ]] || die "inventory not readable: ${INVENTORY}"

case "${MODE}" in
  positive|\
  negative-black|\
  negative-single-sample)
    ;;
  *)
    die "unknown --mode: ${MODE}"
    ;;
esac

INVENTORY="$(cd "$(dirname "${INVENTORY}")" && pwd)/$(basename "${INVENTORY}")"

log "inventory=${INVENTORY}"
log "mode=${MODE}"

export WP12E_VERIFY_INVENTORY="${INVENTORY}"
export WP12E_VERIFY_MODE="${MODE}"
export WP12E_SCHEMA="${SCHEMA}"
export WP12E_MIN_INTERVAL="${MIN_INTERVAL_SECONDS}"
export WP12E_ANALYZE="${ANALYZE}"

set +e
PY_OUT="$(
python3 <<'PY'
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

inv_path = Path(os.environ["WP12E_VERIFY_INVENTORY"])
mode = os.environ["WP12E_VERIFY_MODE"]
SCHEMA = os.environ["WP12E_SCHEMA"]
MIN_INTERVAL = float(os.environ["WP12E_MIN_INTERVAL"])
ANALYZE = Path(os.environ.get("WP12E_ANALYZE", ""))

HEX64 = re.compile(r"^[a-f0-9]{64}$")


def emit(status: str, codes: list[str], message: str) -> None:
    for c in codes:
        print(c, file=sys.stderr)
    print(f"{status}|{','.join(codes)}|{message}")


def parse_iso8601(value: str):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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

required = ["schemaVersion", "samples", "pluginPid", "surface", "failClosed"]
missing = [k for k in required if k not in data]
if missing:
    emit("INVALID", ["INVALID_INVENTORY"], f"inventory missing fields: {missing}")
    sys.exit(0)

samples = data.get("samples")
if not isinstance(samples, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "samples must be an object")
    sys.exit(0)

surface = data.get("surface")
if not isinstance(surface, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "surface must be an object")
    sys.exit(0)

fail_closed = data.get("failClosed")
if not isinstance(fail_closed, dict):
    emit("INVALID", ["INVALID_INVENTORY"], "failClosed must be an object")
    sys.exit(0)

plugin_pid = data.get("pluginPid")
if not isinstance(plugin_pid, int) or isinstance(plugin_pid, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "pluginPid must be an integer")
    sys.exit(0)

failures: list[tuple[str, str]] = []


def add(code: str, message: str) -> None:
    failures.append((code, message))


def role_frames(role: str) -> list[dict]:
    node = samples.get(role)
    if not isinstance(node, dict):
        return []
    frames = node.get("frames")
    if not isinstance(frames, list):
        return []
    return [f for f in frames if isinstance(f, dict)]


scene_frames = role_frames("scene")
video_frames = role_frames("video")
has_scene = len(scene_frames) > 0
has_video = len(video_frames) > 0

# ---------------------------------------------------------------------------
# SINGLE_SAMPLE / MISSING_FRAME
# ---------------------------------------------------------------------------
# Dual-frame contract: positive path requires both scene and video samples.
if has_scene ^ has_video:
    add("SINGLE_SAMPLE", "only one of scene/video samples present (dual required)")
elif not has_scene and not has_video:
    add("MISSING_FRAME", "no scene or video frames present")
    add("SINGLE_SAMPLE", "neither scene nor video sample present")

for role, frames in (("scene", scene_frames), ("video", video_frames)):
    node = samples.get(role)
    if not isinstance(node, dict):
        continue
    if not frames and role in samples:
        # empty frames list when role key present
        if isinstance(node.get("frames"), list) and len(node.get("frames") or []) == 0:
            add("MISSING_FRAME", f"samples.{role}.frames is empty")

    non_black = node.get("nonBlack")
    non_solid = node.get("nonSolid")
    if non_black is not None and not isinstance(non_black, bool):
        emit("INVALID", ["INVALID_INVENTORY"], f"samples.{role}.nonBlack must be boolean")
        sys.exit(0)
    if non_solid is not None and not isinstance(non_solid, bool):
        emit("INVALID", ["INVALID_INVENTORY"], f"samples.{role}.nonSolid must be boolean")
        sys.exit(0)

    if non_black is False:
        add("BLACK_FRAME", f"samples.{role}.nonBlack is false")
    if non_solid is False:
        add("SOLID_COLOR", f"samples.{role}.nonSolid is false")

    for i, fr in enumerate(frames):
        sha = fr.get("sha256")
        path_val = fr.get("path")
        if sha is None and path_val is None:
            add("MISSING_FRAME", f"samples.{role}.frames[{i}] missing path and sha256")
        if sha is not None:
            if not isinstance(sha, str) or not HEX64.fullmatch(sha):
                # treat bad hash as missing evidence of frame content
                add("MISSING_FRAME", f"samples.{role}.frames[{i}].sha256 invalid")
        if path_val is not None and (not isinstance(path_val, str) or not path_val.strip()):
            add("MISSING_FRAME", f"samples.{role}.frames[{i}].path empty")

# ---------------------------------------------------------------------------
# FRAME_INTERVAL_TOO_SHORT
# ---------------------------------------------------------------------------
interval = data.get("intervalSeconds")
if interval is not None:
    if not isinstance(interval, (int, float)) or isinstance(interval, bool):
        emit("INVALID", ["INVALID_INVENTORY"], "intervalSeconds must be a number")
        sys.exit(0)
    if float(interval) < MIN_INTERVAL:
        add(
            "FRAME_INTERVAL_TOO_SHORT",
            f"intervalSeconds={interval} < {MIN_INTERVAL}",
        )

times = []
for fr in scene_frames + video_frames:
    cap = fr.get("capturedAt")
    if isinstance(cap, str):
        dt = parse_iso8601(cap)
        if dt is not None:
            times.append(dt)
if len(times) >= 2:
    times_sorted = sorted(times)
    gap = (times_sorted[-1] - times_sorted[0]).total_seconds()
    if gap < MIN_INTERVAL:
        add(
            "FRAME_INTERVAL_TOO_SHORT",
            f"dual capturedAt gap={gap:.3f}s < {MIN_INTERVAL}s",
        )

for role, frames in (("scene", scene_frames), ("video", video_frames)):
    role_times = []
    for fr in frames:
        cap = fr.get("capturedAt")
        if isinstance(cap, str):
            dt = parse_iso8601(cap)
            if dt is not None:
                role_times.append(dt)
    if len(role_times) >= 2:
        role_times.sort()
        for i in range(1, len(role_times)):
            gap = (role_times[i] - role_times[i - 1]).total_seconds()
            if gap < MIN_INTERVAL:
                add(
                    "FRAME_INTERVAL_TOO_SHORT",
                    f"samples.{role} consecutive frame gap={gap:.3f}s < {MIN_INTERVAL}s",
                )
                break

# ---------------------------------------------------------------------------
# deviceE4Claim must not be true on contract dry-run (no forged E4)
# ---------------------------------------------------------------------------
contract_dry_run = data.get("contractDryRun")
if contract_dry_run is not None and not isinstance(contract_dry_run, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "contractDryRun must be boolean when present")
    sys.exit(0)
device_e4_claim = data.get("deviceE4Claim")
if device_e4_claim is not None and not isinstance(device_e4_claim, bool):
    emit("INVALID", ["INVALID_INVENTORY"], "deviceE4Claim must be boolean when present")
    sys.exit(0)
if contract_dry_run is True and device_e4_claim is True:
    add(
        "BLACK_FRAME",
        "contract dry-run must not set deviceE4Claim=true (no forged device E4)",
    )

# ---------------------------------------------------------------------------
# Positive structural integrity
# ---------------------------------------------------------------------------
positive_defects: list[tuple[str, str]] = []


def pos_add(code: str, message: str) -> None:
    positive_defects.append((code, message))


if mode == "positive":
    # Offline contract dry-run: require dual samples, non-black/non-solid flags,
    # interval ok, pluginPid/surface present, no E4 claim.
    if not (has_scene and has_video):
        # already covered; keep positive clean via codes
        pass
    for role in ("scene", "video"):
        node = samples.get(role)
        if not isinstance(node, dict):
            pos_add("MISSING_FRAME", f"positive requires samples.{role}")
            continue
        if node.get("nonBlack") is not True:
            pos_add("BLACK_FRAME", f"positive requires samples.{role}.nonBlack true")
        if node.get("nonSolid") is not True:
            pos_add("SOLID_COLOR", f"positive requires samples.{role}.nonSolid true")
        frames = role_frames(role)
        if not frames:
            pos_add("MISSING_FRAME", f"positive requires samples.{role}.frames non-empty")
        for i, fr in enumerate(frames):
            sha = fr.get("sha256")
            if not isinstance(sha, str) or not HEX64.fullmatch(sha):
                pos_add("MISSING_FRAME", f"positive samples.{role}.frames[{i}] needs sha256")

    if not (isinstance(plugin_pid, int) and plugin_pid > 0):
        pos_add("MISSING_FRAME", "positive requires pluginPid > 0")
    if surface.get("present") is not True:
        pos_add("MISSING_FRAME", "positive requires surface.present true")
    else:
        owner = surface.get("ownerPid")
        if not (isinstance(owner, int) and owner == plugin_pid):
            pos_add("MISSING_FRAME", "surface.ownerPid must match pluginPid")

    if device_e4_claim is True:
        pos_add("BLACK_FRAME", "positive inventory must not forge deviceE4Claim")

    # Prefer contractDryRun true for offline synthetic; live path may omit it.
    # Offline green path must not claim E4.
    for code, msg in positive_defects:
        add(code, msg)

# Deduplicate codes preserving order
codes: list[str] = []
seen: set[str] = set()
for code, _msg in failures:
    if code not in seen:
        seen.add(code)
        codes.append(code)

expected_by_mode = {
    "positive": None,
    "negative-black": "BLACK_FRAME",
    "negative-single-sample": "SINGLE_SAMPLE",
}

if mode == "positive":
    if not codes:
        emit(
            "PASS",
            [],
            "scene/video e4 contract clean (offline dry-run; no device E4 claim)",
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
