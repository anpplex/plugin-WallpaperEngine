#!/usr/bin/env python3
"""
pkg2mpkg: Wallpaper Engine desktop PKG/scene → Android-friendly PKGM mpkg.

Container layout shared by PKGV/PKGM (see RePKG PackageReader/Writer):
  u32 magic_len + magic
  u32 entry_count
  entries: path_len + path + offset + length
  contiguous blobs

TEX: TEXV0005 / TEXI0001 header (RePKG TexReader). Desktop often embeds
JPEG (FreeImage FIF_JPEG=2) or DXT. Official mobile packs (car-verified
75681/95769) use format=5 (ETC2 RGBA8), free_fmt=-1, LZ4-compressed blocks.

Default convert mode is etc2 (requires: pip install Pillow lz4 etcpak).
Other modes: rgba (raw+LZ4), astc (experimental), jpeg (desktop-style, fails on car).

References:
  https://github.com/notscuffed/repkg
  https://github.com/masterLazy/RePKG.Neo
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    print("Pillow required: pip install Pillow", file=sys.stderr)
    sys.exit(1)

try:
    import lz4.block as lz4_block
except ImportError:
    lz4_block = None  # type: ignore

# FreeImageFormat
FIF_JPEG = 2
FIF_UNKNOWN = -1

# TexFormat (desktop RePKG + mobile extensions observed on Android packs)
TEX_RGBA8888 = 0
# Mobile WE fmt=5 is ETC2 RGBA8 (EAC_R11 + ETC2), 16 bytes / 4x4 block.
# Confirmed by decoding car-working 75681/95769 packs with decode_etc2a8.
TEX_ETC2_RGBA = 5
TEX_RG88 = 8
TEX_R8 = 9

_TOOL_DIR = Path(__file__).resolve().parent
_DEFAULT_ASTCENC = _TOOL_DIR / "bin" / "astcenc"


# ---------------------------------------------------------------------------
# Package I/O (PKGV / PKGM)
# ---------------------------------------------------------------------------

def read_pkg(data: bytes) -> Tuple[str, Dict[str, bytes]]:
    hl = struct.unpack_from("<I", data, 0)[0]
    if hl < 4 or hl > 64:
        raise ValueError(f"bad magic length {hl}")
    magic = data[4 : 4 + hl].decode("ascii", "replace")
    pos = 4 + hl
    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if n > 100_000:
        raise ValueError(f"bad entry count {n}")
    entries: List[Tuple[str, int, int]] = []
    for _ in range(n):
        plen = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        path = data[pos : pos + plen].decode("utf-8", "replace")
        pos += plen
        off, length = struct.unpack_from("<II", data, pos)
        pos += 8
        entries.append((path, off, length))
    base = pos
    files = {p: data[base + o : base + o + ln] for p, o, ln in entries}
    return magic, files


def write_pkg(magic: str, files: Dict[str, bytes]) -> bytes:
    magic_b = magic.encode("ascii")
    paths = sorted(files.keys())
    table: List[Tuple[str, int, int]] = []
    offset = 0
    blobs: List[bytes] = []
    for p in paths:
        b = files[p]
        table.append((p, offset, len(b)))
        blobs.append(b)
        offset += len(b)
    out = bytearray()
    out += struct.pack("<I", len(magic_b))
    out += magic_b
    out += struct.pack("<I", len(table))
    for p, off, ln in table:
        pb = p.encode("utf-8")
        out += struct.pack("<I", len(pb))
        out += pb
        out += struct.pack("<II", off, ln)
    for b in blobs:
        out += b
    return bytes(out)


# ---------------------------------------------------------------------------
# TEX analyze / decode / encode
# ---------------------------------------------------------------------------

@dataclass
class TexInfo:
    path: str
    size: int
    fmt: int
    flags: int
    tw: int
    th: int
    mobile_ready: bool
    note: str = ""


def tex_header(blob: bytes) -> Optional[Tuple[int, int, int, int, int, int, int]]:
    if len(blob) < 50 or blob[:8] != b"TEXV0005" or blob[8] != 0:
        return None
    if blob[9:17] != b"TEXI0001" or blob[17] != 0:
        return None
    return struct.unpack_from("<7I", blob, 18)


def _tex_container_meta(blob: bytes) -> Optional[Tuple[int, int, int, int, int]]:
    """Return (free_fmt, is_lz4, decomp, w, h) for first mip if parseable."""
    i = _find_texb(blob)
    if i < 0:
        return None
    magic = blob[i : i + 8]
    off = i + 8
    if off < len(blob) and blob[off] == 0:
        off += 1
    if off + 8 > len(blob):
        return None
    off += 4  # image count
    free_fmt = struct.unpack_from("<i", blob, off)[0]
    off += 4
    if magic.startswith(b"TEXB0004"):
        if off + 4 > len(blob):
            return None
        off += 4  # isVideoMp4
    if off + 20 > len(blob):
        return None
    _mip_count = struct.unpack_from("<I", blob, off)[0]
    off += 4
    w, h = struct.unpack_from("<II", blob, off)
    off += 8
    is_lz4 = struct.unpack_from("<I", blob, off)[0]
    off += 4
    decomp = struct.unpack_from("<I", blob, off)[0]
    return free_fmt, is_lz4, decomp, w, h


def analyze_tex(path: str, blob: bytes) -> TexInfo:
    h = tex_header(blob)
    if not h:
        return TexInfo(path, len(blob), -1, 0, 0, 0, False, "not TEXV0005/TEXI0001")
    fmt, flags, tw, th, iw, ih, unk = h
    meta = _tex_container_meta(blob)
    free_fmt = meta[0] if meta else None
    # Car-working packs: free_fmt=-1 and either:
    #   fmt=5 ASTC4x4 (decomp == ceil(w/4)*ceil(h/4)*16), or
    #   fmt=0/8/9 raw channels LZ4, or embedded image only when free_fmt image.
    # Desktop JPEG-in-TEX uses free_fmt=FIF_JPEG(2) and fails on Android.
    is_jpeg_embed = free_fmt == FIF_JPEG or (
        free_fmt is None and blob.find(b"\xff\xd8\xff") > 0 and fmt == 0
    )
    if is_jpeg_embed and fmt in (0, 5):
        mobile = False
        note = "desktop JPEG-in-TEX (needs reencode)"
    elif fmt == TEX_ETC2_RGBA and free_fmt == FIF_UNKNOWN:
        mobile = True
        note = "mobile ETC2_RGBA"
    elif fmt in (TEX_RGBA8888, TEX_RG88, TEX_R8) and free_fmt == FIF_UNKNOWN:
        mobile = True
        note = "mobile raw+LZ4"
    elif fmt in (TEX_ETC2_RGBA, TEX_R8, TEX_RG88):
        mobile = free_fmt == FIF_UNKNOWN
        note = "mobile-like" if mobile else f"fmt={fmt} free={free_fmt}"
    else:
        mobile = False
        note = "desktop-like (needs reencode)"
    return TexInfo(path, len(blob), fmt, flags, tw, th, mobile, note)


def _find_texb(blob: bytes) -> int:
    return blob.find(b"TEXB")


def extract_image_from_tex(blob: bytes) -> Optional[Image.Image]:
    """Best-effort image from desktop/mobile TEX using RePKG-like layout."""
    h = tex_header(blob)
    if not h:
        return None
    i = _find_texb(blob)
    if i < 0:
        # raw jpeg/png somewhere
        return _image_from_embedded(blob)

    off = i + 8
    if off < len(blob) and blob[off] == 0:
        off += 1
    magic = blob[i : i + 8]  # TEXB0003 / TEXB0004

    if off + 8 > len(blob):
        return _image_from_embedded(blob)

    image_count = struct.unpack_from("<I", blob, off)[0]
    off += 4
    free_fmt = None
    if magic.startswith(b"TEXB0003") or magic.startswith(b"TEXB0004"):
        free_fmt = struct.unpack_from("<i", blob, off)[0]
        off += 4
        if magic.startswith(b"TEXB0004") and off + 4 <= len(blob):
            # isVideoMp4 flag
            off += 4

    if image_count < 1 or image_count > 64:
        return _image_from_embedded(blob)

    # First image: mipmapCount then first mipmap (V2/V3 layout)
    if off + 4 > len(blob):
        return None
    mip_count = struct.unpack_from("<I", blob, off)[0]
    off += 4
    if mip_count < 1 or mip_count > 32:
        return _image_from_embedded(blob)

    w, hgt = struct.unpack_from("<II", blob, off)
    off += 8
    is_lz4 = struct.unpack_from("<I", blob, off)[0] == 1
    off += 4
    decomp = struct.unpack_from("<I", blob, off)[0]
    off += 4
    byte_count = struct.unpack_from("<I", blob, off)[0]
    off += 4
    if byte_count <= 0 or off + byte_count > len(blob):
        return _image_from_embedded(blob)
    payload = blob[off : off + byte_count]

    # JPEG / PNG embedded
    if payload[:3] == b"\xff\xd8\xff" or free_fmt == FIF_JPEG:
        try:
            return Image.open(io.BytesIO(payload)).convert("RGBA")
        except Exception:
            pass
    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            return Image.open(io.BytesIO(payload)).convert("RGBA")
        except Exception:
            pass

    # LZ4 raw RGBA (optional dependency)
    if is_lz4 and decomp > 0:
        try:
            import lz4.frame  # type: ignore

            raw = lz4.frame.decompress(payload)
            if len(raw) >= w * hgt * 4:
                return Image.frombytes("RGBA", (w, hgt), raw[: w * hgt * 4])
        except Exception:
            try:
                import lz4.block  # type: ignore

                raw = lz4.block.decompress(payload, uncompressed_size=decomp)
                if len(raw) >= w * hgt * 4:
                    return Image.frombytes("RGBA", (w, hgt), raw[: w * hgt * 4])
            except Exception:
                pass

    # Uncompressed RGBA8888
    if len(payload) >= w * hgt * 4 and h[0] == 0:
        try:
            return Image.frombytes("RGBA", (w, hgt), payload[: w * hgt * 4])
        except Exception:
            pass

    return _image_from_embedded(blob)


def _image_from_embedded(blob: bytes) -> Optional[Image.Image]:
    for sig in (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"):
        j = blob.find(sig)
        if j >= 0:
            try:
                return Image.open(io.BytesIO(blob[j:])).convert("RGBA")
            except Exception:
                continue
    return None


def _resize_max_edge(img: Image.Image, max_edge: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_edge:
        return img
    scale = max_edge / max(w, h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    # ASTC 4x4 prefers multiples of 4 for clean block grid
    nw = max(4, (nw + 3) // 4 * 4)
    nh = max(4, (nh + 3) // 4 * 4)
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _avg_unk(img: Image.Image) -> int:
    rgb = img.convert("RGB").resize((1, 1)).getpixel((0, 0))
    return 0xFF000000 | (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


def _lz4_compress(raw: bytes) -> bytes:
    if lz4_block is None:
        raise RuntimeError("lz4 required: pip install lz4")
    # store=True → raw LZ4 block (matches WE / RePKG, no frame header)
    return lz4_block.compress(raw, store_size=False)


def _find_astcenc(explicit: Optional[Path] = None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("ASTCENC")
    if env:
        candidates.append(Path(env))
    candidates.append(_DEFAULT_ASTCENC)
    for name in ("astcenc", "astcenc-neon", "astcenc-avx2"):
        which = Path(name)
        candidates.append(which)
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
        # PATH lookup
        import shutil

        p = shutil.which(str(c))
        if p:
            return Path(p)
    raise FileNotFoundError(
        "astcenc not found. Place binary at tools/pkg2mpkg/bin/astcenc "
        "or set ASTCENC= (ARM astc-encoder release)."
    )


def _encode_astc_4x4(img: Image.Image, *, quality: str = "medium", astcenc: Optional[Path] = None) -> bytes:
    """Return raw ASTC 4x4 block payload (no .astc file header)."""
    enc = _find_astcenc(astcenc)
    img = img.convert("RGBA")
    w, h = img.size
    with tempfile.TemporaryDirectory(prefix="pkg2mpkg-astc-") as td:
        td_path = Path(td)
        png = td_path / "in.png"
        astc = td_path / "out.astc"
        img.save(png, format="PNG")
        # -cl = LDR linear (mobile samples look linear, not sRGB profile flag)
        cmd = [
            str(enc),
            "-cl",
            str(png),
            str(astc),
            "4x4",
            f"-{quality}",
            "-silent",
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        data = astc.read_bytes()
    # .astc container: 16-byte header + blocks
    if len(data) >= 16 and data[:4] == bytes([0x13, 0xAB, 0xA1, 0x5C]):
        blocks = data[16:]
    else:
        blocks = data
    expected = ((w + 3) // 4) * ((h + 3) // 4) * 16
    if len(blocks) != expected:
        raise ValueError(f"ASTC size mismatch got {len(blocks)} expected {expected} for {w}x{h}")
    return blocks


def _pack_tex_raw_mip(
    *,
    fmt_code: int,
    flags: int,
    tw: int,
    th: int,
    iw: int,
    ih: int,
    unk: int,
    payload: bytes,
    decomp_size: int,
    use_lz4: bool,
    container: bytes = b"TEXB0003",
) -> bytes:
    body = payload
    if use_lz4:
        body = _lz4_compress(payload)
    out = bytearray()
    out += b"TEXV0005\x00"
    out += b"TEXI0001\x00"
    out += struct.pack("<7I", fmt_code, flags, tw, th, iw, ih, unk)
    out += container + b"\x00"
    out += struct.pack("<I", 1)  # image count
    out += struct.pack("<i", FIF_UNKNOWN)  # free_fmt = -1 (not FreeImage)
    out += struct.pack("<I", 1)  # mipmap count
    out += struct.pack("<II", tw, th)
    out += struct.pack("<I", 1 if use_lz4 else 0)
    out += struct.pack("<I", decomp_size if use_lz4 else 0)
    out += struct.pack("<I", len(body))
    out += body
    return bytes(out)


def _encode_etc2_rgba(img: Image.Image) -> Tuple[bytes, int, int]:
    """ETC2 RGBA8 block payload via etcpak (pip install etcpak). Returns (blocks, w, h)."""
    try:
        import etcpak
    except ImportError as e:
        raise RuntimeError("etcpak required for ETC2: pip install etcpak") from e
    img = img.convert("RGBA")
    w, h = img.size
    # ETC2 requires multiples of 4
    nw, nh = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
    if (nw, nh) != (w, h):
        canvas = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
        canvas.paste(img, (0, 0))
        img = canvas
        w, h = nw, nh
    rgba = img.tobytes("raw", "RGBA")
    blocks = etcpak.compress_etc2_rgba(rgba, w, h)
    expected = (w // 4) * (h // 4) * 16
    if len(blocks) != expected:
        raise ValueError(f"ETC2 size mismatch got {len(blocks)} expected {expected} for {w}x{h}")
    return blocks, w, h


def encode_tex_etc2_mobile(
    img: Image.Image,
    *,
    max_edge: int = 1920,
    flags: int = 2,
) -> bytes:
    """
    Mobile-compatible TEX matching car-verified packs (75681 / 95769):
      TEXV0005 / TEXI0001
      format=5 (ETC2 RGBA8), flags=2 (ClampUVs)
      TEXB0003, free_fmt=-1, 1 mip, LZ4-compressed ETC2 blocks
    """
    img = _resize_max_edge(img.convert("RGBA"), max_edge)
    blocks, w, h = _encode_etc2_rgba(img)
    return _pack_tex_raw_mip(
        fmt_code=TEX_ETC2_RGBA,
        flags=flags,
        tw=w,
        th=h,
        iw=w,
        ih=h,
        unk=_avg_unk(img),
        payload=blocks,
        decomp_size=len(blocks),
        use_lz4=True,
    )


def encode_tex_astc_mobile(
    img: Image.Image,
    *,
    max_edge: int = 1920,
    flags: int = 2,
    quality: str = "medium",
    astcenc: Optional[Path] = None,
) -> bytes:
    """
    Experimental ASTC 4x4 TEX (fmt still written as 5 — NOT what mobile WE uses).
    Prefer encode_tex_etc2_mobile for Android.
    """
    img = _resize_max_edge(img.convert("RGBA"), max_edge)
    w, h = img.size
    blocks = _encode_astc_4x4(img, quality=quality, astcenc=astcenc)
    return _pack_tex_raw_mip(
        fmt_code=TEX_ETC2_RGBA,  # same numeric slot; payload differs
        flags=flags,
        tw=w,
        th=h,
        iw=w,
        ih=h,
        unk=_avg_unk(img),
        payload=blocks,
        decomp_size=len(blocks),
        use_lz4=True,
    )


def encode_tex_rgba_lz4_mobile(
    img: Image.Image,
    *,
    max_edge: int = 1920,
    flags: int = 2,
) -> bytes:
    """Fallback: fmt=0 RGBA8888 + free_fmt=-1 + LZ4 (works for particle TEXes on car)."""
    img = _resize_max_edge(img.convert("RGBA"), max_edge)
    w, h = img.size
    raw = img.tobytes("raw", "RGBA")
    return _pack_tex_raw_mip(
        fmt_code=TEX_RGBA8888,
        flags=flags,
        tw=w,
        th=h,
        iw=w,
        ih=h,
        unk=_avg_unk(img),
        payload=raw,
        decomp_size=len(raw),
        use_lz4=True,
    )


def encode_tex_jpeg_mobile(
    img: Image.Image,
    *,
    max_edge: int = 1920,
    quality: int = 90,
    fmt_code: int = 5,
    flags: int = 2,
) -> bytes:
    """Legacy JPEG-in-TEX (desktop style). Prefer encode_tex_astc_mobile for Android."""
    img = img.convert("RGBA")
    img = _resize_max_edge(img, max_edge)
    w, h = img.size
    bg = Image.new("RGB", (w, h), (40, 40, 40))
    bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=quality, optimize=True)
    jpeg = buf.getvalue()
    unk = _avg_unk(bg)
    out = bytearray()
    out += b"TEXV0005\x00"
    out += b"TEXI0001\x00"
    out += struct.pack("<7I", fmt_code, flags, w, h, w, h, unk)
    out += b"TEXB0003\x00"
    out += struct.pack("<I", 1)
    out += struct.pack("<i", FIF_JPEG)
    out += struct.pack("<I", 1)
    out += struct.pack("<II", w, h)
    out += struct.pack("<I", 0)
    out += struct.pack("<I", 0)
    out += struct.pack("<I", len(jpeg))
    out += jpeg
    return bytes(out)


def encode_tex_mobile(
    img: Image.Image,
    *,
    max_edge: int = 1920,
    mode: str = "etc2",
    jpeg_quality: int = 90,
    astc_quality: str = "medium",
    astcenc: Optional[Path] = None,
) -> bytes:
    mode = mode.lower()
    if mode in ("etc2", "etc2_rgba", "mobile"):
        return encode_tex_etc2_mobile(img, max_edge=max_edge)
    if mode == "astc":
        return encode_tex_astc_mobile(
            img, max_edge=max_edge, quality=astc_quality, astcenc=astcenc
        )
    if mode in ("rgba", "rgba_lz4", "lz4"):
        return encode_tex_rgba_lz4_mobile(img, max_edge=max_edge)
    if mode == "jpeg":
        return encode_tex_jpeg_mobile(img, max_edge=max_edge, quality=jpeg_quality)
    raise ValueError(f"unknown encode mode: {mode}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load_source(path: Path) -> Tuple[str, Dict[str, bytes], Path]:
    """Return magic, files, project_dir."""
    path = path.resolve()
    if path.is_file() and path.suffix.lower() in (".pkg", ".mpkg"):
        magic, files = read_pkg(path.read_bytes())
        return magic, files, path.parent
    if path.is_dir():
        pkg = path / "scene.pkg"
        if not pkg.is_file():
            pkgs = list(path.glob("*.pkg")) + list(path.glob("*.mpkg"))
            if not pkgs:
                raise FileNotFoundError(f"no scene.pkg/mpkg in {path}")
            pkg = pkgs[0]
        magic, files = read_pkg(pkg.read_bytes())
        # overlay project.json / preview from directory
        for name in ("project.json", "preview.jpg", "preview.gif", "preview.png"):
            fp = path / name
            if fp.is_file():
                files[name] = fp.read_bytes()
        return magic, files, path
    raise FileNotFoundError(path)


def cmd_analyze(path: Path) -> int:
    magic, files, _ = load_source(path)
    print(f"magic: {magic}")
    print(f"entries: {len(files)}  bytes: {sum(len(v) for v in files.values())}")
    if "project.json" in files:
        proj = json.loads(files["project.json"])
        print(f"title: {proj.get('title')}")
        print(f"type: {proj.get('type')}  file: {proj.get('file')}")
        print(f"workshopid: {proj.get('workshopid')}")
    texes = [analyze_tex(p, b) for p, b in files.items() if p.endswith(".tex")]
    mobile = sum(1 for t in texes if t.mobile_ready)
    desk = sum(1 for t in texes if not t.mobile_ready)
    print(f"textures: {len(texes)}  mobile_ready≈{mobile}  need_reencode≈{desk}")
    for t in sorted(texes, key=lambda x: -x.size)[:12]:
        print(
            f"  [{('OK' if t.mobile_ready else 'DESKTOP'):7}] "
            f"fmt={t.fmt} {t.tw}x{t.th} {t.size:9d}  {t.path}"
        )
    if desk:
        print("\n→ convert recommended before Android import")
        return 2
    print("\n→ already mobile-like; convert will mostly re-wrap PKGM")
    return 0


def cmd_convert(
    path: Path,
    out: Path,
    *,
    max_edge: int,
    magic: str,
    force_reencode: bool,
    quality: int,
    mode: str,
    astc_quality: str,
    astcenc: Optional[Path],
) -> int:
    src_magic, files, root = load_source(path)
    print(f"source magic={src_magic} entries={len(files)} mode={mode}")

    # ensure project.json
    if "project.json" not in files:
        # minimal project
        title = root.name
        files["project.json"] = json.dumps(
            {
                "title": title,
                "type": "scene",
                "file": "scene.json" if "scene.json" in files else "scene.json",
                "preview": "preview.jpg" if "preview.jpg" in files else "preview.gif",
            },
            indent=2,
        ).encode("utf-8")

    report: Dict = {
        "source": str(path),
        "mode": mode,
        "reencoded": [],
        "kept": [],
        "failed": [],
    }

    new_files: Dict[str, bytes] = {}
    for p, blob in files.items():
        if not p.endswith(".tex"):
            new_files[p] = blob
            continue
        info = analyze_tex(p, blob)
        if info.mobile_ready and not force_reencode:
            new_files[p] = blob
            report["kept"].append(p)
            continue
        img = extract_image_from_tex(blob)
        if img is None:
            # keep original but warn
            new_files[p] = blob
            report["failed"].append({"path": p, "reason": "decode_failed"})
            print(f"  WARN decode failed, keep raw: {p}")
            continue
        try:
            new_tex = encode_tex_mobile(
                img,
                max_edge=max_edge,
                mode=mode,
                jpeg_quality=quality,
                astc_quality=astc_quality,
                astcenc=astcenc,
            )
            new_files[p] = new_tex
            report["reencoded"].append(
                {
                    "path": p,
                    "from": f"fmt={info.fmt} {info.tw}x{info.th}",
                    "to_size": len(new_tex),
                    "mode": mode,
                }
            )
            print(
                f"  reencode {p}: {info.tw}x{info.th} fmt={info.fmt} → "
                f"{len(new_tex)} bytes ({mode})"
            )
        except Exception as e:
            new_files[p] = blob
            report["failed"].append({"path": p, "reason": str(e)})
            print(f"  FAIL reencode {p}: {e}")

    # normalize project type string
    try:
        proj = json.loads(new_files["project.json"])
        if str(proj.get("type", "")).lower() == "scene":
            proj["type"] = "scene"
        new_files["project.json"] = (json.dumps(proj, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    except Exception:
        pass

    packed = write_pkg(magic, new_files)
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(packed)
    report_path = out.with_suffix(out.suffix + ".report.json")
    report["output"] = str(out)
    report["output_bytes"] = len(packed)
    report["magic"] = magic
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({len(packed)} bytes)")
    print(f"report {report_path}")
    print(
        f"summary reencoded={len(report['reencoded'])} kept={len(report['kept'])} failed={len(report['failed'])}"
    )
    return 0 if not report["failed"] else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_an = sub.add_parser("analyze", help="Inspect pkg/mpkg/folder")
    p_an.add_argument("path", type=Path)

    p_cv = sub.add_parser("convert", help="Convert to Android-oriented mpkg")
    p_cv.add_argument("path", type=Path)
    p_cv.add_argument("-o", "--output", type=Path, required=True)
    p_cv.add_argument("--max-edge", type=int, default=1920, help="Max texture edge (default 1920)")
    p_cv.add_argument("--magic", default="PKGM0019", help="Package magic (default PKGM0019)")
    p_cv.add_argument("--force-reencode", action="store_true", help="Reencode even mobile-like TEX")
    p_cv.add_argument(
        "--mode",
        choices=("etc2", "astc", "rgba", "jpeg"),
        default="etc2",
        help="Texture encode mode (default etc2 = mobile fmt=5 ETC2_RGBA+LZ4)",
    )
    p_cv.add_argument("--quality", type=int, default=90, help="JPEG quality 1-95 (mode=jpeg)")
    p_cv.add_argument(
        "--astc-quality",
        default="medium",
        choices=("fastest", "fast", "medium", "thorough", "exhaustive"),
        help="astcenc quality preset (default medium)",
    )
    p_cv.add_argument("--astcenc", type=Path, default=None, help="Path to astcenc binary")

    args = ap.parse_args(argv)
    if args.cmd == "analyze":
        return cmd_analyze(args.path)
    if args.cmd == "convert":
        return cmd_convert(
            args.path,
            args.output,
            max_edge=args.max_edge,
            magic=args.magic,
            force_reencode=args.force_reencode,
            quality=args.quality,
            mode=args.mode,
            astc_quality=args.astc_quality,
            astcenc=args.astcenc,
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
