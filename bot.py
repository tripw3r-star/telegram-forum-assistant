import asyncio
import logging
import os
import re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, Filter

bot_info: types.User = None

class BotMentionFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if not message.text or not bot_info or not bot_info.username:
            return False
        return f"@{bot_info.username}" in message.text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
import database as db
import web_extractor
import ai_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

async def safe_edit_text(message: types.Message, text: str, disable_web_page_preview: bool = True):
    """Безопасно редактирует сообщение с защитой от лимитов длины и ошибок парсинга HTML"""
    if len(text) > 4000:
        text = text[:3950] + "...\n\n<i>(сообщение сокращено)</i>"
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=disable_web_page_preview)
    except Exception as e:
        logger.warning(f"Telegram HTML parse failed: {e}. Falling back to plain text.")
        clean_text = re.sub(r"<[^>]+>", "", text)
        try:
            await message.edit_text(clean_text, parse_mode=None, disable_web_page_preview=disable_web_page_preview)
        except Exception as e2:
            logger.error(f"Fallback edit failed: {e2}")

class AdminStates(StatesGroup):
    waiting_for_system_prompt = State()
    waiting_for_model_name = State()

def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS

# ----------------- КОМАНДЫ -----------------

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type == "private":
        await message.answer(
            "👋 <b>Привет! Я продвинутый ИИ-куратор базы знаний для групп с ветками (форумов).</b>\n\n"
            "📌 <b>Основные возможности:</b>\n"
            "• Авто-сортировка из ветки <b>«📥 Входящие»</b> по тематическим топикам с анализом сути и пользы.\n"
            "• Автоматическое создание веток с <b>закреплённым README-гайдом</b>.\n"
            "• 🌐 <code>/research &lt;запрос&gt;</code> — живой ресерч по всему интернету в реальном времени.\n"
            "• <code>/digest</code> — еженедельный дайджест базы знаний.\n"
            "• <code>/ask &lt;вопрос&gt;</code> — семантический поиск по накопленным материалам.\n"
            "• <code>/export</code> — экспорт всей базы знаний в Markdown для Obsidian / Notion.\n"
            "• Кнопка «📝 Сгенерировать ТЗ» под каждым материалом.\n\n"
            "⚙️ Админка: <code>/admin</code>"
        )
    else:
        await message.answer("👋 Бот активен! Для создания ветки входящих введите <code>/setup</code>")

@dp.message(Command("setup"))
async def cmd_setup(message: types.Message):
    if not message.chat.is_forum:
        await message.reply("⚠️ Включите в настройках группы: «Темы» (Topics / Форум), чтобы бот мог работать с ветками.")
        return

    chat_id = message.chat.id
    cfg = db.get_chat_settings(chat_id)
    inbox_id = cfg.get("inbox_topic_id")

    if not inbox_id:
        try:
            topic = await bot.create_forum_topic(
                chat_id=chat_id,
                name=settings.DEFAULT_INBOX_TOPIC_NAME,
                icon_color=0x6FB9F0
            )
            inbox_id = topic.message_thread_id
            db.update_inbox_topic(chat_id, inbox_id)
            db.save_forum_topic(chat_id, settings.DEFAULT_INBOX_TOPIC_NAME, inbox_id)
            await message.reply(
                f"✅ Ветка <b>«{settings.DEFAULT_INBOX_TOPIC_NAME}»</b> создана (ID: <code>{inbox_id}</code>)!\n\n"
                f"Кидайте сюда любые ссылки, GitHub, YouTube и документы — я выйду в интернет, разберу их и распределю по веткам!"
            )
        except Exception as e:
            await message.reply(f"❌ Ошибка создания темы: {e}\nУбедитесь, что у бота включено право <b>«Управление темами»</b>.")
    else:
        await message.reply(f"ℹ️ Ветка входящих уже готова (Thread ID: <code>{inbox_id}</code>). Можно скидывать материалы!")

# ----------------- БОНУС: ЭКСПОРТ В OBSIDIAN / NOTION (/export) -----------------

@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    """Экспорт базы знаний в чистый Markdown файл"""
    chat_id = message.chat.id
    md_content = db.export_knowledge_base_markdown(chat_id)
    
    file_bytes = md_content.encode("utf-8")
    input_file = BufferedInputFile(file_bytes, filename="telegram_knowledge_base.md")
    
    await message.reply_document(
        document=input_file,
        caption="📚 <b>Экспорт базы знаний готов!</b>\nФайл <code>telegram_knowledge_base.md</code> полностью совместим с <b>Obsidian</b>, <b>Notion</b> и <b>GitHub Wiki</b>."
    )

# ----------------- АДМИНКА -----------------

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        if message.chat.type in ["group", "supergroup"]:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            if member.status not in ["creator", "administrator"]:
                await message.reply("⛔ Доступ только для администраторов.")
                return
        else:
            await message.reply("⛔ Вы не числитесь в ADMIN_IDS.")
            return

    chat_id = message.chat.id if message.chat.type in ["group", "supergroup"] else (settings.ADMIN_IDS[0] if settings.ADMIN_IDS else message.from_user.id)
    cfg = db.get_chat_settings(chat_id)
    stats = db.get_chat_statistics(chat_id)

    top_str = "\n".join([f"  • {t['target_topic_name']}: {t['count']} шт." for t in stats["top_topics"]]) or "  (пока пусто)"

    text = (
        "⚙️ <b>АДМИН-ПАНЕЛЬ ИИ-АССИСТЕНТА</b>\n\n"
        f"🤖 <b>Модель:</b> <code>{cfg['openai_model']}</code>\n"
        f"🌐 <b>API URL:</b> <code>{settings.OPENAI_BASE_URL}</code>\n"
        f"📥 <b>ID ветки «Входящие»:</b> <code>{cfg.get('inbox_topic_id') or 'Не задан (/setup)'}</code>\n"
        f"📊 <b>Разобрано материалов:</b> {stats['total']}\n"
        f"📁 <b>Топ веток:</b>\n{top_str}\n\n"
        f"📝 <b>Системный промпт:</b>\n<i>{cfg['system_prompt']}</i>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить системный промпт", callback_data=f"set_sys_{chat_id}")],
        [InlineKeyboardButton(text="🔄 Сменить модель ИИ", callback_data=f"set_model_{chat_id}")],
        [InlineKeyboardButton(text="📢 Сформировать дайджест сейчас", callback_data=f"run_digest_{chat_id}")],
        [InlineKeyboardButton(text="📚 Экспорт базы знаний (.md)", callback_data=f"run_export_{chat_id}")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("set_sys_"))
async def cb_set_system(call: types.CallbackQuery, state: FSMContext):
    chat_id = int(call.data.split("_")[2])
    await state.update_data(target_chat_id=chat_id)
    await state.set_state(AdminStates.waiting_for_system_prompt)
    await call.message.answer("📝 <b>Пришлите новый системный промпт:</b>")
    await call.answer()

@dp.message(AdminStates.waiting_for_system_prompt)
async def state_save_system_prompt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get("target_chat_id", message.chat.id)
    new_prompt = message.text.strip()
    db.update_system_prompt(chat_id, new_prompt)
    await state.clear()
    await message.reply("✅ <b>Системный промпт успешно сохранён в БД!</b>")

@dp.callback_query(F.data.startswith("set_model_"))
async def cb_set_model(call: types.CallbackQuery, state: FSMContext):
    chat_id = int(call.data.split("_")[2])
    await state.update_data(target_chat_id=chat_id)
    await state.set_state(AdminStates.waiting_for_model_name)
    await call.message.answer("🤖 <b>Введите название модели:</b>\nНапример: <code>openrouter/free</code>, <code>deepseek/deepseek-chat</code>")
    await call.answer()

@dp.message(AdminStates.waiting_for_model_name)
async def state_save_model(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get("target_chat_id", message.chat.id)
    new_model = message.text.strip()
    db.update_openai_model(chat_id, new_model)
    await state.clear()
    await message.reply(f"✅ <b>Модель переключена на:</b> <code>{new_model}</code>")

@dp.callback_query(F.data.startswith("run_export_"))
async def cb_run_export(call: types.CallbackQuery):
    chat_id = int(call.data.split("_")[2])
    md_content = db.export_knowledge_base_markdown(chat_id)
    input_file = BufferedInputFile(md_content.encode("utf-8"), filename="knowledge_base.md")
    await call.message.answer_document(document=input_file, caption="📚 Экспорт базы знаний (.md)")
    await call.answer()

# ----------------- ДАЙДЖЕСТ (/digest) -----------------

@dp.message(Command("digest"))
async def cmd_digest(message: types.Message):
    chat_id = message.chat.id
    items = db.get_recent_processed_items(chat_id, limit=12)
    if not items:
        await message.reply("ℹ️ В базе пока нет сохранённых материалов для составления дайджеста.")
        return

    wait_msg = await message.reply("⏳ <i>Формирую умный дайджест по материалам группы...</i>")
    cfg = db.get_chat_settings(chat_id)
    digest_text = await ai_router.generate_group_digest(items, custom_model=cfg["openai_model"])

    digest_topic_id = db.find_topic_by_name(chat_id, "📢 Дайджесты")
    if not digest_topic_id and message.chat.is_forum:
        try:
            t = await bot.create_forum_topic(chat_id, name="📢 Дайджесты", icon_color=0xFFD67E)
            digest_topic_id = t.message_thread_id
            db.save_forum_topic(chat_id, "📢 Дайджесты", digest_topic_id)
        except Exception:
            digest_topic_id = message.message_thread_id

    if digest_topic_id:
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=digest_topic_id,
            text=f"📢 <b>ДАЙДЖЕСТ МАТЕРИАЛОВ ГРУППЫ</b>\n\n{digest_text}"
        )
        await wait_msg.edit_text(f"✅ <b>Дайджест готов и опубликован в ветку «📢 Дайджесты»!</b>")
    else:
        await wait_msg.edit_text(f"📢 <b>ДАЙДЖЕСТ МАТЕРИАЛОВ ГРУППЫ:</b>\n\n{digest_text}")

@dp.callback_query(F.data.startswith("run_digest_"))
async def cb_run_digest(call: types.CallbackQuery):
    chat_id = int(call.data.split("_")[2])
    items = db.get_recent_processed_items(chat_id, limit=12)
    if not items:
        await call.answer("Пока нет материалов в базе", show_alert=True)
        return
    await call.answer("Генерирую дайджест...")
    cfg = db.get_chat_settings(chat_id)
    digest_text = await ai_router.generate_group_digest(items, custom_model=cfg["openai_model"])
    await call.message.answer(f"📢 <b>ДАЙДЖЕСТ МАТЕРИАЛОВ:</b>\n\n{digest_text}")

# ----------------- ПОИСК ПО БАЗЕ ЗНАНИЙ (/ask) -----------------

@dp.message(Command("ask"))
async def cmd_ask(message: types.Message):
    query = message.text.replace("/ask", "").strip()
    if not query:
        await message.reply("💡 <b>Пример использования:</b>\n<code>/ask какие у нас были ссылки по парсингу на python?</code>")
        return

    chat_id = message.chat.id
    items = db.get_recent_processed_items(chat_id, limit=20)
    if not items:
        await message.reply("В базе пока нет материалов.")
        return

    wait_msg = await message.reply("🔍 <i>Ищу по базе знаний группы...</i>")
    try:
        cfg = db.get_chat_settings(chat_id)
        answer = await ai_router.answer_knowledge_query(query, items, custom_model=cfg["openai_model"])
        await safe_edit_text(wait_msg, f"🤖 <b>Ответ по базе знаний:</b>\n\n{answer}")
    except Exception as e:
        logger.error(f"Ask error: {e}")
        await safe_edit_text(wait_msg, f"❌ <b>Ошибка поиска:</b> {e}")

# ----------------- ИНТЕРАКТИВНЫЕ КНОПКИ: СГЕНЕРИРОВАТЬ ТЗ -----------------

@dp.callback_query(F.data.startswith("gentask_"))
async def cb_gen_task(call: types.CallbackQuery):
    item_id = int(call.data.split("_")[1])
    item = db.get_item_by_id(item_id)
    if not item:
        await call.answer("Материал не найден в БД", show_alert=True)
        return

    await call.answer("Генерирую ТЗ на основе материала...")
    cfg = db.get_chat_settings(item["chat_id"])
    task_spec = await ai_router.generate_task_spec(
        title=item["title"],
        what_is_it=item["summary"],
        why_useful=item.get("why_useful", ""),
        custom_model=cfg["openai_model"]
    )

    await bot.send_message(
        chat_id=item["chat_id"],
        message_thread_id=item["target_thread_id"],
        text=(
            f"📋 <b>ЧЕРНОВИК ТЗ ДЛЯ КОМАНДЫ</b>\n"
            f"<i>На основе: {item['title']}</i>\n\n"
            f"{task_spec}"
        )
    )

# ----------------- УПОМИНАНИЕ БОТА В ЧАТЕ -----------------

@dp.message(BotMentionFilter())
async def handle_bot_mention(message: types.Message):
    """Ответ на прямое обращение к боту в любой ветке по сохранённым материалам"""
    mention_str = f"@{bot_info.username}"
    query = message.text.replace(mention_str, "").strip()
    if not query:
        await message.reply("Привет! Скинь ссылку во «Входящие» — я разберусь и сохраню её в нужную ветку.")
        return

    wait_msg = await message.reply("🤖 <i>Ищу в базе знаний группы...</i>")
    try:
        cfg = db.get_chat_settings(message.chat.id)
        items = db.get_recent_processed_items(message.chat.id, limit=20)
        if not items:
            await wait_msg.edit_text("ℹ️ В базе пока нет сохранённых материалов. Отправьте ссылки во «Входящие»!")
            return
        answer = await ai_router.answer_knowledge_query(query, items, custom_model=cfg["openai_model"])
        await safe_edit_text(wait_msg, f"🤖 <b>Ответ по базе знаний:</b>\n\n{answer}")
    except Exception as e:
        logger.error(f"Bot mention error: {e}")
        await safe_edit_text(wait_msg, f"❌ <b>Ошибка:</b> {e}")

# ----------------- ОСНОВНАЯ ОБРАБОТКА ВХОДЯЩИХ -----------------

@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_message(message: types.Message):
    if not message.chat.is_forum:
        return

    chat_id = message.chat.id
    cfg = db.get_chat_settings(chat_id)
    inbox_thread_id = cfg.get("inbox_topic_id")

    if message.message_thread_id and message.forum_topic_created:
        db.save_forum_topic(chat_id, message.forum_topic_created.name, message.message_thread_id)
        return

    if not inbox_thread_id and message.message_thread_id:
        known_id = db.find_topic_by_name(chat_id, settings.DEFAULT_INBOX_TOPIC_NAME)
        if known_id:
            inbox_thread_id = known_id
            db.update_inbox_topic(chat_id, inbox_thread_id)

    if message.message_thread_id != inbox_thread_id:
        return

    if message.text and message.text.startswith("/"):
        return

    text_content = message.text or message.caption or ""
    extracted_url = web_extractor.extract_first_url(text_content)
    document = message.document

    if not extracted_url and not document and len(text_content.strip()) < 30:
        return

    dedup_key = extracted_url or (document.file_unique_id if document else text_content[:150])
    already_saved = db.check_item_already_processed(chat_id, dedup_key)
    if already_saved:
        await message.reply(
            f"ℹ️ <b>Этот материал уже был сохранён ранее!</b>\n"
            f"Ветка: <b>«{already_saved['target_topic_name']}»</b>\n"
            f"Суть: <i>{already_saved['summary']}</i>"
        )
        return

    status_msg = await message.reply("🔍 <i>Выхожу в интернет, изучаю материал...</i>")

    raw_data = ""
    res_title = "Материал"

    if extracted_url:
        page_info = await web_extractor.fetch_web_page_content(extracted_url)
        raw_data = page_info["raw_text"]
        res_title = page_info.get("title") or extracted_url
    elif document:
        res_title = document.file_name or "Документ"
        if document.file_size and document.file_size < 1024 * 1024 * 2:
            file_info = await bot.get_file(document.file_id)
            file_bytes = await bot.download_file(file_info.file_path)
            try:
                raw_data = file_bytes.read().decode("utf-8", errors="ignore")[:4000]
            except Exception:
                raw_data = f"Документ: {document.file_name}, тип: {document.mime_type}"
        else:
            raw_data = f"Файл: {document.file_name}"
    else:
        raw_data = text_content[:3500]

    known_topics = [t["topic_name"] for t in db.get_known_topics(chat_id) if t["topic_name"] != settings.DEFAULT_INBOX_TOPIC_NAME]
    
    analysis = await ai_router.analyze_and_route_content(
        content_text=raw_data,
        user_comment=text_content,
        existing_topics=known_topics,
        custom_system_prompt=cfg["system_prompt"],
        custom_model=cfg["openai_model"]
    )

    target_category = analysis["category"]

    # Ищем существующую ветку или создаём новую С ЗАКРЕПЛЁННЫМ README!
    target_thread_id = db.find_topic_by_name(chat_id, target_category)
    if not target_thread_id:
        try:
            new_topic = await bot.create_forum_topic(chat_id=chat_id, name=target_category)
            target_thread_id = new_topic.message_thread_id
            db.save_forum_topic(chat_id, target_category, target_thread_id)
            
            # БОНУС: Генерируем и закрепляем вводный README ветки
            readme_text = await ai_router.generate_topic_readme(target_category, custom_model=cfg["openai_model"])
            readme_msg = await bot.send_message(chat_id=chat_id, message_thread_id=target_thread_id, text=readme_text)
            try:
                await bot.pin_chat_message(chat_id=chat_id, message_id=readme_msg.message_id)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Не удалось создать тему: {e}")
            target_thread_id = inbox_thread_id

    author_name = message.from_user.full_name
    author_tag = f"@{message.from_user.username}" if message.from_user.username else author_name
    source_link = extracted_url or (f"Файл: <code>{document.file_name}</code>" if document else "Заметка")

    orig_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{message.message_id}"

    card_text = (
        f"📌 <b>{analysis['title']}</b>\n\n"
        f"🔗 <b>Источник:</b> {source_link}\n"
        f"👤 <b>Добавил:</b> {author_tag}\n\n"
        f"💡 <b>Что это такое:</b>\n{analysis['what_is_it']}\n\n"
        f"🎯 <b>Зачем это команде:</b>\n{analysis['why_useful']}\n\n"
        f"🏷 <code>{analysis['tags']}</code>"
    )

    item_id = db.record_processed_item(
        chat_id=chat_id,
        url_or_hash=dedup_key,
        title=analysis["title"],
        summary=analysis["what_is_it"],
        why_useful=analysis["why_useful"],
        tags=analysis["tags"],
        target_topic_name=target_category,
        target_thread_id=target_thread_id,
        target_message_id=0,
        author_id=message.from_user.id,
        author_username=message.from_user.username or ""
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Исходное сообщение во Входящих", url=orig_link)],
        [InlineKeyboardButton(text="📝 Сгенерировать задачу / ТЗ", callback_data=f"gentask_{item_id}")]
    ])

    sent_card = await bot.send_message(
        chat_id=chat_id,
        message_thread_id=target_thread_id,
        text=card_text,
        reply_markup=kb,
        disable_web_page_preview=False
    )

    card_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{sent_card.message_id}"
    done_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📂 Открыть в «{target_category}»", url=card_link)]
    ])
    await status_msg.edit_text(
        f"✅ <b>Материал разобран и перенесён в ветку «{target_category}»!</b>",
        reply_markup=done_kb
    )

# ----------------- ЗАПУСК -----------------

async def main():
    global bot_info
    bot_info = await bot.get_me()
    print("==================================================")
    print(f"🤖 Telegram Forum Assistant Bot (@{bot_info.username}) запущен!")
    print(f"ID бота: {bot_info.id}")
    print(f"OpenRouter/OpenAI Model: {settings.OPENAI_MODEL}")
    print(f"Админы: {settings.ADMIN_IDS}")
    print("==================================================")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
