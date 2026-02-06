"""Обработчики бронирования"""

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import (
    CANCELLATION_HOURS,
    DAY_NAMES,
    MAX_BOOKINGS_PER_USER,
    SERVICE_DURATION,
    SERVICE_LOCATION,
    SERVICE_PRICE,
    TIMEZONE,
    WORK_HOURS_END,
    WORK_HOURS_START,
)
from database.queries import Database
from keyboards.user_keyboards import (
    MAIN_MENU,
    create_cancel_confirmation_keyboard,
    create_confirmation_keyboard,
    create_month_calendar,
    create_time_slots,
)
from services.booking_service import BookingService
from services.notification_service import NotificationService
from utils.helpers import now_local

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
            reply_markup=MAIN_MENU,
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
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("cal:"))
async def month_nav(callback: CallbackQuery):
    """Навигация по месяцам"""
    await callback.answer("⏳ Загружаю...")

    _, year_month = callback.data.split(":", 1)
    year, month = map(int, year_month.split("-"))

    kb = await create_month_calendar(year, month)

    try:
        await callback.message.edit_text(
            "📍 ШАГ 1 из 3: Выберите дату\n\n" "🟢🟡🔴⚫ — статус дня", reply_markup=kb
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
    except (ValueError, IndexError) as e:
        await callback.answer("❌ Ошибка: неверная дата", show_alert=True)
        logging.error(f"Invalid date in select_day: {callback.data}, error: {e}")
        await state.clear()
        return

    await callback.answer("⏳ Загружаю слоты...")

    try:
        text, kb = await create_time_slots(date_str, state)
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Error editing message in select_day: {e}")
        await callback.answer("❌ Ошибка отображения")
        await state.clear()


@router.callback_query(F.data.startswith("time:"))
async def confirm_time(callback: CallbackQuery, state: FSMContext):
    """Подтверждение времени с улучшенной валидацией"""
    # ВАЛИДАЦИЯ
    try:
        parts = callback.data.split(":", 2)
        if len(parts) != 3:
            raise ValueError("Неверный формат")
        _, date_str, time_str = parts

        # Проверяем формат даты и времени
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        time_obj = datetime.strptime(time_str, "%H:%M")

        # Проверяем что дата не в прошлом
        booking_dt = datetime.combine(date_obj.date(), time_obj.time())
        booking_dt = booking_dt.replace(tzinfo=TIMEZONE)
        if booking_dt < now_local():
            raise ValueError("Дата в прошлом")

        # Проверяем рабочие часы
        hour = time_obj.hour
        if not (WORK_HOURS_START <= hour < WORK_HOURS_END):
            raise ValueError(
                f"Время вне рабочих часов ({WORK_HOURS_START}-{WORK_HOURS_END})"
            )

    except (ValueError, IndexError) as e:
        await callback.answer("❌ Ошибка: неверные данные", show_alert=True)
        logging.error(
            f"Invalid callback_data in confirm_time: {callback.data}, error: {e}"
        )
        await state.clear()
        return

    day_name = DAY_NAMES[date_obj.weekday()]

    confirm_kb = create_confirmation_keyboard(date_str, time_str)

    try:
        await callback.message.edit_text(
            "📍 ШАГ 3 из 3: Подтверждение\n\n"
            f"📅 {date_obj.strftime('%d.%m.%Y')} ({day_name})\n"
            f"🕒 {time_str}\n\n"
            "✅ Подтвердить?",
            reply_markup=confirm_kb,
        )
    except Exception as e:
        logging.error(f"Error editing message in confirm_time: {e}")
        await callback.answer("❌ Ошибка")


@router.callback_query(F.data == "cancel_booking_flow")
async def cancel_booking_flow(callback: CallbackQuery, state: FSMContext):
    """Отмена процесса бронирования"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Запись отменена\n\nВы вернулись в главное меню", reply_markup=None
    )
    await callback.answer("Действие отменено")


@router.callback_query(F.data.startswith("confirm:"))
async def book_time(
    callback: CallbackQuery,
    booking_service: BookingService,
    notification_service: NotificationService,
):
    """Финальное бронирование с обработкой кодов ошибок"""
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
        logging.error(
            f"Invalid callback_data in book_time: {callback.data}, error: {e}"
        )
        return

    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or "Гость"

    # Проверка can_book внутри create_booking в транзакции!
    success, error_code = await booking_service.create_booking(
        date_str, time_str, user_id, username
    )

    if success:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")

        await callback.message.edit_text(
            "✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!\n\n"
            f"📅 {date_obj.strftime('%d.%m.%Y')} ({DAY_NAMES[date_obj.weekday()]})\n"
            f"🕒 {time_str}\n"
            f"⏱ {SERVICE_DURATION}\n"
            f"📍 {SERVICE_LOCATION}\n"
            f"💰 {SERVICE_PRICE}\n\n"
            "⏰ Напоминание за 24 часа\n"
            "📋 'Мои записи' — посмотреть все"
        )
        await callback.answer("✅ Запись создана!", show_alert=False)

        # Уведомить админа
        try:
            await notification_service.notify_admin_new_booking(
                date_str, time_str, user_id, username
            )
        except Exception as e:
            logging.error(f"Failed to notify admin: {e}")
    else:
        # Обработка различных ошибок
        if error_code == "limit_exceeded":
            await callback.answer(
                f"⚠️ У вас уже {MAX_BOOKINGS_PER_USER} активных записи", show_alert=True
            )
        elif error_code == "slot_taken":
            await callback.answer("❌ Этот слот уже занят!", show_alert=True)
        else:
            await callback.answer("❌ Ошибка создания записи", show_alert=True)

        # Показываем слоты снова
        try:
            text, kb = await create_time_slots(date_str)
            await callback.message.edit_text(
                "❌ Не удалось записать\n\nВыберите другое время:", reply_markup=kb
            )
        except Exception as e:
            logging.error(f"Error showing time slots after failed booking: {e}")


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
        reply_markup=kb,
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

    for i, (booking_id, date_str, time_str, username, created_at) in enumerate(
        bookings, 1
    ):
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        booking_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        booking_dt = booking_dt.replace(tzinfo=TIMEZONE)

        days_left = (booking_dt.date() - now.date()).days
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][date_obj.weekday()]

        text += f"{i}. 📅 {date_obj.strftime('%d.%m')} ({day_name}) 🕒 {time_str}"

        if days_left == 0:
            text += " — сегодня!\n"
        elif days_left == 1:
            text += " — завтра\n"
        else:
            text += f" — через {days_left} дн.\n"

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"❌ Отменить #{i}", callback_data=f"cancel:{booking_id}"
                ),
                InlineKeyboardButton(
                    text=f"🔄 Перенести #{i}", callback_data=f"reschedule:{booking_id}"
                ),
            ]
        )

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

    # Используем Database API вместо прямого запроса
    result = await Database.get_booking_by_id(booking_id, callback.from_user.id)

    if not result:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        return

    date_str, time_str, _ = result
    can_cancel, hours_until = await Database.can_cancel_booking(date_str, time_str)

    if not can_cancel:
        await callback.answer(
            f"⚠️ До встречи осталось {hours_until:.1f}ч\n"
            f"Отмена возможна за {CANCELLATION_HOURS}ч.\n"
            "Свяжитесь с администратором.",
            show_alert=True,
        )
        return

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    confirm_kb = create_cancel_confirmation_keyboard(booking_id)

    await callback.message.edit_text(
        "⚠️ ПОДТВЕРЖДЕНИЕ ОТМЕНЫ\n\n"
        f"📅 {date_obj.strftime('%d.%m.%Y')}\n"
        f"🕒 {time_str}\n\n"
        "Точно отменить?",
        reply_markup=confirm_kb,
    )


@router.callback_query(F.data.startswith("cancel_confirm:"))
async def cancel_confirmed(
    callback: CallbackQuery,
    booking_service: BookingService,
    notification_service: NotificationService,
):
    """Подтверждённая отмена"""
    # ВАЛИДАЦИЯ
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка: неверный ID записи", show_alert=True)
        return

    # Используем Database API вместо прямого запроса
    result = await Database.get_booking_by_id(booking_id, callback.from_user.id)

    if not result:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        return

    date_str, time_str, _ = result
    success, _ = await booking_service.cancel_booking(
        date_str, time_str, callback.from_user.id
    )

    if success:
        await callback.message.edit_text(
            "✅ ЗАПИСЬ ОТМЕНЕНА\n\n"
            f"📅 {date_str}\n"
            f"🕒 {time_str}\n\n"
            "Вы можете записаться снова в любое время"
        )
        await callback.answer("✅ Отменено")

        # Уведомить админа об отмене
        try:
            await notification_service.notify_admin_cancellation(
                date_str, time_str, callback.from_user.id
            )
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
    """Сохранение отзыва с проверкой результата"""
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
        logging.error(
            f"Invalid callback_data in save_feedback: {callback.data}, error: {e}"
        )
        return

    user_id = callback.from_user.id

    # Используем возвращаемое значение
    success = await Database.save_feedback(user_id, booking_id, rating)

    if success:
        await Database.log_event(user_id, "feedback_given", str(rating))
        await callback.message.edit_text(
            "💚 Спасибо за отзыв!\n\n"
            f"Ваша оценка: {'⭐' * rating}\n\n"
            "Будем рады видеть вас снова! 😊"
        )
        await callback.answer("✅ Отзыв сохранен")
    else:
        await callback.answer("❌ Ошибка сохранения отзыва", show_alert=True)


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
        "📅 ПЕРЕНОС ЗАПИСИ\n\n" "Шаг 1: Выберите НОВУЮ дату\n\n" "🟢🟡🔴 — статус дня",
        reply_markup=kb,
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
    booking_id = data.get("reschedule_booking_id")

    if not booking_id:
        await callback.answer("❌ Ошибка: данные потеряны", show_alert=True)
        await state.clear()
        return

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_name = DAY_NAMES[date_obj.weekday()]

    # Создаем клавиатуру подтверждения переноса
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить перенос",
                    callback_data=f"reschedule_confirm:{booking_id}:{date_str}:{time_str}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Выбрать другое время", callback_data=f"day:{date_str}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить перенос", callback_data="cancel_reschedule"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        "📅 ПОДТВЕРЖДЕНИЕ ПЕРЕНОСА\n\n"
        "Перенести на:\n"
        f"📅 {date_obj.strftime('%d.%m.%Y')} ({day_name})\n"
        f"🕒 {time_str}\n\n"
        "Подтвердить?",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("reschedule_confirm:"))
async def execute_reschedule(
    callback: CallbackQuery, state: FSMContext, booking_service: BookingService
):
    """Выполнение переноса через безопасный метод reschedule_booking"""
    try:
        parts = callback.data.split(":", 3)
        booking_id = int(parts[1])
        new_date_str = parts[2]
        new_time_str = parts[3]
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка данных", show_alert=True)
        await state.clear()
        return

    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or "Гость"

    # Получаем старую запись через Database API
    old_booking = await Database.get_booking_by_id(booking_id, user_id)

    if not old_booking:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        await state.clear()
        return

    old_date_str, old_time_str, _ = old_booking

    # Выполняем перенос через новый безопасный метод
    success = await booking_service.reschedule_booking(
        booking_id=booking_id,
        old_date_str=old_date_str,
        old_time_str=old_time_str,
        new_date_str=new_date_str,
        new_time_str=new_time_str,
        user_id=user_id,
        username=username,
    )

    await state.clear()

    if success:
        date_obj = datetime.strptime(new_date_str, "%Y-%m-%d")
        await callback.message.edit_text(
            "✅ ЗАПИСЬ ПЕРЕНЕСЕНА!\n\n"
            f"Старая дата: {old_date_str} {old_time_str}\n\n"
            "Новая дата:\n"
            f"📅 {date_obj.strftime('%d.%m.%Y')} ({DAY_NAMES[date_obj.weekday()]})\n"
            f"🕒 {new_time_str}\n\n"
            "⏰ Напоминание за 24 часа"
        )
        await callback.answer("✅ Перенесено!")
    else:
        await callback.answer("❌ Не удалось перенести запись", show_alert=True)
        # Показываем календарь для повторной попытки
        today = now_local()
        kb = await create_month_calendar(today.year, today.month)
        await callback.message.edit_text(
            "❌ Слот занят или произошла ошибка\n\n" "Выберите другую дату:",
            reply_markup=kb,
        )


@router.callback_query(F.data == "cancel_reschedule")
async def cancel_reschedule_flow(callback: CallbackQuery, state: FSMContext):
    """Отмена процесса переноса"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Перенос отменен\n\n" "Ваша запись осталась без изменений"
    )
    await callback.answer("Перенос отменен")


# === ОБРАБОТЧИКИ ОШИБОК ===


@router.callback_query(F.data == "error")
async def handle_error_callback(callback: CallbackQuery):
    """Обработка ошибочных callback"""
    await callback.answer("⚠️ Произошла ошибка, попробуйте снова", show_alert=True)
    await callback.message.answer(
        "Что-то пошло не так. Вернитесь в главное меню:", reply_markup=MAIN_MENU
    )


@router.callback_query()
async def catch_all_callback(callback: CallbackQuery):
    """Обработчик для всех необработанных callback"""
    logging.warning(
        f"Unhandled callback: {callback.data} from user {callback.from_user.id}"
    )
    await callback.answer("⚠️ Устаревшая кнопка", show_alert=False)
