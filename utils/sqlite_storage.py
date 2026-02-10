"""
SQLite FSM Storage для сохранения состояний FSM
Альтернатива MemoryStorage с персистентностью
"""

import json
from typing import Dict, Any, Optional
import aiosqlite
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType


class SQLiteStorage(BaseStorage):
    """FSM storage на базе SQLite"""
    
    def __init__(self, db_path: str = "fsm_storage.db", state_ttl: int = 600, data_ttl: int = 600):
        """
        Args:
            db_path: Путь к файлу базы данных
            state_ttl: TTL для состояний (в секундах)
            data_ttl: TTL для данных (в секундах)
        """
        self.db_path = db_path
        self.state_ttl = state_ttl
        self.data_ttl = data_ttl
    
    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        """Set state for specified key"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO fsm_states (bot_id, user_id, chat_id, state, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))""",
                (key.bot_id, key.user_id, key.chat_id, state)
            )
            await db.commit()
    
    async def get_state(self, key: StorageKey) -> Optional[str]:
        """Get state for specified key"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                f"""SELECT state FROM fsm_states 
                WHERE bot_id=? AND user_id=? AND chat_id=?
                AND datetime(updated_at, '+{self.state_ttl} seconds') > datetime('now')""",
                (key.bot_id, key.user_id, key.chat_id)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else None
    
    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        """Set data for specified key"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO fsm_data (bot_id, user_id, chat_id, data, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))""",
                (key.bot_id, key.user_id, key.chat_id, json.dumps(data, ensure_ascii=False))
            )
            await db.commit()
    
    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        """Get data for specified key"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                f"""SELECT data FROM fsm_data 
                WHERE bot_id=? AND user_id=? AND chat_id=?
                AND datetime(updated_at, '+{self.data_ttl} seconds') > datetime('now')""",
                (key.bot_id, key.user_id, key.chat_id)
            ) as cursor:
                result = await cursor.fetchone()
                return json.loads(result[0]) if result else {}
    
    async def close(self) -> None:
        """Close storage (cleanup if needed)"""
        # Удаляем устаревшие записи
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"DELETE FROM fsm_states WHERE datetime(updated_at, '+{self.state_ttl} seconds') < datetime('now')"
            )
            await db.execute(
                f"DELETE FROM fsm_data WHERE datetime(updated_at, '+{self.data_ttl} seconds') < datetime('now')"
            )
            await db.commit()


async def init_fsm_storage(db_path: str = "fsm_storage.db"):
    """Инициализация схемы базы данных для FSM storage"""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS fsm_states
            (bot_id INTEGER, user_id INTEGER, chat_id INTEGER, 
             state TEXT, updated_at TEXT,
             PRIMARY KEY (bot_id, user_id, chat_id))"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS fsm_data
            (bot_id INTEGER, user_id INTEGER, chat_id INTEGER,
             data TEXT, updated_at TEXT,
             PRIMARY KEY (bot_id, user_id, chat_id))"""
        )
        
        # Индексы для производительности
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_fsm_states_updated ON fsm_states(updated_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_fsm_data_updated ON fsm_data(updated_at)"
        )
        
        await db.commit()
