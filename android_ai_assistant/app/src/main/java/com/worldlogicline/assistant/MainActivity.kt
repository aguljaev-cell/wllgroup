package com.worldlogicline.assistant

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    private val viewModel by viewModels<AssistantViewModel> {
        AssistantViewModelFactory(
            MemoryStore(this),
            AssistantApi(BuildConfig.API_BASE_URL)
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { WorldLogicLineApp(viewModel) }
    }
}

@Composable
private fun WorldLogicLineApp(viewModel: AssistantViewModel) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(topBar = { TopAppBar(title = { Text("WorldLogicLine Assistant") }) }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).padding(12.dp)) {
            if (state.messages.isEmpty()) {
                Text("WorldLogicLine Assistant готов. Чем помочь?", Modifier.padding(8.dp))
            }
            LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
                items(state.messages) { message ->
                    Text(
                        if (message.role == "user") "Вы: ${message.text}" else "Assistant: ${message.text}",
                        Modifier.padding(vertical = 8.dp)
                    )
                }
            }
            state.error?.let { Text("Ошибка: $it", Modifier.padding(vertical = 4.dp)) }
            Row(Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = state.input,
                    onValueChange = viewModel::setInput,
                    modifier = Modifier.weight(1f),
                    enabled = !state.sending,
                    placeholder = { Text("Напишите сообщение...") }
                )
                Spacer(Modifier.width(8.dp))
                Button(enabled = state.input.isNotBlank() && !state.sending, onClick = viewModel::send) {
                    Text(if (state.sending) "…" else "➤")
                }
            }
        }
    }
}
