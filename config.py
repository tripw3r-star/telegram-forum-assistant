import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
    ]
    
    # OpenAI-compatible API
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "openrouter/free")
    OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "2000"))
    
    DEFAULT_INBOX_TOPIC_NAME: str = "📥 Входящие"
    DEFAULT_SYSTEM_PROMPT: str = (
        "Ты — экспертный куратор и технический архитектор группы. "
        "Твоя задача — анализировать ссылки, репозитории, документы и материалы из ветки 'Входящие', "
        "понимать суть (что это), практическую ценность (зачем это нужно команде) "
        "и точно определять наиболее подходящую тематическую ветку для хранения. "
        "Форматируй ответ ёмко, технически грамотно и без лишней 'воды'."
    )

settings = Settings()
