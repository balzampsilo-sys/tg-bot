"""Обработчики бронирования"""
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database.queries import Database
from keyboards.user_keyboards import (
    MAIN_MENU, 
    create_month_calendar, 
    create_time_slots,
    create_confirmation_keyboard,
    create_cancel_confirmation_keyboard
)
from services.booking_service import BookingService
from services.notification_service import NotificationService
from utils.helpers import now_local
from config import (
    SERVICE_DURATION, 
    SERVICE_LOCATION, 
    SERVICE_PRICE,
    MAX_BOOKINGS_PER_USER,
    CANCELLATION_HOURS,
    DAY_NAMES
)

router = Router()


@router.message(F.text == "📅 Записаться")
async def booking_start(message: Message, state: FSMContext):
    """Начало процесса записи"""
    await state.clear()
    await Database.log_event(message.from_user.id, "booking_started")
    
    can_book, current_count = await Database.can_user_book(message.from_user.id)
    
    if not can_book:
        await message.answer(
            f"⚠️ У вас уже {MAX_BOOKINGS_PER_USER} активных записи.\n\n"
            "Отмените одну из них, чтобы записаться снова.\n"
            "📋 Мои записи → выберите запись для отмены",
            reply_markup=MAIN_MENU
        )
        return
    
    today = now_local()
    kb = await create_month_calendar(today.year, today.month)
    
    await message.answer(
        "📍 ШАГ 1 из 3: Выберите дату\n\n"
        "🟢 = все слоты свободны\n"
        "🟡 = есть свободные слоты\n"
        "🔴 = все занято\n"
        "⚫ = прошедшая дата\n\n"
        f"📊 Ваших записей: {current_count}/{MAX_BOOKINGS_PER_USER}",
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("cal:"))
async def month_nav(callback: CallbackQuery):
    """Навигация по месяцам"""
    if callback.data == "ignore":
        await callback.answer()
        return
    
    await callback.answer("⏳ Загружаю...")
    
    _, year_month = callback.data.split(":", 1)
    year, month = map(int, year_month.split("-"))
    
    kb = await create_month_calendar(year, month)
    
    try:
        await callback.message.edit_text(
            "📍 ШАГ 1 из 3: Выберите дату\n\n"
            "🟢🟡🔴⚫ — статус дня",
            reply_markup=kb
        )
    except:
        await callback.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("day:"))
async def select_day(callback: CallbackQuery, state: FSMContext):
    """Выбор дня"""
    await callback.answer("⏳ Загружаю слоты...")
    
    date_str = callback.data.split(":", 1)[1]
    text, kb = await create_time_slots(date_str, state)
    
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("time:"))
async def confirm_time(callback: CallbackQuery):
    """Подтверждение времени"""
    _, date_str, time_str = callback.data.split(":", 2)
    
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_name = DAY_NAMES[date_obj.weekday()]
    
    confirm_kb = create_confirmation_keyboard(date_str, time_str)
    
    await callback.message.edit_text(
        f"📍 ШАГ 3 из 3: Подтверждение\n\n"
        f"📅 {date_obj.strftime('%d.%m.%Y')} ({day_name})\n"
        f"🕒 {time_str}\n\n"
        f"✅ Подтвердить?",
        reply_markup=confirm_kb
    )


@router.callback_query(F.data == "cancel_booking_flow")
async def cancel_booking_flow(callback: CallbackQuery, state: FSMContext):
    """Отмена процесса бронирования"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Запись отменена\n\nВы вернулись в главное меню",
        reply_markup=None
    )
    await callback.answer("Действие отменено")


@router.callback_query(F.data.startswith("confirm:"))
async def book_time(callback: CallbackQuery, booking_service: BookingService, notification_service: NotificationService):
    """Финальное бронирование"""
    _, date_str, time_str = callback.data.split(":", 2)
    
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or "Гость"
    
    can_book, _ = await Database.can_user_book(user_id)
    if not can_book:
        await callback.answer(f"❌ У вас уже {MAX_BOOKINGS_PER_USER} активных записи!", show_alert=True)
        return
    
    success = await booking_service.create_booking(date_str, time_str, user_id, username)
    
    if success:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        
        await callback.message.edit_text(
            f"✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!\n\n"
            f"📅 {date_obj.strftime('%d.%m.%Y')} ({DAY_NAMES[date_obj.weekday()]})\n"
            f"🕒 {time_str}\n"
            f"⏱ {SERVICE_DURATION}\n"
            f"📍 {SERVICE_LOCATION}\n"
            f"💰 {SERVICE_PRICE}\n\n"
            f"⏰ Напоминание за 24 часа\n"
            f"📋 'Мои записи' — посмотреть все"
        )
        await callback.answer("✅ Запись создана!", show_alert=False)
        
        # Уведомить админа
        await notification_service.notify_admin_new_booking(date_str, time_str, user_id, username)
    else:
        await callback.answer("❌ Этот слот уже занят!", show_alert=True)
        text, kb = await create_time_slots(date_str)
        await callback.message.edit_text(
            f"❌ Слот {time_str} уже занят!\n\nВыберите другое время:",
            reply_markup=kb
        )


@router.callback_query(F.data == "back_calendar")
async def back_calendar(callback: CallbackQuery, state: FSMContext):
    """Возврат к календарю"""
    await callback.answer("⏳ Загружаю календарь...")
    
    today = now_local()
    kb = await create_month_calendar(today.year, today.month)
    
    can_book, current_count = await Database.can_user_book(callback.from_user.id)
    
    await callback.message.edit_text(
        "📍 ШАГ 1 из 3: Выберите дату\n\n"
        "🟢🟡🔴⚫ — статус дня\n\n"
        f"📊 Ваших записей: {current_count}/{MAX_BOOKINGS_PER_USER}",
        reply_markup=kb
    )


@router.message(F.text == "📋 Мои записи")
async def my_bookings(message: Message):
    """Список записей пользователя"""
    user_id = message.from_user.id
    bookings = await Database.get_user_bookings(user_id)
    
    if not bookings:
        await message.answer("📭 У вас нет активных записей", reply_markup=MAIN_MENU)
        return
    
    text = "📋 ВАШИ АКТИВНЫЕ ЗАПИСИ:\n\n"
    keyboard = []
    now = now_local()
    
    for i, (booking_id, date_str, time_str, username, created_at) in enumerate(bookings, 1):
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        booking_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        booking_dt = booking_dt.replace(tzinfo=now.tzinfo)
        
        days_left = (booking_dt.date() - now.date()).days
        day_name = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][date_obj.weekday()]
        
        text += f"{i}. 📅 {date_obj.strftime('%d.%m')} ({day_name}) 🕒 {time_str}"
        
        if days_left == 0:
            text += " — сегодня!\n"
        elif days_left == 1:
            text += " — завтра\n"
        else:
            text += f" — через {days_left} дн.\n"
        
        from aiogram.types import InlineKeyboardButton
        keyboard.append([
            InlineKeyboardButton(
                text=f"❌ Отменить запись #{i}",
                callback_data=f"cancel:{booking_id}"
            )
        ])
    
    from aiogram.types import InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_booking_callback(callback: CallbackQuery, state: FSMContext):
    """Запрос подтверждения отмены"""
    await state.clear()
    
    booking_id = int(callback.data.split(":", 1)[1])
    
    import aiosqlite
    from config import DATABASE_PATH
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT date, time FROM bookings WHERE id=? AND user_id=?",
            (booking_id, callback.from_user.id)
        ) as cursor:
            result = await cursor.fetchone()
    
    if not result:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        return
    
    date_str, time_str = result
    can_cancel, hours_until = await Database.can_cancel_booking(date_str, time_str)
    
    if not can_cancel:
        await callback.answer(
            f"⚠️ До встречи осталось {hours_until:.1f}ч\n"
            f"Отмена возможна за {CANCELLATION_HOURS}ч.\n"
            f"Свяжитесь с администратором.",
            show_alert=True
        )
        return
    
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    confirm_kb = create_cancel_confirmation_keyboard(booking_id)
    
    await callback.message.edit_text(
        f"⚠️ ПОДТВЕРЖДЕНИЕ ОТМЕНЫ\n\n"
        f"📅 {date_obj.strftime('%d.%m.%Y')}\n"
        f"🕒 {time_str}\n\n"
        f"Точно отменить?",
        reply_markup=confirm_kb
    )


@router.callback_query(F.data.startswith("cancel_confirm:"))
async def cancel_confirmed(callback: CallbackQuery, booking_service: BookingService):
    """Подтверждённая отмена"""
    import aiosqlite
    from config import DATABASE_PATH
    
    booking_id = int(callback.data.split(":", 1)[1])
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT date, time FROM bookings WHERE id=? AND user_id=?",
            (booking_id, callback.from_user.id)
        ) as cursor:
            result = await cursor.fetchone()
    
    if not result:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        return
    
    date_str, time_str = result
    success, _ = await booking_service.cancel_booking(date_str, time_str, callback.from_user.id)
    
    if success:
        await callback.message.edit_text(
            f"✅ ЗАПИСЬ ОТМЕНЕНА\n\n"
            f"📅 {date_str}\n"
            f"🕒 {time_str}\n\n"
            f"Вы можете записаться снова в любое время"
        )
        await callback.answer("✅ Отменено")
    else:
        await callback.answer("❌ Ошибка отмены", show_alert=True)


@router.callback_query(F.data == "cancel_decline")
async def cancel_decline(callback: CallbackQuery):
    """Отклонение отмены"""
    await callback.message.edit_text(
        "👍 ЗАПИСЬ СОХРАНЕНА\n\nВы можете посмотреть её в 'Мои записи'"
    )
    await callback.answer("Запись сохранена")


@router.callback_query(F.data.startswith("feedback:"))
async def save_feedback(callback: CallbackQuery):
    """Сохранение отзыва"""
    _, booking_id, rating = callback.data.split(":")
    user_id = callback.from_user.id
    
    await Database.save_feedback(user_id, int(booking_id), int(rating))
    await Database.log_event(user_id, "feedback_given", rating)
    
    await callback.message.edit_text(
        f"💚 Спасибо за отзыв!\n\n"
        f"Ваша оценка: {'⭐' * int(rating)}\n\n"
        f"Будем рады видеть вас снова! 😊"
    )
    await callback.answer("✅ Отзыв сохранен")
