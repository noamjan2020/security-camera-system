package com.noamjan.homeguard.ui

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.os.Build
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.noamjan.homeguard.HomeUiState
import com.noamjan.homeguard.HomeViewModel
import com.noamjan.homeguard.data.EventRecord
import com.noamjan.homeguard.logging.AppLogger
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val Night = Color(0xFF070A10)
private val Panel = Color(0xFF111722)
private val PanelBright = Color(0xFF192231)
private val Green = Color(0xFF54E39E)
private val Red = Color(0xFFFF6B78)
private val Amber = Color(0xFFFFC857)
private val Blue = Color(0xFF70A5FF)
private val Muted = Color(0xFF97A3B6)

private val HomeGuardColors = darkColorScheme(
    primary = Green,
    onPrimary = Color(0xFF052116),
    secondary = Blue,
    background = Night,
    surface = Panel,
    surfaceVariant = PanelBright,
    error = Red,
)

private enum class Tab(val label: String, val symbol: String) {
    HOME("Home", "⌂"),
    EVENTS("Events", "▤"),
    LIVE("Live", "◉"),
    TALK("Talk", "◖"),
    SETTINGS("Settings", "⚙"),
}

@Composable
fun HomeGuardRoot(
    viewModel: HomeViewModel,
    onScanPairingCode: () -> Unit,
    appLocked: Boolean,
    biometricEnabled: Boolean,
    biometricAvailable: Boolean,
    lockError: String?,
    onUnlock: () -> Unit,
    onSetBiometricEnabled: (Boolean) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    LaunchedEffect(state.paired) {
        if (
            state.paired &&
            Build.VERSION.SDK_INT >= 33 &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
        ) {
            (context as? Activity)?.requestPermissions(
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                1001,
            )
        }
    }

    MaterialTheme(colorScheme = HomeGuardColors) {
        Surface(Modifier.fillMaxSize(), color = Night) {
            when {
                appLocked -> {
                    AppLockScreen(
                        biometricAvailable = biometricAvailable,
                        lockError = lockError,
                        onUnlock = onUnlock,
                    )
                }

                !state.paired -> {
                    PairingScreen(
                        loading = state.loading,
                        error = state.error,
                        onScan = onScanPairingCode,
                        onPastePairingLink = viewModel::pair,
                        onDismissMessage = viewModel::clearMessage,
                    )
                }

                else -> {
                    PairedApp(
                        state = state,
                        viewModel = viewModel,
                        biometricEnabled = biometricEnabled,
                        biometricAvailable = biometricAvailable,
                        lockError = lockError,
                        onSetBiometricEnabled = onSetBiometricEnabled,
                    )
                }
            }
        }
    }
}

@Composable
private fun AppLockScreen(
    biometricAvailable: Boolean,
    lockError: String?,
    onUnlock: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Night)
            .padding(28.dp),
        contentAlignment = Alignment.Center,
    ) {
        Card(
            colors = CardDefaults.cardColors(containerColor = Panel),
            shape = RoundedCornerShape(28.dp),
        ) {
            Column(
                modifier = Modifier.padding(28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    modifier = Modifier
                        .size(72.dp)
                        .clip(CircleShape)
                        .background(Green.copy(alpha = .16f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("●", color = Green, fontSize = 32.sp)
                }

                Spacer(Modifier.height(18.dp))
                Text(
                    text = "HomeGuard locked",
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Black,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    text = if (biometricAvailable) {
                        "Authenticate to view your cameras, events and controls."
                    } else {
                        "Biometric authentication is currently unavailable."
                    },
                    color = Muted,
                )

                if (!lockError.isNullOrBlank()) {
                    Spacer(Modifier.height(14.dp))
                    Text(lockError, color = Red)
                }

                Spacer(Modifier.height(22.dp))
                Button(
                    onClick = onUnlock,
                    enabled = biometricAvailable,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Unlock HomeGuard")
                }
            }
        }
    }
}

@Composable
private fun PairingScreen(
    loading: Boolean,
    error: String?,
    onScan: () -> Unit,
    onPastePairingLink: (String) -> Unit,
    onDismissMessage: () -> Unit,
) {
    var showAdvanced by remember { mutableStateOf(false) }
    var pairingLink by remember { mutableStateOf("") }

    Box(
        Modifier.fillMaxSize().background(Night).padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(
                Modifier.size(76.dp).clip(RoundedCornerShape(24.dp)).background(Green.copy(alpha = .16f)),
                contentAlignment = Alignment.Center,
            ) { Text("◉", color = Green, fontSize = 38.sp) }
            Spacer(Modifier.height(18.dp))
            Text("HomeGuard", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Black)
            Text("Your home camera, without the creepy cloud camera account.", color = Muted)
            Spacer(Modifier.height(30.dp))

            Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(24.dp)) {
                Column(Modifier.padding(22.dp)) {
                    Text("Pair your Windows PC", fontWeight = FontWeight.Bold, fontSize = 20.sp)
                    Spacer(Modifier.height(6.dp))
                    Text("Open HomeGuard on the PC and scan its temporary QR code.", color = Muted)
                    Spacer(Modifier.height(18.dp))
                    Button(onClick = onScan, modifier = Modifier.fillMaxWidth(), enabled = !loading) {
                        Text("Scan pairing QR")
                    }
                    TextButton(onClick = { showAdvanced = !showAdvanced }, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                        Text(if (showAdvanced) "Hide advanced setup" else "Advanced local setup")
                    }
                    if (showAdvanced) {
                        OutlinedTextField(
                            value = pairingLink,
                            onValueChange = { pairingLink = it },
                            label = { Text("Temporary HomeGuard pairing link") },
                            supportingText = { Text("Use the link shown on the PC. It expires and works only once.") },
                            minLines = 2,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Spacer(Modifier.height(12.dp))
                        OutlinedButton(
                            onClick = { onPastePairingLink(pairingLink) },
                            enabled = pairingLink.startsWith("homeguard://pair?"),
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Claim pairing code") }
                    }
                }
            }
            if (error != null) {
                Spacer(Modifier.height(14.dp))
                MessageCard(error, error = true, onDismiss = onDismissMessage)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PairedApp(
    state: HomeUiState,
    viewModel: HomeViewModel,
    biometricEnabled: Boolean,
    biometricAvailable: Boolean,
    lockError: String?,
    onSetBiometricEnabled: (Boolean) -> Unit,
) {
    var tab by remember { mutableStateOf(Tab.HOME) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(state.error, state.info) {
        val message = state.error ?: state.info
        if (message != null) {
            snackbar.showSnackbar(message)
            viewModel.clearMessage()
        }
    }
    LaunchedEffect(state.selectedEventId) {
        if (state.selectedEventId != null) tab = Tab.EVENTS
    }

    Scaffold(
        containerColor = Night,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("HomeGuard", fontWeight = FontWeight.Black)
                        Text(statusSubtitle(state), color = statusColor(state), fontSize = 12.sp)
                    }
                },
                actions = {
                    TextButton(onClick = { viewModel.refresh() }, enabled = !state.refreshing) {
                        Text(if (state.refreshing) "Refreshing…" else "Refresh")
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar(containerColor = Panel) {
                Tab.entries.forEach { item ->
                    NavigationBarItem(
                        selected = tab == item,
                        onClick = {
                            if (tab == Tab.LIVE && item != Tab.LIVE) viewModel.stopLive()
                            tab = item
                        },
                        icon = { Text(item.symbol, fontSize = 20.sp) },
                        label = { Text(item.label, maxLines = 1) },
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (tab) {
                Tab.HOME -> HomeTab(state, viewModel, onOpenLive = { tab = Tab.LIVE }, onOpenTalk = { tab = Tab.TALK })
                Tab.EVENTS -> EventsTab(state, viewModel)
                Tab.LIVE -> LiveTab(state, viewModel)
                Tab.TALK -> TalkTab(state, viewModel)
                Tab.SETTINGS -> SettingsTab(
                    state = state,
                    viewModel = viewModel,
                    biometricEnabled = biometricEnabled,
                    biometricAvailable = biometricAvailable,
                    lockError = lockError,
                    onSetBiometricEnabled = onSetBiometricEnabled,
                )
            }
            if (state.loading) Box(Modifier.fillMaxSize().background(Night.copy(alpha = .7f)), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        }
    }

    state.selectedEventId?.let { id ->
        state.events.firstOrNull { it.id == id }?.let { event ->
            EventDialog(event, state.images[id], onClose = { viewModel.selectEvent(null) }, onDelete = viewModel::deleteSelectedEvent)
        }
    }
}

@Composable
private fun HomeTab(state: HomeUiState, viewModel: HomeViewModel, onOpenLive: () -> Unit, onOpenTalk: () -> Unit) {
    val health = state.health
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = statusColor(state).copy(alpha = .13f)), shape = RoundedCornerShape(24.dp)) {
                Row(Modifier.fillMaxWidth().padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(48.dp).clip(CircleShape).background(statusColor(state).copy(alpha = .2f)), contentAlignment = Alignment.Center) {
                        Text(if (health?.cameraActive == true) "●" else "○", color = statusColor(state), fontSize = 26.sp)
                    }
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(statusTitle(state), fontWeight = FontWeight.Black, fontSize = 21.sp)
                        Text(statusSubtitle(state), color = Muted)
                    }
                    Text("${health?.fps?.toInt() ?: 0} FPS", color = Muted)
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricCard("Events", state.events.size.toString(), Modifier.weight(1f))
                MetricCard("AI", "${health?.inferenceFps?.let { "%.1f".format(it) } ?: "0"}/s", Modifier.weight(1f))
                MetricCard("Disk", "${health?.diskFreeMb ?: 0} MB", Modifier.weight(1f))
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = onOpenLive, modifier = Modifier.weight(1f), enabled = health?.cameraActive == true) { Text("Open live") }
                OutlinedButton(onClick = onOpenTalk, modifier = Modifier.weight(1f), enabled = health?.emergencyDisabled != true) { Text("Talk to PC") }
            }
        }
        item { SectionTitle("Latest activity") }
        if (state.events.isEmpty()) {
            item { EmptyCard("No detections in this time range.") }
        } else {
            items(state.events.take(5), key = { it.id }) { event ->
                EventCard(event, state.images[event.id], onClick = { viewModel.selectEvent(event.id) })
            }
        }
    }
}

@Composable
private fun EventsTab(state: HomeUiState, viewModel: HomeViewModel) {
    var unknownOnly by remember { mutableStateOf(false) }
    val events = if (unknownOnly) state.events.filter { it.faceResult != "whitelisted" } else state.events
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Event timeline", fontWeight = FontWeight.Black, fontSize = 24.sp)
                Text("Tap an event for the full screenshot.", color = Muted)
            }
            OutlinedButton(onClick = { unknownOnly = !unknownOnly }) { Text(if (unknownOnly) "Unknown only" else "All events") }
        }
        if (events.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(18.dp), contentAlignment = Alignment.Center) { EmptyCard("Nothing to show.") }
        } else {
            LazyColumn(contentPadding = PaddingValues(horizontal = 18.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(events, key = { it.id }) { event ->
                    EventCard(event, state.images[event.id], onClick = { viewModel.selectEvent(event.id) })
                }
            }
        }
    }
}

@Composable
private fun LiveTab(state: HomeUiState, viewModel: HomeViewModel) {
    LaunchedEffect(Unit) { viewModel.startLive() }
    Column(Modifier.fillMaxSize().padding(18.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text("Live preview", fontWeight = FontWeight.Black, fontSize = 24.sp, modifier = Modifier.align(Alignment.Start))
        Text(
            if (state.remoteStream != null) "Low-latency encrypted WebRTC with short-lived TURN access."
            else "Lightweight private-LAN preview while remote WebRTC connects.",
            color = Muted,
            modifier = Modifier.align(Alignment.Start),
        )
        Spacer(Modifier.height(16.dp))
        Card(
            Modifier.fillMaxWidth().aspectRatio(16f / 9f),
            shape = RoundedCornerShape(22.dp),
            colors = CardDefaults.cardColors(containerColor = Color.Black),
        ) {
            val remote = state.remoteStream
            if (remote != null) {
                WebRtcLiveView(
                    session = remote,
                    modifier = Modifier.fillMaxSize(),
                    onStatus = viewModel::updateLiveStatus,
                )
            } else {
                ByteImage(state.liveFrame, Modifier.fillMaxSize(), ContentScale.Fit, "Live camera")
            }
        }
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(onClick = { if (state.liveRunning) viewModel.stopLive() else viewModel.startLive() }) {
                Text(if (state.liveRunning) "Stop stream" else "Reconnect")
            }
            OutlinedButton(onClick = { viewModel.refresh() }) { Text("Check status") }
        }
        Spacer(Modifier.height(12.dp))
        Text(
            state.liveStatus.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() },
            color = if (state.liveRunning) Green else Muted,
        )
    }
}

@Composable
private fun TalkTab(state: HomeUiState, viewModel: HomeViewModel) {
    val context = LocalContext.current
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) viewModel.startRecording()
    }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(22.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Talk to your PC", fontWeight = FontWeight.Black, fontSize = 25.sp, modifier = Modifier.align(Alignment.Start))
        Text("The microphone starts only after you press record.", color = Muted, modifier = Modifier.align(Alignment.Start))
        Spacer(Modifier.height(34.dp))
        Box(
            Modifier.size(170.dp).clip(CircleShape).background(if (state.recording) Red.copy(alpha = .18f) else Green.copy(alpha = .14f)).clickable {
                if (state.recording) viewModel.stopRecording()
                else if (viewModel.microphonePermissionGranted()) viewModel.startRecording()
                else permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            },
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(if (state.recording) "■" else "●", fontSize = 52.sp, color = if (state.recording) Red else Green)
                Text(if (state.recording) "Stop" else "Record", fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.height(18.dp))
        Text("Status: ${state.playbackStatus}", color = Muted)
        Spacer(Modifier.height(24.dp))
        Text("PC playback volume: ${state.speakerVolume}%", modifier = Modifier.align(Alignment.Start))
        Slider(value = state.speakerVolume.toFloat(), onValueChange = { viewModel.setSpeakerVolume(it.toInt()) }, valueRange = 0f..100f)
        if (state.recordingFile != null && !state.recording) {
            Button(onClick = viewModel::sendRecording, enabled = !state.audioSending, modifier = Modifier.fillMaxWidth()) {
                Text(if (state.audioSending) "Sending…" else "Send and play on PC")
            }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(onClick = viewModel::cancelRecording, modifier = Modifier.fillMaxWidth()) { Text("Delete recording") }
        }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = viewModel::stopRemoteAudio, modifier = Modifier.fillMaxWidth()) { Text("Stop PC audio") }
    }
}

@Composable
private fun SettingsTab(
    state: HomeUiState,
    viewModel: HomeViewModel,
    biometricEnabled: Boolean,
    biometricAvailable: Boolean,
    lockError: String?,
    onSetBiometricEnabled: (Boolean) -> Unit,
) {
    var showDisconnect by remember { mutableStateOf(false) }
    var cloudEmail by remember(state.cloudEmail) { mutableStateOf(state.cloudEmail) }
    var cloudPassword by remember { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { SectionTitle("Privacy and safety") }
        item {
            SettingsCard(
                title = if (state.health?.privacyPaused == true) "Camera paused" else if (state.localReachable) "Camera active" else "PC offline",
                body = if (state.health?.emergencyDisabled == true) "Emergency disable is active. It can only be cleared on the PC." else "Pause detection and live view without closing the app.",
            ) {
                Button(
                    onClick = { viewModel.setPrivacyPaused(state.health?.privacyPaused != true) },
                    enabled = state.localReachable && state.health?.emergencyDisabled != true,
                ) { Text(if (state.health?.privacyPaused == true) "Resume" else "Privacy pause") }
            }
        }
        item { SectionTitle("Connection") }
        item {
            SettingsCard("Paired Windows agent", viewModel.repository.client.baseUrl) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(if (state.localReachable) "Reachable on this network" else "Not reachable right now", color = if (state.localReachable) Green else Amber, fontSize = 12.sp)
                    OutlinedButton(onClick = { showDisconnect = true }) { Text("Disconnect") }
                }
            }
        }
        if (state.cloudConfigured) {
            item {
                SettingsCard(
                    "Secure cloud history",
                    if (state.cloudSignedIn) "Connected as ${state.cloudEmail}. Events and images remain available when the PC is unreachable." else "Sign in to the same HomeGuard account to view cloud-backed alerts outside your home network.",
                ) {
                    if (state.cloudSignedIn) {
                        OutlinedButton(onClick = viewModel::signOutCloud) { Text("Sign out of cloud") }
                    } else {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            OutlinedTextField(
                                value = cloudEmail,
                                onValueChange = { cloudEmail = it },
                                label = { Text("Email") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            OutlinedTextField(
                                value = cloudPassword,
                                onValueChange = { cloudPassword = it },
                                label = { Text("Password") },
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation(),
                                modifier = Modifier.fillMaxWidth(),
                            )
                            Button(
                                onClick = { viewModel.signInCloud(cloudEmail, cloudPassword) },
                                enabled = cloudEmail.isNotBlank() && cloudPassword.length >= 6 && !state.loading,
                                modifier = Modifier.fillMaxWidth(),
                            ) { Text(if (state.loading) "Working…" else "Connect cloud history") }
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                TextButton(
                                    onClick = { viewModel.signUpCloud(cloudEmail, cloudPassword) },
                                    enabled = cloudEmail.isNotBlank() && cloudPassword.length >= 8 && !state.loading,
                                ) { Text("Create account") }
                                TextButton(
                                    onClick = { viewModel.resetCloudPassword(cloudEmail) },
                                    enabled = cloudEmail.isNotBlank() && !state.loading,
                                ) { Text("Forgot password") }
                            }
                        }
                    }
                }
            }
        } else {
            item {
                SettingsCard("Secure cloud history", "This build has no Supabase URL or anon key. Local pairing still works, but remote history is unavailable.") {
                    Text("Configure HOMEGUARD_SUPABASE_URL and HOMEGUARD_SUPABASE_ANON_KEY when building the APK.", color = Muted, fontSize = 12.sp)
                }
            }
        }
        item { SectionTitle("App security") }
        item {
            SettingsCard(
                title = "Biometric app lock",
                body = when {
                    biometricEnabled ->
                        "HomeGuard locks after being in the background for 15 seconds."
                    biometricAvailable ->
                        "Protect cameras, events and remote controls with your device lock."
                    else ->
                        "Set up a fingerprint, face unlock or secure device credential first."
                },
            ) {
                Button(
                    onClick = { onSetBiometricEnabled(!biometricEnabled) },
                    enabled = biometricAvailable || biometricEnabled,
                ) {
                    Text(
                        if (biometricEnabled) {
                            "Disable app lock"
                        } else {
                            "Enable app lock"
                        }
                    )
                }

                if (!lockError.isNullOrBlank()) {
                    Spacer(Modifier.height(8.dp))
                    Text(lockError, color = Red, fontSize = 12.sp)
                }
            }
        }

        item { SectionTitle("Diagnostics") }
        item {
            SettingsCard("Debug logs", "Both the app and PC keep rotating logs with request IDs and failures. Secrets and authorization headers are redacted.") {
                Button(onClick = viewModel::loadPcLogs, enabled = state.localReachable) { Text("Load PC logs") }
            }
        }
        if (state.pcLogs.isNotEmpty()) {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(18.dp)) {
                    Text(state.pcLogs.takeLast(80).joinToString("\n"), modifier = Modifier.padding(14.dp), fontSize = 10.sp, color = Muted)
                }
            }
        }
    }
    if (showDisconnect) {
        AlertDialog(
            onDismissRequest = { showDisconnect = false },
            title = { Text("Disconnect phone?") },
            text = { Text("You will need to pair again to see the camera.") },
            confirmButton = { TextButton(onClick = { showDisconnect = false; viewModel.clearPairing() }) { Text("Disconnect", color = Red) } },
            dismissButton = { TextButton(onClick = { showDisconnect = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun EventDialog(event: EventRecord, bytes: ByteArray?, onClose: () -> Unit, onDelete: () -> Unit) {
    Dialog(onDismissRequest = onClose) {
        Card(Modifier.fillMaxWidth().fillMaxHeight(.9f), shape = RoundedCornerShape(24.dp), colors = CardDefaults.cardColors(containerColor = Panel)) {
            Column(Modifier.fillMaxSize()) {
                ByteImage(bytes, Modifier.fillMaxWidth().weight(1f).background(Color.Black), ContentScale.Fit, "Detection screenshot")
                Column(Modifier.padding(18.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(eventTitle(event), fontWeight = FontWeight.Black, fontSize = 22.sp)
                            Text(formatTime(event.timestamp), color = Muted)
                        }
                        StatusPill(event)
                    }
                    Spacer(Modifier.height(12.dp))
                    Text("${(event.personConfidence * 100).toInt()}% person confidence · ${event.cameraName}", color = Muted)
                    Text("Delivery: ${event.notificationStatus}", color = Muted)
                    Spacer(Modifier.height(14.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(onClick = onClose, modifier = Modifier.weight(1f)) { Text("Close") }
                        OutlinedButton(onClick = onDelete, modifier = Modifier.weight(1f), colors = ButtonDefaults.outlinedButtonColors(contentColor = Red)) { Text("Delete") }
                    }
                }
            }
        }
    }
}

@Composable
private fun EventCard(event: EventRecord, bytes: ByteArray?, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = if (event.viewed) Panel else PanelBright),
    ) {
        Row(Modifier.height(112.dp)) {
            ByteImage(bytes, Modifier.width(150.dp).fillMaxHeight().background(Color.Black), ContentScale.Crop, "Event thumbnail")
            Column(Modifier.weight(1f).padding(14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(eventTitle(event), fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    StatusPill(event)
                }
                Spacer(Modifier.height(5.dp))
                Text(formatTime(event.timestamp), color = Muted, fontSize = 12.sp)
                Text("${(event.personConfidence * 100).toInt()}% confidence", color = Muted, fontSize = 12.sp)
                if (!event.viewed) Text("NEW", color = Green, fontWeight = FontWeight.Bold, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun ByteImage(bytes: ByteArray?, modifier: Modifier, scale: ContentScale, description: String) {
    if (bytes == null) {
        Box(modifier, contentAlignment = Alignment.Center) { CircularProgressIndicator(modifier = Modifier.size(26.dp), strokeWidth = 2.dp) }
        return
    }
    val bitmap = remember(bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap() }
    if (bitmap != null) Image(bitmap, contentDescription = description, modifier = modifier, contentScale = scale)
    else Box(modifier, contentAlignment = Alignment.Center) { Text("Image unavailable", color = Muted) }
}

@Composable
private fun MetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier, colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp)) {
            Text(value, fontWeight = FontWeight.Black, fontSize = 18.sp, maxLines = 1)
            Text(label, color = Muted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun SettingsCard(title: String, body: String, action: @Composable () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(body, color = Muted, fontSize = 13.sp)
            Spacer(Modifier.height(12.dp))
            action()
        }
    }
}

@Composable private fun SectionTitle(value: String) = Text(value, fontWeight = FontWeight.Black, fontSize = 19.sp)

@Composable
private fun EmptyCard(text: String) {
    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(18.dp)) {
        Text(text, modifier = Modifier.fillMaxWidth().padding(28.dp), color = Muted)
    }
}

@Composable
private fun MessageCard(message: String, error: Boolean, onDismiss: () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = (if (error) Red else Green).copy(alpha = .14f))) {
        Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(message, modifier = Modifier.weight(1f), color = if (error) Red else Green)
            TextButton(onClick = onDismiss) { Text("Dismiss") }
        }
    }
}

@Composable
private fun StatusPill(event: EventRecord) {
    val unknown = event.faceResult != "whitelisted"
    Text(
        if (unknown) "UNKNOWN" else "KNOWN",
        modifier = Modifier.clip(RoundedCornerShape(50)).background((if (unknown) Red else Green).copy(alpha = .15f)).padding(horizontal = 8.dp, vertical = 4.dp),
        color = if (unknown) Red else Green,
        fontSize = 9.sp,
        fontWeight = FontWeight.Black,
    )
}

private fun eventTitle(event: EventRecord): String = if (event.faceResult == "whitelisted") event.personName ?: "Whitelisted person" else "Unknown person"

private fun formatTime(value: String): String = runCatching {
    DateTimeFormatter.ofPattern("MMM d · HH:mm:ss").withZone(ZoneId.systemDefault()).format(Instant.parse(value))
}.getOrDefault(value)

private fun statusTitle(state: HomeUiState): String = when {
    state.health?.emergencyDisabled == true -> "Emergency disabled"
    state.health?.privacyPaused == true -> "Privacy paused"
    state.health?.cameraActive == true -> "Camera active"
    state.health == null && state.cloudReachable -> "PC offline"
    state.health == null -> "Connecting"
    else -> "Camera unavailable"
}

private fun statusSubtitle(state: HomeUiState): String = when {
    state.health?.emergencyDisabled == true -> "Clear it locally on the Windows PC"
    state.health?.privacyPaused == true -> "No camera frames are being processed"
    state.health?.cameraActive == true -> "Agent online · ${state.health.version}"
    state.health == null && state.cloudReachable -> "Secure cloud event history is still available"
    state.error != null -> state.error
    else -> "Waiting for the Windows agent"
}

private fun statusColor(state: HomeUiState): Color = when {
    state.health?.emergencyDisabled == true -> Red
    state.health?.privacyPaused == true -> Amber
    state.health?.cameraActive == true -> Green
    else -> Muted
}
