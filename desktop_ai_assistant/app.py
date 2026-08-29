import json
import os
import sqlite3
import threading
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

APP_NAME = "Memory AI"
DATA_DIR = Path.home() / ".memory_ai"
DB_PATH = DATA_DIR / "memory.db"
CONFIG_PATH = DATA_DIR / "config.json"


def load_config():
    defaults = {
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "",
        "model": "llama3.2"
    }
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        defaults.update(cfg)
    except Exception:
        pass
    return defaults


def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


class MemoryStore:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        self.db.commit()

    def add_message(self, role, content):
        self.db.execute("INSERT INTO messages(role, content, created_at) VALUES(?,?,?)",
                        (role, content, datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    def add_memory(self, fact):
        self.db.execute("INSERT INTO memories(fact, created_at) VALUES(?,?)",
                        (fact, datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    def recent(self, limit=30):
        rows = self.db.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return list(reversed(rows))

    def search(self, query, limit=12):
        words = [w.strip(".,!?;:()[]{}\"'").lower() for w in query.split() if len(w) > 2]
        rows = self.db.execute("SELECT id, role, content, created_at FROM messages ORDER BY id DESC LIMIT 1000").fetchall()
        scored = []
        for row in rows:
            text = row[2].lower()
            score = sum(text.count(w) for w in words)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda x: (x[0], x[1][0]), reverse=True)
        return [x[1] for x in scored[:limit]]

    def all_memories(self):
        return self.db.execute("SELECT id, fact, created_at FROM memories ORDER BY id DESC").fetchall()

    def clear(self):
        self.db.execute("DELETE FROM messages")
        self.db.execute("DELETE FROM memories")
        self.db.commit()


class AIClient:
    def __init__(self, cfg):
        self.cfg = cfg

    def chat(self, messages):
        base = self.cfg["base_url"].rstrip("/")
        url = base + "/chat/completions"
        payload = json.dumps({
            "model": self.cfg["model"],
            "messages": messages,
            "temperature": 0.7
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("api_key"):
            headers["Authorization"] = "Bearer " + self.cfg["api_key"]
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.URLError as e:
            raise RuntimeError(f"Не удалось подключиться к AI: {e}")
        except (KeyError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Некорректный ответ AI: {e}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1000x720")
        self.minsize(760, 560)
        self.cfg = load_config()
        self.memory = MemoryStore()
        self.client = AIClient(self.cfg)
        self._build_ui()
        self._load_recent()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Memory AI", font=("TkDefaultFont", 16, "bold")).grid(row=0, column=0, padx=(0, 15))
        ttk.Label(top, text=f"Модель: {self.cfg['model']}").grid(row=0, column=1, sticky="w")
        ttk.Button(top, text="Настройки", command=self.settings).grid(row=0, column=2, padx=5)
        ttk.Button(top, text="Память", command=self.show_memory).grid(row=0, column=3, padx=5)
        ttk.Button(top, text="Очистить всё", command=self.clear_memory).grid(row=0, column=4, padx=(5, 0))

        self.chat = tk.Text(self, wrap="word", state="disabled", padx=14, pady=14, font=("TkDefaultFont", 11))
        self.chat.grid(row=1, column=0, sticky="nsew", padx=10)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.chat.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=10)
        self.chat.configure(yscrollcommand=scroll.set)

        bottom = ttk.Frame(self, padding=10)
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        self.input = tk.Text(bottom, height=4, wrap="word", font=("TkDefaultFont", 11))
        self.input.grid(row=0, column=0, sticky="ew")
        self.input.bind("<Control-Return>", lambda e: self.send())
        ttk.Button(bottom, text="Отправить  Ctrl+Enter", command=self.send).grid(row=0, column=1, padx=(8, 0), sticky="ns")
        ttk.Label(bottom, text="Все сообщения сохраняются локально в SQLite.").grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _append(self, who, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"\n{who}\n{text}\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _load_recent(self):
        for role, content in self.memory.recent(40):
            self._append("Вы" if role == "user" else "AI", content)

    def send(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self.memory.add_message("user", text)
        self._append("Вы", text)
        self._append("AI", "Думаю…")
        threading.Thread(target=self._answer, args=(text,), daemon=True).start()

    def _answer(self, text):
        try:
            relevant = self.memory.search(text)
            recent = self.memory.recent(20)
            context = []
            if relevant:
                context.append("Релевантные фрагменты долгосрочной памяти:\n" + "\n".join(f"- {r[2]}" for r in relevant))
            system = (
                "Ты персональный AI-ассистент пользователя. Отвечай на языке пользователя. "
                "Используй память ниже, но не выдумывай факты. Если пользователь сообщает важную "
                "долгосрочную информацию о себе, проекте, предпочтениях или задачах, учитывай её в будущих ответах. "
                "Все предыдущие сообщения хранятся локально.\n\n" + "\n".join(context)
            )
            messages = [{"role": "system", "content": system}]
            messages.extend({"role": r, "content": c} for r, c in recent)
            answer = self.client.chat(messages)
            self.memory.add_message("assistant", answer)
            self.after(0, lambda: self._replace_last_thinking(answer))
        except Exception as e:
            self.after(0, lambda: self._replace_last_thinking("Ошибка: " + str(e)))

    def _replace_last_thinking(self, answer):
        self.chat.configure(state="normal")
        text = self.chat.get("1.0", "end-1c")
        marker = "\nAI\nДумаю…\n"
        idx = text.rfind(marker)
        if idx >= 0:
            self.chat.delete(f"1.0 + {idx + 1} chars", "end")
            self.chat.insert("end", "\nAI\n" + answer + "\n")
        else:
            self.chat.insert("end", "\nAI\n" + answer + "\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def settings(self):
        win = tk.Toplevel(self)
        win.title("Настройки AI")
        win.geometry("560x260")
        win.transient(self)
        fields = [("OpenAI-compatible URL", "base_url"), ("API key", "api_key"), ("Model", "model")]
        vars_ = {}
        for i, (label, key) in enumerate(fields):
            ttk.Label(win, text=label).grid(row=i, column=0, padx=12, pady=10, sticky="w")
            v = tk.StringVar(value=self.cfg.get(key, ""))
            vars_[key] = v
            ttk.Entry(win, textvariable=v, width=52, show="*" if key == "api_key" else "").grid(row=i, column=1, padx=12, pady=10)
        ttk.Label(win, text="По умолчанию используется Ollama на этом компьютере.").grid(row=3, column=0, columnspan=2, padx=12, pady=5)
        def save():
            for key, v in vars_.items(): self.cfg[key] = v.get().strip()
            save_config(self.cfg)
            self.client.cfg = self.cfg
            win.destroy()
            messagebox.showinfo("Готово", "Настройки сохранены.")
        ttk.Button(win, text="Сохранить", command=save).grid(row=4, column=1, pady=12, sticky="e")

    def show_memory(self):
        win = tk.Toplevel(self)
        win.title("Память")
        win.geometry("760x560")
        txt = tk.Text(win, wrap="word", padx=12, pady=12)
        txt.pack(fill="both", expand=True)
        rows = self.memory.all_memories()
        txt.insert("end", "Локальная история сообщений хранится в: " + str(DB_PATH) + "\n\n")
        txt.insert("end", f"Сообщений: {self.memory.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]}\n")
        txt.insert("end", f"Сохранённых фактов: {len(rows)}\n\n")
        for _, fact, created in rows:
            txt.insert("end", f"[{created}] {fact}\n")
        txt.configure(state="disabled")

    def clear_memory(self):
        if messagebox.askyesno("Очистить память", "Удалить всю локальную историю и память? Это действие нельзя отменить."):
            self.memory.clear()
            self.chat.configure(state="normal")
            self.chat.delete("1.0", "end")
            self.chat.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
