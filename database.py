import sqlite3
import os
from typing import Optional, List, Dict
from config import settings

DB_PATH = os.path.join(os.path.dirname(__file__), "assistant_bot.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id INTEGER PRIMARY KEY,
        system_prompt TEXT,
        inbox_topic_id INTEGER,
        openai_model TEXT,
        auto_create_topics INTEGER DEFAULT 1
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS forum_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        topic_name TEXT,
        message_thread_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(chat_id, topic_name)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS processed_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        url_or_hash TEXT,
        title TEXT,
        summary TEXT,
        why_useful TEXT,
        tags TEXT,
        target_topic_name TEXT,
        target_thread_id INTEGER,
        target_message_id INTEGER,
        author_id INTEGER,
        author_username TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()

def get_chat_settings(chat_id: int) -> Dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    
    return {
        "chat_id": chat_id,
        "system_prompt": settings.DEFAULT_SYSTEM_PROMPT,
        "inbox_topic_id": None,
        "openai_model": settings.OPENAI_MODEL,
        "auto_create_topics": 1
    }

def update_system_prompt(chat_id: int, prompt: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO chat_settings (chat_id, system_prompt, openai_model)
    VALUES (?, ?, ?)
    ON CONFLICT(chat_id) DO UPDATE SET system_prompt = excluded.system_prompt
    """, (chat_id, prompt, settings.OPENAI_MODEL))
    conn.commit()
    conn.close()

def update_inbox_topic(chat_id: int, topic_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO chat_settings (chat_id, inbox_topic_id, system_prompt, openai_model)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(chat_id) DO UPDATE SET inbox_topic_id = excluded.inbox_topic_id
    """, (chat_id, topic_id, settings.DEFAULT_SYSTEM_PROMPT, settings.OPENAI_MODEL))
    conn.commit()
    conn.close()

def update_openai_model(chat_id: int, model: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO chat_settings (chat_id, openai_model, system_prompt)
    VALUES (?, ?, ?)
    ON CONFLICT(chat_id) DO UPDATE SET openai_model = excluded.openai_model
    """, (chat_id, model, settings.DEFAULT_SYSTEM_PROMPT))
    conn.commit()
    conn.close()

def save_forum_topic(chat_id: int, topic_name: str, message_thread_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO forum_topics (chat_id, topic_name, message_thread_id)
    VALUES (?, ?, ?)
    ON CONFLICT(chat_id, topic_name) DO UPDATE SET message_thread_id = excluded.message_thread_id
    """, (chat_id, topic_name.strip(), message_thread_id))
    conn.commit()
    conn.close()

def get_known_topics(chat_id: int) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT topic_name, message_thread_id FROM forum_topics WHERE chat_id = ?", (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def find_topic_by_name(chat_id: int, topic_name: str) -> Optional[int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT message_thread_id FROM forum_topics WHERE chat_id = ? AND LOWER(topic_name) = LOWER(?)", (chat_id, topic_name.strip()))
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT message_thread_id FROM forum_topics WHERE chat_id = ? AND LOWER(topic_name) LIKE LOWER(?)", (chat_id, f"%{topic_name.strip()}%"))
        row = cursor.fetchone()
    conn.close()
    return row["message_thread_id"] if row else None

def check_item_already_processed(chat_id: int, url_or_hash: str) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM processed_items WHERE chat_id = ? AND url_or_hash = ?", (chat_id, url_or_hash.strip()))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def record_processed_item(chat_id: int, url_or_hash: str, title: str, summary: str, why_useful: str, tags: str, target_topic_name: str, target_thread_id: int, target_message_id: int, author_id: int, author_username: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO processed_items (chat_id, url_or_hash, title, summary, why_useful, tags, target_topic_name, target_thread_id, target_message_id, author_id, author_username)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (chat_id, url_or_hash.strip(), title, summary, why_useful, tags, target_topic_name, target_thread_id, target_message_id, author_id, author_username))
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return item_id

def get_item_by_id(item_id: int) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM processed_items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_recent_processed_items(chat_id: int, limit: int = 15) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM processed_items WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_chat_statistics(chat_id: int) -> Dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM processed_items WHERE chat_id = ?", (chat_id,))
    total = cursor.fetchone()["total"]
    
    cursor.execute("SELECT target_topic_name, COUNT(*) as count FROM processed_items WHERE chat_id = ? GROUP BY target_topic_name ORDER BY count DESC LIMIT 5", (chat_id,))
    top_topics = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    return {"total": total, "top_topics": top_topics}

def export_knowledge_base_markdown(chat_id: int) -> str:
    """Генерирует готовый Markdown-документ базы знаний для экспорта в Obsidian / Notion"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM processed_items WHERE chat_id = ? ORDER BY target_topic_name, id DESC", (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return "# 📚 База знаний пуста\n\nВ группу пока не отправляли материалы."
        
    md = "# 📚 БАЗА ЗНАНИЙ КОМАНДЫ (TELEGRAM FORUM)\n\n"
    md += f"Всего сохранено материалов: **{len(rows)}**\n\n---\n\n"
    
    current_topic = None
    for r in rows:
        topic = r["target_topic_name"]
        if topic != current_topic:
            current_topic = topic
            md += f"\n## 📂 Ветка: {current_topic}\n\n"
            
        md += f"### 📌 {r['title']}\n"
        md += f"- **Источник:** {r['url_or_hash']}\n"
        md += f"- **Автор:** @{r['author_username'] or 'Участник'} ({r['created_at'][:10]})\n"
        md += f"- **Суть:** {r['summary']}\n"
        if r['why_useful']:
            md += f"- **Польза:** {r['why_useful']}\n"
        if r['tags']:
            md += f"- **Теги:** `{r['tags']}`\n"
        md += "\n"
        
    return md

init_db()
