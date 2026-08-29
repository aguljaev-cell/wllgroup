package com.worldlogicline.assistant

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider

class AssistantViewModelFactory(
    private val store: MemoryStore,
    private val api: AssistantApi
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        require(modelClass.isAssignableFrom(AssistantViewModel::class.java))
        return AssistantViewModel(store, api) as T
    }
}
