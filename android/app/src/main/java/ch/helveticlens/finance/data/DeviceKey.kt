package ch.helveticlens.finance.data

import android.content.pm.PackageManager
import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * The device key is an ECDSA P-256 key created inside the Android Keystore — in the StrongBox
 * secure chip when the phone has one. The private key cannot be exported: the chip signs, the app
 * never sees the key material.
 */
object DeviceKey {
    private const val ALIAS = "financial-lens-device"
    private fun store(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    fun exists(): Boolean = store().containsAlias(ALIAS)

    /** Returns true when the key lives in StrongBox. */
    fun create(context: Context): Boolean {
        delete()
        fun spec(strongBox: Boolean) = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .apply { if (strongBox && Build.VERSION.SDK_INT >= 28) setIsStrongBoxBacked(true) }
            .build()
        val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
        val hasStrongBox = Build.VERSION.SDK_INT >= 28 &&
            context.packageManager.hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)
        return try {
            gen.initialize(spec(hasStrongBox)); gen.generateKeyPair(); hasStrongBox
        } catch (e: StrongBoxUnavailableException) {
            gen.initialize(spec(false)); gen.generateKeyPair(); false
        }
    }

    fun delete() { if (exists()) store().deleteEntry(ALIAS) }

    /** SubjectPublicKeyInfo (DER), base64 — the only part of the key that leaves the phone. */
    fun publicKeyB64(): String =
        Base64.encodeToString(store().getCertificate(ALIAS).publicKey.encoded, Base64.NO_WRAP)

    /** ECDSA-SHA256 signature, DER encoded, base64. */
    fun sign(message: ByteArray): String {
        val key = store().getKey(ALIAS, null) as PrivateKey
        val sig = Signature.getInstance("SHA256withECDSA").apply { initSign(key); update(message) }.sign()
        return Base64.encodeToString(sig, Base64.NO_WRAP)
    }
}
