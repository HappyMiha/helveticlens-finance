package ch.helveticlens.finance.data

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit

data class QueuedItem(val id: String, val name: String, val mime: String, val result: JSONObject? = null, val error: String? = null) {
    val done get() = result != null
    fun toJson(): JSONObject = JSONObject().put("id", id).put("name", name).put("mime", mime).put("result", result).put("error", error)
    companion object {
        fun from(j: JSONObject) = QueuedItem(j.getString("id"), j.getString("name"), j.getString("mime"),
            j.optJSONObject("result"), if (j.isNull("error")) null else j.optString("error"))
    }
}

/**
 * Offline queue: documents wait in the app's private storage until the Financial Lens is reachable on
 * the same network. WorkManager retries with backoff. Retries are harmless: the server recognises a file
 * it already has by its SHA-256.
 */
object UploadQueue {
    private val _items = MutableStateFlow<List<QueuedItem>>(emptyList())
    val items: StateFlow<List<QueuedItem>> = _items
    private lateinit var dir: File

    @Synchronized fun init(c: Context) {
        if (::dir.isInitialized) return
        dir = File(c.filesDir, "queue").apply { mkdirs() }
        val index = File(dir, "index.json")
        if (index.exists()) {
            val arr = JSONArray(index.readText())
            _items.value = (0 until arr.length()).map { QueuedItem.from(arr.getJSONObject(it)) }
        }
    }

    @Synchronized private fun save(list: List<QueuedItem>) {
        _items.value = list
        File(dir, "index.json").writeText(JSONArray(list.map { it.toJson() }).toString())
    }

    fun add(c: Context, name: String, mime: String, data: ByteArray) {
        init(c)
        val id = UUID.randomUUID().toString()
        File(dir, id).writeBytes(data)
        save(listOf(QueuedItem(id, name, mime)) + _items.value)
        schedule(c)
    }

    fun schedule(c: Context) {
        val req = OneTimeWorkRequestBuilder<UploadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
        WorkManager.getInstance(c).enqueueUniqueWork("uploads", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
    }

    fun clearDone() = save(_items.value.filter { !it.done })

    /** Sends pending items; returns false when the server was unreachable (retry later). */
    fun flush(c: Context): Boolean {
        init(c)
        val client = Session.client(c) ?: return true
        for (item in _items.value.filter { !it.done }.reversed()) {
            val file = File(dir, item.id)
            val updated = try {
                val r = client.upload(item.name, item.mime, file.readBytes())
                file.delete() // the original now lives in the ledger
                item.copy(result = r, error = null)
            } catch (e: LensException) {
                item.copy(error = e.message)
            } catch (e: java.io.IOException) {
                save(_items.value.map { if (it.id == item.id) it.copy(error = "Waiting for your Financial Lens (same Wi-Fi, app running)…") else it })
                return false
            }
            save(_items.value.map { if (it.id == item.id) updated else it })
            if (updated.error != null && (updated.error.contains("not paired") || updated.error.contains("permission"))) break
        }
        return true
    }
}

class UploadWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = if (UploadQueue.flush(applicationContext)) Result.success() else Result.retry()
}
