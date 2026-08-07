package com.motif.wallpaperengine.plugin

import android.app.Activity
import android.os.Bundle

/**
 * WP-12C experimental: embedded preview Activity shell.
 *
 * Placeholder registration target for the embedded runtime path.
 * No rendering, no official WE client launch — full preview lands in WP-12D+.
 */
class EmbeddedPreviewActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Experimental shell only — no UI surface yet.
    }
}
