package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * WP-12E pure/JVM unit contract for experimental scene/video preview surface.
 *
 * No device, no forged EffectiveDone, no claim of official SceneLib frames.
 * Locks:
 * 1. scene vs video produce distinct seeds for the same mpkg sha
 * 2. synthetic gradient color stats are non-black and non-solid
 * 3. intent extras allowlist is fail-closed
 * 4. invalid kind/sha rejected by parseConfig
 * 5. motion phase changes video seed (dual screencap differ)
 */
class EmbeddedSceneVideoTest {

    private val sampleSha =
        "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"

    // -------------------------------------------------------------------------
    // Distinct seeds: scene vs video
    // -------------------------------------------------------------------------

    @Test
    fun sceneAndVideo_produceDistinctSeeds_sameMpkgSha() {
        val scene = EmbeddedExperimentalPreview.seedFor(
            EmbeddedExperimentalPreview.KIND_SCENE,
            sampleSha,
            framePhase = 0,
        )
        val video = EmbeddedExperimentalPreview.seedFor(
            EmbeddedExperimentalPreview.KIND_VIDEO,
            sampleSha,
            framePhase = 0,
        )
        assertNotEquals(scene, video)
    }

    @Test
    fun differentMpkgSha_produceDistinctSeeds_sameKind() {
        val other =
            "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        val a = EmbeddedExperimentalPreview.seedFor(
            EmbeddedExperimentalPreview.KIND_SCENE,
            sampleSha,
        )
        val b = EmbeddedExperimentalPreview.seedFor(
            EmbeddedExperimentalPreview.KIND_SCENE,
            other,
        )
        assertNotEquals(a, b)
    }

    @Test
    fun videoMotionPhase_changesSeed() {
        val p0 = EmbeddedExperimentalPreview.seedFor(
            EmbeddedExperimentalPreview.KIND_VIDEO,
            sampleSha,
            framePhase = 0,
        )
        val p1 = EmbeddedExperimentalPreview.seedFor(
            EmbeddedExperimentalPreview.KIND_VIDEO,
            sampleSha,
            framePhase = 1,
        )
        assertNotEquals(p0, p1)
    }

    @Test
    fun config_exposesKindLabelAndChecksumDigits() {
        val scene = EmbeddedExperimentalPreview.parseConfig(
            EmbeddedExperimentalPreview.KIND_SCENE,
            sampleSha,
        )
        assertNotNull(scene)
        assertEquals("EXP SCENE", scene!!.kindLabel)
        assertEquals(sampleSha.take(8), scene.checksumDigits)

        val video = EmbeddedExperimentalPreview.parseConfig(
            EmbeddedExperimentalPreview.KIND_VIDEO,
            sampleSha,
        )
        assertNotNull(video)
        assertEquals("EXP VIDEO", video!!.kindLabel)
        assertNotEquals(scene.seed, video.seed)
    }

    // -------------------------------------------------------------------------
    // Color stats: non-black, non-solid
    // -------------------------------------------------------------------------

    @Test
    fun sampleGradientStats_nonBlackNonSolid_forSceneAndVideoSeeds() {
        for (kind in listOf(
            EmbeddedExperimentalPreview.KIND_SCENE,
            EmbeddedExperimentalPreview.KIND_VIDEO,
        )) {
            for (phase in 0..1) {
                val seed = EmbeddedExperimentalPreview.seedFor(kind, sampleSha, phase)
                val stats = EmbeddedExperimentalPreview.sampleGradientStats(seed)
                assertTrue(
                    "kind=$kind phase=$phase mean=${stats.meanLuminance}",
                    stats.meanLuminance >= EmbeddedExperimentalPreview.BLACK_MEAN_THRESHOLD,
                )
                assertTrue(
                    "kind=$kind phase=$phase var=${stats.variance}",
                    stats.variance >= EmbeddedExperimentalPreview.SOLID_VARIANCE_THRESHOLD,
                )
                assertTrue(stats.nonBlackNonSolid)
                assertFalse(stats.black)
                assertFalse(stats.solid)
                assertTrue(stats.pixelCount > 0)
            }
        }
    }

    @Test
    fun colorStatsFromRgbRows_detectsSolidBlack() {
        val rows = List(8) { IntArray(8 * 3) { 0 } }
        val stats = EmbeddedExperimentalPreview.colorStatsFromRgbRows(rows)
        assertTrue(stats.black)
        assertTrue(stats.solid)
        assertFalse(stats.nonBlackNonSolid)
        assertEquals(0.0, stats.meanLuminance, 1e-9)
    }

    @Test
    fun colorStatsFromRgbRows_detectsSolidNonBlack() {
        // Flat mid-gray: non-black but solid (low variance).
        val rows = List(8) { IntArray(8 * 3) { 128 } }
        val stats = EmbeddedExperimentalPreview.colorStatsFromRgbRows(rows)
        assertFalse(stats.black)
        assertTrue(stats.solid)
        assertFalse(stats.nonBlackNonSolid)
    }

    @Test
    fun colorStatsFromRgbRows_gradientIsNonSolid() {
        val rows = mutableListOf<IntArray>()
        for (y in 0 until 16) {
            val row = IntArray(16 * 3)
            for (x in 0 until 16) {
                val v = (x * 16).coerceIn(0, 255)
                row[x * 3] = v
                row[x * 3 + 1] = 255 - v
                row[x * 3 + 2] = (y * 16).coerceIn(0, 255)
            }
            rows.add(row)
        }
        val stats = EmbeddedExperimentalPreview.colorStatsFromRgbRows(rows)
        assertTrue(stats.nonBlackNonSolid)
    }

    @Test
    fun luminance_rec601_matchesKnownValues() {
        assertEquals(0.0, EmbeddedExperimentalPreview.luminance(0, 0, 0), 1e-9)
        assertEquals(255.0, EmbeddedExperimentalPreview.luminance(255, 255, 255), 1e-9)
        // Pure green dominates Rec.601.
        val green = EmbeddedExperimentalPreview.luminance(0, 255, 0)
        val red = EmbeddedExperimentalPreview.luminance(255, 0, 0)
        assertTrue(green > red)
    }

    @Test
    fun primaryAndSecondaryRgb_areNotNearBlack() {
        val seed = EmbeddedExperimentalPreview.seedFor(
            EmbeddedExperimentalPreview.KIND_SCENE,
            sampleSha,
        )
        val p = EmbeddedExperimentalPreview.primaryRgb(seed)
        val s = EmbeddedExperimentalPreview.secondaryRgb(seed)
        assertTrue(p.r >= 48 && p.g >= 64 && p.b >= 80)
        assertTrue(s.r >= 180)
        assertNotEquals(p, s)
    }

    // -------------------------------------------------------------------------
    // Fail-closed extras / parse
    // -------------------------------------------------------------------------

    @Test
    fun unknownExtras_failClosed() {
        val unknown = EmbeddedExperimentalPreview.findUnknownExtras(
            setOf(
                EmbeddedExperimentalPreview.EXTRA_SAMPLE_KIND,
                "evilExtra",
                EmbeddedExperimentalPreview.EXTRA_MPKG_SHA256,
            ),
        )
        assertEquals(setOf("evilExtra"), unknown)
    }

    @Test
    fun allowlistedExtras_only_pass() {
        val unknown = EmbeddedExperimentalPreview.findUnknownExtras(
            EmbeddedExperimentalPreview.ALLOWED_INTENT_EXTRAS,
        )
        assertTrue(unknown.isEmpty())
        assertTrue(
            EmbeddedExperimentalPreview.EXTRA_MPKG_PATH in
                EmbeddedExperimentalPreview.ALLOWED_INTENT_EXTRAS,
        )
        assertTrue(
            EmbeddedExperimentalPreview.EXTRA_MPKG_SHA256 in
                EmbeddedExperimentalPreview.ALLOWED_INTENT_EXTRAS,
        )
    }

    @Test
    fun parseConfig_rejectsInvalidKind() {
        assertNull(
            EmbeddedExperimentalPreview.parseConfig("official", sampleSha),
        )
        assertNull(
            EmbeddedExperimentalPreview.parseConfig(null, sampleSha),
        )
        assertNull(
            EmbeddedExperimentalPreview.parseConfig("", sampleSha),
        )
    }

    @Test
    fun parseConfig_rejectsInvalidSha() {
        assertNull(
            EmbeddedExperimentalPreview.parseConfig(
                EmbeddedExperimentalPreview.KIND_SCENE,
                "not-a-sha",
            ),
        )
        assertNull(
            EmbeddedExperimentalPreview.parseConfig(
                EmbeddedExperimentalPreview.KIND_SCENE,
                "gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg",
            ),
        )
        assertNull(
            EmbeddedExperimentalPreview.parseConfig(
                EmbeddedExperimentalPreview.KIND_SCENE,
                sampleSha.take(63), // too short
            ),
        )
        assertNull(
            EmbeddedExperimentalPreview.parseConfig(
                EmbeddedExperimentalPreview.KIND_SCENE,
                null,
            ),
        )
    }

    @Test
    fun parseConfig_normalizesUppercaseAndAcceptsValid() {
        val upper =
            "A1B2C3D4E5F60718293A4B5C6D7E8F90123456789ABCDEF0123456789ABCDEF0"
        // parseConfig lowercases then validates.
        val cfg = EmbeddedExperimentalPreview.parseConfig(
            EmbeddedExperimentalPreview.KIND_VIDEO,
            "  $upper  ",
        )
        assertNotNull(cfg)
        assertEquals(sampleSha, cfg!!.mpkgSha256)
        assertEquals(EmbeddedExperimentalPreview.KIND_VIDEO, cfg.sampleKind)
    }

    @Test
    fun isValidMpkgSha256_requiresLowercaseHex64() {
        assertTrue(EmbeddedExperimentalPreview.isValidMpkgSha256(sampleSha))
        assertFalse(
            EmbeddedExperimentalPreview.isValidMpkgSha256(
                "A1B2C3D4E5F60718293A4B5C6D7E8F90123456789ABCDEF0123456789ABCDEF0",
            ),
        )
    }

    @Test
    fun thresholds_alignWithAnalyzerContract() {
        assertEquals(2.0, EmbeddedExperimentalPreview.BLACK_MEAN_THRESHOLD, 0.0)
        assertEquals(1.0, EmbeddedExperimentalPreview.SOLID_VARIANCE_THRESHOLD, 0.0)
        assertTrue(EmbeddedExperimentalPreview.VIDEO_MOTION_DELAY_MS >= 3_000L)
    }

    @Test
    fun disclaimer_doesNotClaimOfficialSceneLib() {
        val d = EmbeddedExperimentalPreview.DISCLAIMER.lowercase()
        assertTrue(d.contains("experimental"))
        assertTrue(d.contains("not official"))
        assertFalse(d.contains("official scenelib rendering"))
    }

    @Test
    fun embeddedAdapter_exposesPreviewActivityIdentity() {
        assertEquals(
            "com.motif.wallpaperengine.plugin.EmbeddedPreviewActivity",
            EmbeddedEngineAdapter.EMBEDDED_PREVIEW_ACTIVITY,
        )
        assertTrue(
            EmbeddedEngineAdapter.EMBEDDED_PREVIEW_COMPONENT.startsWith(
                EmbeddedEngineAdapter.EMBEDDED_ENGINE_PACKAGE,
            ),
        )
        assertNotEquals(
            PluginContract.ENGINE_PACKAGE,
            EmbeddedEngineAdapter.EMBEDDED_ENGINE_PACKAGE,
        )
        assertFalse(
            EmbeddedEngineAdapter.EMBEDDED_PREVIEW_ACTIVITY.contains("wallpaperengine.weclient"),
        )
    }
}
