@echo off
chcp 65001 > nul
title Telegram Bot
color 0A

echo ================================================
echo        ЗАПУСК TELEGRAM БОТА
echo ================================================
echo.

echo [1/7] Убиваем старые процессы Python...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
echo ✓ Готово

echo.
echo [2/7] Ожидание 10 секунд...
timeout /t 10 /nobreak >nul
echo ✓ Готово

echo.
echo [3/7] Проверка что процессы убиты...
tasklist | findstr python >nul
if not errorlevel 1 (
    echo ✗ ОШИБКА: Python всё ещё работает!
    echo Закройте все программы Python вручную!
    pause
    exit /b 1
)
echo ✓ Процессы убиты

echo.
echo [4/7] Переход в папку проекта...
cd /d C:\bot_project\bot-5\tg-bot
if errorlevel 1 (
    echo ✗ ОШИБКА: Папка не найдена!
    pause
    exit /b 1
)
echo ✓ Готово

echo.
echo [5/7] Активация venv...
if not exist venv\Scripts\activate.bat (
    echo ✗ ОШИБКА: venv не найден!
    echo Создаём venv...
    python -m venv venv
)
call venv\Scripts\activate
echo ✓ Готово

echo.
echo [6/7] Установка зависимостей...
pip install -r requirements.txt --quiet --disable-pip-version-check
echo ✓ Готово

echo.
echo [7/7] Запуск бота...
echo.
echo ================================================
echo   ✓ БОТ ЗАПУЩЕН!
echo   
echo   НЕ ЗАКРЫВАЙТЕ ЭТО ОКНО!
echo   НЕ ЗАПУСКАЙТЕ БОТ ЕЩЁ РАЗ!
echo   
echo   Для остановки: Ctrl+C
echo ================================================
echo.

python main.py

echo.
echo Бот остановлен.
pause
