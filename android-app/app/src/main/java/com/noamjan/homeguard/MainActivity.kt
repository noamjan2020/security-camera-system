package com.noamjan.homeguard

import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.fragment.app.FragmentActivity
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.noamjan.homeguard.logging.AppLogger
import com.noamjan.homeguard.security.BiometricAppLock
import com.noamjan.homeguard.ui.HomeGuardRoot

class MainActivity : FragmentActivity() {
    private val viewModel by viewModels<HomeViewModel>()
    private lateinit var biometricLock: BiometricAppLock
    private var appLocked by mutableStateOf(false)
    private var lockError by mutableStateOf<String?>(null)
    private var backgroundedAtMs: Long = 0L
    private var promptActive = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        biometricLock = BiometricAppLock(this)
        appLocked = biometricLock.enabled
        enableEdgeToEdge()
        setContent {
            HomeGuardRoot(
                viewModel = viewModel,
                onScanPairingCode = ::scanPairingCode,
                appLocked = appLocked,
                biometricEnabled = biometricLock.enabled,
                biometricAvailable = biometricLock.isAvailable(),
                lockError = lockError,
                onUnlock = { requestUnlock("Confirm it is you to view your cameras and events.") },
                onSetBiometricEnabled = ::setBiometricEnabled,
            )
        }
        handleIntent(intent)
        if (appLocked) requestUnlock("Confirm it is you to open HomeGuard.")
    }

    override fun onStart() {
        super.onStart()
        val awayForMs = if (backgroundedAtMs == 0L) 0L else SystemClock.elapsedRealtime() - backgroundedAtMs
        if (biometricLock.enabled && awayForMs >= LOCK_AFTER_BACKGROUND_MS) {
            appLocked = true
            requestUnlock("Confirm it is you to return to HomeGuard.")
        }
    }

    override fun onStop() {
        backgroundedAtMs = SystemClock.elapsedRealtime()
        super.onStop()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun setBiometricEnabled(enabled: Boolean) {
        lockError = null
        if (!enabled) {
            biometricLock.enabled = false
            appLocked = false
            return
        }
        if (!biometricLock.isAvailable()) {
            lockError = "Set up a fingerprint, face unlock, or secure device credential first."
            return
        }
        requestUnlock("Authenticate once to enable the HomeGuard app lock.") { success ->
            if (success) {
                biometricLock.enabled = true
                appLocked = false
            }
        }
    }

    private fun requestUnlock(reason: String, after: ((Boolean) -> Unit)? = null) {
        if (promptActive) return
        promptActive = true
        lockError = null
        biometricLock.authenticate(reason) { success, error ->
            promptActive = false
            if (success) {
                appLocked = false
                lockError = null
            } else if (!error.isNullOrBlank()) {
                lockError = error
            }
            after?.invoke(success)
        }
    }

    private fun handleIntent(intent: Intent?) {
        val eventId = intent?.getStringExtra("event_id") ?: return
        AppLogger.i("MainActivity", "Notification deep link received", mapOf("event_id" to eventId))
        viewModel.selectEvent(eventId)
    }

    private fun scanPairingCode() {
        val options = GmsBarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .enableAutoZoom()
            .build()
        GmsBarcodeScanning.getClient(this, options)
            .startScan()
            .addOnSuccessListener { barcode ->
                barcode.rawValue?.let(viewModel::pair)
                    ?: AppLogger.w("MainActivity", "QR scanner returned no raw value")
            }
            .addOnCanceledListener { AppLogger.i("MainActivity", "QR scan cancelled") }
            .addOnFailureListener { error ->
                AppLogger.e("MainActivity", "QR scan failed", error = error)
            }
    }

    private companion object {
        const val LOCK_AFTER_BACKGROUND_MS = 15_000L
    }
}
