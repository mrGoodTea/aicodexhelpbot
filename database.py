import sqlite3
import re
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, date

from config import (
    DB_PATH,
    FREE_REQUESTS_PER_DAY,
    SUBSCRIPTION_DAYS,
    TRIAL_DAYS,
    TRIAL_GRANT_MAX_DAYS,
    VOICE_PERSONA_DEFAULT,
    AI_PROVIDER_DEFAULT,
    STREAK_BONUS_EVERY_DAYS,
    STREAK_BONUS_REQUESTS,
    STREAK_DISCOUNT_PERCENT,
    GOLDEN_QUERY_INTERVAL_DAYS,
    DYNAMIC_DISCOUNT_ACTIVE_DAYS,
    DYNAMIC_DISCOUNT_PERCENT,
    DYNAMIC_DISCOUNT_WINDOW_HOURS,
    REFERRAL_SUBSCRIPTION_BONUS_REQUESTS,
    RAG_TOP_K,
    RAG_MAX_CHUNKS_TOTAL,
)

_db_dir = os.path.dirname(DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_column_if_missing(conn, table: str, column: str, coltype: str):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                subscription_until TEXT,
                requests_today INTEGER DEFAULT 0,
                last_request_date TEXT,
                bonus_requests INTEGER DEFAULT 0,
                referred_by INTEGER,
                mode TEXT DEFAULT 'default',
                reminder_sent INTEGER DEFAULT 0,
                last_active_date TEXT,
                streak_count INTEGER DEFAULT 0,
                streak_bonus_given_at_count INTEGER DEFAULT 0,
                golden_query_last_used TEXT,
                discount_percent INTEGER DEFAULT 0,
                discount_expires_at TEXT,
                referral_sub_bonus_given INTEGER DEFAULT 0,
                trial_until TEXT,
                voice_mode INTEGER DEFAULT 0,
                voice_persona TEXT DEFAULT 'friendly',
                ai_provider TEXT DEFAULT 'groq'
            )
        """)
        # миграция для баз, созданных до появления новых колонок
        for col, coltype in [
            ("bonus_requests", "INTEGER DEFAULT 0"),
            ("referred_by", "INTEGER"),
            ("mode", "TEXT DEFAULT 'default'"),
            ("reminder_sent", "INTEGER DEFAULT 0"),
            ("last_active_date", "TEXT"),
            ("streak_count", "INTEGER DEFAULT 0"),
            ("streak_bonus_given_at_count", "INTEGER DEFAULT 0"),
            ("golden_query_last_used", "TEXT"),
            ("discount_percent", "INTEGER DEFAULT 0"),
            ("discount_expires_at", "TEXT"),
            ("referral_sub_bonus_given", "INTEGER DEFAULT 0"),
            ("trial_until", "TEXT"),
            ("voice_mode", "INTEGER DEFAULT 0"),
            ("voice_persona", "TEXT DEFAULT 'friendly'"),
            ("ai_provider", "TEXT DEFAULT 'groq'"),
        ]:
            _add_column_if_missing(conn, "users", col, coltype)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_stars INTEGER,
                charge_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # currency: 'XTR' (Telegram Stars, как раньше) или 'RUB' (оплата картой через ЮKassa).
        # Для RUB значение amount_stars хранит сумму в копейках (так её отдаёт Telegram API).
        _add_column_if_missing(conn, "payments", "currency", "TEXT DEFAULT 'XTR'")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT,
                chunk_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                username TEXT PRIMARY KEY,
                added_by TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def get_or_create_user(
    user_id: int, username: str | None, referred_by: int | None = None
) -> tuple[sqlite3.Row, bool]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        created = False
        if row is None:
            trial_until = (datetime.now() + timedelta(days=TRIAL_DAYS)).isoformat()
            conn.execute(
                "INSERT INTO users (user_id, username, referred_by, trial_until) VALUES (?, ?, ?, ?)",
                (user_id, username, referred_by, trial_until),
            )
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            created = True
        elif username and row["username"] != username:
            # Пользователь сменил юзернейм в Telegram — держим базу в актуальном состоянии,
            # иначе поиск по старому/новому юзернейму (например, для выдачи триала) сломается.
            conn.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                (username, user_id),
            )
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row, created


def _reset_if_new_day(conn, row) -> sqlite3.Row:
    today = date.today().isoformat()
    if row["last_request_date"] != today:
        conn.execute(
            "UPDATE users SET requests_today = 0, last_request_date = ? WHERE user_id = ?",
            (today, row["user_id"]),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (row["user_id"],)).fetchone()
    return row


def has_active_subscription(row: sqlite3.Row) -> bool:
    if not row["subscription_until"]:
        return False
    return datetime.fromisoformat(row["subscription_until"]) > datetime.now()


def is_subscriber(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and has_active_subscription(row))


def has_active_trial(row: sqlite3.Row) -> bool:
    if not row["trial_until"]:
        return False
    return datetime.fromisoformat(row["trial_until"]) > datetime.now()


def is_trial_active(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and has_active_trial(row))


def get_trial_status(user_id: int) -> str | None:
    """Возвращает trial_until в ISO-формате, если пробный период ещё активен, иначе None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and has_active_trial(row):
            return row["trial_until"]
        return None


def has_full_access(row: sqlite3.Row) -> bool:
    """Безлимитный доступ: активная подписка ИЛИ активный пробный период."""
    return has_active_subscription(row) or has_active_trial(row)


def is_full_access(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and has_full_access(row))


def get_user_row(user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def grant_trial(user_id: int, days: int) -> tuple[bool, str]:
    """Выдаёт/продлевает пробный период пользователю на `days` дней.

    Нельзя выдать триал платящему подписчику (возвращает 'has_subscription').
    Остаток триала от текущего момента не может превышать TRIAL_GRANT_MAX_DAYS —
    если уже есть активный триал, дни добавляются к нему, но итог обрезается по потолку.
    Возвращает (success, new_trial_until_iso | причина отказа).
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "user_not_found"
        if has_active_subscription(row):
            return False, "has_subscription"

        now = datetime.now()
        current_trial = datetime.fromisoformat(row["trial_until"]) if row["trial_until"] else None
        base = current_trial if (current_trial and current_trial > now) else now

        new_until = base + timedelta(days=days)
        cap = now + timedelta(days=TRIAL_GRANT_MAX_DAYS)
        if new_until > cap:
            new_until = cap

        conn.execute(
            "UPDATE users SET trial_until = ? WHERE user_id = ?",
            (new_until.isoformat(), user_id),
        )
        return True, new_until.isoformat()


def revoke_trial(user_id: int) -> tuple[bool, str]:
    """Убирает пробный период у пользователя (переводит на free). Не действует на подписчиков."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return False, "user_not_found"
        if has_active_subscription(row):
            return False, "has_subscription"
        conn.execute("UPDATE users SET trial_until = NULL WHERE user_id = ?", (user_id,))
        return True, ""


def can_make_request(user_id: int) -> tuple[bool, str]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        row = _reset_if_new_day(conn, row)

        if has_full_access(row):
            return True, ""
        if row["requests_today"] < FREE_REQUESTS_PER_DAY:
            return True, ""
        if row["bonus_requests"] > 0:
            return True, ""
        return False, "limit"


def register_request(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        row = _reset_if_new_day(conn, row)

        if has_full_access(row):
            return

        if row["requests_today"] < FREE_REQUESTS_PER_DAY:
            conn.execute(
                "UPDATE users SET requests_today = requests_today + 1 WHERE user_id = ?",
                (user_id,),
            )
        elif row["bonus_requests"] > 0:
            conn.execute(
                "UPDATE users SET bonus_requests = bonus_requests - 1 WHERE user_id = ?",
                (user_id,),
            )


def remaining_free_requests(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        row = _reset_if_new_day(conn, row)
        return max(0, FREE_REQUESTS_PER_DAY - row["requests_today"])


def get_bonus_requests(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT bonus_requests FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["bonus_requests"] if row else 0


def add_bonus_requests(user_id: int, amount: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET bonus_requests = bonus_requests + ? WHERE user_id = ?",
            (amount, user_id),
        )


def count_referrals(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE referred_by = ?", (user_id,)
        ).fetchone()
        return row["cnt"] if row else 0


def get_username(user_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["username"] if row else None


def get_top_referrers(limit: int = 10) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT referred_by AS user_id, COUNT(*) AS cnt
            FROM users
            WHERE referred_by IS NOT NULL
            GROUP BY referred_by
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def activate_subscription(user_id: int, charge_id: str, amount_stars: int, currency: str = "XTR"):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        now = datetime.now()
        base = now
        if row["subscription_until"]:
            current_until = datetime.fromisoformat(row["subscription_until"])
            if current_until > now:
                base = current_until
        new_until = base + timedelta(days=SUBSCRIPTION_DAYS)

        conn.execute(
            "UPDATE users SET subscription_until = ?, reminder_sent = 0 WHERE user_id = ?",
            (new_until.isoformat(), user_id),
        )
        conn.execute(
            "INSERT INTO payments (user_id, amount_stars, charge_id, currency) VALUES (?, ?, ?, ?)",
            (user_id, amount_stars, charge_id, currency),
        )
        return new_until


def get_subscription_status(user_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and row["subscription_until"] and has_active_subscription(row):
            return row["subscription_until"]
        return None


# --- Режимы ответа ---

def set_user_mode(user_id: int, mode: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET mode = ? WHERE user_id = ?", (mode, user_id))


def get_user_mode(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT mode FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["mode"] if row and row["mode"] else "default"


# --- Напоминание об окончании подписки ---

def get_users_to_remind(days_before: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        now = datetime.now().isoformat()
        threshold = (datetime.now() + timedelta(days=days_before)).isoformat()
        return conn.execute(
            """
            SELECT * FROM users
            WHERE subscription_until IS NOT NULL
              AND subscription_until > ?
              AND subscription_until <= ?
              AND reminder_sent = 0
            """,
            (now, threshold),
        ).fetchall()


def mark_reminder_sent(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET reminder_sent = 1 WHERE user_id = ?", (user_id,))


# --- Стрик и геймификация ---

def update_streak(user_id: int) -> tuple[int, bool]:
    """
    Обновляет стрик активности (дни подряд). Вызывать не чаще раза в день на пользователя —
    повторные вызовы в тот же день ничего не меняют.
    Возвращает (текущий_стрик, бонус_начислен_ли_сейчас).
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        today = date.today()

        if row["last_active_date"] == today.isoformat():
            return row["streak_count"] or 0, False

        if row["last_active_date"] == (today - timedelta(days=1)).isoformat():
            streak = (row["streak_count"] or 0) + 1
        else:
            streak = 1

        conn.execute(
            "UPDATE users SET last_active_date = ?, streak_count = ? WHERE user_id = ?",
            (today.isoformat(), streak, user_id),
        )

        bonus_awarded = False
        if (
            streak > 0
            and streak % STREAK_BONUS_EVERY_DAYS == 0
            and streak != row["streak_bonus_given_at_count"]
        ):
            conn.execute(
                "UPDATE users SET bonus_requests = bonus_requests + ?, "
                "streak_bonus_given_at_count = ? WHERE user_id = ?",
                (STREAK_BONUS_REQUESTS, streak, user_id),
            )
            bonus_awarded = True

        return streak, bonus_awarded


def get_streak(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT streak_count FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["streak_count"] if row and row["streak_count"] else 0


# --- Золотой запрос ---

def is_golden_query_available(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT golden_query_last_used FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row or not row["golden_query_last_used"]:
            return True
        last_used = datetime.fromisoformat(row["golden_query_last_used"])
        return datetime.now() - last_used >= timedelta(days=GOLDEN_QUERY_INTERVAL_DAYS)


def use_golden_query(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET golden_query_last_used = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id),
        )


# --- Динамическая скидка ---

def maybe_grant_dynamic_discount(user_id: int) -> bool:
    """
    Если пользователь бесплатный, набрал минимум DYNAMIC_DISCOUNT_ACTIVE_DAYS дней подряд активности
    и скидка ещё не выдавалась — выдаёт временную скидку. Возвращает True, если выдана именно сейчас.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if has_active_subscription(row):
            return False
        if row["discount_percent"]:
            return False  # скидка уже когда-то выдавалась — повторно не выдаём
        if (row["streak_count"] or 0) < DYNAMIC_DISCOUNT_ACTIVE_DAYS:
            return False

        expires = datetime.now() + timedelta(hours=DYNAMIC_DISCOUNT_WINDOW_HOURS)
        conn.execute(
            "UPDATE users SET discount_percent = ?, discount_expires_at = ? WHERE user_id = ?",
            (DYNAMIC_DISCOUNT_PERCENT, expires.isoformat(), user_id),
        )
        return True


def get_active_discount(user_id: int) -> tuple[int, str | None]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT discount_percent, discount_expires_at FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row or not row["discount_percent"] or not row["discount_expires_at"]:
            return 0, None
        if datetime.fromisoformat(row["discount_expires_at"]) <= datetime.now():
            return 0, None
        return row["discount_percent"], row["discount_expires_at"]


def get_purchase_discount_percent(user_id: int) -> int:
    """Суммарная скидка при покупке: временная динамическая + бонус за стрик (берётся большая)."""
    dynamic_percent, _ = get_active_discount(user_id)
    with get_conn() as conn:
        row = conn.execute("SELECT streak_count FROM users WHERE user_id = ?", (user_id,)).fetchone()
    streak = row["streak_count"] if row else 0
    streak_percent = STREAK_DISCOUNT_PERCENT if streak >= STREAK_BONUS_EVERY_DAYS else 0
    return min(70, max(dynamic_percent, streak_percent))


def clear_discount(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET discount_percent = 0, discount_expires_at = NULL WHERE user_id = ?",
            (user_id,),
        )


# --- Реферальный бонус за покупку подписки другом ---

def grant_referral_subscription_bonus_if_needed(user_id: int) -> int | None:
    """
    Если у купившего подписку пользователя есть referred_by и бонус ещё не выдавался —
    начисляет рефереру REFERRAL_SUBSCRIPTION_BONUS_REQUESTS. Возвращает id реферера, если бонус выдан.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row["referred_by"] or row["referral_sub_bonus_given"]:
            return None
        referrer_id = row["referred_by"]
        conn.execute(
            "UPDATE users SET bonus_requests = bonus_requests + ? WHERE user_id = ?",
            (REFERRAL_SUBSCRIPTION_BONUS_REQUESTS, referrer_id),
        )
        conn.execute(
            "UPDATE users SET referral_sub_bonus_given = 1 WHERE user_id = ?",
            (user_id,),
        )
        return referrer_id


# --- База знаний (RAG) ---

def add_kb_chunks(source_name: str, chunks: list[str]) -> int:
    """Добавляет куски текста в базу знаний. Возвращает, сколько реально добавлено
    (с учётом предохранителя RAG_MAX_CHUNKS_TOTAL)."""
    with get_conn() as conn:
        current_count = conn.execute("SELECT COUNT(*) AS cnt FROM kb_chunks").fetchone()["cnt"]
        free_slots = max(0, RAG_MAX_CHUNKS_TOTAL - current_count)
        to_add = chunks[:free_slots]
        for chunk in to_add:
            conn.execute(
                "INSERT INTO kb_chunks (source_name, chunk_text) VALUES (?, ?)",
                (source_name, chunk),
            )
        return len(to_add)


def list_kb_sources() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT source_name, COUNT(*) AS chunks, MIN(created_at) AS added_at
            FROM kb_chunks
            GROUP BY source_name
            ORDER BY added_at DESC
            """
        ).fetchall()


def clear_kb():
    with get_conn() as conn:
        conn.execute("DELETE FROM kb_chunks")


def kb_chunk_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS cnt FROM kb_chunks").fetchone()["cnt"]


def search_kb(query: str, top_k: int = None) -> list[str]:
    """
    Простой поиск по ключевым словам (без внешнего embeddings API): для каждого куска
    считается количество пересечений слов с запросом, взвешенное по редкости слова
    (упрощённый TF-IDF). Подходит для небольших баз (FAQ, инструкции, до ~тысяч кусков).
    """
    top_k = top_k or RAG_TOP_K
    with get_conn() as conn:
        rows = conn.execute("SELECT chunk_text FROM kb_chunks").fetchall()

    if not rows:
        return []

    def tokenize(text: str) -> set[str]:
        return {w.lower() for w in re.findall(r"\w{3,}", text.lower())}

    query_words = tokenize(query)
    if not query_words:
        return []

    # редкость слова по всей базе (чем реже слово встречается в кусках — тем весомее совпадение)
    doc_word_sets = [tokenize(r["chunk_text"]) for r in rows]
    word_doc_freq: dict[str, int] = {}
    for words in doc_word_sets:
        for w in words & query_words:
            word_doc_freq[w] = word_doc_freq.get(w, 0) + 1

    scored = []
    for row, words in zip(rows, doc_word_sets):
        overlap = words & query_words
        if not overlap:
            continue
        score = sum(1 / word_doc_freq[w] for w in overlap)
        scored.append((score, row["chunk_text"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:top_k]]


# --- Админ-панель: список клиентов ---

def get_all_users(limit: int = 500, offset: int = 0) -> list[sqlite3.Row]:
    """Возвращает пользователей, отсортированных по дате регистрации (новые сверху)."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()


def count_all_users() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        return row["cnt"] if row else 0


def get_admin_stats() -> dict:
    """Сводная статистика для админ-панели."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        now = datetime.now().isoformat()
        subscribers = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE subscription_until IS NOT NULL AND subscription_until > ?",
            (now,),
        ).fetchone()["c"]
        on_trial = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE trial_until IS NOT NULL AND trial_until > ?",
            (now,),
        ).fetchone()["c"]
        today = date.today().isoformat()
        active_today = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE last_active_date = ?",
            (today,),
        ).fetchone()["c"]
        return {
            "total": total,
            "subscribers": subscribers,
            "on_trial": on_trial,
            "active_today": active_today,
        }


# --- Динамическое управление админами (добавляются владельцем через бота) ---

def add_admin(username: str, added_by: str | None = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (username, added_by) VALUES (?, ?)",
            (username, added_by),
        )


def remove_admin(username: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM admins WHERE username = ?", (username,))


def list_db_admins() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT username FROM admins ORDER BY added_at").fetchall()
        return [r["username"] for r in rows]


def is_db_admin(username: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM admins WHERE username = ?", (username,)).fetchone()
        return row is not None


def get_user_id_by_username(username: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM users WHERE username = ? COLLATE NOCASE ORDER BY created_at DESC LIMIT 1",
            (username,),
        ).fetchone()
        return row["user_id"] if row else None


# --- Голосовой AI: переключатель ответа голосом ---

def get_voice_mode(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT voice_mode FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and row["voice_mode"])


def toggle_voice_mode(user_id: int) -> bool:
    """Переключает режим и возвращает новое состояние (True = включён)."""
    with get_conn() as conn:
        row = conn.execute("SELECT voice_mode FROM users WHERE user_id = ?", (user_id,)).fetchone()
        new_state = 0 if (row and row["voice_mode"]) else 1
        conn.execute("UPDATE users SET voice_mode = ? WHERE user_id = ?", (new_state, user_id))
        return bool(new_state)


def get_voice_persona(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT voice_persona FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return (row["voice_persona"] if row and row["voice_persona"] else VOICE_PERSONA_DEFAULT)


def set_voice_persona(user_id: int, persona_key: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET voice_persona = ? WHERE user_id = ?", (persona_key, user_id))


def get_ai_provider(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT ai_provider FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return (row["ai_provider"] if row and row["ai_provider"] else AI_PROVIDER_DEFAULT)


def set_ai_provider(user_id: int, provider_key: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET ai_provider = ? WHERE user_id = ?", (provider_key, user_id))
