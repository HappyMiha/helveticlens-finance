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
            DeviceKey.delete(); throw e
        }
        prefs(c).edit().putString("address", offer.address).putString("fingerprint", offer.fingerprint)
            .putString("device_id", client.deviceId).putString("scopes", offer.scopes.joinToString(","))
            .putBoolean("strongbox", strong).apply()
        return client
    }

    fun forget(c: Context) {
        prefs(c).edit().clear().apply()
        DeviceKey.delete()
        c.getSharedPreferences("widget", Context.MODE_PRIVATE).edit().clear().apply()
    }
}
