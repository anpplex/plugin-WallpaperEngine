package com.motif.wallpaperengine.plugin

/**
 * WP-02 caller allowlist for Provider Binder calls.
 *
 * Truth: Binder calling UID + PackageManager package/cert digests.
 * Shell (UID 2000) is debug-only. Release always rejects shell.
 */
class CallerPolicy(
    private val allowedPackages: Set<String> = DEFAULT_ALLOWED_PACKAGES,
    private val allowedCertSha256: Set<String>,
    private val isDebugBuild: Boolean = true,
    private val allowShellInDebug: Boolean = true,
    private val packageIdentitiesForUid: (callingUid: Int) -> List<PackageIdentity>,
) {
    data class PackageIdentity(
        val packageName: String,
        val certSha256: String,
    )

    data class Decision(
        val allowed: Boolean,
        val reason: String,
        val packageName: String? = null,
    )

    fun evaluate(callingUid: Int): Decision {
        if (callingUid == SHELL_UID) {
            return if (isDebugBuild && allowShellInDebug) {
                Decision(allowed = true, reason = "SHELL_DEBUG", packageName = "shell")
            } else {
                rejected(packageName = "shell")
            }
        }

        val identities = packageIdentitiesForUid(callingUid)
        if (identities.isEmpty()) {
            return rejected()
        }

        // Same UID may map to multiple packages — each package is checked independently.
        // Any single package that matches both name allowlist and cert allowlist is enough.
        for (identity in identities) {
            if (identity.packageName !in allowedPackages) {
                continue
            }
            val cert = normalizeCert(identity.certSha256) ?: continue
            if (cert in allowedCertSha256) {
                return Decision(
                    allowed = true,
                    reason = "ALLOW",
                    packageName = identity.packageName,
                )
            }
        }

        // Package name hit without matching cert → still reject (do not allow by name alone).
        return rejected(packageName = identities.firstOrNull()?.packageName)
    }

    private fun rejected(packageName: String? = null): Decision =
        Decision(allowed = false, reason = REASON_CALLER_REJECTED, packageName = packageName)

    companion object {
        const val SHELL_UID = 2000
        const val REASON_CALLER_REJECTED = "CALLER_REJECTED"
        val DEFAULT_ALLOWED_PACKAGES: Set<String> = setOf(
            "com.mineradio.app",
            "com.motif.wallpaperengine",
        )
        private val CERT_SHA256_REGEX = Regex("^[0-9a-f]{64}$")

        fun normalizeCertSet(raw: Collection<String>): Set<String> =
            raw.mapNotNull { normalizeCert(it) }.toSet()

        fun normalizeCert(raw: String?): String? {
            if (raw.isNullOrBlank()) return null
            val cert = raw.trim().lowercase()
            return if (CERT_SHA256_REGEX.matches(cert)) cert else null
        }
    }
}
