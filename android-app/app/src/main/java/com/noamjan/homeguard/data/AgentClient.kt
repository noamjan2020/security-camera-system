package com.noamjan.homeguard.data

import android.content.Context
import android.os.Build
import com.noamjan.homeguard.BuildConfig
import com.noamjan.homeguard.logging.AppLogger
import com.noamjan.homeguard.security.SecureStore
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

class AgentClient(context: Context) {
    private val secureStore = SecureStore(context.applicationContext)

    var token: String
        get() = secureStore.get("api_token")
        private set(value) = secureStore.put("api_token", value)

    var deviceId: String
        get() = secureStore.get("device_id")
        private set(value) = secureStore.put("device_id", value)

    var baseUrl: String
        get() = secureStore.get("agent_url", BuildConfig.DEFAULT_AGENT_URL)
        private set(value) = secureStore.put("agent_url", normalizeBaseUrl(value))

    val paired: Boolean get() = token.isNotBlank() && deviceId.isNotBlank() && baseUrl.isNotBlank()

    private val authInterceptor = Interceptor { chain ->
        val requestId = java.util.UUID.randomUUID().toString().take(16)
        val request = chain.request().newBuilder()
            .header("X-Request-ID", requestId)
            .apply { if (token.isNotBlank()) header("Authorization", "Bearer $token") }
            .build()
        val started = System.nanoTime()
        runCatching { chain.proceed(request) }
            .onSuccess { response ->
                AppLogger.i(
                    "Network",
                    "${request.method} ${request.url.encodedPath} -> ${response.code}",
                    mapOf("request_id" to requestId, "duration_ms" to (System.nanoTime() - started) / 1_000_000),
                )
            }
            .onFailure { error ->
                AppLogger.e(
                    "Network",
                    "${request.method} ${request.url.encodedPath} failed",
                    mapOf("request_id" to requestId, "duration_ms" to (System.nanoTime() - started) / 1_000_000),
                    error,
                )
            }
            .getOrThrow()
    }

    suspend fun claimPairing(payload: PairingPayload): PairClaimResponse {
        val client = baseClient(authenticated = false)
        val pairingApi = retrofit(payload.url, client).create(PairingApi::class.java)
        val deviceName = listOf(Build.MANUFACTURER, Build.MODEL).filter { it.isNotBlank() }.joinToString(" ").take(100)
        val response = pairingApi.claim(PairClaimRequest(payload.code, deviceName.ifBlank { "Android phone" }))
        baseUrl = payload.url
        token = response.token
        deviceId = response.deviceId
        AppLogger.i("AgentClient", "One-time pairing claimed", mapOf("url" to payload.url, "device_id" to response.deviceId))
        return response
    }

    fun api(): AgentApi = retrofit(baseUrl, baseClient(authenticated = true)).create(AgentApi::class.java)

    fun clearPairing() {
        secureStore.remove("agent_url", "api_token", "device_id")
        AppLogger.w("AgentClient", "Pairing cleared")
    }

    private fun baseClient(authenticated: Boolean): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .callTimeout(30, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
        if (authenticated) builder.addInterceptor(authInterceptor)
        if (BuildConfig.ENABLE_VERBOSE_NETWORK_LOGS) {
            builder.addInterceptor(HttpLoggingInterceptor { line -> AppLogger.d("OkHttp", redact(line)) }.apply {
                level = HttpLoggingInterceptor.Level.BASIC
                redactHeader("Authorization")
            })
        }
        return builder.build()
    }

    private fun retrofit(url: String, client: OkHttpClient): Retrofit = Retrofit.Builder()
        .baseUrl(normalizeBaseUrl(url))
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    private fun redact(line: String): String = line.replace(Regex("Bearer\\s+[A-Za-z0-9._~-]+"), "Bearer [REDACTED]")
}
