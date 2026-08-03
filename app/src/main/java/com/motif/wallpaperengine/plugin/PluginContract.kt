package com.motif.wallpaperengine.plugin

import android.os.Bundle

/**
 * Protocol 1 contract: authority, methods, field keys, return codes,
 * orthogonal states, and pure request validation.
 *
 * Must not access Android Context, filesystem, or network.
 * Spec: WALLPAPER-PLUGIN-DEVELOPMENT §3.2–§3.5 (frozen).
 */
object PluginContract {
    const val PROTOCOL_VERSION = 1
    const val AUTHORITY = "com.motif.wallpaperengine.control"
    const val ENGINE_PACKAGE = "io.wallpaperengine.weclient"
    const val ENGINE_BROWSE_ACTIVITY = "io.wallpaperengine.weclient.BrowseActivity"
    // First-version fixed baseline; each target official APK must re-resolve.
    const val ENGINE_WALLPAPER_SERVICE = "io.wallpaperengine.weclient.WEWallpaperService"

    // --- §3.2 methods --------------------------------------------------------

    const val METHOD_PING = "ping"
    const val METHOD_STATUS = "status"
    const val METHOD_RENEW_ACTION = "renew_action"
    const val METHOD_IMPORT_MPKG = "import_mpkg"
    const val METHOD_OPEN_LIBRARY = "open_library"
    const val METHOD_APPLY_CURRENT = "apply_current"
    const val METHOD_NEXT = "next"
    const val METHOD_PREVIOUS = "previous"
    const val METHOD_STOP = "stop"
    const val METHOD_DIAGNOSTICS = "diagnostics"

    val METHODS: Set<String> = setOf(
        METHOD_PING,
        METHOD_STATUS,
        METHOD_RENEW_ACTION,
        METHOD_IMPORT_MPKG,
        METHOD_OPEN_LIBRARY,
        METHOD_APPLY_CURRENT,
        METHOD_NEXT,
        METHOD_PREVIOUS,
        METHOD_STOP,
        METHOD_DIAGNOSTICS,
    )

    /** Methods that require a non-blank operationId at the validate layer. */
    private val MUTATION_METHODS: Set<String> = setOf(
        METHOD_RENEW_ACTION,
        METHOD_IMPORT_MPKG,
        METHOD_OPEN_LIBRARY,
        METHOD_APPLY_CURRENT,
        METHOD_NEXT,
        METHOD_PREVIOUS,
        METHOD_STOP,
    )

    // --- §3.3 fixed field keys -----------------------------------------------

    const val KEY_PROTOCOL_VERSION = "protocolVersion"
    const val KEY_CALL_ID = "callId"
    const val KEY_OPERATION_ID = "operationId"
    const val KEY_TARGET_OPERATION_ID = "targetOperationId"
    const val KEY_ACTION_EPOCH = "actionEpoch"
    /** Random one-shot action token for HMI confirmUserAction (not PendingIntent). */
    const val KEY_ACTION_TOKEN = "actionToken"
    const val KEY_ACTIVE_OPERATION_ID = "activeOperationId"
    const val KEY_COMPLETED_OPERATION_IDS = "completedOperationIds"
    const val KEY_CODE = "code"
    const val KEY_MESSAGE = "message"
    const val KEY_OPERATION_STATE = "operationState"
    const val KEY_BINDING_STATE = "bindingState"
    const val KEY_SOURCE_URI = "sourceUri"
    const val KEY_SOURCE_CONSUMED = "sourceConsumed"
    const val KEY_SOURCE_OPERATION_ID = "sourceOperationId"
    const val KEY_DISPLAY_NAME = "displayName"
    const val KEY_BYTES = "bytes"
    const val KEY_SHA256 = "sha256"
    const val KEY_RUNTIME_PID = "runtimePid"
    /** Binder caller package that passed CallerPolicy (null/shell → "shell"). */
    const val KEY_CALLER_PACKAGE = "callerPackage"
    /** Binder calling UID (process identity; not forged by extras). */
    const val KEY_CALLER_UID = "callerUid"
    /** True when package+cert allowlist matched (shell debug is false for continuous E3). */
    const val KEY_CERT_ALLOWLIST_MATCH = "certAllowlistMatch"
    const val KEY_ENGINE_INSTALLED = "engineInstalled"
    const val KEY_ENGINE_VERSION = "engineVersion"
    const val KEY_ACTIVE_PACKAGE = "activePackage"
    const val KEY_ACTIVE_COMPONENT = "activeComponent"
    const val KEY_LAST_ERROR = "lastError"
    /** Native Bundle only; never serialized to WebView. */
    const val KEY_USER_ACTION = "userAction"
    const val KEY_USER_ACTION_KIND = "userActionKind"
    const val KEY_USER_ACTION_EXPIRES_AT = "userActionExpiresAt"
    const val KEY_FALLBACK_ACTION = "fallbackAction"

    // --- §3.4 return codes ---------------------------------------------------

    const val CODE_OK = 0
    const val CODE_ACCEPTED = 10
    const val CODE_USER_ACTION_REQUIRED = 20
    const val CODE_BAD_REQUEST = 40
    const val CODE_CALLER_REJECTED = 41
    const val CODE_PROTOCOL_MISMATCH = 42
    const val CODE_ENGINE_NOT_INSTALLED = 43
    const val CODE_SOURCE_UNREADABLE = 44
    const val CODE_PACKAGE_INVALID = 45
    const val CODE_USER_LOCKED = 46
    const val CODE_BUSY = 50
    const val CODE_TIMEOUT = 51
    const val CODE_APPLY_PERMISSION_REQUIRED = 52
    const val CODE_ACTION_TOKEN_EXPIRED = 53
    const val CODE_STAGING_QUOTA_EXCEEDED = 54
    const val CODE_INTERNAL_ERROR = 60

    val CODES: Set<Int> = setOf(
        CODE_OK,
        CODE_ACCEPTED,
        CODE_USER_ACTION_REQUIRED,
        CODE_BAD_REQUEST,
        CODE_CALLER_REJECTED,
        CODE_PROTOCOL_MISMATCH,
        CODE_ENGINE_NOT_INSTALLED,
        CODE_SOURCE_UNREADABLE,
        CODE_PACKAGE_INVALID,
        CODE_USER_LOCKED,
        CODE_BUSY,
        CODE_TIMEOUT,
        CODE_APPLY_PERMISSION_REQUIRED,
        CODE_ACTION_TOKEN_EXPIRED,
        CODE_STAGING_QUOTA_EXCEEDED,
        CODE_INTERNAL_ERROR,
    )

    // --- §3.5 orthogonal states ----------------------------------------------

    val OPERATION_STATES: Set<String> = setOf(
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

    val BINDING_STATES: Set<String> = setOf(
        "UNKNOWN",
        "UNBOUND",
        "ACTIVE_TARGET",
        "ACTIVE_OTHER",
    )

    /**
     * Pure request validation for protocol 1.
     *
     * Does not mutate [extras]. Does not perform I/O or IPC.
     * Returns [CODE_OK] only when identity/method/required fields are valid;
     * business execution is out of scope for WP-01.
     */
    fun validate(method: String, extras: Bundle): PluginResult {
        // Protocol version first: unsupported / missing versions must not proceed.
        val version = readProtocolVersion(extras)
        if (version != PROTOCOL_VERSION) {
            return PluginResult.of(CODE_PROTOCOL_MISMATCH, "PROTOCOL_MISMATCH")
        }

        requireNonBlank(extras, KEY_CALL_ID, "MISSING_CALL_ID")?.let { return it }

        if (method !in METHODS) {
            return badRequest("UNKNOWN_METHOD")
        }

        if (method in MUTATION_METHODS) {
            requireNonBlank(extras, KEY_OPERATION_ID, "MISSING_OPERATION_ID")?.let { return it }
        }

        return when (method) {
            METHOD_RENEW_ACTION -> validateRenewAction(extras)
            METHOD_STOP -> validateStop(extras)
            METHOD_IMPORT_MPKG -> validateImportMpkg(extras)
            else -> PluginResult.ok()
        }
    }

    // --- pure validation helpers (no I/O, no mutation of extras) -------------

    private fun readProtocolVersion(extras: Bundle): Int {
        return if (extras.containsKey(KEY_PROTOCOL_VERSION)) {
            extras.getInt(KEY_PROTOCOL_VERSION)
        } else {
            Int.MIN_VALUE
        }
    }

    private fun validateRenewAction(extras: Bundle): PluginResult {
        if (!extras.containsKey(KEY_ACTION_EPOCH)) {
            return badRequest("MISSING_ACTION_EPOCH")
        }
        return PluginResult.ok()
    }

    private fun validateStop(extras: Bundle): PluginResult {
        requireNonBlank(extras, KEY_TARGET_OPERATION_ID, "MISSING_TARGET_OPERATION_ID")
            ?.let { return it }
        return PluginResult.ok()
    }

    private fun validateImportMpkg(extras: Bundle): PluginResult {
        requireNonBlank(extras, KEY_SOURCE_URI, "MISSING_SOURCE_URI")?.let { return it }
        requireNonBlank(extras, KEY_DISPLAY_NAME, "MISSING_DISPLAY_NAME")?.let { return it }
        if (!extras.containsKey(KEY_BYTES)) {
            return badRequest("MISSING_BYTES")
        }
        if (extras.getLong(KEY_BYTES) <= 0L) {
            return badRequest("INVALID_BYTES")
        }
        requireNonBlank(extras, KEY_SHA256, "MISSING_SHA256")?.let { return it }
        return PluginResult.ok()
    }

    /** Returns a BAD_REQUEST result when the string key is null/blank; otherwise null. */
    private fun requireNonBlank(
        extras: Bundle,
        key: String,
        message: String,
    ): PluginResult? {
        val value = extras.getString(key)
        return if (value.isNullOrBlank()) badRequest(message) else null
    }

    private fun badRequest(message: String): PluginResult =
        PluginResult.of(CODE_BAD_REQUEST, message)
}
