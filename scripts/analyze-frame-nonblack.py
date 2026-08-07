#!/usr/bin/env python3
"""WP-12E — analyze frame(s) / inventory for non-black, non-solid scene/video contract.

Product path: scripts/analyze-frame-nonblack.py (Plugin worktree)

Inputs:
  - one or two PNG image paths, OR
  - --inventory PATH  (schema wp12e-scene-video-e4/v1 frame inventory)

Detects (stderr bare tokens for catalog matching):
  BLACK_FRAME               mean luminance near 0
  SOLID_COLOR               low pixel variance (flat fill)
  FRAME_INTERVAL_TOO_SHORT  dual frames with gap < 3s when timestamps present
  SINGLE_SAMPLE             only scene or only video present when both required
  MISSING_FRAME             required frame path/sha256/frames absent

Exit codes:
  0  non-black, non-solid, dual-frame rules ok when required
  1  one or more fail-closed defects
  2  usage / invalid input
  3  unexpected internal error

Uses PIL/Pillow when available; otherwise pure struct + zlib PNG RGB stats.
Fail-closed: never forges non-black PASS without analysis of pixels or inventory.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Luminance near 0 on 0–255 scale (fail-closed black).
BLACK_MEAN_THRESHOLD = 2.0
# Population variance of luminance (flat solid fill).
SOLID_VARIANCE_THRESHOLD = 1.0
# Minimum gap between dual captured frames when timestamps present.
MIN_INTERVAL_SECONDS = 3.0

SCHEMA = "wp12e-scene-video-e4/v1"

try:
    from PIL import Image  # type: ignore

    HAS_PIL = True
except ImportError:  # pragma: no cover - optional dep
    HAS_PIL = False


@dataclass
class FrameStats:
    path: Optional[str]
    width: int
    height: int
    mean_luminance: float
    variance: float
    pixel_count: int
    black: bool
    solid: bool


def die_usage(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def emit_code(code: str) -> None:
    print(code, file=sys.stderr)


def parse_iso8601(value: str) -> Optional[datetime]:
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


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter_scanlines(
    raw: bytes, width: int, height: int, bpp: int
) -> list[bytes]:
    stride = width * bpp
    out: list[bytes] = []
    offset = 0
    prev = bytearray(stride)
    for _ in range(height):
        if offset >= len(raw):
            raise ValueError("truncated PNG IDAT scanline data")
        ftype = raw[offset]
        offset += 1
        if offset + stride > len(raw):
            raise ValueError("truncated PNG IDAT row")
        row = bytearray(raw[offset : offset + stride])
        offset += stride
        if ftype == 0:  # None
            pass
        elif ftype == 1:  # Sub
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + left) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev[i]
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev[i]
                up_left = prev[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth(left, up, up_left)) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter type {ftype}")
        out.append(bytes(row))
        prev = row
    return out


def png_rgb_stats_pure(path: Path) -> FrameStats:
    """Pure-Python PNG decoder for 8-bit RGB/RGBA (no palette/interlace)."""
    data = path.read_bytes()
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")

    pos = 8
    width = height = None
    color_type = None
    bit_depth = None
    idat = bytearray()

    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # length + type + data + crc
        if ctype == b"IHDR":
            if length < 13:
                raise ValueError("invalid IHDR")
            width, height, bit_depth, color_type, comp, filt, inter = struct.unpack(
                ">IIBBBBB", chunk[:13]
            )
            if comp != 0 or filt != 0:
                raise ValueError("unsupported PNG compression/filter method")
            if inter != 0:
                raise ValueError("interlaced PNG not supported without PIL")
            if bit_depth != 8:
                raise ValueError(f"bit depth {bit_depth} not supported without PIL")
            if color_type not in (2, 6):  # RGB, RGBA
                raise ValueError(
                    f"color type {color_type} not supported without PIL "
                    "(need RGB/RGBA)"
                )
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break

    if width is None or height is None or color_type is None:
        raise ValueError("PNG missing IHDR")
    if width <= 0 or height <= 0:
        raise ValueError("invalid PNG dimensions")

    raw = zlib.decompress(bytes(idat))
    bpp = 3 if color_type == 2 else 4
    rows = _unfilter_scanlines(raw, width, height, bpp)

    # Online mean / M2 (Welford) over luminance.
    n = 0
    mean = 0.0
    m2 = 0.0
    for row in rows:
        for x in range(width):
            base = x * bpp
            r, g, b = row[base], row[base + 1], row[base + 2]
            # Rec. 601 luma
            y = 0.299 * r + 0.587 * g + 0.114 * b
            n += 1
            delta = y - mean
            mean += delta / n
            m2 += delta * (y - mean)

    variance = m2 / n if n else 0.0
    black = mean < BLACK_MEAN_THRESHOLD
    solid = variance < SOLID_VARIANCE_THRESHOLD
    return FrameStats(
        path=str(path),
        width=width,
        height=height,
        mean_luminance=mean,
        variance=variance,
        pixel_count=n,
        black=black,
        solid=solid,
    )


def png_rgb_stats_pil(path: Path) -> FrameStats:
    assert HAS_PIL
    with Image.open(path) as im:
        im = im.convert("RGB")
        width, height = im.size
        pixels = list(im.getdata())
    n = 0
    mean = 0.0
    m2 = 0.0
    for r, g, b in pixels:
        y = 0.299 * r + 0.587 * g + 0.114 * b
        n += 1
        delta = y - mean
        mean += delta / n
        m2 += delta * (y - mean)
    variance = m2 / n if n else 0.0
    black = mean < BLACK_MEAN_THRESHOLD
    solid = variance < SOLID_VARIANCE_THRESHOLD
    return FrameStats(
        path=str(path),
        width=width,
        height=height,
        mean_luminance=mean,
        variance=variance,
        pixel_count=n,
        black=black,
        solid=solid,
    )


def analyze_png(path: Path) -> FrameStats:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if HAS_PIL:
        return png_rgb_stats_pil(path)
    return png_rgb_stats_pure(path)


def analyze_image_paths(
    paths: list[Path],
    *,
    require_dual: bool,
) -> tuple[list[str], list[FrameStats], str]:
    """Return (codes, stats, message)."""
    codes: list[str] = []
    stats: list[FrameStats] = []

    if not paths:
        codes.append("MISSING_FRAME")
        return codes, stats, "no image paths provided"

    for p in paths:
        if not p.is_file():
            codes.append("MISSING_FRAME")
            return codes, stats, f"missing frame file: {p}"
        try:
            st = analyze_png(p)
        except Exception as e:  # noqa: BLE001 — fail-closed on decode errors
            codes.append("MISSING_FRAME")
            return codes, stats, f"frame unreadable: {p}: {e}"
        stats.append(st)
        if st.black:
            if "BLACK_FRAME" not in codes:
                codes.append("BLACK_FRAME")
        if st.solid and not st.black:
            # Solid black already covered by BLACK_FRAME; still note SOLID when flat non-black.
            if "SOLID_COLOR" not in codes:
                codes.append("SOLID_COLOR")
        elif st.solid and st.black:
            # Black is also solid; emit both for catalog visibility.
            if "SOLID_COLOR" not in codes:
                codes.append("SOLID_COLOR")

    if require_dual and len(paths) < 2:
        if "SINGLE_SAMPLE" not in codes:
            codes.append("SINGLE_SAMPLE")

    # Dual image path mode: no inventory timestamps — interval check skipped.
    detail_parts = []
    for st in stats:
        detail_parts.append(
            f"{st.path}: mean={st.mean_luminance:.3f} var={st.variance:.3f} "
            f"black={st.black} solid={st.solid}"
        )
    message = "; ".join(detail_parts) if detail_parts else "no stats"
    return codes, stats, message


def _sample_frames(samples: dict[str, Any], role: str) -> list[dict[str, Any]]:
    node = samples.get(role)
    if not isinstance(node, dict):
        return []
    frames = node.get("frames")
    if not isinstance(frames, list):
        return []
    return [f for f in frames if isinstance(f, dict)]


def analyze_inventory(
    inv_path: Path,
    *,
    require_dual: bool,
    analyze_pixel_paths: bool,
) -> tuple[list[str], str, dict[str, Any]]:
    """Recompute fail-closed codes from inventory structure (+ optional pixel paths)."""
    try:
        data = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        die_usage(f"invalid inventory: {e}")

    if not isinstance(data, dict):
        die_usage("inventory root must be a JSON object")
    if data.get("schemaVersion") != SCHEMA:
        die_usage(f"unsupported schemaVersion: {data.get('schemaVersion')!r}")

    codes: list[str] = []
    samples = data.get("samples")
    if not isinstance(samples, dict):
        codes.append("MISSING_FRAME")
        return codes, "samples missing or not an object", data

    scene_frames = _sample_frames(samples, "scene")
    video_frames = _sample_frames(samples, "video")
    has_scene = len(scene_frames) > 0
    has_video = len(video_frames) > 0

    if require_dual:
        if has_scene ^ has_video:
            codes.append("SINGLE_SAMPLE")
        elif not has_scene and not has_video:
            codes.append("MISSING_FRAME")
            # dual missing is also a single-sample situation for catalog RED
            if "SINGLE_SAMPLE" not in codes:
                codes.append("SINGLE_SAMPLE")
    else:
        if not has_scene and not has_video:
            codes.append("MISSING_FRAME")

    def check_role(role: str, frames: list[dict[str, Any]]) -> None:
        node = samples.get(role)
        if not isinstance(node, dict):
            return
        non_black = node.get("nonBlack")
        non_solid = node.get("nonSolid")
        if non_black is False:
            if "BLACK_FRAME" not in codes:
                codes.append("BLACK_FRAME")
        if non_solid is False:
            if "SOLID_COLOR" not in codes:
                codes.append("SOLID_COLOR")

        if not frames:
            return

        for fr in frames:
            sha = fr.get("sha256")
            path_val = fr.get("path")
            if sha is None and path_val is None:
                if "MISSING_FRAME" not in codes:
                    codes.append("MISSING_FRAME")
            if path_val is not None:
                if not isinstance(path_val, str) or not path_val.strip():
                    if "MISSING_FRAME" not in codes:
                        codes.append("MISSING_FRAME")
                elif analyze_pixel_paths:
                    p = Path(path_val)
                    if not p.is_file():
                        # Relative to inventory dir
                        alt = inv_path.parent / path_val
                        p = alt if alt.is_file() else p
                    if not p.is_file():
                        if "MISSING_FRAME" not in codes:
                            codes.append("MISSING_FRAME")
                    else:
                        try:
                            st = analyze_png(p)
                        except Exception as e:  # noqa: BLE001
                            if "MISSING_FRAME" not in codes:
                                codes.append("MISSING_FRAME")
                            continue
                        if st.black and "BLACK_FRAME" not in codes:
                            codes.append("BLACK_FRAME")
                        if st.solid and "SOLID_COLOR" not in codes:
                            codes.append("SOLID_COLOR")

    check_role("scene", scene_frames)
    check_role("video", video_frames)

    # Interval: top-level intervalSeconds and/or dual capturedAt timestamps.
    interval = data.get("intervalSeconds")
    if interval is not None:
        if not isinstance(interval, (int, float)) or isinstance(interval, bool):
            die_usage("intervalSeconds must be a number when present")
        if float(interval) < MIN_INTERVAL_SECONDS:
            if "FRAME_INTERVAL_TOO_SHORT" not in codes:
                codes.append("FRAME_INTERVAL_TOO_SHORT")

    # Cross-role earliest/latest capturedAt if both present.
    times: list[datetime] = []
    for fr in scene_frames + video_frames:
        cap = fr.get("capturedAt")
        if cap is None:
            continue
        dt = parse_iso8601(cap) if isinstance(cap, str) else None
        if dt is not None:
            times.append(dt)
    if len(times) >= 2:
        times_sorted = sorted(times)
        gap = (times_sorted[-1] - times_sorted[0]).total_seconds()
        if gap < MIN_INTERVAL_SECONDS:
            if "FRAME_INTERVAL_TOO_SHORT" not in codes:
                codes.append("FRAME_INTERVAL_TOO_SHORT")

    # Also check consecutive pairs within the same role when ≥2 frames.
    for role_frames in (scene_frames, video_frames):
        role_times: list[datetime] = []
        for fr in role_frames:
            cap = fr.get("capturedAt")
            if isinstance(cap, str):
                dt = parse_iso8601(cap)
                if dt is not None:
                    role_times.append(dt)
        if len(role_times) >= 2:
            role_times.sort()
            for i in range(1, len(role_times)):
                gap = (role_times[i] - role_times[i - 1]).total_seconds()
                if gap < MIN_INTERVAL_SECONDS:
                    if "FRAME_INTERVAL_TOO_SHORT" not in codes:
                        codes.append("FRAME_INTERVAL_TOO_SHORT")
                    break

    message = (
        f"scene_frames={len(scene_frames)} video_frames={len(video_frames)} "
        f"codes={codes}"
    )
    return codes, message, data


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="WP-12E non-black / non-solid frame analyzer (fail-closed)"
    )
    p.add_argument(
        "images",
        nargs="*",
        help="one or two PNG paths (mutually exclusive with --inventory)",
    )
    p.add_argument(
        "--inventory",
        metavar="PATH",
        help=f"inventory JSON ({SCHEMA})",
    )
    p.add_argument(
        "--require-dual",
        action="store_true",
        help="require both scene and video samples (or two images)",
    )
    p.add_argument(
        "--analyze-paths",
        action="store_true",
        help="when inventory has frame path fields, open PNGs and recompute stats",
    )
    p.add_argument(
        "--json-out",
        metavar="PATH",
        help="optional path to write machine-readable result JSON",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.inventory and args.images:
        die_usage("pass either image paths or --inventory, not both")
    if not args.inventory and not args.images:
        die_usage("provide image path(s) or --inventory PATH")

    result: dict[str, Any] = {
        "ok": False,
        "codes": [],
        "message": "",
        "backend": "pil" if HAS_PIL else "pure-png",
        "schemaVersion": SCHEMA if args.inventory else None,
    }

    try:
        if args.inventory:
            inv = Path(args.inventory)
            if not inv.is_file():
                die_usage(f"inventory not found: {inv}")
            codes, message, _data = analyze_inventory(
                inv,
                require_dual=bool(args.require_dual),
                analyze_pixel_paths=bool(args.analyze_paths),
            )
            result["codes"] = codes
            result["message"] = message
            result["mode"] = "inventory"
        else:
            paths = [Path(x) for x in args.images]
            if len(paths) > 2:
                die_usage("at most two image paths supported")
            codes, stats, message = analyze_image_paths(
                paths, require_dual=bool(args.require_dual)
            )
            result["codes"] = codes
            result["message"] = message
            result["mode"] = "images"
            result["frames"] = [
                {
                    "path": s.path,
                    "width": s.width,
                    "height": s.height,
                    "meanLuminance": round(s.mean_luminance, 6),
                    "variance": round(s.variance, 6),
                    "black": s.black,
                    "solid": s.solid,
                }
                for s in stats
            ]
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"INTERNAL_ERROR\nERROR: {e}", file=sys.stderr)
        return 3

    for c in codes:
        emit_code(c)

    ok = len(codes) == 0
    result["ok"] = ok
    status = "PASS" if ok else "FAIL"
    print(f"{status}|{','.join(codes)}|{result['message']}")

    if args.json_out:
        outp = Path(args.json_out)
        outp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
