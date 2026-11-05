package ch.helveticlens.finance.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import java.math.BigDecimal
import java.math.RoundingMode

// Helvetic Lens dark tokens (design-tokens.css).
object T {
    val bg = Color(0xFF090B0E); val surface = Color(0xFF111418); val surface2 = Color(0xFF181A1E)
    val line = Color(0xFF343A44); val text = Color(0xFFE6E3E1); val muted = Color(0xFFA7ADB5)
    val success = Color(0xFFA4D2B7); val warning = Color(0xFFE6C083); val danger = Color(0xFFF2B0A9)
    val expense = listOf(Color(0xFF7A2F2A), Color(0xFF8A4127), Color(0xFF6F3A2C), Color(0xFF93502A), Color(0xFF5F2F2F))

    /** Display only: every amount arrives already computed by the ledger, as a decimal string. */
    fun chf(v: Any?): String {
        val d = try { BigDecimal(v.toString()) } catch (e: Exception) { BigDecimal.ZERO }.setScale(2, RoundingMode.HALF_EVEN)
        val s = d.abs().toPlainString().split(".")
        val whole = s[0].reversed().chunked(3).joinToString("’").reversed()
        return (if (d.signum() < 0) "-" else "") + "CHF $whole.${s[1]}"
    }
    fun status(s: String?) = when (s) { "confirmed" -> success; "needs_review" -> warning; else -> muted }
    fun statusLabel(s: String?) = when (s) { "confirmed" -> "Confirmed"; "needs_review" -> "Needs review"; "unconfirmed" -> "Unconfirmed"; else -> s ?: "" }
}

@Composable
fun LensTheme(content: @Composable () -> Unit) = MaterialTheme(
    colorScheme = darkColorScheme(primary = T.text, onPrimary = T.bg, background = T.bg, onBackground = T.text,
        surface = T.surface, onSurface = T.text, surfaceVariant = T.surface2, outline = T.line, error = T.danger),
    content = content,
)
