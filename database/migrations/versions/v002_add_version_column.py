"""Добавление колонки version для оптимистичной блокировки"""

from database.migrations.migration_manager import Migration


class AddVersionColumn(Migration):
    version = 2
    description = "Add version column for optimistic locking in bookings"
    
    async def upgrade(self, db):
        # Добавляем колонку version
        await db.execute("ALTER TABLE bookings ADD COLUMN version INTEGER DEFAULT 1")
        
        # Обновляем существующие записи
        await db.execute("UPDATE bookings SET version=1 WHERE version IS NULL")
    
    async def downgrade(self, db):
        # SQLite не поддерживает DROP COLUMN, поэтому пересоздаем таблицу
        await db.execute(
            """CREATE TABLE bookings_backup AS 
            SELECT id, date, time, user_id, username, created_at 
            FROM bookings"""
        )
        await db.execute("DROP TABLE bookings")
        await db.execute("ALTER TABLE bookings_backup RENAME TO bookings")
        
        # Восстанавливаем индексы
        await db.execute(
            "CREATE INDEX idx_bookings_date ON bookings(date, time)"
        )
        await db.execute(
            "CREATE INDEX idx_bookings_user ON bookings(user_id)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX idx_user_active_bookings ON bookings(user_id, date, time)"
        )
