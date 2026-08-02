package com.motif.wallpaperengine.plugin

/**
 * WP-08 public apply path controller.
 *
 * Baseline (Android 12 ordinary app):
 * 1. PackageManager resolve WEWallpaperService ComponentName
 * 2. Provider returns one-shot PendingIntent → PluginActionActivity
 * 3. User click → WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER
 * 4. Intent EXTRA_LIVE_WALLPAPER_COMPONENT
 * 5. Persist pendingApplyOperationId / targetComponent / actionEpoch
 * 6. onResume / status → WallpaperManager.getWallpaperInfo() reconcile
 *
 * No non-public wallpaper API / shell as baseline. OEM Lyra/R3 only when public Activity
 * missing AND capability probed → APPLY_PERMISSION_REQUIRED structured fallback.
 */
data class ApplyRequestResult(
    /** Family token for RED/GREEN fixtures (not a second protocol code). */
    val codeFamily: String,
    val code: Int = PluginContract.CODE_OK,
    val message: String? = null,
)

class WallpaperApplyController {
    /**
     * Build public apply user-action request or structured fallback.
     *
     * @param hasPublicActivity whether ACTION_CHANGE_LIVE_WALLPAPER resolve succeeds
     * @param hasOemCapability whether authorized Lyra/R3 OEM capability is present
     */
    fun requestApply(
        hasPublicActivity: Boolean,
        hasOemCapability: Boolean,
    ): ApplyRequestResult {
        if (hasPublicActivity) {
            return ApplyRequestResult(
                codeFamily = "USER_ACTION_CHANGE_LIVE_WALLPAPER",
                code = PluginContract.CODE_USER_ACTION_REQUIRED,
                message = "WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER",
            )
        }
        // Public Activity unreachable.
        return if (hasOemCapability) {
            ApplyRequestResult(
                codeFamily = "APPLY_PERMISSION_REQUIRED",
                code = PluginContract.CODE_APPLY_PERMISSION_REQUIRED,
                message = "APPLY_PERMISSION_REQUIRED structured Lyra/R3 fallback",
            )
        } else {
            // No OEM capability → fail-closed (do not invent shell path).
            ApplyRequestResult(
                codeFamily = "APPLY_PERMISSION_REQUIRED_OR_FAIL_CLOSED",
                code = PluginContract.CODE_APPLY_PERMISSION_REQUIRED,
                message = "public Activity missing; no OEM capability; fail-closed",
            )
        }
    }

    fun publicChangeLiveWallpaperAction(): String =
        "android.service.wallpaper.CHANGE_LIVE_WALLPAPER" // WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER

    fun publicExtraLiveWallpaperComponent(): String =
        "android.service.wallpaper.extra.LIVE_WALLPAPER_COMPONENT" // EXTRA_LIVE_WALLPAPER_COMPONENT

    fun methodApplyCurrent(): String = "apply_current"

    fun methodStop(): String = "stop"
}
