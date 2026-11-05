package ch.helveticlens.finance.ui

import android.app.Activity
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import ch.helveticlens.finance.data.QueuedItem
import ch.helveticlens.finance.data.UploadQueue
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

fun displayName(c: Context, uri: Uri): String =
    c.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
        if (it.moveToFirst()) it.getString(0) else null
    } ?: (uri.lastPathSegment ?: "document")

fun enqueueUri(c: Context, uri: Uri, fallbackName: String? = null) {
    val name = fallbackName ?: displayName(c, uri)
    val mime = c.contentResolver.getType(uri) ?: "application/octet-stream"
    val bytes = c.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: return
    UploadQueue.add(c, name, mime, bytes)
}

private fun stamp() = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(Date())

@Composable
fun AddScreen() {
    val ctx = LocalContext.current
    val items by UploadQueue.items.collectAsState()
    var photoUri by remember { mutableStateOf<Uri?>(null) }

    val takePhoto = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val uri = photoUri
        if (ok && uri != null) enqueueUri(ctx, uri, "IMG_${stamp()}.jpg")
    }
    // ML Kit document scanner: edge detection, perspective correction, several pages → one PDF, all on the phone.
    val scan = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { r ->
        if (r.resultCode == Activity.RESULT_OK) {
            GmsDocumentScanningResult.fromActivityResultIntent(r.data)?.pdf?.let { enqueueUri(ctx, it.uri, "Scan_${stamp()}.pdf") }
        }
    }
    val photos = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(20)) { uris ->
        uris.forEach { enqueueUri(ctx, it) }
    }
    val files = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        uris.forEach { enqueueUri(ctx, it) }
    }

    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        item {
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Big(Icons.Outlined.PhotoCamera, "Photo", Modifier.weight(1f), tall = true) {
                    val f = File(ctx.cacheDir, "camera").apply { mkdirs() }.let { File(it, "IMG_${stamp()}.jpg") }
                    val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.files", f)
                    photoUri = uri
                    takePhoto.launch(uri)
                }
                Big(Icons.Outlined.DocumentScanner, "Scan", Modifier.weight(1f), tall = true) {
                    val opts = GmsDocumentScannerOptions.Builder().setGalleryImportAllowed(false).setPageLimit(20)
                        .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_PDF)
                        .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL).build()
                    GmsDocumentScanning.getClient(opts).getStartScanIntent(ctx as Activity)
                        .addOnSuccessListener { scan.launch(IntentSenderRequest.Builder(it).build()) }
                }
            }
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Big(Icons.Outlined.PhotoLibrary, "Photos", Modifier.weight(1f)) {
                    photos.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                }
                Big(Icons.Outlined.FolderOpen, "Files", Modifier.weight(1f)) {
                    files.launch(arrayOf("application/pdf", "image/*", "text/*", "application/xml",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                }
            }
            Spacer(Modifier.height(20.dp))
            val pending = items.count { !it.done }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (pending == 0) "Sent" else "$pending waiting", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.weight(1f))
                if (pending > 0) TextButton(onClick = { UploadQueue.schedule(ctx) }) { Text("Send now") }
                if (items.any { it.done }) TextButton(onClick = { UploadQueue.clearDone() }) { Text("Clear") }
            }
        }
        items(items, key = { it.id }) { QueueRow(it) }
        item {
            Text("Originals go only to your own Financial Lens on this Wi-Fi. Amounts and categories are read there, " +
                "and every record links back to the photo.", color = T.muted, fontSize = 12.sp,
                modifier = Modifier.padding(vertical = 16.dp))
        }
    }
}

@Composable
private fun Big(icon: ImageVector, label: String, modifier: Modifier, tall: Boolean = false, onClick: () -> Unit) =
    OutlinedCard(onClick = onClick, modifier = modifier.height(if (tall) 120.dp else 72.dp)) {
        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, null, Modifier.size(if (tall) 36.dp else 24.dp))
            Spacer(Modifier.height(6.dp))
            Text(label, fontWeight = FontWeight.SemiBold)
        }
    }

@Composable
private fun QueueRow(i: QueuedItem) {
    val r = i.result
    val (title, sub, dot) = when {
        r != null && r.has("amount") -> Triple(r.optString("counterparty").ifBlank { i.name },
            "${T.chf(r.optString("amount"))} · ${r.optJSONArray("category")?.let { a -> (0 until a.length()).joinToString(" / ") { a.getString(it) } } ?: ""} · ${T.statusLabel(r.optString("status"))}",
            T.status(r.optString("status")))
        r != null -> Triple(i.name, if (r.optBoolean("duplicate")) "Already in your ledger" else "Saved; waiting in the inbox on your computer", T.warning)
        else -> Triple(i.name, i.error ?: "Waiting to send…", T.muted)
    }
    ListItem(headlineContent = { Text(title) }, supportingContent = { Text(sub, color = T.muted) },
        leadingContent = { Text("●", color = dot) })
}
