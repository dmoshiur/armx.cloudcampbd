package ai.armx.managed

import android.Manifest
import android.app.Activity
import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.core.content.ContextCompat
import ai.armx.managed.management.DeviceOwnerController
import ai.armx.managed.management.ManagementNotifications
import ai.armx.managed.management.UsageTelemetry
import ai.armx.managed.sessions.ProjectionService
import ai.armx.managed.sessions.VisibleVoiceService
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private lateinit var owner: DeviceOwnerController
    private var pendingProjectionResult: MethodChannel.Result? = null
    private var pendingProjectionSession = ""
    private var pendingProjectionApiBase = ""
    private var pendingProjectionDeviceId = ""
    private var pendingProjectionDeviceToken = ""
    private var pendingNotificationResult: MethodChannel.Result? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        owner = DeviceOwnerController(this)
        if (owner.isDeviceOwner) ManagementNotifications.showManagedStatus(this, owner.state()["kioskEnabled"] == true)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler(::handleMethod)
    }

    private fun handleMethod(call: MethodCall, result: MethodChannel.Result) {
        try {
            when (call.method) {
                "managementState" -> result.success(owner.state() + ("notificationPermission" to hasNotificationPermission()))
                "requestNotificationPermission" -> requestNotificationPermission(result)
                "setInitialPasscode" -> withPasscode(call, "passcode") { passcode ->
                    owner.setInitialPasscode(passcode)
                    result.success(owner.state())
                }
                "changePasscode" -> {
                    val current = call.string("current").toCharArray()
                    val replacement = call.string("replacement").toCharArray()
                    try {
                        result.success(owner.changePasscode(current, replacement))
                    } finally {
                        current.fill('\u0000')
                        replacement.fill('\u0000')
                    }
                }
                "launchableApplications" -> result.success(owner.launchableApplications().map { it.asMap() })
                "applyPolicy" -> applyPolicy(call, result)
                "launchApplication" -> result.success(owner.launch(call.string("packageName")))
                "openUsageAccessSettings" -> {
                    owner.openUsageAccessSettings()
                    result.success(null)
                }
                "usageTelemetry" -> {
                    if (!owner.hasUsageAccess()) throw SecurityException("Usage access has not been granted by the device owner")
                    val since = call.argument<Number>("since")?.toLong()
                        ?: (System.currentTimeMillis() - 24L * 60L * 60L * 1000L)
                    val until = call.argument<Number>("until")?.toLong() ?: System.currentTimeMillis()
                    result.success(UsageTelemetry(this).aggregate(since, until))
                }
                "requestScreenShare" -> requestScreenShare(
                    call.string("sessionId"),
                    call.string("apiBase"),
                    call.string("deviceId"),
                    call.string("deviceToken"),
                    result,
                )
                "stopScreenShare" -> {
                    stopService(Intent(this, ProjectionService::class.java))
                    result.success(null)
                }
                "startVisibleVoiceSession" -> startVoice(
                    call.string("sessionId"),
                    call.string("apiBase"),
                    call.string("deviceId"),
                    call.string("deviceToken"),
                    result,
                )
                "stopVisibleVoiceSession" -> {
                    stopService(Intent(this, VisibleVoiceService::class.java))
                    result.success(null)
                }
                "deprovision" -> deprovision(call, result)
                "requestUninstall" -> requestUninstall(result)
                "openDeviceOwnerHelp" -> {
                    startActivity(Intent(Settings.ACTION_SETTINGS))
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        } catch (error: SecurityException) {
            result.error("permission_denied", error.message, null)
        } catch (error: IllegalArgumentException) {
            result.error("invalid_argument", error.message, null)
        } catch (error: IllegalStateException) {
            result.error("invalid_state", error.message, null)
        } catch (error: Exception) {
            result.error("native_error", error.message ?: "Android operation failed", null)
        }
    }

    private fun applyPolicy(call: MethodCall, result: MethodChannel.Result) {
        if (!hasNotificationPermission()) {
            throw SecurityException("Notification permission is required so management and consent sessions remain visible")
        }
        val passcode = call.string("passcode").toCharArray()
        try {
            val allowed = call.argument<List<String>>("allowedPackages").orEmpty().toSet()
            val kiosk = call.argument<Boolean>("kioskEnabled") ?: false
            val launcher = call.argument<Boolean>("launcherEnabled") ?: kiosk
            val restrictions = call.argument<List<String>>("restrictions")?.toSet()
                ?: if (kiosk) DeviceOwnerController.SUPPORTED_RESTRICTIONS else emptySet()
            val applied = owner.applyPolicy(passcode, allowed, kiosk, launcher, restrictions)
            if (kiosk && isLockTaskPermitted()) {
                startLockTask()
            } else if (!kiosk && isInLockTaskMode()) {
                stopLockTask()
            }
            result.success(applied.asMap())
        } finally {
            passcode.fill('\u0000')
        }
    }

    private fun deprovision(call: MethodCall, result: MethodChannel.Result) {
        val passcode = call.string("passcode").toCharArray()
        try {
            if (isInLockTaskMode()) stopLockTask()
            owner.deprovision(passcode)
            result.success(mapOf("deviceOwner" to false, "uninstallRequiresSystemConfirmation" to true))
        } finally {
            passcode.fill('\u0000')
        }
    }

    private fun requestUninstall(result: MethodChannel.Result) {
        if (owner.isDeviceOwner) throw IllegalStateException("Deprovision with the owner passcode before uninstalling")
        startActivity(Intent(Intent.ACTION_DELETE, Uri.parse("package:$packageName")))
        result.success(null)
    }

    private fun requestScreenShare(
        sessionId: String,
        apiBase: String,
        deviceId: String,
        deviceToken: String,
        result: MethodChannel.Result,
    ) {
        if (!hasNotificationPermission()) throw SecurityException("Notification permission is required for visible screen sharing")
        if (!apiBase.startsWith("https://") && !BuildConfig.DEBUG) {
            throw SecurityException("Release mirroring requires an HTTPS API origin")
        }
        if (pendingProjectionResult != null) throw IllegalStateException("A screen-share consent request is already open")
        val manager = getSystemService(MediaProjectionManager::class.java)
        pendingProjectionResult = result
        pendingProjectionSession = sessionId
        pendingProjectionApiBase = apiBase.trimEnd('/')
        pendingProjectionDeviceId = deviceId
        pendingProjectionDeviceToken = deviceToken
        startActivityForResult(manager.createScreenCaptureIntent(), REQUEST_MEDIA_PROJECTION)
    }

    @Deprecated("Activity result API retained for FlutterActivity compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_MEDIA_PROJECTION) return
        val callback = pendingProjectionResult ?: return
        pendingProjectionResult = null
        val sessionId = pendingProjectionSession
        val apiBase = pendingProjectionApiBase
        val deviceId = pendingProjectionDeviceId
        val deviceToken = pendingProjectionDeviceToken
        pendingProjectionSession = ""
        pendingProjectionApiBase = ""
        pendingProjectionDeviceId = ""
        pendingProjectionDeviceToken = ""
        if (resultCode != Activity.RESULT_OK || data == null) {
            callback.success(mapOf("consented" to false))
            return
        }
        val service = Intent(this, ProjectionService::class.java)
            .putExtra(ProjectionService.EXTRA_RESULT_CODE, resultCode)
            .putExtra(ProjectionService.EXTRA_DATA, data)
            .putExtra(ProjectionService.EXTRA_SESSION_ID, sessionId)
            .putExtra(ProjectionService.EXTRA_API_BASE, apiBase)
            .putExtra(ProjectionService.EXTRA_DEVICE_ID, deviceId)
            .putExtra(ProjectionService.EXTRA_DEVICE_CREDENTIAL, deviceToken)
        ContextCompat.startForegroundService(this, service)
        callback.success(mapOf("consented" to true, "visibleNotification" to true))
    }

    private fun startVoice(
        sessionId: String,
        apiBase: String,
        deviceId: String,
        deviceToken: String,
        result: MethodChannel.Result,
    ) {
        if (!hasNotificationPermission()) throw SecurityException("Notification permission is required for visible voice sessions")
        if (!apiBase.startsWith("https://") && !BuildConfig.DEBUG) {
            throw SecurityException("Release voice sessions require an HTTPS API origin")
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            throw SecurityException("Microphone permission must be granted in the visible app before starting voice")
        }
        ContextCompat.startForegroundService(
            this,
            Intent(this, VisibleVoiceService::class.java)
                .putExtra(VisibleVoiceService.EXTRA_SESSION_ID, sessionId)
                .putExtra(VisibleVoiceService.EXTRA_API_BASE, apiBase.trimEnd('/'))
                .putExtra(VisibleVoiceService.EXTRA_DEVICE_ID, deviceId)
                .putExtra(VisibleVoiceService.EXTRA_DEVICE_CREDENTIAL, deviceToken),
        )
        result.success(mapOf("started" to true, "visibleNotification" to true))
    }

    private fun requestNotificationPermission(result: MethodChannel.Result) {
        if (hasNotificationPermission()) {
            result.success(true)
            return
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            result.success(true)
            return
        }
        if (pendingNotificationResult != null) throw IllegalStateException("A notification permission request is already open")
        pendingNotificationResult = result
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_NOTIFICATIONS) {
            pendingNotificationResult?.success(grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED)
            pendingNotificationResult = null
        }
    }

    private fun hasNotificationPermission(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun isLockTaskPermitted(): Boolean =
        getSystemService(DevicePolicyManager::class.java).isLockTaskPermitted(packageName)

    private fun isInLockTaskMode(): Boolean =
        getSystemService(ActivityManager::class.java).lockTaskModeState != ActivityManager.LOCK_TASK_MODE_NONE

    private fun withPasscode(call: MethodCall, field: String, action: (CharArray) -> Unit) {
        val passcode = call.string(field).toCharArray()
        try {
            action(passcode)
        } finally {
            passcode.fill('\u0000')
        }
    }

    private fun MethodCall.string(name: String): String =
        argument<String>(name)?.takeIf { it.isNotBlank() }
            ?: throw IllegalArgumentException("$name is required")

    companion object {
        private const val CHANNEL = "ai.armx/managed_device"
        private const val REQUEST_MEDIA_PROJECTION = 8101
        private const val REQUEST_NOTIFICATIONS = 8102
    }
}
