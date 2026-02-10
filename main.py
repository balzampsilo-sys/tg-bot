"""Главный файл приложения"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, DATABASE_PATH
from database.queries import Database
from database.migrations.migration_manager import MigrationManager
from database.migrations.versions.v004_add_services import AddServicesBackwardCompatible
from handlers import admin_handlers, booking_handlers, user_handlers
from middlewares.rate_limit import RateLimitMiddleware
from services.booking_service import BookingService
from services.notification_service import NotificationService
from utils.retry import async_retry

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def init_database():
    """Инициализация БД с миграциями"""
    # Сначала создаем базовую структуру (если еще не создана)
    await Database.init_db()
    
    # Затем применяем миграции
    manager = MigrationManager(DATABASE_PATH)
    
    # Регистрируем миграции
    manager.register(AddServicesBackwardCompatible)
    
    # Применяем миграции
    await manager.migrate()
    
    logging.info("✅ Database initialized with migrations")


@async_retry(
    max_attempts=5,
    delay=2.0,
    backoff=2.0,
    exceptions=(TelegramNetworkError, TelegramRetryAfter, ConnectionError)
)
async def start_bot():
    """Запуск бота с retry логикой"""
    # Инициализация
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Настройка планировщика с одним исполнителем
    scheduler = AsyncIOScheduler(
        jobstores={},
        executors={
            'default': {'type': 'threadpool', 'max_workers': 1}
        },
        job_defaults={
            'coalesce': False,
            'max_instances': 1
        }
    )

    # Инициализация БД
    await init_database()

    # Сервисы
    booking_service = BookingService(scheduler, bot)
    notification_service = NotificationService(bot)

    # Регистрация сервисов для dependency injection
    dp["booking_service"] = booking_service
    dp["notification_service"] = notification_service

    # Rate limiting middleware
    dp.message.middleware(RateLimitMiddleware(rate_limit=0.5))  # 0.5 сек между сообщениями
    dp.callback_query.middleware(RateLimitMiddleware(rate_limit=0.3))  # 0.3 сек между callback

    # Регистрация роутеров (ВАЖЕН ПОРЯДОК!)
    dp.include_router(admin_handlers.router)      # 1. Админ первым
    dp.include_router(booking_handlers.router)    # 2. Бронирования
    dp.include_router(user_handlers.router)       # 3. Пользователи последним (catch-all)

    # Восстановление напоминаний
    await booking_service.restore_reminders()

    # Запуск планировщика
    scheduler.start()

    logging.info("🚀 Bot started")

    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()
        scheduler.shutdown()


async def main():
    """Главная функция с обработкой критических ошибок"""
    try:
        await start_bot()
    except Exception as e:
        logging.critical(f"Bot crashed with critical error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
