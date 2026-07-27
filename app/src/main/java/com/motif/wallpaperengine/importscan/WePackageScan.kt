package com.motif.wallpaperengine.importscan

import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import java.io.File

/**
 * 车机无 DocumentsUI：扫固定目录 + U 盘 + 华为分享常见落点，发现 .mpkg。
 *
 * 路径分层（A–E）：
 * A 专用库 motif_live/we、motif_live
 * B Download 根 + 华为分享别名子目录（实车分享多落 /sdcard/Download）
 * C App externalFilesDir/we_import
 * D U 盘卷
 * E MediaStore *.mpkg 兜底
 */
object WePackageScan {
    private const val TAG = "WePkgScan"
    private const val MAX_FILES = 200
    private const val MIN_BYTES = 10_000L

    const val FOLDER_MOTIF_LIVE = "motif_live"
    const val FOLDER_WE = "we"
    const val FOLDER_WE_IMPORT = "we_import"

    /** Download 下华为分享 / 接收常见子目录（有则扫、无则跳过） */
    private val SHARE_SUBDIRS = listOf(
        "HuaweiShare",
        "Share",
        "FromShare",
        "InstantShare",
        "received",
        "Bluetooth",
        "蓝牙",
        "Nearby",
        "HiShare",
        "OneHop",
    )

    data class Candidate(
        val file: File,
        val label: String,
        val bytes: Long,
        /** dedicated | download | share | usb | app | media */
        val bucket: String,
        val sourceHint: String,
        /**
         * user12 常无法直接 File 读 emulated/0/Download；
         * 有 contentUri 时投递走 ContentResolver 拷贝。
         */
        val contentUri: Uri? = null,
    )

    fun scanAll(context: Context): List<Candidate> {
        val found = LinkedHashMap<String, Candidate>()

        dedicatedRoots(context).forEach { root ->
            walkMpkg(root, depth = 0, maxDepth = 3, out = found, bucket = "dedicated", hint = "专用库")
        }

        downloadAndShareRoots().forEach { root ->
            val isShareSub = SHARE_SUBDIRS.any { sub ->
                root.name.equals(sub, ignoreCase = true) ||
                    root.path.contains("/$sub", ignoreCase = true)
            }
            val bucket = if (isShareSub) "share" else "download"
            val hint = if (isShareSub) "分享·下载" else "下载"
            // Download 根浅扫；分享子目录稍深
            val maxDepth = if (isShareSub) 2 else 1
            walkMpkg(root, 0, maxDepth, found, bucket, hint)
        }

        // motif_live 在 Download 下再扫一层 we（depth 已由 dedicated 覆盖，这里补遗）
        downloadPrimaryAliases().forEach { dl ->
            walkMpkg(File(dl, "$FOLDER_MOTIF_LIVE/$FOLDER_WE"), 0, 2, found, "dedicated", "专用库")
            walkMpkg(File(dl, FOLDER_MOTIF_LIVE), 0, 2, found, "dedicated", "专用库")
        }

        appRoots(context).forEach { root ->
            walkMpkg(root, 0, 3, found, "app", "App目录")
        }

        usbRoots().forEach { vol ->
            walkMpkg(vol, 0, 1, found, "usb", "U盘")
            listOf(
                FOLDER_MOTIF_LIVE,
                "$FOLDER_MOTIF_LIVE/$FOLDER_WE",
                "Download",
                "Huawei",
                "Documents",
            ).forEach { sub ->
                walkMpkg(File(vol, sub), 0, 2, found, "usb", "U盘")
            }
        }

        mergeMediaStore(context, found)

        val list = found.values.sortedWith(
            compareBy<Candidate> { bucketRank(it.bucket) }
                .thenByDescending { it.file.lastModified() },
        )
        Log.i(
            TAG,
            "scan found=${list.size} " +
                "dedicated=${list.count { it.bucket == "dedicated" }} " +
                "download=${list.count { it.bucket == "download" }} " +
                "share=${list.count { it.bucket == "share" }} " +
                "usb=${list.count { it.bucket == "usb" }} " +
                "app=${list.count { it.bucket == "app" }} " +
                "media=${list.count { it.bucket == "media" }}",
        )
        return list
    }

    /** 创建推荐投放目录（不抛错） */
    fun ensureRecommendedDirs(context: Context) {
        runCatching {
            File("/sdcard/Download/$FOLDER_MOTIF_LIVE/$FOLDER_WE").mkdirs()
            File("/storage/emulated/0/Download/$FOLDER_MOTIF_LIVE/$FOLDER_WE").mkdirs()
            context.getExternalFilesDir(null)?.let { File(it, FOLDER_WE_IMPORT).mkdirs() }
        }
    }

    fun rootsSummary(context: Context): String {
        val roots = buildList {
            addAll(dedicatedRoots(context).map { it.absolutePath })
            addAll(downloadPrimaryAliases().map { it.absolutePath })
            addAll(appRoots(context).map { it.absolutePath })
            addAll(usbRoots().map { "USB:${it.name}" })
        }
        return roots.distinct().take(12).joinToString("\n")
    }

    // region roots

    private fun dedicatedRoots(context: Context): List<File> {
        val list = linkedSetOf<File>()
        fun add(f: File?) {
            if (f != null) list += f
        }
        downloadPrimaryAliases().forEach { dl ->
            add(File(dl, "$FOLDER_MOTIF_LIVE/$FOLDER_WE"))
            add(File(dl, FOLDER_MOTIF_LIVE))
        }
        add(File("/sdcard/$FOLDER_MOTIF_LIVE/$FOLDER_WE"))
        add(File("/sdcard/$FOLDER_MOTIF_LIVE"))
        context.getExternalFilesDir(null)?.let {
            add(File(it, FOLDER_WE_IMPORT))
            add(File(it, "$FOLDER_MOTIF_LIVE/$FOLDER_WE"))
            add(File(it, FOLDER_MOTIF_LIVE))
        }
        usbRoots().forEach { vol ->
            add(File(vol, "$FOLDER_MOTIF_LIVE/$FOLDER_WE"))
            add(File(vol, FOLDER_MOTIF_LIVE))
        }
        return list.toList()
    }

    private fun downloadAndShareRoots(): List<File> {
        val list = linkedSetOf<File>()
        downloadPrimaryAliases().forEach { dl ->
            list += dl
            SHARE_SUBDIRS.forEach { sub -> list += File(dl, sub) }
        }
        return list.toList()
    }

    private fun downloadPrimaryAliases(): List<File> {
        val list = linkedSetOf<File>()
        fun add(f: File?) {
            if (f != null) list += f
        }
        add(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS))
        add(File("/sdcard/Download"))
        add(File("/storage/emulated/0/Download"))
        add(File("/storage/self/primary/Download"))
        add(File("/storage/emulated/12/Download"))
        add(File("/mnt/user/12/emulated/0/Download"))
        add(File("/mnt/pass_through/0/emulated/0/Download"))
        return list.toList()
    }

    private fun appRoots(context: Context): List<File> {
        val out = mutableListOf<File>()
        context.getExternalFilesDir(null)?.let {
            out += it
            out += File(it, FOLDER_WE_IMPORT)
            out += File(it, "Download")
        }
        context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)?.let { out += it }
        context.externalCacheDir?.let { out += it }
        context.cacheDir?.let { out += it }
        return out
    }

    private fun usbRoots(): List<File> {
        val out = mutableListOf<File>()
        val storage = File("/storage")
        storage.listFiles()?.forEach { vol ->
            if (!vol.isDirectory) return@forEach
            val n = vol.name
            if (n in setOf("emulated", "self", "sdcard0", ".")) return@forEach
            out += vol
        }
        listOf(
            File("/mnt/media_rw"),
            File("/mnt/usb"),
            File("/mnt/udisk"),
        ).forEach { base ->
            if (base.isDirectory) {
                base.listFiles()?.filter { it.isDirectory }?.forEach { out += it }
            }
        }
        return out.distinctBy { f ->
            runCatching { f.canonicalPath }.getOrDefault(f.absolutePath)
        }
    }

    // endregion

    private fun bucketRank(bucket: String): Int = when (bucket) {
        "dedicated" -> 0
        "app" -> 1
        "share" -> 2
        "download" -> 3
        "usb" -> 4
        "media" -> 5
        else -> 9
    }

    private fun walkMpkg(
        dir: File,
        depth: Int,
        maxDepth: Int,
        out: LinkedHashMap<String, Candidate>,
        bucket: String,
        hint: String,
    ) {
        if (depth > maxDepth || out.size >= MAX_FILES) return
        if (!dir.exists()) return
        if (dir.isFile) {
            if (isMpkg(dir)) put(out, dir, bucket, hint)
            return
        }
        if (!dir.isDirectory) return
        val children = dir.listFiles() ?: return
        for (f in children) {
            if (out.size >= MAX_FILES) return
            if (f.isDirectory) {
                if (f.name.startsWith(".")) continue
                if (f.name in SKIP_DIRS) continue
                walkMpkg(f, depth + 1, maxDepth, out, bucket, hint)
            } else if (isMpkg(f)) {
                put(out, f, bucket, hint)
            }
        }
    }

    private val SKIP_DIRS = setOf(
        "Android", "obb", "data", "LOST.DIR",
        "System Volume Information", "theme", "Alarms",
        "Notifications", "Ringtones", "Podcasts",
    )

    private fun isMpkg(f: File): Boolean {
        if (!f.isFile || f.length() < MIN_BYTES) return false
        val n = f.name.lowercase()
        return n.endsWith(".mpkg") || n.endsWith(".bin")
    }

    private fun put(
        out: LinkedHashMap<String, Candidate>,
        f: File,
        bucket: String,
        hint: String,
        bytes: Long = f.length(),
        contentUri: Uri? = null,
    ) {
        val key = runCatching { f.canonicalPath }.getOrElse { f.absolutePath }
        val existing = out[key]
        if (existing != null) {
            // 补 contentUri / 更大 size
            if (existing.contentUri == null && contentUri != null) {
                out[key] = existing.copy(
                    contentUri = contentUri,
                    bytes = maxOf(existing.bytes, bytes),
                    label = "${f.name}  (${formatMb(maxOf(existing.bytes, bytes))} · $hint)",
                    bucket = preferBucket(existing.bucket, bucket),
                    sourceHint = if (bucketRank(bucket) < bucketRank(existing.bucket)) hint else existing.sourceHint,
                )
            }
            return
        }
        out[key] = Candidate(
            file = f,
            label = "${f.name}  (${formatMb(bytes)} · $hint)",
            bytes = bytes,
            bucket = bucket,
            sourceHint = hint,
            contentUri = contentUri,
        )
    }

    private fun preferBucket(a: String, b: String): String =
        if (bucketRank(b) < bucketRank(a)) b else a

    private fun mergeMediaStore(context: Context, out: LinkedHashMap<String, Candidate>) {
        runCatching {
            val collection = MediaStore.Files.getContentUri("external")
            val proj = arrayOf(
                MediaStore.Files.FileColumns._ID,
                MediaStore.MediaColumns.DATA,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.SIZE,
            )
            // 仅 .mpkg：.bin 会误匹配高德等系统语言包
            val selection =
                "${MediaStore.MediaColumns.DISPLAY_NAME} LIKE ? OR " +
                    "${MediaStore.MediaColumns.DATA} LIKE ?"
            val args = arrayOf("%.mpkg", "%.mpkg")
            context.contentResolver.query(
                collection,
                proj,
                selection,
                args,
                "${MediaStore.MediaColumns.DATE_MODIFIED} DESC",
            )?.use { c ->
                val iId = c.getColumnIndex(MediaStore.Files.FileColumns._ID)
                val iData = c.getColumnIndex(MediaStore.MediaColumns.DATA)
                val iName = c.getColumnIndex(MediaStore.MediaColumns.DISPLAY_NAME)
                val iSize = c.getColumnIndex(MediaStore.MediaColumns.SIZE)
                if (iData < 0) return@use
                while (c.moveToNext() && out.size < MAX_FILES) {
                    val path = c.getString(iData) ?: continue
                    val lower = path.lowercase()
                    if (!lower.endsWith(".mpkg") && !lower.endsWith(".bin")) continue
                    val f = File(path)
                    val sizeFromStore = if (iSize >= 0) c.getLong(iSize) else 0L
                    val sizeFromFile = runCatching { if (f.isFile) f.length() else 0L }.getOrDefault(0L)
                    val bytes = maxOf(sizeFromStore, sizeFromFile)
                    // user12 可能无法 File 直读 Download，仍凭 MediaStore 入库
                    if (bytes < MIN_BYTES && !f.isFile) continue
                    if (bytes < MIN_BYTES) continue
                    val name = if (iName >= 0) c.getString(iName) ?: f.name else f.name
                    val contentUri = if (iId >= 0) {
                        Uri.withAppendedPath(collection, c.getLong(iId).toString())
                    } else {
                        null
                    }
                    val lowerPath = path.lowercase()
                    val hint = when {
                        path.contains(FOLDER_MOTIF_LIVE) -> "专用库"
                        SHARE_SUBDIRS.any { path.contains(it, ignoreCase = true) } -> "分享·下载"
                        lowerPath.contains("/download") -> "下载·分享"
                        else -> "媒体库"
                    }
                    val bucket = when {
                        path.contains(FOLDER_MOTIF_LIVE) -> "dedicated"
                        SHARE_SUBDIRS.any { path.contains(it, ignoreCase = true) } -> "share"
                        lowerPath.contains("/download") -> "download"
                        else -> "media"
                    }
                    // 用 path 作 key；name 可能与 path  basename 不同
                    val displayFile = if (f.name.isNotEmpty()) f else File(path)
                    put(
                        out,
                        displayFile,
                        bucket,
                        hint,
                        bytes = if (bytes > 0) bytes else MIN_BYTES,
                        contentUri = contentUri,
                    )
                    Log.i(TAG, "MediaStore hit name=$name path=$path bytes=$bytes uri=$contentUri")
                }
            }
        }.onFailure {
            Log.w(TAG, "MediaStore: ${it.message}")
        }
    }

    private fun formatMb(bytes: Long): String {
        val mb = bytes / (1024.0 * 1024.0)
        return String.format("%.1fMB", mb)
    }
}
