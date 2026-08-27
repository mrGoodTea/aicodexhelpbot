import logging

import aiohttp
from shazamio import Shazam

from config import GENIUS_ACCESS_TOKEN, MUSIC_RESULTS_LIMIT

DEEZER_SEARCH_URL = "https://api.deezer.com/search"
GENIUS_SEARCH_URL = "https://api.genius.com/search"


class GeniusApiError(Exception):
    """Реальная ошибка запроса к Genius (не путать с 'просто нет совпадений')."""


async def search_track_by_name(query: str, limit: int = MUSIC_RESULTS_LIMIT) -> list[dict]:
    """
    Поиск трека по названию/исполнителю через Deezer API — полностью бесплатно, без ключа.
    Возвращает список {title, artist, url, preview, cover}. preview — ссылка на 30-сек. mp3-отрывок.
    """
    params = {"q": query, "limit": limit}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(DEEZER_SEARCH_URL, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
    except Exception as e:
        logging.error(f"Deezer search error: {e}")
        return []

    results = []
    for item in (data.get("data") or [])[:limit]:
        results.append({
            "title": item.get("title"),
            "artist": (item.get("artist") or {}).get("name"),
            "url": item.get("link"),
            "preview": item.get("preview"),
            "cover": (item.get("album") or {}).get("cover_medium"),
        })
    return results


async def find_preview_url(title: str, artist: str) -> str | None:
    """
    Пытается найти 30-сек. превью для трека через Deezer по названию+исполнителю.
    Используется, чтобы добавить прослушивание к результатам без своего аудио
    (например, из поиска по словам через Genius, где превью нет).
    """
    query = f"{artist or ''} {title or ''}".strip()
    if not query:
        return None
    results = await search_track_by_name(query, limit=1)
    if results and results[0].get("preview"):
        return results[0]["preview"]
    return None


async def search_by_lyrics(query: str, limit: int = MUSIC_RESULTS_LIMIT) -> list[dict] | None:
    """
    Поиск песни по фрагменту текста через Genius API (нужен бесплатный токен в .env).
    Возвращает None, если GENIUS_ACCESS_TOKEN не настроен — тогда фича считается выключенной.
    Поднимает GeniusApiError, если токен задан, но запрос реально не удался (неверный токен,
    сетевая ошибка и т.п.) — это отличается от "просто нет совпадений" (пустой список).
    """
    if not GENIUS_ACCESS_TOKEN:
        return None

    headers = {"Authorization": f"Bearer {GENIUS_ACCESS_TOKEN}"}
    params = {"q": query}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(GENIUS_SEARCH_URL, params=params) as resp:
                body_text = await resp.text()
                if resp.status != 200:
                    logging.error(
                        f"Genius API вернул {resp.status} на запрос '{query}': {body_text[:300]}"
                    )
                    raise GeniusApiError(f"HTTP {resp.status}")
                data = await resp.json()
    except GeniusApiError:
        raise
    except Exception as e:
        logging.error(f"Genius search error: {e}")
        raise GeniusApiError(str(e))

    hits = ((data.get("response") or {}).get("hits") or [])[:limit]
    results = []
    for hit in hits:
        info = hit.get("result") or {}
        results.append({
            "title": info.get("title"),
            "artist": (info.get("primary_artist") or {}).get("name"),
            "url": info.get("url"),
        })
    return results


async def recognize_audio(file_path: str) -> dict | None:
    """
    Распознаёт трек по аудиофайлу через shazamio (неофициальный, но бесплатный клиент Shazam,
    без ключа и лимитов). file_path — путь к уже подготовленному аудиофайлу (mp3/wav и т.п.).
    Возвращает {title, artist, url} либо None, если распознать не удалось.
    """
    try:
        shazam = Shazam()
        result = await shazam.recognize(file_path)
    except Exception as e:
        logging.error(f"Shazam recognize error: {e}")
        return None

    track = result.get("track") if result else None
    if not track:
        return None

    url = track.get("url") or (track.get("share") or {}).get("href")

    return {
        "title": track.get("title"),
        "artist": track.get("subtitle"),
        "url": url,
    }
