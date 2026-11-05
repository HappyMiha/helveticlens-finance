package ch.helveticlens.finance.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.Buffer
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.time.Instant
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

class LensException(val status: Int, message: String) : Exception(message)

fun sha256Hex(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

/**
 * Talks only to the paired Financial Lens. TLS trusts exactly one certificate — the one whose
 * SHA-256 fingerprint came in the pairing QR code — and no certificate authority at all.
 * Every request is signed by the hardware-backed device key.
 */
class LensClient(val address: String, private val fingerprint: String, var deviceId: String? = null) {
    private val pinned = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = throw CertificateException()
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (chain.isEmpty() || sha256Hex(chain[0].encoded) != fingerprint)
                throw CertificateException("Certificate does not match the paired Financial Lens")
        }
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }
    private val http: OkHttpClient = OkHttpClient.Builder()
        .sslSocketFactory(SSLContext.getInstance("TLS").apply { init(null, arrayOf(pinned), SecureRandom()) }.socketFactory, pinned)
        .hostnameVerifier { _, _ -> true } // identity is proven by the pinned certificate, not by a name
        .connectTimeout(8, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS).writeTimeout(120, TimeUnit.SECONDS)
        .build()

    companion object {
        fun canonical(method: String, path: String, ts: String, nonce: String, body: ByteArray): ByteArray =
            listOf(method.uppercase(), path, ts, nonce, sha256Hex(body)).joinToString("\n").toByteArray()
    }

    private fun call(method: String, pathAndQuery: String, body: RequestBody? = null, sign: Boolean = true): Pair<ByteArray, String> {
        val url = "https://$address$pathAndQuery"
        val bytes = body?.let { Buffer().also { b -> it.writeTo(b) }.readByteArray() } ?: ByteArray(0)
        val req = Request.Builder().url(url).method(method, body?.let { bytes.toRequestBody(it.contentType()) })
        if (sign) {
            val ts = Instant.now().toString()
            val nonce = UUID.randomUUID().toString()
            val path = url.toHttpPath()
            req.header("X-FL-Device", deviceId!!).header("X-FL-Timestamp", ts).header("X-FL-Nonce", nonce)
                .header("X-FL-Signature", DeviceKey.sign(canonical(method, path, ts, nonce, bytes)))
        }
        http.newCall(req.build()).execute().use { res ->
            val data = res.body?.bytes() ?: ByteArray(0)
            if (!res.isSuccessful) {
                val msg = try { JSONObject(String(data)).optString("detail", "Error ${res.code}") } catch (e: Exception) { "Error ${res.code}" }
                throw LensException(res.code, msg)
            }
            return data to (res.header("Content-Type") ?: "")
        }
    }

    private fun String.toHttpPath(): String = java.net.URI(this).rawPath

    private fun json(method: String, path: String, body: RequestBody? = null, sign: Boolean = true) =
        JSONObject(String(call(method, path, body, sign).first))

    fun pair(offer: PairingOffer, name: String): String {
        val body = JSONObject().put("offer", offer.offer).put("otp", offer.otp).put("name", name)
            .put("platform", "android").put("public_key", DeviceKey.publicKeyB64()).toString()
            .toRequestBody("application/json".toMediaType())
        deviceId = json("POST", "/mobile/v1/pair", body, sign = false).getString("device_id")
        return deviceId!!
    }

    fun get(pathAndQuery: String): JSONObject = json("GET", pathAndQuery)

    fun original(documentId: String): Pair<ByteArray, String> = call("GET", "/mobile/v1/documents/$documentId/original")

    fun upload(name: String, mime: String, data: ByteArray): JSONObject {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("files", name.replace("\"", ""), data.toRequestBody(mime.toMediaType())).build()
        return json("POST", "/mobile/v1/documents", body).getJSONArray("results").getJSONObject(0)
    }
}
