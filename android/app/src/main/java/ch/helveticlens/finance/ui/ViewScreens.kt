package ch.helveticlens.finance.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ch.helveticlens.finance.data.LensClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate

/** Loads JSON from the paired Financial Lens off the main thread. */
@Composable
fun rememberLoad(key: Any, load: () -> JSONObject): State<Result<JSONObject>?> =
    produceState<Result<JSONObject>?>(null, key) { value = withContext(Dispatchers.IO) { runCatching(load) } }

fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

@Composable
fun Loading(state: Result<JSONObject>?, content: @Composable (JSONObject) -> Unit) {
    when {
        state == null -> Box(Modifier.fillMaxWidth().padding(40.dp)) { CircularProgressIndicator() }
        state.isFailure -> Text(state.exceptionOrNull()?.message ?: "Not reachable", color = T.warning, modifier = Modifier.padding(16.dp))
        else -> content(state.getOrThrow())
    }
}

@Composable
fun OverviewScreen(client: LensClient, open: (List<String>, String, String) -> Unit) {
    var months by remember { mutableStateOf(0) }
    var refresh by remember { mutableStateOf(0) }
    val today = LocalDate.now()
    val start = if (months == 0) today.withDayOfMonth(1) else today.minusYears(1)
    val state by rememberLoad(months to refresh) { client.get("/mobile/v1/summary?start=$start&end=$today") }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            listOf(0 to "This month", 12 to "12 months").forEachIndexed { i, (m, label) ->
                SegmentedButton(selected = months == m, onClick = { months = m }, shape = SegmentedButtonDefaults.itemShape(i, 2)) { Text(label) }
            }
        }
        Spacer(Modifier.height(12.dp))
        Loading(state) { d ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Kpi("Expenses", T.chf(d.optString("expenses")), Modifier.weight(1f))
                Kpi("Income", T.chf(d.optString("income")), Modifier.weight(1f))
            }
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Kpi("Balance", T.chf(d.optString("balance")), Modifier.weight(1f))
                Kpi("To check", "${d.optInt("unconfirmed")} · ${d.optInt("unpaid")} unpaid", Modifier.weight(1f))
            }
            Spacer(Modifier.height(20.dp))
            Text("Where the money went", style = MaterialTheme.typography.titleMedium)
            val cats = d.optJSONArray("categories")?.objects() ?: emptyList()
            if (cats.isEmpty()) Text("No spending recorded in this period yet.", color = T.muted)
            val max = cats.maxOfOrNull { it.optString("total").toBigDecimalOrNull() ?: java.math.BigDecimal.ZERO }
            cats.forEachIndexed { i, c ->
                val share = if (max == null || max.signum() == 0) 0f
                    else ((c.optString("total").toBigDecimalOrNull() ?: java.math.BigDecimal.ZERO).toFloat() / max.toFloat())
                Column(Modifier.fillMaxWidth().clickable { open(listOf(c.getString("name")), start.toString(), today.toString()) }.padding(vertical = 8.dp)) {
                    Row { Text(c.getString("name"), fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f)); Text(T.chf(c.optString("total"))) }
                    Spacer(Modifier.height(4.dp))
                    Box(Modifier.fillMaxWidth(share.coerceIn(0.02f, 1f)).height(10.dp)
                        .background(T.expense[i % T.expense.size], RoundedCornerShape(3.dp)))
                }
            }
            TextButton(onClick = { refresh++ }) { Text("Refresh") }
        }
    }
}

@Composable
private fun Kpi(label: String, value: String, modifier: Modifier) = OutlinedCard(modifier) {
    Column(Modifier.padding(14.dp)) {
        Text(label, color = T.muted, fontSize = 12.sp)
        Text(value, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
    }
}

@Composable
fun CategoryScreen(client: LensClient, path: List<String>, start: String, end: String,
                   openCategory: (List<String>) -> Unit, openOperation: (String) -> Unit) {
    val state by rememberLoad(path) {
        client.get("/mobile/v1/treemap?path=${java.net.URLEncoder.encode(path.joinToString("/"), "UTF-8")}&start=$start&end=$end")
    }
    Loading(state) { n ->
        LazyColumn {
            item { ListItem(headlineContent = { Text(T.chf(n.optString("total")), fontSize = 22.sp, fontWeight = FontWeight.SemiBold) },
                supportingContent = { Text("${n.optInt("count")} records · $start – $end", color = T.muted) }) }
            items(n.optJSONArray("children")?.objects() ?: emptyList()) { c ->
                ListItem(modifier = Modifier.clickable { openCategory(path + c.getString("name")) },
                    headlineContent = { Text(c.getString("name")) }, trailingContent = { Text(T.chf(c.optString("total"))) })
            }
            items(n.optJSONArray("operations")?.objects() ?: emptyList()) { o ->
                ListItem(modifier = Modifier.clickable { openOperation(o.getString("id")) },
                    leadingContent = { Text("●", color = T.status(o.optString("verification"))) },
                    headlineContent = { Text(o.optString("counterparty").ifBlank { o.optString("kind") }) },
                    supportingContent = { Text("${o.optString("date")} · ${T.statusLabel(o.optString("verification"))}", color = T.muted) },
                    trailingContent = { Text(T.chf(o.optString("amount"))) })
            }
        }
    }
}

@Composable
fun OperationScreen(client: LensClient, id: String, openOriginal: (String, String) -> Unit) {
    val state by rememberLoad(id) { client.get("/mobile/v1/operations/$id") }
    Loading(state) { d ->
        Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp)) {
            Text(d.optString("counterparty").ifBlank { d.optString("kind") }, style = MaterialTheme.typography.titleLarge)
            Text(T.chf(d.optString("amount")), fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
            Text("● ${T.statusLabel(d.optString("verification"))} — ${d.optString("verification_reason")}", color = T.status(d.optString("verification")))
            Spacer(Modifier.height(12.dp))
            Row2("Date", d.optString("op_date"))
            if (!d.isNull("due_date")) Row2("Due", d.optString("due_date"))
            Row2("Category", d.optJSONArray("category_path")?.let { a -> (0 until a.length()).joinToString(" / ") { a.getString(it) } })
            Row2("Read by", d.optString("method"))
            d.optJSONObject("provenance")?.let { p ->
                Spacer(Modifier.height(16.dp)); Text("Where each value came from", style = MaterialTheme.typography.titleSmall)
                p.keys().forEach { k -> p.optJSONObject(k)?.let { v -> if (!v.isNull("quote")) Row2(k, "“${v.optString("quote")}”" + (if (!v.isNull("line")) " · line ${v.optInt("line")}" else "")) } }
            }
            Spacer(Modifier.height(16.dp)); Text("Documents", style = MaterialTheme.typography.titleSmall)
            d.optJSONArray("documents")?.objects()?.forEach { doc ->
                ListItem(modifier = Modifier.clickable { openOriginal(doc.getString("id"), doc.getString("filename")) },
                    headlineContent = { Text(doc.getString("filename")) },
                    supportingContent = { Text("${doc.optString("role")} · sha256 ${doc.optString("sha256").take(12)}…", color = T.muted) })
            }
            d.optJSONArray("links")?.objects()?.takeIf { it.isNotEmpty() }?.let { links ->
                Spacer(Modifier.height(16.dp)); Text("Linked", style = MaterialTheme.typography.titleSmall)
                links.forEach { l -> Row2("${l.optString("other_kind")} ${l.optString("other_date")}",
                    "${T.chf(l.optString("other_amount"))} · ${l.optString("status")}\n" +
                        (l.optJSONArray("reasons")?.let { a -> (0 until a.length()).joinToString("; ") { a.getString(it) } } ?: "")) }
            }
            Spacer(Modifier.height(16.dp)); Text("History", style = MaterialTheme.typography.titleSmall)
            d.optJSONArray("history")?.objects()?.forEach { h ->
                Row2("r${h.optInt("revision")}", "${h.optString("change_reason")} · ${T.statusLabel(h.optString("verification"))}\n${h.optString("agent")}")
            }
        }
    }
}

@Composable
private fun Row2(k: String, v: String?) = Row(Modifier.padding(vertical = 4.dp)) {
    Text(k, color = T.muted, modifier = Modifier.width(110.dp)); Text(v ?: "—")
}

@Composable
fun OriginalScreen(client: LensClient, id: String) {
    val state by produceState<Result<Pair<ByteArray, String>>?>(null, id) { value = withContext(Dispatchers.IO) { runCatching { client.original(id) } } }
    val s = state
    when {
        s == null -> CircularProgressIndicator(Modifier.padding(40.dp))
        s.isFailure -> Text(s.exceptionOrNull()?.message ?: "", color = T.warning, modifier = Modifier.padding(16.dp))
        else -> {
            val (bytes, type) = s.getOrThrow()
            val bmp = if (type.startsWith("image/")) BitmapFactory.decodeByteArray(bytes, 0, bytes.size) else null
            if (bmp != null) Image(bmp.asImageBitmap(), null, Modifier.fillMaxSize())
            else Text("$type · ${bytes.size / 1024} KB\nOpen it on your computer to view this file type.", modifier = Modifier.padding(16.dp))
        }
    }
}
