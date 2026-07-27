# 官方 WE Android — 车机冷启动验收（约 10 分钟）

> 验证：**重启后** user12 的动态壁纸组件是否仍为  
> `io.wallpaperengine.weclient/.WEWallpaperService`（WMS 自持）。  
> 前置：已在座舱成功 Apply WE 壁纸（见 `docs/官方WE-车机30分钟摸底清单.md` 判定 A）。

---

## 一键命令

```bash
# 完整自动：拍 BEFORE → reboot → 等开机 → 拍 AFTER → 出 RESULT
./scripts/we-android-car-coldboot-check.sh LD249H019625 --reboot

# 不自动重启：只拍 BEFORE，你手动重启后再：
./scripts/we-android-car-coldboot-check.sh LD249H019625
./scripts/we-android-car-coldboot-check.sh LD249H019625 --post-only \
  --audit audit-we-coldboot-时间戳

# 失败后恢复 Motif 视频壁纸
./scripts/we-android-car-coldboot-check.sh LD249H019625 --restore-motif
```

环境变量：

| 变量 | 默认 | 含义 |
|---|---|---|
| `WAIT_BOOT_SEC` | 420 | 等 ADB + boot_completed 最久秒数 |
| `POST_SETTLE_SEC` | 45 | 进系统后额外等待（WMS 起来） |

---

## 判定

| 结果 | 含义 | 量产动作 |
|---|---|---|
| **CB-PASS** | user12 重启后仍是 WE 组件 | 开机重绑作保险即可 |
| **CB-FAIL** | 被 OEM/主题改回或清空 | **必须** 开机脚本重绑 WE（或回 Motif） |

人工可选：桌面是否仍出画、动画、触控（`RESULT.md` 内 V1–V3）。

---

## 报告目录

`audit-we-coldboot-<时间戳>/`

- `wallpaper-before.txt` / `wallpaper-after.txt`
- `screen-before.png` / `screen-after.png`
- `RESULT.md`

---

## 与 Motif 关系

| Motif | WE |
|---|---|
| 已有 shell 自持经验 | 本脚本验证 **官方组件** 是否同样被 WMS 记住 |
| `set-motif-wallpaper-shell.sh` | 失败时用 probe 重绑 WE 或 restore Motif |
