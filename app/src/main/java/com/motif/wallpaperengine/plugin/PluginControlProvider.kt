package com.motif.wallpaperengine.plugin

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Bundle
import android.os.Process
import java.security.MessageDigest

/**
 * Protocol-1 control Provider on process `:we_runtime`.
 *
 * WP-08 queue/apply + WP-10A ping / import_mpkg / renew_action (actionToken).
 * Caller allowlist: Binder UID → package + cert SHA-256 (shell debug-only).
 * Native Mineradio 1.1.7 base: allowlist inject via -PmineradioCallerCertSha256.
 */
class PluginControlProvider : ContentProvider() {
    @Volatile
    internal var callerPolicyOverride: CallerPolicy? = null

    override fun onCreate(): Boolean = true

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
        val ctx = context
            ?: return errorBundle(PluginContract.CODE_INTERNAL_ERROR, "NO_CONTEXT")

        val callingUid = Binder.getCallingUid()
        val policy = callerPolicyOverride ?: buildDefaultCallerPolicy(ctx)
        val decision = policy.evaluate(callingUid)
        if (!decision.allowed) {
            return errorBundle(PluginContract.CODE_CALLER_REJECTED, decision.reason)
        }

        val runtime = PluginProcessRuntime
        val request = extras ?: Bundle()
        // Force unparcel before reads.
        request.size()

        val validation = PluginContract.validate(method, request)
        if (!validation.ok) {
            return errorBundle(validation.code, validation.message)
        }

        val caller = CallerStamp.from(decision, callingUid)
        val out = when (method) {
            PluginContract.METHOD_PING, "ping" -> handlePing()
            PluginContract.METHOD_STATUS, "status" -> handleStatus(runtime, request)
            PluginContract.METHOD_IMPORT_MPKG, "import_mpkg" ->
                handleImportMpkg(runtime, request, caller)
            PluginContract.METHOD_RENEW_ACTION, "renew_action" -> handleRenewAction(runtime, request)
            PluginContract.METHOD_OPEN_LIBRARY, "open_library" -> handleOpenLibrary(request)
            PluginContract.METHOD_APPLY_CURRENT, "apply_current" -> handleApplyCurrent(runtime, request)
            PluginContract.METHOD_NEXT, "next" -> {
                runtime.queue.next()
                okBundle()
            }
            PluginContract.METHOD_PREVIOUS, "previous" -> {
                runtime.queue.previous()
                okBundle()
            }
            PluginContract.METHOD_STOP, "stop" -> {
                val op = request.getString(PluginContract.KEY_OPERATION_ID).orEmpty()
                val target = request.getString(PluginContract.KEY_TARGET_OPERATION_ID).orEmpty()
                runtime.stop(op, target)
                okBundle()
            }
            PluginContract.METHOD_DIAGNOSTICS, "diagnostics" -> handleDiagnostics()
            else -> errorBundle(PluginContract.CODE_BAD_REQUEST, "UNKNOWN_METHOD")
        }

        echoCallId(request, out)
        attachCallerStamp(out, caller)
        // Always project latest runtime snapshot (orthogonal bindingState).
        if (!out.containsKey(PluginContract.KEY_OPERATION_STATE)) {
            out.putString(PluginContract.KEY_OPERATION_STATE, runtime.snapshotOperationState())
        }
        if (!out.containsKey(PluginContract.KEY_BINDING_STATE)) {
            if (context != null) {
                WallpaperBindingReconciler.reconcileFromSystem(context!!)
            }
            out.putString(PluginContract.KEY_BINDING_STATE, runtime.snapshotBindingState())
        }
        out.putInt(PluginContract.KEY_PROTOCOL_VERSION, PluginContract.PROTOCOL_VERSION)
        return out
    }

    /** Identity derived from Binder + CallerPolicy only (never from request extras). */
    internal data class CallerStamp(
        val packageName: String?,
        val uid: Int,
        val certAllowlistMatch: Boolean,
        val reason: String,
    ) {
        companion object {
            fun from(decision: CallerPolicy.Decision, callingUid: Int): CallerStamp {
                val pkg = decision.packageName
                // Shell debug path is never continuous-E3 cert allowlist match.
                val certMatch =
                    decision.allowed &&
                        decision.reason == "ALLOW" &&
                        pkg != null &&
                        pkg != "shell"
                return CallerStamp(
                    packageName = pkg,
                    uid = callingUid,
                    certAllowlistMatch = certMatch,
                    reason = decision.reason,
                )
            }
        }
    }

    private fun attachCallerStamp(out: Bundle, caller: CallerStamp) {
        caller.packageName?.let { out.putString(PluginContract.KEY_CALLER_PACKAGE, it) }
        out.putInt(PluginContract.KEY_CALLER_UID, caller.uid)
        out.putBoolean(PluginContract.KEY_CERT_ALLOWLIST_MATCH, caller.certAllowlistMatch)
    }

    private fun handlePing(): Bundle {
        return okBundle().apply {
            putInt(PluginContract.KEY_RUNTIME_PID, Process.myPid())
            putStringArray("capabilities", PluginContract.METHODS.toTypedArray())
        }
    }

    private fun handleStatus(runtime: PluginProcessRuntime, request: Bundle): Bundle {
        val operationId = request.getString(PluginContract.KEY_OPERATION_ID)
        val ctx = context
        if (ctx != null) {
            WallpaperBindingReconciler.reconcileFromSystem(ctx)
        }
        val out = okBundle()
        out.putInt(PluginContract.KEY_RUNTIME_PID, Process.myPid())
        if (operationId.isNullOrBlank()) {
            out.putString(PluginContract.KEY_OPERATION_STATE, runtime.snapshotOperationState())
            out.putString(PluginContract.KEY_BINDING_STATE, runtime.snapshotBindingState())
            return out
        }
        val rec = runtime.ledger.get(operationId)
        if (rec == null) {
            out.putString(PluginContract.KEY_OPERATION_ID, operationId)
            out.putString(PluginContract.KEY_OPERATION_STATE, "IDLE")
            out.putString(PluginContract.KEY_BINDING_STATE, runtime.snapshotBindingState())
            out.putBoolean(PluginContract.KEY_SOURCE_CONSUMED, false)
            return out
        }
        out.putString(PluginContract.KEY_OPERATION_ID, rec.operationId)
        out.putString(PluginContract.KEY_OPERATION_STATE, rec.operationState)
        out.putString(PluginContract.KEY_BINDING_STATE, runtime.snapshotBindingState())
        out.putInt(PluginContract.KEY_ACTION_EPOCH, rec.actionEpoch)
        out.putBoolean(PluginContract.KEY_SOURCE_CONSUMED, rec.sourceConsumed)
        rec.actionKind?.let { out.putString(PluginContract.KEY_USER_ACTION_KIND, it) }
        rec.sourceUri?.let { out.putString(PluginContract.KEY_SOURCE_OPERATION_ID, rec.operationId) }
        // Ledger-bound caller identity (set at import; not request-forged).
        rec.callerPackage?.let { out.putString(PluginContract.KEY_CALLER_PACKAGE, it) }
        if (rec.callerUid >= 0) {
            out.putInt(PluginContract.KEY_CALLER_UID, rec.callerUid)
        }
        out.putBoolean(PluginContract.KEY_CERT_ALLOWLIST_MATCH, rec.certAllowlistMatch)
        // Never re-echo live actionToken on status (one-shot surface).
        return out
    }

    private fun handleImportMpkg(
        runtime: PluginProcessRuntime,
        request: Bundle,
        caller: CallerStamp,
    ): Bundle {
        val operationId = request.getString(PluginContract.KEY_OPERATION_ID).orEmpty()
        val sourceUri = request.getString(PluginContract.KEY_SOURCE_URI)
        val displayName = request.getString(PluginContract.KEY_DISPLAY_NAME)
        val rec = runtime.ledger.beginImport(
            operationId = operationId,
            sourceUri = sourceUri,
            displayName = displayName,
            callerPackage = caller.packageName,
            callerUid = caller.uid,
            certAllowlistMatch = caller.certAllowlistMatch,
        )
        runtime.state.markStaged(operationId)
        // Domain: import requires user confirm before stage is "consumed" from Mineradio POV.
        // Keep ledger ACTION_PENDING until renew_action.
        return Bundle().apply {
            putInt(PluginContract.KEY_CODE, PluginContract.CODE_USER_ACTION_REQUIRED)
            putString(PluginContract.KEY_OPERATION_ID, rec.operationId)
            putString(PluginContract.KEY_OPERATION_STATE, rec.operationState)
            putInt(PluginContract.KEY_ACTION_EPOCH, rec.actionEpoch)
            putString(PluginContract.KEY_ACTION_TOKEN, rec.actionToken)
            putString(PluginContract.KEY_USER_ACTION_KIND, rec.actionKind)
            putString(PluginContract.KEY_MESSAGE, "confirmUserAction required")
            putBoolean(PluginContract.KEY_SOURCE_CONSUMED, false)
        }
    }

    private fun handleRenewAction(runtime: PluginProcessRuntime, request: Bundle): Bundle {
        val operationId = request.getString(PluginContract.KEY_OPERATION_ID).orEmpty()
        val epoch = if (request.containsKey(PluginContract.KEY_ACTION_EPOCH)) {
            request.getInt(PluginContract.KEY_ACTION_EPOCH)
        } else {
            request.getLong(PluginContract.KEY_ACTION_EPOCH).toInt()
        }
        val token = request.getString(PluginContract.KEY_ACTION_TOKEN)
        val (code, rec) = runtime.ledger.confirmUserAction(operationId, epoch, token)
        val out = Bundle().apply {
            putInt(PluginContract.KEY_CODE, code)
            putString(PluginContract.KEY_OPERATION_ID, operationId)
        }
        if (rec != null) {
            out.putString(PluginContract.KEY_OPERATION_STATE, rec.operationState)
            out.putInt(PluginContract.KEY_ACTION_EPOCH, rec.actionEpoch)
            out.putBoolean(PluginContract.KEY_SOURCE_CONSUMED, rec.sourceConsumed)
            if (code == PluginContract.CODE_OK) {
                runtime.state.markStaged(operationId)
                out.putString(PluginContract.KEY_MESSAGE, "sourceConsumed; Mineradio must revoke sourceUri")
            } else {
                out.putString(PluginContract.KEY_MESSAGE, "ACTION_TOKEN_INVALID_OR_USED")
            }
        } else {
            out.putString(PluginContract.KEY_MESSAGE, "UNKNOWN_OPERATION")
        }
        return out
    }

    private fun handleOpenLibrary(request: Bundle): Bundle {
        val operationId = request.getString(PluginContract.KEY_OPERATION_ID).orEmpty()
        return Bundle().apply {
            putInt(PluginContract.KEY_CODE, PluginContract.CODE_USER_ACTION_REQUIRED)
            putString(PluginContract.KEY_OPERATION_ID, operationId)
            putString(PluginContract.KEY_USER_ACTION_KIND, "OPEN_LIBRARY")
            putString(PluginContract.KEY_MESSAGE, "open BrowseActivity")
        }
    }

    private fun handleApplyCurrent(runtime: PluginProcessRuntime, request: Bundle): Bundle {
        val fromOp = request.getString(PluginContract.KEY_OPERATION_ID).orEmpty()
        if (fromOp.isNotBlank()) {
            runtime.state.beginApplyCurrent(fromOp)
        }
        return Bundle().apply {
            putInt(PluginContract.KEY_CODE, PluginContract.CODE_USER_ACTION_REQUIRED)
            putString(PluginContract.KEY_USER_ACTION_KIND, "APPLY_CURRENT")
            putString(
                PluginContract.KEY_MESSAGE,
                "PluginActionActivity → WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER",
            )
        }
    }

    private fun handleDiagnostics(): Bundle {
        return okBundle().apply {
            putInt(PluginContract.KEY_RUNTIME_PID, Process.myPid())
            putInt("ledgerSize", PluginProcessRuntime.ledger.size())
        }
    }

    private fun buildDefaultCallerPolicy(ctx: Context): CallerPolicy {
        val certProp = readBuildConfigString("MINERADIO_CALLER_CERT_SHA256")
        val debug = readBuildConfigBoolean("DEBUG", default = true)
        val certs = CallerPolicy.normalizeCertSet(
            listOf(certProp).filter { it.isNotBlank() && it != "0".repeat(64) },
        )
        return CallerPolicy(
            allowedCertSha256 = certs,
            isDebugBuild = debug,
            allowShellInDebug = debug,
            packageIdentitiesForUid = { uid -> resolvePackageIdentities(ctx, uid) },
        )
    }

    private fun readBuildConfigString(field: String): String {
        return try {
            val buildConfigClass = Class.forName("com.motif.wallpaperengine.BuildConfig")
            (buildConfigClass.getField(field).get(null) as? String).orEmpty()
        } catch (_: Exception) {
            ""
        }
    }

    private fun readBuildConfigBoolean(field: String, default: Boolean): Boolean {
        return try {
            val buildConfigClass = Class.forName("com.motif.wallpaperengine.BuildConfig")
            buildConfigClass.getField(field).getBoolean(null)
        } catch (_: Exception) {
            default
        }
    }

    private fun resolvePackageIdentities(
        ctx: Context,
        uid: Int,
    ): List<CallerPolicy.PackageIdentity> {
        val pm = ctx.packageManager
        val packages = pm.getPackagesForUid(uid) ?: return emptyList()
        return packages.mapNotNull { pkg ->
            try {
                @Suppress("DEPRECATION")
                val info = pm.getPackageInfo(pkg, PackageManager.GET_SIGNATURES)
                @Suppress("DEPRECATION")
                val sig = info.signatures?.firstOrNull()?.toByteArray() ?: return@mapNotNull null
                val digest = MessageDigest.getInstance("SHA-256").digest(sig)
                val hex = digest.joinToString("") { b -> "%02x".format(b) }
                CallerPolicy.PackageIdentity(pkg, hex)
            } catch (_: Exception) {
                null
            }
        }
    }

    private fun okBundle(): Bundle =
        Bundle().apply { putInt(PluginContract.KEY_CODE, PluginContract.CODE_OK) }

    private fun errorBundle(code: Int, message: String?): Bundle =
        Bundle().apply {
            putInt(PluginContract.KEY_CODE, code)
            if (!message.isNullOrBlank()) putString(PluginContract.KEY_MESSAGE, message)
        }

    private fun echoCallId(request: Bundle, result: Bundle) {
        val callId = request.getString(PluginContract.KEY_CALL_ID)
        if (!callId.isNullOrBlank() && !result.containsKey(PluginContract.KEY_CALL_ID)) {
            result.putString(PluginContract.KEY_CALL_ID, callId)
        }
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0
}
