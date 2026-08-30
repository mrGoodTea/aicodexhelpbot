import logging
import re

import aiohttp

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_DESCRIPTIONS = {
    0: "☀️ Ясно",
    1: "🌤 Малооблачно",
    2: "⛅ Переменная облачность",
    3: "☁️ Пасмурно",
    45: "🌫 Туман",
    48: "🌫 Изморозь",
    51: "🌦 Лёгкая морось",
    53: "🌦 Морось",
    55: "🌧 Сильная морось",
    56: "🌧 Ледяная морось",
    57: "🌧 Сильная ледяная морось",
    61: "🌦 Небольшой дождь",
    63: "🌧 Дождь",
    65: "🌧 Сильный дождь",
    66: "🌧 Ледяной дождь",
    67: "🌧 Сильный ледяной дождь",
    71: "🌨 Небольшой снег",
    73: "❄️ Снег",
    75: "❄️ Сильный снег",
    77: "❄️ Снежная крупа",
    80: "🌦 Ливень",
    81: "🌧 Сильный ливень",
    82: "⛈ Очень сильный ливень",
    85: "🌨 Небольшой снегопад",
    86: "❄️ Сильный снегопад",
    95: "⛈ Гроза",
    96: "⛈ Гроза с градом",
    99: "⛈ Сильная гроза с градом",
}

_WEATHER_KEYWORDS = re.compile(r"погод[а-яё]*|прогноз[а-яё]*", re.IGNORECASE)
_STOPWORDS = {
    "в", "во", "на", "по", "для", "сегодня", "завтра", "сейчас", "щас",
    "какая", "какой", "как", "г", "город", "городе", "мне", "у", "нас",
}


def extract_weather_city(text: str) -> str | None:
    """
    Если в запросе явно спрашивают про погоду/прогноз — вырезает из текста
    предполагаемое название города. Иначе возвращает None (это не погодный запрос).
    """
    if not _WEATHER_KEYWORDS.search(text):
        return None

    cleaned = _WEATHER_KEYWORDS.sub("", text)
    tokens = [t for t in re.findall(r"[а-яёa-z\-]+", cleaned.lower()) if t not in _STOPWORDS]
    city = " ".join(tokens).strip()
    return city or None


async def get_weather_summary(city_query: str) -> str | None:
    """
    Возвращает готовый текст с текущей погодой по городу через Open-Meteo
    (бесплатно, без ключа, лёгкие ответы — не подвержено ошибке 413, в отличие
    от общего веб-поиска). None — если город не найден геокодером или запрос не удался.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                GEOCODING_URL, params={"name": city_query, "count": 1, "language": "ru"}
            ) as resp:
                if resp.status != 200:
                    return None
                geo_data = await resp.json()
    except Exception as e:
        logging.warning(f"Open-Meteo geocoding error: {e}")
        return None

    results = geo_data.get("results") or []
    if not results:
        return None

    place = results[0]
    lat, lon = place.get("latitude"), place.get("longitude")
    place_name = place.get("name", city_query)
    country = place.get("country", "")

    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            "timezone": "auto",
        }
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(FORECAST_URL, params=params) as resp:
                if resp.status != 200:
                    return None
                weather_data = await resp.json()
    except Exception as e:
        logging.warning(f"Open-Meteo forecast error: {e}")
        return None

    current = weather_data.get("current")
    if not current:
        return None

    code = current.get("weather_code")
    desc = WEATHER_DESCRIPTIONS.get(code, "🌡")
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")

    location_label = f"{place_name}, {country}" if country else place_name

    return (
        f"📍 {location_label}\n"
        f"{desc}\n"
        f"🌡 {temp}°C (ощущается как {feels}°C)\n"
        f"💧 Влажность: {humidity}%\n"
        f"💨 Ветер: {wind} км/ч"
    )
