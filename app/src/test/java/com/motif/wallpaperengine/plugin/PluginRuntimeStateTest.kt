package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * WP-08 RED contract: operationState/bindingState + getWallpaperInfo reconciliation.
 * GREEN implements PluginRuntimeState / WallpaperApplyController.
 */
class PluginRuntimeStateTest {
    @Test
    fun bindingActiveTargetOnlyWhenComponentMatches() {
        val state = PluginRuntimeState()
        state.reconcileWallpaperInfo(component = "com.example/.TargetService", target = "com.example/.TargetService")
        assertEquals(BindingState.ACTIVE_TARGET, state.bindingState)
    }

    @Test
    fun bindingNotTargetWhenNullOrOther() {
        val state = PluginRuntimeState()
        state.reconcileWallpaperInfo(component = null, target = "com.example/.TargetService")
        assertEquals(BindingState.UNBOUND, state.bindingState)
        state.reconcileWallpaperInfo(component = "com.other/.Service", target = "com.example/.TargetService")
        assertEquals(BindingState.ACTIVE_OTHER, state.bindingState)
    }

    @Test
    fun stopDoesNotChangeBindingState() {
        val state = PluginRuntimeState()
        state.reconcileWallpaperInfo(component = "com.example/.TargetService", target = "com.example/.TargetService")
        val before = state.bindingState
        state.stop(targetOperationId = "op-1")
        assertEquals(before, state.bindingState)
        assertEquals(OperationState.CANCELLED, state.operationState)
    }

    @Test
    fun applyCurrentCreatesIndependentOperationFromStaged() {
        val state = PluginRuntimeState()
        state.markStaged("op-import")
        val applyOp = state.beginApplyCurrent(fromOperationId = "op-import")
        assertNotEquals("op-import", applyOp)
        assertEquals(OperationState.ENGINE_LAUNCHED, state.operationState)
    }

    @Test
    fun publicActivityMissingYieldsApplyPermissionRequiredOnlyWithOemCapability() {
        val controller = WallpaperApplyController()
        val noOem = controller.requestApply(hasPublicActivity = false, hasOemCapability = false)
        assertEquals("APPLY_PERMISSION_REQUIRED_OR_FAIL_CLOSED", noOem.codeFamily)
        val withOem = controller.requestApply(hasPublicActivity = false, hasOemCapability = true)
        assertEquals("APPLY_PERMISSION_REQUIRED", withOem.codeFamily)
    }

    @Test
    fun concurrentClaimLaunchOnlyOneSucceeds() {
        val state = PluginRuntimeState()
        val a = state.claimLaunch("op-1", actionEpoch = 1)
        val b = state.claimLaunch("op-1", actionEpoch = 1)
        assertEquals(true, a)
        assertEquals(false, b)
    }
}
