package ai.armx.managed.management

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import kotlin.math.max
import kotlin.math.min

/** Aggregate foreground duration only; no keystrokes, content, notifications or screenshots. */
class UsageTelemetry(private val context: Context) {
    fun aggregate(sinceEpochMs: Long, untilEpochMs: Long = System.currentTimeMillis()): List<Map<String, Any>> {
        val until = min(untilEpochMs, System.currentTimeMillis())
        val since = max(sinceEpochMs, until - MAX_WINDOW_MS)
        require(until > since) { "Invalid usage window" }
        val manager = context.getSystemService(UsageStatsManager::class.java)
        val events = manager.queryEvents(since, until)
        val active = mutableMapOf<String, Long>()
        val totals = mutableMapOf<String, Long>()
        val launches = mutableMapOf<String, Int>()
        val event = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            val packageName = event.packageName ?: continue
            when (event.eventType) {
                UsageEvents.Event.ACTIVITY_RESUMED -> {
                    if (!active.containsKey(packageName)) {
                        active[packageName] = event.timeStamp
                        launches[packageName] = (launches[packageName] ?: 0) + 1
                    }
                }
                UsageEvents.Event.ACTIVITY_PAUSED -> {
                    val started = active.remove(packageName) ?: continue
                    totals[packageName] = (totals[packageName] ?: 0L) + max(0L, event.timeStamp - started)
                }
            }
        }
        active.forEach { (packageName, started) ->
            totals[packageName] = (totals[packageName] ?: 0L) + max(0L, until - started)
        }
        return (totals.keys + launches.keys)
            .distinct()
            .map { packageName ->
                mapOf(
                    "packageName" to packageName,
                    "foregroundSeconds" to ((totals[packageName] ?: 0L) / 1000L),
                    "launches" to (launches[packageName] ?: 0),
                    "windowStart" to since,
                    "windowEnd" to until,
                )
            }
            .filter { (it["foregroundSeconds"] as Long) > 0L || (it["launches"] as Int) > 0 }
            .sortedByDescending { it["foregroundSeconds"] as Long }
    }

    companion object {
        private const val MAX_WINDOW_MS = 7L * 24L * 60L * 60L * 1000L
    }
}
