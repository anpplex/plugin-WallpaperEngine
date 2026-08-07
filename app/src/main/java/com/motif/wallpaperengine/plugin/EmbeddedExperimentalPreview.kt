package com.motif.wallpaperengine.plugin

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader

/**
 * Pure WP-12E experimental preview math (JVM unit-testable).
 *
 * Honest experimental surface only — never asserts official SceneLib / WE frames.
 * Color stats thresholds align with [scripts/analyze-frame-nonblack.py].
 */
object EmbeddedExperimentalPreview {
    const val EXTRA_SAMPLE_KIND = "sampleKind"
    const val EXTRA_MPKG_SHA256 = "mpkgSha256"
    const val EXTRA_FRAME_PHASE = "framePhase"

    const val KIND_SCENE = "scene"
    const val KIND_VIDEO = "video"

    /** Align with analyze-frame-nonblack.py BLACK_MEAN_THRESHOLD. */
    const val BLACK_MEAN_THRESHOLD = 2.0

    /** Align with analyze-frame-nonblack.py SOLID_VARIANCE_THRESHOLD. */
    const val SOLID_VARIANCE_THRESHOLD = 1.0

    /** Dual-frame gap ≥ 3s for video motion phase (matches analyzer MIN_INTERVAL). */
    const val VIDEO_MOTION_DELAY_MS = 3_500L

    const val DISCLAIMER = "experimental embedded preview — not official SceneLib"

    /** Optional on-device path used by device harness when sha-driven pattern is not used. */
    const val EXTRA_MPKG_PATH = "mpkgPath"

    val ALLOWED_INTENT_EXTRAS: Set<String> = setOf(
        EXTRA_SAMPLE_KIND,
        EXTRA_MPKG_SHA256,
        EXTRA_FRAME_PHASE,
        EXTRA_MPKG_PATH,
    )

    private val SHA256_HEX = Regex("^[0-9a-f]{64}$")

    data class Config(
        val sampleKind: String,
        val mpkgSha256: String,
        val framePhase: Int,
    ) {
        val seed: Int get() = seedFor(sampleKind, mpkgSha256, framePhase)
        val kindLabel: String get() = kindLabelOf(sampleKind)
        val checksumDigits: String get() = mpkgSha256.take(8)
    }

    data class Rgb(val r: Int, val g: Int, val b: Int) {
        fun toArgb(): Int = Color.rgb(r.coerceIn(0, 255), g.coerceIn(0, 255), b.coerceIn(0, 255))
    }

    data class ColorStats(
        val meanLuminance: Double,
        val variance: Double,
        val pixelCount: Int,
    ) {
        val black: Boolean get() = meanLuminance < BLACK_MEAN_THRESHOLD
        val solid: Boolean get() = variance < SOLID_VARIANCE_THRESHOLD
        val nonBlackNonSolid: Boolean get() = !black && !solid
    }

    fun findUnknownExtras(keys: Set<String>): Set<String> =
        keys.filterNot { it in ALLOWED_INTENT_EXTRAS }.toSet()

    fun isAllowedSampleKind(kind: String?): Boolean =
        kind == KIND_SCENE || kind == KIND_VIDEO

    fun isValidMpkgSha256(value: String?): Boolean =
        value != null && SHA256_HEX.matches(value)

    fun kindLabelOf(sampleKind: String): String = when (sampleKind) {
        KIND_SCENE -> "EXP SCENE"
        KIND_VIDEO -> "EXP VIDEO"
        else -> "EXP UNKNOWN"
    }

    /**
     * Distinct seeds for scene vs video (and phase). Same mpkg sha always yields
     * different scene/video seeds.
     */
    fun seedFor(sampleKind: String, mpkgSha256: String, framePhase: Int = 0): Int {
        val material = "wp12e|$sampleKind|$mpkgSha256|p$framePhase"
        var h = 0x811C9DC5.toInt() // FNV-1a offset basis
        for (ch in material) {
            h = h xor ch.code
            h *= 0x01000193
        }
        // Mix kind discriminant so scene/video never collide even if hash collapses.
        val kindTag = when (sampleKind) {
            KIND_SCENE -> 0x53434E45 // 'SCNE'
            KIND_VIDEO -> 0x56494445 // 'VIDE'
            else -> 0x554E4B4E
        }
        return h xor kindTag xor (framePhase * 0x9E3779B9.toInt())
    }

    fun parseConfig(
        sampleKind: String?,
        mpkgSha256: String?,
        framePhase: Int = 0,
    ): Config? {
        if (!isAllowedSampleKind(sampleKind)) return null
        val sha = mpkgSha256?.trim()?.lowercase() ?: return null
        if (!isValidMpkgSha256(sha)) return null
        val phase = framePhase.coerceIn(0, 1)
        return Config(sampleKind!!, sha, phase)
    }

    /** Primary gradient endpoint — channel floors keep mean luminance well above black. */
    fun primaryRgb(seed: Int): Rgb {
        val r = 48 + ((seed ushr 16) and 0x7F) // 48..175
        val g = 64 + ((seed ushr 8) and 0x6F) // 64..175
        val b = 80 + (seed and 0x5F) // 80..175
        return Rgb(r, g, b)
    }

    /** Secondary endpoint, deliberately distant in color space for high variance. */
    fun secondaryRgb(seed: Int): Rgb {
        val r = 180 + ((seed ushr 10) and 0x3F) // 180..243
        val g = 40 + ((seed ushr 4) and 0x5F) // 40..135
        val b = 120 + ((seed * 17) and 0x6F) // 120..231
        return Rgb(r, g, b)
    }

    /** Rec. 601 luminance (matches analyze-frame-nonblack.py). */
    fun luminance(r: Int, g: Int, b: Int): Double =
        0.299 * r + 0.587 * g + 0.114 * b

    /**
     * Welford online mean/variance over synthetic gradient samples.
     * Pure; no Android bitmap required.
     */
    fun sampleGradientStats(
        seed: Int,
        width: Int = 64,
        height: Int = 64,
    ): ColorStats {
        require(width > 0 && height > 0)
        val c0 = primaryRgb(seed)
        val c1 = secondaryRgb(seed)
        var n = 0
        var mean = 0.0
        var m2 = 0.0
        for (y in 0 until height) {
            val ty = y.toDouble() / (height - 1).coerceAtLeast(1)
            for (x in 0 until width) {
                val tx = x.toDouble() / (width - 1).coerceAtLeast(1)
                val t = (tx + ty) * 0.5
                val r = lerp(c0.r, c1.r, t)
                val g = lerp(c0.g, c1.g, t)
                val b = lerp(c0.b, c1.b, t)
                // Checker accent every 8px boosts variance (non-solid).
                val accent = if (((x / 8) + (y / 8)) % 2 == 0) 18 else -12
                val yLuma = luminance(
                    (r + accent).coerceIn(0, 255),
                    (g + accent).coerceIn(0, 255),
                    (b + accent).coerceIn(0, 255),
                )
                n += 1
                val delta = yLuma - mean
                mean += delta / n
                m2 += delta * (yLuma - mean)
            }
        }
        val variance = if (n > 0) m2 / n else 0.0
        return ColorStats(meanLuminance = mean, variance = variance, pixelCount = n)
    }

    fun colorStatsFromRgbRows(rows: List<IntArray>): ColorStats {
        var n = 0
        var mean = 0.0
        var m2 = 0.0
        for (row in rows) {
            var i = 0
            while (i + 2 < row.size) {
                val yLuma = luminance(row[i], row[i + 1], row[i + 2])
                n += 1
                val delta = yLuma - mean
                mean += delta / n
                m2 += delta * (yLuma - mean)
                i += 3
            }
        }
        val variance = if (n > 0) m2 / n else 0.0
        return ColorStats(meanLuminance = mean, variance = variance, pixelCount = n)
    }

    private fun lerp(a: Int, b: Int, t: Double): Int =
        (a + (b - a) * t).toInt().coerceIn(0, 255)

    /**
     * Draw honest experimental frame onto [canvas]. Labels never claim official WE.
     */
    fun drawExperimentalFrame(canvas: Canvas, config: Config, phase: Int) {
        val w = canvas.width.coerceAtLeast(1)
        val h = canvas.height.coerceAtLeast(1)
        val seed = seedFor(config.sampleKind, config.mpkgSha256, phase)
        val c0 = primaryRgb(seed)
        val c1 = secondaryRgb(seed)

        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        paint.shader = LinearGradient(
            0f,
            0f,
            w.toFloat(),
            h.toFloat(),
            c0.toArgb(),
            c1.toArgb(),
            Shader.TileMode.CLAMP,
        )
        canvas.drawRect(0f, 0f, w.toFloat(), h.toFloat(), paint)
        paint.shader = null

        // High-contrast checker band for non-solid stats under downscale/screencap.
        val cell = (w / 16).coerceAtLeast(8)
        val bandTop = h / 3
        val bandBottom = bandTop + cell * 2
        for (y in bandTop until bandBottom step cell) {
            var x = 0
            var col = ((y - bandTop) / cell) % 2
            while (x < w) {
                paint.color = if (col == 0) Color.WHITE else Color.rgb(20, 20, 40)
                canvas.drawRect(
                    x.toFloat(),
                    y.toFloat(),
                    (x + cell).toFloat().coerceAtMost(w.toFloat()),
                    (y + cell).toFloat().coerceAtMost(bandBottom.toFloat()),
                    paint,
                )
                x += cell
                col = 1 - col
            }
        }

        val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textAlign = Paint.Align.CENTER
            setShadowLayer(4f, 1f, 1f, Color.BLACK)
        }
        textPaint.textSize = (h * 0.08f).coerceIn(28f, 72f)
        val cx = w / 2f
        var ty = h * 0.22f
        canvas.drawText(config.kindLabel, cx, ty, textPaint)

        if (config.sampleKind == KIND_VIDEO && phase > 0) {
            textPaint.textSize = (h * 0.05f).coerceIn(20f, 48f)
            ty += textPaint.textSize * 1.4f
            canvas.drawText("MOTION p$phase", cx, ty, textPaint)
        }

        textPaint.textSize = (h * 0.045f).coerceIn(18f, 40f)
        ty = h * 0.55f
        canvas.drawText("sha ${config.checksumDigits}", cx, ty, textPaint)

        textPaint.textSize = (h * 0.035f).coerceIn(14f, 32f)
        textPaint.color = Color.rgb(255, 230, 160)
        ty = h * 0.72f
        canvas.drawText(DISCLAIMER, cx, ty, textPaint)

        textPaint.color = Color.rgb(200, 220, 255)
        ty = h * 0.82f
        canvas.drawText("seed=$seed phase=$phase", cx, ty, textPaint)
    }
}
