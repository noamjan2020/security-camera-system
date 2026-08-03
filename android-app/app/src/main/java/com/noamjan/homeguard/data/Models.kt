package com.noamjan.homeguard.data

import com.google.gson.annotations.SerializedName

data class HealthResponse(
    val status: String,
    val version: String,
    @SerializedName("camera_active") val cameraActive: Boolean,
    @SerializedName("privacy_paused") val privacyPaused: Boolean,
    @SerializedName("emergency_disabled") val emergencyDisabled: Boolean,
    @SerializedName("last_frame_at") val lastFrameAt: String?,
    @SerializedName("last_event_at") val lastEventAt: String?,
    val fps: Double,
    @SerializedName("inference_fps") val inferenceFps: Double,
    @SerializedName("upload_queue_depth") val uploadQueueDepth: Int,
    @SerializedName("cloud_enabled") val cloudEnabled: Boolean,
    @SerializedName("disk_free_mb") val diskFreeMb: Int,
    @SerializedName("webrtc_available") val webRtcAvailable: Boolean = false,
    @SerializedName("webrtc_active") val webRtcActive: Boolean = false,
    @SerializedName("webrtc_session_id") val webRtcSessionId: String? = null,
    @SerializedName("webrtc_last_error") val webRtcLastError: String = "",
)

data class EventRecord(
    val id: String,
    val timestamp: String,
    @SerializedName("camera_name") val cameraName: String,
    @SerializedName("person_confidence") val personConfidence: Double,
    @SerializedName("face_result") val faceResult: String,
    @SerializedName("person_name") val personName: String?,
    @SerializedName("notification_status") val notificationStatus: String,
    val viewed: Boolean,
    @SerializedName("bbox_x") val bboxX: Int?,
    @SerializedName("bbox_y") val bboxY: Int?,
    @SerializedName("bbox_width") val bboxWidth: Int?,
    @SerializedName("bbox_height") val bboxHeight: Int?,
)

data class StateResponse(
    @SerializedName("privacy_paused") val privacyPaused: Boolean,
    @SerializedName("emergency_disabled") val emergencyDisabled: Boolean,
    @SerializedName("emergency_disabled_at") val emergencyDisabledAt: String?,
    @SerializedName("emergency_reason") val emergencyReason: String?,
)

data class AudioUploadResponse(
    @SerializedName("file_name") val fileName: String,
    val size: Long,
    @SerializedName("duration_seconds") val durationSeconds: Double,
    @SerializedName("sample_rate") val sampleRate: Int,
)

data class PlaybackRequest(
    @SerializedName("file_name") val fileName: String,
    val nonce: String,
    @SerializedName("issued_at") val issuedAt: String,
    @SerializedName("expires_at") val expiresAt: String,
    val volume: Int = 100,
    @SerializedName("repeat_count") val repeatCount: Int = 1,
    @SerializedName("command_id") val commandId: String,
    @SerializedName("restore_volume") val restoreVolume: Boolean = true,
)

data class PlaybackReceipt(
    val accepted: Boolean,
    val status: String,
    val detail: String,
    @SerializedName("command_id") val commandId: String?,
)

data class LogsResponse(val lines: List<String>)


data class IceServerConfig(
    val urls: List<String>,
    val username: String? = null,
    val credential: String? = null,
)

data class StreamLaunch(
    @SerializedName("session_id") val sessionId: String,
    @SerializedName("signaling_url") val signalingUrl: String,
    @SerializedName("ice_servers") val iceServers: List<IceServerConfig>,
    @SerializedName("expires_at") val expiresAt: String,
)

data class StreamSession(
    val launch: StreamLaunch,
    val accessToken: String,
    val viewerDeviceId: String,
)

data class PairingPayload(val url: String, val code: String) {
    companion object {
        fun parse(raw: String): PairingPayload {
            val value = raw.trim()
            require(value.startsWith("homeguard://pair?")) { "Not a HomeGuard pairing code" }
            val query = value.substringAfter('?')
            val pairs = query.split('&').mapNotNull { part ->
                val separator = part.indexOf('=')
                if (separator <= 0) null else part.substring(0, separator) to java.net.URLDecoder.decode(part.substring(separator + 1), "UTF-8")
            }.toMap()
            val url = normalizeBaseUrl(pairs["url"].orEmpty())
            val code = pairs["code"].orEmpty()
            require(code.length >= 32) { "Pairing code is invalid" }
            return PairingPayload(url, code)
        }
    }
}



data class PushRegistrationRequest(
    val token: String,
    @SerializedName("device_name") val deviceName: String,
)

data class PushRegistrationResponse(
    val registered: Boolean,
    @SerializedName("device_id") val deviceId: String,
)

data class PairClaimRequest(
    val code: String,
    @SerializedName("device_name") val deviceName: String,
)

data class PairClaimResponse(
    @SerializedName("device_id") val deviceId: String,
    val token: String,
    @SerializedName("api_url") val apiUrl: String,
)

fun normalizeBaseUrl(value: String): String {
    val trimmed = value.trim()
    val uri = java.net.URI(trimmed)
    val scheme = uri.scheme?.lowercase()
    require(scheme == "http" || scheme == "https") { "URL must use HTTP or HTTPS" }
    val host = uri.host ?: throw IllegalArgumentException("URL host is missing")
    require(uri.userInfo == null && uri.fragment == null) { "URL contains unsupported components" }
    if (scheme == "http") {
        require(isPrivateLanHost(host)) { "Unencrypted HTTP is allowed only for a private LAN address" }
    }
    val normalized = uri.toString().trimEnd('/')
    return "$normalized/"
}

fun normalizeWebSocketUrl(value: String): String {
    val trimmed = value.trim()
    val uri = java.net.URI(trimmed)
    require(uri.scheme?.lowercase() == "wss") { "Remote signaling must use WSS" }
    require(uri.host != null && uri.userInfo == null && uri.fragment == null) { "Signaling URL is invalid" }
    return uri.toString()
}

private fun isPrivateLanHost(host: String): Boolean {
    if (host == "localhost" || host == "127.0.0.1" || host == "10.0.2.2") return true
    val parts = host.split('.').mapNotNull { it.toIntOrNull() }
    if (parts.size != 4 || parts.any { it !in 0..255 }) return false
    return parts[0] == 10 ||
        (parts[0] == 172 && parts[1] in 16..31) ||
        (parts[0] == 192 && parts[1] == 168) ||
        (parts[0] == 169 && parts[1] == 254)
}
