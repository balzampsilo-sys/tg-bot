"""Репозиторий для работы с услугами"""

import logging
from typing import List, Optional
import aiosqlite
from config import DATABASE_PATH
from database.models import Service, ScheduleSettings
from utils.helpers import now_local


class ServiceRepository:
    """Репозиторий для услуг"""
    
    @staticmethod
    async def get_all_services(active_only: bool = True) -> List[Service]:
        """Получить все услуги"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            query = """SELECT * FROM services 
                      WHERE is_active=1 
                      ORDER BY display_order, name""" if active_only else \
                    """SELECT * FROM services 
                      ORDER BY display_order, name"""
            
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [Service(
                    id=row['id'],
                    name=row['name'],
                    description=row['description'],
                    duration_minutes=row['duration_minutes'],
                    price=row['price'],
                    color=row['color'],
                    is_active=bool(row['is_active']),
                    display_order=row['display_order']
                ) for row in rows]
    
    @staticmethod
    async def get_service_by_id(service_id: int) -> Optional[Service]:
        """Получить услугу по ID"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM services WHERE id=?",
                (service_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                
                return Service(
                    id=row['id'],
                    name=row['name'],
                    description=row['description'],
                    duration_minutes=row['duration_minutes'],
                    price=row['price'],
                    color=row['color'],
                    is_active=bool(row['is_active']),
                    display_order=row['display_order']
                )
    
    @staticmethod
    async def create_service(service: Service) -> int:
        """Создать новую услугу"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO services 
                (name, description, duration_minutes, price, color, display_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (service.name, service.description, service.duration_minutes,
                 service.price, service.color, service.display_order, service.is_active)
            )
            await db.commit()
            return cursor.lastrowid
    
    @staticmethod
    async def update_service(service_id: int, service: Service) -> bool:
        """Обновить услугу"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """UPDATE services 
                SET name=?, description=?, duration_minutes=?, price=?, 
                    color=?, display_order=?, is_active=?
                WHERE id=?""",
                (service.name, service.description, service.duration_minutes,
                 service.price, service.color, service.display_order, 
                 service.is_active, service_id)
            )
            await db.commit()
            return cursor.rowcount > 0
    
    @staticmethod
    async def delete_service(service_id: int) -> bool:
        """Удалить услугу (мягкое удаление)"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "UPDATE services SET is_active=0 WHERE id=?",
                (service_id,)
            )
            await db.commit()
            return cursor.rowcount > 0


class ScheduleSettingsRepository:
    """Репозиторий для настроек расписания"""
    
    @staticmethod
    async def get_settings() -> ScheduleSettings:
        """Получить настройки расписания"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM schedule_settings WHERE id=1"
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    # Возвращаем настройки по умолчанию
                    return ScheduleSettings()
                
                return ScheduleSettings(
                    work_hours_start=row['work_hours_start'],
                    work_hours_end=row['work_hours_end'],
                    max_bookings_per_day=row['max_bookings_per_day']
                )
    
    @staticmethod
    async def update_settings(settings: ScheduleSettings) -> bool:
        """Обновить настройки расписания"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """INSERT OR REPLACE INTO schedule_settings 
                (id, work_hours_start, work_hours_end, max_bookings_per_day, updated_at)
                VALUES (1, ?, ?, ?, ?)""",
                (settings.work_hours_start, settings.work_hours_end,
                 settings.max_bookings_per_day, now_local().isoformat())
            )
            await db.commit()
            return cursor.rowcount > 0
