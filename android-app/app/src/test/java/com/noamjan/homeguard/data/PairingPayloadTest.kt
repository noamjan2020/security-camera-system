package com.noamjan.homeguard.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingPayloadTest {
    @Test
    fun parsesOneTimePairingPayload() {
        val code = "a".repeat(48)
        val payload = PairingPayload.parse("homeguard://pair?url=http%3A%2F%2F192.168.1.5%3A8765&code=$code")
        assertEquals("http://192.168.1.5:8765/", payload.url)
        assertEquals(code, payload.code)
    }

    @Test
    fun rejectsPermanentTokenStylePayload() {
        val token = "a".repeat(48)
        assertThrows(IllegalArgumentException::class.java) {
            PairingPayload.parse("homeguard://pair?url=http%3A%2F%2F192.168.1.5%3A8765&token=$token")
        }
    }

    @Test
    fun rejectsPublicCleartextUrl() {
        assertThrows(IllegalArgumentException::class.java) { normalizeBaseUrl("http://example.com") }
    }

    @Test
    fun allowsPrivateLanHttpAndPublicHttps() {
        assertEquals("http://10.0.0.5:8765/", normalizeBaseUrl("http://10.0.0.5:8765"))
        assertEquals("https://camera.example/", normalizeBaseUrl("https://camera.example"))
    }

    @Test
    fun rejectsNonHomeGuardPayload() {
        assertThrows(IllegalArgumentException::class.java) { PairingPayload.parse("https://example.com") }
    }
}
