package com.motif.wallpaperengine.wallpaper

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.service.wallpaper.WallpaperService
import android.view.SurfaceHolder

/**
 * 占位 Live Wallpaper：证明车机绑定链路。
 * 后续替换为：官方 Scene 引擎桥 / 视频引擎 / 共享 Motif 播放器。
 */
class WeBridgeWallpaperService : WallpaperService() {
    override fun onCreateEngine(): Engine = BridgeEngine()

    private inner class BridgeEngine : Engine() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 48f
        }

        override fun onVisibilityChanged(visible: Boolean) {
            if (visible) drawFrame()
        }

        override fun onSurfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
            drawFrame()
        }

        private fun drawFrame() {
            val holder = surfaceHolder
            var canvas: Canvas? = null
            try {
                canvas = holder.lockCanvas()
                canvas?.drawColor(Color.rgb(16, 24, 48))
                canvas?.drawText("Motif WE · bridge", 64f, 128f, paint)
                canvas?.drawText("WallpaperEngine subproject", 64f, 200f, paint)
            } catch (_: Exception) {
            } finally {
                if (canvas != null) {
                    try {
                        holder.unlockCanvasAndPost(canvas)
                    } catch (_: Exception) {
                    }
                }
            }
        }
    }
}
