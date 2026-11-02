package ai.armx.managed.management

import android.app.admin.DevicePolicyManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_LOCKED_BOOT_COMPLETED)) return
        val policy = context.getSystemService(DevicePolicyManager::class.java)
        if (policy.isDeviceOwnerApp(context.packageName)) {
            val storage = context.createDeviceProtectedStorageContext()
            val kiosk = storage.getSharedPreferences("armx_policy", Context.MODE_PRIVATE)
                .getBoolean("kiosk_enabled", false)
            ManagementNotifications.showManagedStatus(context, kiosk)
        }
    }
}
