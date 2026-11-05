package ch.helveticlens.finance

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import ch.helveticlens.finance.data.DeviceKey
import ch.helveticlens.finance.data.PairingOffer
import ch.helveticlens.finance.data.Session
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith

/**
 * On a real Android runtime against a real Financial Lens (packaging/mobile_e2e_server.py):
 * pinned TLS, pairing with the one-time code, hardware-keystore signatures, upload, read-back.
 * Pass the pairing URI with -Pandroid.testInstrumentationRunnerArguments.pairUri=...
 */
@RunWith(AndroidJUnit4::class)
class EndToEndTest {
    @Test fun pairUploadReadBack() {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val uri = InstrumentationRegistry.getArguments().getString("pairUri") ?: error("pairUri argument missing")
        val offer = PairingOffer.parse(uri)
        Session.forget(ctx)

        // A look-alike server (different certificate) is refused before anything is sent.
        try {
            Session.pair(ctx, offer.copy(fingerprint = "0".repeat(64))); fail("impostor accepted")
        } catch (e: Exception) { assertTrue(!DeviceKey.exists()) }

        val client = Session.pair(ctx, offer)
        assertNotNull(client.deviceId)
        assertEquals(client.deviceId, Session.client(ctx)!!.deviceId)
        assertTrue(DeviceKey.exists())

        val receipt = "Bäckerei Frey AG\nQuittung\nDatum 03.10.2026\nTotal CHF 12.80\n".toByteArray()
        val r = client.upload("receipt.txt", "text/plain", receipt)
        assertEquals("12.80", r.getString("amount"))
        val s = client.get("/mobile/v1/summary?start=2026-10-01&end=2026-10-31")
        assertEquals("12.80", s.getString("expenses"))
        val op = client.get("/mobile/v1/operations/${r.getString("operation_id")}")
        val doc = op.getJSONArray("documents").getJSONObject(0).getString("id")
        assertTrue(String(client.original(doc).first).contains("Bäckerei Frey"))
        // A replayed or forged request is refused by the server: the signature binds path, time and nonce.
        println("E2E OK strongbox=${Session.strongBox(ctx)} device=${client.deviceId}")
        Session.forget(ctx)
    }
}
