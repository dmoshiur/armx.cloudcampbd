package ai.armx.managed.management

import android.content.Context
import android.util.Base64
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/** Local-only owner passcode verifier. The passcode never reaches Flutter or the API. */
class OwnerPasscodeStore(context: Context) {
    private val preferences = context.getSharedPreferences("armx_owner_auth", Context.MODE_PRIVATE)

    val isConfigured: Boolean
        get() = preferences.contains(KEY_HASH) && preferences.contains(KEY_SALT)

    fun setInitial(passcode: CharArray) {
        require(!isConfigured) { "Owner passcode is already configured" }
        requireStrong(passcode)
        store(passcode)
    }

    fun change(current: CharArray, replacement: CharArray): Boolean {
        if (!verify(current)) return false
        requireStrong(replacement)
        store(replacement)
        return true
    }

    fun verify(passcode: CharArray): Boolean {
        val blockedUntil = preferences.getLong(KEY_BLOCKED_UNTIL, 0L)
        if (System.currentTimeMillis() < blockedUntil) return false
        val salt = preferences.getString(KEY_SALT, null)?.decode() ?: return false
        val expected = preferences.getString(KEY_HASH, null)?.decode() ?: return false
        val actual = derive(passcode, salt)
        val valid = MessageDigest.isEqual(expected, actual)
        if (valid) {
            preferences.edit().putInt(KEY_FAILURES, 0).remove(KEY_BLOCKED_UNTIL).apply()
        } else {
            val failures = preferences.getInt(KEY_FAILURES, 0) + 1
            val editor = preferences.edit().putInt(KEY_FAILURES, failures)
            if (failures >= MAX_ATTEMPTS) {
                editor.putInt(KEY_FAILURES, 0)
                    .putLong(KEY_BLOCKED_UNTIL, System.currentTimeMillis() + LOCKOUT_MS)
            }
            editor.apply()
        }
        salt.fill(0)
        expected.fill(0)
        actual.fill(0)
        return valid
    }

    fun clearAfterDeprovision() {
        preferences.edit().clear().apply()
    }

    private fun store(passcode: CharArray) {
        val salt = ByteArray(SALT_BYTES).also(SecureRandom()::nextBytes)
        val hash = derive(passcode, salt)
        preferences.edit()
            .putString(KEY_SALT, salt.encode())
            .putString(KEY_HASH, hash.encode())
            .putInt(KEY_FAILURES, 0)
            .remove(KEY_BLOCKED_UNTIL)
            .apply()
        salt.fill(0)
        hash.fill(0)
    }

    private fun derive(passcode: CharArray, salt: ByteArray): ByteArray {
        val spec = PBEKeySpec(passcode, salt, ITERATIONS, KEY_BITS)
        return try {
            SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
        } finally {
            spec.clearPassword()
        }
    }

    private fun requireStrong(passcode: CharArray) {
        require(passcode.size >= 8) { "Owner passcode must contain at least 8 characters" }
        require(passcode.any(Char::isLetter) && passcode.any(Char::isDigit)) {
            "Owner passcode must include a letter and a number"
        }
        require(passcode.distinct().size >= 5) { "Owner passcode is too repetitive" }
    }

    private fun ByteArray.encode(): String = Base64.encodeToString(this, Base64.NO_WRAP)
    private fun String.decode(): ByteArray = Base64.decode(this, Base64.NO_WRAP)

    companion object {
        private const val KEY_HASH = "hash"
        private const val KEY_SALT = "salt"
        private const val KEY_FAILURES = "failures"
        private const val KEY_BLOCKED_UNTIL = "blocked_until"
        private const val ITERATIONS = 210_000
        private const val KEY_BITS = 256
        private const val SALT_BYTES = 32
        private const val MAX_ATTEMPTS = 5
        private const val LOCKOUT_MS = 60_000L
    }
}
