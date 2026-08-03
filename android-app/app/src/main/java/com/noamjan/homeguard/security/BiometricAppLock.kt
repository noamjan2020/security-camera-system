package com.noamjan.homeguard.security

import android.os.Build
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.noamjan.homeguard.logging.AppLogger

/**
 * Optional local app lock. HomeGuard never receives or stores biometric samples;
 * Android owns the prompt and returns only success/failure.
 */
class BiometricAppLock(private val activity: FragmentActivity) {
    private val store = SecureStore(activity)

    var enabled: Boolean
        get() = store.get(KEY_ENABLED, "false").toBooleanStrictOrNull() ?: false
        set(value) {
            store.put(KEY_ENABLED, value.toString())
            AppLogger.i("BiometricLock", "Biometric app lock setting changed", mapOf("enabled" to value))
        }

    fun isAvailable(): Boolean {
        val result = BiometricManager.from(activity).canAuthenticate(authenticators())
        AppLogger.d("BiometricLock", "Biometric availability checked", mapOf("result" to result))
        return result == BiometricManager.BIOMETRIC_SUCCESS
    }

    fun authenticate(reason: String, onResult: (Boolean, String?) -> Unit) {
        if (!isAvailable()) {
            onResult(false, "No enrolled biometric is available on this phone.")
            return
        }

        val prompt = BiometricPrompt(
            activity,
            ContextCompat.getMainExecutor(activity),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    AppLogger.i("BiometricLock", "Biometric authentication succeeded")
                    onResult(true, null)
                }

                override fun onAuthenticationFailed() {
                    AppLogger.w("BiometricLock", "Biometric authentication attempt rejected")
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    AppLogger.w(
                        "BiometricLock",
                        "Biometric authentication ended",
                        mapOf("error_code" to errorCode, "message" to errString.toString()),
                    )
                    onResult(false, errString.toString())
                }
            },
        )

        val builder = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Unlock HomeGuard")
            .setSubtitle(reason)
            .setAllowedAuthenticators(authenticators())
            .setConfirmationRequired(false)

        // Device-credential fallback is only safely supported with this combination
        // on Android 11+. Older devices use an enrolled biometric or cancel.
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            builder.setNegativeButtonText("Cancel")
        }

        prompt.authenticate(builder.build())
    }

    private fun authenticators(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
    } else {
        BiometricManager.Authenticators.BIOMETRIC_WEAK
    }

    private companion object {
        const val KEY_ENABLED = "biometric_app_lock_enabled"
    }
}
