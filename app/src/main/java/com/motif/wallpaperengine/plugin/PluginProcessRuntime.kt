package com.motif.wallpaperengine.plugin

/**
 * WP-08 REFACTOR: single process-scoped owner of queue + operation/binding state.
 *
 * Activity lifecycle and Provider must not each hold a private RuntimeState —
 * that would create a second source of truth. All status/apply/stop transitions
 * and getWallpaperInfo reconciliation go through [state] / [queue] here.
 */
object PluginProcessRuntime {
    val state: PluginRuntimeState = PluginRuntimeState()
    val queue: WallpaperQueue = WallpaperQueue()
    val applyController: WallpaperApplyController = WallpaperApplyController()
    /** WP-10A: import_mpkg / renew_action actionToken ledger (process-scoped). */
    val ledger: PluginOperationLedger = PluginOperationLedger()

    /**
     * stop: cancel operation + queue work; bindingState is orthogonal (unchanged).
     */
    fun stop(operationId: String, targetOperationId: String) {
        state.stop(targetOperationId)
        queue.stop(operationId, targetOperationId)
    }

    /**
     * Single status projection from domain state (no second cache).
     */
    fun snapshotOperationState(): String = state.operationState.name

    fun snapshotBindingState(): String = state.bindingState.name
}
