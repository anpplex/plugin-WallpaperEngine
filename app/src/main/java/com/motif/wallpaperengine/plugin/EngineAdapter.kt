package com.motif.wallpaperengine.plugin

/**
 * WP-12C experimental: pure engine-path adapter contract (protocol 1).
 *
 * Resolves which runtime path (official WE client package vs embedded) a
 * method should use. No Context, I/O, Binder, or package-manager probes.
 *
 * Fail-closed signatures (stable for host harness):
 * - [FAILURE_UNKNOWN_METHOD]
 * - [FAILURE_CALLER_APPENDED_ARGS]
 * - [FAILURE_FALLBACK_MASQUERADE] (owned by [EmbeddedEngineAdapter])
 */
interface EngineAdapter {
    fun resolve(method: String, extras: Map<String, Any?>): AdapterResult

    companion object {
        const val RUNTIME_MODE_OFFICIAL = "OFFICIAL"
        const val RUNTIME_MODE_EMBEDDED = "EMBEDDED"

        /** Caller requests embedded PASS; must not silently fall back to official. */
        const val KEY_REQUIRE_EMBEDDED = "requireEmbedded"

        const val FAILURE_UNKNOWN_METHOD = "UNKNOWN_METHOD"
        const val FAILURE_CALLER_APPENDED_ARGS = "CALLER_APPENDED_ARGS"
        const val FAILURE_FALLBACK_MASQUERADE = "FALLBACK_MASQUERADE"

        /** Official WE client package (must match [PluginContract.ENGINE_PACKAGE]). */
        val OFFICIAL_ENGINE_PACKAGE: String = PluginContract.ENGINE_PACKAGE

        /** Official live-wallpaper service (must match [PluginContract.ENGINE_WALLPAPER_SERVICE]). */
        val OFFICIAL_WALLPAPER_SERVICE: String = PluginContract.ENGINE_WALLPAPER_SERVICE

        /**
         * Allowlisted request keys for adapter [resolve].
         * Any key outside this set is [FAILURE_CALLER_APPENDED_ARGS].
         */
        val ALLOWED_EXTRA_KEYS: Set<String> = setOf(
            PluginContract.KEY_PROTOCOL_VERSION,
            PluginContract.KEY_CALL_ID,
            PluginContract.KEY_OPERATION_ID,
            PluginContract.KEY_TARGET_OPERATION_ID,
            PluginContract.KEY_ACTION_EPOCH,
            PluginContract.KEY_ACTION_TOKEN,
            PluginContract.KEY_SOURCE_URI,
            PluginContract.KEY_DISPLAY_NAME,
            PluginContract.KEY_BYTES,
            PluginContract.KEY_SHA256,
            KEY_REQUIRE_EMBEDDED,
        )

        /** Methods that select an engine runtime path (official package or embedded). */
        val ENGINE_METHODS: Set<String> = setOf(
            PluginContract.METHOD_IMPORT_MPKG,
            PluginContract.METHOD_OPEN_LIBRARY,
            PluginContract.METHOD_APPLY_CURRENT,
            PluginContract.METHOD_NEXT,
            PluginContract.METHOD_PREVIOUS,
            PluginContract.METHOD_STOP,
            PluginContract.METHOD_RENEW_ACTION,
        )

        fun requireEmbedded(extras: Map<String, Any?>): Boolean {
            return when (val v = extras[KEY_REQUIRE_EMBEDDED]) {
                null -> false
                is Boolean -> v
                is String -> v.equals("true", ignoreCase = true) || v == "1"
                is Number -> v.toInt() != 0
                else -> false
            }
        }

        fun rejectUnknownMethod(runtimeMode: String = RUNTIME_MODE_OFFICIAL): AdapterResult =
            AdapterResult.fail(
                code = PluginContract.CODE_BAD_REQUEST,
                failureSignature = FAILURE_UNKNOWN_METHOD,
                runtimeMode = runtimeMode,
                enginePackage = OFFICIAL_ENGINE_PACKAGE,
                wallpaperService = OFFICIAL_WALLPAPER_SERVICE,
            )

        fun rejectCallerAppendedArgs(runtimeMode: String = RUNTIME_MODE_OFFICIAL): AdapterResult =
            AdapterResult.fail(
                code = PluginContract.CODE_BAD_REQUEST,
                failureSignature = FAILURE_CALLER_APPENDED_ARGS,
                runtimeMode = runtimeMode,
                enginePackage = OFFICIAL_ENGINE_PACKAGE,
                wallpaperService = OFFICIAL_WALLPAPER_SERVICE,
            )

        fun findCallerAppendedKeys(extras: Map<String, Any?>): Set<String> =
            extras.keys.filterNot { it in ALLOWED_EXTRA_KEYS }.toSet()
    }
}

/**
 * Immutable resolve envelope for [EngineAdapter.resolve].
 *
 * [runtimeMode] is OFFICIAL or EMBEDDED. Failures never claim a successful
 * embedded PASS when the official package was selected.
 */
data class AdapterResult(
    val code: Int,
    val message: String? = null,
    val runtimeMode: String,
    val enginePackage: String,
    val wallpaperService: String,
    val failureSignature: String? = null,
) {
    val ok: Boolean
        get() = code == PluginContract.CODE_OK

    companion object {
        fun ok(
            runtimeMode: String,
            enginePackage: String,
            wallpaperService: String,
            message: String? = null,
        ): AdapterResult =
            AdapterResult(
                code = PluginContract.CODE_OK,
                message = message,
                runtimeMode = runtimeMode,
                enginePackage = enginePackage,
                wallpaperService = wallpaperService,
                failureSignature = null,
            )

        fun fail(
            code: Int,
            failureSignature: String,
            runtimeMode: String,
            enginePackage: String,
            wallpaperService: String,
        ): AdapterResult =
            AdapterResult(
                code = code,
                message = failureSignature,
                runtimeMode = runtimeMode,
                enginePackage = enginePackage,
                wallpaperService = wallpaperService,
                failureSignature = failureSignature,
            )
    }
}

/**
 * Default / official path: always selects [PluginContract.ENGINE_PACKAGE].
 * Never claims [EngineAdapter.RUNTIME_MODE_EMBEDDED].
 */
class OfficialEngineAdapter : EngineAdapter {
    override fun resolve(method: String, extras: Map<String, Any?>): AdapterResult {
        val appended = EngineAdapter.findCallerAppendedKeys(extras)
        if (appended.isNotEmpty()) {
            return EngineAdapter.rejectCallerAppendedArgs(EngineAdapter.RUNTIME_MODE_OFFICIAL)
        }
        if (method !in PluginContract.METHODS) {
            return EngineAdapter.rejectUnknownMethod(EngineAdapter.RUNTIME_MODE_OFFICIAL)
        }
        return AdapterResult.ok(
            runtimeMode = EngineAdapter.RUNTIME_MODE_OFFICIAL,
            enginePackage = EngineAdapter.OFFICIAL_ENGINE_PACKAGE,
            wallpaperService = EngineAdapter.OFFICIAL_WALLPAPER_SERVICE,
            message = "OFFICIAL",
        )
    }
}
