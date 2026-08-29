package com.worldlogicline.assistant

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

class AssistantApi(private val baseUrl: String) {
    suspend fun send(message: String, userId: String): String = withContext(Dispatchers.IO) {
        val connection = URL(baseUrl.trimEnd('/') + "/v1/chat").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 15000
        connection.readTimeout = 60000
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        val body = "{\"user_id\":${json(userId)},\"message\":${json(message)}}"
        connection.outputStream.use { it.write(body.toByteArray()) }
        val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
        val response = stream.bufferedReader().use { it.readText() }
        if (connection.responseCode !in 200..299) error("API ${connection.responseCode}: $response")
        response
    }

    private fun json(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\""
}
