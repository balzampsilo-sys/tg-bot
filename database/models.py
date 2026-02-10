"""Модели данных"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta


@dataclass
class Service:
    """Модель услуги/процедуры"""
    id: Optional[int]
    name: str
    description: Optional[str]
    duration_minutes: int
    price: Optional[str]
    color: str = '#4CAF50'
    is_active: bool = True
    display_order: int = 0
    created_at: Optional[datetime] = None
    
    def get_duration_display(self) -> str:
        """Отображение длительности в читаемом формате"""
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        
        if hours and minutes:
            return f"{hours} ч {minutes} мин"
        elif hours:
            return f"{hours} ч"
        else:
            return f"{minutes} мин"


@dataclass
class ScheduleSettings:
    """Настройки расписания"""
    work_hours_start: int = 9
    work_hours_end: int = 19
    max_bookings_per_day: int = 8
    updated_at: Optional[datetime] = None
    
    def get_available_hours(self) -> list[int]:
        """Получить список доступных часов"""
        return list(range(self.work_hours_start, self.work_hours_end))


@dataclass
class Booking:
    """Расширенная модель бронирования"""
    id: Optional[int]
    date: str
    time: str
    user_id: int
    username: Optional[str]
    service_id: Optional[int]
    duration_minutes: int = 60
    created_at: Optional[datetime] = None
    version: int = 1
    
    # Расширенные поля (загружаются из JOIN)
    service_name: Optional[str] = None
    service_color: Optional[str] = None
    service_price: Optional[str] = None
