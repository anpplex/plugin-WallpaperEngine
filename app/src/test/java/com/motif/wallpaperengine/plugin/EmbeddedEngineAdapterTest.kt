package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * WP-12C positive contract: default flag → official; explicit flag → EMBEDDED.
 * Pure JVM unit tests (returnDefaultValues already true; no Robolectric).
 */
class EmbeddedEngineAdapterTest {

    @Test
    fun defaultFlag_false_usesOfficialPath() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = false)
        val result = adapter.resolve(
            PluginContract.METHOD_PING,
            mapOf(PluginContract.KEY_CALL_ID to "call-official"),
        )
        assertTrue(result.ok)
        assertEquals(PluginContract.CODE_OK, result.code)
        assertEquals(EngineAdapter.RUNTIME_MODE_OFFICIAL, result.runtimeMode)
        assertEquals(PluginContract.ENGINE_PACKAGE, result.enginePackage)
        assertEquals(PluginContract.ENGINE_WALLPAPER_SERVICE, result.wallpaperService)
        assertNull(result.failureSignature)
        assertNotEquals(EngineAdapter.RUNTIME_MODE_EMBEDDED, result.runtimeMode)
    }

    @Test
    fun defaultFlag_engineMethod_stillOfficial() {
        val adapter = EmbeddedEngineAdapter()
        val result = adapter.resolve(
            PluginContract.METHOD_APPLY_CURRENT,
            mapOf(
                PluginContract.KEY_CALL_ID to "call-apply",
                PluginContract.KEY_OPERATION_ID to "op-1",
            ),
        )
        assertTrue(result.ok)
        assertEquals(EngineAdapter.RUNTIME_MODE_OFFICIAL, result.runtimeMode)
        assertEquals(EngineAdapter.OFFICIAL_ENGINE_PACKAGE, result.enginePackage)
    }

    @Test
    fun flagTrue_embeddedMode_ok() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = true)
        val result = adapter.resolve(
            PluginContract.METHOD_APPLY_CURRENT,
            mapOf(
                PluginContract.KEY_CALL_ID to "call-embedded",
                PluginContract.KEY_OPERATION_ID to "op-embed",
            ),
        )
        assertTrue(result.ok)
        assertEquals(PluginContract.CODE_OK, result.code)
        assertEquals(EngineAdapter.RUNTIME_MODE_EMBEDDED, result.runtimeMode)
        assertEquals(EmbeddedEngineAdapter.EMBEDDED_ENGINE_PACKAGE, result.enginePackage)
        assertEquals(EmbeddedEngineAdapter.EMBEDDED_WALLPAPER_SERVICE, result.wallpaperService)
        assertNull(result.failureSignature)
        assertNotEquals(PluginContract.ENGINE_PACKAGE, result.enginePackage)
    }

    @Test
    fun flagTrue_requireEmbedded_stillEmbeddedOk() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = true)
        val result = adapter.resolve(
            PluginContract.METHOD_OPEN_LIBRARY,
            mapOf(
                PluginContract.KEY_CALL_ID to "call-req",
                PluginContract.KEY_OPERATION_ID to "op-req",
                EngineAdapter.KEY_REQUIRE_EMBEDDED to true,
            ),
        )
        assertTrue(result.ok)
        assertEquals(EngineAdapter.RUNTIME_MODE_EMBEDDED, result.runtimeMode)
        assertEquals(PluginContract.CODE_OK, result.code)
    }

    @Test
    fun officialAdapter_neverClaimsEmbedded() {
        val official = OfficialEngineAdapter()
        val result = official.resolve(
            PluginContract.METHOD_NEXT,
            mapOf(
                PluginContract.KEY_CALL_ID to "c",
                PluginContract.KEY_OPERATION_ID to "o",
            ),
        )
        assertTrue(result.ok)
        assertEquals(EngineAdapter.RUNTIME_MODE_OFFICIAL, result.runtimeMode)
        assertEquals(PluginContract.ENGINE_PACKAGE, result.enginePackage)
    }

    @Test
    fun constants_matchPluginContract() {
        assertEquals(PluginContract.ENGINE_PACKAGE, EngineAdapter.OFFICIAL_ENGINE_PACKAGE)
        assertEquals(
            PluginContract.ENGINE_WALLPAPER_SERVICE,
            EngineAdapter.OFFICIAL_WALLPAPER_SERVICE,
        )
    }
}
