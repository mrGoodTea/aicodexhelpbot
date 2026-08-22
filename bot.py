import asyncio
import base64
import logging
import os
import random
import tempfile
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    Message,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile,
    FSInputFile,
)
from pypdf import PdfReader

from config import (
    BOT_TOKEN,
    SUBSCRIPTION_PRICE_STARS,
    SUBSCRIPTION_DAYS,
    TRIAL_DAYS,
    FREE_REQUESTS_PER_DAY,
    SHORT_HISTORY_MESSAGES,
    LONG_HISTORY_MESSAGES,
    REFERRAL_BONUS_REQUESTS,
    REFERRAL_SUBSCRIPTION_BONUS_REQUESTS,
    REMINDER_DAYS_BEFORE,
    REMINDER_CHECK_INTERVAL_HOURS,
    MODES,
    ADMIN_USERNAMES,
    OWNER_USERNAME,
    STREAK_BONUS_EVERY_DAYS,
    STREAK_BONUS_REQUESTS,
    GOLDEN_QUERY_INTERVAL_DAYS,
    DYNAMIC_DISCOUNT_ACTIVE_DAYS,
    FREE_CONTEXT_TTL_MINUTES,
    IMAGE_GEN_BASE_URL,
    TEXT_COOLDOWN_SECONDS,
    SPAM_WINDOW_SECONDS,
    SPAM_MAX_MESSAGES,
    SPAM_BLOCK_SECONDS,
    RAG_CHUNK_SIZE,
    RAG_SYSTEM_PROMPT_TEMPLATE,
    SEARCH_COOLDOWN_SECONDS,
    VOICE_MAX_DURATION_SECONDS,
    VISION_DEFAULT_QUESTION,
    VIDEO_NOTE_MAX_DURATION_SECONDS,
    VIDEO_NOTE_MAX_FILE_SIZE_MB,
    VIDEO_NOTE_SIZE_PX,
    FALLBACK_APOLOGIES,
)
import database as db
from groq_client import ask_ai, ask_with_web_search, analyze_image, transcribe_voice

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CONTACT_USERNAME = "Abc123qwerty09"
BOT_USERNAME = ""  # заполняется при старте

# История диалога и вспомогательное состояние в памяти (сбрасывается при перезапуске бота)
user_history: dict[int, list[dict]] = {}
user_history_last_at: dict[int, datetime] = {}   # для TTL контекста бесплатных пользователей
golden_pending: set[int] = set()                  # кто сейчас использует золотой запрос
awaiting_image_prompt: set[int] = set()           # кто сейчас должен прислать описание картинки
awaiting_search_query: set[int] = set()           # кто сейчас должен прислать поисковый запрос
awaiting_kb_document: set[int] = set()            # админ ждём PDF для базы знаний
awaiting_admin_broadcast: set[int] = set()        # админ пишет сообщение в общий чат админов
awaiting_admin_dm: dict[int, int] = {}            # админ пишет личное сообщение конкретному админу (sender_id -> target_id)
awaiting_admin_add: set[int] = set()              # владелец вводит юзернейм нового админа

image_last_request_at: dict[int, datetime] = {}  # защита от слишком частых запросов картинок
IMAGE_COOLDOWN_SECONDS = 16  # анонимный доступ Pollinations ограничен ~1 запросом/15 сек
search_last_request_at: dict[int, datetime] = {}  # защита от слишком частых веб-поисков

# --- Rate limiting / анти-спам ---
text_last_request_at: dict[int, datetime] = {}
message_timestamps: dict[int, list[datetime]] = {}
spam_blocked_until: dict[int, datetime] = {}

# Кнопки нижнего меню
BTN_STATUS = "📊 Статус"
BTN_BUY = "💎 Подписка"
BTN_INVITE = "🎁 Пригласить друга"
BTN_HELP = "ℹ️ Помощь"
BTN_MODE = "🎨 Режим"
BTN_IMAGE = "🖼 Картинка"
BTN_SEARCH = "🌐 Веб-поиск"
BTN_VIDEO_CIRCLE = "⭕ Видео-кружок"
BTN_GOLDEN = "🌟 Золотой запрос"
BTN_ADMIN = "🛠 Админ-панель"

FOMO_TEASERS = [
    "💎 В подписке ответ был бы примерно в 2 раза длиннее, с примерами кода и в режиме под задачу.",
    "💎 Подписчики получают более развёрнутые ответы — с примерами и в выбранном стиле.",
    "💎 С подпиской бот помнил бы весь разговор, а не только последние сообщения.",
]


def is_admin(username: str | None) -> bool:
    if not username:
        return False
    if username in ADMIN_USERNAMES:
        return True
    return db.is_db_admin(username)


def is_owner(username: str | None) -> bool:
    return bool(username) and username == OWNER_USERNAME


def user_has_full_access(user_id: int, username: str | None) -> bool:
    return is_admin(username) or db.is_full_access(user_id)


def main_menu_keyboard(full_access: bool, golden_available: bool = False, username: str | None = None) -> ReplyKeyboardMarkup:
    if full_access:
        keyboard = [
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_MODE)],
            [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_INVITE)],
            [KeyboardButton(text=BTN_IMAGE), KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_VIDEO_CIRCLE)],
            [KeyboardButton(text=BTN_HELP)],
        ]
    else:
        keyboard = [
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_BUY)],
            [KeyboardButton(text=BTN_INVITE), KeyboardButton(text=BTN_HELP)],
        ]
        if golden_available:
            keyboard.append([KeyboardButton(text=BTN_GOLDEN)])
    if is_admin(username):
        keyboard.insert(0, [KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True)


def buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оформить подписку", callback_data="buy_subscription")]
        ]
    )


def mode_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=info["label"], callback_data=f"mode_{key}")]
        for key, info in MODES.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def invite_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏆 Топ приглашающих", callback_data="show_leaderboard")]
        ]
    )


def progress_bar(used: int, total: int, length: int = 10) -> str:
    total = max(total, 1)
    filled = int(length * min(used, total) / total)
    return "▓" * filled + "░" * (length - filled)


def time_until_midnight() -> str:
    now = datetime.now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    delta = tomorrow - now
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}"


def format_time_left(expires_at_iso: str) -> str:
    delta = datetime.fromisoformat(expires_at_iso) - datetime.now()
    hours, remainder = divmod(max(0, int(delta.total_seconds())), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours} ч {minutes} мин"


def price_with_discount(user_id: int) -> tuple[int, int]:
    """Возвращает (цена_со_скидкой, процент_скидки)."""
    discount = db.get_purchase_discount_percent(user_id)
    price = SUBSCRIPTION_PRICE_STARS
    if discount > 0:
        price = max(1, round(SUBSCRIPTION_PRICE_STARS * (1 - discount / 100)))
    return price, discount


def chunk_text(text: str, chunk_size: int) -> list[str]:
    """Простое разбиение текста на куски фиксированного размера для базы знаний."""
    text = text.strip()
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def build_leaderboard_text() -> str:
    top = db.get_top_referrers(10)
    if not top:
        return "Пока никто никого не пригласил. Стань первым — набери /invite"

    lines = []
    for i, row in enumerate(top, start=1):
        username = db.get_username(row["user_id"])
        name = f"@{username}" if username else f"id{row['user_id']}"
        lines.append(f"{i}. {name} — {row['cnt']} приглашённых")

    return (
        "🏆 Топ-10 по приглашениям:\n\n" + "\n".join(lines) +
        "\n\nЛидеры получают бесплатный месяц подписки — итоги подводит администратор."
    )


async def check_rate_limit(message: Message, user_id: int, admin: bool) -> bool:
    """
    Защита от перегрузки API и злоупотреблений. Возвращает True, если запрос можно обрабатывать.
    Администратор не ограничивается.
    """
    if admin:
        return True

    now = datetime.now()

    blocked_until = spam_blocked_until.get(user_id)
    if blocked_until and now < blocked_until:
        return False  # уже предупреждали — молчим, чтобы не спамить самим предупреждением

    last_at = text_last_request_at.get(user_id)
    if last_at and (now - last_at).total_seconds() < TEXT_COOLDOWN_SECONDS:
        return False  # слишком частые повторные нажатия/дубли — тихо игнорируем

    timestamps = message_timestamps.setdefault(user_id, [])
    timestamps.append(now)
    cutoff = now - timedelta(seconds=SPAM_WINDOW_SECONDS)
    timestamps[:] = [t for t in timestamps if t > cutoff]

    if len(timestamps) > SPAM_MAX_MESSAGES:
        spam_blocked_until[user_id] = now + timedelta(seconds=SPAM_BLOCK_SECONDS)
        await message.answer(
            f"⏳ Слишком много сообщений подряд. Подожди {SPAM_BLOCK_SECONDS} секунд и попробуй снова."
        )
        return False

    text_last_request_at[user_id] = now
    return True


def build_image_url(prompt: str) -> str:
    """
    Формирует URL для Pollinations.ai.
    safe=true — фильтр неподходящего контента.
    seed=случайный — иначе сервис может закэшированно отдать не связанную с промптом картинку.
    enhance=true — просит сервис доработать/уточнить промпт перед генерацией.
    """
    params = {
        "model": "flux",
        "width": 1024,
        "height": 1024,
        "seed": random.randint(1, 999_999_999),
        "nologo": "true",
        "safe": "true",
        "enhance": "true",
        "referrer": "telegram-ai-bot",
    }
    return f"{IMAGE_GEN_BASE_URL}{quote(prompt)}?{urlencode(params)}"


async def translate_prompt_for_image(prompt: str) -> str:
    """
    Модель генерации изображений (Pollinations/flux) заметно надёжнее следует промптам на
    английском. Переводим и слегка уточняем описание через уже настроенный Groq — без истории
    диалога и без лишних слов в ответе.
    """
    try:
        translated = await ask_ai(
            prompt,
            history=None,
            system_prompt=(
                "Переведи описание изображения от пользователя на английский язык для "
                "модели генерации картинок. Ответь ТОЛЬКО переводом, без кавычек, без пояснений, "
                "одной строкой. Если описание уже на английском — просто верни его."
            ),
        )
        translated = translated.strip().strip('"').strip("'")
        return translated or prompt
    except Exception:
        return prompt  # если перевод не удался — используем оригинал, это не критично


@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    referred_by = None
    if command.args and command.args.startswith("ref_"):
        try:
            ref_id = int(command.args.replace("ref_", ""))
            if ref_id != message.from_user.id:
                referred_by = ref_id
        except ValueError:
            referred_by = None

    user, created = db.get_or_create_user(message.from_user.id, message.from_user.username, referred_by)

    if created and referred_by:
        db.add_bonus_requests(referred_by, REFERRAL_BONUS_REQUESTS)
        db.add_bonus_requests(message.from_user.id, REFERRAL_BONUS_REQUESTS)
        try:
            await bot.send_message(
                referred_by,
                "🎉 По твоей ссылке зарегистрировался новый пользователь!\n"
                f"Тебе начислено +{REFERRAL_BONUS_REQUESTS} бонусных запросов.",
            )
        except Exception:
            pass

    db.update_streak(message.from_user.id)

    welcome = "Привет! Я ИИ-ассистент 🤖\n\n"
    if created:
        welcome += (
            f"🎉 Дарю тебе {TRIAL_DAYS} дня полного доступа ко ВСЕМ функциям бота — "
            "безлимитные запросы, режимы ответа, генерация картинок, анализ фото и голоса, "
            "работа с PDF и веб-поиск. Просто пользуйся!\n\n"
            f"После пробного периода — {FREE_REQUESTS_PER_DAY} бесплатных запросов в день "
            "или подписка без ограничений.\n"
        )
    else:
        welcome += f"У тебя есть {FREE_REQUESTS_PER_DAY} бесплатных запросов в день.\n"
    if created and referred_by:
        welcome += f"🎁 Плюс тебе начислено +{REFERRAL_BONUS_REQUESTS} бонусных запросов за переход по ссылке друга!\n"
    welcome += "Просто напиши мне вопрос — и я отвечу.\n\nИспользуй кнопки внизу 👇"

    full_access = user_has_full_access(message.from_user.id, message.from_user.username)
    golden_available = not full_access and db.is_golden_query_available(message.from_user.id)
    await message.answer(welcome, reply_markup=main_menu_keyboard(full_access, golden_available, message.from_user.username))


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def cmd_help(message: Message):
    full_access = user_has_full_access(message.from_user.id, message.from_user.username)
    golden_available = not full_access and db.is_golden_query_available(message.from_user.id)

    text = (
        "Я ИИ-ассистент. Вот что я умею 👇\n\n"
        "🆓 <b>Бесплатно</b>\n"
        f"• {FREE_REQUESTS_PER_DAY} текстовых ответов в день\n"
        "• Короткая память диалога в рамках одной сессии\n"
        "• 🌟 Золотой запрос раз в неделю — попробовать все функции подписки на одно сообщение\n"
        "• 🎁 Реферальная программа — бонусные запросы за друзей\n"
        "• Статус, стрик активности, персональные скидки за активность\n\n"
        "💎 <b>По подписке</b>\n"
        "• Безлимитные текстовые запросы\n"
        "• Длинная память диалога — бот помнит весь разговор\n"
        "• 🎨 Режимы ответа (копирайтер, кодер, простыми словами и другие)\n"
        "• 🖼 Генерация изображений по описанию\n"
        "• 📷 Анализ фото — пришли картинку, бот опишет её или ответит на вопрос\n"
        "• 🎙 Распознавание голосовых сообщений — можно просто наговорить вопрос\n"
        "• 📄 Загрузка PDF — краткий пересказ или ответ по документу\n"
        "• 📚 База знаний (RAG) — бот отвечает строго по документам, без выдумок\n"
        "• 🌐 Веб-поиск в реальном времени — новости, цены, погода\n\n"
    ).replace("<b>", "").replace("</b>", "")  # обычный текст, без разметки

    text += "Кнопки внизу:\n" f"{BTN_STATUS} — лимит и статус подписки\n" f"{BTN_BUY} — купить подписку\n" f"{BTN_INVITE} — пригласить друга\n"
    if full_access:
        text += f"{BTN_MODE} — выбрать режим ответа\n{BTN_IMAGE} — сгенерировать картинку\n{BTN_SEARCH} — веб-поиск\n{BTN_VIDEO_CIRCLE} — превратить видео в кружок\n"
    if golden_available:
        text += f"{BTN_GOLDEN} — раз в {GOLDEN_QUERY_INTERVAL_DAYS} дней попробовать бота как подписчик\n"

    text += f"\n/leaderboard — топ приглашающих друзей\n\nПо любым вопросам — пиши мне: @{CONTACT_USERNAME}"

    await message.answer(text, reply_markup=main_menu_keyboard(full_access, golden_available, message.from_user.username))


@dp.message(Command("status"))
@dp.message(F.text == BTN_STATUS)
async def cmd_status(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    full_access = user_has_full_access(user_id, message.from_user.username)
    streak = db.get_streak(user_id)

    if is_admin(message.from_user.username):
        mode_label = MODES.get(db.get_user_mode(user_id), MODES["default"])["label"]
        await message.answer(
            "👑 Ты администратор — безлимитный доступ навсегда.\n"
            f"Текущий режим ответа: {mode_label} (кнопка {BTN_MODE})",
            reply_markup=main_menu_keyboard(full_access, username=message.from_user.username),
        )
        return

    sub_until = db.get_subscription_status(user_id)
    if sub_until:
        mode_label = MODES.get(db.get_user_mode(user_id), MODES["default"])["label"]
        await message.answer(
            f"✅ У тебя активна подписка до {sub_until[:16].replace('T', ' ')}.\n"
            "Запросы без лимита.\n"
            f"Текущий режим ответа: {mode_label} (кнопка {BTN_MODE})\n"
            f"🔥 Стрик активности: {streak} дней подряд",
            reply_markup=main_menu_keyboard(full_access, username=message.from_user.username),
        )
        return

    trial_until = db.get_trial_status(user_id)
    if trial_until:
        mode_label = MODES.get(db.get_user_mode(user_id), MODES["default"])["label"]
        await message.answer(
            f"🎉 У тебя активен пробный период — полный доступ ещё {format_time_left(trial_until)}.\n"
            "Запросы без лимита, доступны все функции.\n"
            f"Текущий режим ответа: {mode_label} (кнопка {BTN_MODE})\n"
            f"🔥 Стрик активности: {streak} дней подряд\n\n"
            f"После окончания пробного периода — {FREE_REQUESTS_PER_DAY} бесплатных запросов в день, "
            f"либо оформи подписку заранее кнопкой {BTN_BUY}.",
            reply_markup=main_menu_keyboard(full_access, username=message.from_user.username),
        )
        return

    left = db.remaining_free_requests(user_id)
    bonus = db.get_bonus_requests(user_id)
    used = FREE_REQUESTS_PER_DAY - left
    bar = progress_bar(used, FREE_REQUESTS_PER_DAY)

    text = f"{bar} Использовано {used}/{FREE_REQUESTS_PER_DAY} сегодня.\n"
    if left == 0:
        text += f"Следующий бесплатный запрос через {time_until_midnight()}.\n"
    if bonus > 0:
        text += f"🎁 Бонусных запросов на балансе: {bonus}\n"
    if streak > 0:
        text += f"🔥 Стрик активности: {streak} дней подряд\n"

    discount, expires_at = db.get_active_discount(user_id)
    if discount > 0 and expires_at:
        text += f"\n🔥 Персональная скидка {discount}% на подписку — ещё {format_time_left(expires_at)}!\n"

    golden_available = db.is_golden_query_available(user_id)
    if golden_available:
        text += f"\n🌟 Тебе доступен золотой запрос — попробуй кнопкой {BTN_GOLDEN}\n"

    text += f"\nХочешь без лимита? Нажми {BTN_BUY}"
    await message.answer(text, reply_markup=main_menu_keyboard(full_access, golden_available, message.from_user.username))


@dp.message(Command("buy"))
@dp.message(F.text == BTN_BUY)
async def cmd_buy(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    price, discount = price_with_discount(user_id)
    price_line = f"{SUBSCRIPTION_PRICE_STARS} ⭐"
    if discount > 0:
        price_line = f"{price} ⭐ вместо {SUBSCRIPTION_PRICE_STARS} ⭐ (скидка {discount}%)"

    modes_text = "\n\n".join(
        f"{info['label']}\n{info['description']}" for key, info in MODES.items() if key != "default"
    )
    await message.answer(
        f"Подписка на {SUBSCRIPTION_DAYS} дней без ограничения по запросам — {price_line}.\n\n"
        "Что получаешь дополнительно:\n"
        f"• Безлимитные запросы (сейчас {FREE_REQUESTS_PER_DAY} в день)\n"
        "• Длинная память диалога — бот помнит весь разговор\n"
        "• Генерация картинок, анализ фото, распознавание голоса\n"
        "• Загрузка PDF и база знаний (бот отвечает по твоим документам)\n"
        "• Веб-поиск в реальном времени (новости, цены, погода)\n"
        "• Режимы ответа под разные задачи:\n\n"
        f"{modes_text}",
        reply_markup=buy_keyboard(),
    )


@dp.message(Command("invite"))
@dp.message(F.text == BTN_INVITE)
async def cmd_invite(message: Message):
    db.get_or_create_user(message.from_user.id, message.from_user.username)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{message.from_user.id}"
    referrals = db.count_referrals(message.from_user.id)
    bonus = db.get_bonus_requests(message.from_user.id)
    await message.answer(
        "🎁 Приглашай друзей и получай бонусные запросы!\n\n"
        f"За каждого друга, который запустит бота по твоей ссылке, вы оба получите "
        f"+{REFERRAL_BONUS_REQUESTS} запросов.\n\n"
        f"Если приглашённый друг купит подписку — тебе начислится ещё "
        f"+{REFERRAL_SUBSCRIPTION_BONUS_REQUESTS} бонусных запросов.\n\n"
        f"Твоя ссылка:\n{link}\n\n"
        f"Приглашено друзей: {referrals}\n"
        f"Бонусных запросов на балансе: {bonus}",
        reply_markup=invite_keyboard(),
    )


@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    await message.answer(build_leaderboard_text())


@dp.callback_query(F.data == "show_leaderboard")
async def process_leaderboard_callback(callback):
    await callback.answer()
    await callback.message.answer(build_leaderboard_text())


@dp.message(Command("reward_top10"))
async def cmd_reward_top10(message: Message):
    """Админ вручную награждает топ-10 бесплатным месяцем — периодичность конкурса не была
    уточнена в задаче, поэтому награждение запускается вручную командой, а не по расписанию."""
    if not is_admin(message.from_user.username):
        return

    top = db.get_top_referrers(10)
    rewarded = 0
    for row in top:
        new_until = db.activate_subscription(row["user_id"], charge_id="leaderboard_reward", amount_stars=0)
        rewarded += 1
        try:
            await bot.send_message(
                row["user_id"],
                "🏆 Ты в топ-10 по приглашениям! В подарок — бесплатный месяц подписки.\n"
                f"Действует до {new_until.isoformat()[:16].replace('T', ' ')}.",
            )
        except Exception:
            pass

    await message.answer(f"Награждено пользователей: {rewarded}")


@dp.message(Command("mode"))
@dp.message(F.text == BTN_MODE)
async def cmd_mode(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Режимы ответа доступны только по подписке.\n"
            "Оформи подписку, чтобы выбрать стиль общения с ботом:",
            reply_markup=buy_keyboard(),
        )
        return

    current_label = MODES.get(db.get_user_mode(user_id), MODES["default"])["label"]
    modes_text = "\n\n".join(f"{info['label']}\n{info['description']}" for info in MODES.values())

    await message.answer(
        f"Текущий режим: {current_label}\n\n"
        f"Доступные режимы:\n\n{modes_text}\n\n"
        "Выбери новый режим кнопкой ниже:",
        reply_markup=mode_keyboard(),
    )


@dp.callback_query(F.data.startswith("mode_"))
async def process_mode_callback(callback):
    user_id = callback.from_user.id
    if not user_has_full_access(user_id, callback.from_user.username):
        await callback.answer("Доступно только по подписке", show_alert=True)
        return

    mode_key = callback.data.replace("mode_", "")
    if mode_key not in MODES:
        await callback.answer("Неизвестный режим", show_alert=True)
        return

    db.set_user_mode(user_id, mode_key)
    await callback.answer(f"Режим изменён: {MODES[mode_key]['label']}")
    await callback.message.edit_text(f"✅ Установлен режим: {MODES[mode_key]['label']}")


@dp.message(F.text == BTN_GOLDEN)
async def handle_golden_button(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if user_has_full_access(user_id, message.from_user.username):
        return

    if not db.is_golden_query_available(user_id):
        await message.answer("🌟 Золотой запрос уже использован. Загляни через несколько дней!")
        return

    golden_pending.add(user_id)
    await message.answer(
        "🌟 Отлично! Следующее сообщение будет обработано как у подписчика:\n"
        "полная память диалога и режим ответа без ограничений.\n\n"
        "Просто напиши свой вопрос."
    )


@dp.callback_query(F.data == "buy_subscription")
async def process_buy_callback(callback):
    user_id = callback.from_user.id
    price, discount = price_with_discount(user_id)

    await callback.message.answer_invoice(
        title="Подписка на бота",
        description=(
            f"Безлимитные запросы на {SUBSCRIPTION_DAYS} дней"
            + (f" (скидка {discount}%)" if discount else "")
        ),
        payload=f"subscription_{user_id}",
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=price)],
        provider_token="",
    )
    await callback.answer()


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payment = message.successful_payment
    user_id = message.from_user.id

    new_until = db.activate_subscription(
        user_id=user_id,
        charge_id=payment.telegram_payment_charge_id,
        amount_stars=payment.total_amount,
    )
    db.clear_discount(user_id)

    referrer_id = db.grant_referral_subscription_bonus_if_needed(user_id)
    if referrer_id:
        try:
            await bot.send_message(
                referrer_id,
                "🎉 Друг, которого ты пригласил, купил подписку!\n"
                f"Тебе начислено +{REFERRAL_SUBSCRIPTION_BONUS_REQUESTS} бонусных запросов.",
            )
        except Exception:
            pass

    await message.answer(
        f"🎉 Подписка активирована! Действует до {new_until.isoformat()[:16].replace('T', ' ')}.\n"
        "Теперь запросы без лимита, и в меню появились новые кнопки — Режим, Картинка, Веб-поиск.",
        reply_markup=main_menu_keyboard(True, username=message.from_user.username),
    )


# --- Генерация изображений ---

@dp.message(Command("image"))
async def cmd_image(message: Message, command: CommandObject):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Генерация изображений доступна только по подписке.\n"
            "Оформи подписку и описывай, что нарисовать: /image закат над горами",
            reply_markup=buy_keyboard(),
        )
        return

    prompt = command.args
    if not prompt:
        awaiting_image_prompt.add(user_id)
        await message.answer("Напиши, что нарисовать, например: закат над горами")
        return

    await generate_and_send_image(message, prompt)


@dp.message(F.text == BTN_IMAGE)
async def handle_image_button(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Генерация изображений доступна только по подписке.\n"
            "Оформи подписку, чтобы рисовать картинки по описанию:",
            reply_markup=buy_keyboard(),
        )
        return

    awaiting_image_prompt.add(user_id)
    await message.answer("🖼 Опиши, что нарисовать, например: кот-космонавт в скафандре")


async def generate_and_send_image(message: Message, prompt: str):
    user_id = message.from_user.id

    last_at = image_last_request_at.get(user_id)
    if last_at:
        wait_left = IMAGE_COOLDOWN_SECONDS - (datetime.now() - last_at).total_seconds()
        if wait_left > 0:
            await message.answer(f"⏳ Подожди ещё {int(wait_left) + 1} сек. перед следующей генерацией.")
            return
    image_last_request_at[user_id] = datetime.now()

    await bot.send_chat_action(message.chat.id, "upload_photo")

    english_prompt = await translate_prompt_for_image(prompt)
    url = build_image_url(english_prompt)

    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"сервис генерации ответил кодом {resp.status}")
                image_bytes = await resp.read()
    except asyncio.TimeoutError:
        logging.error("Pollinations timeout")
        await message.answer(random.choice(FALLBACK_APOLOGIES))
        return
    except Exception as e:
        logging.error(f"Image generation error: {e}")
        await message.answer(random.choice(FALLBACK_APOLOGIES))
        return

    photo_file = BufferedInputFile(image_bytes, filename="image.png")
    try:
        await message.answer_photo(photo=photo_file, caption=f"🎨 {prompt}")
    except Exception as e:
        logging.error(f"Failed to send generated image: {e}")
        await message.answer(random.choice(FALLBACK_APOLOGIES))


# --- Веб-поиск в реальном времени ---

@dp.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Веб-поиск в реальном времени доступен только по подписке.\n"
            "Оформи подписку и спрашивай: /search курс доллара сегодня",
            reply_markup=buy_keyboard(),
        )
        return

    query = command.args
    if not query:
        awaiting_search_query.add(user_id)
        await message.answer("Что найти? Например: погода в Москве сегодня")
        return

    await run_web_search(message, query)


@dp.message(F.text == BTN_SEARCH)
async def handle_search_button(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Веб-поиск в реальном времени доступен только по подписке.\n"
            "Оформи подписку, чтобы получать актуальные новости, цены и погоду:",
            reply_markup=buy_keyboard(),
        )
        return

    awaiting_search_query.add(user_id)
    await message.answer("🌐 Что найти? Например: курс доллара сегодня")


async def run_web_search(message: Message, query: str):
    user_id = message.from_user.id

    last_at = search_last_request_at.get(user_id)
    if last_at:
        wait_left = SEARCH_COOLDOWN_SECONDS - (datetime.now() - last_at).total_seconds()
        if wait_left > 0:
            await message.answer(f"⏳ Подожди ещё {int(wait_left) + 1} сек. перед следующим поиском.")
            return
    search_last_request_at[user_id] = datetime.now()

    await bot.send_chat_action(message.chat.id, "typing")
    answer = await ask_with_web_search(query)
    await message.answer(f"🌐 {answer}")


# --- База знаний (RAG), администрирование ---

@dp.message(Command("kb_add"))
async def cmd_kb_add(message: Message):
    if not is_admin(message.from_user.username):
        return
    awaiting_kb_document.add(message.from_user.id)
    await message.answer("📚 Пришли PDF-файл, который нужно добавить в базу знаний.")


@dp.message(Command("kb_list"))
async def cmd_kb_list(message: Message):
    if not is_admin(message.from_user.username):
        return
    sources = db.list_kb_sources()
    if not sources:
        await message.answer("База знаний пока пуста. Добавь документ через /kb_add")
        return
    total = db.kb_chunk_count()
    lines = [f"• {row['source_name']} — {row['chunks']} фрагментов" for row in sources]
    await message.answer(f"📚 В базе знаний {total} фрагментов из {len(sources)} документов:\n\n" + "\n".join(lines))


@dp.message(Command("kb_clear"))
async def cmd_kb_clear(message: Message):
    if not is_admin(message.from_user.username):
        return
    db.clear_kb()
    await message.answer("🗑 База знаний очищена.")


# --- Админ-панель: список клиентов, внутренний чат админов, управление админами ---

ADMIN_CLIENTS_PAGE_SIZE = 10

CLIENT_FILTERS = {
    "all": "Все",
    "sub": "💎 Подписка",
    "trial": "🎉 Триал",
    "free": "🆓 Free",
    "admin": "👑 Админы",
}


def admin_panel_keyboard(username: str | None) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="👥 Список клиентов", callback_data="admin_clients:all:0")],
        [InlineKeyboardButton(text="💬 Общий чат админов", callback_data="admin_chat_broadcast")],
        [InlineKeyboardButton(text="✉️ Написать админу лично", callback_data="admin_chat_dm_pick")],
    ]
    if is_owner(username):
        buttons.append([InlineKeyboardButton(text="⚙️ Управление админами", callback_data="admin_manage")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def categorize_client(row: "sqlite3.Row") -> str:
    if is_admin(row["username"]):
        return "admin"
    if db.has_active_subscription(row):
        return "sub"
    if db.has_active_trial(row):
        return "trial"
    return "free"


def format_client_line(row: "sqlite3.Row") -> str:
    username = row["username"]
    label = f"@{username}" if username else f"id{row['user_id']}"
    cat = categorize_client(row)
    if cat == "admin":
        status = "👑 Админ"
    elif cat == "sub":
        status = f"💎 Подписка до {row['subscription_until'][:10]}"
    elif cat == "trial":
        status = f"🎉 Триал до {row['trial_until'][:10]}"
    else:
        status = f"🆓 Free ({row['requests_today']}/{FREE_REQUESTS_PER_DAY} сегодня)"
    return f"{label} — {status}"


def clients_filter_keyboard(current_filter: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    def label(key: str, text: str) -> str:
        return f"• {text} •" if key == current_filter else text

    rows = [
        [
            InlineKeyboardButton(text=label("all", "Все"), callback_data="admin_clients:all:0"),
            InlineKeyboardButton(text=label("sub", "💎 Подписка"), callback_data="admin_clients:sub:0"),
        ],
        [
            InlineKeyboardButton(text=label("trial", "🎉 Триал"), callback_data="admin_clients:trial:0"),
            InlineKeyboardButton(text=label("free", "🆓 Free"), callback_data="admin_clients:free:0"),
        ],
        [InlineKeyboardButton(text=label("admin", "👑 Админы"), callback_data="admin_clients:admin:0")],
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_clients:{current_filter}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_clients:{current_filter}:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="⬅️ В панель", callback_data="admin_panel_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_all_admin_user_ids(exclude_user_id: int | None = None) -> list[tuple[int, str]]:
    """Возвращает (user_id, username) для всех текущих админов, которые уже запускали бота."""
    admin_usernames = set(ADMIN_USERNAMES) | set(db.list_db_admins())
    result = []
    for uname in admin_usernames:
        uid = db.get_user_id_by_username(uname)
        if uid and uid != exclude_user_id:
            result.append((uid, uname))
    return result


@dp.message(F.text == BTN_ADMIN)
async def show_admin_panel(message: Message):
    if not is_admin(message.from_user.username):
        return
    await message.answer("🛠 Админ-панель", reply_markup=admin_panel_keyboard(message.from_user.username))


@dp.callback_query(F.data == "admin_panel_back")
async def admin_panel_back(callback):
    if not is_admin(callback.from_user.username):
        await callback.answer("Недоступно", show_alert=True)
        return
    try:
        await callback.message.edit_text("🛠 Админ-панель", reply_markup=admin_panel_keyboard(callback.from_user.username))
    except Exception:
        await callback.message.answer("🛠 Админ-панель", reply_markup=admin_panel_keyboard(callback.from_user.username))
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop_callback(callback):
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_clients:"))
async def admin_clients_page(callback):
    if not is_admin(callback.from_user.username):
        await callback.answer("Недоступно", show_alert=True)
        return

    _, filter_key, page_str = callback.data.split(":")
    page = int(page_str)
    if filter_key not in CLIENT_FILTERS:
        filter_key = "all"

    all_rows = db.get_all_users(limit=5000, offset=0)
    counts = {"all": len(all_rows), "sub": 0, "trial": 0, "free": 0, "admin": 0}
    categorized = []
    for r in all_rows:
        cat = categorize_client(r)
        counts[cat] += 1
        categorized.append((cat, r))

    filtered = [r for cat, r in categorized if filter_key == "all" or cat == filter_key]

    total = len(filtered)
    total_pages = max(1, (total + ADMIN_CLIENTS_PAGE_SIZE - 1) // ADMIN_CLIENTS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_rows = filtered[page * ADMIN_CLIENTS_PAGE_SIZE: (page + 1) * ADMIN_CLIENTS_PAGE_SIZE]

    lines = [format_client_line(r) for r in page_rows] if page_rows else ["Никого нет в этой категории."]
    header = (
        f"👥 Клиенты — {CLIENT_FILTERS[filter_key]} ({total})\n"
        f"Всего: {counts['all']} · 💎 {counts['sub']} · 🎉 {counts['trial']} · "
        f"🆓 {counts['free']} · 👑 {counts['admin']}\n\n"
    )
    text = header + "\n".join(lines) + f"\n\nСтр. {page + 1}/{total_pages}"

    kb = clients_filter_keyboard(filter_key, page, total_pages)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "admin_chat_broadcast")
async def admin_chat_broadcast_start(callback):
    if not is_admin(callback.from_user.username):
        await callback.answer("Недоступно", show_alert=True)
        return
    awaiting_admin_broadcast.add(callback.from_user.id)
    await callback.message.answer("💬 Напиши сообщение — оно уйдёт всем остальным администраторам.")
    await callback.answer()


@dp.callback_query(F.data == "admin_chat_dm_pick")
async def admin_chat_dm_pick(callback):
    if not is_admin(callback.from_user.username):
        await callback.answer("Недоступно", show_alert=True)
        return
    admins = await get_all_admin_user_ids(exclude_user_id=callback.from_user.id)
    if not admins:
        await callback.message.answer("Других администраторов пока нет в базе (они ещё не запускали бота).")
        await callback.answer()
        return
    buttons = [
        [InlineKeyboardButton(text=f"@{uname}", callback_data=f"admin_chat_dm_to:{uid}")]
        for uid, uname in admins
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ В панель", callback_data="admin_panel_back")])
    await callback.message.answer("Кому написать?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_chat_dm_to:"))
async def admin_chat_dm_to(callback):
    if not is_admin(callback.from_user.username):
        await callback.answer("Недоступно", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    awaiting_admin_dm[callback.from_user.id] = target_id
    await callback.message.answer("✉️ Напиши сообщение — оно уйдёт этому администратору лично.")
    await callback.answer()


async def _render_admin_manage(callback):
    db_admins = db.list_db_admins()
    lines = ["👑 Базовые (из конфига): " + ", ".join(f"@{u}" for u in ADMIN_USERNAMES)]
    buttons = []
    if db_admins:
        lines.append("\n➕ Добавленные вручную:")
        for u in db_admins:
            lines.append(f"• @{u}")
            buttons.append([InlineKeyboardButton(text=f"❌ Убрать @{u}", callback_data=f"admin_manage_remove:{u}")])
    else:
        lines.append("\nДополнительных админов пока нет.")
    buttons.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_manage_add")])
    buttons.append([InlineKeyboardButton(text="⬅️ В панель", callback_data="admin_panel_back")])
    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception:
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data == "admin_manage")
async def admin_manage(callback):
    if not is_owner(callback.from_user.username):
        await callback.answer("Только владелец может управлять админами", show_alert=True)
        return
    await _render_admin_manage(callback)
    await callback.answer()


@dp.callback_query(F.data == "admin_manage_add")
async def admin_manage_add(callback):
    if not is_owner(callback.from_user.username):
        await callback.answer("Только владелец может управлять админами", show_alert=True)
        return
    awaiting_admin_add.add(callback.from_user.id)
    await callback.message.answer("Пришли юзернейм нового админа (без @).")
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_manage_remove:"))
async def admin_manage_remove(callback):
    if not is_owner(callback.from_user.username):
        await callback.answer("Только владелец может управлять админами", show_alert=True)
        return
    username = callback.data.split(":", 1)[1]
    db.remove_admin(username)
    await _render_admin_manage(callback)
    await callback.answer(f"@{username} удалён")


async def broadcast_to_admins(message: Message):
    sender = f"@{message.from_user.username}" if message.from_user.username else f"id{message.from_user.id}"
    admins = await get_all_admin_user_ids(exclude_user_id=message.from_user.id)
    if not admins:
        await message.answer("В общем чате пока нет других администраторов (они ещё не запускали бота).")
        return
    sent = 0
    for uid, _ in admins:
        try:
            await bot.send_message(uid, f"💬 [Общий чат] {sender}:\n{message.text}")
            sent += 1
        except Exception:
            pass
    await message.answer(f"✅ Сообщение отправлено {sent} администратор(ам) в общем чате.")


async def send_admin_dm(message: Message, target_id: int):
    sender = f"@{message.from_user.username}" if message.from_user.username else f"id{message.from_user.id}"
    try:
        await bot.send_message(target_id, f"✉️ [Личное] {sender}:\n{message.text}")
        await message.answer("✅ Сообщение отправлено.")
    except Exception:
        await message.answer("⚠️ Не удалось доставить — возможно, этот админ ещё не запускал бота.")


# --- Документы (PDF): вопрос по файлу или пополнение базы знаний админом ---

@dp.message(F.document)
async def handle_document(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await message.answer("Пока поддерживаются только PDF-файлы.")
        return

    if user_id in awaiting_kb_document and is_admin(message.from_user.username):
        awaiting_kb_document.discard(user_id)
        await bot.send_chat_action(message.chat.id, "typing")
        try:
            file = await bot.get_file(doc.file_id)
            file_bytes = await bot.download_file(file.file_path)
            reader = PdfReader(file_bytes)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:
            logging.error(f"KB PDF read error: {e}")
            await message.answer(random.choice(FALLBACK_APOLOGIES))
            return

        chunks = chunk_text(text, RAG_CHUNK_SIZE)
        if not chunks:
            await message.answer("В файле не нашлось текста для базы знаний (возможно, это скан).")
            return

        added = db.add_kb_chunks(doc.file_name, chunks)
        total = db.kb_chunk_count()
        await message.answer(
            f"✅ Добавлено {added} фрагментов из «{doc.file_name}» в базу знаний.\n"
            f"Всего в базе: {total} фрагментов."
        )
        return

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Загрузка документов доступна только по подписке.\n"
            "Оформи подписку, чтобы бот мог отвечать по содержимому файлов:",
            reply_markup=buy_keyboard(),
        )
        return

    await bot.send_chat_action(message.chat.id, "typing")

    try:
        file = await bot.get_file(doc.file_id)
        file_bytes = await bot.download_file(file.file_path)
        reader = PdfReader(file_bytes)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        logging.error(f"PDF read error: {e}")
        await message.answer(random.choice(FALLBACK_APOLOGIES))
        return

    text = text[:8000]
    if not text.strip():
        await message.answer("В файле не нашлось текста для анализа (возможно, это скан).")
        return

    question = message.caption or "Кратко перескажи содержимое этого документа."
    prompt = f"Вот текст документа:\n\n{text}\n\nЗадача: {question}"

    answer = await ask_ai(prompt, system_prompt=MODES["default"]["prompt"])
    await message.answer(answer)


# --- Анализ фото ---

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Анализ изображений доступен только по подписке.\n"
            "Оформи подписку, чтобы бот мог отвечать по содержимому фото:",
            reply_markup=buy_keyboard(),
        )
        return

    admin = is_admin(message.from_user.username)
    if not await check_rate_limit(message, user_id, admin):
        return

    await bot.send_chat_action(message.chat.id, "typing")

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_b64 = base64.b64encode(file_bytes.read()).decode()
    except Exception as e:
        logging.error(f"Photo download error: {e}")
        await message.answer(random.choice(FALLBACK_APOLOGIES))
        return

    question = message.caption or VISION_DEFAULT_QUESTION
    data_url = f"data:image/jpeg;base64,{image_b64}"
    answer = await analyze_image(data_url, question)
    await message.answer(answer)


# --- Голосовые сообщения ---

@dp.message(F.voice | F.audio)
async def handle_voice(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Распознавание голосовых сообщений доступно только по подписке.\n"
            "Оформи подписку и просто наговаривай вопросы:",
            reply_markup=buy_keyboard(),
        )
        return

    admin = is_admin(message.from_user.username)
    if not await check_rate_limit(message, user_id, admin):
        return

    voice = message.voice or message.audio
    if voice.duration and voice.duration > VOICE_MAX_DURATION_SECONDS:
        await message.answer(f"Голосовое слишком длинное (максимум {VOICE_MAX_DURATION_SECONDS} сек).")
        return

    await bot.send_chat_action(message.chat.id, "typing")

    try:
        file = await bot.get_file(voice.file_id)
        file_bytes = await bot.download_file(file.file_path)
        audio_bytes = file_bytes.read()
    except Exception as e:
        logging.error(f"Voice download error: {e}")
        await message.answer(random.choice(FALLBACK_APOLOGIES))
        return

    text = await transcribe_voice(audio_bytes, filename="voice.ogg")
    if not text or not text.strip():
        await message.answer("🙉 Не удалось распознать речь — возможно, звук слишком тихий или короткий.")
        return

    await message.answer(f"🎙 Распознано: «{text.strip()}»")
    await process_user_query(message, text.strip())


# --- Видео в кружок (Telegram video note) ---

@dp.message(F.text == BTN_VIDEO_CIRCLE)
async def prompt_video_circle(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Превращение видео в кружок доступно только по подписке.\n"
            "Оформи подписку, чтобы делать видео-кружки из любых роликов:",
            reply_markup=buy_keyboard(),
        )
        return

    await message.answer(
        f"⭕ Пришли видео (до {VIDEO_NOTE_MAX_DURATION_SECONDS} секунд, до {VIDEO_NOTE_MAX_FILE_SIZE_MB} МБ) — "
        "и я сразу сделаю из него кружок."
    )


@dp.message(F.video)
async def handle_video_to_circle(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if not user_has_full_access(user_id, message.from_user.username):
        await message.answer(
            "🔒 Превращение видео в кружок доступно только по подписке.\n"
            "Оформи подписку, чтобы делать видео-кружки из любых роликов:",
            reply_markup=buy_keyboard(),
        )
        return

    admin = is_admin(message.from_user.username)
    if not await check_rate_limit(message, user_id, admin):
        return

    video = message.video
    if video.duration and video.duration > VIDEO_NOTE_MAX_DURATION_SECONDS:
        await message.answer(
            f"⏱ Видео слишком длинное — максимум {VIDEO_NOTE_MAX_DURATION_SECONDS} секунд для кружка."
        )
        return
    if video.file_size and video.file_size > VIDEO_NOTE_MAX_FILE_SIZE_MB * 1024 * 1024:
        await message.answer(f"📦 Видео слишком большое — максимум {VIDEO_NOTE_MAX_FILE_SIZE_MB} МБ.")
        return

    status_msg = await message.answer("🔄 Делаю кружок, подожди немного...")
    await bot.send_chat_action(message.chat.id, "upload_video_note")

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = os.path.join(tmp_dir, "input.mp4")
            output_path = os.path.join(tmp_dir, "circle.mp4")

            file = await bot.get_file(video.file_id)
            await bot.download_file(file.file_path, destination=input_path)

            size = VIDEO_NOTE_SIZE_PX
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-t", str(VIDEO_NOTE_MAX_DURATION_SECONDS),
                "-vf", f"crop='min(iw,ih)':'min(iw,ih)',scale={size}:{size}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode != 0 or not os.path.exists(output_path):
                raise RuntimeError(stderr.decode(errors="ignore")[-500:])

            await bot.send_video_note(message.chat.id, FSInputFile(output_path))
    except Exception as e:
        logging.error(f"Video-to-circle error: {e}")
        await status_msg.edit_text(random.choice(FALLBACK_APOLOGIES))
        return

    await status_msg.delete()


# --- Основная обработка текстовых запросов к ИИ (используется текстом и голосом) ---

async def process_user_query(message: Message, query_text: str):
    user_id = message.from_user.id

    admin = is_admin(message.from_user.username)
    subscriber = db.is_subscriber(user_id)
    full_access = admin or subscriber or db.is_trial_active(user_id)
    using_golden = user_id in golden_pending

    if not await check_rate_limit(message, user_id, admin):
        return

    streak, streak_bonus_awarded = db.update_streak(user_id)
    if streak_bonus_awarded:
        await message.answer(
            f"🔥 {streak} дней подряд с ботом! Начислено +{STREAK_BONUS_REQUESTS} бонусных запроса."
        )

    if not admin and not full_access:
        newly_granted = db.maybe_grant_dynamic_discount(user_id)
        if newly_granted:
            discount, expires_at = db.get_active_discount(user_id)
            price, _ = price_with_discount(user_id)
            await message.answer(
                f"🔥 Ты активно пользуешься ботом {DYNAMIC_DISCOUNT_ACTIVE_DAYS} дня подряд — держи "
                f"персональную скидку {discount}% на подписку!\n"
                f"Всего {price} ⭐ вместо {SUBSCRIPTION_PRICE_STARS} ⭐ — но только ближайшие "
                f"{format_time_left(expires_at)}.",
                reply_markup=buy_keyboard(),
            )

    if not admin and not full_access and not using_golden:
        allowed, reason = db.can_make_request(user_id)
        if not allowed:
            if reason == "limit":
                await message.answer(
                    "🚫 Бесплатные запросы на сегодня закончились.\n"
                    f"Следующий бесплатный запрос через {time_until_midnight()}.\n"
                    "Оформи подписку — и лимита не будет, либо пригласи друга через /invite:",
                    reply_markup=buy_keyboard(),
                )
            return

    await bot.send_chat_action(message.chat.id, "typing")

    is_sub_like = full_access or using_golden
    max_history = LONG_HISTORY_MESSAGES if is_sub_like else SHORT_HISTORY_MESSAGES

    if not is_sub_like:
        last_at = user_history_last_at.get(user_id)
        now = datetime.now()
        if last_at and (now - last_at).total_seconds() > FREE_CONTEXT_TTL_MINUTES * 60:
            user_history[user_id] = []
        user_history_last_at[user_id] = now

    mode_key = db.get_user_mode(user_id) if is_sub_like else "default"
    history = user_history.get(user_id, [])

    if mode_key == "kb":
        chunks = db.search_kb(query_text)
        if not chunks:
            answer = (
                "🤷 В базе знаний нет информации по этому вопросу — не хочу выдумывать ответ. "
                "Попробуй переформулировать вопрос или уточни у администратора, что есть в базе."
            )
        else:
            context = "\n\n---\n\n".join(chunks)
            system_prompt = RAG_SYSTEM_PROMPT_TEMPLATE.format(context=context)
            answer = await ask_ai(query_text, history, system_prompt=system_prompt)
    else:
        system_prompt = MODES.get(mode_key, MODES["default"])["prompt"]
        answer = await ask_ai(query_text, history, system_prompt=system_prompt)

    history.append({"role": "user", "content": query_text})
    history.append({"role": "assistant", "content": answer})
    user_history[user_id] = history[-max_history:]

    if using_golden:
        golden_pending.discard(user_id)
        db.use_golden_query(user_id)
        await message.answer(answer)
        await message.answer(
            "🌟 Это был твой золотой запрос — с полной подпиской так будет каждый раз!",
            reply_markup=buy_keyboard(),
        )
        return

    if not admin and not full_access:
        db.register_request(user_id)

        left = db.remaining_free_requests(user_id)
        bonus = db.get_bonus_requests(user_id)
        used = FREE_REQUESTS_PER_DAY - left
        bar = progress_bar(used, FREE_REQUESTS_PER_DAY)

        footer = f"\n\n{random.choice(FOMO_TEASERS)}\n\n{bar} Использовано {used}/{FREE_REQUESTS_PER_DAY} сегодня."
        if left == 0:
            footer += f" Следующий через {time_until_midnight()}."
        if bonus > 0:
            footer += f" 🎁 Бонусных: {bonus}."

        await message.answer(answer + footer, reply_markup=buy_keyboard())
    else:
        await message.answer(answer)


@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    db.get_or_create_user(user_id, message.from_user.username)

    if user_id in awaiting_admin_broadcast:
        awaiting_admin_broadcast.discard(user_id)
        if is_admin(message.from_user.username):
            await broadcast_to_admins(message)
        return

    if user_id in awaiting_admin_dm:
        target_id = awaiting_admin_dm.pop(user_id)
        if is_admin(message.from_user.username):
            await send_admin_dm(message, target_id)
        return

    if user_id in awaiting_admin_add:
        awaiting_admin_add.discard(user_id)
        if is_owner(message.from_user.username):
            new_username = message.text.strip().lstrip("@")
            if not new_username or " " in new_username:
                await message.answer("Некорректный юзернейм. Пришли ещё раз, без @ и пробелов.")
            elif new_username in ADMIN_USERNAMES or db.is_db_admin(new_username):
                await message.answer(f"@{new_username} уже администратор.")
            else:
                db.add_admin(new_username, added_by=message.from_user.username)
                await message.answer(f"✅ @{new_username} добавлен в администраторы.")
        return

    if user_id in awaiting_image_prompt:
        awaiting_image_prompt.discard(user_id)
        await generate_and_send_image(message, message.text)
        return

    if user_id in awaiting_search_query:
        awaiting_search_query.discard(user_id)
        await run_web_search(message, message.text)
        return

    await process_user_query(message, message.text)


async def reminder_loop():
    while True:
        try:
            users = db.get_users_to_remind(REMINDER_DAYS_BEFORE)
            for row in users:
                try:
                    until_str = row["subscription_until"][:16].replace("T", " ")
                    await bot.send_message(
                        row["user_id"],
                        f"⏰ Твоя подписка заканчивается совсем скоро ({until_str}).\n"
                        "Продли её, чтобы не потерять безлимитный доступ:",
                        reply_markup=buy_keyboard(),
                    )
                except Exception as e:
                    logging.warning(f"Не удалось отправить напоминание {row['user_id']}: {e}")
                finally:
                    db.mark_reminder_sent(row["user_id"])
        except Exception as e:
            logging.error(f"Ошибка в reminder_loop: {e}")

        await asyncio.sleep(REMINDER_CHECK_INTERVAL_HOURS * 3600)


async def main():
    global BOT_USERNAME
    db.init_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())