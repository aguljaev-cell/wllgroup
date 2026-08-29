package com.worldlogicline.assistant

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class AssistantUiState(
    val messages: List<ChatMessage> = emptyList(),
    val input: String = "",
    val sending: Boolean = false,
    val error: String? = null
)

class AssistantViewModel(
    private val store: MemoryStore,
    private val api: AssistantApi
) : ViewModel() {
    private val _uiState = MutableStateFlow(AssistantUiState(messages = store.load()))
    val uiState: StateFlow<AssistantUiState> = _uiState.asStateFlow()

    fun setInput(value: String) {
        _uiState.value = _uiState.value.copy(input = value, error = null)
    }

    fun send() {
        val text = _uiState.value.input.trim()
        if (text.isBlank() || _uiState.value.sending) return

        val updated = _uiState.value.messages + ChatMessage("user", text)
        store.save(updated)
        _uiState.value = _uiState.value.copy(messages = updated, input = "", sending = true, error = null)

        viewModelScope.launch {
            runCatching { api.send(text) }
                .onSuccess { reply ->
                    val withReply = _uiState.value.messages + ChatMessage("assistant", reply)
                    store.save(withReply)
                    _uiState.value = _uiState.value.copy(messages = withReply, sending = false)
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        sending = false,
                        error = error.message ?: "Не удалось получить ответ AI"
                    )
                }
        }
    }
}
