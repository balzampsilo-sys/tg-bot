# 📋 План Улучшений Проекта

> Основано на профессиональном code review от сеньор-разработчика Telegram ботов

## 🔴 КРИТИЧНЫЕ ПРОБЛЕМЫ (Высший приоритет)

### 1. Валидация токена бота

**Проблема:** В `config.py` отсутствует проверка формата токена

**Текущий код:**
```python
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")
```

**Исправление:**
```python
import re

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

# Валидация формата токена Telegram: 123456789:ABCdef_1234567890ABCdef
if not re.match(r'^\d{8,10}:[A-Za-z0-9_-]{35}$', BOT_TOKEN):
    raise ValueError(
        "Invalid BOT_TOKEN format. Expected format: 123456789:ABCdef_123..."
    )
```

**Файл:** `config.py` (строки 10-13)

---

### 2. Добавление Rate Limiting

**Проблема:** Пользователи могут спамить кнопками, перегружая бота

**Решение:** Создать middleware для ограничения частоты запросов

**Создать файл:** `middlewares/__init__.py`
```python
"""Middleware для бота"""
```

**Создать файл:** `middlewares/rate_limit.py`
```python
"""Middleware для ограничения частоты запросов"""

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from cachetools import TTLCache


class RateLimitMiddleware(BaseMiddleware):
    """Middleware для защиты от спама"""

    def __init__(self, rate_limit: float = 1.0):
        """
        Args:
            rate_limit: Минимальный интервал между действиями (секунды)
        """
        self.cache = TTLCache(maxsize=10000, ttl=rate_limit)
        self.rate_limit = rate_limit
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Определяем user_id в зависимости от типа события
        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        # Проверяем кэш
        if user_id in self.cache:
            # Для callback query отвечаем тихо
            if isinstance(event, CallbackQuery):
                await event.answer(
                    "⏳ Слишком быстро! Подождите немного",
                    show_alert=False
                )
            elif isinstance(event, Message):
                await event.answer(
                    "⏳ Пожалуйста, подождите немного перед следующим действием"
                )
            logging.warning(f"Rate limit exceeded for user {user_id}")
            return

        # Добавляем в кэш
        self.cache[user_id] = True

        # Продолжаем обработку
        return await handler(event, data)
```

**Обновить:** `main.py`
```python
from middlewares.rate_limit import RateLimitMiddleware

# После создания dp добавить:
dp.message.middleware(RateLimitMiddleware(rate_limit=0.5))  # 0.5 сек между сообщениями
dp.callback_query.middleware(RateLimitMiddleware(rate_limit=0.3))  # 0.3 сек между callback
```

**Добавить в:** `requirements.txt`
```
cachetools==5.3.2
```

---

### 3. Исправление Race Condition в бронировании

**Проблема:** Между проверкой лимита и вставкой записи возможен race condition

**Файл:** `services/booking_service.py` метод `create_booking()`

**Решение 1: Добавить уникальный индекс на уровне БД**

**Обновить:** `database/queries.py` метод `init_db()`
```python
@staticmethod
async def init_db():
    """Инициализация БД с индексами"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # ... существующие таблицы ...
        
        # ИСПРАВЛЕНИЕ: Добавляем уникальный индекс для защиты от дублей
        await db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_user_active_bookings 
            ON bookings(user_id, date, time)"""
        )
        
        await db.commit()
```

**Решение 2: Улучшить логику в сервисе**

**Обновить:** `services/booking_service.py`
```python
async def create_booking(
    self, date_str: str, time_str: str, user_id: int, username: str
) -> Tuple[bool, str]:
    """Создание записи с атомарной проверкой"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            # ИСПРАВЛЕНИЕ: Проверяем и лимит, и слот одним запросом
            async with db.execute(
                """SELECT 
                    (SELECT COUNT(*) FROM bookings WHERE user_id=? AND date >= date('now')) as user_count,
                    (SELECT COUNT(*) FROM bookings WHERE date=? AND time=?) as slot_taken
                """,
                (user_id, date_str, time_str),
            ) as cursor:
                result = await cursor.fetchone()
                user_count, slot_taken = result

            if user_count >= MAX_BOOKINGS_PER_USER:
                await db.rollback()
                return False, "limit_exceeded"

            if slot_taken > 0:
                await db.rollback()
                return False, "slot_taken"

            # Создаем запись
            cursor = await db.execute(
                """INSERT INTO bookings (date, time, user_id, username, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (date_str, time_str, user_id, username, now_local().isoformat()),
            )
            booking_id = cursor.lastrowid

            await db.commit()

            # Планируем напоминание
            await self._schedule_reminder(booking_id, date_str, time_str, user_id)
            await Database.log_event(
                user_id, "booking_created", f"{date_str} {time_str}"
            )

            logging.info(f"Booking created: {booking_id} for user {user_id}")
            return True, "success"

        except sqlite3.IntegrityError as e:
            await db.rollback()
            logging.warning(f"Integrity error: {e}")
            return False, "slot_taken"
        except Exception as e:
            await db.rollback()
            logging.error(f"Error in create_booking: {e}")
            return False, "unknown_error"
```

---

### 4. Исправление обработки timezone

**Проблема:** `replace(tzinfo=)` не учитывает переход на летнее время

**Файл:** `database/queries.py` и `services/booking_service.py`

**Найти и заменить все вхождения:**
```python
# ПЛОХО ❌
booking_datetime = booking_datetime.replace(tzinfo=TIMEZONE)

# ХОРОШО ✅
from datetime import datetime
import pytz

# В config.py изменить:
TIMEZONE = pytz.timezone("Europe/Moscow")  # вместо ZoneInfo

# В коде использовать:
booking_datetime = TIMEZONE.localize(booking_datetime)
```

**Обновить:** `requirements.txt`
```
pytz==2023.3.post1
```

**Найти в файлах:**
- `database/queries.py` (строка ~403)
- `services/booking_service.py` (строки ~234, ~267)

---

### 5. Добавить retry логику для Telegram API

**Проблема:** Если Telegram API недоступен, бот упадет

**Создать файл:** `utils/retry.py`
```python
"""Утилиты для повторных попыток"""

import asyncio
import logging
from functools import wraps
from typing import Callable


def async_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """Декоратор для повторных попыток асинхронных функций
    
    Args:
        max_attempts: Максимальное количество попыток
        delay: Начальная задержка между попытками (секунды)
        backoff: Множитель для экспоненциальной задержки
        exceptions: Кортеж исключений для перехвата
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logging.error(
                            f"Failed after {max_attempts} attempts: {func.__name__}"
                        )
                        raise

                    logging.warning(
                        f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            raise last_exception

        return wrapper

    return decorator
```

**Обновить:** `main.py`
```python
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from utils.retry import async_retry

@async_retry(
    max_attempts=5,
    delay=2.0,
    backoff=2.0,
    exceptions=(TelegramNetworkError, TelegramRetryAfter, ConnectionError)
)
async def start_bot():
    """Запуск бота с retry логикой"""
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # ... остальной код ...
    
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()

async def main():
    """Главная функция с обработкой критических ошибок"""
    try:
        await start_bot()
    except Exception as e:
        logging.critical(f"Bot crashed with critical error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 6. Исправление валидации прошедших дат и времени

**Проблема:** Проверяется только дата, но не время. Можно выбрать сегодня в прошедшее время.

**Файл:** `handlers/booking_handlers.py` функция `select_day()`

**Исправление:**
```python
@router.callback_query(F.data.startswith("day:"))
async def select_day(callback: CallbackQuery, state: FSMContext):
    """Выбор дня с валидацией"""
    try:
        date_str = callback.data.split(":", 1)[1]
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, IndexError) as e:
        await callback.answer("❌ Ошибка: неверная дата", show_alert=True)
        logging.error(f"Invalid date in select_day: {callback.data}, error: {e}")
        await state.clear()
        return

    # ИСПРАВЛЕНИЕ: Проверяем datetime, а не только date
    now = now_local()
    selected_date = date_obj.date()
    
    # Если выбрана прошедшая дата
    if selected_date < now.date():
        await callback.answer("❌ Нельзя выбрать прошедшую дату", show_alert=True)
        return
    
    # Если выбрана сегодняшняя дата - проверяем есть ли доступные слоты
    if selected_date == now.date():
        # Получаем все слоты и фильтруем прошедшие
        occupied = await Database.get_occupied_slots_for_day(date_str)
        available_slots = []
        
        for hour in range(WORK_HOURS_START, WORK_HOURS_END):
            time_str = f"{hour:02d}:00"
            slot_datetime = datetime.combine(selected_date, datetime.strptime(time_str, "%H:%M").time())
            slot_datetime = TIMEZONE.localize(slot_datetime)
            
            # Проверяем что слот в будущем И свободен
            if slot_datetime > now and time_str not in occupied:
                available_slots.append(time_str)
        
        if not available_slots:
            await callback.answer(
                "❌ На сегодня нет доступных слотов\n\nВыберите другую дату",
                show_alert=True
            )
            return
    else:
        # Для будущих дат - стандартная проверка
        occupied = await Database.get_occupied_slots_for_day(date_str)
        total_slots = WORK_HOURS_END - WORK_HOURS_START
        
        if len(occupied) >= total_slots:
            await callback.answer(
                "❌ Все слоты на эту дату заняты\n\nВыберите другую дату",
                show_alert=True
            )
            return

    await callback.answer("⏳ Загружаю слоты...")

    try:
        text, kb = await create_time_slots(date_str, state)
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Error editing message in select_day: {e}")
        await callback.answer("❌ Ошибка отображения")
        await state.clear()
```

**Также обновить:** `keyboards/user_keyboards.py` функцию `create_time_slots()`
```python
async def create_time_slots(date_str: str, state: FSMContext) -> Tuple[str, InlineKeyboardMarkup]:
    """Создание клавиатуры с временными слотами"""
    from utils.helpers import now_local
    
    occupied = await Database.get_occupied_slots_for_day(date_str)
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    now = now_local()
    is_today = date_obj.date() == now.date()
    
    buttons = []
    row = []
    
    for hour in range(WORK_HOURS_START, WORK_HOURS_END):
        time_str = f"{hour:02d}:00"
        
        # ИСПРАВЛЕНИЕ: Проверяем что время не в прошлом (для сегодняшней даты)
        is_past = False
        if is_today:
            slot_datetime = datetime.combine(date_obj.date(), datetime.strptime(time_str, "%H:%M").time())
            slot_datetime = TIMEZONE.localize(slot_datetime)
            is_past = slot_datetime <= now
        
        # Определяем callback_data и текст
        if is_past:
            # Прошедшее время - неактивная кнопка
            callback_data = "ignore"
            button_text = f"⚫ {time_str}"
        elif time_str in occupied:
            # Занятый слот
            callback_data = "ignore"
            button_text = f"❌ {time_str}"
        else:
            # Свободный слот
            data = await state.get_data()
            is_rescheduling = data.get("reschedule_booking_id") is not None
            
            if is_rescheduling:
                callback_data = f"reschedule_time:{date_str}:{time_str}"
            else:
                callback_data = f"time:{date_str}:{time_str}"
            
            button_text = f"✅ {time_str}"
        
        row.append(InlineKeyboardButton(text=button_text, callback_data=callback_data))
        
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Кнопка назад
    buttons.append([
        InlineKeyboardButton(text="🔙 Назад к календарю", callback_data="back_calendar")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    day_name = DAY_NAMES[date_obj.weekday()]
    text = (
        f"📍 ШАГ 2 из 3: Выберите время\n\n"
        f"📅 {date_obj.strftime('%d.%m.%Y')} ({day_name})\n\n"
        f"✅ = свободно\n"
        f"❌ = занято\n"
    )
    
    if is_today:
        text += "⚫ = прошедшее время\n"
    
    return text, kb
```

---

## 🟡 СРЕДНИЕ ПРОБЛЕМЫ (Средний приоритет)

### 7. Рефакторинг Database класса

**Проблема:** God Object - 700+ строк кода в одном классе

**Решение:** Разделить на репозитории по ответственности

**Создать структуру:**
```
database/
├── __init__.py
├── models.py (существует)
├── connection.py (новый)
├── repositories/
│   ├── __init__.py
│   ├── base.py
│   ├── booking_repository.py
│   ├── user_repository.py
│   ├── analytics_repository.py
│   └── blocked_slots_repository.py
└── queries.py (переименовать в migrations.py)
```

**Создать:** `database/connection.py`
```python
"""Управление подключениями к БД"""

import aiosqlite
from contextlib import asynccontextmanager
from config import DATABASE_PATH


class DatabaseConnection:
    """Менеджер подключений к базе данных"""
    
    @staticmethod
    @asynccontextmanager
    async def get_connection():
        """Получить подключение к БД с автоматическим закрытием"""
        conn = await aiosqlite.connect(DATABASE_PATH)
        try:
            yield conn
        finally:
            await conn.close()
    
    @staticmethod
    @asynccontextmanager
    async def transaction():
        """Транзакция с автоматическим rollback при ошибке"""
        async with DatabaseConnection.get_connection() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
```

**Создать:** `database/repositories/base.py`
```python
"""Базовый репозиторий"""

from abc import ABC
from database.connection import DatabaseConnection


class BaseRepository(ABC):
    """Базовый класс для всех репозиториев"""
    
    @staticmethod
    def get_connection():
        """Получить подключение к БД"""
        return DatabaseConnection.get_connection()
    
    @staticmethod
    def transaction():
        """Получить транзакцию"""
        return DatabaseConnection.transaction()
```

**Создать:** `database/repositories/booking_repository.py`
```python
"""Репозиторий для работы с бронированиями"""

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from database.repositories.base import BaseRepository
from utils.helpers import now_local


class BookingRepository(BaseRepository):
    """Репозиторий для операций с бронированиями"""
    
    @staticmethod
    async def create(
        date_str: str, 
        time_str: str, 
        user_id: int, 
        username: str
    ) -> Optional[int]:
        """Создать бронирование
        
        Returns:
            booking_id или None при ошибке
        """
        try:
            async with BookingRepository.get_connection() as db:
                cursor = await db.execute(
                    """INSERT INTO bookings (date, time, user_id, username, created_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (date_str, time_str, user_id, username, now_local().isoformat()),
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logging.error(f"Error creating booking: {e}")
            return None
    
    @staticmethod
    async def get_by_id(booking_id: int, user_id: int) -> Optional[Tuple]:
        """Получить бронирование по ID"""
        try:
            async with BookingRepository.get_connection() as db:
                async with db.execute(
                    "SELECT date, time, username FROM bookings WHERE id=? AND user_id=?",
                    (booking_id, user_id),
                ) as cursor:
                    return await cursor.fetchone()
        except Exception as e:
            logging.error(f"Error getting booking {booking_id}: {e}")
            return None
    
    @staticmethod
    async def get_user_bookings(user_id: int) -> List[Tuple]:
        """Получить активные записи пользователя"""
        try:
            now = now_local()
            async with BookingRepository.get_connection() as db:
                async with db.execute(
                    """SELECT id, date, time, username, created_at 
                    FROM bookings 
                    WHERE user_id=? 
                    ORDER BY date, time""",
                    (user_id,),
                ) as cursor:
                    bookings = await cursor.fetchall()

            # Фильтруем только будущие
            future_bookings = []
            for booking_id, date_str, time_str, username, created_at in bookings:
                booking_dt = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                )
                booking_dt = booking_dt.replace(tzinfo=now.tzinfo)
                if booking_dt >= now:
                    future_bookings.append(
                        (booking_id, date_str, time_str, username, created_at)
                    )

            return future_bookings
        except Exception as e:
            logging.error(f"Error getting bookings for user {user_id}: {e}")
            return []
    
    @staticmethod
    async def delete(booking_id: int, user_id: int) -> bool:
        """Удалить бронирование"""
        try:
            async with BookingRepository.get_connection() as db:
                cursor = await db.execute(
                    "DELETE FROM bookings WHERE id=? AND user_id=?",
                    (booking_id, user_id),
                )
                await db.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"Error deleting booking {booking_id}: {e}")
            return False
    
    @staticmethod
    async def is_slot_free(date_str: str, time_str: str) -> bool:
        """Проверить свободен ли слот"""
        try:
            async with BookingRepository.get_connection() as db:
                async with db.execute(
                    "SELECT * FROM bookings WHERE date=? AND time=?",
                    (date_str, time_str),
                ) as cursor:
                    booking = await cursor.fetchone()

                async with db.execute(
                    "SELECT * FROM blocked_slots WHERE date=? AND time=?",
                    (date_str, time_str),
                ) as cursor:
                    blocked = await cursor.fetchone()

                return booking is None and blocked is None
        except Exception as e:
            logging.error(f"Error checking slot {date_str} {time_str}: {e}")
            return False
    
    @staticmethod
    async def get_occupied_slots_for_day(date_str: str) -> set:
        """Получить все занятые слоты за день"""
        occupied = set()
        try:
            async with BookingRepository.get_connection() as db:
                # Забронированные слоты
                async with db.execute(
                    "SELECT time FROM bookings WHERE date=?", (date_str,)
                ) as cursor:
                    bookings = await cursor.fetchall()
                    occupied.update(time for (time,) in bookings)

                # Заблокированные слоты
                async with db.execute(
                    "SELECT time FROM blocked_slots WHERE date=?", (date_str,)
                ) as cursor:
                    blocked = await cursor.fetchall()
                    occupied.update(time for (time,) in blocked)
        except Exception as e:
            logging.error(f"Error getting occupied slots for {date_str}: {e}")

        return occupied
    
    @staticmethod
    async def count_user_bookings(user_id: int) -> int:
        """Подсчитать количество активных бронирований пользователя"""
        try:
            async with BookingRepository.get_connection() as db:
                async with db.execute(
                    """SELECT COUNT(*) FROM bookings
                    WHERE user_id=? AND date >= date('now')""",
                    (user_id,),
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logging.error(f"Error counting bookings for user {user_id}: {e}")
            return 0
```

**Примечание:** Аналогично создайте:
- `user_repository.py` (для операций с пользователями)
- `analytics_repository.py` (для аналитики)
- `blocked_slots_repository.py` (для блокировок)

**Обновить:** Все места где используется `Database.*` заменить на соответствующие репозитории

---

### 8. Вынести тексты в локализацию

**Проблема:** Хардкод текстов в коде затрудняет поддержку и перевод

**Создать:** `locales/ru.json`
```json
{
  "booking": {
    "confirmed": "✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!",
    "select_date": "📍 ШАГ 1 из 3: Выберите дату",
    "select_time": "📍 ШАГ 2 из 3: Выберите время",
    "confirm": "📍 ШАГ 3 из 3: Подтверждение",
    "cancelled": "✅ ЗАПИСЬ ОТМЕНЕНА",
    "slot_taken": "❌ Этот слот уже занят!",
    "limit_exceeded": "⚠️ У вас уже {max} активных записи",
    "past_date": "❌ Нельзя выбрать прошедшую дату",
    "no_slots": "❌ Все слоты на эту дату заняты"
  },
  "calendar": {
    "free": "🟢",
    "partial": "🟡",
    "full": "🔴",
    "past": "⚫"
  },
  "errors": {
    "invalid_data": "❌ Ошибка: неверные данные",
    "not_found": "❌ Запись не найдена",
    "unknown": "❌ Произошла ошибка"
  }
}
```

**Создать:** `utils/localization.py`
```python
"""Система локализации"""

import json
import logging
from pathlib import Path
from typing import Any, Dict


class Localization:
    """Менеджер локализации"""
    
    def __init__(self, locale: str = "ru"):
        self.locale = locale
        self.translations: Dict[str, Any] = {}
        self._load_translations()
    
    def _load_translations(self):
        """Загрузить переводы из файла"""
        try:
            locale_file = Path(__file__).parent.parent / f"locales/{self.locale}.json"
            with open(locale_file, "r", encoding="utf-8") as f:
                self.translations = json.load(f)
        except Exception as e:
            logging.error(f"Failed to load translations for {self.locale}: {e}")
            self.translations = {}
    
    def get(self, key: str, **kwargs) -> str:
        """Получить перевод по ключу
        
        Args:
            key: Ключ в формате "section.key" (например: "booking.confirmed")
            **kwargs: Параметры для форматирования
        
        Returns:
            Переведенная строка или ключ если перевод не найден
        """
        keys = key.split(".")
        value = self.translations
        
        try:
            for k in keys:
                value = value[k]
            
            # Форматирование параметров
            if kwargs and isinstance(value, str):
                return value.format(**kwargs)
            
            return value
        except (KeyError, TypeError):
            logging.warning(f"Translation not found for key: {key}")
            return key


# Глобальный экземпляр
_localization = Localization("ru")


def t(key: str, **kwargs) -> str:
    """Shortcut функция для получения перевода"""
    return _localization.get(key, **kwargs)
```

**Использование в коде:**
```python
from utils.localization import t

# Было:
await message.answer("✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!")

# Стало:
await message.answer(t("booking.confirmed"))

# С параметрами:
await message.answer(t("booking.limit_exceeded", max=MAX_BOOKINGS_PER_USER))
```

---

### 9. Оптимизация SQL запросов

**Проблема:** В `get_month_statuses()` выполняются 2 отдельных запроса

**Файл:** `database/queries.py` (или новый `booking_repository.py`)

**Исправление:**
```python
@staticmethod
async def get_month_statuses(year: int, month: int) -> dict:
    """Получить статусы всех дней месяца ОДНИМ запросом"""
    try:
        import calendar
        from config import WORK_HOURS_START, WORK_HOURS_END
        
        first_day = datetime(year, month, 1).date()
        last_day_num = calendar.monthrange(year, month)[1]
        last_day = datetime(year, month, last_day_num).date()

        statuses = {}
        total_slots = WORK_HOURS_END - WORK_HOURS_START

        async with BookingRepository.get_connection() as db:
            # ИСПРАВЛЕНИЕ: Объединяем запросы через UNION ALL
            async with db.execute(
                """SELECT date, SUM(cnt) as total_count FROM (
                    SELECT date, COUNT(*) as cnt
                    FROM bookings
                    WHERE date >= ? AND date <= ?
                    GROUP BY date
                    
                    UNION ALL
                    
                    SELECT date, COUNT(*) as cnt
                    FROM blocked_slots
                    WHERE date >= ? AND date <= ?
                    GROUP BY date
                )
                GROUP BY date""",
                (
                    first_day.isoformat(), last_day.isoformat(),
                    first_day.isoformat(), last_day.isoformat()
                ),
            ) as cursor:
                rows = await cursor.fetchall()

        # Определяем статусы
        for date_str, total_count in rows:
            if total_count == 0:
                statuses[date_str] = "🟢"
            elif total_count < total_slots:
                statuses[date_str] = "🟡"
            else:
                statuses[date_str] = "🔴"

        return statuses
    except Exception as e:
        logging.error(f"Error getting month statuses for {year}-{month}: {e}")
        return {}
```

---

### 10. Добавить недостающие индексы

**Файл:** `database/queries.py` метод `init_db()`

**Добавить:**
```python
# Индексы для аналитики
await db.execute(
    """CREATE INDEX IF NOT EXISTS idx_analytics_timestamp
    ON analytics(timestamp)"""
)

await db.execute(
    """CREATE INDEX IF NOT EXISTS idx_feedback_timestamp
    ON feedback(timestamp)"""
)

await db.execute(
    """CREATE INDEX IF NOT EXISTS idx_feedback_user
    ON feedback(user_id)"""
)

# Индекс для быстрого поиска будущих бронирований
await db.execute(
    """CREATE INDEX IF NOT EXISTS idx_bookings_date_time
    ON bookings(date, time)"""
)
```

---

## 🟢 НИЗКИЙ ПРИОРИТЕТ (Можно отложить)

### 11. Настройка CI/CD

**Создать:** `.github/workflows/ci.yml`
```yaml
name: CI

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install black isort flake8 mypy
      
      - name: Format check with black
        run: black --check .
      
      - name: Import sorting with isort
        run: isort --check-only .
      
      - name: Lint with flake8
        run: flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
      
      - name: Type check with mypy
        run: mypy . --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov
      
      - name: Run tests
        run: |
          pytest --cov=. --cov-report=xml --cov-report=term
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

**Создать:** `.github/workflows/deploy.yml`
```yaml
name: Deploy

on:
  push:
    branches: [ main ]
    tags:
      - 'v*'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to production
        run: |
          echo "Deploy logic here"
          # Например: docker build, push, restart
```

---

### 12. Добавить Docker

**Создать:** `Dockerfile`
```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создание директории для БД
RUN mkdir -p /app/data

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/app/data/bookings.db

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

CMD ["python", "main.py"]
```

**Создать:** `docker-compose.yml`
```yaml
version: '3.8'

services:
  bot:
    build: .
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**Запуск:**
```bash
docker-compose up -d
```

---

### 13. Мониторинг и логирование

**Добавить Sentry для отслеживания ошибок:**

**requirements.txt:**
```
sentry-sdk==1.40.0
```

**config.py:**
```python
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
```

**main.py:**
```python
import sentry_sdk
from config import SENTRY_DSN

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,
        environment="production",
    )
```

---

## 📊 Порядок внедрения

### Этап 1: Критические исправления (1-2 дня)
1. ✅ Валидация токена бота
2. ✅ Rate limiting middleware
3. ✅ Исправление race condition
4. ✅ Исправление timezone
5. ✅ Retry логика
6. ✅ Валидация времени

### Этап 2: Рефакторинг (3-5 дней)
7. ✅ Разделение Database на репозитории
8. ✅ Локализация текстов
9. ✅ Оптимизация SQL
10. ✅ Добавление индексов

### Этап 3: Инфраструктура (2-3 дня)
11. ✅ CI/CD настройка
12. ✅ Docker контейнеризация
13. ✅ Мониторинг и алерты

### Этап 4: Тестирование (3-4 дня)
14. ✅ Написание unit тестов
15. ✅ Интеграционные тесты
16. ✅ Нагрузочное тестирование

## 📝 Итоговый чеклист

- [ ] Критические исправления безопасности
- [ ] Rate limiting внедрен
- [ ] Race conditions устранены
- [ ] Timezone корректно обрабатывается
- [ ] Retry логика добавлена
- [ ] Валидация времени работает
- [ ] Database разделен на репозитории
- [ ] Тексты вынесены в локализацию
- [ ] SQL запросы оптимизированы
- [ ] Индексы добавлены
- [ ] CI/CD настроен
- [ ] Docker работает
- [ ] Мониторинг подключен
- [ ] Тесты написаны (coverage > 60%)

## 🎯 Ожидаемый результат

После внедрения всех улучшений:
- **Безопасность:** 9/10
- **Производительность:** 8/10
- **Надежность:** 9/10
- **Поддерживаемость:** 9/10
- **Тесты:** 8/10
- **Общая оценка:** 8.5/10

---

**Время на реализацию:** 10-14 рабочих дней  
**Сложность:** Средняя  
**Приоритет:** Высокий
