package com.noamjan.homeguard.logging

import android.content.Context
import android.util.Log
import java.io.File
import java.time.Instant
import java.util.concurrent.Executors

object AppLogger {
    private const val MAX_BYTES = 1_000_000L
    private const val MAX_FILES = 3
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "homeguard-log-writer").apply { isDaemon = true }
    }
    @Volatile private var logDir: File? = null

    fun initialize(context: Context) {
        logDir = File(context.filesDir, "logs").apply { mkdirs() }
    }

    fun d(tag: String, message: String, fields: Map<String, Any?> = emptyMap()) = write("DEBUG", tag, message, fields, null)
    fun i(tag: String, message: String, fields: Map<String, Any?> = emptyMap()) = write("INFO", tag, message, fields, null)
    fun w(tag: String, message: String, fields: Map<String, Any?> = emptyMap(), error: Throwable? = null) = write("WARN", tag, message, fields, error)
    fun e(tag: String, message: String, fields: Map<String, Any?> = emptyMap(), error: Throwable? = null) = write("ERROR", tag, message, fields, error)

    private fun write(level: String, tag: String, message: String, fields: Map<String, Any?>, error: Throwable?) {
        val logcatMessage = if (fields.isEmpty()) message else "$message $fields"
        when (level) {
            "DEBUG" -> Log.d(tag, logcatMessage, error)
            "INFO" -> Log.i(tag, logcatMessage, error)
            "WARN" -> Log.w(tag, logcatMessage, error)
            else -> Log.e(tag, logcatMessage, error)
        }
        val directory = logDir ?: return
        val line = buildString {
            append('{')
            append("\"ts\":\"").append(escape(Instant.now().toString())).append("\",")
            append("\"level\":\"").append(level).append("\",")
            append("\"tag\":\"").append(escape(tag)).append("\",")
            append("\"thread\":\"").append(escape(Thread.currentThread().name)).append("\",")
            append("\"message\":\"").append(escape(message)).append('"')
            fields.forEach { (key, value) ->
                append(',').append('"').append(escape(key)).append("\":\"").append(escape(value?.toString() ?: "null")).append('"')
            }
            error?.let {
                append(",\"error\":\"").append(escape(it.stackTraceToString())).append('"')
            }
            append("}\n")
        }
        executor.execute {
            runCatching {
                rotateIfNeeded(directory)
                File(directory, "homeguard-mobile.jsonl").appendText(line, Charsets.UTF_8)
            }.onFailure { Log.e("AppLogger", "File logging failed", it) }
        }
    }

    fun tail(maxLines: Int = 300): List<String> {
        val file = logDir?.let { File(it, "homeguard-mobile.jsonl") } ?: return emptyList()
        if (!file.exists()) return emptyList()
        return runCatching { file.readLines().takeLast(maxLines.coerceIn(10, 2000)) }.getOrDefault(emptyList())
    }

    private fun rotateIfNeeded(directory: File) {
        val active = File(directory, "homeguard-mobile.jsonl")
        if (!active.exists() || active.length() < MAX_BYTES) return
        File(directory, "homeguard-mobile.$MAX_FILES.jsonl").delete()
        for (index in MAX_FILES - 1 downTo 1) {
            val source = File(directory, "homeguard-mobile.$index.jsonl")
            if (source.exists()) source.renameTo(File(directory, "homeguard-mobile.${index + 1}.jsonl"))
        }
        active.renameTo(File(directory, "homeguard-mobile.1.jsonl"))
    }

    private fun escape(value: String): String = value
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
}
