package com.motif.wallpaperengine.plugin

/**
 * WP-08 orthogonal operationState / bindingState machine.
 *
 * Pure domain logic: no second repository; status/apply/stop transitions only.
 * WallpaperManager.getWallpaperInfo() results are fed in via [reconcileWallpaperInfo].
 */
enum class OperationState {
    IDLE,
    ACTION_PENDING,
    IMPORTING,
    STAGED,
    ENGINE_ACTION_PENDING,
    ENGINE_LAUNCHED,
    PREVIEW_READY,
    APPLY_ACTION_PENDING,
    APPLY_ACTION_LAUNCHED,
    FAILED,
    CANCELLED,
}

enum class BindingState {
    UNKNOWN,
    UNBOUND,
    ACTIVE_TARGET,
    ACTIVE_OTHER,
}

class PluginRuntimeState {
    @Volatile
    var operationState: OperationState = OperationState.IDLE
        private set

    @Volatile
    var bindingState: BindingState = BindingState.UNKNOWN
        private set

    @Volatile
    var activeOperationId: String? = null
        private set

    @Volatile
    var pendingApplyOperationId: String? = null
        private set

    @Volatile
    var targetComponent: String? = null
        private set

    @Volatile
    var actionEpoch: Int = 0
        private set

    private val launchClaims = HashSet<String>()
    private val lock = Any()

    fun markStaged(operationId: String) {
        synchronized(lock) {
            activeOperationId = operationId
            operationState = OperationState.STAGED
        }
    }

    /**
     * apply_current creates an independent apply operation from STAGED/ENGINE_LAUNCHED/PREVIEW_READY.
     */
    fun beginApplyCurrent(fromOperationId: String): String {
        synchronized(lock) {
            val applyOp = "apply-$fromOperationId-${System.nanoTime()}"
            pendingApplyOperationId = applyOp
            activeOperationId = applyOp
            operationState = OperationState.ENGINE_LAUNCHED
            actionEpoch += 1
            return applyOp
        }
    }

    /**
     * stop cancels unfinished work; must NOT change bindingState.
     */
    fun stop(targetOperationId: String) {
        synchronized(lock) {
            // bindingState intentionally unchanged
            operationState = OperationState.CANCELLED
            if (pendingApplyOperationId == targetOperationId) {
                pendingApplyOperationId = null
            }
            launchClaims.remove(claimKey(targetOperationId, actionEpoch))
        }
    }

    /**
     * Concurrent claimLaunch: only one success per operationId+actionEpoch.
     */
    fun claimLaunch(operationId: String, actionEpoch: Int): Boolean {
        synchronized(lock) {
            val key = claimKey(operationId, actionEpoch)
            if (launchClaims.contains(key)) return false
            launchClaims.add(key)
            this.actionEpoch = actionEpoch
            pendingApplyOperationId = operationId
            operationState = OperationState.APPLY_ACTION_LAUNCHED
            return true
        }
    }

    /**
     * Reconcile against WallpaperManager.getWallpaperInfo() component name.
     * Prefer [WallpaperBindingReconciler.reconcileFromSystem] from Activity/Provider —
     * this method is the single domain write for bindingState (no second truth).
     * Target match → ACTIVE_TARGET; null → UNBOUND; other → ACTIVE_OTHER.
     */
    fun reconcileWallpaperInfo(component: String?, target: String?) {
        // Marker for capacity contracts: getWallpaperInfo
        synchronized(lock) {
            targetComponent = target
            // Single mapping shared with WallpaperBindingReconciler.mapComponentToBinding
            bindingState = WallpaperBindingReconciler.mapComponentToBinding(component, target)
        }
    }

    fun markFailed(message: String? = null) {
        synchronized(lock) {
            operationState = OperationState.FAILED
            // message retained by caller ledger; no second store here
            void(message)
        }
    }

    fun markPreviewReady() {
        synchronized(lock) {
            operationState = OperationState.PREVIEW_READY
        }
    }

    private fun claimKey(operationId: String, epoch: Int): String = "$operationId\u0000$epoch"

    private fun void(@Suppress("UNUSED_PARAMETER") x: Any?) {}
}
