"""Миграция: Добавление услуг с обратной совместимостью"""

from database.migrations.migration_manager import Migration


class AddServicesBackwardCompatible(Migration):
    version = 4
    description = "Add services and schedule settings with backward compatibility"
    
    async def upgrade(self, db):
        """Применение миграции"""
        # Создаем таблицу услуг
        await db.execute(
            """CREATE TABLE IF NOT EXISTS services
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             name TEXT NOT NULL,
             description TEXT,
             duration_minutes INTEGER NOT NULL,
             price TEXT,
             color TEXT DEFAULT '#4CAF50',
             is_active BOOLEAN DEFAULT 1,
             display_order INTEGER DEFAULT 0,
             created_at TEXT DEFAULT CURRENT_TIMESTAMP,
             UNIQUE(name))"""
        )
        
        # Создаем таблицу настроек расписания
        await db.execute(
            """CREATE TABLE IF NOT EXISTS schedule_settings
            (id INTEGER PRIMARY KEY CHECK (id = 1),
             work_hours_start INTEGER DEFAULT 9,
             work_hours_end INTEGER DEFAULT 19,
             max_bookings_per_day INTEGER DEFAULT 8,
             updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )
        
        # Индексы
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_services_active ON services(is_active, display_order)"
        )
        
        # Вставляем дефолтные настройки из config
        await db.execute(
            """INSERT OR IGNORE INTO schedule_settings (id, work_hours_start, work_hours_end)
            VALUES (1, 9, 19)"""
        )
        
        # Проверяем есть ли уже колонки service_id и duration_minutes
        async with db.execute("PRAGMA table_info(bookings)") as cursor:
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
        
        # Добавляем колонки если их еще нет
        if 'service_id' not in column_names:
            await db.execute("ALTER TABLE bookings ADD COLUMN service_id INTEGER")
        
        if 'duration_minutes' not in column_names:
            await db.execute("ALTER TABLE bookings ADD COLUMN duration_minutes INTEGER DEFAULT 60")
        
        # Добавляем индекс на service_id
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookings_service ON bookings(service_id)"
        )
        
        # Вставляем дефолтную услугу
        await db.execute(
            """INSERT OR IGNORE INTO services (name, description, duration_minutes, price, display_order)
            VALUES ('Консультация', 'Стандартная консультация', 60, '3000 ₽', 1)"""
        )
        
        # Обновляем существующие записи
        await db.execute(
            """UPDATE bookings 
            SET service_id = (SELECT id FROM services WHERE name='Консультация'),
                duration_minutes = 60
            WHERE service_id IS NULL"""
        )
    
    async def downgrade(self, db):
        """Откат миграции"""
        # Удаляем таблицы
        await db.execute("DROP TABLE IF EXISTS services")
        await db.execute("DROP TABLE IF EXISTS schedule_settings")
        
        # SQLite не поддерживает DROP COLUMN, поэтому пересоздаем таблицу
        await db.execute(
            """CREATE TABLE bookings_backup AS 
            SELECT id, date, time, user_id, username, created_at, version 
            FROM bookings"""
        )
        await db.execute("DROP TABLE bookings")
        await db.execute("ALTER TABLE bookings_backup RENAME TO bookings")
        
        # Восстанавливаем индексы
        await db.execute(
            "CREATE UNIQUE INDEX idx_bookings_date_time ON bookings(date, time)"
        )
