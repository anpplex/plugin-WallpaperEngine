package com.motif.wallpaperengine.importscan

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.util.Log
import com.motif.wallpaperengine.BuildConfig
import kotlinx.coroutines.delay

/**
 * 适配目录（扫描源）→ 官方 WE 壁纸库联动。
 *
 * 官方库路径（BrowseActivity.DOWNLOAD_FOLDER）：
 *   we_filesDir/downloads/ 下的 mpkg
 * 只能通过 BrowseActivity ACTION_VIEW 写入（复制 + SceneLib 校验 + ViewModel 入库）。
 * 冷启动时 enumerateWallpapers() 会再扫该目录，故入库后重启仍在库。
 */
object WeLibrarySync {
    private const val TAG = "WeLibrarySync"
    private const val PREF = "we_library_sync"
    private const val KEY_IMPORTED = "imported_keys"

    data class ImportOutcome(
        val ok: Boolean,
        val message: String,
        val fileName: String,
    )

    fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE)

    fun importKey(name: String, bytes: Long): String = "$name|$bytes"

    fun isMarkedImported(context: Context, name: String, bytes: Long): Boolean {
        val set = prefs(context).getStringSet(KEY_IMPORTED, emptySet()) ?: emptySet()
        return importKey(name, bytes) in set
    }

    fun markImported(context: Context, name: String, bytes: Long) {
        val p = prefs(context)
        val set = p.getStringSet(KEY_IMPORTED, emptySet())?.toMutableSet() ?: mutableSetOf()
        set += importKey(name, bytes)
        p.edit().putStringSet(KEY_IMPORTED, set).apply()
    }

    /**
     * 将单个 mpkg 入库官方 WE 壁纸库（BrowseActivity VIEW 复制到 downloads/）。
     * @param openPreview 是否打开预览（单条建议 true；批量时仅最后一条 true）
     */
    fun importOne(
        context: Context,
        candidate: WePackageScan.Candidate,
        openPreview: Boolean = true,
        forceRestartWe: Boolean = false,
    ): ImportOutcome {
        val name = candidate.file.name
        val bytes = candidate.bytes
        return try {
            val staged = WeMpkgDelivery.stageForProvider(
                context,
                candidate.file,
                candidate.contentUri,
            )
            val r = WeMpkgDelivery.deliver(
                context,
                staged,
                contentUri = null,
                forceClearTask = forceRestartWe || !openPreview,
            )
            if (r.ok) {
                markImported(context, name, bytes)
                ImportOutcome(true, "已入库 WE 壁纸库: $name", name)
            } else {
                ImportOutcome(false, r.message, name)
            }
        } catch (e: Exception) {
            Log.e(TAG, "importOne failed $name", e)
            ImportOutcome(false, "入库失败 $name: ${e.message}", name)
        }
    }

    /**
     * 批量入库：逐个强制重启 BrowseActivity 以走 onCreate 导入（singleTop 下 onNewIntent 不会拷文件）。
     */
    suspend fun importAll(
        context: Context,
        candidates: List<WePackageScan.Candidate>,
        onProgress: (Int, Int, String) -> Unit = { _, _, _ -> },
    ): Pair<Int, Int> {
        var ok = 0
        var fail = 0
        candidates.forEachIndexed { index, c ->
            onProgress(index + 1, candidates.size, c.file.name)
            val outcome = importOne(
                context,
                c,
                openPreview = index == candidates.lastIndex,
                forceRestartWe = true,
            )
            if (outcome.ok) ok++ else fail++
            // 给 BrowseActivity 完成复制/校验的时间
            delay(1800)
        }
        return ok to fail
    }

    /** 打开官方 WE 壁纸库（添加页/主浏览） */
    fun openWeLibrary(context: Context) {
        try {
            val intent = Intent().apply {
                component = ComponentName(
                    BuildConfig.WE_OFFICIAL_PKG,
                    "${BuildConfig.WE_OFFICIAL_PKG}.BrowseActivity",
                )
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
                addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
            }
            context.startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "openWeLibrary", e)
        }
    }
}
