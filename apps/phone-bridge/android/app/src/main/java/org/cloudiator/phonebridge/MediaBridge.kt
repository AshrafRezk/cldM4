package org.cloudiator.phonebridge

/**
 * Skeleton for the Android SIM ↔ Mini PCM bridge (Phase G).
 *
 * Wire this into an Android Foreground Service that:
 * 1. Opens ws://<mini>/v1/voice/lines/{lineId}/media?token=...
 * 2. Sends JSON {"type":"ring","from":"+2..."} on inbound calls
 * 3. Streams 16 kHz mono PCM16 uplink bytes; plays downlink bytes into the call
 * 4. Honours {"type":"answer"|"dial"|"hangup"|"busy"}
 *
 * Root path: AudioRecord with MediaRecorder.AudioSource.VOICE_CALL.
 * No-root path: SPEAKERPHONE + MIC (acoustic).
 */
class MediaBridge(
    private val miniHost: String,
    private val lineId: String,
    private val token: String,
) {
    data class ControlMessage(val type: String, val callId: String? = null, val to: String? = null)

    fun mediaUrl(): String =
        "ws://$miniHost:8080/v1/voice/lines/$lineId/media?token=$token"

    fun ringPayload(fromE164: String): String =
        """{"type":"ring","from":"$fromE164"}"""

    fun endedPayload(callId: String?): String =
        if (callId == null) """{"type":"ended"}""" else """{"type":"ended","call_id":"$callId"}"""

    fun parseControl(json: String): ControlMessage {
        // Minimal parser placeholder — replace with kotlinx.serialization in the real app.
        val type = Regex(""""type"\s*:\s*"([^"]+)"""").find(json)?.groupValues?.get(1) ?: "unknown"
        val callId = Regex(""""call_id"\s*:\s*"([^"]+)"""").find(json)?.groupValues?.getOrNull(1)
        val to = Regex(""""to"\s*:\s*"([^"]+)"""").find(json)?.groupValues?.getOrNull(1)
        return ControlMessage(type = type, callId = callId, to = to)
    }

    companion object {
        const val SAMPLE_RATE_HZ = 16_000
        const val CHANNELS = 1
        const val PCM16_BYTES_PER_FRAME = 2
    }
}
