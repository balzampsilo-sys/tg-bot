"""Модели данных"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Booking:
    """Модель записи"""
    id: int
    date: str
    time: str
    user_id: int
    username: str
    created_at: str


@dataclass
class User:
    """Модель пользователя"""
    user_id: int
    first_seen: str


@dataclass
class BlockedSlot:
    """Модель заблокированного слота"""
    id: int
    date: str
    time: str
    reason: str
    created_by: int
    created_at: str


@dataclass
class ClientStats:
    """Статистика клиента"""
    total_bookings: int
    cancelled_bookings: int
    avg_rating: float
    last_booking: Optional[str]
