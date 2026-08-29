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
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); setContent { MemoryAIApp() } }
}

data class ChatMessage(val role:String, val text:String)

@Composable fun MemoryAIApp() {
    var input by remember { mutableStateOf("") }
    var messages by remember { mutableStateOf(listOf(ChatMessage("assistant", "Привет. Я Memory AI — твой постоянный ассистент. Память будет храниться локально на телефоне."))) }
    Scaffold(topBar={ TopAppBar(title={Text("Memory AI")}) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).padding(12.dp)) {
            LazyColumn(Modifier.weight(1f).fillMaxWidth()) { items(messages) { m ->
                Text(if(m.role=="user") "Вы: ${m.text}" else "AI: ${m.text}", Modifier.padding(vertical=8.dp))
            }}
            Row(Modifier.fillMaxWidth()) {
                OutlinedTextField(input,{input=it},Modifier.weight(1f),placeholder={Text("Напишите сообщение...")})
                Spacer(Modifier.width(8.dp))
                Button(onClick={ if(input.isNotBlank()){ messages += ChatMessage("user",input); messages += ChatMessage("assistant","Сообщение сохранено. Подключение модели и долговременной памяти — следующий слой агента."); input="" }}) { Text("➤") }
            }
        }
    }
}
