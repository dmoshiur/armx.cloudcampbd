package ai.armx.managed.management

import android.app.admin.DeviceAdminReceiver
import android.app.admin.DevicePolicyManager
import android.content.Context
import android.content.Intent
import android.widget.Toast
import ai.armx.managed.MainActivity

class ArmxDeviceAdminReceiver : DeviceAdminReceiver() {
    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        ManagementNotifications.showManagedStatus(context, kiosk = false)
        Toast.makeText(context, "A.R.M.X Device Owner enabled", Toast.LENGTH_LONG).show()
    }

    override fun onProfileProvisioningComplete(context: Context, intent: Intent) {
        super.onProfileProvisioningComplete(context, intent)
        val manager = context.getSystemService(DevicePolicyManager::class.java)
        runCatching { manager.setProfileName(component(context), "A.R.M.X managed device") }
        ManagementNotifications.showManagedStatus(context, kiosk = false)
        context.startActivity(
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
        )
    }

    override fun onDisabled(context: Context, intent: Intent) {
        ManagementNotifications.cancelManagedStatus(context)
        super.onDisabled(context, intent)
    }

    companion object {
        fun component(context: Context) = android.content.ComponentName(
            context,
            ArmxDeviceAdminReceiver::class.java,
        )
    }
}
