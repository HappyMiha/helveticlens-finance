package ch.helveticlens.finance

import android.content.Context
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.color.ColorProvider
import androidx.glance.layout.Column
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.padding
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import ch.helveticlens.finance.data.Session
import ch.helveticlens.finance.ui.T
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Home-screen widget: this month's spending, from a snapshot the app refreshes on the home Wi-Fi. */
class LensWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val p = context.getSharedPreferences("widget", Context.MODE_PRIVATE)
        val snap = p.getString("snapshot", null)?.let { JSONObject(it) }
        val hide = p.getBoolean("hide_amounts", false)
        provideContent {
            val fg = ColorProvider(T.text, T.text)
            val muted = ColorProvider(T.muted, T.muted)
            Column(GlanceModifier.fillMaxSize().background(ColorProvider(T.bg, T.bg)).padding(12.dp)
                .clickable(actionStartActivity<MainActivity>())) {
                Text("Financial Lens · ${snap?.optString("month") ?: ""}", style = TextStyle(color = muted, fontSize = 11.sp))
                if (snap == null) {
                    Text("Open the app at home to load", style = TextStyle(color = fg, fontSize = 13.sp))
                } else {
                    Text(if (hide) "CHF •••" else T.chf(snap.optString("expenses")),
                        style = TextStyle(color = fg, fontSize = 22.sp, fontWeight = FontWeight.Bold))
                    Text("${snap.optInt("unconfirmed")} to check", style = TextStyle(color = muted, fontSize = 12.sp))
                    if (!hide) snap.optJSONArray("top")?.let { a ->
                        for (i in 0 until minOf(a.length(), 3)) {
                            val c = a.getJSONObject(i)
                            Text("${c.optString("name")}  ${T.chf(c.optString("total"))}", style = TextStyle(color = muted, fontSize = 12.sp))
                        }
                    }
                }
            }
        }
    }
}

class LensWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = LensWidget()
}

class WidgetWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val client = Session.client(applicationContext) ?: return Result.success()
        if ("read" !in Session.scopes(applicationContext)) return Result.success()
        return try {
            val snap = client.get("/mobile/v1/widget")
            applicationContext.getSharedPreferences("widget", Context.MODE_PRIVATE).edit().putString("snapshot", snap.toString()).apply()
            LensWidget().updateAll(applicationContext)
            Result.success()
        } catch (e: Exception) { Result.success() } // away from home: keep the last snapshot
    }

    companion object {
        fun schedule(c: Context) = WorkManager.getInstance(c).enqueueUniquePeriodicWork("widget",
            ExistingPeriodicWorkPolicy.KEEP, PeriodicWorkRequestBuilder<WidgetWorker>(30, TimeUnit.MINUTES).build())
    }
}
