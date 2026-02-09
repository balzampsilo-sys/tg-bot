"""Конфигурация приложения"""

import os
import re
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Админы (поддержка нескольких)
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
if not ADMIN_IDS_STR:
    raise ValueError("ADMIN_IDS not found in .env file")

ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(",") if id.strip()]

# Валидация токена бота
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

# Проверка формата токена Telegram: 123456789:ABCdef_1234567890ABCdef
if not re.match(r'^\d{8,10}:[A-Za-z0-9_-]{35}$', BOT_TOKEN):
    raise ValueError(
        "Invalid BOT_TOKEN format. Expected format: 123456789:ABCdef_123..."
    )

if not ADMIN_IDS:
    raise ValueError("No valid admin IDs provided")

# База данных
DATABASE_PATH = "bookings.db"

# Настройки бронирования
MAX_BOOKINGS_PER_USER = 3
CANCELLATION_HOURS = 24
WORK_HOURS_START = 9
WORK_HOURS_END = 19

# Настройки услуги
SERVICE_DURATION = "1 час"
SERVICE_LOCATION = "г. Москва, ул. Примерная, 1 / Онлайн"
SERVICE_PRICE = "3000 ₽"

# Временная зона
TIMEZONE = ZoneInfo("Europe/Moscow")

# Тайминги и задержки (в секундах)
ONBOARDING_DELAY_SHORT = 1.0  # Короткая задержка между сообщениями
ONBOARDING_DELAY_LONG = 4.0   # Длинная задержка для чтения
BROADCAST_DELAY = 0.05        # Задержка между сообщениями в рассылке (50ms)
RATE_LIMIT_TIME = 1.0         # Время между действиями одного пользователя

# FSM таймауты (в секундах)
FSM_STATE_TTL = 600  # 10 минут - автоматический сброс состояния

# Ограничения навигации календаря
CALENDAR_MAX_MONTHS_AHEAD = 3  # Максимум месяцев вперёд для бронирования

# Названия месяцев
MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]

# Названия дней недели
DAY_NAMES = [
    "понедельник",
    "вторник",
    "среду",
    "четверг",
    "пятницу",
    "субботу",
    "воскресенье",
]

DAY_NAMES_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
