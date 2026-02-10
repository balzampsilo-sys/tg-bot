"""Утилиты для работы с датами и временем"""

from datetime import datetime, date, timedelta
from typing import Optional
import pytz
from config import TIMEZONE


def now_local() -> datetime:
    """Текущее время в timezone приложения (aware)"""
    return datetime.now(TIMEZONE)


def localize_datetime(dt: datetime) -> datetime:
    """Безопасная локализация datetime с учетом DST
    
    Args:
        dt: Наивный datetime объект
        
    Returns:
        Aware datetime в TIMEZONE приложения
    """
    if dt.tzinfo is not None:
        # Уже aware - конвертируем в нужную зону
        return dt.astimezone(TIMEZONE)
    
    # Используем is_dst=None чтобы получить исключение при неоднозначности
    try:
        return TIMEZONE.localize(dt, is_dst=None)
    except pytz.exceptions.AmbiguousTimeError:
        # Время попадает на переход часов - используем стандартное время
        return TIMEZONE.localize(dt, is_dst=False)
    except pytz.exceptions.NonExistentTimeError:
        # Время не существует (пропущено при переходе) - сдвигаем на час вперед
        return TIMEZONE.localize(dt + timedelta(hours=1), is_dst=True)


def parse_datetime(date_str: str, time_str: str) -> datetime:
    """Парсинг даты и времени в aware datetime
    
    Args:
        date_str: Дата в формате YYYY-MM-DD
        time_str: Время в формате HH:MM
        
    Returns:
        Aware datetime объект
    """
    naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return localize_datetime(naive_dt)


def format_datetime(dt: datetime, format_str: str = "%d.%m.%Y %H:%M") -> str:
    """Форматирование datetime с учетом timezone
    
    Args:
        dt: Datetime объект (может быть naive или aware)
        format_str: Формат вывода
        
    Returns:
        Отформатированная строка
    """
    if dt.tzinfo is None:
        dt = localize_datetime(dt)
    else:
        dt = dt.astimezone(TIMEZONE)
    
    return dt.strftime(format_str)


def get_date_range(start_date: date, days: int) -> list:
    """Генерация диапазона дат
    
    Args:
        start_date: Начальная дата
        days: Количество дней
        
    Returns:
        Список дат
    """
    return [start_date + timedelta(days=i) for i in range(days)]


def is_business_hours(dt: datetime, start_hour: int, end_hour: int) -> bool:
    """Проверка попадания в рабочие часы
    
    Args:
        dt: Проверяемое время
        start_hour: Начало рабочего дня
        end_hour: Конец рабочего дня
        
    Returns:
        True если попадает в рабочие часы
    """
    if dt.tzinfo is None:
        dt = localize_datetime(dt)
    else:
        dt = dt.astimezone(TIMEZONE)
    
    return start_hour <= dt.hour < end_hour


def to_utc(dt: datetime) -> datetime:
    """Конвертация в UTC для хранения в БД
    
    Args:
        dt: Локальное время
        
    Returns:
        UTC datetime
    """
    if dt.tzinfo is None:
        dt = localize_datetime(dt)
    return dt.astimezone(pytz.UTC)


def from_utc(dt: datetime) -> datetime:
    """Конвертация из UTC в локальное время
    
    Args:
        dt: UTC datetime
        
    Returns:
        Локальное aware datetime
    """
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(TIMEZONE)
