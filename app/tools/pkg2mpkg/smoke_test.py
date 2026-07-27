#!/usr/bin/env python3
"""Offline smoke tests for pkg2mpkg (no adb / car required)."""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pkg2mpkg import (  # noqa: E402
    TEX_ETC2_RGBA,
    _tex_container_meta,
    analyze_tex,
    encode_tex_etc2_mobile,
    extract_image_from_tex,
    load_source,
    read_pkg,
    tex_header,
    write_pkg,
)

try:
    import lz4.block as lz4_block
except ImportError:
    print("FAIL: pip install lz4")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src" / "main" / "assets" / "we_packs"
TESTDATA = ROOT / "testdata"


def check_etc2_structure(label: str, blob: bytes) -> list[str]:
    errs: list[str] = []
    h = tex_header(blob)
    if not h:
        return [f"{label}: bad TEX header"]
    fmt, flags, tw, th, iw, ih, _unk = h
    meta = _tex_container_meta(blob)
    if not meta:
        return [f"{label}: cannot parse TEXB"]
    free_fmt, is_lz4, decomp, w, hgt = meta
    if fmt != TEX_ETC2_RGBA:
        errs.append(f"{label}: fmt={fmt} want 5")
    if free_fmt != -1:
        errs.append(f"{label}: free_fmt={free_fmt} want -1")
    if not is_lz4:
        errs.append(f"{label}: expected LZ4")
    exp = ((w + 3) // 4) * ((hgt + 3) // 4) * 16
    if decomp != exp:
        errs.append(f"{label}: decomp={decomp} exp_astc_or_etc2={exp}")
    # decompress and check size
    i = blob.find(b"TEXB")
    off = i + 9 + 8  # after count+free
    if blob[i : i + 8].startswith(b"TEXB0004"):
        off += 4
    off += 4 + 8 + 4 + 4  # mips + wh + lz4 + decomp
    bc = struct.unpack_from("<I", blob, off)[0]
    off += 4
    payload = blob[off : off + bc]
    try:
        raw = lz4_block.decompress(payload, uncompressed_size=decomp)
    except Exception as e:
        errs.append(f"{label}: lz4 fail {e}")
        return errs
    if len(raw) != exp:
        errs.append(f"{label}: raw len {len(raw)} != {exp}")
    return errs


def test_roundtrip_small() -> None:
    from PIL import Image

    img = Image.new("RGBA", (64, 64), (180, 40, 120, 255))
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), (x * 4, y * 4, 128, 255))
    tex = encode_tex_etc2_mobile(img, max_edge=64)
    errs = check_etc2_structure("roundtrip", tex)
    if errs:
        raise AssertionError(errs)
    # pack/unpack container
    pkg = write_pkg("PKGM0019", {"materials/t.tex": tex, "project.json": b'{"title":"t","type":"scene"}'})
    magic, files = read_pkg(pkg)
    assert magic == "PKGM0019"
    assert "materials/t.tex" in files
    print("  OK roundtrip small ETC2 + PKGM")


def test_mobile_samples_untouched() -> None:
    for name in ("75681.mpkg", "95769.mpkg"):
        p = ASSETS / name
        if not p.is_file():
            print(f"  SKIP missing {name}")
            continue
        magic, files = read_pkg(p.read_bytes())
        assert magic.startswith("PKGM"), name
        texes = [analyze_tex(k, v) for k, v in files.items() if k.endswith(".tex")]
        bad = [t for t in texes if t.fmt == 5 and not t.mobile_ready]
        if bad:
            raise AssertionError(f"{name} false-desktop: {[t.path for t in bad]}")
        # structure check first fmt=5
        for k, v in files.items():
            if k.endswith(".tex") and tex_header(v) and tex_header(v)[0] == 5:
                errs = check_etc2_structure(f"{name}:{k}", v)
                if errs:
                    raise AssertionError(errs)
                break
        print(f"  OK {name} already mobile (magic={magic})")


def test_convert_dva() -> None:
    src = Path("/Users/anpple/Downloads/1994794519")
    if not src.is_dir():
        print("  SKIP DVA workshop dir missing")
        return
    from pkg2mpkg import cmd_convert

    out = TESTDATA / "1994794519_mobile.mpkg"
    rc = cmd_convert(
        src,
        out,
        max_edge=1920,
        magic="PKGM0019",
        force_reencode=True,
        quality=90,
        mode="etc2",
        astc_quality="medium",
        astcenc=None,
    )
    if rc != 0:
        raise AssertionError(f"convert rc={rc}")
    magic, files = read_pkg(out.read_bytes())
    assert magic == "PKGM0019"
    n = 0
    for k, v in files.items():
        if not k.endswith(".tex"):
            continue
        errs = check_etc2_structure(k, v)
        if errs:
            raise AssertionError(errs)
        n += 1
    print(f"  OK DVA convert → {out.name} ({n} TEX ETC2, {out.stat().st_size} bytes)")


def test_convert_second_desktop() -> None:
    src = Path(
        "/Users/anpple/Downloads/d-va-overwatch-18-x-ray-nsfw_6kZk_VSTHEMES-ORG/2017159732"
    )
    if not (src / "scene.pkg").is_file():
        print("  SKIP second desktop pack missing")
        return
    from pkg2mpkg import cmd_convert

    out = TESTDATA / "2017159732_mobile.mpkg"
    rc = cmd_convert(
        src,
        out,
        max_edge=1920,
        magic="PKGM0019",
        force_reencode=True,
        quality=90,
        mode="etc2",
        astc_quality="medium",
        astcenc=None,
    )
    if rc != 0:
        raise AssertionError(f"convert rc={rc}")
    magic, files = read_pkg(out.read_bytes())
    assert magic == "PKGM0019"
    for k, v in files.items():
        if k.endswith(".tex"):
            errs = check_etc2_structure(k, v)
            if errs:
                raise AssertionError(errs)
    # decode path should have worked (source was JPEG-in-TEX)
    desk_magic, desk_files = load_source(src)[:2]
    print(f"  OK second pack convert src={desk_magic} → {out.name} ({out.stat().st_size} bytes)")


def main() -> int:
    print("pkg2mpkg smoke_test (offline)")
    failed = 0
    for name, fn in [
        ("roundtrip", test_roundtrip_small),
        ("mobile_samples", test_mobile_samples_untouched),
        ("convert_dva", test_convert_dva),
        ("convert_second", test_convert_second_desktop),
    ]:
        print(f"[{name}]")
        try:
            fn()
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1
    print("PASS" if failed == 0 else f"FAILED {failed} case(s)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
