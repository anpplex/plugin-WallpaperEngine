package com.motif.wallpaperengine.plugin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** WP-10A: one-shot actionToken for import → confirmUserAction. */
class PluginOperationLedgerTest {
    @Test
    fun importMintsTokenAndPendingState() {
        val ledger = PluginOperationLedger()
        val rec = ledger.beginImport("op-1", "content://src/1", "demo.mpkg")
        assertEquals("ACTION_PENDING", rec.operationState)
        assertEquals(1, rec.actionEpoch)
        assertNotNull(rec.actionToken)
        assertFalse(rec.sourceConsumed)
        assertFalse(rec.tokenConsumed)
    }

    @Test
    fun importRecordsBinderCallerIdentityNotRequestForged() {
        val ledger = PluginOperationLedger()
        val rec = ledger.beginImport(
            operationId = "op-caller",
            sourceUri = "content://src/c",
            displayName = "c.mpkg",
            callerPackage = "com.mineradio.app",
            callerUid = 10244,
            certAllowlistMatch = true,
        )
        assertEquals("com.mineradio.app", rec.callerPackage)
        assertEquals(10244, rec.callerUid)
        assertTrue(rec.certAllowlistMatch)

        val shellRec = ledger.beginImport(
            operationId = "op-shell",
            sourceUri = "content://src/s",
            displayName = "s.mpkg",
            callerPackage = "shell",
            callerUid = CallerPolicy.SHELL_UID,
            certAllowlistMatch = false,
        )
        assertEquals("shell", shellRec.callerPackage)
        assertFalse(shellRec.certAllowlistMatch)
    }

    @Test
    fun confirmConsumesTokenOnceAndSetsSourceConsumed() {
        val ledger = PluginOperationLedger()
        val rec = ledger.beginImport("op-2", "content://src/2", "demo.mpkg")
        val token = rec.actionToken!!
        val (code, after) = ledger.confirmUserAction("op-2", rec.actionEpoch, token)
        assertEquals(PluginContract.CODE_OK, code)
        assertNotNull(after)
        assertTrue(after!!.sourceConsumed)
        assertTrue(after.tokenConsumed)
        assertNull(after.actionToken)
        assertEquals("STAGED", after.operationState)

        val (code2, _) = ledger.confirmUserAction("op-2", rec.actionEpoch, token)
        assertEquals(PluginContract.CODE_ACTION_TOKEN_EXPIRED, code2)
    }

    @Test
    fun wrongTokenOrEpochFailsClosed() {
        val ledger = PluginOperationLedger()
        val rec = ledger.beginImport("op-3", "content://src/3", "demo.mpkg")
        val (c1, _) = ledger.confirmUserAction("op-3", rec.actionEpoch, "wrong")
        assertEquals(PluginContract.CODE_ACTION_TOKEN_EXPIRED, c1)
        val (c2, _) = ledger.confirmUserAction("op-3", rec.actionEpoch + 9, rec.actionToken)
        assertEquals(PluginContract.CODE_ACTION_TOKEN_EXPIRED, c2)
        assertNotEquals(true, ledger.get("op-3")?.sourceConsumed)
    }
}
