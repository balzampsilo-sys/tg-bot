"""Базовый класс для всех репозиториев"""

import logging
from typing import Any, Optional

import aiosqlite

from config import DATABASE_PATH


class BaseRepository:
    """Базовый класс репозитория с общими методами"""

    @staticmethod
    async def _execute_query(
        query: str,
        params: tuple = (),
        fetch_one: bool = False,
        fetch_all: bool = False,
        commit: bool = False,
    ) -> Optional[Any]:
        """
        Универсальный метод выполнения запросов

        Args:
            query: SQL запрос
            params: Параметры запроса
            fetch_one: Вернуть одну строку
            fetch_all: Вернуть все строки
            commit: Сделать commit

        Returns:
            Результат запроса или None
        """
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(query, params) as cursor:
                    if fetch_one:
                        result = await cursor.fetchone()
                    elif fetch_all:
                        result = await cursor.fetchall()
                    else:
                        result = cursor

                if commit:
                    await db.commit()

                return result
        except Exception as e:
            logging.error(f"Database error in query '{query[:50]}...': {e}")
            return None

    @staticmethod
    async def _execute_many(query: str, params_list: list, commit: bool = True) -> bool:
        """
        Выполнить множественные INSERT/UPDATE

        Args:
            query: SQL запрос
            params_list: Список параметров
            commit: Сделать commit

        Returns:
            True если успешно
        """
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                await db.executemany(query, params_list)
                if commit:
                    await db.commit()
                return True
        except Exception as e:
            logging.error(f"Database error in executemany: {e}")
            return False

    @staticmethod
    async def _count(table: str, where: str = "", params: tuple = ()) -> int:
        """
        Подсчитать количество записей

        Args:
            table: Название таблицы
            where: WHERE условие (без WHERE)
            params: Параметры для WHERE

        Returns:
            Количество записей
        """
        where_clause = f"WHERE {where}" if where else ""
        query = f"SELECT COUNT(*) FROM {table} {where_clause}"

        result = await BaseRepository._execute_query(query, params, fetch_one=True)
        return result[0] if result else 0

    @staticmethod
    async def _exists(table: str, where: str, params: tuple) -> bool:
        """
        Проверить существование записи

        Args:
            table: Название таблицы
            where: WHERE условие (без WHERE)
            params: Параметры для WHERE

        Returns:
            True если запись существует
        """
        query = f"SELECT 1 FROM {table} WHERE {where} LIMIT 1"
        result = await BaseRepository._execute_query(query, params, fetch_one=True)
        return result is not None
