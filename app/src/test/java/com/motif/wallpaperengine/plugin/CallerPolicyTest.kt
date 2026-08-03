package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * WP-02 CallerPolicy unit tests — allowlist package+cert, shell debug-only.
 */
class CallerPolicyTest {

    private val goodCert = "a".repeat(64)
    private val otherCert = "b".repeat(64)

    @Test
    fun allowsMineradioWithMatchingCert() {
        val policy = policy(
            identities = listOf(
                CallerPolicy.PackageIdentity("com.mineradio.app", goodCert),
            ),
        )
        val d = policy.evaluate(10001)
        assertTrue(d.allowed)
        assertEquals("ALLOW", d.reason)
        assertEquals("com.mineradio.app", d.packageName)
    }

    @Test
    fun allowsPluginSelfWithMatchingCert() {
        val policy = policy(
            identities = listOf(
                CallerPolicy.PackageIdentity("com.motif.wallpaperengine", goodCert),
            ),
        )
        assertTrue(policy.evaluate(10002).allowed)
    }

    @Test
    fun rejectsUnknownPackage() {
        val policy = policy(
            identities = listOf(
                CallerPolicy.PackageIdentity("com.evil.app", goodCert),
            ),
        )
        val d = policy.evaluate(10003)
        assertFalse(d.allowed)
        assertEquals(CallerPolicy.REASON_CALLER_REJECTED, d.reason)
    }

    @Test
    fun rejectsSameUidPackageWhenCertDoesNotMatch() {
        val policy = policy(
            identities = listOf(
                CallerPolicy.PackageIdentity("com.mineradio.app", otherCert),
            ),
        )
        val d = policy.evaluate(10004)
        assertFalse(d.allowed)
        assertEquals(CallerPolicy.REASON_CALLER_REJECTED, d.reason)
    }

    @Test
    fun sameUidMultiplePackages_requiresMatchingCertOnAllowedName() {
        val policy = policy(
            identities = listOf(
                CallerPolicy.PackageIdentity("com.other.shared", goodCert),
                CallerPolicy.PackageIdentity("com.mineradio.app", otherCert),
            ),
        )
        // name hit without matching cert → reject
        assertFalse(policy.evaluate(10005).allowed)

        val okPolicy = policy(
            identities = listOf(
                CallerPolicy.PackageIdentity("com.other.shared", otherCert),
                CallerPolicy.PackageIdentity("com.mineradio.app", goodCert),
            ),
        )
        assertTrue(okPolicy.evaluate(10005).allowed)
    }

    @Test
    fun shellAllowedOnlyInDebug() {
        val debug = policy(isDebug = true, allowShell = true, identities = emptyList())
        assertTrue(debug.evaluate(CallerPolicy.SHELL_UID).allowed)

        val release = policy(isDebug = false, allowShell = true, identities = emptyList())
        val d = release.evaluate(CallerPolicy.SHELL_UID)
        assertFalse(d.allowed)
        assertEquals(CallerPolicy.REASON_CALLER_REJECTED, d.reason)
    }

    @Test
    fun emptyUidPackagesRejected() {
        val policy = policy(identities = emptyList())
        assertFalse(policy.evaluate(42).allowed)
    }

    @Test
    fun allowReasonIsStrictTokenForCertAllowlistStamp() {
        // PluginControlProvider.CallerStamp treats reason=="ALLOW" as cert match.
        val policy = policy(
            identities = listOf(
                CallerPolicy.PackageIdentity("com.mineradio.app", goodCert),
            ),
        )
        assertEquals("ALLOW", policy.evaluate(10001).reason)
        assertEquals("SHELL_DEBUG", policy(isDebug = true, identities = emptyList())
            .evaluate(CallerPolicy.SHELL_UID).reason)
    }

    private fun policy(
        identities: List<CallerPolicy.PackageIdentity>,
        isDebug: Boolean = true,
        allowShell: Boolean = true,
    ): CallerPolicy {
        return CallerPolicy(
            allowedCertSha256 = CallerPolicy.normalizeCertSet(listOf(goodCert)),
            isDebugBuild = isDebug,
            allowShellInDebug = allowShell,
            packageIdentitiesForUid = { identities },
        )
    }
}
