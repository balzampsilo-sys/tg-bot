"""Конфигурация pytest и общие фикстуры для всех тестов

Этот файл содержит:
- Настройку тестовой среды
- Mock объекты для aiogram (Bot, Message, CallbackQuery)
- Фикстуры для БД
- Фикстуры для сервисов
- Автоматическую очистку после тестов
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    User,
)

# Добавляем корневую папку в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

# ============================================================================
# НАСТРОЙКА ТЕСТОВОЙ СРЕДЫ
# ============================================================================

# Настройка переменных окружения ДО импорта config
os.environ["DATABASE_PATH"] = "./test_bookings.db"
os.environ["BOT_TOKEN"] = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz12345678"
os.environ["ADMIN_ID"] = "12345"

# Теперь можно импортировать модули проекта
from config import DATABASE_PATH, TIMEZONE  # noqa: E402
from database.queries import Database  # noqa: E402
from services.booking_service import BookingService  # noqa: E402
from utils.helpers import now_local  # noqa: E402


# ============================================================================
# PYTEST КОНФИГУРАЦИЯ
# ============================================================================


def pytest_configure(config):
    """Регистрация пользовательских маркеров"""
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "integration: integration test")
    config.addinivalue_line("markers", "unit: unit test")
    config.addinivalue_line("markers", "security: security test")


def pytest_collection_modifyitems(items):
    """Автоматическое добавление маркера asyncio к async тестам"""
    for item in items:
        if "asyncio" in item.keywords:
            item.add_marker(pytest.mark.asyncio)


# ============================================================================
# ОЧИСТКА БД
# ============================================================================


@pytest.fixture(autouse=True)
async def cleanup_database():
    """Автоматическая очистка БД после каждого теста"""
    yield

    # Очистка после теста
    import aiosqlite

    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("DELETE FROM bookings")
            await db.execute("DELETE FROM users")
            await db.execute("DELETE FROM analytics")
            await db.execute("DELETE FROM feedback")
            await db.execute("DELETE FROM blocked_slots")
            await db.execute("DELETE FROM admin_sessions")
            await db.commit()
    except Exception as e:
        print(f"Warning: Failed to cleanup test database: {e}")


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db_on_exit():
    """Удаляем тестовую БД после всех тестов"""
    yield

    if os.path.exists(DATABASE_PATH):
        try:
            os.remove(DATABASE_PATH)
            print(f"\n✅ Cleaned up test database: {DATABASE_PATH}")
        except Exception as e:
            print(f"\n⚠️  Warning: Could not remove test database: {e}")


@pytest.fixture
async def init_database():
    """Инициализация тестовой БД"""
    await Database.init_db()
    yield


# ============================================================================
# MOCK SCHEDULER
# ============================================================================


class MockScheduler:
    """Mock APScheduler для тестов"""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.job_history: List[Dict[str, Any]] = []

    def add_job(
        self,
        func,
        trigger,
        run_date=None,
        args=None,
        kwargs=None,
        id=None,
        replace_existing=False,
    ):
        """Мок add_job"""
        if id:
            if id in self.jobs and not replace_existing:
                raise Exception(f"Job {id} already exists")

            self.jobs[id] = {
                "func": func,
                "trigger": trigger,
                "run_date": run_date,
                "args": args or [],
                "kwargs": kwargs or {},
            }
            self.job_history.append({"action": "add", "id": id})
        return Mock()

    def remove_job(self, job_id: str):
        """Мок remove_job"""
        if job_id in self.jobs:
            del self.jobs[job_id]
            self.job_history.append({"action": "remove", "id": job_id})
        else:
            raise Exception(f"Job {job_id} not found")

    def get_job(self, job_id: str):
        """Мок get_job"""
        return self.jobs.get(job_id)

    def get_jobs(self) -> List:
        """Мок get_jobs"""
        return list(self.jobs.values())

    def shutdown(self, wait=True):
        """Мок shutdown"""
        self.jobs.clear()

    def clear_history(self):
        """Очистить историю для тестов"""
        self.job_history.clear()


@pytest.fixture
def mock_scheduler():
    """Фикстура mock scheduler"""
    return MockScheduler()


# ============================================================================
# MOCK BOT
# ============================================================================


class MockBot:
    """Mock Telegram Bot для тестов"""

    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self.sent_documents: List[Dict[str, Any]] = []
        self.edited_messages: List[Dict[str, Any]] = []
        self.deleted_messages: List[int] = []
        self.session = Mock()
        self.session.close = AsyncMock()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup=None,
        parse_mode=None,
        **kwargs,
    ):
        """Мок send_message"""
        message_data = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
            **kwargs,
        }
        self.sent_messages.append(message_data)

        # Создаем mock объект Message для возврата
        message = Mock(spec=Message)
        message.message_id = len(self.sent_messages)
        message.text = text
        message.chat = Mock(spec=Chat)
        message.chat.id = chat_id
        return message

    async def send_document(
        self, chat_id: int, document, caption=None, **kwargs
    ):
        """Мок send_document"""
        doc_data = {
            "chat_id": chat_id,
            "document": document,
            "caption": caption,
            **kwargs,
        }
        self.sent_documents.append(doc_data)
        return Mock()

    async def edit_message_text(
        self, text: str, chat_id: int, message_id: int, reply_markup=None, **kwargs
    ):
        """Мок edit_message_text"""
        edit_data = {
            "text": text,
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
            **kwargs,
        }
        self.edited_messages.append(edit_data)
        return Mock()

    async def delete_message(self, chat_id: int, message_id: int):
        """Мок delete_message"""
        self.deleted_messages.append(message_id)
        return True

    def clear_history(self):
        """Очистить историю для тестов"""
        self.sent_messages.clear()
        self.sent_documents.clear()
        self.edited_messages.clear()
        self.deleted_messages.clear()


@pytest.fixture
def mock_bot():
    """Фикстура mock bot"""
    return MockBot()


# ============================================================================
# MOCK AIOGRAM OBJECTS
# ============================================================================


@pytest.fixture
def mock_user():
    """Создание mock User"""

    def _create_user(
        user_id: int = 12345,
        username: str = "testuser",
        first_name: str = "Test",
        is_bot: bool = False,
    ) -> User:
        user = Mock(spec=User)
        user.id = user_id
        user.username = username
        user.first_name = first_name
        user.is_bot = is_bot
        user.last_name = None
        user.language_code = "ru"
        return user

    return _create_user


@pytest.fixture
def mock_chat():
    """Создание mock Chat"""

    def _create_chat(chat_id: int = 12345, chat_type: str = "private") -> Chat:
        chat = Mock(spec=Chat)
        chat.id = chat_id
        chat.type = chat_type
        return chat

    return _create_chat


@pytest.fixture
def mock_message(mock_user, mock_chat):
    """Создание mock Message"""

    def _create_message(
        text: str = "/start",
        user_id: int = 12345,
        username: str = "testuser",
        chat_id: int = 12345,
    ) -> Message:
        message = Mock(spec=Message)
        message.text = text
        message.message_id = 1
        message.date = datetime.now()
        message.from_user = mock_user(user_id=user_id, username=username)
        message.chat = mock_chat(chat_id=chat_id)

        # Mock методы
        message.answer = AsyncMock(return_value=Mock(spec=Message))
        message.edit_text = AsyncMock()
        message.delete = AsyncMock()
        message.reply = AsyncMock(return_value=Mock(spec=Message))

        return message

    return _create_message


@pytest.fixture
def mock_callback_query(mock_user, mock_message):
    """Создание mock CallbackQuery"""

    def _create_callback(
        data: str = "test",
        user_id: int = 12345,
        username: str = "testuser",
        message_text: str = "Test message",
    ) -> CallbackQuery:
        callback = Mock(spec=CallbackQuery)
        callback.id = "callback_id_123"
        callback.data = data
        callback.from_user = mock_user(user_id=user_id, username=username)
        callback.message = mock_message(text=message_text, user_id=user_id)

        # Mock методы
        callback.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        callback.message.answer = AsyncMock(return_value=Mock(spec=Message))
        callback.message.delete = AsyncMock()

        return callback

    return _create_callback


@pytest.fixture
async def mock_state():
    """Создание mock FSMContext"""
    storage = MemoryStorage()
    bot = Mock(spec=Bot)
    bot.id = 123456789

    state = FSMContext(
        storage=storage, key={"bot_id": bot.id, "chat_id": 12345, "user_id": 12345}
    )

    yield state

    # Очистка
    await state.clear()


# ============================================================================
# SERVICE FIXTURES
# ============================================================================


@pytest.fixture
async def booking_service(mock_scheduler, mock_bot):
    """Фикстура BookingService"""
    service = BookingService(mock_scheduler, mock_bot)
    return service


# ============================================================================
# HELPER FIXTURES
# ============================================================================


@pytest.fixture
def tomorrow_date():
    """Завтрашняя дата в формате YYYY-MM-DD"""
    return (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture
def next_week_date():
    """Дата через неделю"""
    return (now_local() + timedelta(days=7)).strftime("%Y-%m-%d")


@pytest.fixture
def yesterday_date():
    """Вчерашняя дата"""
    return (now_local() - timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture
def test_user_data():
    """Тестовые данные пользователя"""
    return {
        "user_id": 12345,
        "username": "testuser",
        "first_name": "Test",
        "time_slot": "10:00",
    }


@pytest.fixture
def admin_user_data():
    """Данные админа"""
    return {
        "user_id": 12345,  # Совпадает с ADMIN_ID в env
        "username": "admin",
        "first_name": "Admin",
    }


# ============================================================================
# DATABASE HELPER FIXTURES
# ============================================================================


@pytest.fixture
async def create_test_booking(init_database, tomorrow_date):
    """Создание тестовой записи в БД"""

    async def _create(
        date_str: str = None,
        time_str: str = "10:00",
        user_id: int = 12345,
        username: str = "testuser",
    ) -> int:
        """Возвращает booking_id"""
        import aiosqlite

        date_str = date_str or tomorrow_date

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO bookings (date, time, user_id, username, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (date_str, time_str, user_id, username, now_local().isoformat()),
            )
            booking_id = cursor.lastrowid
            await db.commit()

        return booking_id

    return _create


@pytest.fixture
async def create_test_user(init_database):
    """Создание тестового пользователя в БД"""

    async def _create(user_id: int = 12345, username: str = "testuser"):
        import aiosqlite

        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, username, first_seen) VALUES (?, ?, ?)",
                (user_id, username, now_local().isoformat()),
            )
            await db.commit()

    return _create


# ============================================================================
# ASSERTION HELPERS
# ============================================================================


@pytest.fixture
def assert_message_sent(mock_bot):
    """Проверка что сообщение было отправлено"""

    def _assert(text_contains: str = None, chat_id: int = None):
        messages = mock_bot.sent_messages
        assert len(messages) > 0, "No messages sent"

        if text_contains:
            found = any(text_contains in msg["text"] for msg in messages)
            assert found, f"No message contains '{text_contains}'"

        if chat_id:
            found = any(msg["chat_id"] == chat_id for msg in messages)
            assert found, f"No message sent to chat_id {chat_id}"

    return _assert


@pytest.fixture
def assert_job_scheduled(mock_scheduler):
    """Проверка что job запланирован"""

    def _assert(job_id: str):
        job = mock_scheduler.get_job(job_id)
        assert job is not None, f"Job '{job_id}' not scheduled"
        return job

    return _assert


print("✅ conftest.py loaded successfully")
