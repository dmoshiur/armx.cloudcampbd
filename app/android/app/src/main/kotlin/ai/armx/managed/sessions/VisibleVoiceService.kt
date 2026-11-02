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

/** Visible lifetime marker for a user-started microphone/voice assistance session. */
class VisibleVoiceService : Service() {
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
        startForeground(NOTIFICATION_ID, notification(intent?.getStringExtra(EXTRA_SESSION_ID).orEmpty()))
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
            .setContentText(if (sessionId.isBlank()) "Microphone use remains visible and stoppable" else "Session ${sessionId.take(8)} · tap Stop to end")
            .setContentIntent(open)
            .setOngoing(true)
            .setAutoCancel(false)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addAction(0, "Stop voice session", stop)
            .build()
    }

    override fun onDestroy() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_STOP = "ai.armx.managed.STOP_VOICE"
        const val EXTRA_SESSION_ID = "session_id"
        private const val CHANNEL = "armx_voice"
        private const val NOTIFICATION_ID = 4302
    }
}
