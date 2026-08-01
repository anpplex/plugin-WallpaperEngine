package com.motif.wallpaperengine.plugin

/**
 * Immutable protocol-1 validation / response envelope.
 *
 * WP-01: pure data only — no Context, I/O, or Binder.
 */
data class PluginResult(
    val code: Int,
    val message: String? = null,
) {
    val ok: Boolean
        get() = code == PluginContract.CODE_OK

    companion object {
        fun ok(message: String? = null): PluginResult =
            PluginResult(code = PluginContract.CODE_OK, message = message)

        fun of(code: Int, message: String? = null): PluginResult =
            PluginResult(code = code, message = message)
    }
}
