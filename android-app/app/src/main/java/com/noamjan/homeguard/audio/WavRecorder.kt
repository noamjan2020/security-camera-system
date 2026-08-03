package com.noamjan.homeguard.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import com.noamjan.homeguard.logging.AppLogger
import java.io.File
import java.io.RandomAccessFile
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class WavRecorder(private val context: Context) {
    private val sampleRate = 16_000
    private val channelConfig = AudioFormat.CHANNEL_IN_MONO
    private val encoding = AudioFormat.ENCODING_PCM_16BIT
    private val recording = AtomicBoolean(false)
    private var audioRecord: AudioRecord? = null
    private var worker: Thread? = null
    private var outputFile: File? = null

    fun hasPermission(): Boolean = ContextCompat.checkSelfPermission(
        context,
        Manifest.permission.RECORD_AUDIO,
    ) == PackageManager.PERMISSION_GRANTED

    fun start(maxSeconds: Int = 30): File {
        check(hasPermission()) { "Microphone permission is required" }
        check(recording.compareAndSet(false, true)) { "Recording already active" }
        val minBuffer = AudioRecord.getMinBufferSize(sampleRate, channelConfig, encoding)
        check(minBuffer > 0) { "Audio input is unavailable" }
        val bufferSize = maxOf(minBuffer * 2, 4096)
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            sampleRate,
            channelConfig,
            encoding,
            bufferSize,
        )
        check(recorder.state == AudioRecord.STATE_INITIALIZED) { "Microphone could not be initialized" }
        val file = File(context.cacheDir, "homeguard_${System.currentTimeMillis()}.wav")
        outputFile = file
        audioRecord = recorder
        recorder.startRecording()
        AppLogger.i("WavRecorder", "Recording started", mapOf("sample_rate" to sampleRate, "buffer" to bufferSize))

        worker = thread(name = "homeguard-audio-record", isDaemon = true) {
            RandomAccessFile(file, "rw").use { output ->
                writeHeader(output, 0)
                val buffer = ByteArray(bufferSize)
                val deadline = System.nanoTime() + maxSeconds * 1_000_000_000L
                var dataBytes = 0L
                while (recording.get() && System.nanoTime() < deadline) {
                    val read = recorder.read(buffer, 0, buffer.size)
                    if (read > 0) {
                        output.write(buffer, 0, read)
                        dataBytes += read
                    } else if (read < 0) {
                        AppLogger.e("WavRecorder", "AudioRecord read failed", mapOf("code" to read))
                        break
                    }
                }
                recording.set(false)
                rewriteSizes(output, dataBytes)
                AppLogger.i("WavRecorder", "Recording finished", mapOf("bytes" to dataBytes))
            }
            runCatching { recorder.stop() }
            recorder.release()
            audioRecord = null
        }
        return file
    }

    fun stop(): File? {
        recording.set(false)
        worker?.join(2_000)
        worker = null
        return outputFile?.takeIf { it.exists() && it.length() > 44 }
    }

    fun cancel() {
        val file = stop()
        file?.delete()
        outputFile = null
        AppLogger.i("WavRecorder", "Recording cancelled")
    }

    fun isRecording(): Boolean = recording.get()

    private fun writeHeader(file: RandomAccessFile, dataSize: Long) {
        file.seek(0)
        val byteRate = sampleRate * 1 * 16 / 8
        file.writeBytes("RIFF")
        writeIntLE(file, (36 + dataSize).toInt())
        file.writeBytes("WAVE")
        file.writeBytes("fmt ")
        writeIntLE(file, 16)
        writeShortLE(file, 1)
        writeShortLE(file, 1)
        writeIntLE(file, sampleRate)
        writeIntLE(file, byteRate)
        writeShortLE(file, 2)
        writeShortLE(file, 16)
        file.writeBytes("data")
        writeIntLE(file, dataSize.toInt())
    }

    private fun rewriteSizes(file: RandomAccessFile, dataSize: Long) {
        file.seek(4)
        writeIntLE(file, (36 + dataSize).toInt())
        file.seek(40)
        writeIntLE(file, dataSize.toInt())
    }

    private fun writeIntLE(file: RandomAccessFile, value: Int) {
        file.write(byteArrayOf(value.toByte(), (value shr 8).toByte(), (value shr 16).toByte(), (value shr 24).toByte()))
    }

    private fun writeShortLE(file: RandomAccessFile, value: Int) {
        file.write(byteArrayOf(value.toByte(), (value shr 8).toByte()))
    }
}
