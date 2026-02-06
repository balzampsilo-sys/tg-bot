"""Запросы к базе данных"""
import logging
import aiosqlite
from typing import List, Optional, Tuple
from datetime import datetime, timedelta

from config import DATABASE_PATH, MAX_BOOKINGS_PER_USER, CANCELLATION_HOURS
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
        """Логирование событий"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO analytics (user_id, event, data, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, event, data, now_local().isoformat())
            )
            await db.commit()
    
    @staticmethod
    async def is_new_user(user_id: int) -> bool:
        """Проверка нового пользователя"""
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
    
    @staticmethod
    async def is_slot_free(date_str: str, time_str: str) -> bool:
        """Проверка свободен ли слот"""
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
    
    @staticmethod
    async def get_occupied_slots_for_day(date_str: str) -> set:
        """Получить все занятые слоты за день"""
        occupied = set()
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
        
        return occupied
    
    @staticmethod
    async def get_day_status(date_str: str) -> str:
        """Статус загрузки дня (🟢🟡🔴)"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,)
            ) as cursor:
                result = await cursor.fetchone()
                booked_count = result[0] if result else 0
        
        total_slots = 10
        if booked_count == 0:
            return "🟢"
        elif booked_count < total_slots:
            return "🟡"
        else:
            return "🔴"
    
    @staticmethod
    async def get_user_bookings(user_id: int) -> List[Tuple]:
        """Получить активные записи пользователя"""
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
    
    @staticmethod
    async def can_user_book(user_id: int) -> Tuple[bool, int]:
        """Проверка лимита записей"""
        bookings = await Database.get_user_bookings(user_id)
        count = len(bookings)
        return count < MAX_BOOKINGS_PER_USER, count
    
    @staticmethod
    async def can_cancel_booking(date_str: str, time_str: str) -> Tuple[bool, float]:
        """Проверка возможности отмены (>24ч)"""
        booking_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        booking_datetime = booking_datetime.replace(tzinfo=now_local().tzinfo)
        hours_until = (booking_datetime - now_local()).total_seconds() / 3600
        return hours_until >= CANCELLATION_HOURS, hours_until
    
    @staticmethod
    async def get_client_stats(user_id: int) -> ClientStats:
        """Статистика клиента"""
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
    
    @staticmethod
    async def get_favorite_slots(user_id: int) -> Tuple[Optional[str], Optional[int]]:
        """Анализ предпочтений пользователя"""
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
    
    @staticmethod
    async def save_feedback(user_id: int, booking_id: int, rating: int):
        """Сохранение отзыва"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO feedback (user_id, booking_id, rating, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, booking_id, rating, now_local().isoformat())
            )
            await db.commit()
