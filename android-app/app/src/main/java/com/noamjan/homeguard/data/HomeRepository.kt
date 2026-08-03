package com.noamjan.homeguard.data

import android.content.Context
import android.os.Build
import com.google.android.gms.tasks.Tasks
import com.google.firebase.messaging.FirebaseMessaging
import com.noamjan.homeguard.logging.AppLogger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.UUID

data class DashboardData(
    val health: HealthResponse?,
    val events: List<EventRecord>,
    val localReachable: Boolean,
    val cloudReachable: Boolean,
)

class HomeRepository(context: Context, val client: AgentClient = AgentClient(context)) {
    val cloud = CloudClient(context)
    private val cacheDir = File(context.cacheDir, "event-images").apply { mkdirs() }

    suspend fun loadDashboard(minutes: Int = 15): DashboardData = withContext(Dispatchers.IO) {
        coroutineScope {
            val localJob = async { runCatching { client.api().health() to client.api().events(minutes = minutes) } }
            val cloudJob = async {
                if (cloud.signedIn) runCatching { cloud.listEvents(minutes) }
                else Result.success(emptyList())
            }
            val localResult = localJob.await()
            val cloudResult = cloudJob.await()
            val local = localResult.getOrNull()
            val cloudEvents = cloudResult.getOrNull().orEmpty()

            if (local == null && (!cloud.signedIn || cloudResult.isFailure)) {
                val localError = localResult.exceptionOrNull() ?: IllegalStateException("The Windows PC is unreachable")
                cloudResult.exceptionOrNull()?.let(localError::addSuppressed)
                throw localError
            }

            val merged = (local?.second.orEmpty() + cloudEvents)
                .distinctBy { it.id }
                .sortedByDescending { it.timestamp }

            AppLogger.i(
                "Repository",
                "Dashboard sources loaded",
                mapOf(
                    "local_reachable" to (local != null),
                    "cloud_reachable" to (cloudResult.isSuccess && cloud.signedIn),
                    "local_events" to local?.second?.size,
                    "cloud_events" to cloudEvents.size,
                    "merged_events" to merged.size,
                ),
            )
            DashboardData(
                health = local?.first,
                events = merged,
                localReachable = local != null,
                cloudReachable = cloudResult.isSuccess && cloud.signedIn,
            )
        }
    }

    suspend fun eventImage(eventId: String, force: Boolean = false): ByteArray = withContext(Dispatchers.IO) {
        val file = File(cacheDir, "$eventId.jpg")
        if (!force && file.exists() && file.length() > 0) return@withContext file.readBytes()

        val local = runCatching { client.api().eventImage(eventId).bytes() }
        val bytes = local.getOrElse { localError ->
            if (!cloud.signedIn) throw localError
            AppLogger.w("Repository", "Local event image unavailable; trying cloud", mapOf("event_id" to eventId), localError)
            cloud.eventImage(eventId)
        }
        file.writeBytes(bytes)
        AppLogger.d("Repository", "Event image cached", mapOf("event_id" to eventId, "bytes" to bytes.size))
        bytes
    }

    suspend fun snapshot(): ByteArray = withContext(Dispatchers.IO) { client.api().snapshot().bytes() }

    suspend fun startRemoteStream(): StreamSession = withContext(Dispatchers.IO) {
        require(client.paired) { "Pair the phone with the Windows agent first" }
        val launch = cloud.createStreamSession(client.deviceId)
        val accessToken = cloud.signalingAccessToken()
        StreamSession(launch, accessToken, client.deviceId)
    }

    suspend fun stopRemoteStream(sessionId: String) = withContext(Dispatchers.IO) {
        if (cloud.signedIn) cloud.stopStream(sessionId)
    }

    suspend fun markViewed(eventId: String) = withContext(Dispatchers.IO) {
        val attempts = coroutineScope {
            buildList {
                add(async { runCatching { client.api().markViewed(eventId) } })
                if (cloud.signedIn) add(async { runCatching { cloud.markViewed(eventId) } })
            }.awaitAll()
        }
        if (attempts.none { it.isSuccess }) {
            val error = attempts.firstNotNullOfOrNull { it.exceptionOrNull() }
                ?: IllegalStateException("No event source is available")
            throw error
        }
        AppLogger.d("Repository", "Event marked viewed", mapOf("event_id" to eventId))
    }

    suspend fun deleteEvent(eventId: String) = withContext(Dispatchers.IO) {
        val attempts = coroutineScope {
            buildList {
                add(async { runCatching { client.api().deleteEvent(eventId) } })
                if (cloud.signedIn) add(async { runCatching { cloud.deleteEvent(eventId) } })
            }.awaitAll()
        }
        if (attempts.none { it.isSuccess }) {
            val error = attempts.firstNotNullOfOrNull { it.exceptionOrNull() }
                ?: IllegalStateException("No event source is available")
            throw error
        }
        File(cacheDir, "$eventId.jpg").delete()
        AppLogger.i("Repository", "Event deleted", mapOf("event_id" to eventId))
    }

    suspend fun setPrivacyPaused(paused: Boolean): StateResponse = withContext(Dispatchers.IO) {
        if (paused) client.api().pauseCamera() else client.api().resumeCamera()
    }

    suspend fun signInCloud(email: String, password: String) {
        cloud.signIn(email, password)
    }

    suspend fun signUpCloud(email: String, password: String): String = cloud.signUp(email, password)
    suspend fun resetCloudPassword(email: String): String = cloud.sendPasswordReset(email)
    fun signOutCloud() = cloud.signOut()

    suspend fun sendAudio(file: File, volume: Int): PlaybackReceipt = withContext(Dispatchers.IO) {
        val localAttempt = runCatching {
            val api = client.api()
            val body = file.asRequestBody("audio/wav".toMediaType())
            val upload = api.uploadAudio(MultipartBody.Part.createFormData("file", file.name, body))
            val now = Instant.now()
            val commandId = UUID.randomUUID().toString()
            val receipt = api.playAudio(
                PlaybackRequest(
                    fileName = upload.fileName,
                    nonce = UUID.randomUUID().toString().replace("-", "") + UUID.randomUUID().toString().replace("-", ""),
                    issuedAt = now.toString(),
                    expiresAt = now.plus(90, ChronoUnit.SECONDS).toString(),
                    volume = volume,
                    commandId = commandId,
                )
            )
            AppLogger.i("Repository", "Local audio command sent", mapOf("command_id" to commandId, "duration" to upload.durationSeconds))
            receipt
        }
        localAttempt.getOrElse { localError ->
            if (!cloud.signedIn) throw localError
            val durationMs = wavDurationMs(file)
            AppLogger.w("Repository", "Local audio path unavailable; queuing secure cloud command", error = localError)
            val commandId = cloud.sendVoiceMessage(file, durationMs, volume, client.deviceId)
            PlaybackReceipt(true, "queued", "Queued securely for the Windows agent", commandId)
        }
    }

    suspend fun registerPushToken(providedToken: String? = null): Boolean = withContext(Dispatchers.IO) {
        val pushToken = providedToken ?: Tasks.await(FirebaseMessaging.getInstance().token)
        val deviceName = listOf(Build.MANUFACTURER, Build.MODEL).filter { it.isNotBlank() }.joinToString(" ").take(100)
        val safeName = deviceName.ifBlank { "Android phone" }
        runCatching {
            val response = client.api().registerPushToken(PushRegistrationRequest(pushToken, safeName))
            AppLogger.i("Repository", "FCM token registered through PC", mapOf("device_id" to response.deviceId, "token_suffix" to pushToken.takeLast(8)))
            response.registered
        }.getOrElse { localError ->
            if (!cloud.signedIn || client.deviceId.isBlank()) throw localError
            AppLogger.w("Repository", "PC push registration unavailable; registering directly in cloud", error = localError)
            cloud.registerPushToken(client.deviceId, safeName, pushToken)
            true
        }
    }

    suspend fun stopAudio(): PlaybackReceipt = withContext(Dispatchers.IO) {
        runCatching { client.api().stopAudio() }.getOrElse { localError ->
            if (!cloud.signedIn) throw localError
            val commandId = cloud.stopRemoteAudio()
            PlaybackReceipt(true, "queued", "Remote stop queued", commandId)
        }
    }

    private fun wavDurationMs(file: File): Int {
        require(file.length() in 45..5_000_000) { "Voice recording is invalid or too large" }
        java.io.RandomAccessFile(file, "r").use { input ->
            val header = ByteArray(44)
            input.readFully(header)
            require(String(header, 0, 4, Charsets.US_ASCII) == "RIFF" && String(header, 8, 4, Charsets.US_ASCII) == "WAVE") { "Voice recording is not a WAV file" }
            fun intLe(offset: Int): Int =
                (header[offset].toInt() and 0xff) or
                    ((header[offset + 1].toInt() and 0xff) shl 8) or
                    ((header[offset + 2].toInt() and 0xff) shl 16) or
                    ((header[offset + 3].toInt() and 0xff) shl 24)
            val byteRate = intLe(28)
            val dataBytes = intLe(40)
            require(byteRate > 0 && dataBytes > 0) { "Voice recording header is invalid" }
            return ((dataBytes.toLong() * 1000L) / byteRate).toInt().coerceIn(1, 30_000)
        }
    }
    suspend fun logs(): List<String> = withContext(Dispatchers.IO) { client.api().logs().lines }
}
