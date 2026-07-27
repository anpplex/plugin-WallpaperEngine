# Motif × Wallpaper Engine 对齐 — 产品开发计划

> 依据：`docs/Wallpaper-Engine-Android-APK沙盒分析.md` + 官方 docs/help + 当前 Motif 能力  
> 目标：在阿维塔车机（user12）上交付「WE 级体验」中的可落地子集，并保留扩展到 Scene 的接口。

---

## 0. 产品定位

| | 说明 |
|---|---|
| **产品名** | Motif 动态壁纸（车机） |
| **对标** | Wallpaper Engine Android Companion 的 **使用体验**，非其二进制 |
| **不做什么** | 不嵌入 `libscenejni`；不实现 Workshop；不冒充官方配对协议商用 |
| **做什么** | 视频/GIF 级动态壁纸为 P0；WE 包资产兼容为 P1；Scene 2D 子集为 P2+ |

### 成功指标（车机）

1. 冷启动无 ADB 时，WMS 仍保持 Motif 引擎（已有文档链路）。  
2. 导入/切换壁纸无假成功，真正换到目标视频。  
3. 支持自有 MP4 + 可选 WE `project.json` video / 解压 mpkg 内视频。  
4. 切换无明显黑帧（双播放器）。  
5. 座舱横屏 crop、省电流程可测。

---

## 1. 现状基线（Motif）

| 能力 | 状态 |
|---|---|
| `VideoLiveWallpaperService` + 双 MediaPlayer | ✅ |
| shell bind / 系统自持 / Shizuku 可选 | ✅ |
| motif_live / U 盘 / HTTP 导入 | ✅ |
| 缩略图、滑动切换、可选 a11y | ✅ |
| WE `project.json` / `.mpkg` | ❌ |
| Scene / GLES 引擎 | ❌ |
| 播放列表（时段/随机） | 部分/弱 |

---

## 2. 能力分层（对标官方）

```
L0  系统壁纸绑定与保活          ← 已完成
L1  视频/GIF 播放与切换        ← 已完成（可打磨）
L2  资产管道（目录 + project.json + mpkg 子集）  ← 下一优先
L3  播放列表 / 时段 / 属性面板
L4  Scene 2D 子集（自研 GLES，可选）
L5  （不做）完整 3D + V8 SceneScript + 官方传输
```

---

## 3. 开发阶段与任务

### Phase 0 — 文档与沙盒固化（0.5–1 天）✅ 进行中

| ID | 任务 | 产出 |
|---|---|---|
| P0.1 | APK 沙盒分析报告 | `Wallpaper-Engine-Android-APK沙盒分析.md` |
| P0.2 | 本开发计划 | 本文档 |
| P0.3 | mpkg 解析脚本入库 | `sandbox/we-android/tools/mpkg_extract.py` |
| P0.4 | 内置 9 包 metadata 索引 | `mpkg_summary.json`（已有） |

**验收**：新同学读两篇文档能说清官方架构与 Motif 边界。

---

### Phase 1 — WE 视频包兼容（1–2 周）**推荐立刻做**

目标：用户把 **video 型** WE 工程目录或导出包放进车机，Motif 能识别并播放。

| ID | 任务 | 细节 |
|---|---|---|
| P1.1 | `WeProject` 数据模型 | 解析 `project.json`：`type/file/title/preview/general` |
| P1.2 | 扫描器扩展 | `motif_live/`、U 盘根目录、`*.mpkg`、含 project.json 的文件夹 |
| P1.3 | **mpkg 解包器** | 实现 PKGM 目录表解析（同 OWE PKGParser）；仅当 `type==video` 或包内存在 mp4/webm 时入库 |
| P1.4 | Video 路径绑定 | `file` 字段相对路径 → 绝对路径；预览图 `preview` |
| P1.5 | 拒绝策略 | `type==scene` 且无预渲染视频 → 明确 UI「暂不支持 Scene」而非崩溃 |
| P1.6 | 导入 UX | 与现有「一键 motif_live」合并；导入后 RELOAD |
| P1.7 | 测试素材 | 自建最小 video 工程 + 可选从 PC Export 的 video mpkg（自有版权） |

**验收**：

- [ ] 解压官方 demo mpkg **不**误播（scene 应提示不支持）  
- [ ] 自建 `type:video` + mp4 可应用为壁纸  
- [ ] 切换无 setBitmap 假成功  

**不在 Phase 1**：解析 `.tex`、跑 shader、V8。

---

### Phase 2 — 播放体验与车机产品化（1–2 周）

对标官方 Companion 的「好用」部分，不碰 Scene 引擎。

| ID | 任务 | 对标官方 |
|---|---|---|
| P2.1 | 播放列表：顺序 / 随机 / 间隔 | `Playlist` + 5s 检查定时器思路 |
| P2.2 | 时段壁纸（驻车/夜间可选） | `TIME_OF_DAY` 模式简化 |
| P2.3 | 可见性暂停 | `onVisibilityChanged` / 省电广播 |
| P2.4 | FPS / 分辨率策略 | 车机固定 30fps、最大 1080p 预转码建议 |
| P2.5 | 属性面板 MVP | 仅 scheme 色占位或静音开关（视频层） |
| P2.6 | 冷启动无 ADB 验收清单写入文档 | 接 `开机自启-不依赖Shizuku.md` |
| P2.7 | 缩略图与列表性能 | 官方 `getWallpaperInfoPreviewBitmap` 对标 |

**验收**：连续切换 20 次无泄漏；灭屏/亮屏壁纸恢复；播放列表过夜不崩。

---

### Phase 3 — 资产工具链（并行，1 周）

| ID | 任务 | 说明 |
|---|---|---|
| P3.1 | PC/Mac 小工具：目录 → Motif pack | zip：`project.json` + mp4 + preview |
| P3.2 | 可选：FFmpeg 车机侧转码 | 大分辨率 → 1080p H.264 |
| P3.3 | 与 BYD/自有素材库批量导入脚本 | 扩展现有 push/import |

**验收**：设计师投递 zip，车机一键扫库可用。

---

### Phase 4 — Scene 2D 子集（可选，4–12 周，高风险）

**仅当**产品明确要求「粒子/视差/多层 2D」且接受自研成本。

| ID | 任务 | 参考 |
|---|---|---|
| P4.1 | 评估 OWE Scene 解析 + Metal/OpenGL 子集 | OWE `SceneParsers` |
| P4.2 | 只读 `scene.json` + PNG/JPG 层（先忽略 .tex） | 官方 mpkg 需预转换 tex→png |
| P4.3 | 正交相机 + 多层平移视差 | `ParallaxController` 思路 |
| P4.4 | 粒子 MVP（精灵 billboard） | 不求完整 ParticleSystem |
| P4.5 | **不做** V8 SceneScript 全量；脚本用 Kotlin 配置替代 | |
| P4.6 | 性能预算 | 车机 GPU/温控；默认 30fps、无 HDR |

**退出条件**：若 2 周 POC 无法稳定 1080p30，冻结 P4，专注视频内容运营。

---

### Phase 5 — 明确不做 / 延后

| 项 | 原因 |
|---|---|
| 嵌入官方 `libscenejni` | 法律 + 无法维护 + ABI |
| 完整 PKGM0020 传输协议客户端对接 Steam WE | 无商业授权、绑定 Windows |
| Web 壁纸 CEF | 车机内存与安全面过大 |
| 音频可视化默认开 | 与车机媒体栈冲突；可作隐藏实验开关 |
| x86 so | 官方无 x86 |

---

## 4. 技术设计要点（Phase 1 预览）

### 4.1 统一壁纸条目

```kotlin
data class MotifWallpaper(
  val id: String,
  val title: String,
  val kind: Kind,           // VIDEO, GIF, WE_VIDEO, WE_SCENE_UNSUPPORTED
  val mediaPath: String?,   // 可播路径
  val previewPath: String?,
  val projectJsonPath: String?,
  val source: Source,       // BUILTIN, MOTIF_LIVE, USB, MPKG, HTTP
)
```

### 4.2 mpkg 解析

- 复用 OWE 布局：`headerLen + "PKGM*" + entries + blobs`  
- 解到 `filesDir/we_packs/<hash>/`  
- 读 `project.json` 决策  
- `type=scene` → 标记 unsupported（除非未来 P4）

### 4.3 与现有 Service 关系

```
LiveWallpaperController.apply(id)
  → Prefs 存路径
  → 若已是 Motif 组件：RELOAD
  → 否则 shell setWallpaperComponent
VideoLiveWallpaperService
  → 只消费「可解码的视频 URI」
  → 不加载 so
```

### 4.4 目录约定（建议）

```
/sdcard/motif_live/           # 散装 mp4
/sdcard/motif_live/we/        # 解压的 WE 工程或 mpkg
/data/user/12/.../files/we_packs/
```

---

## 5. 里程碑与排期建议

| 里程碑 | 时间 | 交付 |
|---|---|---|
| M0 文档与沙盒 | 已完成/本周 | 分析报告 + 计划 |
| M1 Video-WE 兼容 | +2 周 | project.json + mpkg video |
| M2 播放列表与保活 harden | +2 周 | 时段列表 + 冷启动清单 |
| M3 内容工具链 | 并行 | 打包脚本 |
| M4 Scene POC（可选） | 另立项 | go/no-go |

---

## 6. 测试矩阵（车机）

| 用例 | 预期 |
|---|---|
| 应用内置 mp4 | 循环播放、crop 正确 |
| 导入 USB mp4 | 列表出现并可应用 |
| 导入 video 型 project 目录 | 标题/预览正确 |
| 导入官方 scene mpkg | 提示不支持，不崩溃 |
| 切换 10 次 | 无黑屏超过 300ms（目标） |
| 重启无 ADB | 壁纸仍为 Motif（若 OEM 未抢） |
| 低存储 | 导入失败有明确错误 |
| user12 隔离 | user0 推送不可见已修复路径仍有效 |

---

## 7. 人力与依赖

| 角色 | Phase 1–2 |
|---|---|
| Android | 主程：包解析 + Service 集成 |
| 内容 | 提供合规 mp4 / 简易 WE video 工程 |
| 测试 | 实车 user12 脚本验收 |

依赖：现有 Motif 工程、ADB 车机、可选 FFmpeg。

---

## 8. 决策记录（建议默认）

1. **默认路线 = 视频优先**（与官方 Android 用户侧最高频、实现成本最低的交集）。  
2. **Scene 不抄 so**；P4 仅自研或基于开源子集。  
3. **mpkg 当归档格式**，不实现完整加密传输协议。  
4. **文档与沙盒留在仓库** `docs/` + `sandbox/we-android/`，APK 可用 `.gitignore` 忽略大文件。  

---

## 9. 下一步行动（可执行）

说 **go Phase 1** 时按序实现：

1. `WeProjectParser` + 单元测试（用沙盒解出的 `project.json`）  
2. `MpkgReader`（PKGM）  
3. `LiveWallpaperScan` 接入  
4. UI：不支持类型文案  
5. 实车装包验收  

说 **go tools** 时：补 `mpkg_extract.py` 与 pack 打包脚本。


---

> **更新**：全特性沙盒目标见 [`WE-Android-全特性对齐计划.md`](./WE-Android-全特性对齐计划.md)（不再以「砍 Scene」为默认）。
