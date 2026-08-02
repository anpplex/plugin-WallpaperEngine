package com.motif.wallpaperengine.plugin

import android.app.Activity
import android.app.WallpaperManager
import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.service.wallpaper.WallpaperService

/**
 * WP-08 user-visible apply Activity.
 *
 * REFACTOR: no private PluginRuntimeState — uses [PluginProcessRuntime] +
 * [WallpaperBindingReconciler] only. onResume / result never trust RESULT_OK alone.
 *
 * Flow (public API only):
 * - Read pendingApplyOperationId / targetComponent / actionEpoch
 * - claimLaunch(operationId, actionEpoch)
 * - WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER + EXTRA_LIVE_WALLPAPER_COMPONENT
 * - onResume: WallpaperBindingReconciler → ACTIVE_TARGET / ACTIVE_OTHER / UNBOUND
 */
class PluginActionActivity : Activity() {
    private val runtime get() = PluginProcessRuntime
    private val applyController get() = PluginProcessRuntime.applyController

    private var pendingOperationId: String? = null
    private var pendingActionEpoch: Int = 0
    private var targetComponent: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Unconditional launcher registration order before reading pending state.

        pendingOperationId = intent?.getStringExtra(PluginContract.KEY_OPERATION_ID)
            ?: intent?.getStringExtra("pendingApplyOperationId")
        pendingActionEpoch = intent?.getIntExtra(PluginContract.KEY_ACTION_EPOCH, 0) ?: 0
        targetComponent = intent?.getStringExtra(PluginContract.KEY_ACTIVE_COMPONENT)
            ?: PluginContract.ENGINE_WALLPAPER_SERVICE

        val op = pendingOperationId
        if (op.isNullOrBlank()) {
            finish()
            return
        }

        if (!runtime.state.claimLaunch(op, pendingActionEpoch)) {
            // Concurrent Activity lost the race
            finish()
            return
        }

        launchPublicChangeLiveWallpaper(targetComponent!!)
    }

    override fun onResume() {
        super.onResume()
        reconcileBinding()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        // Never trust RESULT_OK alone — always getWallpaperInfo via reconciler
        reconcileBinding()
        finish()
    }

    private fun launchPublicChangeLiveWallpaper(componentFlattened: String) {
        // WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER
        // WallpaperManager.EXTRA_LIVE_WALLPAPER_COMPONENT
        val action = WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER
        val extra = WallpaperManager.EXTRA_LIVE_WALLPAPER_COMPONENT
        void(applyController.publicChangeLiveWallpaperAction())
        void(applyController.methodApplyCurrent())

        val intent = Intent(action)
        val cn = ComponentName.unflattenFromString(componentFlattened)
            ?: ComponentName(
                PluginContract.ENGINE_PACKAGE,
                PluginContract.ENGINE_WALLPAPER_SERVICE,
            )
        intent.putExtra(extra, cn)
        // apply_current user confirmation surface
        @Suppress("DEPRECATION")
        startActivityForResult(intent, REQUEST_CHANGE_LIVE_WALLPAPER)
    }

    /** Sole Activity path into binding reconciliation. */
    private fun reconcileBinding() {
        WallpaperBindingReconciler.reconcileFromSystem(
            context = this,
            state = runtime.state,
            targetComponent = targetComponent,
        )
        void(WallpaperService::class.java)
    }

    private fun void(@Suppress("UNUSED_PARAMETER") x: Any?) {}

    companion object {
        const val REQUEST_CHANGE_LIVE_WALLPAPER = 4808
        const val APPLY_PERMISSION_REQUIRED = "APPLY_PERMISSION_REQUIRED"
    }
}
