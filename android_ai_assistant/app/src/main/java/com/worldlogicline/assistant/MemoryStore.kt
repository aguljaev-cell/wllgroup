package com.worldlogicline.assistant

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

class MemoryStore(context: Context) {
    private val prefs = context.getSharedPreferences("worldlogicline_memory", Context.MODE_PRIVATE)

    fun load(): List<ChatMessage> = runCatching {
        val json = prefs.getString("messages", "[]") ?: "[]"
        val array = JSONArray(json)
        buildList(array.length()) {
            for (i in 0 until array.length()) {
                val item = array.optJSONObject(i) ?: continue
                val role = item.optString("role")
                val text = item.optString("text")
                if (role.isNotBlank() && text.isNotBlank()) add(ChatMessage(role, text))
            }
        }
    }.getOrDefault(emptyList())

    fun save(messages: List<ChatMessage>) {
        val array = JSONArray()
        messages.forEach { message ->
            array.put(JSONObject().put("role", message.role).put("text", message.text))
        }
        prefs.edit().putString("messages", array.toString()).apply()
    }
}
