package com.motif.wallpaperengine.plugin

import android.os.Bundle
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * WP-01 RED: freeze protocol 1 surface before PluginContract exists.
 *
 * Expected on RED: compile/test FAIL because production PluginContract /
 * PluginResult are not implemented yet. GREEN must satisfy every assertion
 * here without expanding protocol 1 or touching Context/FS/network.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [31])
class PluginContractTest {

    // -------------------------------------------------------------------------
    // §3.3 fixed identity / authority / engine components
    // -------------------------------------------------------------------------

    @Test
    fun protocolVersion_isOne() {
        assertEquals(1, PluginContract.PROTOCOL_VERSION)
    }

    @Test
    fun authority_andEngineBaselines_areFrozen() {
        assertEquals("com.motif.wallpaperengine.control", PluginContract.AUTHORITY)
        assertEquals("io.wallpaperengine.weclient", PluginContract.ENGINE_PACKAGE)
        assertEquals(
            "io.wallpaperengine.weclient.BrowseActivity",
            PluginContract.ENGINE_BROWSE_ACTIVITY,
        )
        assertEquals(
            "io.wallpaperengine.weclient.WEWallpaperService",
            PluginContract.ENGINE_WALLPAPER_SERVICE,
        )
    }

    // -------------------------------------------------------------------------
    // §3.2 method set
    // -------------------------------------------------------------------------

    @Test
    fun methodSet_matchesProtocolOneExactly() {
        val expected = setOf(
            "ping",
            "status",
            "renew_action",
            "import_mpkg",
            "open_library",
            "apply_current",
            "next",
            "previous",
            "stop",
            "diagnostics",
        )
        assertEquals(expected, PluginContract.METHODS)
        assertEquals(expected, PluginContract.METHOD_PING.let {
            // individual constants must equal the set members
            setOf(
                PluginContract.METHOD_PING,
                PluginContract.METHOD_STATUS,
                PluginContract.METHOD_RENEW_ACTION,
                PluginContract.METHOD_IMPORT_MPKG,
                PluginContract.METHOD_OPEN_LIBRARY,
                PluginContract.METHOD_APPLY_CURRENT,
                PluginContract.METHOD_NEXT,
                PluginContract.METHOD_PREVIOUS,
                PluginContract.METHOD_STOP,
                PluginContract.METHOD_DIAGNOSTICS,
            )
        })
    }

    // -------------------------------------------------------------------------
    // §3.3 fixed field keys (incl. callId/operationId/actionEpoch/sourceOperationId
    // and native KEY_USER_ACTION)
    // -------------------------------------------------------------------------

    @Test
    fun fixedFieldKeys_matchProtocolOne() {
        assertEquals("protocolVersion", PluginContract.KEY_PROTOCOL_VERSION)
        assertEquals("callId", PluginContract.KEY_CALL_ID)
        assertEquals("operationId", PluginContract.KEY_OPERATION_ID)
        assertEquals("targetOperationId", PluginContract.KEY_TARGET_OPERATION_ID)
        assertEquals("actionEpoch", PluginContract.KEY_ACTION_EPOCH)
        assertEquals("activeOperationId", PluginContract.KEY_ACTIVE_OPERATION_ID)
        assertEquals("completedOperationIds", PluginContract.KEY_COMPLETED_OPERATION_IDS)
        assertEquals("code", PluginContract.KEY_CODE)
        assertEquals("message", PluginContract.KEY_MESSAGE)
        assertEquals("operationState", PluginContract.KEY_OPERATION_STATE)
        assertEquals("bindingState", PluginContract.KEY_BINDING_STATE)
        assertEquals("sourceUri", PluginContract.KEY_SOURCE_URI)
        assertEquals("sourceConsumed", PluginContract.KEY_SOURCE_CONSUMED)
        assertEquals("sourceOperationId", PluginContract.KEY_SOURCE_OPERATION_ID)
        assertEquals("displayName", PluginContract.KEY_DISPLAY_NAME)
        assertEquals("bytes", PluginContract.KEY_BYTES)
        assertEquals("sha256", PluginContract.KEY_SHA256)
        assertEquals("runtimePid", PluginContract.KEY_RUNTIME_PID)
        assertEquals("callerPackage", PluginContract.KEY_CALLER_PACKAGE)
        assertEquals("callerUid", PluginContract.KEY_CALLER_UID)
        assertEquals("certAllowlistMatch", PluginContract.KEY_CERT_ALLOWLIST_MATCH)
        assertEquals("engineInstalled", PluginContract.KEY_ENGINE_INSTALLED)
        assertEquals("engineVersion", PluginContract.KEY_ENGINE_VERSION)
        assertEquals("activePackage", PluginContract.KEY_ACTIVE_PACKAGE)
        assertEquals("activeComponent", PluginContract.KEY_ACTIVE_COMPONENT)
        assertEquals("lastError", PluginContract.KEY_LAST_ERROR)
        assertEquals("userAction", PluginContract.KEY_USER_ACTION)
        assertEquals("userActionKind", PluginContract.KEY_USER_ACTION_KIND)
        assertEquals("userActionExpiresAt", PluginContract.KEY_USER_ACTION_EXPIRES_AT)
        assertEquals("fallbackAction", PluginContract.KEY_FALLBACK_ACTION)
    }

    // -------------------------------------------------------------------------
    // §3.4 return codes 0/10/20/40-46/50-54/60
    // -------------------------------------------------------------------------

    @Test
    fun returnCodes_matchProtocolOne() {
        assertEquals(0, PluginContract.CODE_OK)
        assertEquals(10, PluginContract.CODE_ACCEPTED)
        assertEquals(20, PluginContract.CODE_USER_ACTION_REQUIRED)
        assertEquals(40, PluginContract.CODE_BAD_REQUEST)
        assertEquals(41, PluginContract.CODE_CALLER_REJECTED)
        assertEquals(42, PluginContract.CODE_PROTOCOL_MISMATCH)
        assertEquals(43, PluginContract.CODE_ENGINE_NOT_INSTALLED)
        assertEquals(44, PluginContract.CODE_SOURCE_UNREADABLE)
        assertEquals(45, PluginContract.CODE_PACKAGE_INVALID)
        assertEquals(46, PluginContract.CODE_USER_LOCKED)
        assertEquals(50, PluginContract.CODE_BUSY)
        assertEquals(51, PluginContract.CODE_TIMEOUT)
        assertEquals(52, PluginContract.CODE_APPLY_PERMISSION_REQUIRED)
        assertEquals(53, PluginContract.CODE_ACTION_TOKEN_EXPIRED)
        assertEquals(54, PluginContract.CODE_STAGING_QUOTA_EXCEEDED)
        assertEquals(60, PluginContract.CODE_INTERNAL_ERROR)

        assertEquals(
            setOf(0, 10, 20, 40, 41, 42, 43, 44, 45, 46, 50, 51, 52, 53, 54, 60),
            PluginContract.CODES,
        )
    }

    // -------------------------------------------------------------------------
    // §3.5 orthogonal operationState / bindingState enums
    // -------------------------------------------------------------------------

    @Test
    fun operationStates_matchProtocolOne() {
        val expected = setOf(
            "IDLE",
            "ACTION_PENDING",
            "IMPORTING",
            "STAGED",
            "ENGINE_ACTION_PENDING",
            "ENGINE_LAUNCHED",
            "PREVIEW_READY",
            "APPLY_ACTION_PENDING",
            "APPLY_ACTION_LAUNCHED",
            "FAILED",
            "CANCELLED",
        )
        assertEquals(expected, PluginContract.OPERATION_STATES)
    }

    @Test
    fun bindingStates_matchProtocolOne() {
        val expected = setOf(
            "UNKNOWN",
            "UNBOUND",
            "ACTIVE_TARGET",
            "ACTIVE_OTHER",
        )
        assertEquals(expected, PluginContract.BINDING_STATES)
    }

    // -------------------------------------------------------------------------
    // validate(): version / callId / method / mutation / import_mpkg
    // -------------------------------------------------------------------------

    @Test
    fun validate_protocolVersionOne_ping_withCallId_isOk() {
        val extras = baseExtras(protocolVersion = 1, callId = CALL_ID)
        val result = PluginContract.validate(PluginContract.METHOD_PING, extras)
        assertEquals(PluginContract.CODE_OK, result.code)
        assertTrue(result.ok)
    }

    @Test
    fun validate_protocolVersionTwo_returnsProtocolMismatch42() {
        val extras = baseExtras(protocolVersion = 2, callId = CALL_ID)
        val result = PluginContract.validate(PluginContract.METHOD_PING, extras)
        assertEquals(PluginContract.CODE_PROTOCOL_MISMATCH, result.code)
        assertEquals(42, result.code)
        assertFalse(result.ok)
    }

    @Test
    fun validate_missingCallId_returnsBadRequest40() {
        val extras = Bundle().apply {
            putInt(PluginContract.KEY_PROTOCOL_VERSION, 1)
        }
        val result = PluginContract.validate(PluginContract.METHOD_PING, extras)
        assertEquals(PluginContract.CODE_BAD_REQUEST, result.code)
        assertEquals(40, result.code)
        assertFalse(result.ok)
    }

    @Test
    fun validate_blankCallId_returnsBadRequest40() {
        val extras = baseExtras(protocolVersion = 1, callId = "   ")
        val result = PluginContract.validate(PluginContract.METHOD_PING, extras)
        assertEquals(PluginContract.CODE_BAD_REQUEST, result.code)
    }

    @Test
    fun validate_unknownMethod_returnsBadRequest40() {
        val extras = baseExtras(protocolVersion = 1, callId = CALL_ID)
        val result = PluginContract.validate("not_a_protocol_method", extras)
        assertEquals(PluginContract.CODE_BAD_REQUEST, result.code)
        assertEquals(40, result.code)
    }

    @Test
    fun validate_mutationMethods_missingOperationId_returnBadRequest40() {
        val mutationMethods = listOf(
            PluginContract.METHOD_RENEW_ACTION,
            PluginContract.METHOD_IMPORT_MPKG,
            PluginContract.METHOD_OPEN_LIBRARY,
            PluginContract.METHOD_APPLY_CURRENT,
            PluginContract.METHOD_NEXT,
            PluginContract.METHOD_PREVIOUS,
            PluginContract.METHOD_STOP,
        )
        for (method in mutationMethods) {
            val extras = baseExtras(protocolVersion = 1, callId = CALL_ID)
            // intentionally no operationId
            val result = PluginContract.validate(method, extras)
            assertEquals(
                "method=$method must require operationId",
                PluginContract.CODE_BAD_REQUEST,
                result.code,
            )
        }
    }

    @Test
    fun validate_statusAndDiagnostics_withoutOperationId_areAllowedWhenCallIdPresent() {
        for (method in listOf(PluginContract.METHOD_STATUS, PluginContract.METHOD_DIAGNOSTICS)) {
            val extras = baseExtras(protocolVersion = 1, callId = CALL_ID)
            val result = PluginContract.validate(method, extras)
            assertEquals(
                "method=$method may omit operationId",
                PluginContract.CODE_OK,
                result.code,
            )
        }
    }

    @Test
    fun validate_mutationWithOperationId_passesIdentityChecks() {
        val extras = baseExtras(protocolVersion = 1, callId = CALL_ID).apply {
            putString(PluginContract.KEY_OPERATION_ID, OPERATION_ID)
        }
        // open_library only needs protocolVersion/callId/operationId at validate layer
        val result = PluginContract.validate(PluginContract.METHOD_OPEN_LIBRARY, extras)
        assertEquals(PluginContract.CODE_OK, result.code)
    }

    @Test
    fun validate_importMpkg_missingUriNameBytesSha256_returnsBadRequest40() {
        val base = baseExtras(protocolVersion = 1, callId = CALL_ID).apply {
            putString(PluginContract.KEY_OPERATION_ID, OPERATION_ID)
        }

        fun assertMissing(label: String, builder: Bundle.() -> Unit) {
            val extras = Bundle(base).apply(builder)
            val result = PluginContract.validate(PluginContract.METHOD_IMPORT_MPKG, extras)
            assertEquals(
                "import_mpkg missing $label must be BAD_REQUEST",
                PluginContract.CODE_BAD_REQUEST,
                result.code,
            )
        }

        // all four fields missing
        assertEquals(
            PluginContract.CODE_BAD_REQUEST,
            PluginContract.validate(PluginContract.METHOD_IMPORT_MPKG, base).code,
        )

        // each required field missing in isolation
        assertMissing("sourceUri") {
            putString(PluginContract.KEY_DISPLAY_NAME, "pack.mpkg")
            putLong(PluginContract.KEY_BYTES, 128L)
            putString(PluginContract.KEY_SHA256, SHA256)
        }
        assertMissing("displayName") {
            putString(PluginContract.KEY_SOURCE_URI, SOURCE_URI)
            putLong(PluginContract.KEY_BYTES, 128L)
            putString(PluginContract.KEY_SHA256, SHA256)
        }
        assertMissing("bytes") {
            putString(PluginContract.KEY_SOURCE_URI, SOURCE_URI)
            putString(PluginContract.KEY_DISPLAY_NAME, "pack.mpkg")
            putString(PluginContract.KEY_SHA256, SHA256)
        }
        assertMissing("sha256") {
            putString(PluginContract.KEY_SOURCE_URI, SOURCE_URI)
            putString(PluginContract.KEY_DISPLAY_NAME, "pack.mpkg")
            putLong(PluginContract.KEY_BYTES, 128L)
        }
    }

    @Test
    fun validate_importMpkg_completeExtras_isOk() {
        val extras = baseExtras(protocolVersion = 1, callId = CALL_ID).apply {
            putString(PluginContract.KEY_OPERATION_ID, OPERATION_ID)
            putString(PluginContract.KEY_SOURCE_URI, SOURCE_URI)
            putString(PluginContract.KEY_DISPLAY_NAME, "pack.mpkg")
            putLong(PluginContract.KEY_BYTES, 128L)
            putString(PluginContract.KEY_SHA256, SHA256)
        }
        val result = PluginContract.validate(PluginContract.METHOD_IMPORT_MPKG, extras)
        assertEquals(PluginContract.CODE_OK, result.code)
        assertTrue(result.ok)
    }

    @Test
    fun validate_renewAction_requiresActionEpoch() {
        val extras = baseExtras(protocolVersion = 1, callId = CALL_ID).apply {
            putString(PluginContract.KEY_OPERATION_ID, OPERATION_ID)
            // missing actionEpoch
        }
        val missing = PluginContract.validate(PluginContract.METHOD_RENEW_ACTION, extras)
        assertEquals(PluginContract.CODE_BAD_REQUEST, missing.code)

        extras.putInt(PluginContract.KEY_ACTION_EPOCH, 1)
        val ok = PluginContract.validate(PluginContract.METHOD_RENEW_ACTION, extras)
        assertEquals(PluginContract.CODE_OK, ok.code)
    }

    @Test
    fun validate_stop_requiresTargetOperationId() {
        val extras = baseExtras(protocolVersion = 1, callId = CALL_ID).apply {
            putString(PluginContract.KEY_OPERATION_ID, OPERATION_ID)
        }
        val missing = PluginContract.validate(PluginContract.METHOD_STOP, extras)
        assertEquals(PluginContract.CODE_BAD_REQUEST, missing.code)

        extras.putString(PluginContract.KEY_TARGET_OPERATION_ID, TARGET_OPERATION_ID)
        val ok = PluginContract.validate(PluginContract.METHOD_STOP, extras)
        assertEquals(PluginContract.CODE_OK, ok.code)
    }

    @Test
    fun validate_doesNotMutateExtras() {
        val extras = baseExtras(protocolVersion = 1, callId = CALL_ID)
        val before = extras.keySet().toSet()
        PluginContract.validate(PluginContract.METHOD_PING, extras)
        assertEquals(before, extras.keySet().toSet())
        assertEquals(1, extras.getInt(PluginContract.KEY_PROTOCOL_VERSION))
        assertEquals(CALL_ID, extras.getString(PluginContract.KEY_CALL_ID))
    }

    // -------------------------------------------------------------------------
    // helpers
    // -------------------------------------------------------------------------

    private fun baseExtras(protocolVersion: Int, callId: String): Bundle {
        return Bundle().apply {
            putInt(PluginContract.KEY_PROTOCOL_VERSION, protocolVersion)
            putString(PluginContract.KEY_CALL_ID, callId)
        }
    }

    companion object {
        private const val CALL_ID = "00000000-0000-4000-8000-000000000001"
        private const val OPERATION_ID = "00000000-0000-4000-8000-0000000000aa"
        private const val TARGET_OPERATION_ID = "00000000-0000-4000-8000-0000000000bb"
        private const val SOURCE_URI =
            "content://com.mineradio.app.wallpaperplugin.files/staging/pack.mpkg"
        private const val SHA256 =
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
}
