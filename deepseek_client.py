import logging

from openai import AsyncOpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


async def ask_deepseek(query_text: str, history: list[dict] | None = None, system_prompt: str = "") -> str:
    """Тот же интерфейс, что и groq_client.ask_ai — чтобы process_user_query могла
    выбирать провайдера прозрачно, не меняя остальную логику."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": query_text})

    response = await client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        max_tokens=2000,
    )
    return response.choices[0].message.content
