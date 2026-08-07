package com.motif.wallpaperengine.plugin

/**
 * WP-12C experimental: embedded runtime adapter with official fallback isolation.
 *
 * Active only when [embeddedRuntimeEnabled] is explicitly true. Default is off:
 * resolve delegates to [official] and never claims EMBEDDED.
 *
 * Fail-closed:
 * - unknown method → [EngineAdapter.FAILURE_UNKNOWN_METHOD]
 * - caller-appended extra keys → [EngineAdapter.FAILURE_CALLER_APPENDED_ARGS]
 * - [EngineAdapter.KEY_REQUIRE_EMBEDDED] true while embedded path unavailable
 *   (flag false) → [EngineAdapter.FAILURE_FALLBACK_MASQUERADE] (no silent
 *   official PASS while caller requested embedded)
 */
class EmbeddedEngineAdapter(
    private val embeddedRuntimeEnabled: Boolean = false,
    private val official: EngineAdapter = OfficialEngineAdapter(),
) : EngineAdapter {

    override fun resolve(method: String, extras: Map<String, Any?>): AdapterResult {
        // Shared allowlist / method gates before any path selection.
        val appended = EngineAdapter.findCallerAppendedKeys(extras)
        if (appended.isNotEmpty()) {
            return EngineAdapter.rejectCallerAppendedArgs(selectedModeLabel())
        }
        if (method !in PluginContract.METHODS) {
            return EngineAdapter.rejectUnknownMethod(selectedModeLabel())
        }

        val wantsEmbedded = EngineAdapter.requireEmbedded(extras)

        if (!embeddedRuntimeEnabled) {
            // Official default. Caller that required embedded PASS must not get
            // a successful official result (fallback masquerade).
            if (wantsEmbedded) {
                return AdapterResult.fail(
                    code = PluginContract.CODE_BAD_REQUEST,
                    failureSignature = EngineAdapter.FAILURE_FALLBACK_MASQUERADE,
                    runtimeMode = EngineAdapter.RUNTIME_MODE_OFFICIAL,
                    enginePackage = EngineAdapter.OFFICIAL_ENGINE_PACKAGE,
                    wallpaperService = EngineAdapter.OFFICIAL_WALLPAPER_SERVICE,
                )
            }
            return official.resolve(method, extras)
        }

        // Embedded path explicitly enabled — methods that would use the engine
        // report runtimeMode=EMBEDDED with this package's experimental identity.
        if (method in EngineAdapter.ENGINE_METHODS) {
            return AdapterResult.ok(
                runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
                enginePackage = EMBEDDED_ENGINE_PACKAGE,
                wallpaperService = EMBEDDED_WALLPAPER_SERVICE,
                message = "EMBEDDED",
            )
        }

        // Non-engine methods (ping / status / diagnostics) still surface that
        // the embedded experimental flag is on, without claiming official WE.
        return AdapterResult.ok(
            runtimeMode = EngineAdapter.RUNTIME_MODE_EMBEDDED,
            enginePackage = EMBEDDED_ENGINE_PACKAGE,
            wallpaperService = EMBEDDED_WALLPAPER_SERVICE,
            message = "EMBEDDED",
        )
    }

    private fun selectedModeLabel(): String =
        if (embeddedRuntimeEnabled) {
            EngineAdapter.RUNTIME_MODE_EMBEDDED
        } else {
            EngineAdapter.RUNTIME_MODE_OFFICIAL
        }

    companion object {
        /** Plugin applicationId; embedded path never points at official WE client. */
        const val EMBEDDED_ENGINE_PACKAGE = "com.motif.wallpaperengine"

        /**
         * Experimental preview / bridge service identity for embedded path.
         * Distinct from [PluginContract.ENGINE_WALLPAPER_SERVICE].
         */
        const val EMBEDDED_WALLPAPER_SERVICE =
            "com.motif.wallpaperengine.wallpaper.WeBridgeWallpaperService"
    }
}
