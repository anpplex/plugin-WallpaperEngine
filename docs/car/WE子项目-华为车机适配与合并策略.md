# WE 子项目 — 华为车机适配与合并策略

> **已定决策（2026-07-27）**  
> 1. **现阶段**：优先完成 **Wallpaper Engine Android 在华为车机上的适配与优化**  
> 2. **组织关系**：WE 作为 **Motif 仓库内的子项目**，目录固定为 **`WallpaperEngine/`**（独立 application / 独立版本节奏）  
> 3. **合并时机**：WE 车机适配达到门禁后再 **合并进 Motif 量产能力**（非现在把 so 塞进 `app`）

本文与下列文档配合：

- `docs/官方WE-车机30分钟摸底清单.md`（能跑）
- `docs/官方WE-车机冷启动验收.md`（开机自持 **CB-FAIL**）
- `docs/WE-车机内容导入适配.md`（导入无 DocumentsUI）
- `docs/WE-Android-全特性对齐计划.md`（沙盒全特性）
- `sandbox/we-parity/`（官方 so / 抽取物）

---

## 1. 目标分层

| 阶段 | 目标 | 交付形态 |
|---|---|---|
| **Now · WE 子项目** | 华为/阿维塔 user12 上：装得上、播得出、设得上、重启可恢复、资源加得进 | 独立 APK：`we-car`（包名 TBD） |
| **Later · 合并 Motif** | 用户在 Motif 内一站式：选视频引擎 / WE 引擎、统一导入与绑定 | Motif `app` 集成或双引擎切换 |

**不在 Now 做的事**

- 不把 `libscenejni` 默认打进 Motif 量产 `app`
- 不改坏现有 Motif 视频双播放器与 shell 自持（CB 后仍是 Motif）
- 不把官方 PC 配对当用户主路径

---

## 2. 仓库结构（Motif monorepo 子项目）

```
Motif/
├── app/                         # 量产 Motif（视频引擎）— 合并前尽量少动
├── core/ adapter-* / feature-*
├── WallpaperEngine/             # ★ WE 子项目（已建 module）
│   ├── build.gradle.kts
│   ├── README.md
│   └── src/main/…               # 车机壳：导入/绑定/设置/桥接壁纸
├── shared-car-bind/             # （建议后续）shell 绑定 / user12 公共库
├── sandbox/
│   ├── we-android/              # 官方 APK 样本、jadx、mpkg 工具
│   └── we-parity/               # so/assets 抽取、Track S/K
├── scripts/
│   ├── install-wallpaper-engine-car.sh
│   ├── we-android-car-probe.sh
│   ├── we-android-car-coldboot-check.sh
│   ├── set-motif-wallpaper-shell.sh
│   └── set-we-wallpaper-shell.sh   # 待做
└── docs/
```

| 模块 | 职责 |
|---|---|
| **WallpaperEngine** | WE 引擎托管、车机 UI、扫库导入、Apply、开机自持 |
| **shared-car-bind** | （后续）`setWallpaperComponent`、多用户、开机重绑 |
| **app (Motif)** | 现有视频壁纸；合并前可深链打开本子项目 |
| **sandbox/** | 逆向/探针/官方样本，**不进量产依赖** |

Gradle：

```kotlin
include(":WallpaperEngine")
```

**applicationId**

| 阶段 | applicationId |
|---|---|
| 子项目（当前） | `com.motif.wallpaperengine` |
| 合并后 | 双 APK 软合并，或引擎下沉 Motif（评审时定） |

JNI 若直接加载官方 so：Java 类名须满足 `io.wallpaperengine.wrapper.SceneLib`（可与 applicationId 不同）。

---

## 3. WE 子项目适配 backlog（华为车机）

按实车已发现问题排序：

### M1 · 绑定与自持（P0）

| ID | 项 | 验收 |
|---|---|---|
| W1.1 | 华为 installer 安装（同 Motif） | user12 Success |
| W1.2 | shell 绑定 `WEWallpaperService` | dumpsys user12 = WE |
| W1.3 | App 内 Apply 后桌面出画 | 非黑、有动画 |
| W1.4 | **开机重绑 WE**（CB-FAIL 对策） | 冷启动后仍为 WE 或自动恢复 |
| W1.5 | 与 Motif 互斥策略 | 同时只绑一个引擎；文档说明 |

### M2 · 内容导入（P0）— **不依赖官方「导入文件」**

| ID | 项 | 验收 |
|---|---|---|
| W2.1 | 扫描 `motif_live/we` + U 盘 | 无 DocumentsUI |
| W2.2 | 支持 mp4/gif 进视频路径 | 可播可设 |
| W2.3 | 支持 `.mpkg` 入库（Scene） | 内置 9 包 + 自拷 mpkg |
| W2.4 | （可选）HTTP/二维码接收 | 手机可传文件到固定目录 |
| W2.5 | 降级文案 | 隐藏/弱化 PC 配对为主路径 |

### M3 · 体验与性能（P1）

| ID | 项 |
|---|---|
| W3.1 | 横屏 1920 座舱布局/裁剪 |
| W3.2 | FPS/质量档（省电、温控） |
| W3.3 | 触控不抢桌面（已有正向现象，回归） |
| W3.4 | 与桌面 Web 小游戏共存回归 |

### M4 · 引擎完整度（P1/P2，可平行沙盒）

| ID | 项 |
|---|---|
| W4.1 | Track S/K：官方 so + assets（`we-parity`） |
| W4.2 | Scene 属性/视差等按需 |
| W4.3 | 全特性勾选表推进（非合并门禁必选项） |

---

## 4. 「适配完成 → 可合并 Motif」门禁

以下 **全部满足** 才启动合并评审：

| # | 门禁 | 证据 |
|---|---|---|
| G1 | user12 安装 + 启动稳定 | probe 脚本 PASS |
| G2 | 设壁纸出画 + 触控/小游戏不炸 | 实车截图/目视 |
| G3 | **冷启动后 WE 仍在或 ≤30s 自恢复** | coldboot 脚本 **CB-PASS** |
| G4 | 导入不依赖 DocumentsUI（扫库/U 盘至少一条） | 用例录屏 |
| G5 | 与 Motif 可切换、可回退视频引擎 | 切换脚本/设置项 |
| G6 | 包体/崩溃率可接受（内部标准） | 报告 |
| G7 | 文档：安装、导入、开机、FAQ | docs 齐全 |

**合并方式（届时三选一，评审拍板）**

| 方案 | 说明 |
|---|---|
| **A. 双 APK 软合并** | Motif 设置里「使用 WE 引擎」拉起/绑定 we-car 组件 |
| **B. 单 APK 硬合并** | so + 引擎进 Motif，feature 开关 |
| **C. 引擎 SDK 化** | we-car 打成 AAR 被 app 依赖 |

推荐合并第一期用 **A**（风险隔离），稳定后再考虑 B。

---

## 5. 协作与分支节奏

| 项 | 约定 |
|---|---|
| 分支 | `we-car/*` 或 monorepo 内 module 提交；避免长期改 `app` 核心壁纸 |
| 共享绑定 | 尽快抽 `shared-car-bind`，Motif 与 we-car 共用 |
| 样本与逆向 | 仅 `sandbox/`，gitignore 大 APK/so 已部分配置 |
| 版本 | we-car 独立 versionName，如 `0.1.0-car` |
| 评审 | 每完成 M1/M2 做一次实车回归（probe + coldboot + 导入） |

---

## 6. 近期执行顺序（建议）

```
① ✅ WallpaperEngine/ 骨架 + install-wallpaper-engine-car.sh
② set-we-wallpaper-shell.sh + 开机重绑（解决 CB-FAIL）
③ 扫库导入（motif_live/we + U 盘）— 替代官方导入
④ 官方 so 接入（若目标含 Scene；可先视频-only MVP）
⑤ Gate G1–G7 → 合并方案 A 对接 Motif
```

---

## 7. 一句话

**WE 先在 `Motif/WallpaperEngine` 子项目把华为车机适配做完（绑定、开机、导入、出画），达标后再合并进 Motif 产品；现在不合 so、不搅乱量产视频链路。**

---

## 8. 指令

| 说 | 做 |
|---|---|
| **go we scaffold** | ✅ 已完成于 `WallpaperEngine/` |
| **go we bind** | shell 绑定本 module 桥接服务 / 官方 WE + 开机恢复 |
| **go we import** | 扫库/U 盘导入（子项目内） |
| **go we engine** | 接 libscenejni / Track K 骨架 |
