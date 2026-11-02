package ai.armx.managed.sessions

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class SessionActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            ProjectionService.ACTION_STOP -> context.stopService(Intent(context, ProjectionService::class.java))
            VisibleVoiceService.ACTION_STOP -> context.stopService(Intent(context, VisibleVoiceService::class.java))
        }
    }
}
