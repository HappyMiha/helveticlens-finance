package ch.helveticlens.finance.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import ch.helveticlens.finance.data.LensClient
import ch.helveticlens.finance.data.PairingOffer
import ch.helveticlens.finance.data.Session
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun PairScreen(onPaired: (LensClient) -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    fun handle(raw: String) {
        busy = true; error = null
        scope.launch {
            try {
                val offer = PairingOffer.parse(raw)
                val client = withContext(Dispatchers.IO) { Session.pair(ctx, offer) }
                onPaired(client)
            } catch (e: Exception) {
                error = e.message ?: e.toString()
            } finally { busy = false }
        }
    }

    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text("Connect to Financial Lens", style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(12.dp))
        Text("On your computer open Financial Lens → “Pair phone”, then scan the code. Phone and computer must be on " +
            "the same Wi-Fi. The code works once and expires after 5 minutes.", color = T.muted)
        Spacer(Modifier.height(24.dp))
        Button(enabled = !busy, modifier = Modifier.fillMaxWidth().height(56.dp), onClick = {
            // Google's code scanner: runs on the phone, needs no camera permission for this app.
            GmsBarcodeScanning.getClient(ctx, GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
                .startScan().addOnSuccessListener { it.rawValue?.let(::handle) }
                .addOnFailureListener { error = it.message }
        }) { Text("Scan pairing code") }
        if (busy) { Spacer(Modifier.height(16.dp)); LinearProgressIndicator(Modifier.fillMaxWidth()) }
        error?.let { Spacer(Modifier.height(16.dp)); Text(it, color = T.danger) }
    }
}
