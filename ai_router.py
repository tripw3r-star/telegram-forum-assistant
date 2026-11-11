import json
import re
from typing import List, Dict, Optional
from openai import AsyncOpenAI
from config import settings

def get_openai_client(base_url: Optional[str] = None, api_key: Optional[str] = None) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key or settings.OPENAI_API_KEY,
        base_url=base_url or settings.OPENAI_BASE_URL
    )

def extract_message_text(message) -> str:
    """Безопасно извлекает текст ответа даже из reasoning-моделей (DeepSeek R1, Nemotron)"""
    if not message:
        return ""
    text = getattr(message, "content", "") or ""
    if not text and hasattr(message, "reasoning"):
        text = getattr(message, "reasoning", "") or ""
    return str(text).strip()

def clean_markdown_to_html(text: str) -> str:
    """Конвертирует markdown (###, **, *, ---) и очищает неподдерживаемые HTML теги Telegram"""
    if not text:
        return ""
    
    # 1. Заменяем неподдерживаемые структурные HTML-теги
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(ul|ol|div|span|h[1-6])\b[^>]*>", "", text, flags=re.IGNORECASE)
    
    # 2. Markdown -> HTML
    text = re.sub(r"^[ \t]*[-_]{3,}[ \t]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*([^\*\n]+?)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"#{2,}", "", text)
    text = re.sub(r"\n?[^\n]*\(материалов нет\)[^\n]*\n?", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # 3. Фильтр допустимых тегов Telegram: только b, i, u, s, code, pre, a
    def tag_filter(match):
        tag = match.group(0)
        if re.match(r"^</?(b|i|u|s|code|pre)>$", tag, re.IGNORECASE):
            return tag
        if re.match(r"^</?a(\s+href=[\"'][^\"']+[\"'])?\s*>$", tag, re.IGNORECASE):
            return tag
        return ""

    text = re.sub(r"<[^>]+>", tag_filter, text)
    return text.strip()

ROUTING_PROMPT_TEMPLATE = """
Ты — интеллектуальный классификатор и архивариус контента в Telegram-форуме команды.
Проанализируй предоставленный материал (ссылку, статью, репозиторий GitHub, YouTube-видео или документ) и определи:
1. Краткую суть (Что это такое? 2-3 предложения без воды).
2. Зачем это нужно (Практическая ценность для команды/разработки/бизнеса).
3. В какую ветку (топик форума) это отправить.
   Вот список уже существующих в группе веток:
   {existing_topics_str}
   Если материал подходит под одну из существующих веток — ОБЯЗАТЕЛЬНО выбери её точное название.
   Если ни одна не подходит — придумай новую тему с эмодзи (например: "🛠 Бэкенд & Python", "🤖 AI & Нейросети", "🎨 Дизайн & UI", "⚡ Утилиты & DevOps", "📚 Статьи & Аналитика", "🎬 Видео & Обучение").
4. 3-5 релевантных тегов (например: #python #fastapi #backend).

Верни ответ СТРОГО в формате валидного JSON (без markdown):
{{
  "title": "Название ресурса или репозитория",
  "category": "Название рекомендуемой ветки",
  "what_is_it": "Что это такое (2-3 предложения)...",
  "why_useful": "Зачем это надо (практическая польза)...",
  "tags": ["#тег1", "#тег2", "#тег3"]
}}
"""

async def analyze_and_route_content(
    content_text: str,
    user_comment: str = "",
    existing_topics: Optional[List[str]] = None,
    custom_system_prompt: Optional[str] = None,
    custom_model: Optional[str] = None
) -> Dict:
    client = get_openai_client()
    model = custom_model or settings.OPENAI_MODEL
    
    topics_list = existing_topics or []
    topics_str = ", ".join(f'"{t}"' for t in topics_list) if topics_list else "Пока нет созданных веток"
    
    system_prompt = custom_system_prompt or settings.DEFAULT_SYSTEM_PROMPT
    user_prompt = ROUTING_PROMPT_TEMPLATE.format(existing_topics_str=topics_str)
    context_message = f"Пользовательский комментарий: {user_comment}\n\nМатериал:\n{content_text[:4000]}"
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": user_prompt},
                {"role": "user", "content": context_message}
            ],
            temperature=settings.OPENAI_TEMPERATURE,
            max_tokens=settings.OPENAI_MAX_TOKENS
        )
        raw_answer = extract_message_text(response.choices[0].message)
        json_match = re.search(r"\{.*\}", raw_answer, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
        else:
            data = json.loads(raw_answer)

        return {
            "title": data.get("title", "Полезный материал"),
            "category": data.get("category", "💡 Разное & Идеи").strip(),
            "what_is_it": clean_markdown_to_html(data.get("what_is_it", "")),
            "why_useful": clean_markdown_to_html(data.get("why_useful", "")),
            "tags": " ".join(data.get("tags", [])) if isinstance(data.get("tags"), list) else str(data.get("tags", ""))
        }
    except Exception as e:
        return {
            "title": "Материал из Входящих",
            "category": "💡 Разное & Идеи",
            "what_is_it": content_text[:300] + "...",
            "why_useful": "Полезная ссылка для команды.",
            "tags": "#материалы #входящие"
        }

async def generate_topic_readme(topic_name: str, custom_model: Optional[str] = None) -> str:
    """Генерирует закреплённый README / Гайд ветки при её первом создании"""
    client = get_openai_client()
    model = custom_model or settings.OPENAI_MODEL
    
    prompt = (
        f"Для новой ветки Telegram-форума «{topic_name}» составь краткое закреплённое сообщение (README-хаб ветки).\n"
        "Включи:\n"
        "1. О чем эта ветка (1-2 предложения).\n"
        "2. Что сюда стоит отправлять.\n"
        "3. Рекомендуемые теги.\n\n"
        "ВАЖНО: Форматируй СТРОГО через HTML (<b>жирный</b>, <i>курсив</i>, <code>теги</code>). Без markdown (#, **, *)."
    )
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=600
        )
        raw_text = extract_message_text(response.choices[0].message)
        return clean_markdown_to_html(raw_text) if raw_text else f"📌 <b>БАЗА ЗНАНИЙ ВЕТКИ: {topic_name}</b>\n\nСюда автоматически собираются все материалы по теме."
    except Exception:
        return f"📌 <b>БАЗА ЗНАНИЙ ВЕТКИ: {topic_name}</b>\n\nСюда автоматически собираются все полезные материалы по этой теме."

async def generate_group_digest(items: List[Dict], custom_model: Optional[str] = None) -> str:
    client = get_openai_client()
    model = custom_model or settings.OPENAI_MODEL
    
    items_text = ""
    for idx, item in enumerate(items, 1):
        items_text += f"{idx}. [{item['target_topic_name']}] {item['title']}: {item['summary']} (Польза: {item.get('why_useful', '')})\n"
        
    prompt = (
        "Ты — технический лидер команды. Составь красивый структурированный дайджест последних материалов группы.\n"
        "ВАЖНЫЕ ПРАВИЛА ОФОРМЛЕНИЯ:\n"
        "1. Пиши ТОЛЬКО о тех материалах, которые реально есть в списке. Не создавай пустые категории!\n"
        "2. КАТЕГОРИЧЕСКИ НЕ ИСПОЛЬЗУЙ markdown-символы: никаких решеток (#), никаких звездочек (** или *), никаких линий (---).\n"
        "3. Для выделения используй ТОЛЬКО HTML-теги: <b>жирный текст</b> и <i>курсив</i>.\n"
        "4. Выдели топ-1 находку и напиши краткий общий итог в конце.\n\n"
        f"Материалы:\n{items_text}"
    )
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=settings.OPENAI_MAX_TOKENS
        )
        raw_text = extract_message_text(response.choices[0].message)
        return clean_markdown_to_html(raw_text)
    except Exception as e:
        return f"Ошибка генерации дайджеста: {e}"

async def answer_knowledge_query(query: str, items: List[Dict], custom_model: Optional[str] = None) -> str:
    client = get_openai_client()
    model = custom_model or settings.OPENAI_MODEL
    
    knowledge_base = ""
    for idx, item in enumerate(items, 1):
        knowledge_base += f"- Ветка «{item['target_topic_name']}» | {item['title']}: {item['summary']} (Польза: {item.get('why_useful', '')}) Ссылка: {item['url_or_hash']}\n"
        
    prompt = (
        "Ты — ассистент базы знаний группы. Ответь на вопрос участника, опираясь на сохранённые материалы.\n"
        "ВАЖНО: Не используй markdown (#, ##, **, *). Используй только HTML: <b>жирный</b> и <i>курсив</i>.\n"
        f"Вопрос пользователя: {query}\n\n"
        f"База материалов группы:\n{knowledge_base}"
    )
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=settings.OPENAI_MAX_TOKENS
        )
        raw_text = extract_message_text(response.choices[0].message)
        return clean_markdown_to_html(raw_text)
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def generate_task_spec(title: str, what_is_it: str, why_useful: str, custom_model: Optional[str] = None) -> str:
    client = get_openai_client()
    model = custom_model or settings.OPENAI_MODEL
    
    prompt = (
        f"На основе этого материала сгенерируй конкретный черновик технической задачи (ТЗ) для команды:\n"
        f"Ресурс: {title}\n"
        f"Суть: {what_is_it}\n"
        f"Польза: {why_useful}\n\n"
        f"ВАЖНО: Не используй markdown (#, ##, **, *). Используй ТОЛЬКО HTML: <b>жирный</b> и <i>курсив</i>.\n\n"
        f"Формат:\n"
        f"🎯 <b>Цель задачи</b>\n...\n"
        f"📋 <b>Критерии приёмки</b>\n...\n"
        f"🛠 <b>План реализации</b>\n..."
    )
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=settings.OPENAI_MAX_TOKENS
        )
        raw_text = extract_message_text(response.choices[0].message)
        return clean_markdown_to_html(raw_text)
    except Exception as e:
        return f"Ошибка генерации ТЗ: {e}"
