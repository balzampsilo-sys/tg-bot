"""Репозиторий для работы с аналитикой и отзывами"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiosqlite

from config import DATABASE_PATH
from database.base_repository import BaseRepository
from utils.helpers import now_local


@dataclass
class ClientStats:
    """Статистика клиента"""

    total_bookings: int
    cancelled_bookings: int
    avg_rating: float
    last_booking: Optional[str]


class AnalyticsRepository(BaseRepository):
    """Репозиторий для аналитики и отзывов"""

    @staticmethod
    async def log_event(user_id: int, event: str, data: str = ""):
        """Логирование события"""
        try:
            await AnalyticsRepository._execute_query(
                "INSERT INTO analytics (user_id, event, data, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, event, data, now_local().isoformat()),
                commit=True,
            )
        except Exception as e:
            # Не падаем, только логируем
            logging.error(f"Failed to log event {event} for user {user_id}: {e}")

    @staticmethod
    async def get_client_stats(user_id: int) -> ClientStats:
        """Статистика клиента"""
        try:
            # Всего записей
            total = await AnalyticsRepository._count(
                "analytics", "user_id=? AND event='booking_created'", (user_id,)
            )

            # Отмен
            cancelled = await AnalyticsRepository._count(
                "analytics", "user_id=? AND event='booking_cancelled'", (user_id,)
            )

            # Средний рейтинг
            avg_result = await AnalyticsRepository._execute_query(
                "SELECT AVG(rating) FROM feedback WHERE user_id=?",
                (user_id,),
                fetch_one=True,
            )
            avg_rating = avg_result[0] if avg_result and avg_result[0] else 0.0

            # Последняя запись
            last_result = await AnalyticsRepository._execute_query(
                "SELECT data FROM analytics WHERE user_id=? AND event='booking_created' "
                "ORDER BY timestamp DESC LIMIT 1",
                (user_id,),
                fetch_one=True,
            )
            last_booking = last_result[0] if last_result else None

            return ClientStats(
                total_bookings=total,
                cancelled_bookings=cancelled,
                avg_rating=avg_rating,
                last_booking=last_booking,
            )
        except Exception as e:
            logging.error(f"Error getting client stats for {user_id}: {e}")
            return ClientStats(
                total_bookings=0, cancelled_bookings=0, avg_rating=0.0, last_booking=None
            )

    @staticmethod
    async def save_feedback(user_id: int, booking_id: int, rating: int) -> bool:
        """Сохранить отзыв"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.execute(
                    "INSERT INTO feedback (user_id, booking_id, rating, timestamp) "
                    "VALUES (?, ?, ?, ?)",
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
    async def get_top_clients(limit: int = 10) -> List[Tuple]:
        """Топ клиентов по количеству записей"""
        try:
            return (
                await AnalyticsRepository._execute_query(
                    """SELECT user_id, COUNT(*) as total FROM analytics
                    WHERE event='booking_created'
                    GROUP BY user_id ORDER BY total DESC LIMIT ?""",
                    (limit,),
                    fetch_all=True,
                )
                or []
            )
        except Exception as e:
            logging.error(f"Error getting top clients: {e}")
            return []
