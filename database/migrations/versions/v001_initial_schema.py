"""Начальная схема базы данных"""

from database.migrations.migration_manager import Migration


class InitialSchema(Migration):
    version = 1
    description = "Initial database schema with all tables and indexes"
    
    async def upgrade(self, db):
        # Таблицы
        await db.execute(
            """CREATE TABLE IF NOT EXISTS bookings
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(date, time))"""
        )
        
        await db.execute(
            """CREATE TABLE IF NOT EXISTS users
            (user_id INTEGER PRIMARY KEY, first_seen TEXT NOT NULL)"""
        )
        
        await db.execute(
            """CREATE TABLE IF NOT EXISTS analytics
            (user_id INTEGER, event TEXT, data TEXT, timestamp TEXT)"""
        )
        
        await db.execute(
            """CREATE TABLE IF NOT EXISTS feedback
            (user_id INTEGER, booking_id INTEGER, rating INTEGER, timestamp TEXT)"""
        )
        
        await db.execute(
            """CREATE TABLE IF NOT EXISTS blocked_slots
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            reason TEXT,
            blocked_by INTEGER NOT NULL,
            blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, time))"""
        )
        
        await db.execute(
            """CREATE TABLE IF NOT EXISTS admin_sessions
            (user_id INTEGER PRIMARY KEY, message_id INTEGER, updated_at TEXT)"""
        )
        
        # Индексы для производительности
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date, time)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_user ON analytics(user_id, event)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_blocked_date ON blocked_slots(date, time)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_active_bookings ON bookings(user_id, date, time)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_timestamp ON analytics(timestamp)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookings_date_time ON bookings(date, time)"
        )
    
    async def downgrade(self, db):
        await db.execute("DROP TABLE IF EXISTS bookings")
        await db.execute("DROP TABLE IF EXISTS users")
        await db.execute("DROP TABLE IF EXISTS analytics")
        await db.execute("DROP TABLE IF EXISTS feedback")
        await db.execute("DROP TABLE IF EXISTS blocked_slots")
        await db.execute("DROP TABLE IF EXISTS admin_sessions")
