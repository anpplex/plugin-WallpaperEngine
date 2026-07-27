# WE / 动态壁纸 — 华为车机内容导入适配

> 实车：ICHU3200E15-ADV · user12  
> 现象：官方 WE「与计算机配对」仅适合 PC；「导入文件」点了无反应。  
> 截图：`audit-we-import-ui-*/`（添加页：配对 + 导入文件）

---

## 1. 为什么官方两条路在车机上难受

| 官方入口 | 设计假设 | 车机现实 |
|---|---|---|
| **与计算机配对** | 同 Wi‑Fi + Windows WE + 组播 7884/TCP 7889 | 车机网络常隔离；人在车里未必开 PC；体验「研发向」 |
| **导入文件** | 系统文件选择器（SAF / DocumentsUI） | **阿维塔/华为 HU 常无 DocumentsUI 或不可用** → Intent 发出后 **无 Activity** → 表现为「点了没反应」（与 Motif 早期导入闪退同源） |

结论：**不是资源格式 alone 的问题，是「选文件」与「PC 管道」两条官方路径都不适配座舱。**  
官方 App 闭源，难以在其内修 SAF；**应用层应自建导入管道**，再喂给 WE（mpkg/视频）或 Motif 引擎。

---

## 2. 推荐优先级（华为车机）

### P0 — 目录扫描（强烈推荐，Motif 已验证；WE 壳已实现）

**做法**：固定落盘目录，App **不弹系统选择器**，只扫路径并入库。  
**实现**：`WallpaperEngine` → `WePackageScan` + UI「扫描并刷新」→ 点选 → `WeMpkgDelivery` FileProvider 投官方 WE。

| 路径示例 | 用途 |
|---|---|
| `/sdcard/Download/` **根目录浅扫 `*.mpkg`** | **华为分享 / 任意端默认落点**（实车已见 mpkg 落此） |
| `/sdcard/Download/{HuaweiShare,Share,FromShare,InstantShare,蓝牙,Bluetooth,Nearby,…}/` | 分享别名子目录（有则扫） |
| `/sdcard/Download/motif_live/we/` | 专用 `.mpkg` 库（推荐投放） |
| `/sdcard/Download/motif_live/` | 与 Motif 视频库并列 |
| `…/Android/data/com.motif.wallpaperengine/files/we_import/` | 研发 adb push |
| U 盘 `/storage/<UUID>/` 根 + Download + motif_live | 插优盘即导入 |
| MediaStore `*.mpkg` | user12 文件系统拒读时的兜底 |

**优点**：无 DocumentsUI、无 PC、可一键刷新、user12 可写路径可控。  
**对接**：

- **Motif**：已有 motif_live / U 盘 / 一键扫描 → **继续作为量产默认**。  
- **WE**：用 `adb push` / 文件管理器拷到可访问目录后，若官方仍打不开选择器 → 需 **WE-Car/Motif 侧** 扫 mpkg 再 `file://` 或解压喂引擎；或 shell 把文件丢进 WE 的 files 目录（需反编译路径，脆弱）。

**产品文案**：不要写「导入文件」，写 **「扫描优盘 / 扫描本地壁纸库」**。

---

### P1 — 手机 → 车：华为生态分享 / 超级终端（可用作「投递」）

| 方式 | 角色 | 注意 |
|---|---|---|
| **华为分享 / 超级终端文件互传** | 把 mp4/mpkg 丢到车机「下载/文件管理」 | 只解决 **传输**；若仍用官方「导入文件」选文件，**仍会挂** |
| 手机图库/文件 → 车机共享目录 | 同上 | 必须再接 **P0 扫描** 或 自研导入页 |

**适配要点**：分享落盘目录固定后，Motif/WE-Car **自动 watch 该目录**（Downloads、华为分享默认路径需实车 `logcat`/文件管理确认）。

**多用户（阿维塔）**：HMI 为 **user12**。`adb push /sdcard/Download` 常落 **emulated/0（机主）**，user12 的 MediaStore **扫不到** 该文件。  
- 用户路径：华为分享到前台用户 → 当前用户 `Download`（扫库可命中）  
- 研发路径：`…/Android/data/com.motif.wallpaperengine/files/we_import/` 或 `--user 12` 可见目录

---

### P1 — LocalSend / 局域网 HTTP（推荐作「无 U 盘时」）

| 方式 | 适合 | 车机注意 |
|---|---|---|
| **LocalSend** | 手机/电脑同网一键传文件 | 车机要能装 LocalSend 或自研接收端；接收目录接 P0 扫描 |
| **Motif 内嵌 HTTP 上传**（你们已有 adb reverse + IMPORT 经验） | 开发机/手机浏览器上传 | 量产可改为车机开热点或连家里 Wi‑Fi 后访问 `http://车机IP:port` |
| **二维码 + 临时 HTTP** | 乘客手机扫码上传 | UX 好；注意 user12 网络与防火墙 |

**不要**指望 LocalSend 直接「设壁纸」——只作传输层。

---

### P2 — U 盘 / 便携 SSD

车机最稳的 **离线大宗传输**。  
流程：电脑导出 `.mpkg` 或 mp4 → 拷 U 盘 → 上车 → **一键扫描 U 盘**。  
比 PC 无线配对可靠得多。

---

### P3 — 电脑侧仍保留，但不作为主路径

| 方式 | 何时用 |
|---|---|
| WE PC → Export `.mpkg` → U 盘/LocalSend | 要从 Workshop 拿 **Scene 包** 时 |
| WE 无线配对 | 仅工位调试，不写进用户手册主路径 |
| adb push | 研发；可包成「Mac 一键导入」脚本 |

---

### 不推荐作主路径

| 方式 | 原因 |
|---|---|
| 官方「导入文件」 | 无 DocumentsUI → 无反应 |
| 仅官方 PC 配对 | 车机网络/场景不友好 |
| 依赖 Play 商店/云同步 | 车机常无 GMS |

---

## 3. 推荐产品形态（Motif 或独立 WE-Car）

```
┌──────────── 传输层（任选）────────────┐
│  U盘 │ 华为分享 │ LocalSend │ 扫码HTTP │ push │
└─────────────────┬───────────────────┘
                  ▼
         适配目录（暂存）
         Download/ · motif_live/we/ · we_import/
                  ▼
         扫描「导入文件」
                  ▼
         ACTION_VIEW → 官方 BrowseActivity
                  ▼
         ★ 真正壁纸库：WE files/downloads/*.mpkg
            （SceneLib.enumerateWallpapers 冷启动再扫）
                  ▼
         壁纸页可见 · 预览 · shell 绑定
```

**入库联动要点**

| 层 | 路径 | 角色 |
|---|---|---|
| 适配/暂存 | `/sdcard/Download/`、`motif_live/we/`、`we_import/` | 任意端投放、扫描源 |
| **WE 壁纸库** | `io.wallpaperengine.weclient` 私有 `files/downloads/` | 官方库；必须经 VIEW 导入 |
| 本地标记 | Motif SharedPreferences | UI 显示「已标记入库」 |

实现：`WeLibrarySync` + `WeMpkgDelivery`（`WallpaperEngine` 模块）。

**UI 建议（车机）**

1. **扫描本地库**（默认）  
2. **扫描 U 盘**  
3. **打开接收**（LocalSend 或内置 HTTP，显示 IP/二维码）  
4. （高级）PC 配对 — 折叠进二级菜单  

彻底隐藏或降级官方「导入文件」心智，避免用户点了没反应。

---

## 4. 针对「Windows 版 WE 资源」的友好流水线

Workshop / PC 库上桌的务实路径：

```
Windows WE
  → 右键 Send to Mobile → Export .mpkg
  → 拷到 U盘 或 LocalSend 到车
  → 车机「扫描 U盘/本地」入库
  → 应用（WE 引擎或仅 video 预渲染）
```

或研发脚本：

```bash
# 例：从电脑推到 user12 可扫目录（路径按实车调整）
adb -s SER push ./pack.mpkg /storage/emulated/12/motif_live/we/
# 然后 Motif/WE-Car 扫描刷新
```

**不要**让普通用户走「车机连家里电脑配对」。

---

## 5. 华为分享 vs LocalSend 怎么选

| | 华为分享/超级终端 | LocalSend | 自研 HTTP |
|---|---|---|---|
| 装 App | 系统常自带 | 车+手机都要装 | 仅车（Motif 内） |
| 同账号/生态 | 强依赖华为手机 | 跨平台 | 任意浏览器 |
| 车机可用性 | **需实车测** 落盘路径与 user12 | **需实车测** 安装与网络 | 你们已有经验 |
| 和壁纸关系 | 只传文件 | 只传文件 | 可直接写 motif_live |

**建议**：P0 目录扫描必做；传输层 **U 盘 + 自研 HTTP/二维码** 最可控；华为分享、LocalSend 作 **增强**，实车确认落盘路径后再接自动扫描。

---

## 6. 和当前实车状态

- 主屏/添加页截图见 `audit-we-import-ui-*`  
- 冷启动后组件回到 Motif（CB-FAIL）→ 导入方案应优先服务 **Motif 量产导入**；WE 作可选引擎时共用同一扫描目录  
- 官方 WE「导入文件」无反应：**预期行为**，不必再在官方 App 内死磕  

---

## 7. 下一步实现（若 go）

1. Motif：**强化** U 盘 + motif_live + 可选「接收 HTTP/二维码」页（不依赖 DocumentsUI）  
2. 实车探测：华为分享默认目录、LocalSend 能否装 user12  
3. 文档用户话术：三条路 — U 盘 / 手机传文件到固定目录 / 开发脚本  

说 **go import** 可按 P0+P1 在 Motif 落地「扫库 + 接收」而不碰官方 WE 闭源导入。
