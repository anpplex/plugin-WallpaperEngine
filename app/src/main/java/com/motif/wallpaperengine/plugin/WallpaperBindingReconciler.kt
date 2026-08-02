package com.motif.wallpaperengine.plugin

import android.app.WallpaperManager
import android.content.Context

/**
 * WP-08 REFACTOR: sole entry for system wallpaper → bindingState reconciliation.
 *
 * Always re-query WallpaperManager.getWallpaperInfo(); never trust RESULT_OK,
 * memory cache, or Activity result alone. Updates [PluginRuntimeState] only.
 */
object WallpaperBindingReconciler {
    /**
     * @param context any Context that can reach WallpaperManager
     * @param state domain state to update (defaults to process singleton)
     * @param targetComponent expected live wallpaper component; if null uses engine baseline
     */
    fun reconcileFromSystem(
        context: Context,
        state: PluginRuntimeState = PluginProcessRuntime.state,
        targetComponent: String? = null,
    ): BindingState {
        val info = try {
            // Public API marker: WallpaperManager.getWallpaperInfo()
            WallpaperManager.getInstance(context).getWallpaperInfo()
        } catch (_: SecurityException) {
            null
        } catch (_: Exception) {
            null
        }
        val component = info?.component?.flattenToString()
        val target = targetComponent
            ?: state.targetComponent
            ?: "${PluginContract.ENGINE_PACKAGE}/${PluginContract.ENGINE_WALLPAPER_SERVICE}"
        state.reconcileWallpaperInfo(component = component, target = target)
        return state.bindingState
    }

    /**
     * Pure mapping for unit tests (no Android Context).
     * ACTIVE_TARGET only when component matches target.
     */
    fun mapComponentToBinding(component: String?, target: String?): BindingState {
        return when {
            component.isNullOrBlank() -> BindingState.UNBOUND
            target != null && component == target -> BindingState.ACTIVE_TARGET
            else -> BindingState.ACTIVE_OTHER
        }
    }
}
