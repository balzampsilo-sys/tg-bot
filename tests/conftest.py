"""Конфигурация pytest и общие фикстуры"""
import pytest
import asyncio
import os
import sys
from pathlib import Path

# Добавляем корневую папку в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

# Настройка тестовой БД
os.environ['DATABASE_PATH'] = './test_bookings.db'
os.environ['BOT_TOKEN'] = 'test_token_123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
os.environ['ADMIN_ID'] = '12345'


@pytest.fixture(scope="session")
def event_loop():
    """Создаем event loop для всей сессии тестирования"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def cleanup_database():
    """Автоматическая очистка БД после каждого теста"""
    yield
    
    # Очистка после теста
    import aiosqlite
    from config import DATABASE_PATH
    
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("DELETE FROM bookings")
            await db.execute("DELETE FROM users")
            await db.execute("DELETE FROM analytics")
            await db.execute("DELETE FROM feedback")
            await db.execute("DELETE FROM blocked_slots")
            await db.commit()
    except Exception as e:
        print(f"Warning: Failed to cleanup test database: {e}")


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db_on_exit():
    """Удаляем тестовую БД после всех тестов"""
    yield
    
    # Удаляем файл БД после всех тестов
    test_db_path = './test_bookings.db'
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
            print(f"\nCleaned up test database: {test_db_path}")
        except Exception as e:
            print(f"\nWarning: Could not remove test database: {e}")


class MockScheduler:
    """Мок scheduler для тестов"""
    
    def __init__(self):
        self.jobs = {}
    
    def add_job(self, func, trigger, run_date=None, args=None, id=None, replace_existing=False):
        """Mock add_job"""
        if id:
            self.jobs[id] = {
                'func': func,
                'trigger': trigger,
                'run_date': run_date,
                'args': args
            }
    
    def remove_job(self, job_id):
        """Mock remove_job"""
        if job_id in self.jobs:
            del self.jobs[job_id]


class MockBot:
    """Мок bot для тестов"""
    
    def __init__(self):
        self.sent_messages = []
    
    async def send_message(self, chat_id, text, reply_markup=None):
        """Mock send_message"""
        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup
        })
        return True


@pytest.fixture
def mock_scheduler():
    """Mock scheduler fixture"""
    return MockScheduler()


@pytest.fixture
def mock_bot():
    """Mock bot fixture"""
    return MockBot()


# Добавляем маркеры для pytest
def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as an async test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
