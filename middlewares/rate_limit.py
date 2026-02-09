"""Мидлварь для ограничения частоты запросов"""

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from cachetools import TTLCache


class RateLimitMiddleware(BaseMiddleware):
    """Мидлварь для защиты от спама"""

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
