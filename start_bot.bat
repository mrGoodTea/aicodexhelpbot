@echo off
chcp 65001 >nul
title Telegram Bot

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [Ошибка] Не найдена папка venv рядом с этим файлом.
    echo Убедись, что start_bot.bat лежит в той же папке, что и venv, bot.py и .env
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

if not exist ".env" (
    echo [Ошибка] Не найден файл .env
    echo Создай его на основе .env.example и укажи BOT_TOKEN и GROQ_API_KEY
    pause
    exit /b 1
)

echo Starting the bot...
echo To stop the bot, close this window or click Ctrl+C
echo.

python bot.py

echo.
echo Бот остановлен.
pause