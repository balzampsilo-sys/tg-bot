"""Обработчики бронирования"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
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
    except Exception as e:
        logging.error(f"Error editing message in month_nav: {e}")
        await callback.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("day:"))
async def select_day(callback: CallbackQuery, state: FSMContext):
    """Выбор дня"""
    # ВАЛИДАЦИЯ
    try:
        date_str = callback.data.split(":", 1)[1]
        # Проверяем что дата валидна
        datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка: неверная дата", show_alert=True)
        return
    
    await callback.answer("⏳ Загружаю слоты...")
    
    text, kb = await create_time_slots(date_str, state)
    
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Error editing message in select_day: {e}")
        await callback.answer("❌ Ошибка отображения")


@router.callback_query(F.data.startswith("time:"))
async def confirm_time(callback: CallbackQuery):
    """Подтверждение времени"""
    # ВАЛИДАЦИЯ
    try:
        parts = callback.data.split(":", 2)
        if len(parts) != 3:
            raise ValueError("Неверный формат")
        _, date_str, time_str = parts
        # Проверяем формат даты и времени
        datetime.strptime(date_str, "%Y-%m-%d")
        datetime.strptime(time_str, "%H:%M")
    except (ValueError, IndexError) as e:
        await callback.answer("❌ Ошибка: неверные данные", show_alert=True)
        logging.error(f"Invalid callback_data in confirm_time: {callback.data}, error: {e}")
        return
    
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_name = DAY_NAMES[date_obj.weekday()]
    
    confirm_kb = create_confirmation_keyboard(date_str, time_str)
    
    try:
        await callback.message.edit_text(
            f"📍 ШАГ 3 из 3: Подтверждение\n\n"
            f"📅 {date_obj.strftime('%d.%m.%Y')} ({day_name})\n"
            f"🕒 {time_str}\n\n"
            f"✅ Подтвердить?",
            reply_markup=confirm_kb
        )
    except Exception as e:
        logging.error(f"Error editing message in confirm_time: {e}")
        await callback.answer("❌ Ошибка")


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
    # ВАЛИДАЦИЯ
    try:
        parts = callback.data.split(":", 2)
        if len(parts) != 3:
            raise ValueError("Неверный формат")
        _, date_str, time_str = parts
        # Проверяем форматы
        datetime.strptime(date_str, "%Y-%m-%d")
        datetime.strptime(time_str, "%H:%M")
    except (ValueError, IndexError) as e:
        await callback.answer("❌ Ошибка: неверные данные", show_alert=True)
        logging.error(f"Invalid callback_data in book_time: {callback.data}, error: {e}")
        return
    
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
        try:
            await notification_service.notify_admin_new_booking(date_str, time_str, user_id, username)
        except Exception as e:
            logging.error(f"Failed to notify admin: {e}")
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
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"❌ Отменить #{i}",
                callback_data=f"cancel:{booking_id}"
            ),
            InlineKeyboardButton(
                text=f"🔄 Перенести #{i}",
                callback_data=f"reschedule:{booking_id}"
            )
        ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_booking_callback(callback: CallbackQuery, state: FSMContext):
    """Запрос подтверждения отмены"""
    await state.clear()
    
    # ВАЛИДАЦИЯ
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка: неверный ID записи", show_alert=True)
        return
    
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
async def cancel_confirmed(callback: CallbackQuery, booking_service: BookingService, notification_service: NotificationService):
    """Подтверждённая отмена"""
    import aiosqlite
    from config import DATABASE_PATH
    
    # ВАЛИДАЦИЯ
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка: неверный ID записи", show_alert=True)
        return
    
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
        
        # Уведомить админа об отмене
        try:
            await notification_service.notify_admin_cancellation(date_str, time_str, callback.from_user.id)
        except Exception as e:
            logging.error(f"Failed to notify admin about cancellation: {e}")
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
    # ВАЛИДАЦИЯ
    try:
        parts = callback.data.split(":")
        if len(parts) != 3:
            raise ValueError("Неверный формат")
        _, booking_id, rating = parts
        booking_id = int(booking_id)
        rating = int(rating)
        
        # Проверяем диапазон рейтинга
        if not (1 <= rating <= 5):
            raise ValueError("Рейтинг вне диапазона")
    except (ValueError, IndexError) as e:
        await callback.answer("❌ Ошибка: неверные данные", show_alert=True)
        logging.error(f"Invalid callback_data in save_feedback: {callback.data}, error: {e}")
        return
    
    user_id = callback.from_user.id
    
    await Database.save_feedback(user_id, booking_id, rating)
    await Database.log_event(user_id, "feedback_given", str(rating))
    
    await callback.message.edit_text(
        f"💚 Спасибо за отзыв!\n\n"
        f"Ваша оценка: {'⭐' * rating}\n\n"
        f"Будем рады видеть вас снова! 😊"
    )
    await callback.answer("✅ Отзыв сохранен")


# === ФУНКЦИИ ПЕРЕНОСА ЗАПИСЕЙ ===

@router.callback_query(F.data.startswith("reschedule:"))
async def start_reschedule(callback: CallbackQuery, state: FSMContext):
    """Начало переноса записи"""
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
    
    # Сохраняем ID записи для переноса
    await state.update_data(reschedule_booking_id=booking_id)
    
    # Показываем календарь
    today = now_local()
    kb = await create_month_calendar(today.year, today.month)
    
    await callback.message.edit_text(
        "📅 ПЕРЕНОС ЗАПИСИ\n\n"
        "Шаг 1: Выберите НОВУЮ дату\n\n"
        "🟢🟡🔴 — статус дня",
        reply_markup=kb
    )
    await callback.answer("Выберите новую дату")


@router.callback_query(F.data.startswith("reschedule_time:"))
async def confirm_reschedule_time(callback: CallbackQuery, state: FSMContext):
    """Подтверждение нового времени при переносе"""
    try:
        _, date_str, time_str = callback.data.split(":", 2)
        datetime.strptime(date_str, "%Y-%m-%d")  # валидация
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
    
    data = await state.get_data()
    booking_id = data.get('reschedule_booking_id')
    
    if not booking_id:
        await callback.answer("❌ Ошибка: данные потеряны", show_alert=True)
        return
    
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_name = DAY_NAMES[date_obj.weekday()]
    
    # Создаем клавиатуру подтверждения переноса
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить перенос", 
            callback_data=f"reschedule_confirm:{booking_id}:{date_str}:{time_str}"
        )],
        [InlineKeyboardButton(text="🔙 Выбрать другое время", callback_data=f"day:{date_str}")],
        [InlineKeyboardButton(text="❌ Отменить перенос", callback_data="cancel_reschedule")]
    ])
    
    await callback.message.edit_text(
        f"📅 ПОДТВЕРЖДЕНИЕ ПЕРЕНОСА\n\n"
        f"Перенести на:\n"
        f"📅 {date_obj.strftime('%d.%m.%Y')} ({day_name})\n"
        f"🕒 {time_str}\n\n"
        f"Подтвердить?",
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("reschedule_confirm:"))
async def execute_reschedule(callback: CallbackQuery, state: FSMContext, booking_service: BookingService):
    """Выполнение переноса"""
    import aiosqlite
    from config import DATABASE_PATH
    
    try:
        parts = callback.data.split(":", 3)
        booking_id = int(parts[1])
        new_date_str = parts[2]
        new_time_str = parts[3]
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Получаем старую запись
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT date, time FROM bookings WHERE id=? AND user_id=?",
            (booking_id, user_id)
        ) as cursor:
            old_booking = await cursor.fetchone()
    
    if not old_booking:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        await state.clear()
        return
    
    old_date_str, old_time_str = old_booking
    
    # Проверяем свободен ли новый слот
    is_free = await Database.is_slot_free(new_date_str, new_time_str)
    if not is_free:
        await callback.answer("❌ Этот слот уже занят!", show_alert=True)
        return
    
    # Выполняем перенос (удаляем старую + создаем новую)
    username = callback.from_user.username or callback.from_user.first_name or "Гость"
    
    # Удаляем старую запись
    success_cancel, _ = await booking_service.cancel_booking(old_date_str, old_time_str, user_id)
    
    if not success_cancel:
        await callback.answer("❌ Ошибка переноса", show_alert=True)
        await state.clear()
        return
    
    # Создаем новую запись
    success_create = await booking_service.create_booking(new_date_str, new_time_str, user_id, username)
    
    if success_create:
        await state.clear()
        
        date_obj = datetime.strptime(new_date_str, "%Y-%m-%d")
        await callback.message.edit_text(
            f"✅ ЗАПИСЬ ПЕРЕНЕСЕНА!\n\n"
            f"Старая дата: {old_date_str} {old_time_str}\n\n"
            f"Новая дата:\n"
            f"📅 {date_obj.strftime('%d.%m.%Y')} ({DAY_NAMES[date_obj.weekday()]})\n"
            f"🕒 {new_time_str}\n\n"
            f"⏰ Напоминание за 24 часа"
        )
        await callback.answer("✅ Перенесено!")
        
        # Логируем событие
        await Database.log_event(user_id, "booking_rescheduled", f"{old_date_str} -> {new_date_str}")
    else:
        await callback.answer("❌ Ошибка создания новой записи", show_alert=True)
        await state.clear()


@router.callback_query(F.data == "cancel_reschedule")
async def cancel_reschedule_flow(callback: CallbackQuery, state: FSMContext):
    """Отмена процесса переноса"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Перенос отменен\n\n"
        "Ваша запись осталась без изменений"
    )
    await callback.answer("Перенос отменен")
