import os
from dotenv import load_dotenv

load_dotenv()

# --- Обязательные переменные окружения ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- Модель Groq (OpenAI-совместимый API) ---
# llama-3.3-70b-versatile устарела и отключена Groq в июне 2026 — используем актуальную замену.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# --- DeepSeek (альтернативный ИИ-провайдер, OpenAI-совместимый API) ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
# Старые имена deepseek-chat/deepseek-reasoner сняты с поддержки 24.07.2026 — используем актуальные.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

# --- Переключатель ИИ-модели (доступен только по подписке) ---
AI_PROVIDER_DEFAULT = "groq"
AI_PROVIDERS = {
    "groq": {
        "label": "⚡ Groq",
        "description": "Модель по умолчанию — быстрые ответы.",
    },
    "deepseek": {
        "label": "🐳 DeepSeek",
        "description": "Альтернативная модель — другой стиль и качество ответов.",
    },
}

# --- Модели для мультимодальных функций ---
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")            # анализ изображений
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")    # распознавание голоса
GROQ_SEARCH_MODEL = os.getenv("GROQ_SEARCH_MODEL", "groq/compound-mini")          # веб-поиск (встроен в Groq)

# --- Лимиты и подписка ---
FREE_REQUESTS_PER_DAY = int(os.getenv("FREE_REQUESTS_PER_DAY", "30"))
SUBSCRIPTION_PRICE_STARS = int(os.getenv("SUBSCRIPTION_PRICE_STARS", "150"))
SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS", "30"))

# --- Пробный период для новых пользователей ---
# Новый пользователь получает полный доступ ко всем платным функциям (как у подписчика)
# на TRIAL_DAYS дней с момента первого запуска бота. Дальше — бесплатный тариф или покупка.
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))

# Максимум, на сколько дней вперёд (от текущего момента) админ может продлить/выдать
# пробный период вручную через админ-панель — защита от случайной выдачи "вечного" триала.
TRIAL_GRANT_MAX_DAYS = int(os.getenv("TRIAL_GRANT_MAX_DAYS", "30"))

# --- Администраторы бота ---
# Юзернеймы (без @), для которых лимиты и подписка не действуют — доступ всегда безлимитный.
# Можно добавить несколько через запятую в .env: ADMIN_USERNAMES=Abc123qwerty09,another_admin
ADMIN_USERNAMES = {
    u.strip().lstrip("@")
    for u in os.getenv("ADMIN_USERNAMES", "Abc123qwerty09,pipi725").split(",")
    if u.strip()
}

# --- Владелец бота ---
# Единственный аккаунт, который может добавлять/убирать администраторов через админ-панель.
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "pipi725").strip().lstrip("@")

# --- База данных ---
DB_PATH = os.getenv("DB_PATH", "bot.db")

# --- Системный промпт ассистента (режим по умолчанию) ---
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты полезный ИИ-ассистент в Telegram-боте. Отвечай кратко, по делу, дружелюбно. "
    "Форматируй ответы просто, без сложной разметки."
)

# --- Память диалога ---
SHORT_HISTORY_MESSAGES = int(os.getenv("SHORT_HISTORY_MESSAGES", "6"))   # бесплатные пользователи
LONG_HISTORY_MESSAGES = int(os.getenv("LONG_HISTORY_MESSAGES", "30"))    # подписчики

# --- Реферальная программа ---
REFERRAL_BONUS_REQUESTS = int(os.getenv("REFERRAL_BONUS_REQUESTS", "5"))

# --- Напоминание об окончании подписки ---
REMINDER_DAYS_BEFORE = int(os.getenv("REMINDER_DAYS_BEFORE", "1"))
REMINDER_CHECK_INTERVAL_HOURS = int(os.getenv("REMINDER_CHECK_INTERVAL_HOURS", "6"))

# --- Стрик и геймификация ---
STREAK_BONUS_EVERY_DAYS = int(os.getenv("STREAK_BONUS_EVERY_DAYS", "7"))     # раз в сколько дней стрика — бонус
STREAK_BONUS_REQUESTS = int(os.getenv("STREAK_BONUS_REQUESTS", "2"))        # сколько запросов начисляется
STREAK_DISCOUNT_PERCENT = int(os.getenv("STREAK_DISCOUNT_PERCENT", "10"))   # доп. скидка при покупке, если стрик набран

# --- Золотой запрос (пробный вкус подписки раз в N дней) ---
GOLDEN_QUERY_INTERVAL_DAYS = int(os.getenv("GOLDEN_QUERY_INTERVAL_DAYS", "7"))

# --- Динамическая скидка за активность без покупки ---
DYNAMIC_DISCOUNT_ACTIVE_DAYS = int(os.getenv("DYNAMIC_DISCOUNT_ACTIVE_DAYS", "3"))    # дней подряд активности
DYNAMIC_DISCOUNT_PERCENT = int(os.getenv("DYNAMIC_DISCOUNT_PERCENT", "50"))
DYNAMIC_DISCOUNT_WINDOW_HOURS = int(os.getenv("DYNAMIC_DISCOUNT_WINDOW_HOURS", "6"))  # сколько скидка активна

# --- Ограничение памяти диалога у бесплатных пользователей по времени ---
FREE_CONTEXT_TTL_MINUTES = int(os.getenv("FREE_CONTEXT_TTL_MINUTES", "15"))

# --- Реферальный бонус, если приглашённый друг купит подписку ---
REFERRAL_SUBSCRIPTION_BONUS_REQUESTS = int(os.getenv("REFERRAL_SUBSCRIPTION_BONUS_REQUESTS", "50"))

# --- Генерация изображений (бесплатный публичный сервис Pollinations, без API-ключа) ---
IMAGE_GEN_BASE_URL = "https://image.pollinations.ai/prompt/"

# --- Поиск музыки (доступно только по подписке) ---
# Поиск по названию — Deezer API, бесплатно и без ключа, настройки не требует.
# Поиск по словам из песни — Genius API: нужен бесплатный токен с https://genius.com/api-clients
# (Genius → New API Client → Client Access Token). Пока токен не задан, эта под-функция
# отвечает пользователю, что временно недоступна — распознавание по аудио и поиск по
# названию при этом работают в любом случае.
GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN", "")
# Сколько секунд аудио/видео вырезаем перед отправкой в Shazam (10-20 сек достаточно)
SHAZAM_CLIP_SECONDS = int(os.getenv("SHAZAM_CLIP_SECONDS", "20"))
# Сколько вариантов показывать в результатах поиска музыки
MUSIC_RESULTS_LIMIT = int(os.getenv("MUSIC_RESULTS_LIMIT", "5"))

# --- Rate limiting и анти-спам ---
TEXT_COOLDOWN_SECONDS = float(os.getenv("TEXT_COOLDOWN_SECONDS", "2"))     # мин. пауза между запросами к ИИ
SPAM_WINDOW_SECONDS = int(os.getenv("SPAM_WINDOW_SECONDS", "10"))          # окно для подсчёта частоты
SPAM_MAX_MESSAGES = int(os.getenv("SPAM_MAX_MESSAGES", "6"))               # макс. сообщений в окне
SPAM_BLOCK_SECONDS = int(os.getenv("SPAM_BLOCK_SECONDS", "30"))            # длительность временной блокировки

# --- RAG (поиск по базе знаний) ---
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "800"))     # размер куска текста в символах
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))                 # сколько кусков подставлять в контекст
RAG_MAX_CHUNKS_TOTAL = int(os.getenv("RAG_MAX_CHUNKS_TOTAL", "3000"))  # предохранитель от разрастания базы

RAG_SYSTEM_PROMPT_TEMPLATE = (
    "Ты отвечаешь СТРОГО на основе предоставленного контекста из базы знаний пользователя. "
    "Не придумывай факты, которых нет в контексте. Если ответа в контексте нет — честно скажи, "
    "что в базе знаний нет информации по этому вопросу, и не пытайся угадать.\n\n"
    "Контекст из базы знаний:\n{context}"
)

# --- Веб-поиск в реальном времени (встроенный инструмент Groq, тот же API-ключ) ---
SEARCH_COOLDOWN_SECONDS = int(os.getenv("SEARCH_COOLDOWN_SECONDS", "10"))
SEARCH_SYSTEM_PROMPT = (
    "Отвечай кратко и по делу на основе актуальной информации из веб-поиска. "
    "Указывай конкретные цифры, даты и факты. Отвечай на русском языке."
)

# --- Мультимодальность ---
VOICE_MAX_DURATION_SECONDS = int(os.getenv("VOICE_MAX_DURATION_SECONDS", "120"))
VISION_DEFAULT_QUESTION = "Опиши подробно, что изображено на этой картинке."

# --- Видео-кружки (Telegram video note) ---
VIDEO_NOTE_MAX_DURATION_SECONDS = int(os.getenv("VIDEO_NOTE_MAX_DURATION_SECONDS", "60"))
VIDEO_NOTE_MAX_FILE_SIZE_MB = int(os.getenv("VIDEO_NOTE_MAX_FILE_SIZE_MB", "20"))
VIDEO_NOTE_SIZE_PX = int(os.getenv("VIDEO_NOTE_SIZE_PX", "480"))

# --- Голосовой AI (озвучка ответов через edge-tts, бесплатно) ---
VOICE_AI_VOICE = os.getenv("VOICE_AI_VOICE", "ru-RU-DmitryNeural")
VOICE_AI_MAX_SECONDS = int(os.getenv("VOICE_AI_MAX_SECONDS", "60"))
VOICE_AI_MAX_CHARS = int(os.getenv("VOICE_AI_MAX_CHARS", "2000"))  # предохранитель перед синтезом

# --- Манеры общения Голосового AI ---
VOICE_PERSONA_DEFAULT = "friendly"
VOICE_PERSONAS = {
    "friendly": {
        "label": "😊 Дружелюбный",
        "description": "Обычное тёплое, доброжелательное общение.",
        "prompt": "",
    },
    "edgy": {
        "label": "😏 Дерзкий",
        "description": "Саркастичный, с подколками и лёгким подтруниванием — без настоящих оскорблений.",
        "prompt": (
            " Общайся дерзко, с юмором и лёгкой иронией: подкалывай пользователя, шути над его вопросами "
            "с сарказмом, можешь беззлобно подтрунить над его словами. При этом никогда не переходи в "
            "настоящие оскорбления: не говори всерьёз, что пользователь глупый, бесполезный или никчёмный, "
            "не используй грубые оскорбления, мат или уничижительные слова в его адрес. Тон — как у "
            "остроумного друга, который подкалывает по-доброму, а не унижает."
        ),
    },
    "charming": {
        "label": "💘 Обаятельный",
        "description": "Тёплый, обаятельный стиль общения с комплиментами.",
        "prompt": (
            " Общайся тепло, обаятельно и с лёгким игривым флиртом: делай пользователю искренние комплименты, "
            "будь внимателен и мил в общении. При этом не изображай романтические чувства всерьёз и не веди "
            "себя как партнёр в отношениях — это дружеское тёплое общение с ноткой очарования, не более."
        ),
    },
}

# --- Дружелюбные извинения вместо технических ошибок ---
FALLBACK_APOLOGIES = [
    "🙈 Что-то пошло не так с моей стороны. Попробуй, пожалуйста, ещё раз через минуту.",
    "😅 Не получилось обработать это прямо сейчас. Дай мне ещё одну попытку чуть позже.",
    "🔧 Небольшая заминка на моей стороне. Попробуй повторить запрос через минуту.",
]

# --- Режимы ответа (доступны только подписчикам) ---
MODES = {
    "default": {
        "label": "🤖 Обычный",
        "description": "Универсальный помощник на все случаи — вопросы, советы, объяснения.",
        "prompt": SYSTEM_PROMPT,
    },
    "copywriter": {
        "label": "✍️ Копирайтер",
        "description": "Пишет цепляющие тексты для постов, рекламы и соцсетей — живым языком, без воды.",
        "prompt": (
            "Ты опытный копирайтер. Пиши цепляющие тексты для постов, рекламы и соцсетей. "
            "Используй живой язык, конкретику, избегай воды и штампов."
        ),
    },
    "coder": {
        "label": "💻 Кодер",
        "description": "Помогает с кодом: пишет, объясняет, находит ошибки и подсказывает best practices.",
        "prompt": (
            "Ты опытный программист-ассистент. Отвечай технически точно, показывай код "
            "с пояснениями, указывай на возможные ошибки и best practices."
        ),
    },
    "simple": {
        "label": "🧒 Простыми словами",
        "description": "Объясняет любую тему максимально просто — для новичка, без сложных терминов.",
        "prompt": (
            "Объясняй всё максимально простыми словами, как для новичка без подготовки. "
            "Используй примеры и аналогии, избегай терминов без объяснения."
        ),
    },
    "kb": {
        "label": "📚 База знаний",
        "description": "Отвечает ТОЛЬКО на основе загруженной администратором базы документов — без выдумок.",
        "prompt": SYSTEM_PROMPT,  # реальный промпт для этого режима собирается динамически с контекстом
    },
}
