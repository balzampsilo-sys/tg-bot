"""Конфигурация pytest и общие фикстуры"""
import pytest
import os
import sys
from pathlib import Path

# Добавляем корневую папку в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

# Настройка тестовой БД
os.environ['DATABASE_PATH'] = './test_bookings.db'
os.environ['BOT_TOKEN'] = 'test_token_123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
os.environ['ADMIN_ID'] = '12345'


@pytest.fixture(autouse=True)
async def cleanup_database():
    """Автоматическая очистка БД после каждого теста"""
    yield
    
    # Очистка после теста
    import aiosqlite
    from config import DATABASE_PATH
    
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Очищаем все таблицы
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
    
    # Удаляем файл БД после всех тестов
    test_db_path = './test_bookings.db'
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
            print(f"\n✅ Cleaned up test database: {test_db_path}")
        except Exception as e:
            print(f"\n⚠️  Warning: Could not remove test database: {e}")


class MockScheduler:
    """Мок scheduler для тестов"""
    
    def __init__(self):
        self.jobs = {}
    
    def add_job(self, func, trigger, run_date=None, args=None, id=None, replace_existing=False):
        """Мок add_job"""
        if id:
            self.jobs[id] = {
                'func': func,
                'trigger': trigger,
                'run_date': run_date,
                'args': args
            }
        return self  # Возвращаем self для совместимости
    
    def remove_job(self, job_id):
        """Мок remove_job"""
        if job_id in self.jobs:
            del self.jobs[job_id]
    
    def get_job(self, job_id):
        """Мок get_job"""
        return self.jobs.get(job_id)
    
    def get_jobs(self):
        """Мок get_jobs"""
        return list(self.jobs.values())


class MockBot:
    """Мок bot для тестов"""
    
    def __init__(self):
        self.sent_messages = []
        self.sent_documents = []
    
    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        """Мок send_message"""
        message = {
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup,
            'parse_mode': parse_mode
        }
        self.sent_messages.append(message)
        return message
    
    async def send_document(self, chat_id, document, caption=None):
        """Мок send_document"""
        doc = {
            'chat_id': chat_id,
            'document': document,
            'caption': caption
        }
        self.sent_documents.append(doc)
        return doc
    
    def clear_history(self):
        """Очистить историю сообщений"""
        self.sent_messages.clear()
        self.sent_documents.clear()


@pytest.fixture
def mock_scheduler():
    """Фикстура mock scheduler"""
    return MockScheduler()


@pytest.fixture
def mock_bot():
    """Фикстура mock bot"""
    return MockBot()


# Добавляем маркеры для pytest
def pytest_configure(config):
    """Регистрация пользовательских маркеров"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as an async test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )


def pytest_collection_modifyitems(items):
    """Автоматическое добавление маркера asyncio к async тестам"""
    for item in items:
        if 'asyncio' in item.keywords:
            item.add_marker(pytest.mark.asyncio)
