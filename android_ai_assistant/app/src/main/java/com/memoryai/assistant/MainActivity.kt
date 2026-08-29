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

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); val store=MemoryStore(this); setContent { MemoryAIApp(store) } }
}

data class ChatMessage(val role:String, val text:String)

@Composable fun MemoryAIApp(store: MemoryStore) {
    var messages by remember { mutableStateOf(store.load().ifEmpty { mutableListOf(ChatMessage("assistant", "WorldLogicLine Assistant готов. Я сохраняю историю на этом телефоне.")) }) }
    var input by remember { mutableStateOf("") }
    Scaffold(topBar={ TopAppBar(title={Text("WorldLogicLine Assistant")}) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).padding(12.dp)) {
            LazyColumn(Modifier.weight(1f).fillMaxWidth()) { items(messages) { m -> Text(if(m.role=="user") "Вы: ${m.text}" else "Assistant: ${m.text}", Modifier.padding(vertical=8.dp)) } }
            Row(Modifier.fillMaxWidth()) {
                OutlinedTextField(input,{input=it},Modifier.weight(1f),placeholder={Text("Напишите сообщение...")})
                Spacer(Modifier.width(8.dp)); Button(onClick={ if(input.isNotBlank()){ messages=messages.toMutableList().apply{add(ChatMessage("user",input));add(ChatMessage("assistant","Я сохранил это сообщение в памяти. Подключение выбранной AI-модели будет следующим шагом."))}; store.save(messages); input="" }}) { Text("➤") }
            }
        }
    }
}
