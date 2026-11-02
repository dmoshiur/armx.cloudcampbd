package ai.armx.managed.sessions

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import android.util.DisplayMetrics
import androidx.core.app.NotificationCompat
import ai.armx.managed.MainActivity
import ai.armx.managed.R
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Foreground-only MediaProjection host. Android owns the capture-consent dialog;
 * A.R.M.X keeps a persistent disclosure with a one-tap stop action for the whole session.
 * Frames are transient JPEGs sent only to the active, consent-scoped backend endpoint.
 */
class ProjectionService : Service() {
    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var captureThread: HandlerThread? = null
    private val uploadExecutor = Executors.newSingleThreadExecutor()
    private val uploadInFlight = AtomicBoolean(false)
    private val rejectedFrames = AtomicInteger(0)
    private var lastFrameAt = 0L
    private var sessionId = ""
    private var apiBase = ""
    private var deviceId = ""
    private var deviceToken = ""
    private var stopping = false

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            stopCapture(notifyBackend = true)
            stopSelf()
        }
    }

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopCapture(notifyBackend = true)
            stopSelf()
            return START_NOT_STICKY
        }
        if (projection != null) return START_NOT_STICKY

        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
            ?: Activity.RESULT_CANCELED
        val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        sessionId = intent?.getStringExtra(EXTRA_SESSION_ID).orEmpty()
        apiBase = intent?.getStringExtra(EXTRA_API_BASE).orEmpty().trimEnd('/')
        deviceId = intent?.getStringExtra(EXTRA_DEVICE_ID).orEmpty()
        deviceToken = intent?.getStringExtra(EXTRA_DEVICE_CREDENTIAL).orEmpty()
        if (
            resultCode != Activity.RESULT_OK || data == null || sessionId.isBlank() ||
            apiBase.isBlank() || deviceId.isBlank() || deviceToken.isBlank()
        ) {
            stopSelf()
            return START_NOT_STICKY
        }

        startForeground(NOTIFICATION_ID, notification(sessionId))
        val manager = getSystemService(MediaProjectionManager::class.java)
        val activeProjection = manager.getMediaProjection(resultCode, data)
        if (activeProjection == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        activeProjection.registerCallback(projectionCallback, Handler(mainLooper))
        projection = activeProjection
        beginCapture()
        return START_NOT_STICKY
    }

    private fun beginCapture() {
        val metrics = resources.displayMetrics
        val width = metrics.widthPixels.coerceAtLeast(1)
        val height = metrics.heightPixels.coerceAtLeast(1)
        val density = metrics.densityDpi.takeIf { it > 0 } ?: DisplayMetrics.DENSITY_DEFAULT
        val thread = HandlerThread("armx-visible-screen-capture").also { it.start() }
        captureThread = thread
        val handler = Handler(thread.looper)
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        imageReader = reader
        reader.setOnImageAvailableListener({ source -> captureLatestFrame(source, width, height) }, handler)
        virtualDisplay = projection?.createVirtualDisplay(
            "A.R.M.X visible screen share",
            width,
            height,
            density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface,
            null,
            handler,
        )
    }

    private fun captureLatestFrame(source: ImageReader, width: Int, height: Int) {
        val image = source.acquireLatestImage() ?: return
        try {
            val now = SystemClock.elapsedRealtime()
            if (now - lastFrameAt < FRAME_INTERVAL_MS || !uploadInFlight.compareAndSet(false, true)) return
            lastFrameAt = now
            val plane = image.planes.firstOrNull() ?: return
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val paddedWidth = width + (rowStride - pixelStride * width) / pixelStride
            val padded = Bitmap.createBitmap(paddedWidth, height, Bitmap.Config.ARGB_8888)
            padded.copyPixelsFromBuffer(plane.buffer)
            val frame = Bitmap.createBitmap(padded, 0, 0, width, height)
            if (frame !== padded) padded.recycle()
            val scale = minOf(1f, MAX_FRAME_EDGE.toFloat() / maxOf(width, height).toFloat())
            val uploadBitmap = if (scale < 1f) {
                Bitmap.createScaledBitmap(frame, (width * scale).toInt(), (height * scale).toInt(), true)
            } else {
                frame
            }
            if (uploadBitmap !== frame) frame.recycle()
            val output = ByteArrayOutputStream()
            uploadBitmap.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, output)
            uploadBitmap.recycle()
            val jpeg = output.toByteArray()
            uploadExecutor.execute {
                try {
                    uploadFrame(jpeg)
                } finally {
                    uploadInFlight.set(false)
                }
            }
        } catch (_: Exception) {
            uploadInFlight.set(false)
        } finally {
            image.close()
        }
    }

    private fun uploadFrame(jpeg: ByteArray) {
        if (jpeg.isEmpty() || jpeg.size > MAX_FRAME_BYTES || stopping) return
        val connection = openConnection("frame", "POST")
        try {
            connection.setRequestProperty("Content-Type", "image/jpeg")
            connection.setFixedLengthStreamingMode(jpeg.size)
            connection.doOutput = true
            connection.outputStream.use { it.write(jpeg) }
            val status = connection.responseCode
            val shouldStop = when {
                status in 200..299 -> {
                    rejectedFrames.set(0)
                    false
                }
                status == HttpURLConnection.HTTP_CONFLICT -> rejectedFrames.incrementAndGet() >= MAX_REJECTED_FRAMES
                status == HttpURLConnection.HTTP_UNAUTHORIZED ||
                    status == HttpURLConnection.HTTP_FORBIDDEN ||
                    status == HttpURLConnection.HTTP_GONE -> true
                else -> false
            }
            if (shouldStop) {
                Handler(mainLooper).post {
                    stopCapture(notifyBackend = false)
                    stopSelf()
                }
            }
        } catch (_: Exception) {
            // A later frame retries automatically; no frame is stored on disk.
        } finally {
            connection.disconnect()
        }
    }

    private fun notifySessionEnded() {
        if (sessionId.isBlank() || apiBase.isBlank() || deviceId.isBlank() || deviceToken.isBlank()) return
        uploadExecutor.execute {
            val connection = openConnection("device-end", "POST")
            try {
                val body = "{\"reason\":\"device_projection_stopped\"}".toByteArray(StandardCharsets.UTF_8)
                connection.setRequestProperty("Content-Type", "application/json")
                connection.setFixedLengthStreamingMode(body.size)
                connection.doOutput = true
                connection.outputStream.use { it.write(body) }
                connection.responseCode
            } catch (_: Exception) {
                // Best effort: the backend also expires sessions and frames automatically.
            } finally {
                connection.disconnect()
            }
        }
    }

    private fun openConnection(action: String, method: String): HttpURLConnection {
        val encodedDevice = URLEncoder.encode(deviceId, StandardCharsets.UTF_8.name())
        val encodedSession = URLEncoder.encode(sessionId, StandardCharsets.UTF_8.name())
        val url = URL("$apiBase/devices/$encodedDevice/consent-sessions/$encodedSession/$action")
        return (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = NETWORK_TIMEOUT_MS
            readTimeout = NETWORK_TIMEOUT_MS
            instanceFollowRedirects = false
            useCaches = false
            setRequestProperty("X-Device-Token", deviceToken)
        }
    }

    private fun stopCapture(notifyBackend: Boolean) {
        if (stopping) return
        stopping = true
        if (notifyBackend) notifySessionEnded()
        imageReader?.setOnImageAvailableListener(null, null)
        virtualDisplay?.release()
        virtualDisplay = null
        imageReader?.close()
        imageReader = null
        captureThread?.quitSafely()
        captureThread = null
        projection?.unregisterCallback(projectionCallback)
        projection?.stop()
        projection = null
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    override fun onDestroy() {
        stopCapture(notifyBackend = true)
        uploadExecutor.shutdown()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun notification(sessionId: String): Notification {
        val stop = Intent(this, ProjectionService::class.java).setAction(ACTION_STOP)
        val stopPending = PendingIntent.getService(
            this,
            301,
            stop,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val openPending = PendingIntent.getActivity(
            this,
            302,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("A.R.M.X screen sharing is active")
            .setContentText("Visible session ${sessionId.take(8)} • tap Stop sharing at any time")
            .setContentIntent(openPending)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .addAction(0, "Stop sharing", stopPending)
            .build()
    }

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Visible screen sharing",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Persistent disclosure while a consented A.R.M.X screen-share session is active"
            setShowBadge(true)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        const val EXTRA_RESULT_CODE = "projection_result_code"
        const val EXTRA_DATA = "projection_data"
        const val EXTRA_SESSION_ID = "projection_session_id"
        const val EXTRA_API_BASE = "projection_api_base"
        const val EXTRA_DEVICE_ID = "projection_device_id"
        const val EXTRA_DEVICE_CREDENTIAL = "projection_device_auth"
        const val ACTION_STOP = "ai.armx.managed.STOP_PROJECTION"
        private const val CHANNEL_ID = "armx_visible_screen_share"
        private const val NOTIFICATION_ID = 7301
        private const val FRAME_INTERVAL_MS = 1_000L
        private const val JPEG_QUALITY = 55
        private const val MAX_FRAME_EDGE = 1_280
        private const val MAX_FRAME_BYTES = 750 * 1024
        private const val MAX_REJECTED_FRAMES = 5
        private const val NETWORK_TIMEOUT_MS = 5_000
    }
}
