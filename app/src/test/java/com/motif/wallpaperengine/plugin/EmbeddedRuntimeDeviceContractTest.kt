package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * WP-12D pure/JVM unit contract for E2/E3 identity rules.
 *
 * No device, no ADB, no forged E3 PASS evidence. Rules freeze package /
 * user / caller identity expected by the device harness:
 *
 * 1. Plugin package ≠ official WE (`io.wallpaperengine.weclient`)
 * 2. Embedded host must not be the official package when mode=EMBEDDED
 * 3. realCaller package must match Mineradio expected identity when present
 * 4. car path user must be [EmbeddedRuntimeDeviceContract.TARGET_USER] (12)
 * 5. missing serial / wrong user / official-as-embedded-host → harness
 *    failure signatures ([EmbeddedRuntimeDeviceContract.FAILURE_*])
 *
 * Shell (or any non-Mineradio) realCaller must not yield E3 identity PASS.
 */
class EmbeddedRuntimeDeviceContractTest {

    // -------------------------------------------------------------------------
    // Frozen constants (harness / car path)
    // -------------------------------------------------------------------------

    @Test
    fun targetUser_isTwelve_forCarPath() {
        assertEquals(12, EmbeddedRuntimeDeviceContract.TARGET_USER)
    }

    @Test
    fun pluginPackage_isNotOfficialWePackage() {
        assertEquals(
            EmbeddedEngineAdapter.EMBEDDED_ENGINE_PACKAGE,
            EmbeddedRuntimeDeviceContract.PLUGIN_PACKAGE,
        )
        assertEquals(
            PluginContract.ENGINE_PACKAGE,
            EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
        )
        assertEquals("io.wallpaperengine.weclient", EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE)
        assertNotEquals(
            EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
            EmbeddedRuntimeDeviceContract.PLUGIN_PACKAGE,
        )
    }

    @Test
    fun mineradioExpectedIdentity_isFrozen() {
        assertEquals("com.mineradio.app", EmbeddedRuntimeDeviceContract.MINERADIO_PACKAGE)
        assertNotEquals(
            EmbeddedRuntimeDeviceContract.MINERADIO_PACKAGE,
            EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
        )
        assertNotEquals(
            EmbeddedRuntimeDeviceContract.MINERADIO_PACKAGE,
            EmbeddedRuntimeDeviceContract.PLUGIN_PACKAGE,
        )
    }

    @Test
    fun failureSignatures_areStableHarnessTokens() {
        assertEquals("MISSING_SERIAL", EmbeddedRuntimeDeviceContract.FAILURE_MISSING_SERIAL)
        assertEquals("WRONG_USER", EmbeddedRuntimeDeviceContract.FAILURE_WRONG_USER)
        assertEquals(
            "OFFICIAL_AS_EMBEDDED_HOST",
            EmbeddedRuntimeDeviceContract.FAILURE_OFFICIAL_AS_EMBEDDED_HOST,
        )
        assertEquals(
            "PLUGIN_IS_OFFICIAL",
            EmbeddedRuntimeDeviceContract.FAILURE_PLUGIN_IS_OFFICIAL,
        )
        assertEquals(
            "REAL_CALLER_MISMATCH",
            EmbeddedRuntimeDeviceContract.FAILURE_REAL_CALLER_MISMATCH,
        )
    }

    // -------------------------------------------------------------------------
    // Fail-closed: serial / user
    // -------------------------------------------------------------------------

    @Test
    fun missingSerial_failsClosed_missingSerialSignature() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(serial = null),
        )
        assertFalse(result.ok)
        assertEquals(EmbeddedRuntimeDeviceContract.FAILURE_MISSING_SERIAL, result.failureSignature)
        assertNull(result.message) // signature is the machine token; message optional

        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_MISSING_SERIAL,
            EmbeddedRuntimeDeviceContract.evaluate(
                validSnapshot().copy(serial = ""),
            ).failureSignature,
        )
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_MISSING_SERIAL,
            EmbeddedRuntimeDeviceContract.evaluate(
                validSnapshot().copy(serial = "   "),
            ).failureSignature,
        )
    }

    @Test
    fun wrongUser_failsClosed_wrongUserSignature() {
        for (user in listOf(0, 10, 11, 13, null)) {
            val result = EmbeddedRuntimeDeviceContract.evaluate(
                validSnapshot().copy(userId = user),
            )
            assertFalse("user=$user must fail", result.ok)
            assertEquals(
                "user=$user",
                EmbeddedRuntimeDeviceContract.FAILURE_WRONG_USER,
                result.failureSignature,
            )
        }
    }

    @Test
    fun userTwelve_passesUserGate_whenOtherIdentityValid() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(validSnapshot())
        assertTrue(result.ok)
        assertNull(result.failureSignature)
    }

    // -------------------------------------------------------------------------
    // Fail-closed: plugin / embedded host packages
    // -------------------------------------------------------------------------

    @Test
    fun pluginPackageEqualsOfficial_fails_pluginIsOfficial() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                pluginPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
            ),
        )
        assertFalse(result.ok)
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_PLUGIN_IS_OFFICIAL,
            result.failureSignature,
        )
    }

    @Test
    fun embeddedMode_withOfficialHost_fails_officialAsEmbeddedHost() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
                embeddedHostPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
            ),
        )
        assertFalse(result.ok)
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_OFFICIAL_AS_EMBEDDED_HOST,
            result.failureSignature,
        )
    }

    @Test
    fun embeddedMode_nullHostTreatedAsMissingHost_failsOfficialAsEmbeddedHost() {
        // Fail-closed: EMBEDDED without an explicit non-official host cannot PASS.
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
                embeddedHostPackage = null,
            ),
        )
        assertFalse(result.ok)
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_OFFICIAL_AS_EMBEDDED_HOST,
            result.failureSignature,
        )
    }

    @Test
    fun embeddedMode_withPluginHost_ok() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
                embeddedHostPackage = EmbeddedRuntimeDeviceContract.PLUGIN_PACKAGE,
            ),
        )
        assertTrue(result.ok)
        assertNull(result.failureSignature)
    }

    @Test
    fun officialMode_mayUseOfficialEnginePackage() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                runtimeMode = EngineAdapter.RUNTIME_MODE_OFFICIAL,
                embeddedHostPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
            ),
        )
        assertTrue(result.ok)
        assertNull(result.failureSignature)
    }

    // -------------------------------------------------------------------------
    // Fail-closed: realCaller (no forge E3 via shell / foreign package)
    // -------------------------------------------------------------------------

    @Test
    fun realCallerAbsent_isAllowed_forIdentityGatesWithoutE3Claim() {
        // "when present" — missing realCaller is not an identity gate failure here.
        // Device E3 continuous evidence still requires Mineradio caller on-device;
        // this pure contract never forges that PASS.
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(realCallerPackage = null),
        )
        assertTrue(result.ok)
        assertNull(result.failureSignature)
    }

    @Test
    fun realCallerMineradio_ok() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                realCallerPackage = EmbeddedRuntimeDeviceContract.MINERADIO_PACKAGE,
            ),
        )
        assertTrue(result.ok)
        assertNull(result.failureSignature)
    }

    @Test
    fun realCallerShell_fails_realCallerMismatch_noForgeE3() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(realCallerPackage = "shell"),
        )
        assertFalse("shell must not forge E3 identity PASS", result.ok)
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_REAL_CALLER_MISMATCH,
            result.failureSignature,
        )
    }

    @Test
    fun realCallerForeignPackage_fails_realCallerMismatch() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(realCallerPackage = "com.evil.app"),
        )
        assertFalse(result.ok)
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_REAL_CALLER_MISMATCH,
            result.failureSignature,
        )
    }

    @Test
    fun realCallerOfficialWe_fails_realCallerMismatch() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                realCallerPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
            ),
        )
        assertFalse(result.ok)
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_REAL_CALLER_MISMATCH,
            result.failureSignature,
        )
    }

    // -------------------------------------------------------------------------
    // Precedence: serial → user → plugin → embedded host → realCaller
    // -------------------------------------------------------------------------

    @Test
    fun precedence_missingSerial_beforeWrongUser() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(serial = null, userId = 0),
        )
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_MISSING_SERIAL,
            result.failureSignature,
        )
    }

    @Test
    fun precedence_wrongUser_beforePluginCollision() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                userId = 0,
                pluginPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
            ),
        )
        assertEquals(EmbeddedRuntimeDeviceContract.FAILURE_WRONG_USER, result.failureSignature)
    }

    @Test
    fun precedence_pluginCollision_beforeOfficialAsEmbeddedHost() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                pluginPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
                runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
                embeddedHostPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
            ),
        )
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_PLUGIN_IS_OFFICIAL,
            result.failureSignature,
        )
    }

    @Test
    fun precedence_officialAsEmbeddedHost_beforeRealCallerMismatch() {
        val result = EmbeddedRuntimeDeviceContract.evaluate(
            validSnapshot().copy(
                runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
                embeddedHostPackage = EmbeddedRuntimeDeviceContract.OFFICIAL_WE_PACKAGE,
                realCallerPackage = "shell",
            ),
        )
        assertEquals(
            EmbeddedRuntimeDeviceContract.FAILURE_OFFICIAL_AS_EMBEDDED_HOST,
            result.failureSignature,
        )
    }

    // -------------------------------------------------------------------------
    // helpers
    // -------------------------------------------------------------------------

    private fun validSnapshot(): EmbeddedRuntimeDeviceContract.Snapshot =
        EmbeddedRuntimeDeviceContract.Snapshot(
            serial = "LD249H019625",
            userId = EmbeddedRuntimeDeviceContract.TARGET_USER,
            pluginPackage = EmbeddedRuntimeDeviceContract.PLUGIN_PACKAGE,
            runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
            embeddedHostPackage = EmbeddedRuntimeDeviceContract.PLUGIN_PACKAGE,
            realCallerPackage = EmbeddedRuntimeDeviceContract.MINERADIO_PACKAGE,
        )
}

/**
 * Pure E2/E3 identity rules for WP-12D (host unit tests + future device harness).
 *
 * No Context, ADB, or filesystem. Never synthesizes device E3 PASS evidence.
 */
object EmbeddedRuntimeDeviceContract {
    const val TARGET_USER: Int = 12

    /** Experimental plugin applicationId / embedded engine package. */
    const val PLUGIN_PACKAGE: String = EmbeddedEngineAdapter.EMBEDDED_ENGINE_PACKAGE

    /** Official Wallpaper Engine client package. */
    const val OFFICIAL_WE_PACKAGE: String = PluginContract.ENGINE_PACKAGE

    /** Mineradio host expected as Binder realCaller for continuous E3. */
    const val MINERADIO_PACKAGE: String = "com.mineradio.app"

    const val FAILURE_MISSING_SERIAL: String = "MISSING_SERIAL"
    const val FAILURE_WRONG_USER: String = "WRONG_USER"
    const val FAILURE_OFFICIAL_AS_EMBEDDED_HOST: String = "OFFICIAL_AS_EMBEDDED_HOST"
    const val FAILURE_PLUGIN_IS_OFFICIAL: String = "PLUGIN_IS_OFFICIAL"
    const val FAILURE_REAL_CALLER_MISMATCH: String = "REAL_CALLER_MISMATCH"

    data class Snapshot(
        val serial: String?,
        val userId: Int?,
        val pluginPackage: String,
        val runtimeMode: String,
        val embeddedHostPackage: String?,
        val realCallerPackage: String?,
    )

    data class Result(
        val ok: Boolean,
        val failureSignature: String? = null,
        val message: String? = null,
    ) {
        companion object {
            fun pass(): Result = Result(ok = true, failureSignature = null, message = null)

            fun fail(signature: String): Result =
                Result(ok = false, failureSignature = signature, message = null)
        }
    }

    /**
     * Evaluate identity gates only (fail-closed).
     *
     * Order: serial → user → plugin≠official → embedded host → realCaller (if present).
     */
    fun evaluate(snapshot: Snapshot): Result {
        if (snapshot.serial.isNullOrBlank()) {
            return Result.fail(FAILURE_MISSING_SERIAL)
        }
        if (snapshot.userId != TARGET_USER) {
            return Result.fail(FAILURE_WRONG_USER)
        }
        if (snapshot.pluginPackage == OFFICIAL_WE_PACKAGE) {
            return Result.fail(FAILURE_PLUGIN_IS_OFFICIAL)
        }
        if (snapshot.runtimeMode == EngineAdapter.RUNTIME_MODE_EMBEDDED) {
            val host = snapshot.embeddedHostPackage
            if (host.isNullOrBlank() || host == OFFICIAL_WE_PACKAGE) {
                return Result.fail(FAILURE_OFFICIAL_AS_EMBEDDED_HOST)
            }
        }
        val caller = snapshot.realCallerPackage
        if (caller != null && caller != MINERADIO_PACKAGE) {
            return Result.fail(FAILURE_REAL_CALLER_MISMATCH)
        }
        return Result.pass()
    }
}
