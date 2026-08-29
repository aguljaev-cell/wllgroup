package com.worldlogicline.assistant

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class AssistantApi(private val baseUrl: String) {
    suspend fun send(message: String, userId: String): String = withContext(Dispatchers.IO) {
        require(baseUrl.isNotBlank() && !baseUrl.contains("YOUR-WORLDLOGICLINE-API")) {
            "AI server address is not configured"
        }
        val connection = URL(baseUrl.trimEnd('/') + "/v1/chat").openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 15000
            connection.readTimeout = 60000
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            val body = "{\"user_id\":${json(userId)},\"message\":${json(message)}}"
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) error("API $code: $response")
            JSONObject(response).optString("reply").ifBlank { error("API returned no reply") }
        } finally {
            connection.disconnect()
        }
    }

    private fun json(value: String) = JSONObject.quote(value)
}
