"""Запросы к базе данных"""

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import aiosqlite

from config import (
    CANCELLATION_HOURS,
    DATABASE_PATH,
    MAX_BOOKINGS_PER_USER,
    WORK_HOURS_END,
    WORK_HOURS_START,
)
from utils.helpers import now_local


@dataclass
class ClientStats:
    """Статистика клиента"""
    total_bookings: int
    cancelled_bookings: int
    avg_rating: float
    last_booking: Optional[str]


class Database:
    """Класс для работы с базой данных"""

    @staticmethod
    async def init_db():
        """Инициализация БД с индексами"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Таблицы
            await db.execute("""CREATE TABLE IF NOT EXISTS bookings
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, time TEXT, user_id INTEGER, username TEXT,
                created_at TEXT, UNIQUE(date, time))""")

            await db.execute("""CREATE TABLE IF NOT EXISTS users
                (user_id INTEGER PRIMARY KEY, first_seen TEXT)""")

            await db.execute("""CREATE TABLE IF NOT EXISTS analytics
                (user_id INTEGER, event TEXT, data TEXT, timestamp TEXT)""")

            await db.execute(
                """CREATE TABLE IF NOT EXISTS feedback
                (user_id INTEGER, booking_id INTEGER, rating INTEGER, timestamp TEXT)"""
            )

            # Таблица блокировки слотов
            await db.execute("""CREATE TABLE IF NOT EXISTS blocked_slots
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                reason TEXT,
                blocked_by INTEGER NOT NULL,
                blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, time))""")

            await db.execute("""CREATE TABLE IF NOT EXISTS admin_sessions
                (user_id INTEGER PRIMARY KEY, message_id INTEGER, updated_at TEXT)""")

            # Индексы для производительности
            await db.execute("""CREATE INDEX IF NOT EXISTS idx_bookings_date
                ON bookings(date, time)""")
            await db.execute("""CREATE INDEX IF NOT EXISTS idx_bookings_user
                ON bookings(user_id)""")
            await db.execute("""CREATE INDEX IF NOT EXISTS idx_analytics_user
                ON analytics(user_id, event)""")
            await db.execute("""CREATE INDEX IF NOT EXISTS idx_blocked_date
                ON blocked_slots(date, time)""")
            
            # ИСПРАВЛЕНО: Уникальный индекс для защиты от race condition
            await db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_user_active_bookings 
                ON bookings(user_id, date, time)"""
            )
            
            # ИСПРАВЛЕНО: Индексы для аналитики
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
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_bookings_date_time
                ON bookings(date, time)"""
            )

            await db.commit()
            logging.info("Database initialized with indexes and race condition protection")

    @staticmethod
    async def log_event(user_id: int, event: str, data: str = ""):
        """Логирование событий с обработкой ошибок"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "INSERT INTO analytics (user_id, event, data, timestamp) VALUES (?, ?, ?, ?)",
                    (user_id, event, data, now_local().isoformat()),
                )
                await db.commit()
        except Exception as e:
            # Не падаем, только логируем
            logging.error(f"Failed to log event {event} for user {user_id}: {e}")

    @staticmethod
    async def is_new_user(user_id: int) -> bool:
        """Проверка нового пользователя"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT user_id FROM users WHERE user_id=?", (user_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    if not result:
                        await db.execute(
                            "INSERT INTO users (user_id, first_seen) VALUES (?, ?)",
                            (user_id, now_local().isoformat()),
                        )
                        await db.commit()
                        return True
            return False
        except Exception as e:
            logging.error(f"Error checking new user {user_id}: {e}")
            return False

    @staticmethod
    async def is_slot_free(date_str: str, time_str: str) -> bool:
        """Проверка свободен ли слот (включая блокировки)"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
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
        """Получить все занятые слоты за день (включая блокировки)"""
        occupied = set()
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
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
    async def get_month_statuses(year: int, month: int) -> dict:
        """Получить статусы всех дней месяца одним запросом (оптимизация)"""
        try:
            # Первый и последний день месяца
            first_day = datetime(year, month, 1).date()
            last_day_num = calendar.monthrange(year, month)[1]
            last_day = datetime(year, month, last_day_num).date()

            statuses = {}
            total_slots = WORK_HOURS_END - WORK_HOURS_START

            async with aiosqlite.connect(DATABASE_PATH) as db:
                # ИСПРАВЛЕНО: Объединяем бронирования и блокировки в один запрос
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

    @staticmethod
    async def get_day_status(date_str: str) -> str:
        """Статус загрузки дня (🟢🟡🔴) включая блокировки"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,)
                ) as cursor:
                    result = await cursor.fetchone()
                    booked_count = result[0] if result else 0

                async with db.execute(
                    "SELECT COUNT(*) FROM blocked_slots WHERE date=?", (date_str,)
                ) as cursor:
                    result = await cursor.fetchone()
                    blocked_count = result[0] if result else 0

            total_occupied = booked_count + blocked_count
            total_slots = WORK_HOURS_END - WORK_HOURS_START
            
            if total_occupied == 0:
                return "🟢"
            elif total_occupied < total_slots:
                return "🟡"
            else:
                return "🔴"
        except Exception as e:
            logging.error(f"Error getting day status for {date_str}: {e}")
            return "🟢"  # По умолчанию свободно

    # === МЕТОДЫ ДЛЯ БЛОКИРОВКИ СЛОТОВ ===

    @staticmethod
    async def block_slot(date_str: str, time_str: str, admin_id: int, reason: str = None) -> bool:
        """Заблокировать слот"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "INSERT INTO blocked_slots (date, time, reason, blocked_by, blocked_at) VALUES (?, ?, ?, ?, ?)",
                    (date_str, time_str, reason, admin_id, now_local().isoformat())
                )
                await db.commit()
                logging.info(f"Slot {date_str} {time_str} blocked by admin {admin_id}")
                return True
        except aiosqlite.IntegrityError:
            # Слот уже заблокирован или занят бронированием
            logging.warning(f"Slot {date_str} {time_str} already blocked or booked")
            return False
        except Exception as e:
            logging.error(f"Error blocking slot {date_str} {time_str}: {e}")
            return False

    @staticmethod
    async def unblock_slot(date_str: str, time_str: str) -> bool:
        """Разблокировать слот"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    "DELETE FROM blocked_slots WHERE date = ? AND time = ?",
                    (date_str, time_str)
                )
                await db.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logging.info(f"Slot {date_str} {time_str} unblocked")
                return deleted
        except Exception as e:
            logging.error(f"Error unblocking slot {date_str} {time_str}: {e}")
            return False

    @staticmethod
    async def is_slot_blocked(date_str: str, time_str: str) -> bool:
        """Проверить, заблокирован ли слот"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT 1 FROM blocked_slots WHERE date = ? AND time = ?",
                    (date_str, time_str)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result is not None
        except Exception as e:
            logging.error(f"Error checking if slot blocked {date_str} {time_str}: {e}")
            return False

    @staticmethod
    async def get_blocked_slots(date_str: str = None) -> List[Tuple]:
        """Получить список заблокированных слотов"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                if date_str:
                    async with db.execute(
                        "SELECT date, time, reason FROM blocked_slots WHERE date = ? ORDER BY time",
                        (date_str,)
                    ) as cursor:
                        return await cursor.fetchall()
                else:
                    async with db.execute(
                        "SELECT date, time, reason FROM blocked_slots ORDER BY date, time"
                    ) as cursor:
                        return await cursor.fetchall()
        except Exception as e:
            logging.error(f"Error getting blocked slots: {e}")
            return []

    # === ОСТАЛЬНЫЕ МЕТОДЫ ===

    @staticmethod
    async def get_user_bookings(user_id: int) -> List[Tuple]:
        """Получить активные записи пользователя"""
        try:
            now = now_local()
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT id, date, time, username, created_at FROM bookings WHERE user_id=? ORDER BY date, time",
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
    async def can_user_book(user_id: int) -> Tuple[bool, int]:
        """Проверка лимита записей"""
        try:
            bookings = await Database.get_user_bookings(user_id)
            count = len(bookings)
            return count < MAX_BOOKINGS_PER_USER, count
        except Exception as e:
            logging.error(f"Error checking booking limit for user {user_id}: {e}")
            return False, 0

    @staticmethod
    async def can_cancel_booking(date_str: str, time_str: str) -> Tuple[bool, float]:
        """Проверка возможности отмены (>24ч)"""
        try:
            booking_datetime = datetime.strptime(
                f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
            )
            booking_datetime = booking_datetime.replace(tzinfo=now_local().tzinfo)
            hours_until = (booking_datetime - now_local()).total_seconds() / 3600
            return hours_until >= CANCELLATION_HOURS, hours_until
        except Exception as e:
            logging.error(f"Error checking cancel possibility: {e}")
            return False, 0.0

    @staticmethod
    async def get_client_stats(user_id: int) -> ClientStats:
        """Статистика клиента"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                # Всего записей
                async with db.execute(
                    "SELECT COUNT(*) FROM analytics WHERE user_id=? AND event='booking_created'",
                    (user_id,),
                ) as cursor:
                    total = (await cursor.fetchone())[0]

                # Отмен
                async with db.execute(
                    "SELECT COUNT(*) FROM analytics WHERE user_id=? AND event='booking_cancelled'",
                    (user_id,),
                ) as cursor:
                    cancelled = (await cursor.fetchone())[0]

                # Средний рейтинг
                async with db.execute(
                    "SELECT AVG(rating) FROM feedback WHERE user_id=?", (user_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    avg_rating = result[0] if result and result[0] else 0.0

                # Последняя запись
                async with db.execute(
                    "SELECT data FROM analytics WHERE user_id=? AND event='booking_created' ORDER BY timestamp DESC LIMIT 1",
                    (user_id,),
                ) as cursor:
                    result = await cursor.fetchone()
                    last_booking = result[0] if result else None

            return ClientStats(
                total_bookings=total,
                cancelled_bookings=cancelled,
                avg_rating=avg_rating,
                last_booking=last_booking,
            )
        except Exception as e:
            logging.error(f"Error getting client stats for {user_id}: {e}")
            return ClientStats(
                total_bookings=0,
                cancelled_bookings=0,
                avg_rating=0.0,
                last_booking=None,
            )

    @staticmethod
    async def get_favorite_slots(user_id: int) -> Tuple[Optional[str], Optional[int]]:
        """Анализ предпочтений пользователя"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                # Любимое время
                async with db.execute(
                    "SELECT time, COUNT(*) as cnt FROM bookings WHERE user_id=? GROUP BY time ORDER BY cnt DESC LIMIT 1",
                    (user_id,),
                ) as cursor:
                    result = await cursor.fetchone()
                    fav_time = result[0] if result else None

                # Любимый день недели
                async with db.execute(
                    """SELECT CAST(strftime('%w', date) AS INTEGER) as dow, COUNT(*) as cnt
                    FROM bookings WHERE user_id=?
                    GROUP BY dow ORDER BY cnt DESC LIMIT 1""",
                    (user_id,),
                ) as cursor:
                    result = await cursor.fetchone()
                    fav_dow = int(result[0]) if result else None

            return fav_time, fav_dow
        except Exception as e:
            logging.error(f"Error getting favorite slots for {user_id}: {e}")
            return None, None

    @staticmethod
    async def save_feedback(user_id: int, booking_id: int, rating: int) -> bool:
        """Сохранение отзыва с обработкой ошибок"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "INSERT INTO feedback (user_id, booking_id, rating, timestamp) VALUES (?, ?, ?, ?)",
                    (user_id, booking_id, rating, now_local().isoformat()),
                )
                await db.commit()
            return True
        except aiosqlite.IntegrityError as e:
            logging.warning(f"Feedback already exists for booking {booking_id}: {e}")
            return False
        except Exception as e:
            logging.error(f"Database error in save_feedback: {e}")
            return False

    @staticmethod
    async def get_booking_by_id(booking_id: int, user_id: int) -> Optional[Tuple]:
        """Получить запись по ID для конкретного пользователя"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT date, time, username FROM bookings WHERE id=? AND user_id=?",
                    (booking_id, user_id),
                ) as cursor:
                    return await cursor.fetchone()
        except Exception as e:
            logging.error(f"Error getting booking {booking_id}: {e}")
            return None

    @staticmethod
    async def delete_booking(booking_id: int, user_id: int) -> bool:
        """Удалить запись по ID (с проверкой владельца)"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    "DELETE FROM bookings WHERE id=? AND user_id=?",
                    (booking_id, user_id),
                )
                await db.commit()
                deleted = cursor.rowcount > 0

                if deleted:
                    logging.info(f"Booking {booking_id} deleted by user {user_id}")
                else:
                    logging.warning(
                        f"Booking {booking_id} not found for user {user_id}"
                    )

                return deleted
        except Exception as e:
            logging.error(f"Error deleting booking {booking_id}: {e}")
            return False

    @staticmethod
    async def get_all_users() -> List[int]:
        """Получить список всех user_id"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute("SELECT user_id FROM users") as cursor:
                    users = await cursor.fetchall()
                    return [user_id for (user_id,) in users]
        except Exception as e:
            logging.error(f"Error getting all users: {e}")
            return []

    @staticmethod
    async def cleanup_old_bookings(before_date: str) -> int:
        """Удалить записи старше указанной даты"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    "DELETE FROM bookings WHERE date < ?", (before_date,)
                )
                await db.commit()
                deleted_count = cursor.rowcount
                logging.info(f"Cleaned up {deleted_count} old bookings")
                return deleted_count
        except Exception as e:
            logging.error(f"Error cleaning up old bookings: {e}")
            return 0

    @staticmethod
    async def get_week_schedule(start_date: str, days: int = 7) -> List[Tuple]:
        """Получить расписание на N дней вперёд"""
        try:
            end_date = (
                datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=days)
            ).strftime("%Y-%m-%d")

            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    """SELECT date, time, username
                    FROM bookings
                    WHERE date >= ? AND date <= ?
                    ORDER BY date, time""",
                    (start_date, end_date),
                ) as cursor:
                    return await cursor.fetchall()
        except Exception as e:
            logging.error(f"Error getting week schedule: {e}")
            return []

    @staticmethod
    async def get_top_clients(limit: int = 10) -> List[Tuple]:
        """Получить топ клиентов по количеству записей"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    """SELECT user_id, COUNT(*) as total
                    FROM analytics
                    WHERE event='booking_created'
                    GROUP BY user_id
                    ORDER BY total DESC
                    LIMIT ?""",
                    (limit,),
                ) as cursor:
                    return await cursor.fetchall()
        except Exception as e:
            logging.error(f"Error getting top clients: {e}")
            return []

    @staticmethod
    async def get_total_users_count() -> int:
        """Получить общее количество пользователей"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                    return (await cursor.fetchone())[0]
        except Exception as e:
            logging.error(f"Error getting users count: {e}")
            return 0
