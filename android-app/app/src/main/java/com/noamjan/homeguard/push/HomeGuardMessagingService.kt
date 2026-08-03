package com.noamjan.homeguard.push

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.noamjan.homeguard.MainActivity
import com.noamjan.homeguard.data.HomeRepository
import com.noamjan.homeguard.logging.AppLogger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class HomeGuardMessagingService : FirebaseMessagingService() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNewToken(token: String) {
        AppLogger.i("FCM", "Push token refreshed", mapOf("token_suffix" to token.takeLast(8)))
        getSharedPreferences("homeguard_push", MODE_PRIVATE).edit().putString("pending_fcm_token", token).apply()
        serviceScope.launch {
            runCatching {
                val repository = HomeRepository(applicationContext)
                if (repository.client.paired) repository.registerPushToken(token)
            }.onFailure { AppLogger.w("FCM", "Push token registration deferred", error = it) }
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val eventId = message.data["event_id"]
        val cameraName = message.data["camera_name"] ?: "Home camera"
        val detectedAt = message.data["detected_at"]
        AppLogger.i(
            "FCM",
            "Unknown-person notification received",
            mapOf("message_id" to message.messageId, "event_id" to eventId, "camera" to cameraName),
        )

        val requestCode = eventId?.hashCode() ?: message.messageId?.hashCode() ?: 1
        showNotification(message, requestCode, cameraName, detectedAt, null)

        if (!eventId.isNullOrBlank()) {
            serviceScope.launch {
                runCatching {
                    val repository = HomeRepository(applicationContext)
                    val bytes = repository.eventImage(eventId)
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                }.onSuccess { bitmap ->
                    if (bitmap != null) showNotification(message, requestCode, cameraName, detectedAt, bitmap)
                }.onFailure { AppLogger.w("FCM", "Notification screenshot preview unavailable", mapOf("event_id" to eventId), it) }
            }
        }
    }

    private fun showNotification(
        message: RemoteMessage,
        requestCode: Int,
        cameraName: String,
        detectedAt: String?,
        preview: Bitmap?,
    ) {
        val manager = getSystemService(NotificationManager::class.java)
        val channelId = "unknown_person_alerts"
        manager.createNotificationChannel(
            NotificationChannel(channelId, "Unknown person alerts", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Urgent alerts from your paired HomeGuard PC"
                enableVibration(true)
            }
        )
        val eventId = message.data["event_id"]
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra("event_id", eventId)
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            requestCode,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(message.notification?.title ?: "Unknown person detected")
            .setContentText(message.notification?.body ?: "$cameraName${detectedAt?.let { " · $it" } ?: ""}")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setGroup("homeguard_unknown_people")
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
        if (preview != null) {
            builder.setLargeIcon(preview).setStyle(
                NotificationCompat.BigPictureStyle()
                    .bigPicture(preview)
                    .bigLargeIcon(null as Bitmap?)
                    .setSummaryText("$cameraName · Open HomeGuard for details"),
            )
        } else {
            builder.setStyle(NotificationCompat.BigTextStyle().bigText("Open HomeGuard to review the screenshot and camera status."))
        }
        manager.notify(requestCode, builder.build())
    }
}
