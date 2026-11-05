package ch.helveticlens.finance.data

import java.net.URI
import java.net.URLDecoder

data class PairingOffer(val address: String, val fingerprint: String, val offer: String, val otp: String, val scopes: List<String>) {
    companion object {
        /** Parses fl://pair?v=1&addr=…&fp=…&offer=…&otp=…&scopes=… and rejects anything else. */
        fun parse(text: String): PairingOffer {
            val uri = try { URI(text.trim()) } catch (e: Exception) { throw IllegalArgumentException("This is not a Financial Lens pairing code.") }
            if (uri.scheme != "fl" || uri.host != "pair") throw IllegalArgumentException("This is not a Financial Lens pairing code.")
            val q = (uri.rawQuery ?: "").split("&").filter { it.contains("=") }.associate {
                val (k, v) = it.split("=", limit = 2); k to URLDecoder.decode(v, "UTF-8")
            }
            if (q["v"] != "1") throw IllegalArgumentException("Unsupported pairing code version.")
            for (k in listOf("addr", "fp", "offer", "otp")) if (q[k].isNullOrBlank()) throw IllegalArgumentException("Pairing code is missing \"$k\".")
            if (!Regex("^[0-9a-f]{64}$").matches(q["fp"]!!)) throw IllegalArgumentException("Bad certificate fingerprint.")
            if (!Regex("^[A-Za-z0-9.\\-]+:[0-9]{1,5}$").matches(q["addr"]!!)) throw IllegalArgumentException("Bad address.")
            return PairingOffer(q["addr"]!!, q["fp"]!!, q["offer"]!!, q["otp"]!!, (q["scopes"] ?: "").split(",").filter { it.isNotBlank() })
        }
    }
}
