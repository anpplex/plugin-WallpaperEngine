package com.motif.wallpaperengine.plugin

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.ViewGroup
import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * WP-12E experimental: embedded preview Activity.
 *
 * Prefer path — allowlisted extras `sampleKind` + `mpkgSha256` draw a **non-black,
 * non-solid** experimental Canvas pattern (`EXP SCENE` / `EXP VIDEO` + checksum).
 * Does **not** claim official Wallpaper Engine / SceneLib rendering.
 *
 * Optional `mpkgPath` (also allowlisted): when sha is absent, attempt PKGM preview
 * image decode for device harnesses that push an on-device package.
 *
 * Unknown extras fail-closed. Video + experimental pattern schedules a motion
 * phase so dual screencaps differ.
 */
class EmbeddedPreviewActivity : Activity(), SurfaceHolder.Callback {
    private var config: EmbeddedExperimentalPreview.Config? = null
    private var mpkgBitmap: Bitmap? = null
    private var sampleKindLabel: String = "scene"
    private var surfaceView: SurfaceView? = null
    private var phase: Int = 0
    private val handler = Handler(Looper.getMainLooper())
    private var motionScheduled = false

    private val motionRunnable = Runnable {
        val cfg = config ?: return@Runnable
        if (cfg.sampleKind != EmbeddedExperimentalPreview.KIND_VIDEO) return@Runnable
        phase = 1
        redrawSurface()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val extras = intent?.extras
        val keys = extras?.keySet()?.toSet() ?: emptySet()
        val unknown = EmbeddedExperimentalPreview.findUnknownExtras(keys)
        if (unknown.isNotEmpty()) {
            Log.w(TAG, "unknown extras fail-closed: $unknown")
            finish()
            return
        }

        val kindRaw = extras?.getString(EmbeddedExperimentalPreview.EXTRA_SAMPLE_KIND)
        val shaRaw = extras?.getString(EmbeddedExperimentalPreview.EXTRA_MPKG_SHA256)
        val pathRaw = extras?.getString(EXTRA_MPKG_PATH)?.ifBlank { null }
        val framePhase = when {
            extras == null || !extras.containsKey(EmbeddedExperimentalPreview.EXTRA_FRAME_PHASE) -> 0
            else -> extras.getInt(EmbeddedExperimentalPreview.EXTRA_FRAME_PHASE, 0)
        }

        val parsed = EmbeddedExperimentalPreview.parseConfig(kindRaw, shaRaw, framePhase)
        if (parsed != null) {
            config = parsed
            sampleKindLabel = parsed.sampleKind
            phase = parsed.framePhase.coerceIn(0, 1)
        } else if (pathRaw != null && EmbeddedExperimentalPreview.isAllowedSampleKind(kindRaw)) {
            // Optional mpkg path path without sha — still experimental host, not official WE.
            sampleKindLabel = kindRaw!!
            val file = File(pathRaw)
            if (file.isFile && file.canRead()) {
                mpkgBitmap = runCatching { decodePreviewFromMpkg(file) }.getOrNull()
            }
            if (mpkgBitmap == null) {
                Log.w(TAG, "mpkg path present but no preview bitmap; fail-closed")
                finish()
                return
            }
        } else {
            // Fail-closed: need valid sampleKind+mpkgSha256 or sampleKind+readable mpkgPath.
            finish()
            return
        }

        window.setBackgroundDrawableResource(android.R.color.black)
        val sv = SurfaceView(this)
        sv.holder.addCallback(this)
        surfaceView = sv
        setContentView(
            sv,
            ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
    }

    override fun onDestroy() {
        handler.removeCallbacks(motionRunnable)
        surfaceView?.holder?.removeCallback(this)
        mpkgBitmap?.recycle()
        mpkgBitmap = null
        super.onDestroy()
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        redrawSurface()
        scheduleMotionIfNeeded()
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        redrawSurface()
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        handler.removeCallbacks(motionRunnable)
        motionScheduled = false
    }

    private fun scheduleMotionIfNeeded() {
        val cfg = config ?: return
        if (cfg.sampleKind != EmbeddedExperimentalPreview.KIND_VIDEO) return
        if (motionScheduled) return
        if (phase >= 1) return
        motionScheduled = true
        handler.postDelayed(motionRunnable, EmbeddedExperimentalPreview.VIDEO_MOTION_DELAY_MS)
    }

    private fun redrawSurface() {
        val holder = surfaceView?.holder ?: return
        val canvas = holder.lockCanvas() ?: return
        try {
            val cfg = config
            if (cfg != null) {
                EmbeddedExperimentalPreview.drawExperimentalFrame(canvas, cfg, phase)
            } else {
                drawMpkgFallback(canvas)
            }
        } finally {
            holder.unlockCanvasAndPost(canvas)
        }
    }

    private fun drawMpkgFallback(canvas: Canvas) {
        val bmp = mpkgBitmap
        canvas.drawColor(Color.rgb(8, 10, 18))
        if (bmp != null && !bmp.isRecycled) {
            val scale = maxOf(
                canvas.width.toFloat() / bmp.width,
                canvas.height.toFloat() / bmp.height,
            )
            val dw = bmp.width * scale
            val dh = bmp.height * scale
            val left = (canvas.width - dw) / 2f
            val top = (canvas.height - dh) / 2f
            canvas.drawBitmap(
                bmp,
                null,
                android.graphics.RectF(left, top, left + dw, top + dh),
                null,
            )
        }
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 42f
            setShadowLayer(4f, 1f, 1f, Color.BLACK)
        }
        canvas.drawText(
            "embedded · $sampleKindLabel · mpkg (experimental)",
            48f,
            96f,
            paint,
        )
        paint.textSize = 28f
        paint.color = Color.rgb(255, 230, 160)
        canvas.drawText(EmbeddedExperimentalPreview.DISCLAIMER, 48f, 148f, paint)
    }

    companion object {
        private const val TAG = "EmbeddedPreview"

        /** Optional on-device .mpkg path (allowlisted with experimental extras). */
        const val EXTRA_MPKG_PATH = "mpkgPath"

        /**
         * Build a fail-closed Intent for experimental pattern surface.
         * Returns null when kind/sha are invalid (caller must not launch).
         */
        fun buildLaunchIntent(
            context: Context,
            sampleKind: String,
            mpkgSha256: String,
            framePhase: Int = 0,
        ): Intent? {
            val cfg = EmbeddedExperimentalPreview.parseConfig(sampleKind, mpkgSha256, framePhase)
                ?: return null
            return Intent(context, EmbeddedPreviewActivity::class.java).apply {
                putExtra(EmbeddedExperimentalPreview.EXTRA_SAMPLE_KIND, cfg.sampleKind)
                putExtra(EmbeddedExperimentalPreview.EXTRA_MPKG_SHA256, cfg.mpkgSha256)
                putExtra(EmbeddedExperimentalPreview.EXTRA_FRAME_PHASE, cfg.framePhase)
            }
        }

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

            val preferred = listOf("preview.jpg", "preview.png", "preview.jpeg")
            for (name in preferred) {
                val hit = entries.firstOrNull { it.path.equals(name, ignoreCase = true) }
                    ?: entries.firstOrNull { it.path.endsWith("/$name", ignoreCase = true) }
                if (hit != null) {
                    val bytes = blob(hit) ?: continue
                    val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bmp != null) return bmp
                }
            }

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
