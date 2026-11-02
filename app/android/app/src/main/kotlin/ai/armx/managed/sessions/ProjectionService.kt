package ai.armx.managed.sessions

import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import ai.armx.managed.MainActivity
import ai.armx.managed.R

/**
 * User-consented MediaProjection host. Frames are never stored. A later transport
 * can consume the ImageReader surface only while this visible foreground service
 * and Android's system projection indicator are active.
 */
class ProjectionService : Service() {
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.projection_channel_name), NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "Visible whenever the owner has consented to screen sharing." },
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        val data = intent?.parcelableIntent(EXTRA_DATA) ?: run {
            stopSelf()
            return START_NOT_STICKY
        }
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        if (resultCode != Activity.RESULT_OK) {
            stopSelf()
            return START_NOT_STICKY
        }
        val sessionId = intent.getStringExtra(EXTRA_SESSION_ID).orEmpty()
        startForeground(NOTIFICATION_ID, notification(sessionId))
        if (projection == null) startProjection(resultCode, data)
        return START_NOT_STICKY
    }

    private fun startProjection(resultCode: Int, data: Intent) {
        val manager = getSystemService(MediaProjectionManager::class.java)
        projection = manager.getMediaProjection(resultCode, data).also { mediaProjection ->
            mediaProjection.registerCallback(
                object : MediaProjection.Callback() {
                    override fun onStop() {
                        stopSelf()
                    }
                },
                Handler(Looper.getMainLooper()),
            )
            val metrics = resources.displayMetrics
            reader = ImageReader.newInstance(metrics.widthPixels, metrics.heightPixels, PixelFormat.RGBA_8888, 2)
                .apply {
                    // Until a consent-scoped transport is attached, immediately
                    // discard frames. Nothing is written to storage or logs.
                    setOnImageAvailableListener({ source -> source.acquireLatestImage()?.close() }, null)
                }
            display = mediaProjection.createVirtualDisplay(
                "A.R.M.X consented mirror",
                metrics.widthPixels,
                metrics.heightPixels,
                metrics.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader?.surface,
                null,
                null,
            )
        }
    }

    private fun notification(sessionId: String): android.app.Notification {
        val stop = Intent(this, SessionActionReceiver::class.java).setAction(ACTION_STOP)
        val stopAction = PendingIntent.getBroadcast(
            this,
            91,
            stop,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val open = PendingIntent.getActivity(
            this,
            92,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Screen sharing is active")
            .setContentText(if (sessionId.isBlank()) "Tap Stop to end immediately" else "Session ${sessionId.take(8)} · tap Stop to end")
            .setContentIntent(open)
            .setOngoing(true)
            .setAutoCancel(false)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addAction(0, "Stop sharing", stopAction)
            .build()
    }

    override fun onDestroy() {
        display?.release()
        display = null
        reader?.close()
        reader = null
        projection?.stop()
        projection = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    @Suppress("DEPRECATION")
    private fun Intent.parcelableIntent(key: String): Intent? =
        if (android.os.Build.VERSION.SDK_INT >= 33) getParcelableExtra(key, Intent::class.java)
        else getParcelableExtra(key)

    companion object {
        const val ACTION_STOP = "ai.armx.managed.STOP_PROJECTION"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "result_data"
        const val EXTRA_SESSION_ID = "session_id"
        private const val CHANNEL = "armx_projection"
        private const val NOTIFICATION_ID = 4301
    }
}
