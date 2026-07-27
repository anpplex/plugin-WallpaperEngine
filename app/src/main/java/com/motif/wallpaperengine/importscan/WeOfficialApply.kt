package com.motif.wallpaperengine.importscan

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log
import com.motif.wallpaperengine.BuildConfig

/**
 * 官方 WE「勾选应用」链路的 Motif 侧配套说明与辅助入口。
 *
 * 官方实现（反编译）：
 * 1. SharedPreferences (PreferenceManager 默认):
 *      key = "selectedWallpaper"
 *      value = 相对路径，如 "downloads/xxx.mpkg"
 * 2. 若 WEWallpaperService 已激活 → requestWallpaperReload()
 * 3. 否则 → Intent CHANGE_LIVE_WALLPAPER（车机常失败）
 *
 * 车机可靠做法 = 写 prefs + shell setWallpaperComponent（见 scripts/we-apply-shell.sh）。
 * App 内无法写官方私有 prefs（不同 UID），只能：
 * - 投递入库（[WeMpkgDelivery]）
 * - 记录期望路径（本类 Motif prefs）
 * - 提示/触发 shell 脚本绑定
 */
object WeOfficialApply {
    private const val TAG = "WeOfficialApply"
    private const val PREF = "we_official_apply"
    const val KEY_PENDING_REL_PATH = "pending_selected_wallpaper"
    const val KEY_PENDING_FILE_NAME = "pending_file_name"

    /** 官方 prefs key，与 Util.PREF_KEY_SELECTED_WALLPAPER 一致 */
    const val WE_PREF_KEY_SELECTED = "selectedWallpaper"

    /** 官方入库相对目录，与 BrowseActivity.DOWNLOAD_FOLDER 一致 */
    const val WE_DOWNLOAD_REL = "downloads/"

    const val WE_SERVICE =
        "io.wallpaperengine.weclient.WEWallpaperService"

    fun officialRelPath(fileName: String): String =
        WE_DOWNLOAD_REL + fileName.removePrefix("/")

    fun rememberPending(context: Context, fileName: String) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit()
            .putString(KEY_PENDING_FILE_NAME, fileName)
            .putString(KEY_PENDING_REL_PATH, officialRelPath(fileName))
            .apply()
        Log.i(TAG, "pending selectedWallpaper=${officialRelPath(fileName)}")
    }

    fun pendingRelPath(context: Context): String? =
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
            .getString(KEY_PENDING_REL_PATH, null)

    /**
     * 入库后调用：记录 pending，并可选打开官方库。
     * 真正主屏生效需 scripts/we-apply-shell.sh（写官方 prefs + SetWpUser）。
     */
    fun afterImport(
        context: Context,
        fileName: String,
        openLibrary: Boolean = false,
    ) {
        rememberPending(context, fileName)
        if (openLibrary) {
            WeLibrarySync.openWeLibrary(context)
        }
    }

    /**
     * 尝试拉起系统 CHANGE_LIVE_WALLPAPER（手机可用；华为车机多半失败，与官方 ✓ 相同）。
     */
    fun trySystemChangeLiveWallpaper(context: Context): Boolean {
        return try {
            val intent = Intent("android.service.wallpaper.CHANGE_LIVE_WALLPAPER").apply {
                putExtra(
                    "android.service.wallpaper.extra.LIVE_WALLPAPER_COMPONENT",
                    ComponentName(BuildConfig.WE_OFFICIAL_PKG, WE_SERVICE),
                )
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            true
        } catch (e: Exception) {
            Log.w(TAG, "CHANGE_LIVE_WALLPAPER failed (expected on car)", e)
            false
        }
    }

    fun applyShellHint(fileName: String): String {
        val rel = officialRelPath(fileName)
        return """
            # 车机 shell 应用（root/shell 写官方 prefs + 绑定）
            # selectedWallpaper=$rel
            bash scripts/we-apply-shell.sh <serial> $rel
        """.trimIndent()
    }
}
