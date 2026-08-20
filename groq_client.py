import io

from openai import AsyncOpenAI

from config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    GROQ_WHISPER_MODEL,
    GROQ_VISION_MODEL,
    GROQ_SEARCH_MODEL,
    SYSTEM_PROMPT,
    SEARCH_SYSTEM_PROMPT,
)

client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)


async def ask_ai(
    user_text: str,
    history: list[dict] | None = None,
    system_prompt: str | None = None,
) -> str:
    """
    Отправляет запрос в Groq (OpenAI-совместимый API).
    history — список предыдущих сообщений вида {"role": "user"/"assistant", "content": "..."}
    system_prompt — кастомный системный промпт (например, для выбранного режима подписчика).
    """
    messages = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    try:
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Ошибка при обращении к ИИ: {e}\n\nПопробуйте ещё раз чуть позже."


async def ask_with_web_search(query: str) -> str:
    """
    Отвечает на вопрос с использованием встроенного в Groq веб-поиска (модель groq/compound-mini) —
    не требует отдельного API-ключа для поиска, Groq сам обращается к вебу и формирует ответ.
    """
    try:
        response = await client.chat.completions.create(
            model=GROQ_SEARCH_MODEL,
            messages=[
                {"role": "system", "content": SEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Не удалось выполнить веб-поиск: {e}\n\nПопробуйте ещё раз чуть позже."


async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """
    Распознаёт речь через Groq Whisper. Возвращает распознанный текст,
    либо строку, начинающуюся с '⚠️', если распознать не удалось.
    """
    try:
        file_obj = io.BytesIO(audio_bytes)
        file_obj.name = filename  # SDK ориентируется на расширение по имени файла
        result = await client.audio.transcriptions.create(
            model=GROQ_WHISPER_MODEL,
            file=file_obj,
            response_format="json",
        )
        return result.text
    except Exception as e:
        return f"⚠️ Не удалось распознать голосовое сообщение: {e}"


async def analyze_image(image_data_url: str, question: str) -> str:
    """
    Анализирует изображение через мультимодальную модель Groq.
    image_data_url — уже готовый data:image/...;base64,... URL.
    """
    try:
        response = await client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Не удалось проанализировать изображение: {e}"
