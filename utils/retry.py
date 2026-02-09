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
