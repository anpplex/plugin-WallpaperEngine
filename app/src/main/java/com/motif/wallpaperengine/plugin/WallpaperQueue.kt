package com.motif.wallpaperengine.plugin

/**
 * WP-08 wallpaper item queue: empty / single-loop / next-previous / skip corrupt.
 *
 * Queue index is independent of system bindingState; [stop] is idempotent and
 * does not mutate [bindingState].
 */
class WallpaperQueue {
    private data class Item(val uri: String, val corrupt: Boolean = false)

    private val items = ArrayList<Item>()
    private var index: Int = 0

    /** Mirrors runtime binding for stop-idempotent tests; queue never owns system truth. */
    var bindingState: BindingState = BindingState.UNKNOWN
        private set

    val size: Int
        get() = items.size

    fun isEmpty(): Boolean = items.isEmpty()

    fun add(uri: String) {
        items.add(Item(uri = uri, corrupt = false))
        if (items.size == 1) index = 0
    }

    fun addCorrupt(uri: String) {
        items.add(Item(uri = uri, corrupt = true))
    }

    fun current(): String? {
        if (items.isEmpty()) return null
        return items[normalizeIndex(index)].uri
    }

    fun next(): String? {
        if (items.isEmpty()) return null
        if (items.size == 1) {
            index = 0
            return currentIfHealthy(index) ?: items[0].uri
        }
        var steps = 0
        var i = index
        do {
            i = (i + 1) % items.size
            steps += 1
            val item = items[i]
            if (!item.corrupt) {
                index = i
                return item.uri
            }
        } while (steps < items.size)
        // all corrupt — stay put
        return current()
    }

    fun previous(): String? {
        if (items.isEmpty()) return null
        if (items.size == 1) {
            index = 0
            return items[0].uri
        }
        var steps = 0
        var i = index
        do {
            i = if (i == 0) items.size - 1 else i - 1
            steps += 1
            val item = items[i]
            if (!item.corrupt) {
                index = i
                return item.uri
            }
        } while (steps < items.size)
        return current()
    }

    /**
     * Idempotent stop of queue work; does not change bindingState.
     */
    fun stop(
        @Suppress("UNUSED_PARAMETER") operationId: String,
        @Suppress("UNUSED_PARAMETER") targetOperationId: String,
    ) {
        // no-op body beyond idempotency; bindingState intentionally unchanged
    }

    fun setBindingStateForTest(state: BindingState) {
        bindingState = state
    }

    private fun currentIfHealthy(i: Int): String? {
        val item = items[normalizeIndex(i)]
        return if (item.corrupt) null else item.uri
    }

    private fun normalizeIndex(i: Int): Int {
        if (items.isEmpty()) return 0
        var x = i % items.size
        if (x < 0) x += items.size
        return x
    }
}
