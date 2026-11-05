package ch.helveticlens.finance

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.AddAPhoto
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.PieChart
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import ch.helveticlens.finance.data.LensClient
import ch.helveticlens.finance.data.Session
import ch.helveticlens.finance.data.UploadQueue
import ch.helveticlens.finance.ui.*

sealed interface Screen {
    data object Home : Screen
    data class Category(val path: List<String>, val start: String, val end: String) : Screen
    data class Operation(val id: String) : Screen
    data class Original(val id: String, val name: String) : Screen
}

class MainActivity : FragmentActivity() {
    private var unlocked = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // No screenshots, hidden in Recents. Debug builds allow screenshots for the installation guide.
        if (!BuildConfig.DEBUG || !intent.getBooleanExtra("guide_screenshots", false))
            window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        UploadQueue.init(this)
        handleShare(intent)
        lifecycle.addObserver(LifecycleEventObserver { _, e ->
            if (e == Lifecycle.Event.ON_STOP) unlocked.value = false
            if (e == Lifecycle.Event.ON_START) { unlock(); UploadQueue.schedule(this); WidgetWorker.schedule(this) }
        })
        setContent { LensTheme { Surface(Modifier.fillMaxSize()) { Root() } } }
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handleShare(intent) }

    /** "Share → Financial Lens" from any app: the files join the upload queue. */
    private fun handleShare(intent: Intent?) {
        val uris = when (intent?.action) {
            Intent.ACTION_SEND -> listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
            Intent.ACTION_SEND_MULTIPLE -> IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java) ?: emptyList()
            else -> emptyList()
        }
        uris.forEach { runCatching { enqueueUri(this, it) } }
    }

    private fun unlock() {
        val allowed = BIOMETRIC_STRONG or DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(allowed) != BiometricManager.BIOMETRIC_SUCCESS) {
            unlocked.value = true; return // no screen lock on this phone: nothing to check against
        }
        BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) { unlocked.value = true }
        }).authenticate(BiometricPrompt.PromptInfo.Builder().setTitle("Unlock Financial Lens").setAllowedAuthenticators(allowed).build())
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun Root() {
        var client by remember { mutableStateOf(Session.client(this)) }
        if (!unlocked.value) {
            Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Outlined.Lock, null, tint = T.muted)
                Spacer(Modifier.height(12.dp))
                Button(onClick = { unlock() }) { Text("Unlock") }
            }
            return
        }
        val c = client
        if (c == null) { PairScreen { client = it; UploadQueue.schedule(this); WidgetWorker.schedule(this) }; return }
        Main(c) { Session.forget(this); client = null }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun Main(client: LensClient, forget: () -> Unit) {
        val stack = remember { mutableStateListOf<Screen>(Screen.Home) }
        var tab by remember { mutableIntStateOf(0) }
        var menu by remember { mutableStateOf(false) }
        var confirm by remember { mutableStateOf(false) }
        val screen = stack.last()
        androidx.activity.compose.BackHandler(enabled = stack.size > 1) { stack.removeAt(stack.lastIndex) }
        Scaffold(
            topBar = {
                TopAppBar(title = { Text(when (screen) {
                    is Screen.Category -> screen.path.joinToString(" / "); is Screen.Operation -> "Evidence"
                    is Screen.Original -> screen.name; else -> "Financial Lens" }) },
                    navigationIcon = { if (stack.size > 1) IconButton(onClick = { stack.removeAt(stack.lastIndex) }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                    actions = {
                        IconButton(onClick = { menu = true }) { Icon(Icons.Outlined.MoreVert, "Menu") }
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            DropdownMenuItem(text = { Text("Disconnect this phone") }, onClick = { menu = false; confirm = true })
                        }
                    })
            },
            bottomBar = {
                if (screen == Screen.Home) NavigationBar {
                    NavigationBarItem(selected = tab == 0, onClick = { tab = 0 }, icon = { Icon(Icons.Outlined.AddAPhoto, null) }, label = { Text("Add") })
                    if ("read" in Session.scopes(this@MainActivity))
                        NavigationBarItem(selected = tab == 1, onClick = { tab = 1 }, icon = { Icon(Icons.Outlined.PieChart, null) }, label = { Text("Overview") })
                }
            },
        ) { pad ->
            Box(Modifier.padding(pad)) {
                when (screen) {
                    Screen.Home -> if (tab == 0) AddScreen() else OverviewScreen(client) { p, s, e -> stack.add(Screen.Category(p, s, e)) }
                    is Screen.Category -> CategoryScreen(client, screen.path, screen.start, screen.end,
                        { stack.add(Screen.Category(it, screen.start, screen.end)) }, { stack.add(Screen.Operation(it)) })
                    is Screen.Operation -> OperationScreen(client, screen.id) { id, name -> stack.add(Screen.Original(id, name)) }
                    is Screen.Original -> OriginalScreen(client, screen.id)
                }
            }
        }
        if (confirm) AlertDialog(onDismissRequest = { confirm = false },
            title = { Text("Disconnect this phone?") },
            text = { Text("The phone deletes its key. To connect again, pair it from the computer. You can also revoke it there.") },
            confirmButton = { Button(onClick = { confirm = false; forget() }) { Text("Disconnect") } },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } })
    }
}
