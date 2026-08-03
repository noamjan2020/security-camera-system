package com.noamjan.homeguard.data

import android.content.Context
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import com.google.gson.reflect.TypeToken
import com.noamjan.homeguard.BuildConfig
import com.noamjan.homeguard.logging.AppLogger
import com.noamjan.homeguard.security.SecureStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.net.URLEncoder
import java.time.Instant
import java.util.UUID
import java.util.concurrent.TimeUnit

private data class AuthResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String,
    @SerializedName("expires_in") val expiresIn: Long,
    val user: CloudUser?,
)

private data class CloudUser(val id: String, val email: String?)
private data class SignUpResponse(val user: CloudUser?)
private data class CameraRelation(val name: String?)
private data class CloudEvent(
    val id: String,
    @SerializedName("occurred_at") val occurredAt: String,
    @SerializedName("person_confidence") val personConfidence: Double,
    @SerializedName("face_result") val faceResult: String,
    @SerializedName("person_name") val personName: String?,
    @SerializedName("media_path") val mediaPath: String?,
    @SerializedName("viewed_at") val viewedAt: String?,
    val cameras: CameraRelation?,
)
private data class SignedUrlResponse(@SerializedName("signedURL") val signedUrl: String)
private data class CloudDevice(val id: String)
private data class InsertedId(val id: String)

class CloudClient(context: Context) {
    private val store = SecureStore(context.applicationContext)
    private val gson = Gson()
    private val baseUrl = BuildConfig.SUPABASE_URL.trimEnd('/')
    private val anonKey = BuildConfig.SUPABASE_ANON_KEY
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    val configured: Boolean get() = baseUrl.startsWith("https://") && anonKey.isNotBlank()
    val signedIn: Boolean get() = configured && store.get("cloud_refresh_token").isNotBlank()
    val email: String get() = store.get("cloud_email")
    val userId: String get() = store.get("cloud_user_id")

    suspend fun signIn(email: String, password: String) = withContext(Dispatchers.IO) {
        require(configured) { "Supabase is not configured in this build" }
        require(email.isNotBlank() && password.length >= 6) { "Enter a valid email and password" }
        val body = gson.toJson(mapOf("email" to email.trim(), "password" to password))
        val request = Request.Builder()
            .url("$baseUrl/auth/v1/token?grant_type=password")
            .header("apikey", anonKey)
            .post(body.toRequestBody(JSON))
            .build()
        val auth = executeJson<AuthResponse>(request)
        saveAuth(auth, email.trim())
        AppLogger.i("Cloud", "Supabase sign-in completed", mapOf("user_id" to auth.user?.id, "email" to email.trim()))
    }

    suspend fun signUp(email: String, password: String): String = withContext(Dispatchers.IO) {
        require(configured) { "Supabase is not configured in this build" }
        require(email.isNotBlank() && password.length >= 8) { "Use a valid email and a password of at least 8 characters" }
        val request = Request.Builder()
            .url("$baseUrl/auth/v1/signup")
            .header("apikey", anonKey)
            .post(gson.toJson(mapOf("email" to email.trim(), "password" to password)).toRequestBody(JSON))
            .build()
        val response: SignUpResponse = executeJson(request)
        AppLogger.i("Cloud", "Supabase account creation requested", mapOf("user_id" to response.user?.id, "email" to email.trim()))
        "Account created. Check your email if confirmation is enabled, then sign in."
    }

    suspend fun sendPasswordReset(email: String): String = withContext(Dispatchers.IO) {
        require(configured) { "Supabase is not configured in this build" }
        require(email.isNotBlank()) { "Enter your email first" }
        val request = Request.Builder()
            .url("$baseUrl/auth/v1/recover")
            .header("apikey", anonKey)
            .post(gson.toJson(mapOf("email" to email.trim())).toRequestBody(JSON))
            .build()
        executeAuthorized(request) { Unit }
        AppLogger.i("Cloud", "Password reset requested", mapOf("email" to email.trim()))
        "Password-reset email requested."
    }

    fun signOut() {
        store.remove("cloud_access_token", "cloud_refresh_token", "cloud_expires_at", "cloud_email", "cloud_user_id")
        AppLogger.i("Cloud", "Supabase session cleared")
    }

    suspend fun registerPushToken(deviceId: String, deviceName: String, pushToken: String) = withContext(Dispatchers.IO) {
        require(signedIn) { "Sign in to secure cloud access first" }
        val ownerId = userId.ifBlank { throw IllegalStateException("Cloud account identity is unavailable") }
        upsertAndroidDevice(deviceId, deviceName)
        val tokenPayload = mapOf(
            "owner_id" to ownerId,
            "device_id" to deviceId,
            "token" to pushToken,
            "updated_at" to Instant.now().toString(),
        )
        executeAuthorized(
            authorizedRequest("$baseUrl/rest/v1/push_tokens?on_conflict=token")
                .header("Prefer", "resolution=merge-duplicates,return=minimal")
                .post(gson.toJson(tokenPayload).toRequestBody(JSON))
                .build()
        ) { Unit }
        AppLogger.i("Cloud", "FCM token registered directly", mapOf("device_id" to deviceId, "token_suffix" to pushToken.takeLast(8)))
    }

    suspend fun listEvents(minutes: Int): List<EventRecord> = withContext(Dispatchers.IO) {
        val since = Instant.now().minusSeconds(minutes.coerceAtLeast(1).toLong() * 60).toString()
        val select = "id,occurred_at,person_confidence,face_result,person_name,media_path,viewed_at,cameras(name)"
        val url = "$baseUrl/rest/v1/events?select=${encode(select)}&occurred_at=gte.${encode(since)}&order=occurred_at.desc&limit=200"
        val request = authorizedRequest(url).get().build()
        val type = object : TypeToken<List<CloudEvent>>() {}.type
        val events: List<CloudEvent> = executeAuthorized(request) { gson.fromJson(it, type) }
        events.map { event ->
            EventRecord(
                id = event.id,
                timestamp = event.occurredAt,
                cameraName = event.cameras?.name ?: "Home camera",
                personConfidence = event.personConfidence,
                faceResult = event.faceResult,
                personName = event.personName,
                notificationStatus = "cloud",
                viewed = event.viewedAt != null,
                bboxX = null,
                bboxY = null,
                bboxWidth = null,
                bboxHeight = null,
            )
        }
    }

    suspend fun eventImage(eventId: String): ByteArray = withContext(Dispatchers.IO) {
        val selectUrl = "$baseUrl/rest/v1/events?select=media_path&id=eq.${encode(eventId)}&limit=1"
        val mediaRows: List<Map<String, String?>> = executeAuthorized(authorizedRequest(selectUrl).get().build()) {
            gson.fromJson(it, object : TypeToken<List<Map<String, String?>>>() {}.type)
        }
        val mediaPath = mediaRows.firstOrNull()?.get("media_path") ?: throw IllegalStateException("Cloud event media is unavailable")
        val encodedPath = mediaPath.split('/').joinToString("/") { encode(it) }
        val signRequest = authorizedRequest("$baseUrl/storage/v1/object/sign/event-media/$encodedPath")
            .post(gson.toJson(mapOf("expiresIn" to 300)).toRequestBody(JSON))
            .build()
        val signed: SignedUrlResponse = executeAuthorized(signRequest) { gson.fromJson(it, SignedUrlResponse::class.java) }
        val signedUrl = if (signed.signedUrl.startsWith("http")) signed.signedUrl else "$baseUrl/storage/v1${signed.signedUrl}"
        executeBytes(Request.Builder().url(signedUrl).get().build())
    }

    suspend fun sendVoiceMessage(
        file: File,
        durationMs: Int,
        volume: Int,
        sourceDeviceId: String,
    ): String = withContext(Dispatchers.IO) {
        require(signedIn) { "Sign in to secure cloud access first" }
        require(sourceDeviceId.isNotBlank()) { "The Android device is not paired" }
        require(file.exists() && file.length() in 45..5_000_000) { "Voice recording is invalid or too large" }
        require(durationMs in 1..30_000) { "Voice recording must be 30 seconds or shorter" }
        val ownerId = userId.ifBlank { throw IllegalStateException("Cloud account identity is unavailable") }
        val targetDeviceId = activeWindowsDeviceId()
        val voiceId = java.util.UUID.randomUUID().toString()
        val storagePath = "$ownerId/$sourceDeviceId/$voiceId.wav"
        val encodedPath = storagePath.split('/').joinToString("/") { encode(it) }
        val upload = Request.Builder()
            .url("$baseUrl/storage/v1/object/voice-media/$encodedPath")
            .header("apikey", anonKey)
            .header("Authorization", "Bearer ${ensureAccessToken()}")
            .header("x-upsert", "false")
            .post(file.readBytes().toRequestBody(WAV))
            .build()
        executeAuthorized(upload) { Unit }

        try {
            val expiry = Instant.now().plusSeconds(120).toString()
            val voicePayload = mapOf(
                "id" to voiceId,
                "owner_id" to ownerId,
                "source_device_id" to sourceDeviceId,
                "target_device_id" to targetDeviceId,
                "storage_path" to storagePath,
                "duration_ms" to durationMs,
                "size_bytes" to file.length(),
                "status" to "uploaded",
                "expires_at" to expiry,
            )
            val voiceRequest = authorizedRequest("$baseUrl/rest/v1/voice_messages")
                .header("Prefer", "return=minimal")
                .post(gson.toJson(voicePayload).toRequestBody(JSON))
                .build()
            executeAuthorized(voiceRequest) { Unit }

            val commandId = java.util.UUID.randomUUID().toString()
            val commandPayload = mapOf(
                "id" to commandId,
                "owner_id" to ownerId,
                "target_device_id" to targetDeviceId,
                "command_type" to "play_audio",
                "payload" to mapOf(
                    "voice_message_id" to voiceId,
                    "volume" to volume.coerceIn(0, 100),
                    "repeat_count" to 1,
                    "restore_volume" to true,
                ),
                "nonce" to (java.util.UUID.randomUUID().toString().replace("-", "") + java.util.UUID.randomUUID().toString().replace("-", "")),
                "expires_at" to expiry,
            )
            val commandRequest = authorizedRequest("$baseUrl/rest/v1/remote_commands")
                .header("Prefer", "return=minimal")
                .post(gson.toJson(commandPayload).toRequestBody(JSON))
                .build()
            executeAuthorized(commandRequest) { Unit }
            AppLogger.i("Cloud", "Remote voice command queued", mapOf("command_id" to commandId, "voice_id" to voiceId, "bytes" to file.length()))
            commandId
        } catch (error: Throwable) {
            runCatching { deleteStorageObject("voice-media", storagePath) }
            throw error
        }
    }

    suspend fun stopRemoteAudio(): String = withContext(Dispatchers.IO) {
        require(signedIn) { "Sign in to secure cloud access first" }
        val ownerId = userId.ifBlank { throw IllegalStateException("Cloud account identity is unavailable") }
        val targetDeviceId = activeWindowsDeviceId()
        val commandId = java.util.UUID.randomUUID().toString()
        val payload = mapOf(
            "id" to commandId,
            "owner_id" to ownerId,
            "target_device_id" to targetDeviceId,
            "command_type" to "stop_audio",
            "payload" to emptyMap<String, String>(),
            "nonce" to (java.util.UUID.randomUUID().toString().replace("-", "") + java.util.UUID.randomUUID().toString().replace("-", "")),
            "expires_at" to Instant.now().plusSeconds(60).toString(),
        )
        val request = authorizedRequest("$baseUrl/rest/v1/remote_commands")
            .header("Prefer", "return=minimal")
            .post(gson.toJson(payload).toRequestBody(JSON))
            .build()
        executeAuthorized(request) { Unit }
        AppLogger.i("Cloud", "Remote stop command queued", mapOf("command_id" to commandId))
        commandId
    }

    suspend fun createStreamSession(viewerDeviceId: String): StreamLaunch = withContext(Dispatchers.IO) {
        require(signedIn) { "Sign in to secure cloud access first" }
        require(runCatching { UUID.fromString(viewerDeviceId) }.isSuccess) { "Pair the phone again to create a valid cloud device identity" }
        upsertAndroidDevice(viewerDeviceId, "HomeGuard Android")
        val request = authorizedRequest("$baseUrl/functions/v1/create-stream")
            .post(gson.toJson(mapOf("viewer_device_id" to viewerDeviceId)).toRequestBody(JSON))
            .build()
        val launch: StreamLaunch = executeAuthorized(request) { gson.fromJson(it, StreamLaunch::class.java) }
        validateStreamLaunch(launch)
        AppLogger.i(
            "Cloud",
            "Remote stream session created",
            mapOf("session_id" to launch.sessionId, "ice_server_groups" to launch.iceServers.size),
        )
        launch.copy(signalingUrl = normalizeWebSocketUrl(launch.signalingUrl))
    }

    suspend fun signalingAccessToken(): String = withContext(Dispatchers.IO) {
        require(signedIn) { "Sign in to secure cloud access first" }
        ensureAccessToken()
    }

    suspend fun stopStream(sessionId: String): String = withContext(Dispatchers.IO) {
        require(signedIn) { "Sign in to secure cloud access first" }
        require(runCatching { UUID.fromString(sessionId) }.isSuccess) { "Stream session ID is invalid" }
        val ownerId = userId.ifBlank { throw IllegalStateException("Cloud account identity is unavailable") }
        val targetDeviceId = activeWindowsDeviceId()
        val commandId = UUID.randomUUID().toString()
        val commandPayload = mapOf(
            "id" to commandId,
            "owner_id" to ownerId,
            "target_device_id" to targetDeviceId,
            "command_type" to "stop_stream",
            "payload" to mapOf("session_id" to sessionId),
            "nonce" to (UUID.randomUUID().toString().replace("-", "") + UUID.randomUUID().toString().replace("-", "")),
            "expires_at" to Instant.now().plusSeconds(60).toString(),
        )
        executeAuthorized(
            authorizedRequest("$baseUrl/rest/v1/remote_commands")
                .header("Prefer", "return=minimal")
                .post(gson.toJson(commandPayload).toRequestBody(JSON))
                .build()
        ) { Unit }
        executeAuthorized(
            authorizedRequest("$baseUrl/rest/v1/stream_sessions?id=eq.${encode(sessionId)}")
                .header("Prefer", "return=minimal")
                .patch(gson.toJson(mapOf("status" to "closed", "updated_at" to Instant.now().toString())).toRequestBody(JSON))
                .build()
        ) { Unit }
        AppLogger.i("Cloud", "Remote stream stop queued", mapOf("session_id" to sessionId, "command_id" to commandId))
        commandId
    }

    private fun validateStreamLaunch(launch: StreamLaunch) {
        require(runCatching { UUID.fromString(launch.sessionId) }.isSuccess) { "Cloud returned an invalid stream session" }
        normalizeWebSocketUrl(launch.signalingUrl)
        require(launch.iceServers.size <= 8) { "Cloud returned too many ICE server groups" }
        launch.iceServers.forEach { server ->
            require(server.urls.isNotEmpty() && server.urls.size <= 8) { "Cloud returned invalid ICE server URLs" }
            server.urls.forEach { url ->
                require(url.length <= 512 && url.lowercase().startsWith(listOf("stun:", "stuns:", "turn:", "turns:"))) {
                    "Cloud returned an unsupported ICE URL"
                }
            }
            if (server.urls.any { it.lowercase().startsWith("turn:") || it.lowercase().startsWith("turns:") }) {
                require(!server.username.isNullOrBlank() && !server.credential.isNullOrBlank()) { "TURN credentials are missing" }
            }
        }
        require(runCatching { Instant.parse(launch.expiresAt).isAfter(Instant.now()) }.getOrDefault(false)) { "Stream session is already expired" }
    }

    private fun upsertAndroidDevice(deviceId: String, deviceName: String) {
        require(runCatching { UUID.fromString(deviceId) }.isSuccess) { "Android device identity is invalid; pair again" }
        val ownerId = userId.ifBlank { throw IllegalStateException("Cloud account identity is unavailable") }
        val payload = mapOf(
            "id" to deviceId,
            "owner_id" to ownerId,
            "name" to deviceName.take(100),
            "device_type" to "android",
            "last_seen_at" to Instant.now().toString(),
        )
        executeAuthorized(
            authorizedRequest("$baseUrl/rest/v1/devices?on_conflict=id")
                .header("Prefer", "resolution=merge-duplicates,return=minimal")
                .post(gson.toJson(payload).toRequestBody(JSON))
                .build()
        ) { Unit }
        AppLogger.d("Cloud", "Android cloud device heartbeat sent", mapOf("device_id" to deviceId))
    }

    private fun activeWindowsDeviceId(): String {
        val activeSince = encode(Instant.now().minusSeconds(90).toString())
        val url = "$baseUrl/rest/v1/devices?select=id&device_type=eq.windows_agent&revoked_at=is.null&last_seen_at=gte.$activeSince&order=last_seen_at.desc.nullslast&limit=1"
        val request = authorizedRequest(url).get().build()
        val rows: List<CloudDevice> = executeAuthorized(request) {
            gson.fromJson(it, object : TypeToken<List<CloudDevice>>() {}.type)
        }
        return rows.firstOrNull()?.id ?: throw IllegalStateException("No active Windows HomeGuard device is registered")
    }

    suspend fun markViewed(eventId: String) = withContext(Dispatchers.IO) {
        val request = authorizedRequest("$baseUrl/rest/v1/events?id=eq.${encode(eventId)}")
            .header("Prefer", "return=minimal")
            .patch(gson.toJson(mapOf("viewed_at" to Instant.now().toString())).toRequestBody(JSON))
            .build()
        executeAuthorized(request) { Unit }
    }

    suspend fun deleteEvent(eventId: String) = withContext(Dispatchers.IO) {
        val selectUrl = "$baseUrl/rest/v1/events?select=media_path&id=eq.${encode(eventId)}&limit=1"
        val rows: List<Map<String, String?>> = executeAuthorized(authorizedRequest(selectUrl).get().build()) {
            gson.fromJson(it, object : TypeToken<List<Map<String, String?>>>() {}.type)
        }
        rows.firstOrNull()?.get("media_path")?.let { path ->
            runCatching { deleteStorageObject("event-media", path) }
                .onFailure { AppLogger.w("Cloud", "Cloud event media deletion failed", mapOf("event_id" to eventId), it) }
        }
        val request = authorizedRequest("$baseUrl/rest/v1/events?id=eq.${encode(eventId)}")
            .header("Prefer", "return=minimal")
            .delete()
            .build()
        executeAuthorized(request) { Unit }
    }

    private fun deleteStorageObject(bucket: String, storagePath: String) {
        val encodedPath = storagePath.split('/').joinToString("/") { encode(it) }
        val request = authorizedRequest("$baseUrl/storage/v1/object/$bucket/$encodedPath").delete().build()
        executeAuthorized(request) { Unit }
    }

    private fun authorizedRequest(url: String): Request.Builder {
        val token = ensureAccessToken()
        return Request.Builder().url(url).header("apikey", anonKey).header("Authorization", "Bearer $token")
    }

    private fun ensureAccessToken(): String {
        val access = store.get("cloud_access_token")
        val expiresAt = store.get("cloud_expires_at").toLongOrNull() ?: 0L
        if (access.isNotBlank() && Instant.now().epochSecond < expiresAt - 60) return access
        return refreshAccessToken()
    }

    private fun refreshAccessToken(): String {
        val refresh = store.get("cloud_refresh_token")
        require(refresh.isNotBlank()) { "Sign in to cloud access again" }
        val request = Request.Builder()
            .url("$baseUrl/auth/v1/token?grant_type=refresh_token")
            .header("apikey", anonKey)
            .post(gson.toJson(mapOf("refresh_token" to refresh)).toRequestBody(JSON))
            .build()
        val auth = executeJson<AuthResponse>(request)
        saveAuth(auth, email)
        AppLogger.i("Cloud", "Supabase access token refreshed")
        return auth.accessToken
    }

    private fun saveAuth(auth: AuthResponse, email: String) {
        store.put("cloud_access_token", auth.accessToken)
        store.put("cloud_refresh_token", auth.refreshToken)
        store.put("cloud_expires_at", (Instant.now().epochSecond + auth.expiresIn).toString())
        store.put("cloud_email", auth.user?.email ?: email)
        auth.user?.id?.let { store.put("cloud_user_id", it) }
    }

    private fun <T> executeAuthorized(request: Request, parser: (String) -> T): T {
        val requestId = UUID.randomUUID().toString().take(16)
        val loggedRequest = request.newBuilder().header("X-Request-ID", requestId).build()
        val started = System.nanoTime()
        client.newCall(loggedRequest).execute().use { response ->
            val body = response.body?.string().orEmpty()
            val fields = mapOf(
                "request_id" to requestId,
                "method" to loggedRequest.method,
                "path" to loggedRequest.url.encodedPath,
                "status" to response.code,
                "duration_ms" to (System.nanoTime() - started) / 1_000_000,
            )
            if (!response.isSuccessful) {
                AppLogger.w("CloudNetwork", "Cloud request failed", fields)
                throw IllegalStateException("Cloud request failed (${response.code}): ${body.take(240)}")
            }
            AppLogger.i("CloudNetwork", "Cloud request completed", fields)
            return parser(body)
        }
    }

    private inline fun <reified T> executeJson(request: Request): T = executeAuthorized(request) { gson.fromJson(it, T::class.java) }

    private fun executeBytes(request: Request): ByteArray {
        val requestId = UUID.randomUUID().toString().take(16)
        val loggedRequest = request.newBuilder().header("X-Request-ID", requestId).build()
        val started = System.nanoTime()
        client.newCall(loggedRequest).execute().use { response ->
            val fields = mapOf(
                "request_id" to requestId,
                "path" to loggedRequest.url.encodedPath,
                "status" to response.code,
                "duration_ms" to (System.nanoTime() - started) / 1_000_000,
            )
            if (!response.isSuccessful) {
                AppLogger.w("CloudNetwork", "Cloud media request failed", fields)
                throw IllegalStateException("Cloud media request failed (${response.code})")
            }
            val bytes = response.body?.bytes() ?: throw IllegalStateException("Cloud media response was empty")
            AppLogger.i("CloudNetwork", "Cloud media request completed", fields + ("bytes" to bytes.size))
            return bytes
        }
    }

    private fun encode(value: String): String = URLEncoder.encode(value, Charsets.UTF_8.name()).replace("+", "%20")

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
        private val WAV = "audio/wav".toMediaType()
    }
}
