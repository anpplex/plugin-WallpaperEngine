# 官方「不支持 Android 动态壁纸」弹窗 · 修复说明

## 现象

预览页点 ✓（应用壁纸）→ 弹窗：

> 无法应用壁纸 / 您的设备可能不支持 Android 动态壁纸

**与具体 mpkg 无关**（75681 等预览可 PASS）。

## 根因

`Util.callApplyWallpaper`：

1. 写入 `selectedWallpaper`（prefs）— 往往成功  
2. 若引擎未激活 → `Intent(CHANGE_LIVE_WALLPAPER)`  
3. 华为/阿维塔 HU **无标准 Live Wallpaper 设置页** → 异常 → 弹窗  

## 修复（本仓已提供脚本）

### 立刻上主屏（推荐）

```bash
cd /Users/anpple/Codex/WallpaperEngine

# 完整：写 prefs（需 su）+ 绑定 + 重启引擎
./scripts/we-apply-shell.sh LD249H019625 downloads/75681.mpkg 12

# 若已点过官方 ✓（prefs 可能已有路径），或无 root：
./scripts/we-bind-only.sh LD249H019625 12
```

期望 `dumpsys wallpaper` user12：

```text
mWallpaperComponent=…io.wallpaperengine.weclient/.WEWallpaperService
```

### 冷启动丢失（CB-FAIL）

今天实测重启后会变成 Motif 视频壁纸。开机后：

```bash
./scripts/we-boot-rebind.sh LD249H019625 12
```

可挂 Mac LaunchAgent（设备上线自动跑），与 Motif 自持同思路。

## 产品侧原则

| 错误做法 | 正确做法 |
|---|---|
| 依赖官方 ✓ / CHANGE_LIVE_WALLPAPER | shell `SetWpUser` 绑定 WE |
| 以为 75681 包坏了 | 包可预览；只修 Apply |
| 只绑一次不管开机 | 开机再绑（CB-FAIL） |

## 与入库关系

1. 导入 → 官方 `files/downloads/xxx.mpkg`（VIEW / 扫库）  
2. Apply → `selectedWallpaper=downloads/xxx.mpkg` + 绑定组件  
3. 重启 → 再绑组件  

车机壳 UI 入库后会提示上述 shell 命令（pending 路径）。
