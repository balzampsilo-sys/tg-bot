"""Главный файл приложения"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN
from database.queries import Database
from handlers import admin_handlers, booking_handlers, user_handlers
from services.booking_service import BookingService
from services.notification_service import NotificationService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def main():
    """Главная функция"""
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
    await Database.init_db()

    # Сервисы
    booking_service = BookingService(scheduler, bot)
    notification_service = NotificationService(bot)

    # Регистрация сервисов для dependency injection
    dp["booking_service"] = booking_service
    dp["notification_service"] = notification_service

    # Регистрация роутеров (ВАЖЕН ПОРЯДОК!)
    dp.include_router(admin_handlers.router)      # 1. Админ первым
    dp.include_router(booking_handlers.router)    # 2. Бронирования
    dp.include_router(user_handlers.router)       # 3. Пользователи последним (есть catch-all)

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


if __name__ == "__main__":
    asyncio.run(main())
