package com.noamjan.homeguard

import android.app.Application
import com.noamjan.homeguard.logging.AppLogger

class HomeGuardApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        AppLogger.initialize(this)
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            AppLogger.e(
                "Crash",
                "Uncaught application exception",
                mapOf("thread" to thread.name, "version" to BuildConfig.VERSION_NAME),
                error,
            )
            previous?.uncaughtException(thread, error)
        }
        AppLogger.i("Application", "HomeGuard application started", mapOf("version" to BuildConfig.VERSION_NAME))
    }
}
