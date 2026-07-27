# Wallpaper Engine · 车机版（华为 / 阿维塔）

独立仓库：华为座舱上的 Wallpaper Engine 适配与车机壳 APK。

> 自 Motif monorepo 的 `:WallpaperEngine` 子项目迁出（2026-07-27），后续 **只在本仓** 做 WE 车机开发。  
> Motif 量产视频壁纸与本仓合并时机见 `docs/car/WE子项目-华为车机适配与合并策略.md`。

## 仓库结构

```
WallpaperEngine/                 # git root
├── app/                         # 车机壳 APK (applicationId: com.motif.wallpaperengine)
├── we-official/                 # 官方 APK 补丁流水线（apktool / 签名 / 装车）
├── docs/
│   ├── car/                     # 实车结论与适配文档
│   └── superpowers/             # specs / plans（git workflow）
├── scripts/                     # 安装、探测
└── README.md
```

## Git 工作流（强制）

| 规则 | 说明 |
|---|---|
| 默认分支 | `main` — 仅合并可构建、可说明的基线 |
| 功能分支 | `we-car/<topic>`，例如 `we-car/import-scan` |
| 隔离 | 长任务用 `.worktrees/`（已 gitignore） |
| 提交 | 小步、可回滚；message 用 `feat:` / `fix:` / `docs:` / `chore:` |
| 流程 | **spec → plan → implement → commit**（`docs/superpowers/`） |
| 大文件 | 不提交 `.apk` / `.mpkg` / 完整 apktool `lib/` |

```bash
# 新功能
git checkout main && git pull
git checkout -b we-car/<topic>
# … 开发 …
git add -A && git status
git commit -m "feat: …"
```

## 构建与装车

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
./gradlew :app:assembleDebug

# 华为车机（同 Motif installer 手法）
bash scripts/install-car.sh LD249H019625
```

可选测试包：将 mobile `.mpkg` 放到 `app/src/main/assets/we_packs/`（gitignore，不入库）。

## 产品能力（当前）

| 能力 | 说明 |
|---|---|
| 扫码导入 | HTTP 接收 → 适配目录 |
| 导入文件 | 扫 Download / motif_live/we / U 盘 / we_import（文案保持「导入文件」） |
| 入库联动 | FileProvider VIEW → 官方 WE `files/downloads/` 壁纸库 |
| 官方补丁 | 添加页「扫码导入」+ 跳转本壳（见 `we-official/`） |

## 相关文档

- `docs/car/WE-车机内容导入适配.md`
- `docs/car/WE子项目-华为车机适配与合并策略.md`
- `docs/superpowers/specs/` — 设计规格
