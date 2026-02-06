"""Обработчики для администратора"""
import asyncio
import aiosqlite
import csv
import io
import logging
from datetime import timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext

from keyboards.admin_keyboards import ADMIN_MENU
from keyboards.user_keyboards import MAIN_MENU
from services.analytics_service import AnalyticsService
from utils.helpers import is_admin, now_local
from utils.states import AdminStates
from config import ADMIN_ID, DATABASE_PATH

router = Router()


@router.message(F.text == "/admin")
async def admin_panel(message: Message):
    """Вход в админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    await message.answer(
        "🔐 АДМИН-ПАНЕЛЬ\n\nВыберите действие:",
        reply_markup=ADMIN_MENU
    )


@router.message(F.text == "🔙 Выход из админки")
async def exit_admin(message: Message):
    """Выход из админ-панели"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    await message.answer(
        "👋 Вы вышли из админ-панели",
        reply_markup=MAIN_MENU
    )


@router.message(F.text == "📊 Dashboard")
async def dashboard(message: Message):
    """Дашборд"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    stats = await AnalyticsService.get_dashboard_stats()
    
    await message.answer(
        f"📊 ДАШБОРД\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"📅 Активных записей: {stats['active_bookings']}\n"
        f"❌ Всего отмен: {stats['total_cancelled']}\n"
        f"⭐ Средний рейтинг: {stats['avg_rating']:.1f}/5",
        reply_markup=ADMIN_MENU
    )


@router.message(F.text == "💡 Рекомендации")
async def recommendations(message: Message):
    """AI-рекомендации"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    recs = await AnalyticsService.get_recommendations()
    
    if not recs:
        await message.answer(
            "✅ Всё отлично! Рекомендаций нет.",
            reply_markup=ADMIN_MENU
        )
        return
    
    text = "💡 РЕКОМЕНДАЦИИ:\n\n"
    for rec in recs:
        text += f"{rec['icon']} {rec['title']}\n{rec['text']}\n\n"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "📅 Расписание")
async def schedule_view(message: Message):
    """Просмотр расписания на неделю (ОПТИМИЗИРОВАНО)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    today = now_local()
    end_date = today + timedelta(days=7)
    
    # ОПТИМИЗАЦИЯ: один запрос вместо 7
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            """SELECT date, time, username FROM bookings 
               WHERE date >= ? AND date < ? 
               ORDER BY date, time""",
            (today.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        ) as cursor:
            all_bookings = await cursor.fetchall()
    
    if not all_bookings:
        await message.answer(
            "📅 РАСПИСАНИЕ НА НЕДЕЛЮ\n\n📭 Нет записей на ближайшую неделю",
            reply_markup=ADMIN_MENU
        )
        return
    
    # Группируем по датам
    from collections import defaultdict
    bookings_by_date = defaultdict(list)
    for date_str, time_str, username in all_bookings:
        bookings_by_date[date_str].append((time_str, username))
    
    text = "📅 РАСПИСАНИЕ НА НЕДЕЛЮ\n\n"
    for day_offset in range(7):
        current_date = today + timedelta(days=day_offset)
        date_str = current_date.strftime("%Y-%m-%d")
        
        if date_str in bookings_by_date:
            day_name = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][current_date.weekday()]
            text += f"📆 {current_date.strftime('%d.%m')} ({day_name})\n"
            for time_str, username in bookings_by_date[date_str]:
                text += f"  🕒 {time_str} - @{username}\n"
            text += "\n"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "👥 Клиенты")
async def clients_list(message: Message):
    """Список активных клиентов"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Топ-10 клиентов по количеству записей
        async with db.execute("""
            SELECT user_id, COUNT(*) as total
            FROM analytics 
            WHERE event='booking_created'
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 10
        """) as cursor:
            top_clients = await cursor.fetchall()
        
        # Общее количество
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
    
    text = f"👥 КЛИЕНТЫ\n\n"
    text += f"Всего пользователей: {total_users}\n\n"
    
    if top_clients:
        text += "🏆 ТОП-10 по записям:\n\n"
        for i, (user_id, total) in enumerate(top_clients, 1):
            text += f"{i}. ID {user_id}: {total} записей\n"
    else:
        text += "Пока нет записей"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "⚡ Массовые операции")
async def mass_operations(message: Message):
    """Меню массовых операций"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🗑 Очистить старые записи", callback_data="admin_cleanup_confirm")],
        [InlineKeyboardButton(text="🔒 Заблокировать слоты", callback_data="admin_block_slots")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await message.answer(
        "⚡ МАССОВЫЕ ОПЕРАЦИИ\n\n"
        "⚠️ Будьте осторожны!\n"
        "Выберите действие:",
        reply_markup=kb
    )


@router.message(F.text == "📊 Экспорт данных")
async def export_data(message: Message):
    """Экспорт данных в CSV"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    # Экспорт всех записей
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("""
            SELECT id, date, time, user_id, username, created_at 
            FROM bookings 
            ORDER BY date, time
        """) as cursor:
            bookings = await cursor.fetchall()
    
    # Создаем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Дата', 'Время', 'User ID', 'Username', 'Создано'])
    
    for booking in bookings:
        writer.writerow(booking)
    
    # Отправляем файл
    csv_data = output.getvalue().encode('utf-8-sig')  # BOM для Excel
    file = BufferedInputFile(csv_data, filename="bookings_export.csv")
    
    await message.answer_document(
        file,
        caption=f"📊 Экспорт записей\n\nВсего записей: {len(bookings)}",
        reply_markup=ADMIN_MENU
    )


# === ОБРАБОТЧИКИ МАССОВЫХ ОПЕРАЦИЙ ===

@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.awaiting_broadcast_message)
    
    await callback.message.edit_text(
        "📢 РАССЫЛКА\n\n"
        "Отправьте текст сообщения для рассылки всем пользователям.\n\n"
        "Для отмены отправьте /cancel"
    )
    await callback.answer()


@router.message(AdminStates.awaiting_broadcast_message)
async def broadcast_execute(message: Message, state: FSMContext):
    """Выполнение рассылки (ИСПРАВЛЕНО: добавлена проверка безопасности)"""
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: проверка админа в FSM
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("❌ Нет доступа")
        logging.warning(f"Попытка несанкционированной рассылки от user_id={message.from_user.id}")
        return
    
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена", reply_markup=ADMIN_MENU)
        return
    
    broadcast_text = message.text
    
    # ИСПРАВЛЕНИЕ: исключаем админа из списка получателей
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE user_id != ?",
            (ADMIN_ID,)
        ) as cursor:
            users = await cursor.fetchall()
    
    if not users:
        await state.clear()
        await message.answer(
            "⚠️ Нет пользователей для рассылки",
            reply_markup=ADMIN_MENU
        )
        return
    
    await message.answer(f"📤 Начинаю рассылку {len(users)} пользователям...")
    
    success_count = 0
    fail_count = 0
    
    # ИСПРАВЛЕНИЕ: rate limiting + логирование ошибок
    for (user_id,) in users:
        try:
            await message.bot.send_message(user_id, broadcast_text)
            success_count += 1
            # Rate limiting: 20 сообщений/секунду (защита от бана)
            await asyncio.sleep(0.05)
        except Exception as e:
            # ИСПРАВЛЕНИЕ: логирование конкретных ошибок
            logging.error(f"Broadcast failed for user {user_id}: {e}")
            fail_count += 1
    
    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно: {success_count}\n"
        f"Ошибок: {fail_count}",
        reply_markup=ADMIN_MENU
    )
    
    logging.info(f"Broadcast completed by admin. Success: {success_count}, Failed: {fail_count}")


@router.callback_query(F.data == "admin_cleanup_confirm")
async def cleanup_confirmation(callback: CallbackQuery):
    """Подтверждение очистки старых записей"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    today_str = now_local().strftime("%Y-%m-%d")
    
    # Подсчитываем количество записей для удаления
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM bookings WHERE date < ?",
            (today_str,)
        ) as cursor:
            count_to_delete = (await cursor.fetchone())[0]
    
    if count_to_delete == 0:
        await callback.message.edit_text(
            "✅ Нет старых записей для удаления"
        )
        await callback.answer("Нет данных для очистки")
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Да, удалить {count_to_delete} записей",
            callback_data="admin_cleanup_execute"
        )],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await callback.message.edit_text(
        f"⚠️ ПОДТВЕРЖДЕНИЕ ОЧИСТКИ\n\n"
        f"Будет удалено записей: {count_to_delete}\n"
        f"Дата: раньше {today_str}\n\n"
        f"Это действие необратимо!\n\n"
        f"Продолжить?",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cleanup_execute")
async def cleanup_old_bookings(callback: CallbackQuery):
    """Очистка старых записей (ИСПРАВЛЕНО)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    today_str = now_local().strftime("%Y-%m-%d")
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Удаляем записи старше сегодняшнего дня
        cursor = await db.execute(
            "DELETE FROM bookings WHERE date < ?",
            (today_str,)
        )
        await db.commit()
        # ИСПРАВЛЕНИЕ: правильная обработка rowcount
        deleted_count = cursor.rowcount if cursor.rowcount >= 0 else 0
    
    await callback.message.edit_text(
        f"✅ Очистка завершена\n\n"
        f"Удалено старых записей: {deleted_count}"
    )
    await callback.answer(f"Удалено: {deleted_count}")
    logging.info(f"Admin cleanup: deleted {deleted_count} old bookings")


@router.callback_query(F.data == "admin_block_slots")
async def block_slots_info(callback: CallbackQuery):
    """Информация о блокировке слотов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔒 БЛОКИРОВКА СЛОТОВ\n\n"
        "Эта функция позволяет заблокировать определенные\n"
        "даты и время для записи.\n\n"
        "💡 В разработке: будет доступна в следующей версии"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel_operation(callback: CallbackQuery):
    """Отмена админской операции"""
    await callback.message.delete()
    await callback.answer("Отменено")
