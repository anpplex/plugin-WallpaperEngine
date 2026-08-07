package com.motif.wallpaperengine.plugin

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.TextView
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * WP-12E experimental: embedded mpkg preview Activity.
 *
 * Parses PKGM*.mpkg on-device, extracts [preview.jpg] (or first image), and
 * displays it full-screen. Host is this plugin package — never launches official
 * WE client. Used by live E4 collector for dual non-black frame capture.
 *
 * Intent extras:
 * - [EXTRA_MPKG_PATH] absolute on-device path to .mpkg
 * - [EXTRA_SAMPLE_KIND] "scene" | "video" (label only)
 */
class EmbeddedPreviewActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val kind = intent?.getStringExtra(EXTRA_SAMPLE_KIND)?.ifBlank { null } ?: "scene"
        val mpkgPath = intent?.getStringExtra(EXTRA_MPKG_PATH)?.ifBlank { null }

        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.rgb(8, 10, 18))
        }

        val imageView = ImageView(this).apply {
            scaleType = ImageView.ScaleType.CENTER_CROP
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        }
        root.addView(imageView)

        val label = TextView(this).apply {
            text = "embedded · $kind"
            setTextColor(Color.argb(200, 240, 240, 240))
            textSize = 18f
            setPadding(48, 48, 48, 48)
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.TOP or Gravity.START,
            )
        }
        root.addView(label)

        setContentView(root)

        if (mpkgPath.isNullOrBlank()) {
            label.text = "embedded · $kind · MISSING_MPKG"
            Log.w(TAG, "missing EXTRA_MPKG_PATH")
            return
        }

        val file = File(mpkgPath)
        if (!file.isFile || !file.canRead()) {
            label.text = "embedded · $kind · UNREADABLE"
            Log.w(TAG, "unreadable mpkg: $mpkgPath")
            return
        }

        val bitmap = runCatching { decodePreviewFromMpkg(file) }.getOrElse { err ->
            Log.e(TAG, "mpkg parse failed: $mpkgPath", err)
            null
        }

        if (bitmap == null) {
            label.text = "embedded · $kind · NO_PREVIEW"
            // Fail-closed visual: dark navy with text (still not pure black solid for debugging)
            root.setBackgroundColor(Color.rgb(12, 16, 28))
            return
        }

        imageView.setImageBitmap(bitmap)
        label.text = "embedded · $kind · mpkg"
        Log.i(TAG, "preview ready kind=$kind mpkg=$mpkgPath ${bitmap.width}x${bitmap.height}")
    }

    companion object {
        private const val TAG = "EmbeddedPreview"
        const val EXTRA_MPKG_PATH = "mpkgPath"
        const val EXTRA_SAMPLE_KIND = "sampleKind"

        /**
         * Parse PKGM container and decode preview.jpg / first image entry.
         * Layout matches Motif mpkg_extract / Open Wallpaper Engine PKGParser.
         */
        fun decodePreviewFromMpkg(mpkg: File): Bitmap? {
            val data = FileInputStream(mpkg).use { it.readBytes() }
            if (data.size < 12) return null

            val headerLen = ByteBuffer.wrap(data, 0, 4).order(ByteOrder.LITTLE_ENDIAN).int
            if (headerLen < 4 || headerLen > 64 || 4 + headerLen > data.size) return null
            val header = String(data, 4, headerLen, Charsets.US_ASCII)
            if (!header.startsWith("PKGM") && !header.startsWith("PKGV")) return null

            var pos = 4 + headerLen
            if (pos + 4 > data.size) return null
            val entryCount =
                ByteBuffer.wrap(data, pos, 4).order(ByteOrder.LITTLE_ENDIAN).int
            pos += 4
            if (entryCount <= 0 || entryCount > 100_000) return null

            data class Entry(val path: String, val offset: Int, val length: Int)

            val entries = ArrayList<Entry>(entryCount)
            for (i in 0 until entryCount) {
                if (pos + 4 > data.size) return null
                val pathLen =
                    ByteBuffer.wrap(data, pos, 4).order(ByteOrder.LITTLE_ENDIAN).int
                pos += 4
                if (pathLen <= 0 || pathLen > 10_000 || pos + pathLen + 8 > data.size) return null
                val path = String(data, pos, pathLen, Charsets.UTF_8)
                pos += pathLen
                val offset =
                    ByteBuffer.wrap(data, pos, 4).order(ByteOrder.LITTLE_ENDIAN).int
                val length =
                    ByteBuffer.wrap(data, pos + 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
                pos += 8
                entries.add(Entry(path, offset, length))
            }
            val base = pos

            fun blob(entry: Entry): ByteArray? {
                val start = base + entry.offset
                val end = start + entry.length
                if (start < 0 || end > data.size || entry.length <= 0) return null
                return data.copyOfRange(start, end)
            }

            val preferred = listOf(
                "preview.jpg",
                "preview.png",
                "preview.jpeg",
            )
            for (name in preferred) {
                val hit = entries.firstOrNull { it.path.equals(name, ignoreCase = true) }
                    ?: entries.firstOrNull { it.path.endsWith("/$name", ignoreCase = true) }
                if (hit != null) {
                    val bytes = blob(hit) ?: continue
                    val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bmp != null) return bmp
                }
            }

            // Fallback: first image-like extension
            val imageExt = listOf(".jpg", ".jpeg", ".png", ".webp")
            for (entry in entries) {
                val lower = entry.path.lowercase()
                if (imageExt.any { lower.endsWith(it) }) {
                    val bytes = blob(entry) ?: continue
                    val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bmp != null) return bmp
                }
            }
            return null
        }
    }
}
