package com.motif.wallpaperengine.plugin

import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * In-process ledger for WP-10A action-token handoff (import_mpkg → renew/confirm).
 *
 * One-shot: consuming a token/epoch pair invalidates it. Pure domain; no I/O.
 */
class PluginOperationLedger {
    data class Record(
        val operationId: String,
        val method: String,
        var operationState: String,
        var actionEpoch: Int,
        var actionToken: String?,
        var actionKind: String?,
        var sourceUri: String?,
        var sourceConsumed: Boolean,
        var tokenConsumed: Boolean,
        var displayName: String?,
    )

    private val records = ConcurrentHashMap<String, Record>()

    fun get(operationId: String): Record? = records[operationId]

    fun beginImport(
        operationId: String,
        sourceUri: String?,
        displayName: String?,
    ): Record {
        val epoch = 1
        val token = UUID.randomUUID().toString()
        val rec = Record(
            operationId = operationId,
            method = PluginContract.METHOD_IMPORT_MPKG,
            operationState = "ACTION_PENDING",
            actionEpoch = epoch,
            actionToken = token,
            actionKind = "IMPORT",
            sourceUri = sourceUri,
            sourceConsumed = false,
            tokenConsumed = false,
            displayName = displayName,
        )
        records[operationId] = rec
        return rec
    }

    /**
     * Confirm user action (renew_action / confirmUserAction path).
     * Requires matching epoch and unconsumed token.
     */
    fun confirmUserAction(
        operationId: String,
        actionEpoch: Int,
        actionToken: String?,
    ): Pair<Int, Record?> {
        val rec = records[operationId]
            ?: return PluginContract.CODE_BAD_REQUEST to null
        if (rec.tokenConsumed) {
            return PluginContract.CODE_ACTION_TOKEN_EXPIRED to rec
        }
        if (rec.actionEpoch != actionEpoch) {
            return PluginContract.CODE_ACTION_TOKEN_EXPIRED to rec
        }
        if (actionToken.isNullOrBlank() || actionToken != rec.actionToken) {
            return PluginContract.CODE_ACTION_TOKEN_EXPIRED to rec
        }
        rec.tokenConsumed = true
        rec.actionToken = null
        rec.sourceConsumed = true
        rec.operationState = "STAGED"
        rec.actionEpoch += 1
        return PluginContract.CODE_OK to rec
    }

    fun markStaged(operationId: String) {
        records[operationId]?.let {
            it.operationState = "STAGED"
            it.sourceConsumed = true
        }
    }

    fun size(): Int = records.size
}
