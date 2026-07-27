# pkg2mpkg — Workshop desktop → mobile mpkg

References:
- [notscuffed/repkg](https://github.com/notscuffed/repkg) — PKGV/TEX reverse
- [masterLazy/RePKG.Neo](https://github.com/masterLazy/RePKG.Neo) — same core + `.mpkg`
- Car-verified mobile packs: `75681`, `95769` (fmt=5 ETC2_RGBA + LZ4)

## What it does

```
scene.pkg (PKGV) + project.json + preview.*
        → detect desktop vs mobile TEX
        → decode desktop JPEG/PNG/… TEX
        → re-encode mobile-friendly TEX (default ETC2)
        → pack PKGM00xx .mpkg
```

Desktop Workshop packs often embed **JPEG inside TEX** (`fmt=0`, `free_fmt=FIF_JPEG`).  
Android WE on the car **does not** render those — you only get particles/FX on gray.

Official mobile packs use:

| Field | Value |
|---|---|
| TEX format | **5 = ETC2 RGBA8** (16 B / 4×4 block) |
| free_fmt | **-1** (not FreeImage) |
| container | TEXB0003 (or TEXB0004) |
| mip payload | LZ4-compressed ETC2 blocks |
| decomp size | `ceil(w/4)*ceil(h/4)*16` |

## Usage

```bash
# Analyze
python3 pkg2mpkg.py analyze /path/to/1994794519

# Convert (default --mode etc2)
python3 pkg2mpkg.py convert /path/to/1994794519 -o ./out/1994794519.mpkg

# Options
python3 pkg2mpkg.py convert DIR -o out.mpkg \
  --max-edge 1920 --magic PKGM0019 --mode etc2
```

### Modes

| Mode | Use |
|---|---|
| **`etc2`** (default) | Car-correct. Needs `pip install etcpak lz4 Pillow` |
| `rgba` | fmt=0 raw RGBA + LZ4 (works for small particles; large packs heavy) |
| `astc` | Experimental; car treats fmt=5 as ETC2 → looks like static |
| `jpeg` | Legacy desktop-style (will **fail** on car) |

Input: workshop folder with `scene.pkg`, bare `.pkg`/`.mpkg`, or directory.

## Car import

```bash
# Asset path inside Motif WallpaperEngine APK
adb -s SER shell am start --user 12 \
  -n com.motif.wallpaperengine/.MainActivity \
  --es import_asset we_packs/1994794519_mobile.mpkg

# Bind live wallpaper (OEM often blocks in-app Apply)
export CLASSPATH=/data/local/tmp/setwp_user.dex
app_process /system/bin SetWpUser \
  io.wallpaperengine.weclient \
  io.wallpaperengine.weclient.WEWallpaperService 12
```

## Deps

- Python 3.10+
- `Pillow`, `lz4`, **`etcpak`** (ETC2)
- Optional: `tools/pkg2mpkg/bin/astcenc` only for `--mode astc`

## DVA proof (2026-07-27)

- Raw desktop: gray + FX only  
- ETC2 mpkg: **full DVA scene in official Preview**  
  Audit: `Motif/audit-we-import-1994794519-etc2-20260727-170416/`
