package com.memoryai.assistant

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

object AssistantApi {
    private const val BASE_URL = "https://YOUR-WORLDLOGICLINE-API/v1/chat"

    suspend fun send(message: String): String = withContext(Dispatchers.IO) {
        val connection = (URL(BASE_URL).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 120_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
        }
        try {
            val body = JSONObject().put("message", message).toString()
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
            val text = stream.bufferedReader().use { it.readText() }
            if (connection.responseCode !in 200..299) {
                throw IllegalStateException("Assistant API error ${connection.responseCode}")
            }
            JSONObject(text).optString("reply").ifBlank { throw IllegalStateException("Empty assistant reply") }
        } finally {
            connection.disconnect()
        }
    }
}
