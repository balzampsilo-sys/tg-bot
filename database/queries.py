"""Фасад для работы с базой данных через репозитории"""

import logging
from typing import Dict, List, Optional, Set, Tuple

import aiosqlite

from config import DATABASE_PATH
from database.repositories import (
    AnalyticsRepository,
    BookingRepository,
    ClientStats,
    UserRepository,
)

# Реэкспортируем ClientStats для обратной совместимости
__all__ = ["Database", "ClientStats"]


class Database:
    """
    Фасад для работы с базой данных.
    Делегирует вызовы специализированным репозиториям.
    """

    # === ИНИЦИАЛИЗАЦИЯ ===

    @staticmethod
    async def init_db():
        """Инициализация БД с таблицами и индексами"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Таблицы
            await db.execute(
                """CREATE TABLE IF NOT EXISTS bookings
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, time TEXT, user_id INTEGER, username TEXT,
                created_at TEXT, UNIQUE(date, time))"""
            )

            await db.execute(
                """CREATE TABLE IF NOT EXISTS users
                (user_id INTEGER PRIMARY KEY, first_seen TEXT)"""
            )

            await db.execute(
                """CREATE TABLE IF NOT EXISTS analytics
                (user_id INTEGER, event TEXT, data TEXT, timestamp TEXT)"""
            )

            await db.execute(
                """CREATE TABLE IF NOT EXISTS feedback
                (user_id INTEGER, booking_id INTEGER, rating INTEGER, timestamp TEXT)"""
            )

            await db.execute(
                """CREATE TABLE IF NOT EXISTS blocked_slots
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                reason TEXT,
                blocked_by INTEGER NOT NULL,
                blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, time))"""
            )

            await db.execute(
                """CREATE TABLE IF NOT EXISTS admin_sessions
                (user_id INTEGER PRIMARY KEY, message_id INTEGER, updated_at TEXT)"""
            )

            # Индексы для производительности
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_bookings_date
                ON bookings(date, time)"""
            )
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_bookings_user
                ON bookings(user_id)"""
            )
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_analytics_user
                ON analytics(user_id, event)"""
            )
            await db.execute(
                """CREATE INDEX IF NOT EXISTS idx_blocked_date
                ON blocked_slots(date, time)"""
            )
            await db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_user_active_bookings
                ON bookings(user_id, date, time)"""
            )
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
            logging.info(
                "Database initialized with indexes and race condition protection"
            )

    # === БРОНИРОВАНИЯ (делегирование в BookingRepository) ===

    @staticmethod
    async def is_slot_free(date_str: str, time_str: str) -> bool:
        return await BookingRepository.is_slot_free(date_str, time_str)

    @staticmethod
    async def get_occupied_slots_for_day(date_str: str) -> Set[str]:
        return await BookingRepository.get_occupied_slots_for_day(date_str)

    @staticmethod
    async def get_month_statuses(year: int, month: int) -> Dict[str, str]:
        return await BookingRepository.get_month_statuses(year, month)

    @staticmethod
    async def get_user_bookings(user_id: int) -> List[Tuple]:
        return await BookingRepository.get_user_bookings(user_id)

    @staticmethod
    async def can_user_book(user_id: int) -> Tuple[bool, int]:
        return await BookingRepository.can_user_book(user_id)

    @staticmethod
    async def can_cancel_booking(date_str: str, time_str: str) -> Tuple[bool, float]:
        return await BookingRepository.can_cancel_booking(date_str, time_str)

    @staticmethod
    async def get_booking_by_id(
        booking_id: int, user_id: int
    ) -> Optional[Tuple[str, str, str]]:
        return await BookingRepository.get_booking_by_id(booking_id, user_id)

    @staticmethod
    async def delete_booking(booking_id: int, user_id: int) -> bool:
        return await BookingRepository.delete_booking(booking_id, user_id)

    @staticmethod
    async def cleanup_old_bookings(before_date: str) -> int:
        return await BookingRepository.cleanup_old_bookings(before_date)

    @staticmethod
    async def get_week_schedule(start_date: str, days: int = 7) -> List[Tuple]:
        return await BookingRepository.get_week_schedule(start_date, days)

    @staticmethod
    async def block_slot(
        date_str: str, time_str: str, admin_id: int, reason: str = None
    ) -> bool:
        return await BookingRepository.block_slot(date_str, time_str, admin_id, reason)

    @staticmethod
    async def unblock_slot(date_str: str, time_str: str) -> bool:
        return await BookingRepository.unblock_slot(date_str, time_str)

    @staticmethod
    async def is_slot_blocked(date_str: str, time_str: str) -> bool:
        """DEPRECATED: Используйте is_slot_free() вместо этого"""
        result = await BookingRepository.is_slot_free(date_str, time_str)
        return not result

    @staticmethod
    async def get_blocked_slots(date_str: str = None) -> List[Tuple]:
        return await BookingRepository.get_blocked_slots(date_str)

    @staticmethod
    async def get_day_status(date_str: str) -> str:
        """Статус загрузки дня (🟢🟡🔴)"""
        # Оставляем здесь, так как используется редко
        occupied = await BookingRepository.get_occupied_slots_for_day(date_str)
        from config import WORK_HOURS_END, WORK_HOURS_START

        total_slots = WORK_HOURS_END - WORK_HOURS_START
        total_occupied = len(occupied)

        if total_occupied == 0:
            return "🟢"
        elif total_occupied < total_slots:
            return "🟡"
        else:
            return "🔴"

    # === ПОЛЬЗОВАТЕЛИ (делегирование в UserRepository) ===

    @staticmethod
    async def is_new_user(user_id: int) -> bool:
        return await UserRepository.is_new_user(user_id)

    @staticmethod
    async def get_all_users() -> List[int]:
        return await UserRepository.get_all_users()

    @staticmethod
    async def get_total_users_count() -> int:
        return await UserRepository.get_total_users_count()

    @staticmethod
    async def get_favorite_slots(user_id: int) -> Tuple[Optional[str], Optional[int]]:
        return await UserRepository.get_favorite_slots(user_id)

    # === АНАЛИТИКА И ОТЗЫВЫ (делегирование в AnalyticsRepository) ===

    @staticmethod
    async def log_event(user_id: int, event: str, data: str = ""):
        await AnalyticsRepository.log_event(user_id, event, data)

    @staticmethod
    async def get_client_stats(user_id: int) -> ClientStats:
        return await AnalyticsRepository.get_client_stats(user_id)

    @staticmethod
    async def save_feedback(user_id: int, booking_id: int, rating: int) -> bool:
        return await AnalyticsRepository.save_feedback(user_id, booking_id, rating)

    @staticmethod
    async def get_top_clients(limit: int = 10) -> List[Tuple]:
        return await AnalyticsRepository.get_top_clients(limit)
