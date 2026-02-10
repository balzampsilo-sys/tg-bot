"""Менеджер миграций базы данных"""

import logging
from typing import List, Type
import aiosqlite
from abc import ABC, abstractmethod


class Migration(ABC):
    """Базовый класс для миграций"""
    
    version: int
    description: str
    
    @abstractmethod
    async def upgrade(self, db: aiosqlite.Connection):
        """Применить миграцию"""
        pass
    
    @abstractmethod
    async def downgrade(self, db: aiosqlite.Connection):
        """Откатить миграцию"""
        pass


class MigrationManager:
    """Управление миграциями базы данных"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.migrations: List[Type[Migration]] = []
    
    def register(self, migration_class: Type[Migration]):
        """Регистрация миграции"""
        self.migrations.append(migration_class)
        self.migrations.sort(key=lambda m: m.version)
    
    async def init_migrations_table(self):
        """Создание таблицы миграций"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations
                (version INTEGER PRIMARY KEY,
                 description TEXT,
                 applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
            )
            await db.commit()
    
    async def get_current_version(self) -> int:
        """Получить текущую версию схемы"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result and result[0] else 0
    
    async def migrate(self, target_version: int = None):
        """Применить миграции до target_version"""
        await self.init_migrations_table()
        current = await self.get_current_version()
        target = target_version or (max(m.version for m in self.migrations) if self.migrations else 0)
        
        if current >= target:
            logging.info(f"Database already at version {current}")
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            for migration_class in self.migrations:
                if current < migration_class.version <= target:
                    migration = migration_class()
                    logging.info(f"Applying migration {migration.version}: {migration.description}")
                    
                    try:
                        await db.execute("BEGIN")
                        await migration.upgrade(db)
                        await db.execute(
                            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                            (migration.version, migration.description)
                        )
                        await db.commit()
                        logging.info(f"✅ Migration {migration.version} applied successfully")
                    except Exception as e:
                        await db.rollback()
                        logging.error(f"❌ Migration {migration.version} failed: {e}")
                        raise
    
    async def rollback(self, target_version: int):
        """Откатить миграции до target_version"""
        current = await self.get_current_version()
        
        if current <= target_version:
            logging.info(f"Nothing to rollback")
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            for migration_class in reversed(self.migrations):
                if target_version < migration_class.version <= current:
                    migration = migration_class()
                    logging.info(f"Rolling back migration {migration.version}")
                    
                    try:
                        await db.execute("BEGIN")
                        await migration.downgrade(db)
                        await db.execute(
                            "DELETE FROM schema_migrations WHERE version=?",
                            (migration.version,)
                        )
                        await db.commit()
                        logging.info(f"✅ Migration {migration.version} rolled back")
                    except Exception as e:
                        await db.rollback()
                        logging.error(f"❌ Rollback {migration.version} failed: {e}")
                        raise
