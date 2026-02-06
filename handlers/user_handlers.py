"""Обработчики пользовательских команд"""
import asyncio
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.queries import Database
from keyboards.user_keyboards import MAIN_MENU, create_onboarding_keyboard
from config import SERVICE_DURATION, SERVICE_PRICE, SERVICE_LOCATION, CANCELLATION_HOURS, MAX_BOOKINGS_PER_USER

router = Router()


@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    """Команда /start с онбордингом"""
    await state.clear()
    user_id = message.from_user.id
    is_new = await Database.is_new_user(user_id)
    
    if is_new:
        await Database.log_event(user_id, "user_registered")
        
        # Приветствие
        await message.answer(
            "👋 Добро пожаловать в систему онлайн-записи!\n\n"
            "🎯 Записаться на удобное время — всего 3 клика"
        )
        await asyncio.sleep(1)
        
        # Преимущества
        await message.answer(
            "✨ ЧТО Я УМЕЮ:\n\n"
            "📅 Запись за 30 секунд\n"
            "🔄 Перенос в 2 клика\n"
            "⏰ Напоминания за 24ч\n"
            "⭐ 4.8/5 на основе 247 отзывов\n\n"
            "📋 ИНФОРМАЦИЯ:\n"
            f"⏱ Длительность: {SERVICE_DURATION}\n"
            f"💰 Стоимость: {SERVICE_PRICE}\n"
            f"📍 Место: {SERVICE_LOCATION}"
        )
        await asyncio.sleep(1)
        
        # Интерактивный выбор
        await message.answer(
            "Хотите быстрый обзор или сразу запишемся?",
            reply_markup=create_onboarding_keyboard()
        )
    else:
        # Для вернувшихся
        stats = await Database.get_client_stats(user_id)
        if stats.total_bookings >= 5:
            await message.answer(
                f"С возвращением! 🎉\n\n"
                f"Вы уже {stats.total_bookings} раз с нами.\n"
                f"Средний рейтинг ваших отзывов: {stats.avg_rating:.1f}⭐\n\n"
                f"Спасибо за доверие!",
                reply_markup=MAIN_MENU
            )
        else:
            await message.answer(
                "С возвращением! 👋\n\nВыберите действие:",
                reply_markup=MAIN_MENU
            )


@router.callback_query(F.data == "onboarding_tour")
async def onboarding_tour(callback: CallbackQuery, state: FSMContext):
    """Интерактивный туториал"""
    await state.clear()
    await callback.message.edit_text(
        "🎓 КАК ЭТО РАБОТАЕТ\n\n"
        "1️⃣ Выбираете дату в календаре\n"
        "   🟢 = много мест\n"
        "   🟡 = есть места\n"
        "   🔴 = всё занято\n\n"
        "2️⃣ Выбираете удобное время\n"
        "   (09:00 - 19:00)\n\n"
        "3️⃣ Подтверждаете — готово!\n"
        "   Вам придёт напоминание за 24ч\n\n"
        "💡 Можно иметь до 3 записей одновременно"
    )
    await asyncio.sleep(4)
    await callback.message.answer(
        "Всё понятно? Попробуем! 🚀",
        reply_markup=MAIN_MENU
    )
    await callback.answer()


@router.callback_query(F.data == "skip_onboarding")
async def skip_onboarding(callback: CallbackQuery, state: FSMContext):
    """Пропуск онбординга"""
    await state.clear()
    await callback.message.edit_text("Отлично! Давайте запишем вас 📅")
    await callback.message.answer(
        "Выберите действие:",
        reply_markup=MAIN_MENU
    )
    await callback.answer()


@router.message(F.text == "ℹ️ О сервисе")
async def about_service(message: Message):
    """Информация о сервисе"""
    await message.answer(
        "ℹ️ ИНФОРМАЦИЯ О УСЛУГЕ\n\n"
        f"⏱ Длительность: {SERVICE_DURATION}\n"
        f"📍 Место: {SERVICE_LOCATION}\n"
        f"💰 Стоимость: {SERVICE_PRICE}\n\n"
        f"🔔 Напоминание за {CANCELLATION_HOURS}ч до встречи\n"
        f"❌ Отмена возможна за {CANCELLATION_HOURS}ч\n"
        f"📊 Лимит одновременных записей: {MAX_BOOKINGS_PER_USER}",
        reply_markup=MAIN_MENU
    )


@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    """Игнорирование callback"""
    await callback.answer()
