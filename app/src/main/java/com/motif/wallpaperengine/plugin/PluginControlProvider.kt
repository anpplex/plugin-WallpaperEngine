package com.motif.wallpaperengine.plugin

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.Bundle

/**
 * WP-08 ContentProvider control surface (protocol 1 authority).
 *
 * REFACTOR: uses [PluginProcessRuntime] only — no private RuntimeState/Queue.
 * status always re-reconciles via [WallpaperBindingReconciler] when Context available.
 *
 * Methods: apply_current, next, previous, stop, status.
 */
class PluginControlProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
        val runtime = PluginProcessRuntime
        val out = Bundle()
        out.putInt(PluginContract.KEY_PROTOCOL_VERSION, PluginContract.PROTOCOL_VERSION)

        when (method) {
            PluginContract.METHOD_APPLY_CURRENT,
            "apply_current",
            -> {
                // code=20 + PendingIntent → PluginActionActivity →
                // WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER + EXTRA_LIVE_WALLPAPER_COMPONENT
                // claimLaunch serializes concurrent UI.
                val fromOp = extras?.getString(PluginContract.KEY_OPERATION_ID).orEmpty()
                if (fromOp.isNotBlank()) {
                    runtime.state.beginApplyCurrent(fromOp)
                }
                out.putInt(PluginContract.KEY_CODE, PluginContract.CODE_USER_ACTION_REQUIRED)
                out.putString(PluginContract.KEY_USER_ACTION_KIND, "APPLY_CURRENT")
                out.putString(
                    PluginContract.KEY_MESSAGE,
                    "PluginActionActivity → WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER",
                )
            }
            PluginContract.METHOD_NEXT, "next" -> {
                runtime.queue.next()
                out.putInt(PluginContract.KEY_CODE, PluginContract.CODE_OK)
            }
            PluginContract.METHOD_PREVIOUS, "previous" -> {
                runtime.queue.previous()
                out.putInt(PluginContract.KEY_CODE, PluginContract.CODE_OK)
            }
            PluginContract.METHOD_STOP, "stop" -> {
                val op = extras?.getString(PluginContract.KEY_OPERATION_ID).orEmpty()
                val target = extras?.getString(PluginContract.KEY_TARGET_OPERATION_ID).orEmpty()
                runtime.stop(op, target)
                // stop must not change bindingState (orthogonal)
                out.putInt(PluginContract.KEY_CODE, PluginContract.CODE_OK)
            }
            PluginContract.METHOD_STATUS, "status" -> {
                // Always re-query getWallpaperInfo via single reconciler entry
                val ctx = context
                if (ctx != null) {
                    WallpaperBindingReconciler.reconcileFromSystem(ctx)
                }
                out.putInt(PluginContract.KEY_CODE, PluginContract.CODE_OK)
            }
            else -> {
                val fallback = runtime.applyController.requestApply(
                    hasPublicActivity = false,
                    hasOemCapability = false,
                )
                out.putInt(PluginContract.KEY_CODE, fallback.code)
                out.putString(PluginContract.KEY_FALLBACK_ACTION, fallback.codeFamily)
                if (fallback.code == PluginContract.CODE_APPLY_PERMISSION_REQUIRED) {
                    out.putString(PluginContract.KEY_MESSAGE, "APPLY_PERMISSION_REQUIRED")
                }
            }
        }

        out.putString(PluginContract.KEY_OPERATION_STATE, runtime.snapshotOperationState())
        out.putString(PluginContract.KEY_BINDING_STATE, runtime.snapshotBindingState())
        return out
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
