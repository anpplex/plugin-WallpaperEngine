package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * WP-12C negative / fail-closed contract.
 *
 * Host harness detects non-zero path via [AdapterResult.code] and stable
 * [AdapterResult.failureSignature] values:
 * UNKNOWN_METHOD, CALLER_APPENDED_ARGS, FALLBACK_MASQUERADE.
 */
class EmbeddedEngineAdapterNegativeTest {

    @Test
    fun unknownMethod_returnsBadRequest_unknownMethodSignature() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = false)
        val result = adapter.resolve(
            "not_a_protocol_method",
            mapOf(PluginContract.KEY_CALL_ID to "call-x"),
        )
        assertFalse(result.ok)
        assertEquals(PluginContract.CODE_BAD_REQUEST, result.code)
        assertEquals(EngineAdapter.FAILURE_UNKNOWN_METHOD, result.failureSignature)
        assertEquals(EngineAdapter.FAILURE_UNKNOWN_METHOD, result.message)
        assertNotEquals(PluginContract.CODE_OK, result.code)
    }

    @Test
    fun unknownMethod_withEmbeddedFlag_stillFails() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = true)
        val result = adapter.resolve("launch_secret", emptyMap())
        assertFalse(result.ok)
        assertEquals(PluginContract.CODE_BAD_REQUEST, result.code)
        assertEquals(EngineAdapter.FAILURE_UNKNOWN_METHOD, result.failureSignature)
    }

    @Test
    fun callerAppendedArgs_rejected() {
        val adapter = EmbeddedEngineAdapter()
        val result = adapter.resolve(
            PluginContract.METHOD_PING,
            mapOf(
                PluginContract.KEY_CALL_ID to "call-1",
                "evilExtra" to "injected",
            ),
        )
        assertFalse(result.ok)
        assertEquals(PluginContract.CODE_BAD_REQUEST, result.code)
        assertEquals(EngineAdapter.FAILURE_CALLER_APPENDED_ARGS, result.failureSignature)
        assertEquals(EngineAdapter.FAILURE_CALLER_APPENDED_ARGS, result.message)
    }

    @Test
    fun callerAppendedArgs_withEmbeddedEnabled_rejected() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = true)
        val result = adapter.resolve(
            PluginContract.METHOD_APPLY_CURRENT,
            mapOf(
                PluginContract.KEY_CALL_ID to "call-2",
                PluginContract.KEY_OPERATION_ID to "op-2",
                "runtimeOverride" to "EMBEDDED",
            ),
        )
        assertFalse(result.ok)
        assertEquals(EngineAdapter.FAILURE_CALLER_APPENDED_ARGS, result.failureSignature)
    }

    @Test
    fun requireEmbedded_whenFlagFalse_fallbackMasquerade() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = false)
        val result = adapter.resolve(
            PluginContract.METHOD_APPLY_CURRENT,
            mapOf(
                PluginContract.KEY_CALL_ID to "call-fb",
                PluginContract.KEY_OPERATION_ID to "op-fb",
                EngineAdapter.KEY_REQUIRE_EMBEDDED to true,
            ),
        )
        assertFalse("must not PASS as official when requireEmbedded=true", result.ok)
        assertEquals(PluginContract.CODE_BAD_REQUEST, result.code)
        assertEquals(EngineAdapter.FAILURE_FALLBACK_MASQUERADE, result.failureSignature)
        assertEquals(EngineAdapter.FAILURE_FALLBACK_MASQUERADE, result.message)
        // Must not claim embedded PASS after falling back.
        assertNotEquals(EngineAdapter.RUNTIME_MODE_EMBEDDED, result.runtimeMode)
        assertEquals(EngineAdapter.RUNTIME_MODE_OFFICIAL, result.runtimeMode)
    }

    @Test
    fun requireEmbedded_stringTrue_whenFlagFalse_fallbackMasquerade() {
        val adapter = EmbeddedEngineAdapter(embeddedRuntimeEnabled = false)
        val result = adapter.resolve(
            PluginContract.METHOD_OPEN_LIBRARY,
            mapOf(
                PluginContract.KEY_CALL_ID to "call-s",
                PluginContract.KEY_OPERATION_ID to "op-s",
                EngineAdapter.KEY_REQUIRE_EMBEDDED to "true",
            ),
        )
        assertFalse(result.ok)
        assertEquals(EngineAdapter.FAILURE_FALLBACK_MASQUERADE, result.failureSignature)
    }

    @Test
    fun officialAdapter_unknownMethod_sameSignature() {
        val result = OfficialEngineAdapter().resolve("nope", emptyMap())
        assertFalse(result.ok)
        assertEquals(EngineAdapter.FAILURE_UNKNOWN_METHOD, result.failureSignature)
        assertTrue(result.code != PluginContract.CODE_OK)
    }

    @Test
    fun officialAdapter_appendedArgs_sameSignature() {
        val result = OfficialEngineAdapter().resolve(
            PluginContract.METHOD_STATUS,
            mapOf("sideChannel" to 1),
        )
        assertFalse(result.ok)
        assertEquals(EngineAdapter.FAILURE_CALLER_APPENDED_ARGS, result.failureSignature)
    }
}
