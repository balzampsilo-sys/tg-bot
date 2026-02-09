"""Репозиторий для работы с бронированиями"""

import calendar
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import aiosqlite

from config import (
    CANCELLATION_HOURS,
    DATABASE_PATH,
    MAX_BOOKINGS_PER_USER,
    TIMEZONE,
    WORK_HOURS_END,
    WORK_HOURS_START,
)
from database.base_repository import BaseRepository
from utils.helpers import now_local


class BookingRepository(BaseRepository):
    """Репозиторий для управления бронированиями"""

    @staticmethod
    async def is_slot_free(date_str: str, time_str: str) -> bool:
        """Проверить свободен ли слот (включая блокировки)"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                # Проверяем бронирование
                booking_exists = await BookingRepository._exists(
                    "bookings", "date=? AND time=?", (date_str, time_str)
                )
                # Проверяем блокировку
                async with db.execute(
                    "SELECT 1 FROM blocked_slots WHERE date=? AND time=?",
                    (date_str, time_str),
                ) as cursor:
                    blocked_exists = await cursor.fetchone() is not None

                return not booking_exists and not blocked_exists
        except Exception as e:
            logging.error(f"Error checking slot {date_str} {time_str}: {e}")
            return False

    @staticmethod
    async def get_occupied_slots_for_day(date_str: str) -> Set[str]:
        """Получить все занятые слоты за день"""
        occupied = set()
        try:
            # Забронированные
            bookings = await BookingRepository._execute_query(
                "SELECT time FROM bookings WHERE date=?", (date_str,), fetch_all=True
            )
            if bookings:
                occupied.update(time for (time,) in bookings)

            # Заблокированные
            blocked = await BookingRepository._execute_query(
                "SELECT time FROM blocked_slots WHERE date=?", (date_str,), fetch_all=True
            )
            if blocked:
                occupied.update(time for (time,) in blocked)
        except Exception as e:
            logging.error(f"Error getting occupied slots for {date_str}: {e}")

        return occupied

    @staticmethod
    async def get_month_statuses(year: int, month: int) -> Dict[str, str]:
        """Получить статусы всех дней месяца"""
        try:
            first_day = datetime(year, month, 1).date()
            last_day_num = calendar.monthrange(year, month)[1]
            last_day = datetime(year, month, last_day_num).date()

            statuses = {}
            total_slots = WORK_HOURS_END - WORK_HOURS_START

            # Объединенный запрос UNION ALL
            rows = await BookingRepository._execute_query(
                """SELECT date, SUM(cnt) as total_count FROM (
                    SELECT date, COUNT(*) as cnt FROM bookings
                    WHERE date >= ? AND date <= ? GROUP BY date
                    UNION ALL
                    SELECT date, COUNT(*) as cnt FROM blocked_slots
                    WHERE date >= ? AND date <= ? GROUP BY date
                ) GROUP BY date""",
                (
                    first_day.isoformat(),
                    last_day.isoformat(),
                    first_day.isoformat(),
                    last_day.isoformat(),
                ),
                fetch_all=True,
            )

            if rows:
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
    async def get_user_bookings(user_id: int) -> List[Tuple]:
        """Получить активные (будущие) записи пользователя"""
        try:
            now = now_local()
            bookings = await BookingRepository._execute_query(
                "SELECT id, date, time, username, created_at FROM bookings "
                "WHERE user_id=? ORDER BY date, time",
                (user_id,),
                fetch_all=True,
            )

            if not bookings:
                return []

            # Фильтруем только будущие
            future_bookings = []
            for booking_id, date_str, time_str, username, created_at in bookings:
                booking_dt_naive = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                )
                booking_dt = TIMEZONE.localize(booking_dt_naive)

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
        """Проверить лимит записей пользователя"""
        try:
            bookings = await BookingRepository.get_user_bookings(user_id)
            count = len(bookings)
            return count < MAX_BOOKINGS_PER_USER, count
        except Exception as e:
            logging.error(f"Error checking booking limit for user {user_id}: {e}")
            return False, 0

    @staticmethod
    async def can_cancel_booking(date_str: str, time_str: str) -> Tuple[bool, float]:
        """Проверить возможность отмены (>24ч)"""
        try:
            booking_dt_naive = datetime.strptime(
                f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
            )
            booking_dt = TIMEZONE.localize(booking_dt_naive)
            now = now_local()
            hours_until = (booking_dt - now).total_seconds() / 3600
            return hours_until >= CANCELLATION_HOURS, hours_until
        except Exception as e:
            logging.error(f"Error checking cancel possibility: {e}")
            return False, 0.0

    @staticmethod
    async def get_booking_by_id(
        booking_id: int, user_id: int
    ) -> Optional[Tuple[str, str, str]]:
        """Получить запись по ID"""
        return await BookingRepository._execute_query(
            "SELECT date, time, username FROM bookings WHERE id=? AND user_id=?",
            (booking_id, user_id),
            fetch_one=True,
        )

    @staticmethod
    async def delete_booking(booking_id: int, user_id: int) -> bool:
        """Удалить запись"""
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
    async def cleanup_old_bookings(before_date: str) -> int:
        """Удалить старые записи"""
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
        """Получить расписание на N дней"""
        try:
            end_date = (
                datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=days)
            ).strftime("%Y-%m-%d")

            return await BookingRepository._execute_query(
                """SELECT date, time, username FROM bookings
                WHERE date >= ? AND date <= ?
                ORDER BY date, time""",
                (start_date, end_date),
                fetch_all=True,
            ) or []
        except Exception as e:
            logging.error(f"Error getting week schedule: {e}")
            return []

    @staticmethod
    async def block_slot(
        date_str: str, time_str: str, admin_id: int, reason: str = None
    ) -> bool:
        """Заблокировать слот"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "INSERT INTO blocked_slots (date, time, reason, blocked_by, blocked_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (date_str, time_str, reason, admin_id, now_local().isoformat()),
                )
                await db.commit()
                logging.info(f"Slot {date_str} {time_str} blocked by admin {admin_id}")
                return True
        except aiosqlite.IntegrityError:
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
                    (date_str, time_str),
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
    async def get_blocked_slots(date_str: str = None) -> List[Tuple]:
        """Получить заблокированные слоты"""
        if date_str:
            query = "SELECT date, time, reason FROM blocked_slots WHERE date = ? ORDER BY time"
            params = (date_str,)
        else:
            query = "SELECT date, time, reason FROM blocked_slots ORDER BY date, time"
            params = ()

        return (
            await BookingRepository._execute_query(query, params, fetch_all=True) or []
        )
