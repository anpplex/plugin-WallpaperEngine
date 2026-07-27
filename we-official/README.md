# 官方 Wallpaper Engine Android · 车机补丁

沙盒环境可改官方 APK。本目录存放**补丁说明与参考 smali**，不提交完整反编译树与签名 APK。

## 目标改动（已实现参考）

| 位置 | 改动 |
|---|---|
| `btn_import_file_pc` | 文案 →「扫码导入」 |
| `hint_import_file_pc` | 扫码上传说明 |
| `btn_import_file_local` | **文案不变**「导入文件」 |
| `ImportFileFragment` | 两按钮跳转 `com.motif.wallpaperengine/.MainActivity`（`we_mode=qr` / `scan`） |
| `Util.callApplyWallpaper` | CHANGE_LIVE_WALLPAPER 失败 → Toast 已应用（**不弹错误**），prefs 已写 |
| `queries` | 声明 Motif 壳包名 |
| `extractNativeLibs` | 补丁重打包时 `true`（apktool 对齐） |

参考 smali：`reference/ImportFileFragment.smali`、`reference/Util_Companion.smali`

## 本地重建

```bash
# 1. 解包官方 APK（自备，勿提交）
apktool d -o we-official/apktool-out wallpaper-engine.apk

# 2. 应用 reference/ 中的 smali 与文档中的 strings 改动

# 3. 打包签名
apktool b -o we-car-unsigned.apk apktool-out
zipalign -f -p 4 we-car-unsigned.apk we-car-aligned.apk
apksigner sign --ks ~/.android/debug.keystore \
  --ks-pass pass:android --key-pass pass:android \
  --out we-car-patched.apk we-car-aligned.apk

# 4. 装车（需先卸载原签名包）
# 使用与 scripts/install-car.sh 相同的华为 installer 手法
```

参考 smali：`reference/ImportFileFragment.smali`  
详细产品说明：`docs/car/WE-车机内容导入适配.md`
