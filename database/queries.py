"""Запросы к базе данных"""
import logging
import aiosqlite
import calendar
from typing import List, Optional, Tuple
from datetime import datetime, timedelta

from config import DATABASE_PATH, MAX_BOOKINGS_PER_USER, CANCELLATION_HOURS, WORK_HOURS_START, WORK_HOURS_END
from utils.helpers import now_local
from database.models import Booking, ClientStats


class Database:
    """Класс для работы с базой данных"""
    
    @staticmethod
    async def init_db():
        """Инициализация БД с индексами"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Таблицы
            await db.execute('''CREATE TABLE IF NOT EXISTS bookings
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, time TEXT, user_id INTEGER, username TEXT,
                created_at TEXT, UNIQUE(date, time))''')
            
            await db.execute('''CREATE TABLE IF NOT EXISTS users
                (user_id INTEGER PRIMARY KEY, first_seen TEXT)''')
            
            await db.execute('''CREATE TABLE IF NOT EXISTS analytics
                (user_id INTEGER, event TEXT, data TEXT, timestamp TEXT)''')
            
            await db.execute('''CREATE TABLE IF NOT EXISTS feedback
                (user_id INTEGER, booking_id INTEGER, rating INTEGER, timestamp TEXT)''')
            
            await db.execute('''CREATE TABLE IF NOT EXISTS blocked_slots
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, time TEXT, reason TEXT, created_by INTEGER,
                created_at TEXT, UNIQUE(date, time))''')
            
            await db.execute('''CREATE TABLE IF NOT EXISTS admin_sessions
                (user_id INTEGER PRIMARY KEY, message_id INTEGER, updated_at TEXT)''')
            
            # Индексы для производительности
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_bookings_date 
                ON bookings(date, time)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_bookings_user 
                ON bookings(user_id)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_analytics_user 
                ON analytics(user_id, event)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_blocked_date 
                ON blocked_slots(date, time)''')
            
            await db.commit()
            logging.info("Database initialized with indexes")
    
    @staticmethod
    async def log_event(user_id: int, event: str, data: str = ""):
        """Логирование событий с обработкой ошибок"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "INSERT INTO analytics (user_id, event, data, timestamp) VALUES (?, ?, ?, ?)",
                    (user_id, event, data, now_local().isoformat())
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
                            (user_id, now_local().isoformat())
                        )
                        await db.commit()
                        return True
            return False
        except Exception as e:
            logging.error(f"Error checking new user {user_id}: {e}")
            return False
    
    @staticmethod
    async def is_slot_free(date_str: str, time_str: str) -> bool:
        """Проверка свободен ли слот"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT * FROM bookings WHERE date=? AND time=?",
                    (date_str, time_str)
                ) as cursor:
                    booking = await cursor.fetchone()
                
                async with db.execute(
                    "SELECT * FROM blocked_slots WHERE date=? AND time=?",
                    (date_str, time_str)
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
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT time FROM bookings WHERE date=?", (date_str,)
                ) as cursor:
                    bookings = await cursor.fetchall()
                    occupied.update(time for (time,) in bookings)
                
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
                async with db.execute(
                    """SELECT date, COUNT(*) as booked_count 
                    FROM bookings 
                    WHERE date >= ? AND date <= ?
                    GROUP BY date""",
                    (first_day.isoformat(), last_day.isoformat())
                ) as cursor:
                    rows = await cursor.fetchall()
                    
            for date_str, booked_count in rows:
                if booked_count == 0:
                    statuses[date_str] = "🟢"
                elif booked_count < total_slots:
                    statuses[date_str] = "🟡"
                else:
                    statuses[date_str] = "🔴"
            
            return statuses
        except Exception as e:
            logging.error(f"Error getting month statuses for {year}-{month}: {e}")
            return {}
    
    @staticmethod
    async def get_day_status(date_str: str) -> str:
        """Статус загрузки дня (🟢🟡🔴)"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,)
                ) as cursor:
                    result = await cursor.fetchone()
                    booked_count = result[0] if result else 0
            
            total_slots = WORK_HOURS_END - WORK_HOURS_START
            if booked_count == 0:
                return "🟢"
            elif booked_count < total_slots:
                return "🟡"
            else:
                return "🔴"
        except Exception as e:
            logging.error(f"Error getting day status for {date_str}: {e}")
            return "🟢"  # По умолчанию свободно
    
    @staticmethod
    async def get_user_bookings(user_id: int) -> List[Tuple]:
        """Получить активные записи пользователя"""
        try:
            now = now_local()
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT id, date, time, username, created_at FROM bookings WHERE user_id=? ORDER BY date, time",
                    (user_id,)
                ) as cursor:
                    bookings = await cursor.fetchall()
            
            # Фильтруем только будущие
            future_bookings = []
            for booking_id, date_str, time_str, username, created_at in bookings:
                booking_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                booking_dt = booking_dt.replace(tzinfo=now.tzinfo)
                if booking_dt >= now:
                    future_bookings.append((booking_id, date_str, time_str, username, created_at))
            
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
            booking_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
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
                    (user_id,)
                ) as cursor:
                    total = (await cursor.fetchone())[0]
                
                # Отмен
                async with db.execute(
                    "SELECT COUNT(*) FROM analytics WHERE user_id=? AND event='booking_cancelled'",
                    (user_id,)
                ) as cursor:
                    cancelled = (await cursor.fetchone())[0]
                
                # Средний рейтинг
                async with db.execute(
                    "SELECT AVG(rating) FROM feedback WHERE user_id=?",
                    (user_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    avg_rating = result[0] if result and result[0] else 0.0
                
                # Последняя запись
                async with db.execute(
                    "SELECT data FROM analytics WHERE user_id=? AND event='booking_created' ORDER BY timestamp DESC LIMIT 1",
                    (user_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    last_booking = result[0] if result else None
            
            return ClientStats(
                total_bookings=total,
                cancelled_bookings=cancelled,
                avg_rating=avg_rating,
                last_booking=last_booking
            )
        except Exception as e:
            logging.error(f"Error getting client stats for {user_id}: {e}")
            return ClientStats(total_bookings=0, cancelled_bookings=0, avg_rating=0.0, last_booking=None)
    
    @staticmethod
    async def get_favorite_slots(user_id: int) -> Tuple[Optional[str], Optional[int]]:
        """Анализ предпочтений пользователя"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                # Любимое время
                async with db.execute(
                    "SELECT time, COUNT(*) as cnt FROM bookings WHERE user_id=? GROUP BY time ORDER BY cnt DESC LIMIT 1",
                    (user_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    fav_time = result[0] if result else None
                
                # Любимый день недели
                async with db.execute(
                    """SELECT CAST(strftime('%w', date) AS INTEGER) as dow, COUNT(*) as cnt
                    FROM bookings WHERE user_id=?
                    GROUP BY dow ORDER BY cnt DESC LIMIT 1""",
                    (user_id,)
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
                    (user_id, booking_id, rating, now_local().isoformat())
                )
                await db.commit()
            return True
        except aiosqlite.IntegrityError as e:
            logging.warning(f"Feedback already exists for booking {booking_id}: {e}")
            return False
        except Exception as e:
            logging.error(f"Database error in save_feedback: {e}")
            return False
