"""Репозиторий для работы с пользователями"""

import logging
from typing import List, Optional, Tuple

from database.base_repository import BaseRepository
from utils.helpers import now_local


class UserRepository(BaseRepository):
    """Репозиторий для управления пользователями"""

    @staticmethod
    async def is_new_user(user_id: int) -> bool:
        """Проверить новый ли пользователь"""
        try:
            exists = await UserRepository._exists("users", "user_id=?", (user_id,))

            if not exists:
                # Добавляем нового пользователя
                await UserRepository._execute_query(
                    "INSERT INTO users (user_id, first_seen) VALUES (?, ?)",
                    (user_id, now_local().isoformat()),
                    commit=True,
                )
                return True
            return False
        except Exception as e:
            logging.error(f"Error checking new user {user_id}: {e}")
            return False

    @staticmethod
    async def get_all_users() -> List[int]:
        """Получить список всех user_id"""
        try:
            users = await UserRepository._execute_query(
                "SELECT user_id FROM users", fetch_all=True
            )
            return [user_id for (user_id,) in users] if users else []
        except Exception as e:
            logging.error(f"Error getting all users: {e}")
            return []

    @staticmethod
    async def get_total_users_count() -> int:
        """Получить общее количество пользователей"""
        return await UserRepository._count("users")

    @staticmethod
    async def get_favorite_slots(user_id: int) -> Tuple[Optional[str], Optional[int]]:
        """Анализ предпочтений пользователя"""
        try:
            # Любимое время
            fav_time_result = await UserRepository._execute_query(
                "SELECT time, COUNT(*) as cnt FROM bookings WHERE user_id=? "
                "GROUP BY time ORDER BY cnt DESC LIMIT 1",
                (user_id,),
                fetch_one=True,
            )
            fav_time = fav_time_result[0] if fav_time_result else None

            # Любимый день недели
            fav_dow_result = await UserRepository._execute_query(
                """SELECT CAST(strftime('%w', date) AS INTEGER) as dow, COUNT(*) as cnt
                FROM bookings WHERE user_id=?
                GROUP BY dow ORDER BY cnt DESC LIMIT 1""",
                (user_id,),
                fetch_one=True,
            )
            fav_dow = int(fav_dow_result[0]) if fav_dow_result else None

            return fav_time, fav_dow
        except Exception as e:
            logging.error(f"Error getting favorite slots for {user_id}: {e}")
            return None, None
