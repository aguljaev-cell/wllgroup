package com.memoryai.assistant

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

class MemoryStore(context: Context) {
    private val prefs = context.getSharedPreferences("worldlogicline_memory", Context.MODE_PRIVATE)
    fun load(): MutableList<ChatMessage> = runCatching {
        val a = JSONArray(prefs.getString("messages", "[]"))
        MutableList(a.length()) { i -> val o=a.getJSONObject(i); ChatMessage(o.getString("role"), o.getString("text")) }
    }.getOrElse { mutableListOf() }
    fun save(messages: List<ChatMessage>) { val a=JSONArray(); messages.forEach { a.put(JSONObject().put("role",it.role).put("text",it.text)) }; prefs.edit().putString("messages",a.toString()).apply() }
}
