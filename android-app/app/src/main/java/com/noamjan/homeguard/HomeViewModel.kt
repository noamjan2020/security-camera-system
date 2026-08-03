package com.noamjan.homeguard

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.noamjan.homeguard.audio.WavRecorder
import com.noamjan.homeguard.data.EventRecord
import com.noamjan.homeguard.data.HealthResponse
import com.noamjan.homeguard.data.HomeRepository
import com.noamjan.homeguard.data.PairingPayload
import com.noamjan.homeguard.data.StreamSession
import com.noamjan.homeguard.logging.AppLogger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.File

data class HomeUiState(
    val paired: Boolean = false,
    val loading: Boolean = false,
    val refreshing: Boolean = false,
    val health: HealthResponse? = null,
    val events: List<EventRecord> = emptyList(),
    val images: Map<String, ByteArray> = emptyMap(),
    val liveFrame: ByteArray? = null,
    val liveRunning: Boolean = false,
    val remoteStream: StreamSession? = null,
    val liveStatus: String = "idle",
    val selectedEventId: String? = null,
    val error: String? = null,
    val info: String? = null,
    val recording: Boolean = false,
    val recordingFile: File? = null,
    val audioSending: Boolean = false,
    val playbackStatus: String = "idle",
    val speakerVolume: Int = 100,
    val pcLogs: List<String> = emptyList(),
    val localReachable: Boolean = false,
    val cloudReachable: Boolean = false,
    val cloudConfigured: Boolean = false,
    val cloudSignedIn: Boolean = false,
    val cloudEmail: String = "",
)

class HomeViewModel(application: Application) : AndroidViewModel(application) {
    val repository = HomeRepository(application)
    private val recorder = WavRecorder(application)
    private val _state = MutableStateFlow(
        HomeUiState(
            paired = repository.client.paired,
            cloudConfigured = repository.cloud.configured,
            cloudSignedIn = repository.cloud.signedIn,
            cloudEmail = repository.cloud.email,
        )
    )
    val state: StateFlow<HomeUiState> = _state.asStateFlow()
    private var liveJob: Job? = null

    init {
        AppLogger.i("HomeViewModel", "ViewModel created", mapOf("paired" to repository.client.paired))
        if (repository.client.paired) refresh(initial = true)
    }

    fun pair(rawPayload: String) {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            runCatching {
                val payload = PairingPayload.parse(rawPayload)
                repository.client.claimPairing(payload)
            }.onSuccess { response ->
                _state.update { it.copy(paired = true, loading = false, error = null, info = "Paired successfully") }
                AppLogger.i("HomeViewModel", "Pairing accepted", mapOf("device_id" to response.deviceId))
                viewModelScope.launch {
                    runCatching { repository.registerPushToken() }
                        .onFailure { AppLogger.w("HomeViewModel", "Push registration deferred", error = it) }
                }
                refresh(initial = true)
            }.onFailure { error ->
                _state.update { it.copy(loading = false) }
                showError(error.message ?: "Invalid or expired pairing code", error)
            }
        }
    }

    fun clearPairing() {
        stopLive()
        repository.client.clearPairing()
        _state.value = HomeUiState(
            paired = false,
            info = "Device disconnected",
            cloudConfigured = repository.cloud.configured,
            cloudSignedIn = repository.cloud.signedIn,
            cloudEmail = repository.cloud.email,
        )
    }

    fun refresh(initial: Boolean = false, minutes: Int = 15) {
        viewModelScope.launch {
            _state.update { it.copy(loading = initial && it.health == null, refreshing = !initial, error = null) }
            runCatching { repository.loadDashboard(minutes) }
                .onSuccess { dashboard ->
                    _state.update {
                        it.copy(
                            paired = repository.client.paired,
                            loading = false,
                            refreshing = false,
                            health = dashboard.health,
                            events = dashboard.events,
                            localReachable = dashboard.localReachable,
                            cloudReachable = dashboard.cloudReachable,
                            cloudConfigured = repository.cloud.configured,
                            cloudSignedIn = repository.cloud.signedIn,
                            cloudEmail = repository.cloud.email,
                            error = null,
                        )
                    }
                    AppLogger.i(
                        "HomeViewModel",
                        "Dashboard refreshed",
                        mapOf(
                            "events" to dashboard.events.size,
                            "local_reachable" to dashboard.localReachable,
                            "cloud_reachable" to dashboard.cloudReachable,
                        ),
                    )
                    dashboard.events.take(8).forEach { loadImage(it.id) }
                }
                .onFailure { error ->
                    _state.update { it.copy(loading = false, refreshing = false, error = friendly(error)) }
                    AppLogger.e("HomeViewModel", "Dashboard refresh failed", error = error)
                }
        }
    }

    fun selectEvent(eventId: String?) {
        _state.update { it.copy(selectedEventId = eventId) }
        if (eventId != null) {
            loadImage(eventId)
            viewModelScope.launch(Dispatchers.IO) {
                runCatching { repository.markViewed(eventId) }
                    .onSuccess {
                        _state.update { state ->
                            state.copy(events = state.events.map { event -> if (event.id == eventId) event.copy(viewed = true) else event })
                        }
                    }
                    .onFailure { AppLogger.w("HomeViewModel", "Mark viewed failed", mapOf("event_id" to eventId), it) }
            }
        }
    }

    fun loadImage(eventId: String, force: Boolean = false) {
        if (!force && _state.value.images.containsKey(eventId)) return
        viewModelScope.launch {
            runCatching { repository.eventImage(eventId, force) }
                .onSuccess { bytes -> _state.update { it.copy(images = it.images + (eventId to bytes)) } }
                .onFailure { AppLogger.w("HomeViewModel", "Image load failed", mapOf("event_id" to eventId), it) }
        }
    }

    fun deleteSelectedEvent() {
        val eventId = _state.value.selectedEventId ?: return
        viewModelScope.launch {
            runCatching { repository.deleteEvent(eventId) }
                .onSuccess {
                    _state.update {
                        it.copy(
                            selectedEventId = null,
                            events = it.events.filterNot { event -> event.id == eventId },
                            images = it.images - eventId,
                            info = "Event deleted",
                        )
                    }
                }
                .onFailure { showError(friendly(it), it) }
        }
    }

    fun setPrivacyPaused(paused: Boolean) {
        viewModelScope.launch {
            runCatching { repository.setPrivacyPaused(paused) }
                .onSuccess { response ->
                    _state.update { state ->
                        state.copy(
                            health = state.health?.copy(
                                cameraActive = !response.privacyPaused && !response.emergencyDisabled,
                                privacyPaused = response.privacyPaused,
                                emergencyDisabled = response.emergencyDisabled,
                            ),
                            info = if (paused) "Privacy pause enabled" else "Camera resumed",
                        )
                    }
                    if (paused) stopLive()
                }
                .onFailure { showError(friendly(it), it) }
        }
    }

    fun startLive() {
        if (liveJob?.isActive == true) return
        _state.update { it.copy(liveRunning = true, liveStatus = "connecting", error = null) }
        liveJob = viewModelScope.launch {
            AppLogger.i("HomeViewModel", "Live preview starting")
            val remote = if (repository.cloud.signedIn) runCatching { repository.startRemoteStream() } else null
            if (remote?.isSuccess == true) {
                val session = remote.getOrThrow()
                _state.update {
                    it.copy(
                        remoteStream = session,
                        liveFrame = null,
                        liveStatus = "opening secure WebRTC",
                        info = "Remote Live View session created",
                    )
                }
                AppLogger.i("HomeViewModel", "Remote Live View created", mapOf("session_id" to session.launch.sessionId))
                awaitCancellation()
            }
            remote?.exceptionOrNull()?.let { error ->
                AppLogger.w("HomeViewModel", "Remote Live View unavailable; falling back to private-LAN snapshots", error = error)
                _state.update { it.copy(liveStatus = "LAN fallback") }
            }
            while (_state.value.liveRunning) {
                runCatching { repository.snapshot() }
                    .onSuccess { bytes -> _state.update { it.copy(liveFrame = bytes, liveStatus = "LAN live") } }
                    .onFailure { error ->
                        _state.update { it.copy(error = friendly(error), liveStatus = "offline") }
                        AppLogger.w("HomeViewModel", "Live frame failed", error = error)
                    }
                delay(750)
            }
        }
    }

    fun updateLiveStatus(status: String) {
        _state.update { it.copy(liveStatus = status.take(160)) }
    }

    fun stopLive() {
        val sessionId = _state.value.remoteStream?.launch?.sessionId
        _state.update { it.copy(liveRunning = false, remoteStream = null, liveStatus = "stopped") }
        liveJob?.cancel()
        liveJob = null
        if (sessionId != null) {
            viewModelScope.launch(Dispatchers.IO) {
                runCatching { repository.stopRemoteStream(sessionId) }
                    .onFailure { AppLogger.w("HomeViewModel", "Remote stream cleanup failed", mapOf("session_id" to sessionId), it) }
            }
        }
        AppLogger.i("HomeViewModel", "Live preview stopped", mapOf("session_id" to sessionId))
    }

    fun startRecording(): Boolean {
        return runCatching {
            val file = recorder.start(30)
            _state.update { it.copy(recording = true, recordingFile = file, error = null, playbackStatus = "recording") }
            true
        }.onFailure { showError(it.message ?: "Recording failed", it) }.getOrDefault(false)
    }

    fun stopRecording() {
        val file = recorder.stop()
        _state.update { it.copy(recording = false, recordingFile = file, playbackStatus = if (file != null) "ready" else "idle") }
    }

    fun cancelRecording() {
        recorder.cancel()
        _state.update { it.copy(recording = false, recordingFile = null, playbackStatus = "idle") }
    }

    fun sendRecording() {
        val file = _state.value.recordingFile ?: return
        viewModelScope.launch {
            _state.update { it.copy(audioSending = true, playbackStatus = "uploading", error = null) }
            runCatching { repository.sendAudio(file, _state.value.speakerVolume) }
                .onSuccess { receipt ->
                    file.delete()
                    _state.update {
                        it.copy(
                            audioSending = false,
                            recordingFile = null,
                            playbackStatus = receipt.status,
                            info = "Message sent to PC",
                        )
                    }
                }
                .onFailure {
                    _state.update { state -> state.copy(audioSending = false, playbackStatus = "failed", error = friendly(it)) }
                    AppLogger.e("HomeViewModel", "Audio send failed", error = it)
                }
        }
    }

    fun stopRemoteAudio() {
        viewModelScope.launch {
            runCatching { repository.stopAudio() }
                .onSuccess { _state.update { state -> state.copy(playbackStatus = it.status) } }
                .onFailure { showError(friendly(it), it) }
        }
    }

    fun setSpeakerVolume(value: Int) {
        _state.update { it.copy(speakerVolume = value.coerceIn(0, 100)) }
    }

    fun loadPcLogs() {
        viewModelScope.launch {
            runCatching { repository.logs() }
                .onSuccess { lines -> _state.update { it.copy(pcLogs = lines) } }
                .onFailure { showError(friendly(it), it) }
        }
    }


    fun signInCloud(email: String, password: String) {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            runCatching { repository.signInCloud(email, password) }
                .onSuccess {
                    _state.update {
                        it.copy(
                            loading = false,
                            cloudConfigured = repository.cloud.configured,
                            cloudSignedIn = repository.cloud.signedIn,
                            cloudEmail = repository.cloud.email,
                            info = "Cloud access connected",
                        )
                    }
                    viewModelScope.launch {
                        runCatching { repository.registerPushToken() }
                            .onFailure { AppLogger.w("HomeViewModel", "Cloud push registration deferred", error = it) }
                    }
                    refresh(initial = false)
                }
                .onFailure {
                    _state.update { state -> state.copy(loading = false) }
                    showError("Cloud sign-in failed: ${friendly(it)}", it)
                }
        }
    }


    fun signUpCloud(email: String, password: String) {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            runCatching { repository.signUpCloud(email, password) }
                .onSuccess { message -> _state.update { it.copy(loading = false, info = message) } }
                .onFailure {
                    _state.update { state -> state.copy(loading = false) }
                    showError("Account creation failed: ${friendly(it)}", it)
                }
        }
    }

    fun resetCloudPassword(email: String) {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            runCatching { repository.resetCloudPassword(email) }
                .onSuccess { message -> _state.update { it.copy(loading = false, info = message) } }
                .onFailure {
                    _state.update { state -> state.copy(loading = false) }
                    showError("Password reset failed: ${friendly(it)}", it)
                }
        }
    }

    fun signOutCloud() {
        repository.signOutCloud()
        _state.update {
            it.copy(
                cloudSignedIn = false,
                cloudReachable = false,
                cloudEmail = "",
                info = "Cloud access disconnected",
            )
        }
        refresh(initial = false)
    }

    fun clearMessage() {
        _state.update { it.copy(error = null, info = null) }
    }

    fun microphonePermissionGranted(): Boolean = recorder.hasPermission()

    private fun showError(message: String, error: Throwable? = null) {
        _state.update { it.copy(error = message) }
        AppLogger.e("HomeViewModel", message, error = error)
    }

    private fun friendly(error: Throwable): String = when {
        error.message?.contains("401") == true || error.message?.contains("403") == true -> "Pairing was rejected. Pair the phone again."
        error.message?.contains("423") == true -> "Emergency disable is active on the PC. Clear it locally."
        error.message?.contains("Failed to connect") == true -> "The PC is offline or unreachable."
        else -> error.message ?: "Something went wrong"
    }

    override fun onCleared() {
        stopLive()
        recorder.cancel()
        super.onCleared()
    }
}
