# Wallpaper Engine Android — 沙盒全特性对齐计划

> **约束（本次明确）**：沙盒研发，**不考虑版权与商用**；目标 = **Android 版 Wallpaper Engine Companion 全部特性 1:1 对齐**。  
> **样本**：`sandbox/we-android/` 内官方 APK **2.8.8 (4354)** + jadx 源 + `libscenejni.so`。  
> **非目标**：PC 编辑器 / Workshop 创作端（locale 里混有 PC 字符串，以下矩阵以 **APK 实装组件** 为准）。

---

## 1. 总策略：二进制引擎 + 壳层复刻

要「所有特性」且工期可控，沙盒采用：

| 层级 | 策略 | 原因 |
|---|---|---|
| **Scene 运行时** | **直接加载官方 `libscenejni.so`** | 内含 GLES3 + V8 SceneScript + 粒子/PBR；自研等价 人年级 |
| **JNI 壳** | 保持包名 `io.wallpaperengine.wrapper.SceneLib` | JNI 符号 `Java_io_wallpaperengine_wrapper_SceneLib_*` 写死 |
| **Java/Kotlin UI/Service** | 以 jadx 输出为基线 **移植/修复可编译** | 已反编译 70+ 类，逻辑完整 |
| **Assets** | 从 APK 原样抽取 `assets/` | shader/material/字体/内置 mpkg/locale |
| **视频路径** | 移植 `VideoWallpaperView` | 官方本就走 Java 侧 SurfaceTexture |
| **网络** | 移植 `DiscoverService` + `TcpClient` + `TransferService` | 协议在 Java，非 so |
| **车机绑定（可选附加）** | Motif shell `setWallpaperComponent` | 官方走系统选壁纸；车机可双轨 |

```
┌─────────────────────────────────────────────────────────────┐
│  we-parity（沙盒 App，包名建议仍用 io.wallpaperengine.weclient）│
│  ┌──────────── Kotlin/Java（jadx 移植）───────────────────┐  │
│  │ Browse / Preview / Pair / Settings / Playlist / Import │  │
│  │ WEWallpaperService / DiscoverService / TransferService │  │
│  │ SceneWallpaperView / VideoWallpaperView                │  │
│  └───────────────────────┬───────────────────────────────┘  │
│                          │ JNI 同名 SceneLib                 │
│  ┌───────────────────────▼───────────────────────────────┐  │
│  │ libscenejni.so（APK 抽取 arm64/armeabi-v7a）            │  │
│  │ + assets/*（APK 抽取）                                  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**验收定义「全特性」**：下表 **F-*** 全部为 ✅ 或等价通过；与官方 2.8.8 行为差仅限 OEM 差异（锁屏/省电）。

---

## 2. 完整特性矩阵（Android App 实装）

### 2.1 壁纸类型与播放

| ID | 特性 | 官方实现 | 沙盒路径 | 优先级 |
|---|---|---|---|---|
| F-T01 | Scene 2D/3D 交互壁纸 | `SceneWallpaperView` + `libscenejni` | **复用 so** | P0 |
| F-T02 | Video 壁纸 | `VideoWallpaperView` + 解码 + OES 纹理 | 移植 jadx | P0 |
| F-T03 | GIF 壁纸 | Video 路径 / GifDrawable | 移植 | P0 |
| F-T04 | 本机 Import 视频/图片 | `ImportFileFragment` + MediaStore | 移植 | P0 |
| F-T05 | `.mpkg` 导入 | Intent `*.mpkg` + 引擎解包 | 移植 + assets | P0 |
| F-T06 | `.bin` 导入 | 同 pathPattern | 移植 | P1 |
| F-T07 | 类型探测 | `SceneLib.getWallpaperType` → `"Scene"` / 其他 | so | P0 |
| F-T08 | 版本校验 | `isWallpaperVersionValid` / PKGM0020 | so + `MPKG_SUPPORT_VERSION` | P0 |
| F-T09 | 预览缩略图 | `getWallpaperInfoPreviewBitmap` | so | P0 |
| F-T10 | 分辨率查询 | `getWallpaperResolution` | so | P1 |
| F-T11 | 虚拟文件偏移 | `getWallpaperFileVirtualOffset`（大包内视频） | so | P1 |
| F-T12 | 官方内置 9 演示包 | `assets/wallpapers/*.mpkg` | 拷 assets | P0 |

### 2.2 系统 Live Wallpaper

| ID | 特性 | 官方实现 | 沙盒路径 |
|---|---|---|---|
| F-W01 | `WallpaperService` | `WEWallpaperService` | 移植 |
| F-W02 | Engine 创建/销毁 | `GLWallpaperEngine` | 移植 |
| F-W03 | Surface 生命周期 | onSurfaceCreated/Destroyed | 移植 |
| F-W04 | 可见性暂停 | `onVisibilityChanged` | 移植 |
| F-W05 | 配置变更/旋转 | `onConfigurationChanged` + screenRotation | 移植 |
| F-W06 | WallpaperColors | `onComputeColors` + `colorsApi` | 移植 |
| F-W07 | 外部 RELOAD | `requestWallpaperReload` | 移植 |
| F-W08 | 预览模式 isPreview | Engine 内分支 | 移植 |
| F-W09 | 应用为壁纸入口 | Preview 长按/系统 UI | 移植 |
| F-W10 | 锁屏（OEM 相关） | 系统能力，非 App 可强保证 | 文档 + 实测 |

### 2.3 渲染与输入（Scene）

| ID | 特性 | JNI / 组件 |
|---|---|---|
| F-R01 | GLES3 场景循环 | `updateScene` / `resizeScene` |
| F-R02 | 触控 | `sendTouchInput` + 设置开关 |
| F-R03 | 力反馈式输入 | `sendForceInput` |
| F-R04 | 重力/陀螺仪 | `sendGravityInput` + sensors |
| F-R05 | 视差 | `ParallaxController` → `sendNormalizedParallaxOffset` |
| F-R06 | 自由对齐/缩放平移 | `FreeAlignTouchHandler` + `sendFreeAlignmentXForm` |
| F-R07 | 对齐模式 portrait/landscape | `PROP_ALIGNMENT*` |
| F-R08 | 用户属性 apply | `applySceneProperties(json)` |
| F-R09 | 读属性 | `getSceneProperties` / feature flags |
| F-R10 | 画布尺寸 | `getSceneCanvasSize` |
| F-R11 | 音频 FFT 入引擎 | `AudioRecorder` → `sendAudioData(fft64)` |
| F-R12 | FPS 限制 | `GeneralSettingsInfo.maxFps` / `maxFpsNano` |
| F-R13 | 像素画优化 | `PROP_PIXEL_ART_OPTIMIZATION` |
| F-R14 | 调色 WEC | brightness/contrast/hue/sat `wec_*` |
| F-R15 | 运动响应 | `PROP_MOTION_RESPONSE` |
| F-R16 | Shader 错误日志 | `setLogToFileEnabled` + Save Error Log（设置项） |

### 2.4 视频路径专属

| ID | 特性 | 说明 |
|---|---|---|
| F-V01 | SurfaceTexture 帧回调 | `OnFrameAvailableListener` |
| F-V02 | GLES 合成/滤镜 | combine_video 等 shader 在 assets |
| F-V03 | 本地播放器 vs 引擎内视频 | `setLocalPlayer(type==null)` |
| F-V04 | 循环 | 官方视频默认 loop |
| F-V05 | 无声策略 | 产品默认静音出画（可保留 FFT 可选） |
| F-V06 | Crop / 对齐 | 与 alignment 属性共用 |

### 2.5 浏览与库管理

| ID | 特性 | 组件 |
|---|---|---|
| F-B01 | 主浏览列表 | `BrowseActivity` + `BrowseFragment` |
| F-B02 | 排序 | `SortMethod` |
| F-B03 | 详情页 | `FileDetailsActivity` |
| F-B04 | 属性编辑 | `WallpaperProperties` Preference |
| F-B05 | 预览页 | `PreviewActivity` |
| F-B06 | 枚举库 | `SceneLib.enumerateWallpapers` + 本地列表 |
| F-B07 | 本地壁纸列表持久化 | `Util.readLocalWallpapers` |
| F-B08 | 删除/管理 | Browse action mode |
| F-B09 | 多选 | actionMode |
| F-B10 | 官方 blacklist | `readOfficialBlacklist` |

### 2.6 播放列表

| ID | 特性 | 键/模式 |
|---|---|---|
| F-P01 | 播放列表 CRUD | `PlaylistFragment` / `PlaylistData` |
| F-P02 | 模式 random | `PLAYLIST_MODE_RANDOM` |
| F-P03 | 模式 sorted | `PLAYLIST_MODE_SORTED` |
| F-P04 | 模式 dayOfWeek（≤7） | `PLAYLIST_MODE_DAY_OF_WEEK` |
| F-P05 | 模式 timeOfDay | `PLAYLIST_MODE_TIME_OF_DAY` |
| F-P06 | 切换间隔 duration | 默认 30s；引擎侧 5s 轮询检查 |
| F-P07 | 列表设置页 | `PlaylistSettingsActivity` |
| F-P08 | 保存/加载命名列表 | UI 字符串齐全，移植逻辑 |
| F-P09 | 启动首壁纸策略 | begin first / intro wallpaper |

### 2.7 全局设置

| ID | 特性 | `GeneralSettingsInfo` / Props |
|---|---|---|
| F-S01 | maxFps | 默认 30 |
| F-S02 | touchInputEnabled | 默认 true |
| F-S03 | powerSavingEnabled | 默认 true；广播暂停 |
| F-S04 | logToFileEnabled | shader/错误日志 |
| F-S05 | colorsApi | enabled / disabled / hints |
| F-S06 | auto_connect | 配对自动连 |
| F-S07 | match_preview | 预览匹配 |
| F-S08 | 语言 | `setLanguage` + locale json |
| F-S09 | 法律页 ToS/Privacy | `LegalActivity` + assets/html |
| F-S10 | 滚动提示 has_shown_scroll_warning | 一次性 |

### 2.8 配对与传输（全协议）

| ID | 特性 | 实现 |
|---|---|---|
| F-N01 | UDP 组播发现 | `239.100.0.1:7884` MulticastSocket |
| F-N02 | 手动 IP | `DiscoverDevicesActivity` Enter IP |
| F-N03 | TCP 数据通道 | 端口 **7889** |
| F-N04 | PIN 认证 | 4 位 + 队列消息 |
| F-N05 | RSA + AES 会话 | `RSAPublicKeyHelper` + `TcpClient` |
| F-N06 | 加密 GSON 命令 | `sendEncryptedGSONObject` |
| F-N07 | beginUpload / transmission* | `TransferService` |
| F-N08 | 前台服务传输 | FGS dataSync + 通知 |
| F-N09 | 断点/取消 | transmissionCancel/Continue |
| F-N10 | 设备配对持久化 | `PairedServer` / pairings json |
| F-N11 | mpkg 版本协商 | `PKGM0020` |
| F-N12 | 多设备 | Device list UI |
| F-N13 | 传输进度 UI | DownloadInfo 回调 |

### 2.9 本地化与资源

| ID | 特性 |
|---|---|
| F-L01 | 30+ 语言 `assets/locale` |
| F-L02 | 引擎内 token 本地化 `getLocalization` |
| F-L03 | 壁纸用户本地化 `getUserLocalizations` |
| F-L04 | 全套字体含 CJK / emoji |
| F-L05 | 内置 materials/shaders/scripts |

### 2.10 合规与产品壳（沙盒也要对齐行为）

| ID | 特性 |
|---|---|
| F-C01 | 首次 ToS | LegalActivity |
| F-C02 | FileProvider | 分享/导出路径 |
| F-C03 | 无广告/无追踪 | 保持空实现即可 |
| F-C04 | baseline profile | assets/dexopt 可选 |

### 2.11 车机附加（全特性之外的增强，可选）

| ID | 特性 | 说明 |
|---|---|---|
| X-01 | multi-user user12 bind | Motif shell 绑定 |
| X-02 | 无系统壁纸 UI 时强制组件 | Avatr |
| X-03 | motif_live 路径扫描 | 与 WE 库并列 |

---

## 3. 工程结构（沙盒）

```
Motif/sandbox/we-parity/
  README.md
  FEATURE_CHECKLIST.md          # 可勾选矩阵（由本计划生成）
  scripts/
    01-extract-from-apk.sh      # 抽 so/assets/AndroidManifest
    02-sync-jadx-sources.sh     # 同步反编译源到 app 模块
    03-build-debug.sh
  app/                          # Android Application
    src/main/
      AndroidManifest.xml       # 以官方 manifest 为基线裁剪/对齐
      java/io/wallpaperengine/  # jadx 移植
      jniLibs/arm64-v8a/libscenejni.so
      jniLibs/armeabi-v7a/libscenejni.so
      assets/                   # 从 APK 同步
  tools/
    mpkg_extract.py             # 已有，可 symlink
    protocol_notes.md           # 7884/7889 抓包笔记
```

**Gradle**：独立 `settings.gradle` 或挂到 Motif 的 `include(":sandbox-we-parity")`（推荐独立，避免污染量产 app）。

**签名/包名**：沙盒 debug 可用官方同包名便于覆盖安装官方 App 做 A/B；若冲突则 `io.wallpaperengine.weclient.parity` 但 **JNI 类全名必须仍为** `io.wallpaperengine.wrapper.SceneLib`（可放在同 APK 任意 applicationId 下，**类包名**才影响 JNI）。

---

## 4. 分阶段交付（全特性，零「永久砍掉」）

### Wave 0 — 可运行骨架（3–5 天）

| 任务 | 产出 |
|---|---|
| W0.1 抽 APK → jniLibs + assets | 脚本 01 |
| W0.2 空 App + `System.loadLibrary("scenejni")` + `SceneLib.initLibrary` | 不崩 |
| W0.3 拷贝官方 Manifest 组件声明 | Service/Activity 齐全 |
| W0.4 最小 `WEWallpaperService` 能选为壁纸 | 黑屏可接受 |
| W0.5 加载内置 `deep_space.mpkg` | Scene 出画 = **里程碑 A** |

**Gate A**：桌面/真机上官方内置 Scene 可渲染。

### Wave 1 — 库与预览（1 周）

| 任务 | 特性 ID |
|---|---|
| Browse 列表 + enumerateWallpapers | F-B01, F-B06 |
| PreviewActivity | F-B05 |
| FileDetails + 属性写回 | F-B03, F-B04, F-R08 |
| Import 本地视频/GIF + mpkg | F-T03–T05 |
| VideoWallpaperView 完整移植 | F-T02, F-V* |

**Gate B**：Scene + Video 两条路径均可设壁纸。

### Wave 2 — 输入与画质（1 周）

| 任务 | 特性 ID |
|---|---|
| 触控/视差/重力/自由对齐 | F-R02–R07 |
| 通用设置页 | F-S01–S07 |
| WallpaperColors | F-W06 |
| 音频 FFT 可选 | F-R11 |
| 日志导出 | F-R16, F-S04 |

**Gate C**：交互 Scene 与官方手感一致（同包对比）。

### Wave 3 — 播放列表（3–5 天）

| 任务 | 特性 ID |
|---|---|
| 四模式 + duration | F-P01–P06 |
| 设置页与持久化 | F-P07–P09 |
| Engine 5s 轮询切换 | 与官方一致 |

**Gate D**：隔夜 playlist 无崩。

### Wave 4 — 配对传输 100%（1–2 周）

| 任务 | 特性 ID |
|---|---|
| Discover 组播 + 手动 IP | F-N01–N02 |
| TcpClient 认证加密 | F-N03–N06 |
| TransferService 全命令 | F-N07–N13 |
| 与 Windows WE 真机互测 | 端到端 mpkg |

**Gate E**：PC「Send to Mobile」进沙盒库并可播放。

### Wave 5 — 打磨与全量回归（1 周）

| 任务 |
|---|
| 30+ 语言冒烟 |
| 官方 9 mpkg 全过 |
| 大包 / PKGM0012–0020 |
| 省电/可见性/旋转矩阵 |
| 与官方 2.8.8 并排 diff 清单 |
| FEATURE_CHECKLIST 全 ✅ |

**Gate F = 全特性对齐宣布完成**。

### Wave 6 — 车机附加（可选）

| 任务 | ID |
|---|---|
| user12 shell bind 双轨 | X-01–X-03 |
| 与 Motif 量产模块接口隔离 | 沙盒不污染 release |

---

## 5. 移植作业规范（jadx → 可编译）

1. **源**：`sandbox/we-android/jadx_out/sources/io/wallpaperengine/**`  
2. **修复顺序**：`wedata` → `wrapper` → `weutil` → `weviews` → `weclient`  
3. **依赖对齐**（从 APK 推断，构建时锁定）：  
   - Kotlin 2.x / AndroidX AppCompat / Preference / ConstraintLayout  
   - Gson  
   - Material（若布局需要）  
   - 可能：Glide/Coil（预览）、Kotlin coroutines  
4. **合成类**：jadx 的 `$$ExternalSynthetic*` 需手写还原为 lambda  
5. **R 资源**：用 `apktool d` 解 `res/`，或 aapt2 从官方 APK 链接资源表（推荐 **apktool 解包后以 smali/资源工程重建**，再逐步替换为 Kotlin）

### 5.1 双轨构建（推荐）

| 轨道 | 做法 | 适用 |
|---|---|---|
| **Track S（Smali 快车道）** | apktool 解包 → 改 debug → 重打包签名 | 最快全特性冒烟 |
| **Track K（Kotlin 重建）** | jadx 源 + 官方 res + so | 可维护、可改车机 |

**全特性验收以 Track S 为金标准；Track K 对齐 Track S 行为。**

```bash
# Track S 概念流程
apktool d wallpaper-engine.apk -o we-apktool
# 按需改 debuggable / 网络 cleartext
apktool b we-apktool -o we-parity-unsigned.apk
# zipalign + apksigner
```

---

## 6. 与 Motif 量产关系

| | 沙盒 we-parity | Motif 量产 |
|---|---|---|
| 目标 | WE Android **全特性** | 车机稳定视频 + 绑定 |
| 引擎 | 官方 so | 自有 MediaPlayer |
| 合并 | **不自动合并** | 仅挑选稳定特性反向移植 |
| 安装 | 可与官方同机对比 | user12 专用 |

沙盒完成后，量产侧可「按特性 cherry-pick」（例如 playlist、mpkg video），**不必**整包 so 上车。

---

## 7. 测试矩阵（Gate F）

| 用例 | 通过标准 |
|---|---|
| 9 内置 mpkg 全部 Apply | 出画且可交互（若有） |
| 导入本地 mp4/gif | 循环、对齐 |
| 导入 PC 导出 mpkg | 类型正确 |
| 属性改色/滑条 | 实时或下次加载生效与官方一致 |
| 视差/触控 | 与官方同壁纸对比 |
| Playlist 四模式 | 到点切换 |
| 省电开 | 暂停渲染 |
| 配对 PC | PIN 成功、收包、入库 |
| 旋转横竖屏 | alignment 矩阵正确 |
| 杀进程重启 | 壁纸恢复 |
| 日志开关 | 能导出 shader 错误 |

---

## 8. 工作量粗估（全职 1 人）

| Wave | 人天 |
|---|---|
| W0 Track S 金标准重打包 | 2–3 |
| W0–1 Track K 骨架 + Scene 出画 | 5–8 |
| W1 库/视频/导入 | 5–7 |
| W2 输入/设置 | 4–5 |
| W3 播放列表 | 3–4 |
| W4 网络全协议 | 7–10 |
| W5 回归 | 5 |
| **合计** | **约 6–8 周** 到 Gate F |

Track S 可在 **1 周内** 得到「可玩的全特性官方逻辑」；Track K 并行追平。

---

## 9. 立即执行清单（从现在开始）

1. ✅ APK 沙盒分析（已有）  
2. **本计划**（本文）  
3. `scripts/01-extract-from-apk.sh` — 抽 so/assets  
4. Track S：`apktool` 重打包 debug 版 `we-parity`  
5. Track K：Gradle 空壳 + loadLibrary + 内置 mpkg 冒烟  
6. 维护 `FEATURE_CHECKLIST.md` 逐项打勾  

---

## 10. 决策（沙盒锁定）

1. **全特性 = 官方 Android Companion 行为全集**，不砍 Scene/传输/V8。  
2. **Scene 引擎不自研重写**，沙盒 **绑定官方 libscenejni**。  
3. **Track S 为验收金机**；Track K 为可改代码主干。  
4. 版权/商店上架 **不在本次范围**。  
5. 车机增强单独 Wave 6，不阻塞 Gate F。

---

## 11. 指令约定

| 你说 | 执行 |
|---|---|
| **go Track S** | apktool 解包重签 debug 沙盒 APK |
| **go Track K** | 建 Gradle 工程 + 抽 so/assets + SceneLib 冒烟 |
| **go Wave 0** | Track S + Track K 同时开到 Gate A |
| **go all** | 按 Wave 0→5 连续推进（长工期） |
