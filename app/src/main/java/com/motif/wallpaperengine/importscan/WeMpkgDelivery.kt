package com.motif.wallpaperengine.importscan

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.core.content.FileProvider
import com.motif.wallpaperengine.BuildConfig
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

/**
 * 将 mpkg 投递给官方 WE BrowseActivity（ACTION_VIEW）。
 *
 * 官方会复制到 files/downloads/ 并加入壁纸库 ViewModel：
 *   BrowseActivity.DOWNLOAD_FOLDER = "downloads/"
 * 这是联动壁纸库的唯一可靠路径（无法直接写 WE 私有目录）。
 */
object WeMpkgDelivery {
    private const val TAG = "WeMpkgDelivery"

    data class Result(
        val ok: Boolean,
        val message: String,
        val staged: File? = null,
    )

    fun deliverCandidate(context: Context, candidate: WePackageScan.Candidate): Result {
        return deliver(context, candidate.file, candidate.contentUri)
    }

    fun deliverToOfficialWe(context: Context, source: File): Result {
        return deliver(context, source, contentUri = null)
    }

    fun deliver(
        context: Context,
        source: File,
        contentUri: Uri?,
        forceClearTask: Boolean = false,
    ): Result {
        return try {
            val staged = stageForProvider(context, source, contentUri)
            val uri = FileProvider.getUriForFile(
                context,
                "${BuildConfig.APPLICATION_ID}.fileprovider",
                staged,
            )
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/octet-stream")
                component = ComponentName(
                    BuildConfig.WE_OFFICIAL_PKG,
                    "${BuildConfig.WE_OFFICIAL_PKG}.BrowseActivity",
                )
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                if (forceClearTask) {
                    // 强制走 BrowseActivity.onCreate 的 VIEW 入库分支（singleTop 时 onNewIntent 不拷文件）
                    addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK)
                } else {
                    addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
                }
            }
            context.grantUriPermission(
                BuildConfig.WE_OFFICIAL_PKG,
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION,
            )
            context.startActivity(intent)
            Log.i(TAG, "VIEW→WE library ${source.name} uri=$uri clearTask=$forceClearTask")
            Result(true, "已投递 WE 壁纸库: ${source.name}", staged)
        } catch (e: Exception) {
            Log.e(TAG, "deliver failed", e)
            Result(false, "投递失败: ${e.message}")
        }
    }

    fun stageForProvider(context: Context, source: File, contentUri: Uri? = null): File {
        val underApp = isUnderAppProviderPaths(context, source)
        if (underApp && source.isFile && source.canRead()) return source

        val dest = File(context.cacheDir, "we_stage_${source.name}")
        if (dest.exists() && dest.length() > 10_000L &&
            source.isFile && dest.length() == source.length() &&
            dest.lastModified() >= source.lastModified()
        ) {
            return dest
        }

        if (source.isFile && source.canRead()) {
            FileInputStream(source).use { input ->
                FileOutputStream(dest).use { output -> input.copyTo(output) }
            }
            dest.setLastModified(source.lastModified())
            return dest
        }

        if (contentUri != null) {
            context.contentResolver.openInputStream(contentUri)?.use { input ->
                FileOutputStream(dest).use { output -> input.copyTo(output) }
            } ?: error("无法打开 contentUri: $contentUri")
            if (dest.length() < 10_000L) error("contentUri 拷贝过小: ${dest.length()}")
            return dest
        }

        error("无法读取文件: ${source.absolutePath}")
    }

    private fun isUnderAppProviderPaths(context: Context, file: File): Boolean {
        val path = runCatching { file.canonicalPath }.getOrElse { file.absolutePath }
        val bases = listOfNotNull(
            context.cacheDir,
            context.filesDir,
            context.externalCacheDir,
            context.getExternalFilesDir(null),
        ).map { base -> runCatching { base.canonicalPath }.getOrElse { base.absolutePath } }
        return bases.any { path.startsWith(it) }
    }

    fun deliverAsset(context: Context, assetPath: String): Result {
        return try {
            val name = assetPath.substringAfterLast('/')
            val out = File(context.cacheDir, name)
            context.assets.open(assetPath).use { input ->
                FileOutputStream(out).use { output -> input.copyTo(output) }
            }
            deliverToOfficialWe(context, out)
        } catch (e: Exception) {
            Result(false, "assets 导入失败: ${e.message}")
        }
    }
}
