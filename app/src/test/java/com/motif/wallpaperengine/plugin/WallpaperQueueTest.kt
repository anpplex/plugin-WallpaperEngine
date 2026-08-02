package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * WP-08 RED contract: WallpaperQueue capacity.
 * GREEN implements WallpaperQueue; RED expects compile/link failure until then.
 */
class WallpaperQueueTest {
    @Test
    fun emptyQueue() {
        val q = WallpaperQueue()
        assertTrue(q.isEmpty())
        assertEquals(0, q.size)
    }

    @Test
    fun singleItemLoopNextPrevious() {
        val q = WallpaperQueue()
        q.add("content://demo/a.mpkg")
        assertEquals("content://demo/a.mpkg", q.current())
        q.next()
        assertEquals("content://demo/a.mpkg", q.current())
        q.previous()
        assertEquals("content://demo/a.mpkg", q.current())
    }

    @Test
    fun multiItemNextPrevious() {
        val q = WallpaperQueue()
        q.add("a")
        q.add("b")
        q.add("c")
        assertEquals("a", q.current())
        q.next()
        assertEquals("b", q.current())
        q.next()
        assertEquals("c", q.current())
        q.previous()
        assertEquals("b", q.current())
    }

    @Test
    fun skipCorruptItems() {
        val q = WallpaperQueue()
        q.add("good")
        q.addCorrupt("bad")
        q.next()
        assertEquals("good", q.current())
    }

    @Test
    fun stopIdempotentDoesNotChangeBinding() {
        val q = WallpaperQueue()
        q.add("x")
        val bindingBefore = q.bindingState
        q.stop("op-stop", "op-target")
        q.stop("op-stop", "op-target")
        assertEquals(bindingBefore, q.bindingState)
    }
}
