package ai.armx.managed.management

import android.app.AppOpsManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.Process
import android.provider.Settings
import ai.armx.managed.MainActivity

class DeviceOwnerController(private val context: Context) {
    private val policy = context.getSystemService(DevicePolicyManager::class.java)
    private val admin = ArmxDeviceAdminReceiver.component(context)
    private val passcodes = OwnerPasscodeStore(context)
    private val storage = context.createDeviceProtectedStorageContext()
    private val preferences = storage.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    val isDeviceOwner: Boolean
        get() = policy.isDeviceOwnerApp(context.packageName)

    fun state(): Map<String, Any> = mapOf(
        "supported" to true,
        "deviceOwner" to isDeviceOwner,
        "passcodeConfigured" to passcodes.isConfigured,
        "kioskEnabled" to preferences.getBoolean(KEY_KIOSK, false),
        "launcherPinned" to preferences.getBoolean(KEY_LAUNCHER, false),
        "allowedPackages" to preferences.getStringSet(KEY_ALLOWED, setOf(context.packageName)).orEmpty().sorted(),
        "usageAccess" to hasUsageAccess(),
        "provisioningCommand" to "adb shell dpm set-device-owner ${context.packageName}/.management.ArmxDeviceAdminReceiver",
    )

    fun setInitialPasscode(passcode: CharArray) {
        requireOwner()
        passcodes.setInitial(passcode)
    }

    fun changePasscode(current: CharArray, replacement: CharArray): Boolean {
        requireOwner()
        return passcodes.change(current, replacement)
    }

    fun applyPolicy(passcode: CharArray, requestedPackages: Set<String>, kiosk: Boolean): PolicyResult {
        requireOwner()
        require(passcodes.verify(passcode)) { "Owner passcode rejected" }
        val launchable = launchableApplications().map { it.packageName }.toSet()
        val allowed = (requestedPackages intersect launchable) + context.packageName
        require(allowed.size <= MAX_ALLOWED_PACKAGES) { "Too many allowed applications" }

        val candidates = launchableApplications()
            .filterNot { it.systemApp || it.packageName in allowed }
            .map { it.packageName }
            .distinct()
        val previouslySuspended = preferences.getStringSet(KEY_SUSPENDED, emptySet()).orEmpty()
        if (previouslySuspended.isNotEmpty()) {
            runCatching { policy.setPackagesSuspended(admin, previouslySuspended.toTypedArray(), false) }
        }
        val failedToSuspend = if (kiosk && candidates.isNotEmpty()) {
            policy.setPackagesSuspended(admin, candidates.toTypedArray(), true).toSet()
        } else {
            emptySet()
        }
        val suspended = candidates.toSet() - failedToSuspend

        if (kiosk) {
            policy.setUninstallBlocked(admin, context.packageName, true)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                policy.setUserControlDisabledPackages(admin, listOf(context.packageName))
            }
            policy.setLockTaskPackages(admin, allowed.toTypedArray())
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                policy.setLockTaskFeatures(
                    admin,
                    DevicePolicyManager.LOCK_TASK_FEATURE_HOME or
                        DevicePolicyManager.LOCK_TASK_FEATURE_NOTIFICATIONS or
                        DevicePolicyManager.LOCK_TASK_FEATURE_GLOBAL_ACTIONS,
                )
            }
            installManagedLauncher()
            MANAGED_RESTRICTIONS.forEach { policy.addUserRestriction(admin, it) }
        } else {
            policy.setUninstallBlocked(admin, context.packageName, false)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                policy.setUserControlDisabledPackages(admin, emptyList())
            }
            policy.setLockTaskPackages(admin, emptyArray())
            clearManagedLauncher()
            MANAGED_RESTRICTIONS.forEach { policy.clearUserRestriction(admin, it) }
        }

        preferences.edit()
            .putBoolean(KEY_KIOSK, kiosk)
            .putStringSet(KEY_ALLOWED, allowed)
            .putStringSet(KEY_SUSPENDED, suspended)
            .apply()
        ManagementNotifications.showManagedStatus(context, kiosk)
        return PolicyResult(allowed.sorted(), suspended.sorted(), failedToSuspend.sorted(), kiosk)
    }

    /**
     * Standards-compliant local deprovisioning. A remote command cannot call
     * this method without the owner typing the local passcode into the app.
     */
    fun deprovision(passcode: CharArray) {
        requireOwner()
        require(passcodes.verify(passcode)) { "Owner passcode rejected" }
        val suspended = preferences.getStringSet(KEY_SUSPENDED, emptySet()).orEmpty()
        if (suspended.isNotEmpty()) {
            runCatching { policy.setPackagesSuspended(admin, suspended.toTypedArray(), false) }
        }
        runCatching { policy.setLockTaskPackages(admin, emptyArray()) }
        runCatching { policy.setUninstallBlocked(admin, context.packageName, false) }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            runCatching { policy.setUserControlDisabledPackages(admin, emptyList()) }
        }
        MANAGED_RESTRICTIONS.forEach { runCatching { policy.clearUserRestriction(admin, it) } }
        clearManagedLauncher()
        preferences.edit().clear().commit()
        policy.clearDeviceOwnerApp(context.packageName)
        passcodes.clearAfterDeprovision()
        ManagementNotifications.cancelManagedStatus(context)
    }

    fun launchableApplications(): List<ManagedApplication> {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return context.packageManager.queryIntentActivities(intent, PackageManager.MATCH_ALL)
            .map { info ->
                val application = info.activityInfo.applicationInfo
                ManagedApplication(
                    packageName = info.activityInfo.packageName,
                    label = info.loadLabel(context.packageManager).toString(),
                    systemApp = application.flags and ApplicationInfo.FLAG_SYSTEM != 0,
                )
            }
            .distinctBy { it.packageName }
            .sortedBy { it.label.lowercase() }
    }

    fun launch(packageName: String): Boolean {
        val allowed = preferences.getStringSet(KEY_ALLOWED, setOf(context.packageName)).orEmpty()
        if (preferences.getBoolean(KEY_KIOSK, false) && packageName !in allowed) return false
        val intent = context.packageManager.getLaunchIntentForPackage(packageName) ?: return false
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }

    fun openUsageAccessSettings() {
        context.startActivity(
            Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    fun hasUsageAccess(): Boolean {
        val operations = context.getSystemService(AppOpsManager::class.java)
        return operations.checkOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            Process.myUid(),
            context.packageName,
        ) == AppOpsManager.MODE_ALLOWED
    }

    private fun installManagedLauncher() {
        val filter = IntentFilter(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_HOME)
            addCategory(Intent.CATEGORY_DEFAULT)
        }
        policy.addPersistentPreferredActivity(
            admin,
            filter,
            ComponentName(context, MainActivity::class.java),
        )
        preferences.edit().putBoolean(KEY_LAUNCHER, true).apply()
    }

    private fun clearManagedLauncher() {
        runCatching { policy.clearPackagePersistentPreferredActivities(admin, context.packageName) }
        preferences.edit().putBoolean(KEY_LAUNCHER, false).apply()
    }

    private fun requireOwner() {
        check(isDeviceOwner) { "This device is not provisioned with A.R.M.X as Device Owner" }
    }

    data class ManagedApplication(
        val packageName: String,
        val label: String,
        val systemApp: Boolean,
    ) {
        fun asMap(): Map<String, Any> = mapOf(
            "packageName" to packageName,
            "label" to label,
            "systemApp" to systemApp,
        )
    }

    data class PolicyResult(
        val allowed: List<String>,
        val suspended: List<String>,
        val failedToSuspend: List<String>,
        val kiosk: Boolean,
    ) {
        fun asMap(): Map<String, Any> = mapOf(
            "allowedPackages" to allowed,
            "suspendedPackages" to suspended,
            "failedToSuspend" to failedToSuspend,
            "kioskEnabled" to kiosk,
        )
    }

    companion object {
        private const val PREFERENCES = "armx_policy"
        private const val KEY_KIOSK = "kiosk_enabled"
        private const val KEY_LAUNCHER = "launcher_enabled"
        private const val KEY_ALLOWED = "allowed_packages"
        private const val KEY_SUSPENDED = "suspended_packages"
        private const val MAX_ALLOWED_PACKAGES = 200
        private val MANAGED_RESTRICTIONS = setOf(
            android.os.UserManager.DISALLOW_ADD_USER,
            android.os.UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES,
            android.os.UserManager.DISALLOW_SAFE_BOOT,
        )
    }
}
