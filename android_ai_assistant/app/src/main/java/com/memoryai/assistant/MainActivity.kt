package com.memoryai.assistant

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = MemoryStore(this)
        setContent { WorldLogicLineApp(store) }
    }
}

data class ChatMessage(val role: String, val text: String)

@Composable
private fun WorldLogicLineApp(store: MemoryStore) {
    var messages by remember { mutableStateOf(store.load().ifEmpty { mutableListOf(ChatMessage("assistant", "WorldLogicLine Assistant готов. Чем помочь?")) }) }
    var input by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Scaffold(topBar = { TopAppBar(title = { Text("WorldLogicLine Assistant") }) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).padding(12.dp)) {
            LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
                items(messages) { m ->
                    Text(
                        if (m.role == "user") "Вы: ${m.text}" else "Assistant: ${m.text}",
                        Modifier.padding(vertical = 8.dp)
                    )
                }
            }
            Row(Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.weight(1f),
                    enabled = !sending,
                    placeholder = { Text("Напишите сообщение...") }
                )
                Spacer(Modifier.width(8.dp))
                Button(
                    enabled = input.isNotBlank() && !sending,
                    onClick = {
                        val text = input.trim()
                        input = ""
                        messages = messages.toMutableList().apply { add(ChatMessage("user", text)) }
                        store.save(messages)
                        sending = true
                        scope.launch {
                            val reply = runCatching { AssistantApi.send(text) }
                                .getOrElse { "Не удалось связаться с AI-сервером: ${it.message ?: "неизвестная ошибка"}" }
                            messages = messages.toMutableList().apply { add(ChatMessage("assistant", reply)) }
                            store.save(messages)
                            sending = false
                        }
                    }
                ) { Text(if (sending) "…" else "➤") }
            }
        }
    }
}
