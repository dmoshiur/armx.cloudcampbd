package ai.armx.managed.sessions

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import ai.armx.managed.MainActivity
import ai.armx.managed.R
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/** Visible lifetime marker for a user-started microphone/voice assistance session. */
class VisibleVoiceService : Service() {
    private var sessionId = ""
    private var apiBase = ""
    private var deviceId = ""
    private var deviceCredential = ""
    private var reportedEnd = false

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.voice_channel_name), NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "Visible while a user-started voice session may use the microphone." },
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        sessionId = intent?.getStringExtra(EXTRA_SESSION_ID).orEmpty()
        apiBase = intent?.getStringExtra(EXTRA_API_BASE).orEmpty().trimEnd('/')
        deviceId = intent?.getStringExtra(EXTRA_DEVICE_ID).orEmpty()
        deviceCredential = intent?.getStringExtra(EXTRA_DEVICE_CREDENTIAL).orEmpty()
        if (sessionId.isBlank() || apiBase.isBlank() || deviceId.isBlank() || deviceCredential.isBlank()) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(NOTIFICATION_ID, notification(sessionId))
        return START_NOT_STICKY
    }

    private fun notification(sessionId: String): android.app.Notification {
        val stop = PendingIntent.getBroadcast(
            this,
            101,
            Intent(this, SessionActionReceiver::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val open = PendingIntent.getActivity(
            this,
            102,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Voice session is active")
            .setContentText("Session ${sessionId.take(8)} · tap Stop to end")
            .setContentIntent(open)
            .setOngoing(true)
            .setAutoCancel(false)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addAction(0, "Stop voice session", stop)
            .build()
    }

    private fun reportSessionEnd() {
        if (reportedEnd || sessionId.isBlank() || apiBase.isBlank() || deviceId.isBlank() || deviceCredential.isBlank()) return
        reportedEnd = true
        val endSession = sessionId
        val endBase = apiBase
        val endDevice = deviceId
        val credential = deviceCredential
        Thread {
            var connection: HttpURLConnection? = null
            try {
                val encodedDevice = URLEncoder.encode(endDevice, StandardCharsets.UTF_8.name())
                val encodedSession = URLEncoder.encode(endSession, StandardCharsets.UTF_8.name())
                val endpoint = "$endBase/devices/$encodedDevice/consent-sessions/$encodedSession/device-end"
                val activeConnection = URL(endpoint).openConnection() as HttpURLConnection
                connection = activeConnection
                activeConnection.requestMethod = "POST"
                activeConnection.connectTimeout = NETWORK_TIMEOUT_MS
                activeConnection.readTimeout = NETWORK_TIMEOUT_MS
                activeConnection.instanceFollowRedirects = false
                activeConnection.setRequestProperty("X-Device-Token", credential)
                activeConnection.setRequestProperty("Content-Type", "application/json")
                activeConnection.doOutput = true
                activeConnection.outputStream.use { it.write("{}".toByteArray(StandardCharsets.UTF_8)) }
                activeConnection.responseCode
            } catch (_: Exception) {
                // Best effort; backend expiry remains the final fail-safe.
            } finally {
                connection?.disconnect()
            }
        }.start()
    }

    override fun onDestroy() {
        reportSessionEnd()
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_STOP = "ai.armx.managed.STOP_VOICE"
        const val EXTRA_SESSION_ID = "session_id"
        const val EXTRA_API_BASE = "voice_api_base"
        const val EXTRA_DEVICE_ID = "voice_device_id"
        const val EXTRA_DEVICE_CREDENTIAL = "voice_device_auth"
        private const val CHANNEL = "armx_voice"
        private const val NOTIFICATION_ID = 4302
        private const val NETWORK_TIMEOUT_MS = 5_000
    }
}
