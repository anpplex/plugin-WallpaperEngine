# WE 车机版独立仓库 · 设计规格

**日期：** 2026-07-27  
**状态：** Approved (user chose plan A)  
**仓库：** `/Users/anpple/Codex/WallpaperEngine`

## 1. 目标

将华为/阿维塔车机上的 Wallpaper Engine 适配从 Motif monorepo **迁出为独立 git 仓库**，后续所有 WE 车机开发仅在本仓进行，并严格遵循 git workflow。

## 2. 非目标

- 不在本仓继续开发 Motif 视频壁纸量产功能  
- 不提交官方完整 APK / so / 大型 mpkg 样本  
- 不在此阶段合并回 Motif（见合并门禁文档）

## 3. 架构

```
传输层（任意设备） → 适配目录（暂存）
                         ↓
              app 壳：扫码 / 扫描「导入文件」
                         ↓
              ACTION_VIEW → 官方 WE BrowseActivity
                         ↓
              官方库 files/downloads/  （壁纸库联动）
```

| 组件 | 路径 | 职责 |
|---|---|---|
| 车机壳 APK | `app/` | UI、扫库、HTTP 接收、入库投递 |
| 官方补丁 | `we-official/` | 添加页文案与跳转 |
| 文档 | `docs/car/` + `docs/superpowers/` | 实车结论 + spec/plan |

## 4. Git 约定

- `main`：可构建基线  
- 分支：`we-car/<topic>`  
- worktree：`.worktrees/`（gitignore）  
- 流程：spec → plan → implement → commit  
- 忽略：`*.apk`、`*.mpkg`、完整 `apktool-out/`

## 5. 应用标识（当前）

| 项 | 值 |
|---|---|
| applicationId | `com.motif.wallpaperengine` |
| 官方包名 | `io.wallpaperengine.weclient` |
| minSdk | 31 |

（后续可评审是否改名 `com.wallpaperengine.car`，属独立变更。）

## 6. 成功标准

1. `git clone` 后 `./gradlew :app:assembleDebug` 通过  
2. `scripts/install-car.sh` 可装到实车 user12  
3. 新功能走 `we-car/*` 分支，不直接脏写 `main`  
4. 大文件不进 git 历史  

## 7. 迁移来源

- `Motif/WallpaperEngine/**`（源码）  
- `Motif/docs/WE*.md` 等（文档）  
- `Motif/sandbox/we-android` 补丁逻辑（提炼到 `we-official/`）
