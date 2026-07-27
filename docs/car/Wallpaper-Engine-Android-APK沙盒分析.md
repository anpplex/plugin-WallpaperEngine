# Wallpaper Engine Android APK — 沙盒静态分析报告

> **分析对象**：官方直链 APK  
> `https://www.wallpaperengine.io/android/apk/wallpaper-engine.apk`  
> **分析环境**：本地沙盒 `sandbox/we-android/`（解包 / jadx 反编译 / 符号与包格式解析）  
> **分析日期**：2026-07-27  
> **目的**：为 Motif 车机动壁纸产品对齐官方架构、资产格式与能力边界；**不复制闭源引擎，不二次分发 APK/so**。

---

## 1. 样本指纹

| 项 | 值 |
|---|---|
| 文件大小 | ~139 MB（145,592,226 bytes） |
| SHA-256 | `6982c82745444c5f2eef5a3d8c89ad807360bb5849a133548a6b25d18f4c4cb0` |
| 包名 | `io.wallpaperengine.weclient` |
| versionName | **2.8.8** |
| versionCode | **4354** |
| minSdk | **29**（Android 10） |
| targetSdk / compileSdk | **35**（Android 15） |
| Build flavor | `international` / `release` |
| BUILD_TIME | `1779936743365`（epoch ms，写入 native 初始化） |
| 应用名 | Wallpaper Engine |
| Application | `io.wallpaperengine.weclient.WEClient` |
| 强制 Live Wallpaper | `android.software.live_wallpaper` **required** |
| OpenGL ES | **3.0 required**（`glEsVersion=0x30000`） |
| 陀螺仪 | optional |
| extractNativeLibs | false（page-aligned so） |

### 原生库

| ABI | 库 | 约大小 |
|---|---|---|
| arm64-v8a | `libscenejni.so` | **~40 MB** |
| armeabi-v7a | `libscenejni.so` | **~28 MB** |

**无 x86 / x86_64**。车机若为 arm64 可装；模拟器 x86 不可直接跑官方 so。

### DEX

- `classes.dex` ~9.2 MB  
- `classes2.dex` ~2.2 MB  
- 语言栈：**Kotlin**（UI / Service）+ **C++ native Scene 引擎**

---

## 2. 产品能力地图（从 Manifest + UI 字符串 + 代码）

### 2.1 支持的壁纸类型（运行时二分）

`WEWallpaperService.GLWallpaperEngine.loadWallpaper()`：

```
type = SceneLib.getWallpaperType(file)
if type == "Scene"  → SceneWallpaperView  (GLSurfaceView + libscenejni)
else                → VideoWallpaperView  (含本地 video/gif；type==null 时 setLocalPlayer(true))
```

| 类型 | 运行路径 | 备注 |
|---|---|---|
| **Scene** | OpenGL ES 3 + 完整 Scene 运行时 + V8 SceneScript | 官方内置 9 个 demo 全是 scene |
| **Video / GIF / 本机媒体** | `VideoWallpaperView`：`SurfaceTexture` + GLES 合成 | 可直接 Import 本地视频/GIF |
| **Web / Application** | 未作为移动主路径 | 传输 UI 有 “type not supported on Android” |

### 2.2 核心用户功能

| 功能 | 实现组件 |
|---|---|
| 浏览库 / 详情 / 属性 | `BrowseActivity`, `FileDetailsActivity`, `WallpaperProperties` |
| 预览 | `PreviewActivity` |
| 设为系统动态壁纸 | `WEWallpaperService` → `WallpaperService` |
| PC 无线配对 | `DiscoverService` + `PairingActivity` + `TcpClient` |
| 传输接收 | `TransferService`（FGS `dataSync`） |
| 离线导入 `.mpkg` / `.bin` | Intent VIEW pathPattern + `ImportFileFragment` |
| 播放列表 | `PlaylistFragment` / `PlaylistSettingsActivity`：随机 / 顺序 / 星期 / 时段 |
| 通用设置 | `GeneralSettingsActivity`：FPS、触控、日志、省电暂停等 |
| 视差 | `ParallaxController` → `sendNormalizedParallaxOffset` |
| 触控 / 重力 / 自由对齐 | `sendTouchInput` / `sendGravityInput` / `sendFreeAlignmentXForm` |
| 音频 FFT（可选） | `AudioRecorder` → `sendAudioData(fft64)`；**产品层壁纸仍默认无声出画** |

### 2.3 权限与用途

| 权限 | 用途推断 |
|---|---|
| INTERNET / ACCESS_NETWORK_STATE / ACCESS_WIFI_STATE | 配对与传输 |
| CHANGE_WIFI_MULTICAST_STATE | UDP 组播发现 `239.100.0.1:7884` |
| FOREGROUND_SERVICE + DATA_SYNC | `TransferService` 大文件接收 |
| SET_WALLPAPER | 系统动态壁纸 |
| READ_MEDIA_VIDEO / IMAGES | 本机导入 |
| RECORD_AUDIO / MODIFY_AUDIO_SETTINGS | 可选音频响应（Scene） |
| HIGH_SAMPLING_RATE_SENSORS | 陀螺仪视差 |
| WAKE_LOCK / POST_NOTIFICATIONS | 传输通知与保活 |
| 无 READ_EXTERNAL_STORAGE 旧权限 | 走 MediaStore / SAF |

---

## 3. 架构（官方 App 分层）

```
┌──────────────────────────────────────────────────────────────┐
│ UI (Kotlin)                                                   │
│  Browse / Preview / Pairing / Settings / Import / Playlist    │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│ Services                                                      │
│  WEWallpaperService  ── 系统 Live Wallpaper 生命周期              │
│  DiscoverService     ── UDP 7884 组播发现                        │
│  TransferService     ── 前台服务接收 .mpkg                       │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│ Views                                                         │
│  SceneWallpaperView  ── GLSurfaceView + SceneLib native        │
│  VideoWallpaperView  ── SurfaceTexture OES + GLES 合成/滤镜     │
│  WallpaperControls   ── 统一 pause/resume/load/property 接口    │
└────────────────────────────┬─────────────────────────────────┘
                             │ JNI
┌────────────────────────────▼─────────────────────────────────┐
│ libscenejni.so (~40MB arm64)                                  │
│  • GLES3 渲染管线 (PBR/粒子/HDR/模糊/体积光…)                   │
│  • SceneScript = 嵌入式 V8 (v8:: / SceneScriptEngine)         │
│  • 粒子系统 ParticleSystem / 图像层 ImageLayer                 │
│  • 包枚举 / project.json 解析 / 预览图 / 版本校验                │
│  • FreeType 字体、glm、json、absl 等静态链接                    │
│  • AAssetManager 读 assets（内置 shader/material/字体）         │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 JNI 表面（`SceneLib` → `libscenejni`）

完整 native 方法列表（产品集成边界）：

| 类别 | 方法 |
|---|---|
| 生命周期 | `init`, `initContext`, `destroyContext`, `initScene`, `shutdownScene`, `cancelLoadingScene`, `updateScene`, `resizeScene` |
| 库管理 | `enumerateWallpapers`, `isWallpaperVersionValid`, `getWallpaperType/Resolution/ProjectString/InfoSparse/PreviewBitmap`, `getWallpaperFileVirtualOffset` |
| 属性 | `applySceneProperties`, `getSceneProperties`, `getSceneFeatureFlags`, `getSceneCanvasSize` |
| 输入 | `sendTouchInput`, `sendForceInput`, `sendGravityInput`, `sendNormalizedParallaxOffset`, `sendFreeAlignmentXForm`, `sendAudioData` |
| 本地化 | `setLanguage`, `getLocalization`, `getUserLocalizations` |
| 调试 | `setLogToFileEnabled` |

**结论**：官方把「引擎」整块放在 so 里；Java 层只是 Android 壳 + 传输 + 视频旁路。

---

## 4. 网络与传输协议（产品侧）

| 通道 | 端口 / 地址 | 用途 |
|---|---|---|
| 发现 | **UDP Multicast `239.100.0.1:7884`** | PC 广播 / 手机发现 |
| 数据 | **TCP `7889`** | 配对认证 + 文件传输 |
| 认证 | PIN + **RSA 公钥交换 + AES 加密 GSON** | `TcpClient.performAuthentication` |
| 指令 | `beginUpload` / `transmissionStart` / `transmissionContinue` / `transmissionCancel` | `TransferService` |
| 包版本协商 | `MPKG_SUPPORT_VERSION = "PKGM0020"` | App 支持到 PKGM0020；内置样例为 0012–0018 |

**法律/产品**：Workshop 不直连手机；须 PC 端转码导出 + 创作者 Workshop 附加协议。

---

## 5. 资产格式：`.mpkg`（移动包）

### 5.1 容器格式（与桌面 `.pkg` / PKGV 同构）

```
u32  headerLen          // 固定 8
char header[headerLen]  // "PKGMxxxx"  e.g. PKGM0014 / PKGM0018 / 协议宣称 PKGM0020
u32  entryCount
repeat entryCount:
  u32  pathLen
  char path[pathLen]    // UTF-8，无 '\0'
  u32  offset           // 相对「目录表结束后」的数据区
  u32  length
// 随后连续 blob 数据区
```

与 Open Wallpaper Engine 的 `PKGParser`（`PKGV*`）结构一致，仅魔数为 **`PKGM`**。

**解析结果（内置 9 包）**：全部 `type: scene`（或等价 scene 入口文件），无 video 样例。

| 包名 | 魔数 | 文件数 | 标题 |
|---|---|---|---|
| deep_space | PKGM0014 | 14 | Deep Space |
| dino_run | PKGM0018 | 119 | （含大量材质/动效） |
| dna_fragment | PKGM0014 | 25 | DNA Fragment |
| earth_parallax | PKGM0012 | 21 | Earth Parallax |
| fantastic_car | PKGM0014 | 36 | Fantastic Car |
| neon_sunset | PKGM0014 | 25 | Neon sunset |
| razer_vortex | PKGM0014 | 17 | （Razer 风格） |
| shimmering_particles | PKGM0012 | 13 | 粒子 |
| techno | PKGM0012 | 27 | Techno |

### 5.2 包内典型目录

```
project.json          # 元数据：title/type/file/preview/general.properties
scene.json | *.json   # 场景图（camera/objects/general）
preview.jpg | .gif
materials/**/*.json + *.tex
models/**/*.json | *.mdl
shaders/**/*.frag|.vert
effects/**/effect.json
particles/**/*.json
scripts/**/*.json     # 相机/脚本配置（非完整 JS 源时可内嵌）
```

`project.json` 关键字段：

```json
{
  "title": "Deep Space",
  "type": "scene",
  "file": "scene.json",
  "preview": "preview.jpg",
  "official": true,
  "general": { "properties": { "schemecolor": { "type": "color", "value": "..." } } }
}
```

### 5.3 纹理 `.tex`

头：`TEXV0005\0TEXI0001...`（版本化自定义二进制纹理，非 PNG）。  
移动导出时 PC 端 **transcoder** 会降分辨率（UI：Highest / half / quarter）并转码视频。

### 5.4 PC 导出质量档（UI 字符串）

- **Dynamic**：保留 Scene 实时渲染  
- **Pre-Rendered**：可把部分内容烤成视频（失败时有 `failed_converting_video`）  
- Preset：**High Quality / Balanced / High Performance**  
- Texture Reduction：原图 / ×2 / ×4  
- Video：FPS、裁剪（手机屏适配）

---

## 6. 引擎资产（APK `assets/`）

| 目录 | 数量级 | 说明 |
|---|---|---|
| `shaders/` | ~130 | 通用/粒子/HDR/模糊/字体/体积光… **GLSL 源码随包** |
| `materials/` | ~497 | 粒子纹理、工具材质、编辑器残留资源 |
| `models/` | 少量 util/editor | 全屏层等 |
| `scripts/` | baseclasses + wecolor/wemath/wevector | SceneScript 运行时 JS 基础库 |
| `fonts/` | 含 NotoSans CJK ~19MB、Twemoji 等 | 多语言/emoji |
| `locale/` | core_* + ui_* 30+ 语言 | **ui 含完整 PC 编辑器字符串**（同源 i18n） |
| `wallpapers/*.mpkg` | 9 | 开箱演示 |
| `html/` | 隐私/ToS | 合规页 |

**shader 兼容策略**（与 docs 一致）：同一套语义目标 GLES；坏 effect 可降级移除。

---

## 7. 与 Motif / 车机的对照

| 维度 | 官方 WE Android | Motif（阿维塔 user12） |
|---|---|---|
| 目标设备 | 手机/平板 Android 10+ | 车机多用户座舱 |
| 内容主路径 | PC 库 → mpkg / 本机 video | 内置 + motif_live + U 盘 + HTTP |
| Scene 引擎 | 闭源 `libscenejni` + V8 | **无**；长期需自研子集或合法授权 |
| Video | VideoWallpaperView + ST | **已有** 双 MediaPlayer + crop |
| 设壁纸 | 标准 Live Wallpaper UI | shell `setWallpaperComponent` + WMS 自持 |
| 网络 | 7884/7889 配对 | 车机局域网/ADB；不走 WE 协议 |
| 音频 | 默认真壁纸无声；可选 FFT | 建议静音（导航/媒体） |
| 包格式 | PKGM + project.json | 可兼容 **video 型** 与 **mpkg 解压后播 mp4** |
| 法律 | 免费 Companion；Workshop 协议 | 自有/授权素材；勿嵌官方 so |

### 可合法复用的「思想/格式」

1. **`project.json` 契约**（type/file/preview/properties）  
2. **PKGM 容器解析**（与 OWE PKGV 同源，已在沙盒验证）  
3. **Video / Scene 双路径切换**  
4. **质量档 + 降级**（高分辨率预转码、坏层跳过）  
5. **播放列表模式**（时段/随机）— 车机「驾驶/驻车」场景可映射  
6. **省电/不可见暂停** — 与 `onVisibilityChanged` 对齐  
7. **docs 移动 shader 规范** — 若未来做 GLES 2D 层  

### 不可做

- 提取/链接 `libscenejni.so` 进 Motif（闭源、ToS、签名、ABI）  
- 冒充官方 App 做 Workshop 传输  
- 分发官方 APK 作为车机产品  

---

## 8. 沙盒产物位置

```
Motif/sandbox/we-android/
  wallpaper-engine.apk          # 官方样本（勿提交远端大文件时注意体积）
  unpack/
    assets/wallpapers/*.mpkg
    mpkg_all/<name>/            # 已解包的 9 个演示包
    mpkg_summary.json
    lib/arm64-v8a/libscenejni.so
  jadx_out/sources/io/wallpaperengine/  # 反编译 Kotlin/Java
```

本地 mpkg 解析可复用 OWE：`PKGParser` 逻辑，魔数改为 `PKGM`。

---

## 9. 风险与合规摘要

| 风险 | 说明 |
|---|---|
| 版权 | 演示 mpkg / so / shader 属 Skutta；仅内部分析 |
| 逆向边界 | 静态架构分析 OK；勿发布破解或协议完整复刻用于盗版传输 |
| 车机装官方 App | 可能缺 GMS、多用户隔离、非 arm 兼容；**不能替代 Motif 绑定链路** |
| 依赖 PC | 官方模型强绑定 Windows WE；车机产品必须自洽导入 |

---

## 10. 一句话结论

> **官方 Android Companion = 轻量 Kotlin 壳 + 重型闭源 GLES3/V8 Scene 引擎（libscenejni）+ 视频旁路 + 局域网 mpkg 管道。**  
> Motif 应对齐其 **产品分层与资产契约**，用自有 Video 引擎交付，Scene 仅作可选长期路线；**不要移植 so**。
