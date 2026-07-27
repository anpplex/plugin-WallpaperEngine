# DVA 只有特效 vs Denia 完整显示 — 问题分析

> 样本  
> - **失败**：`/Users/anpple/Downloads/1994794519`（桌面 Workshop）→ 自制 `1994794519_DVA.mpkg`  
> - **成功**：`/Users/anpple/Downloads/95769_6kZk_VSTHEMES-ORG.mpkg`（移动导出 PKGM0019）

---

## 1. 现象

| | DVA（失败） | Denia 95769（成功） |
|---|---|---|
| 导入 | 能进库、能开预览 | 同左 |
| 预览 | **灰底 + 青色粒子**，无角色/房间 | **完整二次元角色与场景** |
| 主页 | 同样无底图 | **完整壁纸** |
| 绑定 | WE 组件绑定成功 | 同左 |

→ **投递链路正常**；DVA 是 **场景主图层未渲染**。

`preview.jpg` 里才有完整 D.VA 画面，说明资源意图是有底图的，只是运行时没画出来。

---

## 2. 根因：桌面纹理 ≠ 移动纹理（主因）

### 2.1 纹理头 `TEXI` 后第一字段

| 包 | 主纹理 flag0 | 含义 |
|---|---|---|
| Denia 背景/角色层 | **5** | 官方移动导出 / 转码后 |
| DVA `DVA壁纸-4kH.tex` | **0** | **桌面原始**，未移动转码 |

官方内置 Deep Space 等 mpkg 纹理同样是 **flag0=5**。

### 2.2 分辨率与体积

| | DVA 主图 | Denia 背景 |
|---|---|---|
| 尺寸 | **4096×2048** | 3840×2160（但已 mobile 编码） |
| 单张 .tex | ~7.5MB ×2 | 背景 ~1.1MB（压缩形态不同） |
| TEXB 元数据 | `(1, 2, 11)` 多 mip 桌面样式 | `(1, 0xFFFFFFFF, 0)` 移动样式 |

Android `libscenejni` 按 **OpenGL ES** 路径解码。PC 导出移动包时会：

- 重编码 `.tex`（flag → 5）  
- 常降分辨率 / 换压缩  
- 处理 effect 依赖  

我们把 **PKGV 桌面 `scene.pkg` 原样塞进 PKGM 壳**，**跳过了转码** → 主图 `genericimage2` 采样失败 → 只剩：

1. `clearcolor = 0.7 0.7 0.7`（灰底）  
2. 仍能跑的 **粒子系统**（贴图走引擎内置 `particle/bubbles/bubble3`）  

于是观感 =「只有特效没有壁纸」。

---

## 3. 场景结构差异（加重 DVA 观感）

### DVA（3 个 object）

```
1. image「DVA壁纸-4kH」  ← 唯一底图 + pulse/xray 特效
2. particle ×2            ← 粒子（内置气泡贴图）
```

底图一挂 → **几乎只剩粒子**。

### Denia（47 个 object）

```
背景 + 大量切图层（身体/头发/眼睛/锁链…）
+ 粒子/音频条等
```

主纹理均为 **mobile-ready**，图层多，即使个别 layer 失败也不至于整屏灰。

---

## 4. 其它次要因素（非主因，但记录）

| 因素 | DVA | 影响 |
|---|---|---|
| 包来源 | Steam 桌面 `scene.pkg` + 自打 mpkg | **致命** |
| PKGM 版本 | 自制 0014 | 次要（Denia 0019 也 OK） |
| 画布 | 4096×2048 | 偏大，但 Denia 也有 4K 级 canvas；关键仍是 TEX 编码 |
| 自定义 shader | pulse / xray 打进包内 | 底图失败后特效也无输入，主要可见的是粒子 |
| 中文路径 | `DVA壁纸-4kH` | 文件在包内齐全，不太像主因 |
| 粒子贴图 | 引用引擎 assets | 粒子能出 → 引擎资产路径正常 |

---

## 5. 导入链路对比（证明不是「没导入」）

```
两者相同成功段：
  mpkg → FileProvider VIEW → WE files/downloads/
  → isWallpaperVersionValid → PreviewActivity

分歧点：
  Scene 运行时加载 .tex
    Denia: mobile TEX (flag=5) → 主图层 OK
    DVA:   desktop TEX (flag=0) → 主图层失败 → 灰底+粒子
```

列表缩略图可用 `preview.jpg`，所以库里卡片仍可能「看起来正常」，**运行时 Scene 才露馅**。

---

## 6. 修复 / 正确用法

| 做法 | 说明 |
|---|---|
| **正确** | PC WE 打开该壁纸 → **Send to Mobile / Export .mpkg** → 再导入车机 |
| **可用替代** | PC 导出 **mp4** → Motif 视频引擎 |
| **错误** | 把 Workshop 目录 `scene.pkg` 直接打成 mpkg（当前 DVA 做法） |
| **产品侧** | 导入前检测：任一主 `.tex` 的 flag0≠5 → 提示「非移动包，请 PC 导出」 |

检测伪代码：

```text
for each .tex in mpkg:
  if TEXV0005 and flag0 != 5 and flag0 != 9:  # 9 有时用于 mask
    warn_desktop_texture(path)
```

---

## 7. 一句话

**DVA 不是导入失败，而是「桌面 4K 纹理未经移动转码」导致主图层不画；Denia 是官方 PKGM0019 移动包，纹理 flag=5，所以预览和主页都完整。**
