package ai.armx.managed.management

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import ai.armx.managed.MainActivity
import ai.armx.managed.R

object ManagementNotifications {
    const val STATUS_CHANNEL = "armx_managed_status"
    const val STATUS_NOTIFICATION_ID = 4300

    fun ensureChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                STATUS_CHANNEL,
                context.getString(R.string.managed_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Always visible while this device is enrolled as an A.R.M.X managed device."
                setShowBadge(false)
            },
        )
    }

    fun showManagedStatus(context: Context, kiosk: Boolean) {
        ensureChannels(context)
        val openIntent = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(context, STATUS_CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("A.R.M.X managed device")
            .setContentText(if (kiosk) "Managed launcher and app policy are active" else "Device Owner is enrolled; kiosk is not active")
            .setContentIntent(openIntent)
            .setOngoing(true)
            .setAutoCancel(false)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
        context.getSystemService(NotificationManager::class.java)
            .notify(STATUS_NOTIFICATION_ID, notification)
    }

    fun cancelManagedStatus(context: Context) {
        context.getSystemService(NotificationManager::class.java).cancel(STATUS_NOTIFICATION_ID)
    }
}
