package ch.helveticlens.finance.data

import android.content.Context
import android.os.Build

/** Non-secret pairing facts. The secret part — the device key — lives in the Android Keystore. */
object Session {
    private fun prefs(c: Context) = c.getSharedPreferences("pairing", Context.MODE_PRIVATE)

    fun client(c: Context): LensClient? {
        val p = prefs(c)
        val id = p.getString("device_id", null) ?: return null
        if (!DeviceKey.exists()) return null
        return LensClient(p.getString("address", "")!!, p.getString("fingerprint", "")!!, id)
    }

    fun scopes(c: Context): List<String> = (prefs(c).getString("scopes", "") ?: "").split(",").filter { it.isNotBlank() }
    fun strongBox(c: Context): Boolean = prefs(c).getBoolean("strongbox", false)

    /** Blocking network call: run off the main thread. */
    fun pair(c: Context, offer: PairingOffer): LensClient {
        val strong = DeviceKey.create(c)
        val client = LensClient(offer.address, offer.fingerprint)
        try {
            client.pair(offer, "${Build.MANUFACTURER} ${Build.MODEL}".trim())
        } catch (e: Exception) {
            DeviceKey.delete(); throw explain(e, offer)
        }
        prefs(c).edit().putString("address", offer.address).putString("fingerprint", offer.fingerprint)
            .putString("device_id", client.deviceId).putString("scopes", offer.scopes.joinToString(","))
            .putBoolean("strongbox", strong).apply()
        return client
    }

    /** Turns network and server errors into a next step a person can follow. */
    fun explain(e: Exception, offer: PairingOffer): Exception = IllegalStateException(when {
        e is LensException && e.status == 404 ->
            "Financial Lens on your computer is too old for the phone app. Update it to 0.6.1 or newer (finance.helveticlens.ch)."
        e is LensException && e.status == 403 ->
            "This pairing code was already used or has expired (codes work once, for 5 minutes). Press “Pair phone” on the computer again."
        e is javax.net.ssl.SSLException || e.cause is java.security.cert.CertificateException ->
            "The computer at ${offer.address} is not the Financial Lens that showed this code. Check you are on your own Wi-Fi."
        e is java.net.SocketTimeoutException || e is java.net.ConnectException || e is java.net.NoRouteToHostException ->
            "Cannot reach your computer at ${offer.address}. Make sure the phone is on the same Wi-Fi as the computer " +
                "and Financial Lens is open there (the “Pair phone” window may stay open)."
        else -> e.message ?: e.toString()
    }, e)

    fun forget(c: Context) {
        prefs(c).edit().clear().apply()
        DeviceKey.delete()
        c.getSharedPreferences("widget", Context.MODE_PRIVATE).edit().clear().apply()
    }
}
